#!/usr/bin/env python3
"""critretest: re-play OPEN critical games from older versions on the current live, same map, side and team (owner 8 Nov, via the Coordinator).
A win closes the game only when the foe drafted the same lineup as in the old game (owner 9 Nov ~20:30Z: a pair whose foe lineup differs is not a
same-map comparison; such a game stays OPEN, counted as 'lineup mismatch'); a loss flags the new match as a fresh critical game on the new version and closes the old one. Games an analyst has claimed are re-played
but left open, with the result in the report. Games are pooled by team, 5 different maps a group (the platform wants 5; a short group is padded and padded games don't count).
The match quota is a rolling window shared with the climbs: groups are only created while used < CRT_ROOM (90).

usage: python3 -I tools/lab/critretest.py plan            what would be played
       python3 -I tools/lab/critretest.py run             play it, apply results, write the report (one at a time; resumes from its state)
State and report: /data/USER/st/crit_retest/{state.json,report.txt,log}."""
import collections
import concurrent.futures as cf
import fcntl
import json
import os
import random
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
DIR = "/data/USER/st/crit_retest"
sys.path.insert(0, REPO + "/tools/lab")
import ladderclimb as L  # noqa: E402

ROOM = int(os.environ.get("CRT_ROOM", 90))
WALL = int(os.environ.get("CRT_WALL", 6 * 3600))
STATE = DIR + "/state.json"


def log(m):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + m
    print(line, flush=True)
    with open(DIR + "/log", "a") as f:
        f.write(line + "\n")


def crit(args, timeout=1800):
    return subprocess.run([sys.executable, "-I", "tools/lab/critgame.py"] + args, cwd=REPO, capture_output=True, text=True, timeout=timeout)


def parse(why):
    """(team name, map) from a flag's why text"""
    m = re.search(r"lost to rank \d+ (.+?) on (\S+) under ", why)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r" on (\S+) to (.+?) \(rating", why)
    return (m.group(2), m.group(1)) if m else (None, None)


def plan():
    """-> (groups [{team, games: [{map, side, ids: [...]}]}], skipped [(id, why)], live version)"""
    live = L.active_version()
    ids = re.findall(r"^OPEN\s+(\S+)", crit(["status"]).stdout, re.M)
    teams = {t["name"]: t for t in L.ladder()[0]}
    want, skipped = {}, []
    for g in ids:
        try:
            d = json.load(open(f"/data/USER/st/crit/{g}/meta.json"))
        except (OSError, ValueError):
            skipped.append((g, "no meta"))
            continue
        if d.get("version") == live:
            continue
        name, mp = parse(d.get("why", ""))
        if not name or name not in teams:
            skipped.append((g, f"team not on the ladder: {name}"))
            continue
        side = (d.get("us") or "").lower()
        if side not in ("a", "b"):
            skipped.append((g, "side unknown"))
            continue
        want.setdefault((name, mp, side), []).append(dict(id=g, old=d.get("version"), owner=d.get("owner")))
    by = collections.defaultdict(list)
    tm = {}
    for (name, mp, side), games in want.items():
        by[name].append(dict(map=mp, side=side, games=games))
        tm[name] = dict(teamId=teams[name]["teamId"], name=name, rank=teams[name].get("rank"))
    return pack(by, tm), skipped, live


def pack(by, tm):
    """five different maps a group, per team"""
    groups = []
    for name, rows in sorted(by.items()):
        rows = rows[:]
        while rows:
            maps, cur, rest = set(), [], []
            for r in rows:
                if len(cur) < 5 and r["map"] not in maps:
                    cur.append(r)
                    maps.add(r["map"])
                else:
                    rest.append(r)
            rows = rest
            groups.append(dict(team=tm[name], games=cur))
    return groups


def puppet_same(x, side, bot):
    """Econ 8 Nov: most re-plays of a loss come back identical. Exact replay of the lost game with the current bot: True when our side plays it exactly as before, so a re-play can't flip it."""
    g = x["games"][0]["id"]
    try:
        r = subprocess.run([sys.executable, "-I", "tools/lab/puppet.py", g, "--us", side.upper(), "--bot", bot, "--dir", f"{DIR}/p/{g[:18]}"], cwd=REPO, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    if "ours: no difference" in r.stdout:
        return True
    return False if "ours: first differs" in r.stdout else None


def precheck(st):
    """check every case not yet played; those the current bot plays identically are set aside, the rest are re-pooled (cases that can't be checked are played)"""
    bot = next(ln.split()[1] for ln in open("/data/USER/st/bq/live.txt") if ln.startswith(st["live"] + " "))
    todo = [x for g in st["groups"] if not g.get("gid") for x in g["games"] if "check" not in x]
    log(f"precheck: {len(todo)} cases by exact replay on {bot}")

    def one(x):
        x["check"] = puppet_same(x, x["side"], bot)
        return x
    with cf.ThreadPoolExecutor(int(os.environ.get("CRT_PAR", 4))) as ex:
        for k, x in enumerate(ex.map(one, todo)):
            save(st)
            if not (k + 1) % 10:
                log(f"precheck: {k + 1}/{len(todo)}")
    by, tm = collections.defaultdict(list), {}
    for g in [g for g in st["groups"] if not g.get("gid")]:
        for x in g["games"]:
            if x.get("check") is True:
                st.setdefault("same", []).append(dict(team=g["team"]["name"], **x))
            else:
                by[g["team"]["name"]].append(x)
                tm[g["team"]["name"]] = g["team"]
    st["groups"] = [g for g in st["groups"] if g.get("gid")] + pack(by, tm)
    st["prechecked"] = True
    save(st)
    log(f"precheck done: {len(st.get('same', []))} set aside (no shipped change touched them); {sum(1 for g in st['groups'] if not g.get('gid'))} groups left to play")


def padded(g):
    used = {x["map"] for x in g["games"]}
    pool = [m for m in L.all_maps() if m not in used]
    random.shuffle(pool)
    return [dict(map=m, side=random.choice("ab")) for m in pool[:5 - len(g["games"])]]


def apply(st, g, rows):
    want = {(x["map"], x["side"]): x for x in g["games"]}
    for match, mp, side, result, _ in rows:
        x = want.get((mp, side))
        if not x or x.get("result"):
            continue
        x["result"], x["match"] = result, match
        won = result == "win"
        new = L.foe_lineup(match, side)  # group() above cached it: no extra platform call
        x["foe"] = list(new or [])
        for o in x["games"]:
            old = L.foe_lineup(o["id"], side)  # the old game's replay is on disk (critgame downloaded it); else one matches show
            o["lu"] = L.same_foe(old, new)
            o["foe"] = list(old or [])
            if o["lu"] != "match":  # owner 9 Nov ~20:30Z: not a same-map comparison; the old game stays OPEN either way
                log(f"{o['id'][:13]}: lineup mismatch: not a same-map comparison ({result} on {st['live']} v foe {L.lineup_txt(new)}, "
                    f"the old game had {L.lineup_txt(old)}{', unknown' if o['lu'] == 'unknown' else ''}); left open")
                continue
            if o.get("owner"):
                log(f"{o['id'][:13]} claimed by {o['owner']}: {result} on {st['live']}, left open")
                continue
            crit(["close", o["id"], f"critretest: {'re-won' if won else 're-lost'} on {st['live']} ({match}, same foe lineup)", "--who", "critretest"])
        if not won:
            mis = [o for o in x["games"] if o.get("lu") != "match"]
            why = (f"critretest: lost again to {g['team']['name']} on {mp} under {st['live']} (was an OPEN loss on "
                   f"{', '.join(sorted({str(o['old']) for o in x['games']}))}"
                   + (f"; {len(mis)} of them under another foe lineup, left open" if mis else "")
                   + "): a loss on the current version, find the flaw (critical)")
            r = crit(["flag", match, "--us", side.upper(), "--prio", "high", "--by", "critretest", "--version", st["live"], "--why", why])
            log(f"re-lost {mp} v {g['team']['name']}: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[0][:140])


def report(st):
    res = [(g["team"]["name"], x) for g in st["groups"] for x in g["games"]]
    n = [x for _, x in res if x.get("result")]
    won = [x for x in n if x["result"] == "win"]
    same = st.get("same", [])
    og = [o for x in n for o in x["games"]]
    lu = collections.Counter(o.get("lu", "unknown") for o in og)
    out = [f"critretest on {st['live']}: {len(res)} distinct map/side/team cases played, covering {sum(len(x['games']) for _, x in res)} OPEN games; "
           f"{len(won)} won ({sum(any(o.get('lu') == 'match' for o in x['games']) for x in won)} of them re-won under the same foe lineup), {len(n) - len(won)} lost again, {len(res) - len(n)} no result; {len(same)} more not played: no shipped change touched this game (still OPEN)",
           f"  foe lineup (owner 9 Nov: same-map pairs must match it): {lu['match']} of {len(og)} played OPEN games matched n (closed unless claimed), "
           f"{lu['mismatch']} dropped for lineup mismatch, {lu['unknown']} lineup unknown (both left OPEN: not a same-map comparison)"]
    for name, k in collections.Counter(x["team"] for x in same).most_common():
        out.append(f"  no change: {name}: {k}")
    for name in sorted({t for t, _ in res}):
        xs = [x for t, x in res if t == name]
        w = sum(x.get("result") == "win" and any(o.get("lu") == "match" for o in x["games"]) for x in xs)
        lost = [x["map"] for x in xs if x.get("result") and x["result"] != "win"]
        wm = sum(x.get("result") == "win" for x in xs) - w
        out.append(f"  {name}: {w}/{len(xs)} won under the same foe lineup" + (f" (+{wm} won under another lineup, not counted)" if wm else "")
                   + (f"; lost {', '.join(lost)}" if lost else ""))
    for g, why in st.get("skipped", []):
        out.append(f"  skipped {g[:13]}: {why}")
    held = [o["id"][:13] + f" ({o['owner']})" for _, x in res for o in x["games"] if o.get("owner") and o.get("lu") == "match"]
    mis = [o["id"][:13] for _, x in res for o in x["games"] if x.get("result") and o.get("lu") != "match"]
    if mis:
        out.append("  lineup mismatch, left open: " + ", ".join(mis))
    if held:
        out.append("  claimed, left open: " + ", ".join(held))
    txt = "\n".join(out) + "\n"
    open(DIR + "/report.txt", "w").write(txt)
    print(txt, flush=True)


def save(st):
    with open(STATE + ".new", "w") as f:
        json.dump(st, f)
    os.replace(STATE + ".new", STATE)


def run():
    lk = open(DIR + "/.lock", "w")
    fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if os.path.exists(STATE):
        st = json.load(open(STATE))
    else:
        groups, skipped, live = plan()
        st = dict(groups=groups, skipped=skipped, live=live, t0=time.time())
        save(st)
        log(f"planned {len(groups)} groups on {live}, {sum(len(g['games']) for g in groups)} cases, {len(skipped)} skipped")
    if not st.get("prechecked"):
        precheck(st)
    while time.time() - st["t0"] < WALL:
        todo = [g for g in st["groups"] if not g.get("gid")]
        if todo:
            room = ROOM - L.quota_used()
            for g in todo[:max(room, 0)]:
                pad = padded(g)
                games = [dict(map=x["map"], side=x["side"]) for x in g["games"]] + pad
                gid, out = L.create(g["team"], [x["map"] for x in games], [x["side"] for x in games])
                if not gid:
                    log(f"!! create failed v {g['team']['name']}: {out[:200]}")
                    break
                g["gid"] = gid
                save(st)
                log(f"group {gid[:13]} v {g['team']['name']}: {len(g['games'])} cases + {len(pad)} padding")
        for g in st["groups"]:
            if g.get("gid") and not g.get("done"):
                rows = L.group(g["gid"])
                if rows and len(rows) >= 5 and all(r[4] == "finished" for r in rows):
                    apply(st, g, rows)
                    g["done"] = True
                    save(st)
        if all(g.get("done") for g in st["groups"]):
            break
        time.sleep(60)
    report(st)
    open(DIR + "/done", "w").write(time.strftime("%H:%M:%SZ\n", time.gmtime()))


def main():
    os.makedirs(DIR, exist_ok=True)
    if sys.argv[1:] == ["plan"]:
        groups, skipped, live = plan()
        print(f"live {live}: {len(groups)} groups, {sum(len(g['games']) for g in groups)} cases covering {sum(len(x['games']) for g in groups for x in g['games'])} OPEN games; {len(skipped)} skipped")
        og = [(o["id"], x["side"]) for g in groups for x in g["games"] for o in x["games"]]
        k = sum(1 for i, sd in og if L.foe_lineup(i, sd, fetch=False))
        print(f"  foe lineup known for {k}/{len(og)} OPEN games (cache or replay on disk; the rest take one matches show when their re-play is applied); "
              "a win closes a game only under the same foe lineup")
        for name, n in collections.Counter(g["team"]["name"] for g in groups).most_common():
            print(f"  {name}: {n} groups")
        for g, why in skipped[:12]:
            print(f"  skipped {g[:13]}: {why}")
    elif sys.argv[1:] == ["run"]:
        run()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
