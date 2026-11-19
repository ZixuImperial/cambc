#!/usr/bin/env python3
"""teamdata: our games v each opponent team, gathered into one ledger per team. Tool builder, 4 Nov (owner via the Builder: "make
some scripts to get our data of our games vs each team so we can gather them; mainly for the top 10 international; add to this
whenever we play them").

usage: python3 -I tools/lab/teamdata.py update [--fetch N] [--quiet] [--rebuild]
       python3 -I tools/lab/teamdata.py report TEAM [TEAM ...] | --top10 | --intl | --all
       python3 -I tools/lab/teamdata.py intl [--write]
  update   scans every game we hold (/data/zw4424/plat/{rk_*,unr_*,vs_*,...} and /data/zw4424/livepipe/vNNN/set) and appends new
           games, deduped by match id, to /data/zw4424/st/teams/<team_slug>/games.jsonl. Incremental: a set whose listing is
           unchanged since the last scan is skipped (state.json), so a run with nothing new takes seconds. Metadata comes from
           what the fetchers stored (meta/list_p*.json, g_*.json, show_*.json, matches.txt, livepipe pergame.json); stats
           (deaths, kills, gold, gems, fuelExhausted, faults, score, end round, kits) from the game's .json. --fetch N: for up to
           N ledger games still missing the platform record (time, kind, team id), run `matches show ID --json` once each and
           cache the answer in show_cache.jsonl (never re-fetched). The ladder is cached in ladder.json (refreshed hourly).
  report   condor-work/reports/teams/<slug>.md per team + index.md (TEAM: a name, a teamId, a teams.py key or group such as TOP3;
           a ledger is keyed by teamId and its <slug> is the team's CURRENT ladder name, so a rename moves it at the next update). Ranked games only in the quality rows (W-L, Wilson 95% CI,
           by version band, map, side, lineups, trend); unranked (designed sets) shown apart. --top10: ladder top 10 minus us;
           --intl: /data/zw4424/st/teams/top_intl.txt (one teamId per line, '# name' comment; names still accepted); --all: every
           team with >= 10 games.
  intl     the ladder's top teams that carry the 'International Qualifiers' qualification (our own team doesn't: Cambridge
           teams don't), minus us; --write seeds top_intl.txt with the first 10 (an existing file is kept as top_intl.txt.old).
Ledger row: id utc ver kind map side result us them (scores) rounds end ours theirs (kit short names in pick order) and per side
(_us/_them): deaths kills gold_earned gold_spent gems_collected gems_tributed fuel_cuts faults; set, stats, replay paths.
"""
import collections
import datetime
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's dir off sys.path
import teams  # noqa: E402  (team id table, shared ladder cache)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = "/data/zw4424/st/teams"
PLAT = "/data/zw4424/plat"
LIVEPIPE = "/data/zw4424/livepipe"
LIVE = "/data/zw4424/st/bq/live.txt"
OUT = "/homes/zw4424/condor-work/reports/teams"
CLI = "/data/zw4424/cambc400/bin/cambc400"
US = "BattleCats"
VIS = "https://2026a.battlecode.co.uk/game/visualiser/"
SHORT = ["Ry", "VV", "Ve", "CI", "St", "Pr", "Ma", "Wi", "Re", "Va", "Ta", "HoR"]  # draft index order (vsteam.py, draft.cpp Champ)
LONG = {"Ryth": "Ry", "Vesper Vale": "VV", "Vendetta": "Ve", "Cassi & Issac": "CI", "Stellar": "St", "Prism": "Pr", "Marcella": "Ma",
        "Willow": "Wi", "Ren": "Re", "Varg": "Va", "Tavi": "Ta", "Heart of Ruin": "HoR"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STATS = ("deaths", "kills", "gold_earned", "gold_spent", "gems_collected", "gems_tributed", "fuel_cuts", "faults")


def slug(name, tid=None):
    """A ledger dir name. 4 Nov: a name with no ASCII letters/digits takes team_<id8> (or team_<md5 of the name> without an id);
    it used hash(), which Python salts per run, so such teams got a new dir every update and were counted twice in the index."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "team_" + (tid[:8] if tid else hashlib.md5((name or "").encode()).hexdigest()[:8])


def jload(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(p, x):
    t = f"{p}.new.{os.getpid()}"
    with open(t, "w") as f:
        json.dump(x, f, indent=0, sort_keys=True)
    os.replace(t, p)


def versions():
    """[(utc, 'vNNN')] ascending: live.txt (newest first; records rollbacks) and, for versions before it, the platform's submission
    times (cached in versions.json; the first page refreshed hourly, the full list fetched once)."""
    lt = {}
    for ln in open(LIVE) if os.path.exists(LIVE) else []:
        p = ln.split()
        if len(p) >= 3 and re.fullmatch(r"v\d+", p[0]):
            lt.setdefault(p[0], p[2])
    cp = f"{ROOT}/versions.json"
    sub = jload(cp, {}) or {}
    if not sub or time.time() - os.path.getmtime(cp) > 3600:
        before, n = None, 0
        while n < 60:
            try:
                x = json.loads(plat(["submissions", "list", "--json"] + (["--before", str(before)] if before else [])).stdout)
            except (subprocess.TimeoutExpired, ValueError):
                break
            got = [(f"v{s['version']}", s["createdAt"][:19] + "Z") for s in x.get("submissions", []) if s.get("version")]
            new = [g for g in got if g[0] not in sub]
            sub.update(dict(got))
            n += 1
            if not got or not x.get("more") or (not new and before is None and len(sub) > 20):
                break
            before = min(int(g[0][1:]) for g in got)
        if sub:
            jsave(cp, sub)
    first = min(lt.values()) if lt else "9999"
    out = dict(lt)
    for v, t in sub.items():
        if v not in out and t < first:
            out[v] = t
    return sorted((t, v) for v, t in out.items())


def ver_at(utc, vs):
    best = None
    for t, v in vs:
        if t <= utc:
            best = v
    return best


def vnum(v):
    m = re.fullmatch(r"v(\d+)", v or "")
    return int(m.group(1)) if m else None


# ---------- metadata sources ----------

def rich(m):
    """A platform match record (list/show/group JSON) -> meta dict, or None if we didn't play it."""
    ts = m.get("teams") or []
    us = next((t for t in ts if t.get("name") == US), None)
    them = next((t for t in ts if t.get("name") != US), None)
    if not us or not them or not m.get("matchId"):
        return None
    kit = lambda t: [SHORT[int(c)] if str(c).isdigit() and int(c) < len(SHORT) else str(c) for c in t.get("draftPicks") or t.get("characters") or []]
    return dict(id=m["matchId"], utc=(m.get("createdAt") or "")[:19] + "Z" if m.get("createdAt") else None, kind=m.get("kind"),
                map=m.get("map"), side=us.get("side"), result=us.get("result"), opp=them.get("name"), opp_id=them.get("teamId"),
                ours=kit(us), theirs=kit(them), end=m.get("endReason"), rich=1)


def meta_in(d):
    """{id: meta} from every metadata file a fetcher left in set dir d (richest wins)."""
    out = {}
    for p in glob.glob(f"{d}/matches.txt") + glob.glob(f"{d}/meta/matches.txt"):
        for ln in open(p, errors="replace"):
            f = ln.split()
            if len(f) >= 5 and UUID.fullmatch(f[0]):
                out.setdefault(f[0], dict(id=f[0], map=f[1], side=f[2], result=f[3], opp=f[4].replace("_", " "),
                                          ver=f[5] if len(f) > 5 and re.fullmatch(r"v\d+", f[5]) else None))
    pg = jload(f"{os.path.dirname(d)}/pergame.json", {}) if os.path.basename(d) == "set" else {}
    for i, g in (pg or {}).items():
        if UUID.fullmatch(i) and i not in out:
            out[i] = dict(id=i, map=g.get("map"), side=(g.get("seat") or "").lower() or None, opp=g.get("opp"),
                          result={1: "win", 0: "loss"}.get(g.get("win")))
    for p in glob.glob(f"{d}/meta/*.json") + glob.glob(f"{d}/g_*.json") + glob.glob(f"{d}/show_*.json") + glob.glob(f"{d}/meta/g_*.json"):
        x = jload(p)
        for m in (x.get("matches") or []) if isinstance(x, dict) else []:
            r = rich(m) if isinstance(m, dict) else None
            if r:
                out[r["id"]] = dict(out.get(r["id"], {}), **{k: v for k, v in r.items() if v not in (None, [])})
    return out


def set_ver(d):
    """The live version a fetched set belongs to, from its dir name (rk_v482, unr_v400, lp_rk_v276, lv_v267, rankedV188)."""
    b = d.split("/plat/")[-1]
    m = re.match(r"(?:lp_|lv_)?(?:rk_|unr_|ranked)?[vV](\d{3})(?:$|[^0-9])", b) if re.match(r"(lp_|lv_|rk_|unr_|ranked)", b) else None
    m = m or re.search(r"/livepipe/v(\d+)/set$", d)
    return f"v{m.group(1)}" if m else None


def set_kind(d):
    b = d.split("/plat/")[-1].lower()
    if "/livepipe/" in d:
        return "ranked"
    if re.match(r"(lp_)?unr_|vs_", b) or "unranked" in b:
        return "unranked"
    if re.match(r"(lp_)?rk_|ranked", b):
        return "ranked"
    return None


# ---------- stats ----------

def stats_of(p, side):
    """The game's stats .json -> per-side numbers, scores, rounds, kits (A = side a)."""
    d = jload(p)
    if not isinstance(d, dict) or "champions" not in d:
        return {}
    me, op = ("teamA", "teamB") if side == "a" else ("teamB", "teamA")
    s = {t: collections.Counter() for t in (me, op)}
    for c in d.get("champions", []):
        m, t = c.get("metrics", {}), c.get("team")
        if t in s:
            for k, src in (("deaths", "deaths"), ("kills", "kills"), ("gold_earned", "earnedGold"), ("gold_spent", "spentGold"),
                           ("gems_collected", "collectedGems"), ("gems_tributed", "submittedGems")):
                try:
                    s[t][k] += int(float(m.get(src) or 0))
                except ValueError:
                    pass
    for e in d.get("events", []):
        if e.get("kind") == "fuelExhausted" and (e.get("owner") or {}).get("team") in s:
            s[e["owner"]["team"]]["fuel_cuts"] += len(e.get("entries") or [])
    for t, n in ((d.get("diagnostics") or {}).get("botFaults") or {}).items():
        if t in s:
            s[t]["faults"] += int(n or 0)
    sc = {t.get("team"): int(float(t.get("submittedGems") or 0)) for t in d.get("teams", [])}
    kits = {me: [], op: []}
    for x in (d.get("roster") or {}).get("draft", []):
        if x.get("team") in kits:
            kits[x["team"]].append(LONG.get(x.get("champion"), x.get("champion")))
    mt = d.get("match") or {}
    out = dict(us=sc.get(me), them=sc.get(op), rounds=mt.get("roundsCompleted"),
               outcome=("win" if mt.get("outcome") == me else "loss" if mt.get("outcome") == op else mt.get("outcome")),
               ours_s=kits[me], theirs_s=kits[op])
    for k in STATS:
        out[k + "_us"], out[k + "_them"] = s[me][k], s[op][k]
    return out


# ---------- ledger ----------

def ledgers():
    """{id: (slug, row)} for every game already in a ledger."""
    out = {}
    for p in glob.glob(f"{ROOT}/*/games.jsonl"):
        sl = os.path.basename(os.path.dirname(p))
        for ln in open(p):
            try:
                r = json.loads(ln)
                out[r["id"]] = (sl, r)
            except (ValueError, KeyError):
                pass
    return out


def set_dirs():
    ds = [d for d in glob.glob(f"{PLAT}/*") if os.path.isdir(d) and not os.path.basename(d).startswith(("deep_", "owner"))]
    return sorted(ds) + sorted(glob.glob(f"{LIVEPIPE}/v*/set"))


def sig(d):
    try:
        st = os.stat(d)
        return f"{int(st.st_mtime)}:{st.st_nlink}:{len(os.listdir(d))}"
    except OSError:
        return None


def find_files(d, i):
    """(stats json, replay) for game i in set dir d."""
    js = next((p for p in (f"{d}/{i}.json",) if os.path.exists(p)), None)
    rp = next((p for p in (f"{d}/x_{i}/replay.repl26a", f"{d}/g_{i}/replay.repl26a", f"{d}/{i}.zip") if os.path.exists(p)), None)  # decoded first: readers load it
    return js, rp


def build_row(i, meta, d, vs):
    js, rp = find_files(d, i)
    row = dict(id=i, utc=meta.get("utc"), kind=meta.get("kind") or set_kind(d), map=meta.get("map"), side=meta.get("side"),
               result=meta.get("result"), opp=meta.get("opp"), opp_id=meta.get("opp_id"), ours=meta.get("ours") or [],
               theirs=meta.get("theirs") or [], end=meta.get("end"), set=d, stats=js, replay=rp, rich=meta.get("rich", 0))
    row["ver"] = meta.get("ver") or set_ver(d) or (ver_at(row["utc"], vs) if row["utc"] else None)
    if js and row["side"] in ("a", "b"):
        s = stats_of(js, row["side"])
        if s:
            row.update({k: v for k, v in s.items() if k not in ("ours_s", "theirs_s", "outcome")})
            if not row["ours"]:
                row["ours"], row["theirs"] = s["ours_s"], s["theirs_s"]
            row["result"] = row["result"] or s["outcome"]
    return row


def better(old, new):
    """Fill old's gaps from new (a later scan may find the platform record or the stats file)."""
    ch = False
    if (new.get("replay") or "").endswith(".repl26a") and not (old.get("replay") or "").endswith(".repl26a"):
        old["replay"], ch = new["replay"], True  # 4 Nov: the decoded replay, which readers load, over the .zip
    for k, v in new.items():
        if v not in (None, [], "") and old.get(k) in (None, [], "", 0) and k != "rich":
            old[k] = v
            ch = True
    if new.get("rich") and not old.get("rich"):
        for k in ("utc", "kind", "opp", "opp_id", "ours", "theirs", "end"):
            if new.get(k):
                old[k] = new[k]
        old["rich"], ch = 1, True
    return ch


def write_ledgers(rows_by_slug):
    for sl, rows in rows_by_slug.items():
        os.makedirs(f"{ROOT}/{sl}", exist_ok=True)
        p = f"{ROOT}/{sl}/games.jsonl"
        t = f"{p}.new.{os.getpid()}"
        with open(t, "w") as f:
            for r in sorted(rows, key=lambda r: (r.get("utc") or "", r["id"])):
                f.write(json.dumps(r, sort_keys=True) + "\n")
        os.replace(t, p)


def plat(args, timeout=120):
    return subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, *args], capture_output=True, text=True, timeout=timeout)


def ladder(force=False):
    """The cached ladder ({ROOT}/ladder.json, refreshed hourly); teams.py owns the read (4 Nov)."""
    return teams.ladder(force=force) or {}


def update(a):
    os.makedirs(ROOT, exist_ok=True)
    quiet = "--quiet" in a
    fetch = int(a[a.index("--fetch") + 1]) if "--fetch" in a else 0
    rebuild = "--rebuild" in a  # re-derive every row from the sets (after a reader change); the show cache is kept
    st = {} if rebuild else jload(f"{ROOT}/state.json", {}) or {}
    seen = st.setdefault("sets", {})
    led = {} if rebuild else ledgers()
    vs = versions()
    changed = collections.defaultdict(list)
    t0, nsets, nnew, nfill = time.time(), 0, 0, 0
    for d in set_dirs():
        s = sig(d)
        if s is None or seen.get(d) == s:
            continue
        nsets += 1
        meta = meta_in(d)
        ids = set(meta) | {m.group(0) for f in os.listdir(d) for m in [UUID.search(f)] if m and f.endswith((".json", ".zip"))
                           and not f.startswith(("g_", "show_"))} | {f[2:] for f in os.listdir(d) if f.startswith("x_") and UUID.fullmatch(f[2:])}
        for i in ids:
            m = meta.get(i, {})
            if i in led:
                sl, old = led[i]
                if not (old.get("rich") and old.get("stats") and (old.get("replay") or "").endswith(".repl26a")) or m.get("rich") and not old.get("rich"):
                    if better(old, build_row(i, m, d, vs)):
                        changed[sl] = None
                        nfill += 1
                continue
            if not m.get("opp"):
                continue  # no idea who it was against (stats files carry no team names); a later metadata file fills it
            row = build_row(i, m, d, vs)
            sl = slug(row["opp"], row.get("opp_id"))
            led[i] = (sl, row)
            changed[sl] = None
            nnew += 1
        seen[d] = s
    if fetch:
        lad = ladder()
        todo = [r for _, r in led.values() if not r.get("rich")][:fetch]
        cache = {}
        cp = f"{ROOT}/show_cache.jsonl"
        for ln in open(cp) if os.path.exists(cp) else []:
            try:
                x = json.loads(ln)
                cache[x["matchId"]] = x
            except (ValueError, KeyError):
                pass
        with open(cp, "a") as cf:
            for r in todo:
                if r["id"] not in cache:
                    try:
                        x = json.loads(plat(["matches", "show", r["id"], "--json"]).stdout)
                    except (subprocess.TimeoutExpired, ValueError):
                        continue
                    x = x.get("match", x) if isinstance(x, dict) else {}
                    if x.get("matchId"):
                        cache[r["id"]] = x
                        cf.write(json.dumps(x) + "\n")
                m = rich(cache.get(r["id"], {}))
                if m and better(r, m):
                    changed[led[r["id"]][0]] = None
                    nfill += 1
    # one ledger per team, keyed by the platform team id: rows without one (old matches.txt sets) take the id of a platform record
    # with the same name; the ledger is named after the team's current ladder name (a rename moves it: 'newer team' -> pantheon)
    id_of = {}
    for _, r in sorted(led.values(), key=lambda x: x[1].get("utc") or ""):
        if r.get("opp_id") and r.get("opp"):
            id_of.setdefault(slug(r["opp"]), r["opp_id"])
    lad = ladder()  # 4 Nov: refreshed hourly, so a rename moves the ledger to the new name's slug at the next update
    slug_of_id = {t["teamId"]: slug(t["name"], t["teamId"]) for t in lad.get("teams", []) if t.get("teamId")}  # the ladder's current name
    def fix(sl, r):  # 4 Nov: a dir from the old salted hash() slug (team_<digits>) is re-derived; 'Team 1' gives team_1 either way
        return slug(r.get("opp"), r.get("opp_id")) if re.fullmatch(r"team_\d+", sl) else sl

    for sl, r in sorted(led.values(), key=lambda x: x[1].get("utc") or "~"):
        if not r.get("opp_id") and id_of.get(slug(r.get("opp"))):
            r["opp_id"] = id_of[slug(r["opp"])]
            changed[sl] = None
        if r.get("opp_id"):
            slug_of_id.setdefault(r["opp_id"], fix(sl, r))
    by = collections.defaultdict(list)
    for sl, r in led.values():
        by[slug_of_id.get(r.get("opp_id")) or fix(sl, r)].append(r)
    moved = {sl for sl, r in led.values()} - set(by)
    # 4 Nov: also a ledger dir none of whose games is assigned to it any more (every id lives in another ledger: the old
    # per-run hash() slugs left such duplicates); set aside below, never deleted
    moved |= {os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{ROOT}/*/games.jsonl")} - set(by)
    write_ledgers({sl: by[sl] for sl in by if rebuild or sl in changed or moved or not os.path.exists(f"{ROOT}/{sl}/games.jsonl")})
    for sl in moved:  # its games now live in another team's ledger: set the old file aside (never deleted)
        if os.path.exists(f"{ROOT}/{sl}/games.jsonl"):
            os.makedirs(f"{ROOT}/_merged", exist_ok=True)
            dst = f"{ROOT}/_merged/{sl}.jsonl"
            if os.path.exists(dst):  # never overwrite an earlier set-aside file
                dst = f"{ROOT}/_merged/{sl}.{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}.jsonl"
            os.replace(f"{ROOT}/{sl}/games.jsonl", dst)
    st["last"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jsave(f"{ROOT}/state.json", st)
    if not quiet or nnew or nfill:
        print(f"teamdata update: {nsets} set(s) scanned, {nnew} new game(s), {nfill} filled; {len(led)} games, {len(by)} teams; "
              f"{time.time() - t0:.0f} s -> {ROOT}")


# ---------- report ----------

def wilson(w, n, z=1.96):
    if not n:
        return "-"
    p = w / n
    c = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    m = (p + z * z / (2 * n)) / (1 + z * z / n)
    return f"{100 * p:.0f}% [{max(0, 100 * (m - c)):.0f}, {min(100, 100 * (m + c)):.0f}]"


def wl(rs):
    w = sum(r.get("result") == "win" for r in rs)
    l = sum(r.get("result") == "loss" for r in rs)
    return w, l


def row_wl(label, rs):
    w, l = wl(rs)
    return f"| {label} | {w}-{l} | {wilson(w, w + l)} |"


def mean(rs, k):
    xs = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
    return f"{sum(xs) / len(xs):.1f}" if xs else "-"


def band(v):
    n = vnum(v)
    return f"v{n // 10 * 10}-{n // 10 * 10 + 9}" if n is not None else "unknown"


def table(title, groups, minn=1, sort=None):
    out = [f"\n### {title}\n", "| | W-L | win% [95% CI] |", "|---|---|---|"]
    items = [(k, v) for k, v in groups.items() if len(v) >= minn]
    items.sort(key=sort or (lambda kv: -len(kv[1])))
    out += [row_wl(k, v) for k, v in items]
    return out if items else []


def load_team(sl):
    p = f"{ROOT}/{sl}/games.jsonl"
    return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []


def resolve(name, lad):
    """A team name/slug -> ledger slug: by the ladder's team id first (teams rename: 'newer team' -> 'Pantheon'), then slug,
    then a unique slug prefix."""
    have = [os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{ROOT}/*/games.jsonl")]
    tid = name.lower() if teams.is_id(name) else teams.TEAMS.get(name.lower())  # 4 Nov: a teamId or a teams.py key directly
    tid = tid or next((t["teamId"] for t in lad.get("teams", []) if t.get("name") == name or slug(t.get("name")) == slug(name)), None)
    cur = next((t["name"] for t in lad.get("teams", []) if t.get("teamId") == tid), None) if tid else None
    if cur and slug(cur, tid) in have:  # the ledger dir is named after the current ladder name
        return slug(cur, tid)
    if tid:
        for h in have:
            with open(f"{ROOT}/{h}/games.jsonl") as f:
                for ln in f:
                    if f'"opp_id": "{tid}"' in ln:
                        return h
    s = slug(name)
    if s in have:
        return s
    pre = [h for h in have if h.startswith(s)]
    return pre[0] if len(pre) == 1 else None


def report_team(sl, intl, lad=None):
    rs = load_team(sl)
    if not rs:
        return None
    name = max((r for r in rs if r.get("opp")), key=lambda r: r.get("utc") or "", default={}).get("opp") or sl
    tid = next((r["opp_id"] for r in rs if r.get("opp_id")), None)
    cur = next((t["name"] for t in (lad or {}).get("teams", []) if tid and t.get("teamId") == tid), None)
    name = (f"{cur} (team {tid})" if cur == name else f"{cur} (was '{name}'; team {tid})") if cur else name  # 4 Nov: current name by id
    rk = [r for r in rs if r.get("kind") == "ranked"]
    un = [r for r in rs if r.get("kind") != "ranked"]
    L = [f"# {US} v {name}", "", f"_{len(rs)} games in /data/zw4424/st/teams/{sl}/games.jsonl ({len(rk)} ranked, {len(un)} unranked/"
         f"designed); written {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%MZ} by tools/lab/teamdata.py. Quality rows are RANKED only; "
         "unranked sets are designed games (our worst maps, chosen opponents), shown apart._"]
    if sl in intl:
        L.append("\nInternational (top_intl.txt).")
    w, l = wl(rk)
    uw, ul = wl(un)
    L += ["", "## Summary", "", "| | W-L | win% [95% CI] |", "|---|---|---|", row_wl("ranked", rk), row_wl("unranked (designed)", un)]
    if rk:
        L += ["", "Ranked means per game (us / them): score " + mean(rk, "us") + " / " + mean(rk, "them") + "; deaths "
              + mean(rk, "deaths_us") + " / " + mean(rk, "deaths_them") + "; kills " + mean(rk, "kills_us") + " / "
              + mean(rk, "kills_them") + "; gold earned " + mean(rk, "gold_earned_us") + " / " + mean(rk, "gold_earned_them")
              + "; gems collected " + mean(rk, "gems_collected_us") + " / " + mean(rk, "gems_collected_them") + "; fuel cuts "
              + mean(rk, "fuel_cuts_us") + " / " + mean(rk, "fuel_cuts_them") + "; rounds " + mean(rk, "rounds") + "."]
        g = collections.defaultdict(list)
        for r in rk:
            g[band(r.get("ver"))].append(r)
        L += table("Ranked by version band (trend)", g, sort=lambda kv: kv[0])
        g = collections.defaultdict(list)
        for r in rk:
            g[r.get("side") or "?"].append(r)
        L += table("Ranked by our side", g)
        g = collections.defaultdict(list)
        for r in rk:
            g[r.get("map") or "?"].append(r)
        rate = lambda kv: (wl(kv[1])[0] / max(1, sum(wl(kv[1]))), -len(kv[1]))
        L += table("Ranked worst maps (n >= 2)", g, minn=2, sort=rate)[:3 + 10]
        L += table("Ranked best maps (n >= 2, at least one win)", {k: v for k, v in g.items() if wl(v)[0]}, minn=2,
                   sort=lambda kv: (-rate(kv)[0], rate(kv)[1]))[:3 + 10]
        L += table("Ranked by map (all)", g, sort=lambda kv: kv[0])
        g = collections.defaultdict(list)
        for r in rk:
            g[" ".join(sorted(r.get("ours") or [])) or "?"].append(r)
        L += table("Ranked by our lineup", g)
        g = collections.defaultdict(list)
        for r in rk:
            g[" ".join(sorted(r.get("theirs") or [])) or "?"].append(r)
        L += table("Ranked by their lineup", g)
        kc = collections.Counter(k for r in rk for k in set(r.get("theirs") or []))
        if kc:
            L += ["", "Their picks (share of ranked games): " + ", ".join(f"{k} {100 * n / len(rk):.0f}%" for k, n in kc.most_common())]
    if un:
        g = collections.defaultdict(list)
        for r in un:
            g[r.get("map") or "?"].append(r)
        L += table("Unranked (designed) by map", g, sort=lambda kv: kv[0])
    L += ["", "## Recent games", "", "| utc | kind | ver | map | side | result | score | ours | theirs | replay |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rs, key=lambda r: r.get("utc") or "", reverse=True)[:20]:
        L.append(f"| {(r.get('utc') or '?')[:16]} | {r.get('kind') or '?'} | {r.get('ver') or '?'} | {r.get('map')} | {r.get('side')} | "
                 f"{r.get('result')} | {r.get('us', '?')}-{r.get('them', '?')} | {' '.join(r.get('ours') or [])} | "
                 f"{' '.join(r.get('theirs') or [])} | [vis]({VIS}{r['id']}) {r.get('replay') or ''} |")
    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/{sl}.md", "w").write("\n".join(L) + "\n")
    return dict(slug=sl, name=name, rk=(w, l), un=(uw, ul), n=len(rs), last=max((r.get("utc") or "" for r in rs), default=""))


def intl_list():
    p = f"{ROOT}/top_intl.txt"
    return [ln.split("#")[0].strip() for ln in open(p) if ln.split("#")[0].strip()] if os.path.exists(p) else []


def ladder_top(lad, n=10, intl_only=False):
    out = []
    for t in sorted(lad.get("teams", []), key=lambda t: t.get("rank", 1e9)):
        if t.get("name") == US or t.get("teamId") == teams.US_ID or t.get("isDev"):
            continue
        if intl_only and not any("International" in (q.get("name") or "") for q in t.get("qualifications") or []):
            continue
        out.append(t)
    return out[:n]


def report(a):
    lad = ladder()
    intl = {resolve(n, lad) for n in intl_list()} - {None}
    if "--top10" in a:
        names = [t["teamId"] for t in ladder_top(lad)]
    elif "--intl" in a:
        names = intl_list()
    elif "--all" in a:
        names = [os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{ROOT}/*/games.jsonl")
                 if sum(1 for _ in open(p)) >= 10]
    else:
        names = [x for x in a if not x.startswith("--")]
    names = [i for n in names for i in (teams.GROUPS.get(n.upper()) or [n])]  # 4 Nov: groups (TOP3) expand to team ids
    done, miss = [], []
    for n in names:
        sl = resolve(n, lad)
        r = report_team(sl, intl, lad) if sl else None
        (done.append(r) if r else miss.append(n))
    # index over every team in the ledger (a file per team only for those reported)
    rank = {t["teamId"]: (t.get("rank"), t["name"]) for t in lad.get("teams", [])}
    rank.update({slug(t["name"], t["teamId"]): (t.get("rank"), t["name"]) for t in lad.get("teams", []) if t["teamId"] not in rank})
    rows = []
    for p in glob.glob(f"{ROOT}/*/games.jsonl"):
        sl = os.path.basename(os.path.dirname(p))
        rs = [json.loads(ln) for ln in open(p)]
        rk = [r for r in rs if r.get("kind") == "ranked"]
        un = [r for r in rs if r.get("kind") != "ranked"]
        w, l = wl(rk)
        uw, ul = wl(un)
        name = max((r for r in rs if r.get("opp")), key=lambda r: r.get("utc") or "", default={}).get("opp") or sl
        tid = next((r["opp_id"] for r in rs if r.get("opp_id")), None)
        rk_, nm = rank.get(tid) or rank.get(sl) or (9999, name)
        rows.append((rk_ or 9999, sl, nm, w, l, uw, ul, max((r.get("utc") or "" for r in rs), default=""), mean(rk, "fuel_cuts_them"), mean(rk, "fuel_cuts_us")))
    rows.sort()
    I = [f"# {US} v each team", "", f"_Ledger /data/zw4424/st/teams/<team>/games.jsonl, {sum(r[3] + r[4] + r[5] + r[6] for r in rows)} decided games v "
         f"{len(rows)} teams; ladder {lad.get('utc', '?')}; written {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%MZ}. Refresh: "
         "`python3 -I tools/lab/teamdata.py update && python3 -I tools/lab/teamdata.py report --intl`. Ranked = quality; "
         "unranked = designed sets. I = top_intl.txt._", "",
         "| rank | team | I | ranked W-L | ranked win% [95% CI] | unranked W-L | their fuel cuts/game | ours | last game | page |",
         "|---|---|---|---|---|---|---|---|---|---|"]  # 8 Nov (owner): fuel cut-offs per game in our ranked games v them (statistics fuelExhausted)
    have = {os.path.basename(p)[:-3] for p in glob.glob(f"{OUT}/*.md")}
    for rk_, sl, name, w, l, uw, ul, last, fc_them, fc_us in rows:
        if w + l + uw + ul == 0:
            continue
        I.append(f"| {rk_ if rk_ < 9999 else '-'} | {name} | {'I' if sl in intl else ''} | {w}-{l} | {wilson(w, w + l)} | {uw}-{ul} | {fc_them} | {fc_us} | "
                 f"{last[:10]} | {f'[{sl}.md]({sl}.md)' if sl in have else ''} |")
    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/index.md", "w").write("\n".join(I) + "\n")
    print(f"teamdata report: {len(done)} team page(s) + index -> {OUT}/index.md" + (f"; no games v: {', '.join(miss)}" if miss else ""))


def intl(a):
    lad = ladder(force=True)
    top = ladder_top(lad, n=40, intl_only=True)
    us = next((t for t in lad.get("teams", []) if t.get("name") == US), {})
    print(f"ladder {lad.get('utc')}: 'International Qualifiers' carried by {sum(any('International' in (q.get('name') or '') for q in t.get('qualifications') or []) for t in lad.get('teams', []))}"
          f" of {len(lad.get('teams', []))} teams; {US} (rank {us.get('rank')}) has {[q['name'] for q in us.get('qualifications', [])]}")
    for t in top[:10]:
        print(f"  {t['rank']:>3} {t['name']} {t['rating']:.0f}")
    if "--write" in a:
        p = f"{ROOT}/top_intl.txt"
        if os.path.exists(p):
            os.replace(p, p + ".old")
        with open(p, "w") as f:
            f.write(f"# top 10 international teams (ladder flag 'International Qualifiers', {lad.get('utc')}); one teamId per line "
                    "(names change; '# name' is a comment, a bare name still works); edit freely\n")
            f.write("".join(f"{t['teamId']}  # {t['name']}\n" for t in top[:10]))
        print(f"wrote {p}")


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("update", "report", "intl"):
        sys.exit(__doc__)
    {"update": update, "report": report, "intl": intl}[a[0]](a[1:])


if __name__ == "__main__":
    main()
