#!/usr/bin/env python3
"""ladderclimb: climb the ladder one team at a time with unranked groups, stopping at every loss until a fix beats it (Tool builder 2,
8 Nov; owner: "slowly sweep the players starting from 21 upwards till we reach our rank and stop anytime there is a single match where
we lose, then get the analysers to analyse the fix with priority as these are critical, then compile the maps we lost on and play them
again ... once we 5-0 on all the maps, then we move onto the next ranked person").

usage: python3 -I tools/lab/ladderclimb.py status
       python3 -I tools/lab/ladderclimb.py step [--dry]          one pass of the state machine (below)
       python3 -I tools/lab/ladderclimb.py loop [--every 600]     a step every N seconds (a daemon)
       python3 -I tools/lab/ladderclimb.py reset [--rank 21]      start again at that ladder rank
       python3 -I tools/lab/ladderclimb.py losses                 the current team's lost maps: READY (fix live, or no-fix) or wait, and why
       python3 -I tools/lab/ladderclimb.py fix MATCH FIX          link a fix to a lost game (FIX: FLAG=V, vNNN or a bot name; replaycheck's
                                                                  links for that match count too)
       python3 -I tools/lab/ladderclimb.py nofix MATCH ["WHY"]    the analysts' call: no fix possible; it leaves the batch and stops blocking
       python3 -I tools/lab/ladderclimb.py replay MATCH ["WHY"]   ready AND kept in the batch: re-play it on the current live anyway (8 Nov,
                                                                  Builder: a closed fix, but later ships may cover the loss)
State machine (state /data/zw4424/st/climb/state.json, log /data/zw4424/st/climb/log):
  PROBE   the target team on EVERY published map (owner 8 Nov: "play against them on all maps, so we can see where our flaws are"):
          one game a map, random side, in groups of 5 (CLIMB_FLIGHT groups in flight, quota use under CLIMB_QUOTA_CAP). All won -> next
          team. Any loss -> RETEST: every lost game is flagged critical (critgame.py flag ... --prio high; identical games link).
  WAITFIX (owner 8 Nov ~04:30Z: "preserve unranked quota by batching the losses ... make sure we have all the upgrades in the batch before
          testing again"): the team's lost maps form one batch; each needs a linked fix (ladderclimb fix, or replaycheck's link for that
          match) that is in the live bot, or an analyst's no-fix mark. Until every loss is ready the climb PAUSES on that team and uses
          no quota. Then RETEST plays the batch once (no-fix maps left out). All won -> next team; any loss -> flagged critical, new batch.
  NEXT    the next team of the FROZEN order (owner 8 Nov: "get this time frame of rating, otherwise we can repeat players as the ladder
          is unstable"): reset snapshots the ladder once (climb/ladder_<stamp>.json) and lists every team from the start rank up to just
          below us, by teamId; the climb walks that list in order, so a team is never repeated or skipped when ranks move. DONE at its end.
Off switch: touch /data/zw4424/st/climb/OFF. Platform calls through platlock.sh (unranked quota shared; one group in flight at a time).
"""
import json
import os
import random
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
DIR = os.environ.get("CLIMB_DIR", "/data/zw4424/st/climb")
SLICE = os.environ.get("CLIMB_SLICE", "")
NO_WAIT = os.environ.get("CLIMB_NO_WAIT") == "1"  # owner 8 Nov: "use the quota we have to its full effect": a second climb (CLIMB_DIR=climb_side) plays the teams ahead while the
# main one waits on fixes: losses are flagged critical for the analysts, it never waits, and it starts the order again at the end
TEAMS = [x for x in os.environ.get("CLIMB_TEAMS", "").split(",") if x]  # 9 Nov (owner via Coordinator: "more data ... especially of the top 3 teams"):
# a lane for these team ids only (ranks above us included), in this order
FULL = os.environ.get("CLIMB_FULL") == "1"  # 9 Nov: every new live version plays every map again (losses keep their side; a loss the live bot
# would play identically is skipped and stays unresolved), not only the lost maps
SAMPLE = int(os.environ.get("CLIMB_SAMPLE", "40"))  # fetchq: per version, team and result, this many games fetched first (Combat 9 Nov)
FLAG_BG = os.environ.get("CLIMB_FLAG_BG") == "1"  # 9 Nov: losses are flagged by a detached flagq run, so a 60-loss probe does not hold the lane
SETNAME = os.environ.get("CLIMB_SET", "")
# 13 Nov (VV, owner's win-inspection task): a lane with no CLIMB_SET kept no win replays (1,607 side-lane wins since v850, 0 replays). Such a lane
# now adds 1 in CLIMB_WIN_SAMPLE (8) of its wins, by sha1 of the match id (no outcome selection), to the shared set sidewin_<version>; one fetchq at
# a time across lanes (lock in /data/zw4424/plat). CLIMB_WIN_SAMPLE=0 turns it off. The platform JSON has no margin or end round, so thin wins
# can't be picked before the download; gameindex reads them from the replays.
WIN_SAMPLE = 0 if SETNAME else int(os.environ.get("CLIMB_WIN_SAMPLE", "8"))
if WIN_SAMPLE:
    SETNAME = "sidewin"  # 9 Nov (Econ, Combat): every game's replay, wins too, in /data/zw4424/plat/<SETNAME>_<version>/ (matches.txt:
# id map seat result team, the rk_/unr_ layout readmany reads), fetched by one detached `fetchq` run, losses first
STATE = DIR + "/state.json"
LOG = DIR + "/log"
CLI = "/data/zw4424/cambc400/bin/cambc400"
sys.path.insert(0, REPO + "/tools/lab")
from teams import US, US_ID  # noqa: E402



def link_copy(src, dst):
    """10 Nov (Deep: 40 top-3 replays of top3_v682 were gone): the set's own copy of a replay dir, as hard links (same disk, no extra space),
    so critgame's crit_auto prune can't take it away; a symlink only if hard links fail (another file system)."""
    try:
        os.makedirs(dst + ".tmp", exist_ok=True)
        for q in os.listdir(src):
            p = os.path.join(src, q)
            if os.path.isfile(p):
                os.link(p, os.path.join(dst + ".tmp", q))
        os.replace(dst + ".tmp", dst)
    except OSError:
        import shutil
        shutil.rmtree(dst + ".tmp", ignore_errors=True)
        if not os.path.lexists(dst):
            os.symlink(src, dst)

def plat(args, timeout=180):
    r = subprocess.run(["sh", "tools/lab/platlock.sh", CLI] + args, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def log(msg):
    os.makedirs(DIR, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return dict(rank=21, phase="NEXT", target=None, lost=[], tried_version=None, gid=None, history=[])


def save(st):
    os.makedirs(DIR, exist_ok=True)
    tmp = f"{STATE}.{os.getpid()}"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def ladder():
    t = json.loads(plat(["ladder", "--page", "1", "--limit", "100", "--json"]))["teams"]
    me = next(x for x in t if x.get("teamId") == US_ID or x.get("name") == US)
    return t, me


def version_at(mid):
    """13 Nov (Aggression: 01a1d3c5-...-7fd6 was created 07:18:18Z, 4 min after v877 went up at 07:14:28Z, but its group carried v876: a lane's
    step reads active_version() once and then queues groups for minutes behind platlock): the version live when the MATCH was created, from its
    UUIDv7 time and bq/live.txt's ship times; None when the id or live.txt can't tell."""
    try:
        import uuid
        t = (uuid.UUID(mid).int >> 80) / 1000.0
        best = None
        for ln in open("/data/zw4424/st/bq/live.txt"):
            p_ = ln.split()
            if len(p_) >= 3 and re.match(r"v\d+$", p_[0]):
                import calendar
                ts = calendar.timegm(time.strptime(p_[2][:19], "%Y-%m-%dT%H:%M:%S"))
                if ts <= t and (best is None or ts > best[0]):
                    best = (ts, p_[0])
        return best[1] if best else None
    except (ValueError, OSError, TypeError):
        return None


def active_version():
    """the version the platform plays now (submissions list 'active'), e.g. 'v611'"""
    try:
        return "v%d" % json.loads(plat(["submissions", "list", "--json"]))["active"]["version"]
    except (ValueError, KeyError, TypeError):
        return None


# ---- foe lineups (owner 9 Nov ~20:30Z): a same-map comparison between our versions, or of ours v a top-3 team, is valid only when the FOE'S
# LINEUP (the champions the opponent drafted) is the same too. Lineup = sorted champion ids (draft index order). Sources, cheapest first: this
# cache (filled from every match-groups show the lanes already make, no extra call), a replay on disk (decoded draft), one `matches show`.
LINEUPS = "/data/zw4424/st/lineups/foe_lineups.tsv"  # match id \t foe lineup (comma ids) \t source
_LU = {}
_LU_STAT = [None]
_RIDX = {}


def lineup_of(team):
    """a platform team record -> sorted champion ids (tuple), or None"""
    c = team.get("draftPicks") or team.get("characters") or []
    try:
        return tuple(sorted(int(x) for x in c)) or None
    except (TypeError, ValueError):
        return None


def lineup_txt(lu):
    return ",".join(map(str, lu)) if lu else "?"


def _lu_load():
    try:
        st = os.stat(LINEUPS)
    except OSError:
        return
    if _LU_STAT[0] == (st.st_size, st.st_mtime):
        return
    _LU_STAT[0] = (st.st_size, st.st_mtime)
    for ln in open(LINEUPS, errors="replace"):
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 2 and p[1] and p[1] != "?":
            try:
                _LU[p[0]] = tuple(int(x) for x in p[1].split(","))
            except ValueError:
                pass


def _lu_put(mid, lu, src):
    if not mid or not lu or _LU.get(mid) == tuple(lu):
        return
    _LU[mid] = tuple(lu)
    try:
        import fcntl
        os.makedirs(os.path.dirname(LINEUPS), exist_ok=True)
        with open(LINEUPS, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(f"{mid}\t{lineup_txt(lu)}\t{src}\n")
    except OSError:
        pass


def _replay_path(mid):
    """a replay of match mid already on disk (any /data/zw4424/plat set), or None; the set dirs are listed once a process"""
    import glob
    if mid not in _RIDX and time.time() - _RIDX.get("", 0) > 300:  # a miss re-lists at most every 5 minutes
        _RIDX[""] = time.time()
        for d in glob.glob("/data/zw4424/plat/*/"):
            try:
                for x in os.listdir(d):
                    if x.startswith("x_"):
                        _RIDX.setdefault(x[2:], d + x)
            except OSError:
                pass
    p = _RIDX.get(mid) if mid else None
    return p + "/replay.repl26a" if p and os.path.exists(p + "/replay.repl26a") else None


def foe_lineup(mid, side=None, fetch=True):
    """the foe's lineup (sorted champion ids) in match mid, or None when it can't be told. side: our side 'a'/'b' (needed to read a replay)"""
    _lu_load()
    if mid in _LU:
        return _LU[mid]
    p = _replay_path(mid) if side and side.lower() in ("a", "b") else None
    if p:
        try:
            import replay as R
            dr = R.decode_bytes(R._raw_replay(p), src=p).get("draft") or [[], []]
            lu = tuple(sorted(int(x) for x in dr[1 - "ab".index(side.lower())]))
            if lu:
                _lu_put(mid, lu, "replay")
                return lu
        except (Exception, SystemExit):  # noqa: BLE001  a bad replay falls through to the platform
            pass
    if fetch:
        try:
            d = json.loads(plat(["matches", "show", mid, "--json"]))
            for m in d.get("matches") or [d]:
                for t in m.get("teams") or []:
                    if t.get("teamId") != US_ID and t.get("name") != US and lineup_of(t):
                        _lu_put(m.get("matchId") or mid, lineup_of(t), "show")
        except ValueError:
            pass
        return _LU.get(mid)
    return None


def same_foe(a, b):
    """'match' / 'mismatch' / 'unknown' for two foe lineups"""
    if not a or not b:
        return "unknown"
    return "match" if tuple(a) == tuple(b) else "mismatch"


def group(gid):
    """[(match id, map, our side, result, status)] of a group, or None when not readable; each finished match's foe lineup goes to the cache
    (foe_lineup reads it with no further call)"""
    try:
        d = json.loads(plat(["match-groups", "show", gid, "--json"]))
    except ValueError:
        return None
    out = []
    _lu_load()
    for m in d.get("matches") or []:
        us = next((t for t in m.get("teams", []) if t.get("teamId") == US_ID or t.get("name") == US), {})
        them = next((t for t in m.get("teams", []) if t is not us and t.get("teamId") != US_ID and t.get("name") != US), {})
        if m.get("status") == "finished" and lineup_of(them):
            _lu_put(m.get("matchId"), lineup_of(them), "group")
        out.append((m.get("matchId"), m.get("map"), us.get("side"), us.get("result"), m.get("status")))
    return out


def create(team, maps=None, sides=None):
    args = ["match-groups", "create", team["teamId"], "--json", "--sides", ",".join(sides or [random.choice("ab") for _ in range(5)])]
    if maps:
        args += ["--maps", ",".join(maps)]
    out = plat(args)
    try:
        d = json.loads(out)
        return d.get("id") or d.get("groupId") or (d.get("group") or {}).get("id"), out
    except ValueError:
        return None, out


def flag(mid, side, team, rank, version, why):
    """critical flag for the analysers (critgame links a game identical to an earlier one instead of opening it again); a game
    already flagged (by hand or by critgame auto) is left as it is, so nobody's windows are overwritten"""
    if os.path.exists(f"/data/zw4424/st/crit/{mid}/meta.json"):
        return f"{mid}: already flagged, left as it is"
    try:  # 13 Nov (Coordinator, owner's top-3-only rule): flag critical only for foe team ids in bq/critical_foes.txt (by id, never name)
        ids = {ln.split("#")[0].strip() for ln in open("/data/zw4424/st/bq/critical_foes.txt") if ln.split("#")[0].strip()}
        if ids and (team or {}).get("teamId") not in ids:
            return f"{mid}: not flagged (foe {(team or {}).get('name', '?')} is outside bq/critical_foes.txt)"
    except OSError:
        pass
    r = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/critgame.py", "flag", mid, "--us", side.upper(), "--prio", "high",
                        "--by", "ladderclimb", "--version", version or "?", "--why", why], cwd=REPO, capture_output=True, text=True, timeout=1800)
    out = (r.stdout.strip().splitlines() or [r.stderr.strip()[-200:]])[0][:200]
    if out.startswith("flagged") and str((team or {}).get("name", "")).lower() in ("mite", "stellar best girl", "prism best fih", "intercontinental fish"):
        try:  # 11 Nov lossclass: top-3 loss class screen; pace/heavy/midgem -> auto-closed-to-class in meta.json (best-effort)
            c = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/lab/lossclass.py", "--annotate", mid, "--us", side.upper(),
                                "--foe", team["name"]], cwd=REPO, capture_output=True, text=True, timeout=900)
            out += " | " + (c.stdout.strip().splitlines() or ["lossclass: no output"])[-1][:120]
        except Exception:  # noqa: BLE001
            pass
    return out


def detached(args, kind):
    """9 Nov: a flagq/fetchq run in its OWN transient systemd unit, so a restart of this lane's unit can't kill it mid-queue (03:30Z: a lane restart
    orphaned flagq_1109032139.json); plain Popen when systemd-run is missing or refuses"""
    cmd = [sys.executable, "-I", f"{REPO}/tools/lab/ladderclimb.py"] + args
    envs = [f"{k}={v}" for k, v in os.environ.items() if k.startswith("CLIMB_")]
    unit = f"nova-{os.path.basename(DIR)}-{kind}-{time.strftime('%H%M%S', time.gmtime())}-{os.getpid() % 1000}"
    try:
        r = subprocess.run(["systemd-run", "--user", "--collect", "--unit", unit, f"--working-directory={REPO}", "/usr/bin/env"] + envs
                           + ["nice", "-n", "10"] + cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return
    except (OSError, subprocess.TimeoutExpired):
        pass
    subprocess.Popen(cmd, cwd=REPO, env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=open(f"{DIR}/{kind}.err", "a"), start_new_session=True)


def set_dir(ver):
    return f"/data/zw4424/plat/{SETNAME}_{ver}"


def set_add(ver, rows):
    """append finished games to the version's set (matches.txt: id map seat result team) and make sure the fetcher runs"""
    d = set_dir(ver)
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/matches.txt", "a") as f:
        f.writelines(f"{m} {mp} {sd} {res or 'draw'} {team.replace(' ', '_')}\n" for m, mp, sd, res, team in rows)
    detached(["fetchq"], "fetchq")


def fetchq():
    """one at a time (flock): every game of this lane's sets that has no x_ID in its set yet, losses first and newest version first;
    a copy already on disk elsewhere (a critgame flag, livepipe) is linked, not downloaded again. Exits when nothing is left."""
    import fcntl
    import glob
    lk = open(f"/data/zw4424/plat/.fetchq_{SETNAME}.lock" if WIN_SAMPLE else f"{DIR}/fetchq.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    got, tried = 0, set()
    while True:
        todo = []
        # 9 Nov (Combat): a fixed random sample first, the same rule for every version: per (version, team, win/loss) the SAMPLE games with the
        # smallest hash of their match id; then the rest (wins first when the loss flagger runs, else losses first)
        import hashlib
        for mt in sorted(glob.glob(f"/data/zw4424/plat/{SETNAME}_v*/matches.txt"), key=lambda p: -int(re.search(r"_v(\d+)/", p).group(1))):
            d = os.path.dirname(mt)
            strata = {}
            for ln in open(mt):
                p = ln.split()
                if len(p) >= 4:
                    strata.setdefault((p[4] if len(p) > 4 else "-", p[3] == "win"), {})[p[0]] = hashlib.sha1(p[0].encode()).hexdigest()
            for (team, w), ms in strata.items():
                rank = {m: i for i, m in enumerate(sorted(ms, key=ms.get))}
                for m in ms:
                    if m in tried or os.path.exists(f"{d}/x_{m}/replay.repl26a"):
                        continue
                    if not w:  # a loss the flagger already downloaded: link it, no second download
                        cp = f"/data/zw4424/plat/crit_auto/x_{m}"
                        if os.path.exists(f"{cp}/replay.repl26a"):
                            if not os.path.lexists(f"{d}/x_{m}"):
                                link_copy(cp, f"{d}/x_{m}")
                            continue
                    # 9 Nov (Coordinator, Combat: v643 kept 0 losses): LOSSES FIRST, as soon as the games are in (the flagger only starts when a team's
                    # whole probe is in, and critgame reuses this copy); wins after, for matching. Within each, the fixed hash order.
                    todo.append((w, -int(re.search(r"_v(\d+)$", d).group(1)), rank[m], d, m))  # newest version first
        # in-sample first, round-robin over the strata (every stratum's rank 0, then rank 1, ...); then the rest by result preference
        # 9 Nov 16:05Z (Coordinator, Combat: v643-v650 kept 0 wins: new losses always went ahead, so no win was ever fetched): losses and wins
        # ALTERNATE, one each, each list newest version first then hash rank; downloads are capped at ~4 a minute (platlock's 15 s gap)
        _l = [(t[3], t[4]) for t in sorted(set(x for x in todo if not x[0]), key=lambda t: (t[1], t[2]))]
        _w = [(t[3], t[4]) for t in sorted(set(x for x in todo if x[0]), key=lambda t: (t[1], t[2]))]
        _a, _b = (_w, _l) if len(tried) % 2 else (_l, _w)  # todo is rebuilt after every download: the turn comes from how many were tried
        todo = [x for pair in zip(_a, _b) for x in pair] + _a[len(_b):] + _b[len(_a):]
        if not todo:
            break
        d, m = todo[0]
        tried.add(m)
        r = subprocess.run(["sh", f"{REPO}/tools/lab/plat_fetch.sh", m, "--dest", d], cwd=REPO, capture_output=True, text=True, timeout=1800,
                           env=dict(os.environ, CAMBC_WHO=f"ladderclimb-{SETNAME}"))
        path = (r.stdout.strip().splitlines() or [""])[-1]
        if r.returncode or not path.endswith("replay.repl26a"):
            log(f"  fetchq {m}: failed ({(r.stderr or r.stdout).strip()[-160:]}); left for the next run")
            break
        src = os.path.dirname(path)
        if os.path.realpath(src) != os.path.realpath(f"{d}/x_{m}"):
            if os.path.islink(f"{d}/x_{m}"):
                os.remove(f"{d}/x_{m}")
            if not os.path.lexists(f"{d}/x_{m}"):
                link_copy(src, f"{d}/x_{m}")
        got += 1
        if got % 25 == 0:
            log(f"  fetchq: {got} replays in {SETNAME} sets this run, {len(todo) - 1} to go")
    log(f"  fetchq: done, {got} replays this run")
    return 0


def links():
    """{match id: fix} from replaycheck's flaw list (analysts link fixes there: replaycheck.py fix MATCH FIX)"""
    try:
        return {r["id"]: r.get("fix") for r in json.load(open("/data/zw4424/st/bq/replaycheck.json")) if r.get("fix")}
    except (OSError, ValueError):
        return {}


def readiness(lost):
    """[(loss, ready, why)]: ready when marked no-fix, or its fix (own link, else replaycheck's) is in the live bot"""
    import replaycheck
    rc = links()
    out = []
    live = active_version() if any(x.get("lumis") for x in lost) else None
    for x in lost:
        if x.get("lumis") and str(x["lumis"]).split()[0] == live:
            out.append((x, False, f"won on {live} under another foe lineup ({x['lumis']}): not a same-map comparison, waits for the next version"))
            continue
        if x.get("replay"):
            out.append((x, True, "re-play on the current live: " + str(x["replay"])))
            continue
        if x.get("nofix"):
            out.append((x, True, "no fix possible: " + str(x["nofix"])))
            continue
        fix = x.get("fix") or next((f for m, f in rc.items() if m.startswith(x["match"][:13])), None)
        if not fix:
            out.append((x, False, "no fix linked"))
            continue
        ok, why = replaycheck.fix_live(fix)
        out.append((x, ok, f"{fix}: {why}"))
    return out


def snapshot(st, rank):
    """freeze the ladder now: every team from RANK up to just below us, by teamId, in climbing order"""
    t, me = ladder()
    stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
    json.dump(dict(t=stamp, us=dict(rank=me["rank"], rating=round(me["rating"])), teams=t), open(f"{DIR}/ladder_{stamp}.json", "w"))
    st["order"] = [dict(teamId=x["teamId"], name=x["name"], rank=x["rank"], rating=round(x["rating"]))
                   for x in sorted(t, key=lambda x: -x["rank"]) if me["rank"] < x["rank"] <= rank and x.get("teamId") != US_ID]
    if TEAMS:
        by = {x["teamId"]: x for x in t}
        st["order"] = [dict(teamId=i, name=by[i]["name"], rank=by[i]["rank"], rating=round(by[i]["rating"])) for i in TEAMS if i in by]
    elif SLICE:  # owner 8 Nov: "batch together 5 people at a time": CLIMB_SLICE=i/n plays every n-th team, so n lanes play n different teams at once, none twice
        i, n = map(int, SLICE.split("/"))
        st["order"] = st["order"][i::n]
    st["idx"], st["snapshot"] = 0, f"{DIR}/ladder_{stamp}.json"
    log(f"frozen order from the ladder at {stamp}: {len(st['order'])} teams, rank {rank} up to {me['rank'] + 1} (us {me['rank']}, {round(me['rating'])})")


MAX_FLIGHT = int(os.environ.get("CLIMB_FLIGHT", "8"))  # groups in flight at once
QUOTA_CAP = int(os.environ.get("CLIMB_QUOTA_CAP", "80"))  # leave the rest of the hourly 100 to others
YIELD_TO = [x for x in os.environ.get("CLIMB_YIELD_TO", "").split(",") if x]  # 9 Nov (owner via Coordinator: keep the quota near full all night):
QUOTA_IDLE = int(os.environ.get("CLIMB_QUOTA_IDLE", "0"))  # while every lane in YIELD_TO (their CLIMB_DIRs) has nothing to play, this lane may use up to
# QUOTA_IDLE; once any of them has groups to queue or in flight (a ship gave it work) it drops back to QUOTA_CAP


def quota_cap():
    if not YIELD_TO or QUOTA_IDLE <= QUOTA_CAP:
        return QUOTA_CAP
    for d in YIELD_TO:
        try:
            o = json.load(open(os.path.join(d, "state.json")))
        except (OSError, ValueError):
            return QUOTA_CAP  # can't tell: yield
        if o.get("pending") or o.get("gids"):
            return QUOTA_CAP
    return QUOTA_IDLE


def all_maps():
    """every published map's platform name (the CLI's own list), cached for the day"""
    f = f"{DIR}/maps_{time.strftime('%Y%m%d', time.gmtime())}.json"
    if os.path.exists(f):
        return json.load(open(f))
    d = json.loads(plat(["match-groups", "quota", "--json"]))
    ms = sorted(m["name"] for m in d["maps"])
    json.dump(ms, open(f, "w"))
    return ms


def quota_used():
    try:
        q = json.loads(plat(["match-groups", "quota", "--json"])).get("quota", {})
        return int(q.get("used", 0))
    except (ValueError, TypeError):
        return 0


def bot_of(ver):
    return next(ln.split()[1] for ln in open("/data/zw4424/st/bq/live.txt") if ln.startswith(ver + " "))


def plays_same(x, bot):
    """exact replay of a lost game with the current bot: True when our side plays it identically, so a re-play can't flip it; None when it can't be told (then it is played)"""
    try:
        r = subprocess.run(["nice", "-n", "19", sys.executable, "-I", "tools/lab/puppet.py", x["match"], "--us", x["side"].upper(), "--bot", bot, "--dir", f"{DIR}/p/{x['match'][:18]}"],
                           cwd=REPO, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    return True if "ours: no difference" in r.stdout else False if "ours: first differs" in r.stdout else None


def book_update(st, res):
    """rotation (owner 8 Nov): a team's unresolved losses. A probe sets them; a re-play removes the maps won and keeps the rest"""
    e = st.setdefault("book", {}).setdefault(st["target"]["teamId"], dict(name=st["target"]["name"], lost=[], tried=None))
    ver = st["tried_version"]
    # owner 9 Nov ~20:30Z: a win on the same map resolves an earlier loss only under the SAME foe lineup; else it is no same-map comparison and
    # the loss stays unresolved ('lumis' = the version whose win did not count). A loss again carries the case forward (the new loss replaces it).
    cnt = dict(match=0, mismatch=0, unknown=0, resolved=0)

    def judge(x, r):
        old = x.get("foe") or foe_lineup(x["match"], x["side"])
        if old:
            x["foe"] = list(old)
        k = same_foe(old, r.get("foe") or foe_lineup(r["match"], r["side"]))
        cnt[k] += 1
        if k == "match":
            cnt["resolved"] += 1
            return True
        x["lumis"] = f"{ver} {k} ({r['match'][:13]}: foe {lineup_txt(r.get('foe'))}, the loss had {lineup_txt(old)})"
        return False

    def new_loss(r):
        return dict(map=r["map"], side=r["side"], match=r["match"], foe=list(r.get("foe") or []))
    if st["phase"] == "PROBE":
        last = {(r["map"], r["side"]): r for r in res}
        bymap = {r["map"]: r for r in res}
        keep = []
        for x in e["lost"]:
            r = last.get((x["map"], x["side"])) or bymap.get(x["map"])
            if r is None:
                if x.get("same"):  # FULL: skipped as identical, still unresolved
                    keep.append(x)
                continue
            if r["result"] == "win" and not judge(x, r):
                keep.append(x)  # won under another foe lineup: still unresolved
        lost_now = [new_loss(r) for r in last.values() if r["result"] != "win"]
        e["lost"] = [x for x in keep if (x["map"], x["side"]) not in {(y["map"], y["side"]) for y in lost_now}] + lost_now
    else:
        for r in res:
            for x in e["lost"][:]:
                if (x["map"], x["side"]) == (r["map"], r["side"]):
                    if r["result"] == "win":
                        if judge(x, r):
                            e["lost"].remove(x)
                    else:
                        x.update(match=r["match"], foe=list(r.get("foe") or []))
                        x.pop("same", None)
                        x.pop("lumis", None)
    e["tried"] = ver
    e["lu"] = dict(cnt, ver=ver)
    if cnt["match"] + cnt["mismatch"] + cnt["unknown"]:
        log(f"  {e['name']} ({ver}): earlier losses won on the same map: {cnt['match']} matched foe lineup (resolved), {cnt['mismatch']} dropped "
            f"for lineup mismatch, {cnt['unknown']} lineup unknown (not a same-map comparison: the loss stays unresolved)")


def rotate(st):
    """the next team with work on this version: never played or no losses left and a new version -> all maps; unresolved losses and a new version -> those maps, less any the current
    bot would play identically (they stay unresolved). No team waits on another. -> False when nothing has work"""
    import concurrent.futures as cf
    live, book, n = active_version(), st.setdefault("book", {}), len(st["order"])
    bot = bot_of(live)
    for k in range(n):
        i = (st.get("idx", 0) + k) % n
        tgt = st["order"][i]
        e = book.get(tgt["teamId"])
        if e is not None and FULL and e.get("tried") != live:
            with cf.ThreadPoolExecutor(4) as ex:
                same = list(ex.map(lambda x: plays_same(x, bot), e["lost"]))
            for x, s in zip(e["lost"], same):
                if s:
                    x["same"] = live
                else:
                    x.pop("same", None)
            side = {x["map"]: x["side"] for x in e["lost"]}
            skip = {x["map"] for x, s in zip(e["lost"], same) if s}
            pending, phase = [dict(map=m, side=side.get(m) or random.choice("ab")) for m in all_maps() if m not in skip], "PROBE"
            random.shuffle(pending)
            if skip:
                log(f"{tgt['name']}: {len(skip)} of {len(same)} unresolved losses play identically on {live}: skipped, still unresolved")
        elif e is None or (not e["lost"] and e.get("tried") != live):
            pending, phase = [dict(map=m, side=random.choice("ab")) for m in all_maps()], "PROBE"
            random.shuffle(pending)
        elif e["lost"] and e.get("tried") != live:
            with cf.ThreadPoolExecutor(4) as ex:
                same = list(ex.map(lambda x: plays_same(x, bot), e["lost"]))
            for x, s in zip(e["lost"], same):
                if s:
                    x["same"] = live
                else:
                    x.pop("same", None)
            pending, phase = [dict(map=x["map"], side=x["side"]) for x, s in zip(e["lost"], same) if not s], "RETEST"
            e["tried"] = live
            skipped = sum(bool(s) for s in same)
            if skipped:
                log(f"{tgt['name']}: {skipped} of {len(same)} unresolved losses: no shipped change touched this game ({live}); they stay unresolved")
            if not pending:
                continue
        else:
            continue
        st.update(idx=i, target=dict(tgt), phase=phase, pending=pending, results=[], lost=[], tried_version=live)
        log(f"rotation {i + 1}/{n}: {phase} rank {tgt['rank']} {tgt['name']} on {live}: {len(pending)} maps")
        return True
    return False


def step(dry=False):
    """owner 8 Nov: a team is played on ALL published maps (one game a map, random side), "so we can see where our flaws are"; every
    lost map is flagged critical; on each new live version exactly the lost maps are re-played (same side) until every one is won"""
    if os.path.exists(DIR + "/OFF"):
        return "off"
    st = load()
    if st["phase"] == "DONE":
        return "done: every team of the frozen order beaten"
    st.setdefault("gids", [])
    st.setdefault("pending", [])
    st.setdefault("results", [])
    # 1. collect finished groups
    for g in list(st["gids"]):
        rows = group(g["gid"])
        if not rows or len(rows) < len(g["games"]) or any(r[4] != "finished" for r in rows):
            continue
        ver = g.get("ver") or st.get("tried_version")  # 9 Nov: the version live when the group was made (a ship mid-probe moved v638 -> v639)
        rows = [r for r in rows]
        vat = {r[0]: (version_at(r[0]) or ver) for r in rows}
        if any(v != ver for v in vat.values()):
            log(f"  group {g['gid'][:13]}: {sum(v != ver for v in vat.values())} games were created under {sorted(set(vat.values()) - {ver})}, not {ver} "
                "(a ship landed while the group was queued): recorded under the version live at match creation")
        for r in rows:
            st["results"].append(dict(match=r[0], map=r[1], side=r[2], result=r[3], ver=vat[r[0]], foe=list(foe_lineup(r[0], r[2], fetch=False) or [])))
        with open(f"{DIR}/games.tsv", "a") as gf:  # 9 Nov: every game this lane played, for the analysts (version team rank match map side result foe-lineup)
            import teamalias  # 12 Nov: a renamed team keeps its one name in games.tsv ('prism best fih' = 'stellar best girl')
            gf.writelines(f"{vat[r[0]]}\t{teamalias.canonical(st['target']['name'])}\t{st['target']['rank']}\t{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t"
                          f"{lineup_txt(foe_lineup(r[0], r[2], fetch=False))}\t{st['target'].get('teamId') or '-'}\n" for r in rows)
            # 13 Nov (Coordinator: SBG renames; filters on team ids): column 9 = the foe's platform teamId
        if SETNAME and ver:
            import hashlib
            keep = [r for r in rows if not WIN_SAMPLE or (r[3] == "win" and int(hashlib.sha1(r[0].encode()).hexdigest(), 16) % WIN_SAMPLE == 0)]
            if keep:
                for v_ in sorted({vat[r[0]] for r in keep}):
                    set_add(v_, [(r[0], r[1], r[2], r[3], st["target"]["name"]) for r in keep if vat[r[0]] == v_])
        st["gids"].remove(g)
    save(st)
    # 2. a phase whose games are all in: decide
    if st["phase"] in ("PROBE", "RETEST") and not st["pending"] and not st["gids"] and st["results"]:
        res = st["results"]
        seen = {}
        for r in res:  # a padded map played twice counts as lost if either game was lost
            seen[(r["map"])] = seen.get(r["map"], True) and r["result"] == "win"
        lost = [r for r in res if r["result"] != "win"]
        n, nl = len(res), len(lost)
        st["history"].append(dict(t=time.time(), phase=st["phase"], team=st["target"]["name"], rank=st["target"]["rank"],
                                  version=st["tried_version"], record=f"{n - nl}-{nl}",
                                  lost=[dict(map=r["map"], side=r["side"], match=r["match"]) for r in lost]))
        log(f"{st['phase']} v rank {st['target']['rank']} {st['target']['name']} ({st['tried_version']}): {n - nl}-{nl} over {len(seen)} maps"
            + ("" if not lost else "; lost " + ", ".join(f"{r['map']}({r['side']})" for r in lost)))
        carry = []  # owner 9 Nov ~20:30Z: a RETEST win resolves a lost map only under the same foe lineup as the loss; else the loss carries over
        if not NO_WAIT and st["phase"] == "RETEST":
            was = {(x["map"], x["side"]): x for x in st.get("lost", [])}
            cnt = dict(match=0, mismatch=0, unknown=0)
            for r in res:
                x = was.get((r["map"], r["side"]))
                if x is None or r["result"] != "win":
                    continue
                old = x.get("foe") or foe_lineup(x["match"], x["side"])
                if old:
                    x["foe"] = list(old)
                k = same_foe(old, r.get("foe") or foe_lineup(r["match"], r["side"]))
                cnt[k] += 1
                if k != "match":
                    x["lumis"] = f"{st['tried_version']} {k} ({r['match'][:13]}: foe {lineup_txt(r.get('foe'))}, the loss had {lineup_txt(old)})"
                    carry.append(x)
            if sum(cnt.values()):
                log(f"  lost maps won again: {cnt['match']} matched foe lineup (resolved), {cnt['mismatch']} dropped for lineup mismatch, "
                    f"{cnt['unknown']} lineup unknown (not a same-map comparison: they stay in the batch for the next version)")
        if NO_WAIT:
            book_update(st, res)
        st["results"] = []
        if not lost and not carry:
            st["phase"], st["lost"] = "NEXT", []
            st["idx"] = st.get("idx", 0) + 1
        else:
            st["phase"] = "WAITFIX"  # owner 8 Nov ~04:30Z: re-play only when every lost map's fix is live (or marked no-fix): no quota meanwhile
            st["lost"] = [dict(map=r["map"], side=r["side"], match=r["match"], fix=None, nofix=None, foe=list(r.get("foe") or [])) for r in lost] + carry
            if FLAG_BG and lost:
                fq = f"{DIR}/flagq_{time.strftime('%m%d%H%M%S', time.gmtime())}.json"
                json.dump(dict(target=st["target"], version=st["tried_version"], record=f"{n - nl}-{nl}", lost=lost), open(fq, "w"))
                detached(["flagq", fq], "flagq")
                log(f"  {nl} losses go to the analysts by a detached flagq ({fq})")
            for r in ([] if FLAG_BG else lost):  # noqa: B007
                why = (f"ladderclimb: lost to rank {st['target']['rank']} {st['target']['name']} on {r['map']} under {r.get('ver') or st['tried_version']} "
                       f"({n - nl}-{nl} over all maps); "
                       + ("rotation: it re-plays this map when something ships and needs no ladderclimb verdict: find the flaw (critical)" if NO_WAIT
                          else "the climb waits on this team until a fix wins every lost map: find the flaw (critical)"))
                log("  flag " + flag(r["match"], r["side"], st["target"], st["target"]["rank"], r.get("ver") or st["tried_version"], why))
                # 13 Nov (TB: side-lane losses created 08:0x-08:22Z under v879 were flagged 'v876', the version live when the PROBE began hours
                # earlier; rotation lanes probe for hours across ships): each loss carries its own game's version (version_at, set at collect)
            if NO_WAIT:
                st["phase"], st["lost"] = "NEXT", []
                st["idx"] = st.get("idx", 0) + 1
        save(st)
    # 3. pick the next team
    if st["phase"] == "NEXT":
        if "order" not in st:
            snapshot(st, st["rank"])
        if NO_WAIT:
            if not rotate(st):
                save(st)
                return f"rotation: nothing to play on {active_version()} (every loss waits for a shipped change)"
            save(st)
        else:
            if st.get("idx", 0) >= len(st["order"]):
                st["phase"] = "DONE"
                save(st)
                log(f"DONE: every team of the frozen order beaten on every map ({len(st['order'])} teams)")
                return "done"
            tgt = st["order"][st["idx"]]
            st["target"] = dict(tgt)
            st["phase"] = "PROBE"
            st["pending"] = [dict(map=m, side=random.choice("ab")) for m in all_maps()]
            random.shuffle(st["pending"])
            st["results"], st["tried_version"] = [], active_version()
            save(st)
            log(f"next target {st['idx'] + 1}/{len(st['order'])}: rank {tgt['rank']} {tgt['name']} ({tgt['rating']}), all {len(st['pending'])} maps on {st['tried_version']}")
    # 4. WAITFIX: the batch of lost maps re-plays once every loss is ready (its linked fix is live, or it is marked no-fix)
    if st["phase"] in ("WAITFIX", "RETEST") and not st["pending"] and not st["gids"]:
        st["phase"] = "WAITFIX"
        ready = readiness(st["lost"])
        notready = [x for x, ok, why in ready if not ok]
        if notready:
            save(st)
            return (f"WAITFIX {st['target']['name']}: {len(st['lost']) - len(notready)}/{len(st['lost'])} lost maps ready; waiting on "
                    + ", ".join(f"{x['map']}({x['match'][:8]})" for x in notready[:6]) + " (no quota used)")
        batch = [x for x in st["lost"] if x.get("replay") or not x.get("nofix")]
        if not batch:  # every remaining loss was marked no-fix by the analysts
            log(f"{st['target']['name']}: every remaining loss marked no-fix ({len(st['lost'])}); next team")
            st["phase"], st["lost"], st["idx"] = "NEXT", [], st.get("idx", 0) + 1
            save(st)
            return "next (no-fix losses)"
        v = active_version()
        st["pending"] = [dict(map=x["map"], side=x["side"]) for x in batch]
        st["results"], st["tried_version"], st["phase"] = [], v, "RETEST"
        save(st)
        log(f"RETEST v {st['target']['name']} on {v}: batch of {len(batch)} lost maps, every linked fix live"
            + (f"; {len(st['lost']) - len(batch)} no-fix maps left out" if len(st['lost']) > len(batch) else ""))
    # 5. launch groups of 5 while there is room
    made = 0
    vnow = active_version() if st["pending"] and NO_WAIT else None  # once a step: each group carries the version it was made under
    quota_now = quota_used() if st["pending"] else 0  # once a step, then counted here: a platform call per group halved the rate
    cap = quota_cap() if st["pending"] else QUOTA_CAP
    while st["pending"] and len(st["gids"]) < MAX_FLIGHT:
        if quota_now + made >= cap:
            break
        batch = st["pending"][:5]
        games = list(batch)
        # a short group: the platform wants five DIFFERENT maps (HTTP 400, 8 Nov), so pad with other maps of this team's games already
        # played (won ones first), on the other side; their results count like any game (a padded loss is a real loss)
        used = {g["map"] for g in games}
        played = [r for r in st["results"] if r["result"] == "win"] + [r for r in st["results"] if r["result"] != "win"]
        extra = [r for r in played if r["map"] not in used and not used.add(r["map"])]
        if len(extra) < 5 - len(games):
            extra += [dict(map=m, side=random.choice("ab")) for m in all_maps() if m not in used and not used.add(m)]
        for r in extra[:5 - len(games)]:
            games.append(dict(map=r["map"], side="b" if r.get("side") == "a" else "a"))
        if dry:
            return f"would create {st['phase']} group v {st['target']['name']}: {games}"
        gid, out = create(st["target"], [g["map"] for g in games], [g["side"] for g in games])
        if not gid:
            log(f"!! group create failed: {out[:300]}")
            break
        st["pending"] = st["pending"][5:]
        st["gids"].append(dict(gid=gid, games=games, ver=vnow))
        save(st)
        made += 1
    if made:
        log(f"{st['phase']} v {st['target']['name']}: {made} groups queued, {len(st['gids'])} in flight, {len(st['pending'])} maps left to queue")
    return f"{st['phase']} {st['target']['name']}: {len(st['gids'])} groups in flight, {len(st['pending'])} maps to queue, {len(st['results'])} games in"


def main():
    a = sys.argv[1:]
    if a[:1] == ["fetchq"]:
        return fetchq() if SETNAME else 0
    if a[:1] == ["flagq"]:  # CLIMB_FLAG_BG: flag one finished probe's losses, one at a time (platlock serialises the downloads anyway)
        q = json.load(open(a[1]))
        tg, n = q["target"], len(q["lost"])
        for r in q["lost"]:
            why = (f"ladderclimb: lost to rank {tg['rank']} {tg['name']} on {r['map']} under {r.get('ver') or q['version']} ({q['record']} over all maps); "
                   "rotation: it re-plays this map when something ships and needs no ladderclimb verdict: find the flaw (critical)")
            log("  flag " + flag(r["match"], r["side"], tg, tg["rank"], r.get("ver") or q["version"], why))
        os.replace(a[1], a[1] + ".done")
        log(f"  flagq done: {n} losses v {tg['name']} ({q['version']})")
        return 0
    if a[:1] == ["book"]:  # rotation: each team's unresolved losses
        for e in load().get("book", {}).values():
            s = sum(1 for x in e["lost"] if x.get("same"))
            lm = sum(1 for x in e["lost"] if x.get("lumis"))
            lu = e.get("lu") or {}
            print(f"{e['name']}: {len(e['lost'])} unresolved, tried on {e.get('tried')}" + (f"; {s}: no shipped change touched this game" if s else "")
                  + (f"; {lm} won later under another foe lineup (not resolved)" if lm else "")
                  + (f"; last pass {lu.get('ver')}: {lu.get('match', 0)} matched foe lineup, {lu.get('mismatch', 0)} dropped for lineup mismatch, "
                     f"{lu.get('unknown', 0)} unknown" if lu else ""))
        return 0
    if not a or a[0] not in ("status", "step", "loop", "reset", "fix", "nofix", "replay", "losses"):
        sys.exit(__doc__)
    if a[0] in ("fix", "nofix", "replay", "losses") and os.path.exists(DIR + "/OFF") and "CLIMB_DIR" not in os.environ:
        # 12 Nov (Coordinator + Path Finding, analysts/climb_v632_ready_1112.md): the main climb is RETIRED (its OFF file; owner: do not
        # restart). Its state.json still held 26 READY rows (v632 losses since re-played and won), shown as work. Its file stays (cited);
        # 'losses' now lists the live lanes' books, and a verb needs an explicit CLIMB_DIR (nothing queues from the retired file).
        if a[0] != "losses":
            sys.exit(f"ladderclimb: {DIR} is retired (OFF): nothing queues from it; set CLIMB_DIR to a live lane's dir to mark a verdict there")
        import glob
        lanes = sorted(glob.glob("/data/zw4424/st/climb_side*") + glob.glob("/data/zw4424/st/climb_top3"))
        n_old = len(json.load(open(DIR + "/state.json")).get("lost", [])) if os.path.exists(DIR + "/state.json") else 0
        print(f"(main climb {DIR} retired: its {n_old} old rows are not listed; CLIMB_DIR={DIR} shows them)")
        for ld in lanes:
            if os.path.exists(ld + "/OFF") or not os.path.exists(ld + "/state.json"):
                continue
            lost = json.load(open(ld + "/state.json")).get("lost", [])
            print(f"{os.path.basename(ld)}: {len(lost)} lost map(s) in its batch")
            for x, ok, why in readiness(lost):
                print(f"  {'READY' if ok else 'wait '} {x['map']:20s} side {x['side']} {x['match']}  {why}")
        return 0
    if a[0] in ("fix", "nofix", "replay", "losses"):
        st = load()
        if a[0] == "losses":
            for x, ok, why in readiness(st.get("lost", [])):
                print(f"  {'READY' if ok else 'wait '} {x['map']:20s} side {x['side']} {x['match']}  {why}")
            return 0
        hit = [x for x in st.get("lost", []) if x["match"].startswith(a[1])]
        if len(hit) != 1:
            sys.exit(f"ladderclimb: {a[1]} matches {len(hit)} lost games (ladderclimb.py losses lists them)")
        if a[0] == "fix":
            import replaycheck
            hit[0]["fix"] = replaycheck.fix_form(a[2])
        elif a[0] == "replay":
            hit[0]["replay"] = " ".join(a[2:]) or "re-play on the current live"
        else:
            hit[0]["nofix"] = " ".join(a[2:]) or "marked by an analyst"
        save(st)
        log(f"{a[0]} {hit[0]['match']} ({hit[0]['map']}): {hit[0].get(a[0]) or hit[0].get('fix')}")
        return 0
    if a[0] == "status":
        st = load()
        print(json.dumps({k: st[k] for k in st if k not in ("history", "order", "pending", "results", "gids", "lost")}, indent=1))
        rs = st.get("results", [])
        print(f"in flight {len(st.get('gids', []))} groups; {len(st.get('pending', []))} maps to queue; {len(rs)} games in, "
              f"{sum(r['result'] != 'win' for r in rs)} lost so far (flagged when the team's games are all in); batch from earlier: "
              f"{len(st.get('lost', []))} lost maps")
        if st.get("order"):
            print(f"frozen order ({st.get('snapshot')}): " + ", ".join(f"{'>' if i == st.get('idx') else ''}{x['rank']} {x['name']}"
                                                                   for i, x in enumerate(st["order"])))
        for h in st.get("history", [])[-10:]:
            print(f"  {time.strftime('%m-%d %H:%MZ', time.gmtime(h['t']))} {h['phase']:6s} rank {h['rank']} {h['team']} {h['version']}: "
                  f"{h['record']} " + ", ".join(f"{x['map']}({x['side']})" for x in h['lost']))
        return 0
    if a[0] == "reset":
        rank = int(a[a.index("--rank") + 1]) if "--rank" in a else 21
        st = dict(rank=rank, phase="NEXT", target=None, lost=[], tried_version=None, gid=None, history=load().get("history", []))
        log(f"reset: start at rank {rank}")
        snapshot(st, rank)
        save(st)
        return 0
    if a[0] == "step":
        print(step("--dry" in a))
        return 0
    every = int(a[a.index("--every") + 1]) if "--every" in a else 600
    while True:
        try:
            r = step()
            if not r.startswith(("waiting", "RETEST")):
                print(r, flush=True)
        except Exception as e:  # noqa: BLE001  the loop must survive a platform hiccup
            log(f"!! step failed: {e!r}"[:300])
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
