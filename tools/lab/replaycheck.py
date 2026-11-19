#!/usr/bin/env python3
"""replaycheck: did a fix change the bug, on the very game that showed it? (Tool builder, 6 Nov; owner idea via the Builder). A short list of games (owner, critical) with the
bug's round and a test. Keep the list small: /data/zw4424/st/bq/replaycheck.json.
usage: python3 -I tools/lab/replaycheck.py list
       python3 -I tools/lab/replaycheck.py add MATCH_ID ROUND ["TEST"] --note "THE FLAW" [--fix FIX]   reads match, group, foe team, map and our seat (`matches show`, read only)
       python3 -I tools/lab/replaycheck.py fix MATCH_ID[@ROUND] FIX                       the change meant to cure this flaw. FIX: FLAG=V (those bits on in the live bot), vNNN, or a bot name
       python3 -I tools/lab/replaycheck.py track [--dry]                                  the tracker's pass (critgame's auto loop runs it every 15 min; off: touch LIST.OFF)
       python3 -I tools/lab/replaycheck.py waiting                                        flaws no fix is linked to, as critgame.py status prints them
       python3 -I tools/lab/replaycheck.py close MATCH_ID[@ROUND] [TEXT]                  stop tracking a flaw (the row stays, state closed)
       python3 -I tools/lab/replaycheck.py run BOT [MATCH_ID ...]                         puppet.py v the recorded foe; every listed game by default
       python3 -I tools/lab/replaycheck.py rematch MATCH_ID [--maps M2,M3,M4,M5] [--go]      LIVE ONLY, once per ship: prints the command; --go queues it. No --maps: the original group's maps and seats
       python3 -I tools/lab/replaycheck.py rematches MATCH_ID                             original v rematch results side by side
TEST: one or more, joined by ';':
      reversal R1 R2      our bodies' A-B-A steps in those rounds (a step straight back)      e.g. reversal 1 5
      camphits KIT R      KIT's hits on camps through round R (farming)                       e.g. camphits marcella 200
      foebag KIT R1 R2    the most gems KIT carried on a turn in the foe half in those rounds (0: banked first, or stayed home)   e.g. foebag prism 520 561
run prints: first round each team differs; the test on the real game and the re-play; CHANGED or SAME. What it can't say, printed each time: the puppet repeats the foe's recorded
moves, so a re-play is exact only until the first difference; past it the foe does not react. A first difference after the bug's round means the bot played that game unchanged there.
rematch: match-groups create with --source-group, so the foe plays the same bot version. Five games: the original map in the original seat (reproduces the game if our bot did not
matter), the original map in the other seat, three other maps. A real, unranked, quota-using platform group: never a candidate (it refuses any bot but live) and one per ship per game.
TRACKER (owner 7 Nov: 'when we find a flaw from a replay ... if the change related to the replay is live, we can retest using the game ID ... make the analyst re-analyse if we lost').
A flaw is a row: game, round, note, fix. `track` does nothing for it until its fix is in the live bot, then, once per fix:
  retest: one group v the same foe bot (--source-group) on the original group's five maps and seats, so the flaw's game is repeated by the real foe, who reacts. No puppet: past the
    first difference a puppet foe does not react and collapses (01a1b2c2 and 01a1b2c6 re-plays: foe tributed 0 and we 'won' 1001-0, 1102-0, v real foes who tributed 1024 and 1250).
  won: closed as won. lost: the new game is flagged in critgame (prio high, LIGHT: one walker, no grill) on the first round it left the old game and on the flaw's round, so it tops
    the analysts' queue. When its verdicts are in, the row reads 'reviewed': name the next fix (`fix`) or `close` it.
A new live links itself (owner 7 Nov: 'when a replay fix is live, the analysts run their live game again'): the flags that ship changed are read once, and a nofix or reviewed flaw whose
note names one (GDM for GDM_BITS, a whole word) takes it as its fix. Anything else stays listed at the top of `critgame.py status` until it has a fix or is closed: a flaw with no link is never retested.
states: nofix, fixwait, queued, won, reanalysis, reviewed, closed. One win is one game v one foe: it says this game was cured, not that the flaw is gone. Every group is logged in builder_queue.md."""
import calendar
import contextlib
import fcntl
import glob
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
LAB = f"{REPO}/tools/lab"
sys.path.insert(0, LAB)
LIST = os.environ.get("REPLAYCHECK_LIST", "/data/zw4424/st/bq/replaycheck.json")
OUT = "/data/zw4424/st/replaycheck"
CLI = "/data/zw4424/cambc400/bin/cambc400"
LIVE = "/data/zw4424/st/bq/live.txt"
QUEUE = "/homes/zw4424/condor-work/reports/builder_queue.md"
PER_PASS = 2     # retests queued in one pass: five unranked games each, on the shared quota
SHIP = LIST + ".ship"  # the last live the tracker read: {live, bot, flags that ship changed}
STALE_H = 12     # a group not finished after this long is reported, not waited on silently
NOTE = "exact only until the first difference: past it the foe's recorded moves do not react to ours"


def plat(*a):
    r = subprocess.run(["sh", f"{LAB}/platlock.sh", CLI, *a], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"replaycheck: {' '.join(a[:2])}: {(r.stdout + r.stderr).strip()[-200:]}")
    return r.stdout


def load():
    return json.load(open(LIST)) if os.path.exists(LIST) else []


def save(rows):
    with open(LIST + ".tmp", "w") as f:
        json.dump(rows, f, indent=1)
    os.replace(LIST + ".tmp", LIST)


@contextlib.contextmanager
def locked():
    """a read-change-write of the list: `add` and `track` must not lose each other's rows"""
    with open(LIST + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        yield


def find(rows, mid):
    mid, _, rnd = mid.partition("@")
    hit = [r for r in rows if r["id"].startswith(mid) and (not rnd or r["round"] == int(rnd))]
    if len(hit) != 1:
        sys.exit(f"replaycheck: {mid}: {len(hit)} rows match (several flaws in a game: ID@ROUND)")
    return hit[0]


def key(r):
    return f"{r['id'][:8]}@{r['round']}"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg):
    """the tracker's own log, plus builder_queue.md (owner: log every unranked game and why) unless this is a test list"""
    line = f"{stamp()} replaycheck {msg}"
    print(line, flush=True)
    with open(LIST + ".log", "a") as f:
        f.write(line + "\n")
    if not os.environ.get("REPLAYCHECK_LIST"):
        with open(QUEUE, "a") as f:
            f.write(line + "\n")


def state(r):
    return r.get("state") or ("fixwait" if r.get("fix") else "nofix")


def fix_form(fix):
    if not re.fullmatch(r"v\d+|nova_\w+|[A-Z][A-Z0-9_]*=\d+", fix):
        sys.exit(f"replaycheck: FIX {fix!r}: use FLAG=V, vNNN or a bot name")
    return fix


def fix_live(fix):
    """(is the fix in the live bot, why). A flag is read from the live bot's source, so a later ship can't hide it and a rollback undoes it."""
    ver, bot = live()
    if "=" in fix:
        name, want = fix.split("=")
        want = int(want)
        vals = []
        for p in glob.glob(f"{REPO}/bots/{bot}/src/*"):
            with open(p, errors="ignore") as f:
                vals += re.findall(rf"^\s*#\s*define\s+{name}\s+\(?(0x[0-9a-fA-F]+|\d+)\)?\s*(?://.*)?$", f.read(), re.M)
        if not vals:
            return False, f"{name} not in {bot}"
        got = int(vals[0], 0)
        return got & want == want, f"{name}={got} in {ver} {bot}"
    hit = next((p for p in (ln.split() for ln in open(LIVE)) if len(p) >= 2 and fix in p[:2]), None)
    if not hit:
        return False, f"{fix} has not shipped"
    return int(ver[1:]) >= int(hit[0][1:]), f"{fix} = {hit[0]}, live {ver}"


def live():
    a = open("/data/zw4424/st/bq/live.txt").readline().split()
    return a[0], a[1]


def score(path, us, test):
    """the test's number on a replay"""
    import replay
    g = replay.load(path, us=us)
    w = test.split()
    mine = [c for c in g.bodies if g.team_of[c] == g.us]
    if w[0] == "reversal":
        lo, hi, n = int(w[1]), int(w[2]), 0
        for c in mine:
            ps = [(t[2], t[3]) for t in g.by_champ.get(c, []) if lo <= t[0] <= hi + 1]
            n += sum(1 for i in range(2, len(ps)) if ps[i] == ps[i - 2] and ps[i] != ps[i - 1])
        return n
    if w[0] == "camphits":
        r = int(w[2])
        return sum(len(replay.camp_hits(g, t) or []) for c in mine if w[1].lower() in g.who(c).lower() for t in g.by_champ.get(c, []) if t[0] <= r)
    if w[0] == "foebag":
        lo, hi = int(w[2]), int(w[3])
        return max([t[8] for c in mine if w[1].lower() in g.who(c).lower() for t in g.by_champ.get(c, [])
                    if lo <= t[0] <= hi and t[g.ci["alive"]] and g.zone(t[2], t[3], g.team_of[c]) == "enemy"] or [0])
    sys.exit(f"replaycheck: unknown test {test!r}")


def cmd_add(a):
    mid, rnd = a[0], int(a[1])
    test = a[2] if len(a) > 2 and not a[2].startswith("--") else ""
    note = a[a.index("--note") + 1] if "--note" in a else ""
    fix = fix_form(a[a.index("--fix") + 1]) if "--fix" in a else None
    m = json.loads(plat("matches", "show", mid, "--json"))["matches"][0]
    me = next((t for t in m["teams"] if t.get("name") == "BattleCats"), None)
    if me is None:
        sys.exit("replaycheck: BattleCats not in this match")
    foe = next(t for t in m["teams"] if t is not me)
    with locked():
        rows = [r for r in load() if (r["id"], r["round"]) != (m["matchId"], rnd)] + [dict(id=m["matchId"], group=m["groupId"], map=m["map"], seat=me["side"].upper(), foe=foe["teamId"], foe_name=foe["name"], round=rnd, test=test, note=note, rematches=[], fix=fix)]
        save(rows)
    print(json.dumps(rows[-1]))


def link(r, fix):
    if r.get("retest"):
        r.setdefault("retests", []).append(r.pop("retest"))
    r.update(fix=fix, state="fixwait")


def cmd_fix(a):
    fix = fix_form(a[1])
    with locked():
        rows = load()
        r = find(rows, a[0])
        if state(r) in ("queued", "reanalysis"):
            sys.exit(f"replaycheck: {key(r)} is {state(r)}: wait for it to finish")
        link(r, fix)
        save(rows)
    print(f"{key(r)}: fix {fix}: {fix_live(fix)[1]}")


def cmd_close(a):
    with locked():
        rows = load()
        r = find(rows, a[0])
        r.update(state="closed", closed=" ".join(a[1:]) or "by hand")
        save(rows)
    print(f"{key(r)}: closed")


def cmd_run(a):
    bot, rows = a[0], load()
    for r in ([find(rows, x) for x in a[1:]] or rows):
        d = f"{OUT}/{r['id'][:8]}_{bot}"
        p = subprocess.run([sys.executable, "-I", f"{LAB}/puppet.py", r["id"], "--us", r["seat"], "--bot", bot, "--dir", d], cwd=REPO, capture_output=True, text=True)
        diffs = re.findall(r"^\s+(.+?): first differs at r(\d+)", p.stdout, re.M)
        print(f"{r['id'][:8]} {r['map']} v {r['foe_name']} ({r['seat']}), bug r{r['round']}, test '{r['test']}', {bot}")
        if not os.path.exists(f"{d}/out.repl26a"):
            print(f"  NO RE-PLAY: {(p.stdout + p.stderr).strip()[-200:]}")
            continue
        first = min((int(x[1]) for x in diffs), default=None)
        print("  first difference: " + (", ".join(f"{n} r{k}" for n, k in diffs) or "none"))
        real = next((p2 for p2 in [f"/data/zw4424/puppet/{r['id'][:8]}/game.repl26a", f"{d}/game.repl26a"] + glob.glob(f"/data/zw4424/plat/*/x_{r['id']}*/replay.repl26a") if os.path.exists(p2)), None)
        for te in (x.strip() for x in r["test"].split(";") if x.strip()):
            a0, b0 = (score(real, r["seat"], te) if real else None), score(f"{d}/out.repl26a", r["seat"], te)
            print(f"  test '{te}': real {a0}, re-play {b0}: {'UNKNOWN (no original replay)' if a0 is None else 'SAME' if a0 == b0 else 'CHANGED'}")
        if first is not None and first <= r["round"]:
            print(f"  NOT EXACT at the bug: the re-play left the real game at r{first}, before r{r['round']}")
        if first is None or first > r["round"]:
            print(f"  the bot played this game unchanged through the bug's round r{r['round']}")
        print(f"  {NOTE}")


def group_games(gid):
    return json.loads(plat("match-groups", "show", gid, "--json"))["matches"]


def our_team(m):
    return next(t for t in m["teams"] if t.get("name") == "BattleCats")


def same_games(r):
    """the original group's five maps and our seat in each: every game of it is played again"""
    ms = group_games(r["group"])
    maps, sides = [m["map"] for m in ms], [our_team(m)["side"] for m in ms]
    if len(set(maps)) != 5 or r["map"] not in maps:
        sys.exit(f"replaycheck: group {r['group'][:8]} holds {maps}: not five maps with {r['map']}")
    return maps, sides


def rematch_cmd(r, maps, sides):
    return ["match-groups", "create", r["foe"], "--source-group", r["group"], "--maps", ",".join(maps), "--sides", ",".join(sides), "--json"]


def cmd_rematch(a):
    with locked():
        rows = load()
        r = find(rows, a[0])
        ver, bot = live()
        if ver in [x["live"] for x in r["rematches"]]:
            sys.exit(f"replaycheck: {r['id'][:8]} already has a rematch for {ver}")
        if "--maps" in a:
            if len(set(a[a.index("--maps") + 1].split(",")) - {r["map"]}) != 4:
                sys.exit("replaycheck: --maps needs four other maps (the platform wants five different maps, 6 Nov)")
            s, o = r["seat"].lower(), "b" if r["seat"] == "A" else "a"
            maps, sides = [r["map"]] + a[a.index("--maps") + 1].split(","), [s, o, s, o, s]
        else:
            maps, sides = same_games(r)
        cmd = rematch_cmd(r, maps, sides)
        print(f"live {ver} {bot}: {CLI} {' '.join(cmd)}")
        if "--go" not in a:
            print("dry: nothing queued (--go queues five unranked games on the shared quota)")
            return
        g = json.loads(plat(*cmd))
        r["rematches"].append(dict(live=ver, bot=bot, group=g.get("groupId") or g.get("id")))
        save(rows)
    print(json.dumps(r["rematches"][-1]))


def cmd_rematches(a):
    r = find(load(), a[0])
    print(f"original {r['id'][:8]} {r['map']} seat {r['seat']} v {r['foe_name']}: group {r['group']}")
    for x in r["rematches"]:
        print(f"{x['live']} {x['bot']}: group {x['group']}")
        print(plat("match-groups", "show", x["group"])[:800])


def queue_retest(r, rows, dry):
    """-> True if a group was queued (or shared with this game's other flaw): the fix is live and this fix has no retest yet"""
    ver, bot = live()
    twin = next((x for x in rows if x is not r and x["id"] == r["id"] and state(x) == "queued" and x["retest"]["live"] == ver), None)
    if twin:
        r["retest"] = dict(twin["retest"], fix=r["fix"])
        r["state"] = "queued"
        log(f"{key(r)} retest shares group {twin['retest']['group'][:8]} with {key(twin)}")
        return False
    maps, sides = same_games(r)
    cmd = rematch_cmd(r, maps, sides)
    if dry:
        print(f"dry {key(r)}: {r['fix']} is live ({ver}): would run {' '.join(cmd)}")
        return True
    g = json.loads(plat(*cmd))
    gid = g.get("groupId") or g.get("id")
    r["retest"] = dict(fix=r["fix"], live=ver, bot=bot, group=gid, t=stamp())
    r["rematches"].append(dict(live=ver, bot=bot, group=gid))
    r["state"] = "queued"
    log(f"{key(r)} retest queued: {r['fix']} is live in {ver} {bot}; group {gid} v {r['foe_name']} (5 unranked games: {r['map']} repeats flaw game {r['id']}): {r['note'][:80]}")
    return True


def compare_games(r, m):
    """(first round our game left the old one or None, last round, final score us-foe, what the tests read) from the two real replays"""
    import critgame as CG
    import puppet as P
    import replay
    foe_t = {"name": r["foe_name"]}
    old = replay.load(f"{CG.fetch_replay(r['id'], r['seat'].lower(), dict(map=r['map']), foe_t)}/replay.repl26a", r["seat"])
    path = f"{CG.fetch_replay(m['matchId'], r['seat'].lower(), m, foe_t)}/replay.repl26a"
    new = replay.load(path, r["seat"])
    if old.d["draft"] != new.d["draft"]:
        first = 1  # another lineup: bodies don't line up, so the games left each other at the draft
    else:
        first = min((v[0] for v in P.compare(old, new)[0].values()), default=None)
    sc = new.final.get("submitted") or [0, 0]
    tests = {}
    for te in (x.strip() for x in r.get("test", "").split(";") if x.strip()):
        tests[te] = [score(f"{CG.fetch_replay(r['id'], r['seat'].lower(), dict(map=r['map']), foe_t)}/replay.repl26a", r["seat"], te), score(path, r["seat"], te)]
    return first, new.last_round, [sc[new.us], sc[1 - new.us]], tests


def reanalyse(r, x):
    """hand the lost game to the analysts: critgame, prio high, one walker, on the rounds that can say whether the flaw is gone"""
    import critgame as CG
    mid = x["match"]
    wins = []
    if x["first"]:
        wins.append((x["first"], min(x["first"] + 30, x["rounds"])))
    if r["round"] <= x["rounds"]:
        wins.append((max(1, r["round"] - 10), min(r["round"] + 8, x["rounds"])))
    wins = wins or [(max(1, x["rounds"] - 30), x["rounds"])]
    why = (f"RETEST: fix {x['fix']} for flaw in {r['id'][:8]} r{r['round']} is live ({x['live']}), and the same game v the same foe bot was lost again {x['score'][0]}-{x['score'][1]}"
           f" ({'left the old game at r' + str(x['first']) if x['first'] else 'turn for turn the same game: the fix never fired here'}). Flaw: {r['note'][:160]}. "
           f"Is the flaw gone and something else lost it, or is it still there? Old findings: critgame.py status {r['id']}")
    d = CG.gdir(mid)
    mp = f"{d}/meta.json"
    cl = [sys.executable, "-I", f"{LAB}/critgame.py"]
    if os.path.exists(mp):  # the auto pass got there first: add our windows, don't re-cut its game
        for p, q in wins:
            subprocess.run(cl + ["addwin", mid, f"{p}-{q}", "--kind", "retest"], check=True, capture_output=True, text=True)
        meta = json.load(open(mp))
        meta.update(prio="high", why=why + " | " + meta["why"])
        with open(mp + ".tmp", "w") as f:
            json.dump(meta, f, indent=1)
        os.replace(mp + ".tmp", mp)
    else:
        subprocess.run(cl + ["flag", mid, "--why", why, "--us", r["seat"], "--by", "replaycheck", "--prio", "high", "--version", x["live"], "--light",
                             "--rounds", ",".join(f"{p}-{q}" for p, q in wins)], check=True, capture_output=True, text=True)
    x["crit"] = mid


def read_retest(r, rows):
    """the group finished: fill in the result and act on it"""
    x = r["retest"]
    ms = group_games(x["group"])
    if any(m.get("status") != "finished" for m in ms):
        if time.time() - calendar.timegm(time.strptime(x["t"], "%Y-%m-%dT%H:%M:%SZ")) > STALE_H * 3600 and not x.get("late"):
            x["late"] = True
            log(f"{key(r)} retest group {x['group'][:8]} not finished after {STALE_H} h")
        return
    m = next((q for q in ms if q["map"] == r["map"] and our_team(q)["side"].upper() == r["seat"]), None)
    if m is None:
        r["state"] = "reviewed"
        log(f"{key(r)} retest group {x['group'][:8]} has no {r['map']} game in seat {r['seat']}: nothing to read")
        return
    first, last, sc, tests = compare_games(r, m)
    res = our_team(m)["result"]
    others = [f"{q['map']} {our_team(q)['result']}" for q in ms if q is not m]
    x.update(match=m["matchId"], result=res, first=first, rounds=last, score=sc, tests=tests, others=others)
    say = f"{key(r)} retest {res} {sc[0]}-{sc[1]} on {r['map']} v {r['foe_name']} ({x['live']}, was a loss; game {m['matchId']}); {'left the old game at r' + str(first) if first else 'same game turn for turn'}; tests {tests or '-'}; others: {', '.join(others)}"
    if res == "win":
        r["state"] = "won"
        log(say + ". Closed as won: one game, not proof the flaw is gone")
    else:
        reanalyse(r, x)
        r["state"] = "reanalysis"
        log(say + ". Flagged in critgame for the analysts")


def reviewed(r):
    """every window of the flagged game has its verdict"""
    import critgame as CG
    d, meta = CG.load_meta(r["retest"]["crit"])
    return all(CG.window_state(d, w["n"])[0] == "DONE" for w in meta["windows"])


def flaw_names(r):
    return set(re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", r["note"]))


def last_ship():
    try:
        with open(SHIP) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ship_pass(rows, dry):
    """Once per new live: open flaws that name a flag this ship changed take it as their fix. A rollback only moves the mark; fix_live reads the live bot, so it undoes a link's effect."""
    ver, bot = live()
    old = last_ship()
    if old and old["live"] == ver:
        return
    own = {}
    if old and int(ver[1:]) > int(old["live"][1:]):
        import shipcheck as sc
        a, b = sc.flag_values(old["bot"]), sc.flag_values(bot)
        if a is None or b is None:
            raise RuntimeError(f"no flag tables for {old['bot']} or {bot}")
        own = {k: str(v) for k, v in b.items() if a.get(k, "0") != v and re.fullmatch(r"[1-9]\d*", str(v))}
    for r in rows:
        if state(r) in ("nofix", "reviewed"):
            hit = next((f"{k}={v}" for k, v in own.items() if re.sub(r"_(BITS|ON|EN)$", "", k) in flaw_names(r)), None)
            if hit and dry:
                print(f"dry {key(r)}: would link {hit} (shipped in {ver})")
            elif hit:
                link(r, hit)
                log(f"{key(r)} linked to {hit}: {ver} changed that flag and the flaw's note names it")
    if not dry:
        with open(SHIP + ".new", "w") as f:
            json.dump(dict(live=ver, bot=bot, flags=own), f)
        os.replace(SHIP + ".new", SHIP)


def waiting():
    """-> lines for the analysts' queue: nothing retests these flaws until a fix is linked"""
    rows = [r for r in load() if state(r) in ("nofix", "reviewed")]
    if not rows:
        return []
    s = last_ship()
    shipped = f"; {s['live']} changed {' '.join(f'{k}={v}' for k, v in list(s['flags'].items())[:6]) or 'no flag'}" if s else ""
    return [f"{len(rows)} flaw(s) with no fix linked: never retested until linked. replaycheck.py fix ID FLAG=V (or close ID){shipped}"] + \
           [f"FLAW {state(r):8s} {key(r)} {r['map']}: {r['note'][:110]}" for r in rows]


def cmd_track(a):
    dry = "--dry" in a
    if os.path.exists(LIST + ".OFF"):
        print(f"replaycheck track: {LIST}.OFF present, skipping")
        return
    with locked():
        rows = load()
        sent = 0
        try:
            ship_pass(rows, dry)
        except (Exception, SystemExit) as e:  # noqa: BLE001  the mark did not move, so the next pass reads this ship again
            log(f"ship pass failed: {str(e)[:200]!r}")
        for r in rows:
            try:
                st = state(r)
                if st == "fixwait" and sent < PER_PASS:
                    ok, why = fix_live(r["fix"])
                    if ok:
                        sent += queue_retest(r, rows, dry)
                    elif dry:
                        print(f"dry {key(r)}: waiting: {why}")
                elif st == "queued" and not dry:
                    read_retest(r, rows)
                elif st == "reanalysis" and reviewed(r):
                    r["state"] = "reviewed"
                    log(f"{key(r)} re-analysis done: read critgame.py status {r['retest']['crit']}, then `fix` the next change or `close`")
            except (Exception, SystemExit) as e:  # noqa: BLE001  one bad row must not stop the others; it is tried again next pass
                log(f"{key(r)} track failed: {str(e)[:200]!r}")
            if not dry:
                save(rows)  # a queued group is written down before the next row can fail


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "list":
        for r in load():
            x = r.get("retest") or {}
            print(f"{state(r):10s} {key(r)} {r['map']} seat {r['seat']} v {r['foe_name']} fix {r.get('fix') or '-'} '{r['test']}' {r['note']}"
                  + (f" | retest {x['live']} group {x['group'][:8]}" if x else "") + (f": {x['result']} {x['score'][0]}-{x['score'][1]}, game {x['match']}" if x.get("result") else ""))
    elif a[0] == "waiting":
        print("\n".join(waiting()))
    else:
        {"add": cmd_add, "run": cmd_run, "rematch": cmd_rematch, "rematches": cmd_rematches, "fix": cmd_fix, "close": cmd_close, "track": cmd_track}[a[0]](a[1:])


if __name__ == "__main__":
    main()
