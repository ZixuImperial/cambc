#!/usr/bin/env python3
"""Post-ship live pipeline: fetch a new live version's games, run the standard detectors, write one digest.

usage: python3 -I tools/lab/livepipe.py once [--version vNNN] [--redo] [--no-fetch] [--jobs 4]
       python3 -I tools/lab/livepipe.py status
  (normally run through tools/lab/livepipe.sh --once | --loop [--every 600], which adds nice 10 and a lock)

VERSIONS. A version is live from the "## vNNN live <date>" line that /data/zw4424/st/bq/unrsets.sh writes in
  /data/zw4424/st/bq/unr_TAG.txt; the same log holds its unranked group ids ("group <gid>: ..."). The bot dir comes from
  builder_queue.md's version table (or CLAUDE.md's live line). Targets of a pass: --version, else every live version
  newer than the newest one digested (on an empty state: only the newest live version). A digested version is never
  redone unless --redo.
READY. All matches of its unranked groups are finished (or failed), or 4 h have passed since it went live (then what has
  finished is used). A version without groups waits for 20 ranked games or until it is superseded.
FETCH (platform calls only through tools/lab/platlock.sh; downloads through tools/lab/plat_fetch.sh, which reuses any
  copy on disk via the shared register; downloads are never executed, only whitelisted members are extracted):
  /data/zw4424/plat/unr_vNNN  our unranked groups' games (meta/g_<gid>.json = `match-groups show`), as
                              scout2/py/fetch_unrsets.sh lays it out; group games created after the next version went
                              live are left out (they were played by the next version)
  /data/zw4424/plat/rk_vNNN   our ranked games created while vNNN was live (meta/list_p*.json = `matches list`), as
                              scout2/py/fetch_ranked_since.sh lays it out
  If one of those dirs already exists and was not made by livepipe (meta/livepipe marker), it is read, never written;
  livepipe's own copy goes to lp_unr_vNNN / lp_rk_vNNN. Copies reused from other set dirs are hard-linked in, so each
  set dir is self-contained (replay.py reads x_<id>/ inside the set).
UNION. /data/zw4424/livepipe/vNNN/set: every plat/*_vNNN set (unr_, rk_, lv_, lp_*, others), deduplicated by match id,
  hard links only, opponent names with spaces as '_' (so names pair across sets). The previous version's union is built
  the same way from its sets on disk (no fetch). All detectors read the union.
DETECTORS (each failure is reported in the digest, never fatal): gamerep.py --live, deaths.py, idlewait.py,
  heavyrace.py --all, waitwalk.py (on the worst 5 losses), topsig.py validate --subject us, anomscan.py (ranked anomaly
  classes ours vs opponents, z >= 2 = candidate bug; vNNN_anomaly.md, its candidates on the NEW_DIGESTS line), tempo.py (A6 tempo
  scoreboard vs top-vs-top targets; vNNN_tempo.md), fuel/fault counts
  (statistics' fuelExhausted / botFaults, via gamefeat). heavykeep.py is skipped: it reads a local KEEP run of two
  bots, not live sets.
PAIRING. Every per-game metric is compared with the previous version opponent-paired: screencal.live_paired for the win
  rate and gem share; the same estimator (per common opponent o: d_o = mean_B - mean_A, weight min(n_A, n_B); two-stage
  bootstrap CI over opponents then games) for the other metrics. Per-game values are cached in
  /data/zw4424/livepipe/vNNN/pergame.json.
OUTPUT. condor-work/reports/live/vNNN_digest.md, vNNN_summary.txt (5 lines), detector reports vNNN_*.md, one line
  appended to condor-work/reports/live/NEW_DIGESTS.log. State: /data/zw4424/livepipe/state.json.
"""
import collections
import fcntl
import glob
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = "/homes/zw4424/cambc"
LAB = REPO + "/tools/lab"
sys.path.insert(0, LAB)
CLI = "/data/zw4424/cambc400/bin/cambc400"
PLAT = "/data/zw4424/plat"
BQ = "/data/zw4424/st/bq"
HOME = "/data/zw4424/livepipe"
STATE = HOME + "/state.json"
REPORTS = "/homes/zw4424/condor-work/reports"
LIVE = REPORTS + "/live"
QUEUE = REPORTS + "/builder_queue.md"
ECON = REPORTS + "/econ"
TOPSIG = "/data/zw4424/scout2/py/topsig.py"
TOPSIG_TABLE = REPORTS + "/overnight/topsig_table.tsv"
OUR_ID, US = "285f4eb5-e97f-4ea4-93c5-19e1590a1e5a", "BattleCats"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
MAX_WAIT = 4 * 3600
AMBIG_S = 60  # 1 Nov (Builder, losses_1101pm.md s1): +-1 min uncertain band around each switch in live.txt (the platform switches
#                 within ~30 s of the submit; `submissions list`'s Live: line lags 2-8 min, which filed v378's games as rk_v377)
LIVE_TXT = BQ + "/live.txt"  # one line per switch, newest first: 'vNNN BOT ISO-time ...' (submits and re-activations)
TERMINAL = ("finished", "failed", "error", "cancelled", "canceled", "aborted")
RETRY = re.compile(r"HTTP (409|429|502|503|504)|[Rr]ate.?limit|[Tt]oo [Mm]any|Unavailable|Bad Gateway|Gateway Time")


CHILD = []  # the running child process (its own process group), killed as a group on SIGTERM


def sp_run(cmd, timeout=None, **kw):
    """subprocess.run in a new process group; SIGTERM to livepipe kills the whole group (platlock, timeout, cambc...)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                         start_new_session=True, **kw)
    CHILD.append(p)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(p)
        raise
    finally:
        CHILD.remove(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def kill_group(p):
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(p.pid, sig)
        except OSError:
            return
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            pass


def log(msg):
    print(f"[livepipe {time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def vnum(v):
    return int(v[1:])


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def parse_iso(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"digested": {}, "status": {}}


def save_state(st):
    os.makedirs(HOME, exist_ok=True)
    with open(STATE + ".part", "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    os.replace(STATE + ".part", STATE)


# ------------------------------------------------------------------------------------------------ versions
def versions():
    """{vNNN: dict(live=epoch, tag, log, groups=[gid...], bot)} for every version an unrsets log saw go live."""
    out = {}
    for f in sorted(glob.glob(BQ + "/unr_*.txt")):
        cur = None
        for line in open(f, errors="replace"):
            line = line.rstrip("\n")
            m = re.match(r"## unrsets (v\d{3}) (\S+) start", line)
            if m:
                cur = m.group(1)
                d = out.setdefault(cur, dict(groups=[], tag=m.group(2), log=f))
                continue
            m = re.match(r"## (v\d{3}) live (.+)$", line.strip())
            if m:
                try:
                    t = datetime.strptime(m.group(2), "%a %d %b %H:%M:%S UTC %Y").replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    continue
                d = out.setdefault(m.group(1), dict(groups=[], tag="?", log=f))
                d.setdefault("live", t)
                continue
            m = re.match(r"group (" + UUID + r"):\s*(\S+) rank (\d+) \((\d+)\) (.*)$", line)
            if m and cur:
                d = out[cur]
                if m.group(1) not in [g["gid"] for g in d["groups"]]:
                    d["groups"].append(dict(gid=m.group(1), grp=m.group(2), rank=int(m.group(3)), opp=m.group(5).rsplit(" ", 1)[0]))
    bots = {}
    try:
        for line in open(QUEUE):
            m = re.match(r"\|\s*(v\d{3})\s*\|\s*([^|]*)\|\s*([^|]*)\|", line)
            if m and m.group(3).split():
                bots[m.group(1)] = m.group(3).split()[0]
    except OSError:
        pass
    try:
        m = re.search(r"\*\*bots/(\S+) = (v\d{3})\*\*", open(REPO + "/CLAUDE.md").read())
        if m:
            bots.setdefault(m.group(2), m.group(1))
    except OSError:
        pass
    sw = switches()
    for t, v, bot in sw:  # live.txt: the switch times (and versions an unrsets log never saw)
        d = out.setdefault(v, dict(groups=[], tag="?", log=LIVE_TXT))
        bots.setdefault(v, bot)
    res = {v: d for v, d in out.items() if "live" in d or any(x[1] == v for x in sw)}
    for v, d in res.items():
        d["bot"] = bots.get(v, "?")
        w = [(t, sw[i + 1][0] if i + 1 < len(sw) else None) for i, (t, x, _) in enumerate(sw) if x == v]
        if w:  # every window this version was live (a re-activation opens another one)
            d["windows"], d["live"], d["until"] = w, w[0][0], w[-1][1]
    order = sorted(res, key=lambda v: res[v]["live"])
    for i, v in enumerate(order):  # versions only an unrsets log knows (before live.txt existed): the old single window
        if "windows" not in res[v]:
            res[v]["until"] = res[order[i + 1]]["live"] if i + 1 < len(order) else None
            res[v]["windows"] = [(res[v]["live"], res[v]["until"])]
    return res


def switches():
    """[(epoch, vNNN, bot)] from live.txt, oldest first: each line is the moment that version became live (submit or activate)."""
    out = []
    try:
        for line in open(LIVE_TXT, errors="replace"):
            m = re.match(r"(v\d{3})\s+(\S+)\s+(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", line)
            if m:
                out.append((parse_iso(m.group(3)), m.group(1), m.group(2)))
    except OSError:
        pass
    return sorted(out)


def in_windows(V, t, band_start=AMBIG_S, band_end=AMBIG_S):
    """t (createdAt) inside one of V's live windows, at least the bands away from the window's start and end."""
    return any(s + band_start <= t < (e - band_end if e else float("inf")) for s, e in V["windows"])


# ------------------------------------------------------------------------------------------------ platform
def plat_json(args, out=None, tries=8):
    """One platform call under platlock; the parsed JSON (also written to out), or None."""
    cmd = ["sh", LAB + "/platlock.sh", "timeout", "180", CLI] + args
    for i in range(tries):
        r = sp_run(cmd, cwd=REPO)
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                if out:
                    with open(out + ".part", "w") as f:
                        f.write(r.stdout)
                    os.replace(out + ".part", out)
                return d
            except ValueError:
                pass
        err = (r.stderr + r.stdout)[-300:]
        if not (RETRY.search(err) or r.returncode in (75, 124)):
            log(f"! {' '.join(args[:3])}: rc {r.returncode}: {err.strip()[:200]}")
            return None
        time.sleep(30 * (i + 1))
    return None


def row_of(m):
    us = [t for t in m.get("teams", []) if t.get("name") == US]
    th = [t for t in m.get("teams", []) if t.get("name") != US]
    if not us or not th or us[0].get("result") not in ("win", "loss"):
        return None
    return "%s %s %s %s %s" % (m["matchId"], m["map"], us[0]["side"], us[0]["result"], th[0]["name"].replace(" ", "_"))


def own_dir(prefix, v):
    """Our set dir for this version: plat/PREFIX_vNNN unless someone else made it, then plat/lp_PREFIX_vNNN."""
    d = f"{PLAT}/{prefix}_{v}"
    if os.path.isdir(d) and not os.path.exists(d + "/meta/livepipe"):
        d = f"{PLAT}/lp_{prefix}_{v}"
    os.makedirs(d + "/meta", exist_ok=True)
    open(d + "/meta/livepipe", "a").close()
    return d


def link_in(dest, mid, replay):
    """Make dest/x_<mid>/ and dest/<mid>.json (.zip) exist, hard-linking from the set that holds replay."""
    src = os.path.dirname(os.path.dirname(replay))
    if os.path.realpath(src) == os.path.realpath(dest):
        return
    x = os.path.join(dest, "x_" + mid)
    os.makedirs(x, exist_ok=True)
    for f in glob.glob(os.path.join(os.path.dirname(replay), "*")):
        link(f, os.path.join(x, os.path.basename(f)))
    for ext in (".json", ".zip"):
        link(os.path.join(src, mid + ext), os.path.join(dest, mid + ext))


def link(a, b):
    if os.path.exists(b) or not os.path.isfile(a):
        return
    try:
        os.link(a, b)
    except OSError:
        with open(a, "rb") as fi, open(b + ".part", "wb") as fo:
            fo.write(fi.read())
        os.replace(b + ".part", b)


def fetch_rows(d, rows):
    """matches.txt of d = rows; fetch every game once (plat_fetch: reuse or download, plus the summary), link reused copies."""
    with open(d + "/matches.txt.part", "w") as f:
        f.write("".join(r + "\n" for r in rows))
    os.replace(d + "/matches.txt.part", d + "/matches.txt")
    ids = [r.split()[0] for r in rows]
    with open(d + "/meta/ids.txt", "w") as f:
        f.write("".join(i + "\n" for i in ids))
    if not ids:
        return 0
    env = dict(os.environ, CAMBC_WHO="livepipe")
    r = sp_run(["sh", LAB + "/plat_fetch.sh", d + "/meta/ids.txt", "--dest", d, "--summary"], cwd=REPO, env=env)
    with open(d + "/meta/fetch.log", "a") as f:
        f.write(f"## {iso(time.time())}\n{r.stdout}{r.stderr}")
    paths = [p for p in r.stdout.split("\n") if p.endswith("replay.repl26a")]
    ok = 0
    for p in paths:
        mid = os.path.basename(os.path.dirname(p))[2:]
        if mid in ids:
            link_in(d, mid, p)
            ok += 1
    return ok


def group_status(v, V, fetch):
    """Poll every unranked group of v (match-groups show). -> (n matches, n terminal, rows of finished games, meta)."""
    sdir = f"{HOME}/{v}/groups"
    os.makedirs(sdir, exist_ok=True)
    n = done = 0
    rows, metas = [], {}
    for g in V["groups"]:
        p = f"{sdir}/g_{g['gid']}.json"
        d = None
        if os.path.exists(p):
            try:
                d = json.load(open(p))
            except ValueError:
                d = None
        complete = d is not None and d.get("matches") and all(m.get("status") in TERMINAL for m in d["matches"])
        if not complete and fetch:
            d = plat_json(["match-groups", "show", g["gid"], "--json"], p) or d
        if not d:
            n += 5
            continue
        ms = d.get("matches", [])
        n += max(5, len(ms))
        metas[g["gid"]] = p
        for m in sorted(ms, key=lambda m: m.get("position", 0)):
            if m.get("status") in TERMINAL:
                done += 1
            if m.get("status") != "finished":
                continue
            t = parse_iso(m.get("createdAt", "1970-01-01T00:00:00"))
            if not in_windows(V, t, band_start=-24 * 3600):
                continue  # played by another version (our own groups: no start band)
            r = row_of(m)
            if r:
                rows.append(r)
    return n, done, rows, metas


def ranked_rows(v, V, d):
    """Our ranked games created in [live, until or now): `matches list` pages into d/meta/list_p*.json."""
    lo = min(s for s, _ in V["windows"])
    for f in glob.glob(d + "/meta/list_p*.json"):
        os.remove(f)  # our own listing files: rewritten every fetch
    cur, rows, seen = [], [], set()
    for p in range(1, 11):
        js = plat_json(["matches", "list", "--team", OUR_ID, "--kind", "ranked", "--limit", "100", "--json"] + cur,
                       f"{d}/meta/list_p{p}.json")
        if not js:
            break
        ms = js.get("matches", [])
        for m in ms:
            t = parse_iso(m.get("createdAt", "1970-01-01T00:00:00"))
            if m["matchId"] in seen or not in_windows(V, t) or m.get("status") != "finished":
                continue
            seen.add(m["matchId"])
            r = row_of(m)
            if r:
                rows.append(r)
        nc = js.get("nextCursor")
        if not ms or not nc or min(parse_iso(m["createdAt"]) for m in ms) < lo:
            break
        cur = ["--cursor", nc]
    return rows


# ------------------------------------------------------------------------------------------------ union sets
def read_rows(d):
    out = []
    try:
        for line in open(os.path.join(d, "matches.txt"), errors="replace"):
            x = line.rstrip("\n").split(" ", 4)
            if len(x) == 5 and x[3] in ("win", "loss") and re.fullmatch(UUID, x[0]):
                out.append((x[0], x[1], x[2], x[3], x[4].strip().replace(" ", "_")))
    except OSError:
        pass
    return out


def union(v):
    """Build HOME/v/set from every plat/*_v set; -> (dir, n games, {set: n}, {mid: set})."""
    u = f"{HOME}/{v}/set"
    os.makedirs(u, exist_ok=True)
    src, rows, seen = {}, [], set()
    # 8 Nov (b1570): unranked groups other teams open can be played by an OLD submission; a game whose first draft turn's fuel differs
    # from v's bot on that map (tools/lab/vercheck.py) is left out of v's set and listed in HOME/v/foreign.tsv. Off: touch bq/vercheck_OFF.
    vbot, foreign = None, []
    if not os.path.exists(BQ + "/vercheck_OFF"):
        try:
            vbot = next(ln.split()[1] for ln in open(BQ + "/live.txt") if ln.split()[:1] == [v])
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import vercheck
        except (OSError, StopIteration, IndexError, ImportError):
            vbot = None
    for d in sorted(glob.glob(f"{PLAT}/*_{v}")):
        if not os.path.isdir(d):
            continue
        for mid, mp, side, res, opp in read_rows(d):
            rp = os.path.join(d, "x_" + mid, "replay.repl26a")
            if mid in seen or not os.path.exists(rp):  # the statistics json is optional (lv sets carry none)
                continue
            seen.add(mid)
            if vbot and vercheck.check(mid, os.path.join(d, "x_" + mid), side, mp, vbot, deep=False) == "foreign":
                foreign.append(f"{mid}\t{os.path.basename(d)}\t{mp}\t{opp}")
                continue
            link_in(u, mid, rp)
            rows.append(f"{mid} {mp} {side} {res} {opp}")
            src[mid] = os.path.basename(d)
    with open(u + "/matches.txt.part", "w") as f:
        f.write("".join(r + "\n" for r in rows))
    os.replace(u + "/matches.txt.part", u + "/matches.txt")
    with open(f"{HOME}/{v}/sources.tsv.part", "w") as f:
        f.write("".join(f"{m}\t{s}\n" for m, s in src.items()))
    os.replace(f"{HOME}/{v}/sources.tsv.part", f"{HOME}/{v}/sources.tsv")
    if vbot:
        with open(f"{HOME}/{v}/foreign.tsv", "w") as f:
            f.write("".join(x + "\n" for x in foreign))
        if foreign:
            log(f"{v}: {len(foreign)} game(s) played by another version left out of the set (vercheck; {HOME}/{v}/foreign.tsv)")
    return u, len(rows), collections.Counter(src.values()), src


def prev_version(v, vers):
    """The newest version below v with live games on disk (any plat/*_vMMM set with matches)."""
    have = set()
    for d in glob.glob(f"{PLAT}/*_v[0-9][0-9][0-9]"):
        if os.path.isdir(d) and read_rows(d):
            have.add(d[-4:])
    cands = sorted((x for x in have if vnum(x) < vnum(v)), key=vnum)
    return cands[-1] if cands else None


# ------------------------------------------------------------------------------------------------ detectors
def run_tool(name, cmd, out_file=None, timeout=3600, cwd=REPO):
    """Run one detector (inherits nice 10); -> (ok, note). stdout goes to out_file when given (via .part)."""
    t0 = time.time()
    try:
        r = sp_run(cmd, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout} s"
    if out_file is not None:
        with open(out_file + ".part", "w") as f:
            f.write(r.stdout)
        os.replace(out_file + ".part", out_file)
    note = f"{time.time() - t0:.0f} s"
    if r.returncode != 0:
        return False, f"rc {r.returncode}: {(r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else ''}"
    return True, note


def pergame(v, u, jobs, redo=False):
    """{mid: {opp, win, seat, map, metrics...}} for the union set of v (cached in HOME/v/pergame.json)."""
    cache = f"{HOME}/{v}/pergame.json"
    rows = read_rows(u)
    ids = {r[0] for r in rows}
    if not redo and os.path.exists(cache):
        try:
            c = json.load(open(cache))
            if set(c) == ids:
                return c
        except ValueError:
            pass
    import gamerep
    out = {}
    for mid, mp, side, res, opp in rows:  # every game: result and opponent; statistics-based metrics only with a json
        out[mid] = dict(opp=opp, win=int(res == "win"), seat=side.upper(), map=mp, rounds=None, m={})
    games, _ = gamerep.load_live([u])
    for g in games:
        us, th = g["us"], g["them"]
        tot = us.get("score", 0) + th.get("score", 0)
        out[g["mid"]] = dict(
            opp=g["opp"], win=int(bool(g["win"])), seat=g["seat"], map=g["map"], rounds=g["rounds"],
            gus=us.get("score", 0), gthem=th.get("score", 0),
            m=dict(gem_share=us.get("score", 0) / tot if tot else 0.5, score_gap=us.get("score", 0) - th.get("score", 0),
                   kills=us.get("kills", 0), deaths=us.get("deaths", 0), kd_gap=us.get("kills", 0) - us.get("deaths", 0),
                   captures=us.get("cap_n", 0), cap_gems=us.get("cap_gems", 0), loot_gems=us.get("loot_gems", 0),
                   bag_lost_champ=us.get("bag_lost_champ", 0), gold_r300=us.get("gold_r300", 0),
                   gold_r800=us.get("gold_r800", 0), sub_r500=us.get("sub_r500", 0), dead_share=us.get("dead_share", 0),
                   wards=us.get("wards", 0), rounds=g["rounds"], fuel=us.get("fuel", 0), faults=us.get("faults", 0),
                   opp_fuel=th.get("fuel", 0)))
    # topsig per-game metrics (our side), one replay load per game
    try:
        sys.path.insert(0, os.path.dirname(TOPSIG))
        import topsig
        res, bad = topsig.run([u], "us", jobs)
        for r in res:
            mid = next((m for m in out if m.startswith(r["game"][:36])), None)
            if mid:
                for k, val in r["m"][r["S"]].items():
                    if val is not None:
                        out[mid]["m"]["ts_" + k] = val
    except Exception as e:  # noqa: BLE001
        log(f"topsig per-game failed: {e!r}")
    # idlewait per-game counters (our side)
    try:
        sys.path.insert(0, ECON)
        import idlewait
        from midcontest import specs_of
        from multiprocessing import get_context
        J = specs_of(u)
        # 2 Nov: spawn, not fork: a forked child of a threaded parent hung 2 h in a futex (a lock held across fork)
        with get_context("spawn").Pool(jobs) as p:
            R = p.map(idlewait.one, J, chunksize=2)
        for (sp, _, _), r in zip(J, R):
            mid = os.path.basename(os.path.dirname(sp))[2:]
            if r and mid in out:
                c = r[1]
                out[mid]["m"]["idle_waits"] = c.get("open", 0) + c.get("resp", 0) + c.get("alivegrp", 0)
                out[mid]["m"]["idle_resp"] = c.get("resp", 0)
    except Exception as e:  # noqa: BLE001
        log(f"idlewait per-game failed: {e!r}")
    with open(cache + ".part", "w") as f:
        json.dump(out, f)
    os.replace(cache + ".part", cache)
    return out


# metric, label, better (+1 higher is better, -1 lower, 0 neutral), format
METRICS = [
    ("gem_share", "gem share (score / both)", 1, "{:.3f}"),
    ("score_gap", "score gap (us - them)", 1, "{:+.0f}"),
    ("kills", "kills / game", 1, "{:.2f}"),
    ("deaths", "deaths / game", -1, "{:.2f}"),
    ("kd_gap", "kills - deaths / game", 1, "{:+.2f}"),
    ("captures", "captures / game", 1, "{:.2f}"),
    ("cap_gems", "captured gems / game", 1, "{:.0f}"),
    ("loot_gems", "looted gems / game", 1, "{:.0f}"),
    ("bag_lost_champ", "bag gems lost to champions", -1, "{:.0f}"),
    ("gold_r300", "gold earned by r300", 1, "{:.0f}"),
    ("gold_r800", "gold earned by r800", 1, "{:.0f}"),
    ("sub_r500", "gems tributed by r500", 1, "{:.0f}"),
    ("dead_share", "dead share of champion-rounds", -1, "{:.3f}"),
    ("wards", "wards placed / game", 0, "{:.2f}"),
    ("rounds", "game length (rounds)", 0, "{:.0f}"),
    ("fuel", "fuel exhaustions / game (us)", -1, "{:.2f}"),
    ("faults", "bot faults / game (us)", -1, "{:.3f}"),
    ("idle_waits", "idle waits, body-rounds (idlewait)", -1, "{:.0f}"),
    ("idle_resp", "  of them at a respawning group", -1, "{:.0f}"),
    ("ts_respawn_hit_delay", "respawn hit delay (topsig)", -1, "{:.2f}"),
    ("ts_respawn_both_capture", "respawn both-present capture (topsig)", 1, "{:.3f}"),
    ("ts_centre_first_capture", "centre first capture round (topsig)", -1, "{:.0f}"),
    ("ts_health_share_300", "health share @300 gold (topsig)", 0, "{:.3f}"),
    ("ts_health_share_600", "health share @600 gold (topsig)", 0, "{:.3f}"),
    ("ts_crew_high_tercile", "crew on top-tercile groups (topsig)", 0, "{:.2f}"),
    ("ts_contest_even_win", "even contests won (topsig)", 1, "{:.3f}"),
    ("ts_cancel_strike_rate", "recall-cancel strike rate (topsig)", 1, "{:.3f}"),
    ("ts_own_zone_deaths", "own-zone deaths / game (topsig)", -1, "{:.2f}"),
    ("ts_spawn8_deaths", "deaths within walk 8 of our spawn / game (topsig)", -1, "{:.2f}"),
    ("ts_lock_cancel_reachable", "lock cancels when reachable (topsig)", 1, "{:.3f}"),
    ("ts_postwin_chase", "post-win chase share (topsig)", 0, "{:.3f}"),
    ("ts_postwin_recall", "post-win recall share (topsig)", 0, "{:.3f}"),
    ("ts_gold_per_body_r300", "gold per body by r300 (topsig)", 1, "{:.0f}"),
]


def paired_metric(A, B, key, boot=1000, seed=1):
    """Opponent-paired delta of a per-game metric, B minus A (screencal.live_paired's weights, two-stage bootstrap)."""
    ca, cb = collections.defaultdict(list), collections.defaultdict(list)
    for g in A:
        if key in g["m"]:
            ca[g["opp"]].append(float(g["m"][key]))
    for g in B:
        if key in g["m"]:
            cb[g["opp"]].append(float(g["m"][key]))
    na, nb = sum(map(len, ca.values())), sum(map(len, cb.values()))
    ma = sum(map(sum, ca.values())) / na if na else None
    mb = sum(map(sum, cb.values())) / nb if nb else None
    common = sorted(set(ca) & set(cb))
    out = dict(a=ma, b=mb, na=na, nb=nb, n_common=len(common), delta=None, lo=None, hi=None)
    if not common:
        return out
    cells = [(ca[o], cb[o], min(len(ca[o]), len(cb[o]))) for o in common]

    def est(cs):
        sw = sum(w for _, _, w in cs)
        return sum(w * (sum(b) / len(b) - sum(a) / len(a)) for a, b, w in cs) / sw

    out["delta"] = est(cells)
    rng = random.Random(seed)
    bs = []
    for _ in range(boot):
        pk = [cells[rng.randrange(len(cells))] for _ in cells]
        bs.append(est([([a[rng.randrange(len(a))] for _ in a], [b[rng.randrange(len(b))] for _ in b], w) for a, b, w in pk]))
    bs.sort()
    out["lo"], out["hi"] = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
    return out


# ------------------------------------------------------------------------------------------------ digest
def deaths_rows(csv_path):
    import csv
    try:
        return list(csv.DictReader(open(csv_path)))
    except OSError:
        return []


def first_line_with(path, pat):
    try:
        for line in open(path, errors="replace"):
            if re.search(pat, line):
                return line.strip()
    except OSError:
        pass
    return None


def publish(stage, v):
    """Copy every staged report into LIVE (each via .part + rename in LIVE), digest and summary last."""
    os.makedirs(LIVE, exist_ok=True)
    names = sorted(os.listdir(stage), key=lambda n: (n.endswith("_digest.md") or n.endswith("_summary.txt"), n))
    for n in names:
        a, b = os.path.join(stage, n), os.path.join(LIVE, n)
        shutil.copyfile(a, b + ".part")
        os.replace(b + ".part", b)
    # CLAUDE.md's "Why we lose" file is REPORTS/losses_vNNN.md (31 Oct, Builder): publish gamerep's report there too
    a = os.path.join(stage, f"{v}_losses.md")
    if os.path.exists(a):
        b = os.path.join(REPORTS, f"losses_{v}.md")
        shutil.copyfile(a, b + ".part")
        os.replace(b + ".part", b)


def digest(v, V, vers, args, fetch_note):
    t0 = time.time()
    os.makedirs(LIVE, exist_ok=True)
    u, n, per_set, src = union(v)
    pv = prev_version(v, vers)
    pu, pn, pper, _ = union(pv) if pv else (None, 0, {}, {})
    log(f"{v}: union {n} games {dict(per_set)}; previous {pv}: {pn} games {dict(pper)}")
    if n == 0:
        return None
    # warm the decode cache once for the detectors that read replays
    run_tool("warm", ["python3", "-I", LAB + "/replay.py", "warm", u] + ([pu] if pu else []) + ["--jobs", str(args.jobs)],
             out_file=f"{HOME}/{v}/warm.log", timeout=7200)
    det = collections.OrderedDict()
    stage = f"{HOME}/{v}/stage"
    if os.path.isdir(stage):
        shutil.rmtree(stage)  # our own staging dir from an interrupted pass
    os.makedirs(stage)
    rp = lambda s: f"{stage}/{v}_{s}"  # noqa: E731  (staged; published to LIVE at the end)
    lp = lambda s: f"{LIVE}/{v}_{s}"  # noqa: E731
    det["gamerep"] = run_tool("gamerep", ["python3", "-I", LAB + "/gamerep.py", "--live", u, "--out", rp("losses.md")]) + (rp("losses.md"),)
    det["deaths"] = run_tool("deaths", ["python3", "-I", LAB + "/deaths.py", u, "--out", rp("deaths.md"), "--jobs",
                                        str(args.jobs)]) + (rp("deaths.md"),)
    ok, note = run_tool("idlewait", ["python3", "-I", ECON + "/idlewait.py", u], out_file=rp("idlewait.md"), cwd=HOME)
    det["idlewait"] = (ok, note, rp("idlewait.md"))
    det["heavyrace"] = run_tool("heavyrace", ["python3", "-I", ECON + "/heavyrace.py", u, "--all", "--out",
                                              rp("heavyrace.md")], cwd=HOME) + (rp("heavyrace.md"),)
    if os.path.exists(TOPSIG_TABLE):
        det["topsig"] = run_tool("topsig", ["python3", "-I", TOPSIG, "validate", u, "--subject", "us", "--table",
                                            TOPSIG_TABLE, "--out", rp("topsig.md"), "--jobs", str(args.jobs)],
                                 cwd=HOME) + (rp("topsig.md"),)
    else:
        det["topsig"] = (False, f"no table {TOPSIG_TABLE}", None)
    # per-game metrics, both versions
    G = pergame(v, u, args.jobs, redo=args.redo)
    P = pergame(pv, pu, args.jobs) if pu else {}
    gB = [dict(g, id=k) for k, g in G.items()]
    gA = [dict(g, id=k) for k, g in P.items()]
    nstat = sum(1 for g in gB if "gus" in g), sum(1 for g in gA if "gus" in g)
    import screencal
    wr = screencal.live_paired(gA, gB, boot=2000) if gA else None
    # worst 5 losses (gamerep's order: score gap), their first death, waitwalk on each
    losses = sorted((g for g in gB if not g["win"]), key=lambda g: (g.get("gus", 0) - g.get("gthem", 0), g["id"]))[:5]
    drows = deaths_rows(rp("deaths.csv"))
    ww = []
    for g in losses:
        seat = g["seat"]
        ok, note = run_tool("waitwalk", ["python3", "-I", ECON + "/waitwalk.py", os.path.join(u, "x_" + g["id"], "replay.repl26a"),
                                         "--us", seat], out_file=f"{HOME}/{v}/waitwalk_{g['id'][:8]}.txt", cwd=HOME, timeout=900)
        txt = open(f"{HOME}/{v}/waitwalk_{g['id'][:8]}.txt").read() if ok else ""
        ww.append((g, ok, note, txt))
    with open(rp("waitwalk.md"), "w") as f:
        f.write(f"# waitwalk.py on {v}'s worst 5 losses\n\n")
        for g, ok, note, txt in ww:
            f.write(f"## {g['id']} {g['map']} vs {g['opp']} (seat {g['seat']})\n\n```\n{txt if ok else note}\n```\n\n")
    det["waitwalk"] = (all(x[1] for x in ww) if ww else False, f"{sum(x[1] for x in ww)}/{len(ww)} games" if ww else "no losses",
                       rp("waitwalk.md"))
    det["heavykeep"] = (None, "skipped: it reads a local KEEP run of two bots (KEEPDIR CAND BASE), not live sets", None)
    # anomaly scan (tools/lab/anomscan.py, 30 Oct): ranked anomaly classes, ours vs opponents per game, z, worst games
    det["anomaly"] = run_tool("anomscan", ["python3", "-I", LAB + "/anomscan.py", u, "--out", rp("anomaly.md"), "--jobs",
                                           str(args.jobs)], cwd=REPO, timeout=1800) + (rp("anomaly.md"),)
    try:
        anom = next((ln.strip() for ln in open(rp("anomaly.md")) if ln.startswith("CANDIDATE BUGS")), "")
    except OSError:
        anom = ""
    # tempo scoreboard (tools/lab/tempo.py, A6 30 Oct): ours vs opponents vs the top-vs-top tempo targets
    det["tempo"] = run_tool("tempo", ["python3", "-I", LAB + "/tempo.py", u, "--out", rp("tempo.md"), "--jobs", str(args.jobs)],
                            cwd=REPO, timeout=1800) + (rp("tempo.md"),)
    # fuel / faults
    fuel = sum(g["m"].get("fuel", 0) for g in gB)
    fault = sum(g["m"].get("faults", 0) for g in gB)
    fuel_g = sum(1 for g in gB if g["m"].get("fuel", 0))
    fault_g = sum(1 for g in gB if g["m"].get("faults", 0))
    pfuel = sum(g["m"].get("fuel", 0) for g in gA)
    pfault = sum(g["m"].get("faults", 0) for g in gA)
    # ---------------------------------------------------------------- write
    nw = sum(g["win"] for g in gB)
    L = [f"# Live digest {v} ({V.get('bot', '?')}) vs {pv or '-'}", "",
         f"Generated {iso(time.time())}Z by tools/lab/livepipe.py ({time.time() - t0:.0f} s). {v} live since "
         f"{iso(V['live'])}Z" + (f", superseded {iso(V['until'])}Z" if V.get("until") else ", still live") + ".", "",
         f"- Games: {v} {n} ({nw} wins, {nw / n:.3f}) from {', '.join(f'{k} {c}' for k, c in sorted(per_set.items()))}; "
         f"union set {u}.",
         f"- Previous: {pv} {pn} games from {', '.join(f'{k} {c}' for k, c in sorted(pper.items()))}" if pv else "- Previous: none on disk",
         f"- Fetch: {fetch_note}",
         f"- Statistics files (needed by the gamefeat metrics, gem share, fuel/faults): {v} {nstat[0]} of {n}, {pv} {nstat[1]} of {pn}; "
         "replay-based metrics (idlewait, topsig) and the win rate use every game.", ""]
    if wr:
        L += ["## Headline (opponent-paired, screencal.live_paired, B = " + v + " minus A = " + str(pv) + ")", ""]
        if wr["delta"] is not None:
            L.append(f"- **Win rate: paired delta {wr['delta']:+.3f} [95% CI {wr['lo']:+.3f}, {wr['hi']:+.3f}], SE {wr['se']:.3f}, "
                     f"{wr['n_common']} common opponents ({wr['games_common'][0]} / {wr['games_common'][1]} games).**")
        else:
            L.append("- Win rate: no common opponent with the previous version.")
        if wr["raw"] is not None:
            L.append(f"- Unmatched win rate {pn and sum(g['win'] for g in gA) / len(gA):.3f} -> {nw / n:.3f} "
                     f"(delta {wr['raw']:+.3f}, SE {wr['raw_se']:.3f}).")
        if wr["gs_delta"] is not None:
            L.append(f"- Gem share (score): paired delta {wr['gs_delta']:+.3f}, SE {wr['gs_se']:.3f} ({wr['gs_n']} opponents).")
        L.append("")
    L += [f"## Metrics vs {pv} (per game, our side; paired = opponent-paired delta with 95% two-stage bootstrap CI)", "",
          "| metric | " + v + " (n) | " + str(pv) + " (n) | paired delta [95% CI] | common opp | note |", "|---|---|---|---|---|---|"]
    flags = []
    for key, label, better, fm in METRICS:
        r = paired_metric(gA, gB, key)
        if r["b"] is None and r["a"] is None:
            continue
        fa = "-" if r["a"] is None else fm.format(r["a"]) + f" ({r['na']})"
        fb = "-" if r["b"] is None else fm.format(r["b"]) + f" ({r['nb']})"
        if r["delta"] is None:
            fd, note = "-", ""
        else:
            fd = f"{r['delta']:+.3g} [{r['lo']:+.3g}, {r['hi']:+.3g}]"
            note = ""
            if r["lo"] > 0 or r["hi"] < 0:
                good = better and ((r["lo"] > 0) == (better > 0))
                note = "**better**" if good else ("**worse**" if better else "**moved**")
                flags.append(f"{label.strip()} {fd} ({'better' if good else 'worse' if better else 'moved'})")
        L.append(f"| {label} | {fb} | {fa} | {fd} | {r['n_common']} | {note} |")
    L += ["", f"Fuel / faults ({v}, games with statistics): {fuel} fuel exhaustions in {fuel_g} of {nstat[0]} games, {fault} bot faults in {fault_g} games "
          f"({pv}: {pfuel} exhaustions, {pfault} faults in {nstat[1]} games with statistics).", ""]
    L += ["## Per opponent (win rate)", "", "| opponent | " + str(pv) + " | " + v + " |", "|---|---|---|"]
    oa, ob = collections.defaultdict(list), collections.defaultdict(list)
    for g in gA:
        oa[g["opp"]].append(g["win"])
    for g in gB:
        ob[g["opp"]].append(g["win"])
    for o in sorted(ob, key=lambda o: (-len(ob[o]), o)):
        a = f"{sum(oa[o])}/{len(oa[o])}" if oa.get(o) else "-"
        L.append(f"| {o} | {a} | {sum(ob[o])}/{len(ob[o])} |")
    L += ["", "## Worst 5 losses (score gap; open with replay.py)", ""]
    for g in losses:
        mid, lab = g["id"], None
        ds = sorted((r for r in drows if r.get("game") and (r["game"] == mid or (len(r["game"]) < 36 and mid.startswith(r["game"]) and
                     sum(1 for g2 in losses if g2["id"].startswith(r["game"])) == 1))), key=lambda r: int(r["round"]))  # 9 Nov: full id; a short id only when it names one loss
        first = ds[0] if ds else None
        L.append(f"- `{mid}` {g['map']} vs {g['opp']}, seat {g['seat']}, {g.get('gus', '?')}-{g.get('gthem', '?')} in {g.get('rounds') or '?'} rounds, "
                 f"deaths {g['m'].get('deaths', '?')}, kills {g['m'].get('kills', '?')}, set {src.get(mid, '?')}")
        if first:
            lab = first["victim"].split(":")[0]
            r0 = int(first["round"])
            L.append(f"  - first death r{r0}: {first['victim']} by {first.get('killer', '?')} ({first.get('zone', '?')})")
            L.append(f"  - `python3 -I tools/lab/replay.py track {mid} --champ {lab} --from {max(0, r0 - 40)} --to {r0}`")
        else:
            lab = "1" if g["seat"] == "A" else "K"
            L.append(f"  - `python3 -I tools/lab/replay.py track {mid} --champ {lab}`")
        L.append(f"  - `python3 -I tools/lab/replay.py moments {mid}`; waitwalk: {LIVE}/{v}_waitwalk.md")
    L += ["", "## Detectors", "", "| detector | status | report |", "|---|---|---|"]
    for k, (ok, note, path) in det.items():
        st = "skipped" if ok is None else ("ok" if ok else "FAILED")
        L.append(f"| {k} | {st} ({note}) | {path or '-'} |")
    # headline lines from the detector reports
    L += ["", "## Detector headlines", ""]
    for pat, path in ((r"^\*\*CALIBRATION|^\*\*HELD-OUT", rp("topsig.md")), (r"deaths in|^Deaths", rp("deaths.md")),
                      (r"^\| us in losses|^\| us in wins", rp("idlewait.md"))):
        try:
            for line in open(path, errors="replace"):
                if re.search(pat, line):
                    L.append(f"- {os.path.basename(path)}: {line.strip()[:300]}")
        except OSError:
            pass
    L.append("")
    with open(rp("digest.md"), "w") as f:
        f.write("\n".join(L).replace(stage + "/", LIVE + "/") + "\n")
    path = lp("digest.md")
    # summary (5 lines) + log line
    if wr and wr["delta"] is not None:
        head = (f"win {nw}/{n} ({nw / n:.3f}); paired vs {pv} {wr['delta']:+.3f} [{wr['lo']:+.3f}, {wr['hi']:+.3f}] "
                f"over {wr['n_common']} common opponents")
    else:
        head = f"win {nw}/{n} ({nw / n:.3f}); no common opponent with {pv}"
    failed = [k for k, (ok, _, _) in det.items() if ok is False]
    S = [f"{v} ({V.get('bot', '?')}) live digest {iso(time.time())}Z: {n} games ({', '.join(f'{k} {c}' for k, c in sorted(per_set.items()))})",
         head,
         f"CI-clear metric moves vs {pv}: " + ("; ".join(flags[:6]) if flags else "none"),
         f"fuel {fuel} in {fuel_g} games, faults {fault} in {fault_g} games ({pv}: {pfuel} / {pfault}); worst loss: "
         + (f"{losses[0]['id'][:8]} {losses[0]['map']} vs {losses[0]['opp']} {losses[0].get('gus', '?')}-{losses[0].get('gthem', '?')}" if losses else "-"),
         f"digest {path}" + (f"; FAILED detectors: {', '.join(failed)}" if failed else "")]
    with open(rp("summary.txt"), "w") as f:
        f.write("\n".join(S) + "\n")
    publish(stage, v)
    with open(LIVE + "/NEW_DIGESTS.log", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(f"{iso(time.time())}Z {v} {V.get('bot', '?')} | {head} | {path}"
                + (f" | anomalies: {anom[len('CANDIDATE BUGS '):]}" if anom else "") + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    return dict(path=path, n=n, prev=pv, summary=S, failed=failed)


# ------------------------------------------------------------------------------------------------ pass
def one_pass(args):
    st = load_state()
    vers = versions()
    if not vers:
        log("no live version found in the unrsets logs")
        return 0
    order = sorted(vers, key=vnum)
    regather = set()
    if args.version:
        if args.version not in vers:
            sys.exit(f"{args.version} has no '## {args.version} live' line in {BQ}/unr_*.txt")
        targets = [args.version]
    else:
        done = [v for v in st["digested"]]
        last = max(done, key=vnum) if done else None
        targets = [v for v in order if last and vnum(v) > vnum(last)][::-1] if last else [order[-1]]  # newest first
        # unrhook.py (owner 4 Nov ~22:15Z) keeps adding groups to the live version after its first digest: while the newest
        # version is live, redo its digest when its logs list more groups than that digest covered (once they are terminal)
        nv = order[-1]
        if nv in st["digested"] and nv not in targets and not vers[nv].get("until"):
            had = st["digested"][nv].get("groups")
            if had is None:
                had = len(glob.glob(f"{PLAT}/*unr_{nv}/meta/g_*.json"))
            if len(vers[nv]["groups"]) > had:
                targets.insert(0, nv)
                regather.add(nv)
    if not args.version:
        ranked_catchup(vers, order)
    for v in targets:
        if st["status"].get(v, {}).get("errors", 0) >= 3 and not args.redo:
            log(f"{v}: 3 failed digests ({st['status'][v].get('last_error')}); fix and run --once --version {v} --redo")
            continue
        if v in st["digested"] and not args.redo and v not in regather:
            log(f"{v}: already digested ({st['digested'][v]['path']}); --redo to redo")
            continue
        V = vers[v]
        now = time.time()
        fetch = not args.no_fetch
        n, done_n, urows, metas = group_status(v, V, fetch) if V["groups"] else (0, 0, [], {})
        superseded = bool(V.get("until"))
        waited = now - V["live"]
        if V["groups"]:
            ready = (done_n >= n and n > 0) or waited > MAX_WAIT
        else:
            ready = superseded or waited > MAX_WAIT
        st["status"][v] = dict(checked=iso(now), groups=len(V["groups"]), matches=n, terminal=done_n, ready=ready)
        save_state(st)
        if not ready:
            log(f"{v}: waiting ({done_n}/{n} group matches terminal, {waited / 60:.0f} min since live)")
            continue
        note = []
        if fetch:
            if urows:
                d = own_dir("unr", v)
                for gid, p in metas.items():  # the latest `match-groups show` of each group, as fetch_unrsets.sh keeps it
                    q = f"{d}/meta/g_{gid}.json"
                    with open(p, "rb") as fi, open(q + ".part", "wb") as fo:
                        fo.write(fi.read())
                    os.replace(q + ".part", q)
                k = fetch_rows(d, urows)
                note.append(f"{os.path.basename(d)} {k}/{len(urows)} games")
            d = own_dir("rk", v)
            rr = ranked_rows(v, V, d)
            k = fetch_rows(d, rr)
            note.append(f"{os.path.basename(d)} {k}/{len(rr)} ranked games")
            log(f"{v}: fetched {'; '.join(note)}")
        else:
            note.append("skipped (--no-fetch)")
        try:
            res = digest(v, V, vers, args, "; ".join(note))
        except Exception as e:  # noqa: BLE001  (a bug in one detector path must not crash-loop the whole pipeline)
            import traceback
            traceback.print_exc()
            st = load_state()
            s_ = st["status"].setdefault(v, {})
            s_["errors"] = s_.get("errors", 0) + 1
            s_["last_error"] = repr(e)[:300]
            save_state(st)
            continue
        if not res:
            log(f"{v}: no games on disk; not digested")
            continue
        st = load_state()
        st["digested"][v] = dict(path=res["path"], at=iso(time.time()), games=res["n"], prev=res["prev"], failed=res["failed"],
                                 groups=len(V["groups"]))
        save_state(st)
        print("\n".join(res["summary"]))
    teamdata()
    return 0


def teamdata():
    """4 Nov (owner via the Builder): grow the per-opponent ledgers (/data/zw4424/st/teams) after every pass; incremental (a set
    whose listing didn't change is skipped), never fatal; then refresh the international report pages."""
    for cmd in (["update", "--quiet"], ["report", "--intl"]):
        try:
            r = sp_run([sys.executable, "-I", LAB + "/teamdata.py", *cmd], cwd=REPO, timeout=1200)
            out = (r.stdout + r.stderr).strip()
            if out and (r.returncode or cmd[0] == "update"):
                log(f"teamdata {cmd[0]}: rc {r.returncode}: {out.splitlines()[-1][:200]}")
        except Exception as e:  # noqa: BLE001
            log(f"teamdata {cmd[0]}: {e!r}"[:200])


def ranked_catchup(vers, order, last_n=30):
    """2 Nov: digests go newest first and skip what they've passed, and with ships minutes apart (v423-v427) some versions never got an rk_ set.
    Every pass: each of the last last_n versions whose live window has ended gets its ranked set fetched once (refile's ranked step)."""
    for v in order[-last_n:]:
        V = vers[v]
        d = own_dir("rk", v)
        if not V.get("until") or time.time() - V["until"] < 600 or os.path.exists(d + "/meta/catchup_done"):
            continue
        try:
            rows = ranked_rows(v, V, d)
            k = fetch_rows(d, rows)
            os.makedirs(d + "/meta", exist_ok=True)
            open(d + "/meta/catchup_done", "w").write(f"{iso(time.time())} {len(rows)} rows, {k} on disk\n")
            log(f"{v}: ranked catch-up: {len(rows)} games, {k} on disk ({d})")
        except Exception as e:  # noqa: BLE001  the digest pass goes on
            log(f"{v}: ranked catch-up failed: {e!r}")


def refile(args):
    """refile [--version vNNN]: re-attribute the ranked (rk_) and unranked (unr_) sets of every version with live.txt windows
    (1 Nov fix), no digest. Copy, never delete: each set's matches.txt goes to meta/matches.txt.pre_refile_<time> first; game
    files already on disk stay; games now attributed to the set are fetched (plat_fetch, platlock). Prints old -> new counts."""
    vers = versions()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    targets = [args.version] if args.version else [v for v in sorted(vers, key=vnum) if any(x[1] == v for x in switches())]
    for v in targets:
        V = vers[v]
        out = []
        for prefix in ("rk", "unr"):
            d = own_dir(prefix, v)
            old = {r[0] for r in read_rows(d)}
            if prefix == "rk":
                rows = ranked_rows(v, V, d)
            else:
                rows = group_status(v, V, True)[2] if V["groups"] else []
            new = {r.split()[0] for r in rows}
            if new == old:
                out.append(f"{os.path.basename(d)} unchanged {len(old)}")
                continue
            if os.path.exists(d + "/matches.txt"):
                with open(d + "/matches.txt", "rb") as fi, open(f"{d}/meta/matches.txt.pre_refile_{stamp}", "wb") as fo:
                    fo.write(fi.read())
            k = fetch_rows(d, rows)
            out.append(f"{os.path.basename(d)} {len(old)} -> {len(new)} (+{len(new - old)} -{len(old - new)}; {k} on disk)")
        log(f"refile {v}: " + "; ".join(out))
        print(f"{v}: " + "; ".join(out))
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["once", "status", "refile"])
    ap.add_argument("--version")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    if args.cmd == "status":
        st = load_state()
        vers = versions()
        for v in sorted(vers, key=vnum)[-6:]:
            print(v, vers[v].get("bot"), iso(vers[v]["live"]), "groups", len(vers[v]["groups"]),
                  "digested" if v in st["digested"] else st["status"].get(v, "not checked"))
        return 0
    cur = os.nice(0)
    if cur < 10:
        os.nice(10 - cur)  # children (detectors, plat_fetch, decoders) inherit nice 10

    def term(signum, frame):
        log(f"signal {signum}: abandoning the current step (child group killed; outputs are .part/staged, state unchanged)")
        for p in list(CHILD):
            kill_group(p)
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, term)
    os.makedirs(HOME, exist_ok=True)
    with open(HOME + "/.lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("another livepipe pass is running; exiting")
            return 0
        if args.cmd == "refile":
            return refile(args)
        rc = one_pass(args)
    # hourly: refresh the game index (tools/lab/gameindex.py; incremental, ~1 s); never fails the pass
    try:
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gameindex.py"),
                        "build", "--if-older", "3300", "--quiet"], timeout=600, stdin=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        log(f"gameindex refresh failed: {e}")
    # hourly: store newly indexed games for census readers (tools/lab/gamesum.py; newest 50 versions, 2 workers); failures only logged
    try:
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamesum.py"),
                            "build", "--since", "-50", "--jobs", "2", "--if-older", "3300", "--quiet"], timeout=1500,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode:
            log(f"gamesum refresh failed rc={r.returncode}: {(r.stdout + r.stderr)[-300:]}")
    except Exception as e:  # noqa: BLE001
        log(f"gamesum refresh failed: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
