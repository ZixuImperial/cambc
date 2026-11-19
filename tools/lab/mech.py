#!/usr/bin/env python3
"""Mechanism metrics from replays: how a team spends its turns, travels, captures, banks and dies (map-agnostic).

Ported from cambc-b3's /data/USER/heavy_1025/heavy.py (corridors and heavy-loss studies, 25 Oct). Per team and game:
  time budget  shares of body-turns walking / farming / idle / recalling / fighting / dead (replay.classify_all)
  pacing       20-turn windows with no fight, farm, capture, tribute, recall or shop, 12+ moves, net displacement <= 3
               and a bounding box <= 7 (share of alive turns)
  opening      first camp hit per body (median body; 2000 = never), bodies whose first hit comes after r100, first capture
  captures     captures and gems, by group kind (elk / boss = monolith or golem / wolf / cluster) and zone (own / mid /
               enemy, by walk distance from the two spawns)
  sorties      stretches beyond 3 walk tiles from the own spawn; empty = no farm, capture, fight or tribute; deep = reached
               walk distance 10+; how they end (walk home, recall, death)
  banking      tributes, mean size, share under 25 gems, gems per bank trip-turn (turns from the last gem gain to the
               tribute), tributes whose trip used a recall
  deaths       count, by zone, to camps, while retreating (moved toward home on 2 of the last 3 turns)
  boss         maps with a monolith or golem group: its windows run from a hit by anyone to the next capture of it (or
               the game's end); in them, the share of living body-turns within 6 tiles of the group; damage to it,
               distinct hitters, the first hit, captures (cambc-b3's bossmono.py, generalised)

usage: python3 -I tools/lab/mech.py run RUN_DIR [--us BOT] [--jobs 6]
          a local A/B (tools/lab/abl.sh with KEEP=1): BOT (default: bot A) vs the other bot. Both sides of a map are one
          trial: means, the mean per-map difference and its 95% bootstrap CI over maps; * = the CI excludes 0.
          Per-game values are cached in RUN_DIR/mech.json.
       python3 -I tools/lab/mech.py live GAME... [--jobs 6]
          live games: us vs them in the same games, paired by game
GAME: a live match id, a live set dir (e.g. /data/USER/plat/m19eD), RUN:ID, a .repl26a, or an abl run dir with rep/.
abl.sh prints the run table at the end of every KEEP=1 A/B (MECH=0 turns it off).
"""
import collections
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as RP  # noqa: E402

ACTS = ("walk", "farm", "idle", "recall", "fight", "dead")
KINDS = ("elk", "boss", "wolf", "cluster")
ZONES = ("own", "mid", "enemy")
BUSY = ("fight", "farm", "capture", "hold", "tribute", "recall", "dead", "shop")  # activities that break a pacing window
PRODUCTIVE = ("farm", "capture", "hold", "fight", "tribute")  # hold: replay.hold_turns (12 Nov)
MECH_VER = 3  # bump when game_metrics changes (invalidates the RUN_DIR/mech.json caches)


def opt(argv, name, default, cast=str):
    """Pop `name VALUE` from argv."""
    if name in argv:
        i = argv.index(name)
        v = cast(argv[i + 1])
        del argv[i:i + 2]
        return v
    return default


def kind_of(gr):
    t = gr["types"]
    if t.get("monolith") or t.get("golem"):
        return "boss"
    if t.get("elk"):
        return "elk"
    if t.get("wolf"):
        return "wolf"
    return "cluster"


def game_metrics(args):
    """{"spec", "map", "us", "teams": [metrics of team 0, of team 1]}; a metric is None when it has no cases."""
    spec, us = args
    try:
        g = RP.load(spec, us)
    except (SystemExit, Exception) as e:
        return {"spec": spec, "error": str(e)}
    ci = g.ci
    acts = RP.classify_all(g)
    df = g.walk_fields()
    arrive = collections.defaultdict(list)
    for e in g.events:
        if e[1] == "recall_arrive":
            arrive[e[2]].append(e[0])
    kind = {gid: kind_of(gr) for gid, gr in g.groups.items()}
    zone = {gid: tuple(g.zone(int(gr["cx"]), int(gr["cy"]), tm) for tm in (0, 1)) for gid, gr in g.groups.items()}
    cnt = [collections.Counter(), collections.Counter()]
    first_hit = [[], []]
    sorties = [[], []]
    for c, ts in g.by_champ.items():
        tm = g.team_of[c]
        m = cnt[tm]
        n = len(ts)
        for t in ts:
            m["act_" + acts[(t[0], c)]] += 1
            m["alive"] += bool(t[ci["alive"]])
        first_hit[tm].append(next((t[0] for t in ts if RP.camp_hits(g, t)), None))  # a turn that also hit a champion counts
        cov = [False] * n
        for i in range(n - 19):
            w = ts[i:i + 20]
            if not all(t[ci["alive"]] and t[2] >= 0 for t in w) or any(acts[(t[0], c)] in BUSY for t in w):
                continue
            xs, ys = [t[2] for t in w], [t[3] for t in w]
            if (sum(1 for t in w if acts[(t[0], c)] == "walk") >= 12 and max(abs(xs[-1] - xs[0]), abs(ys[-1] - ys[0])) <= 3
                    and max(max(xs) - min(xs), max(ys) - min(ys)) <= 7):
                for j in range(i, i + 20):
                    cov[j] = True
        m["pace"] += sum(cov)
        home = df[tm]
        cur = None
        for t in ts:
            alive = t[ci["alive"]] and t[2] >= 0
            d = home.get((t[2], t[3]), 99) if alive else None
            away = alive and d > 3
            if cur is not None and not away:
                cur["end"] = "death" if not alive else ("recall" if any(cur["r0"] <= x <= t[0] for x in arrive[c]) else "walk")
                sorties[tm].append(cur)
                cur = None
            if cur is None and away:
                cur = {"r0": t[0], "turns": 0, "done": False, "maxd": 0}
            if cur is not None and away:
                cur["turns"] += 1
                cur["maxd"] = max(cur["maxd"], d)
                cur["done"] |= acts[(t[0], c)] in PRODUCTIVE
        if cur is not None:
            cur["end"] = "game_end"
            sorties[tm].append(cur)
    banks = [[], []]  # (gems, trip turns from the last gem gain, recall on the way)
    for e in g.events:
        if e[1] != "tribute":
            continue
        r, b, gems = e[0], e[2], e[4]
        ts = [t for t in g.by_champ[b] if t[0] <= r]
        last_gain = next((ts[i][0] for i in range(len(ts) - 1, 0, -1) if ts[i][ci["gems"]] > ts[i - 1][ci["gems"]]), None)
        if last_gain is not None:
            banks[g.team_of[b]].append((gems, r - last_gain, any(last_gain <= x <= r for x in arrive[b])))
    caps = [collections.Counter(), collections.Counter()]
    capg = [collections.Counter(), collections.Counter()]
    capfirst = [{}, {}]
    deaths = [[], []]  # (to a camp, zone, retreating)
    for e in g.events:
        if e[1] == "capture" and e[3] in (0, 1):
            caps[e[3]][e[2]] += 1
            capg[e[3]][e[2]] += sum(x[2] for x in e[4])
            capfirst[e[3]].setdefault(e[2], e[0])
        elif e[1] == "death" and g.team_of.get(e[2]) in (0, 1):
            b, tm, x, y = e[2], g.team_of[e[2]], e[6], e[7]
            # the last 3 turns before the death (its own turn in the death round included, when it came first): their
            # start tiles and the end tile of the last one, so each of the 3 moves is seen
            ts = [t for t in g.by_champ[b] if t[0] <= e[0] and t[ci["alive"]] and t[2] >= 0][-3:]
            ds = [df[tm].get(p, 99) for p in [(t[2], t[3]) for t in ts] + [RP.turn_end_pos(t) for t in ts[-1:]]]
            ret = len(ds) >= 3 and sum(1 for a, a2 in zip(ds, ds[1:]) if a2 < a) >= 2
            deaths[tm].append((e[3] == 2, g.zone(x, y, tm) if x is not None and x >= 0 else "?", ret))
    # boss windows (cambc-b3's bossmono.py, generalised): every monolith or golem group from a hit by anyone to the next
    # capture of it (or the game's end); in those rounds, where the living bodies stand, who hits it and how hard
    boss = {gid for gid, k in kind.items() if k == "boss"}
    camp_group = {cid: c["group"] for cid, c in g.camps.items()}
    bhits = collections.defaultdict(list)  # group -> [(round, team, body, damage)]
    for t in g.turns:
        for a in t[-1]:
            for k, i, d in (a[5] if a[0] == "a" else (a[7] if a[0] == "c" else ())):
                if k == 2 and d < 0 and camp_group.get(i) in boss:
                    bhits[camp_group[i]].append((t[0], g.team_of[t[1]], t[1], -d))
    bcaps = collections.defaultdict(list)
    for e in g.events:
        if e[1] == "capture" and e[2] in boss:
            bcaps[e[2]].append(e[0])
    windows = []
    for gid, hs in bhits.items():
        hs.sort()
        i = 0
        while i < len(hs):
            r0 = hs[i][0]
            r1 = min((c for c in bcaps[gid] if c >= r0), default=g.last_round)
            windows.append((gid, r0, r1))
            while i < len(hs) and hs[i][0] <= r1:
                i += 1
    bnear, balive = [0, 0], [0, 0]
    for t in g.turns:
        act = [gid for gid, r0, r1 in windows if r0 <= t[0] <= r1]
        if act and t[ci["alive"]] and t[2] >= 0:
            tm = g.team_of[t[1]]
            balive[tm] += 1
            bnear[tm] += any(RP.cheb(t[2], t[3], int(g.groups[gid]["cx"]), int(g.groups[gid]["cy"])) <= 6 for gid in act)
    teams = []
    for tm in (0, 1):
        m = cnt[tm]
        v = {}
        tot = sum(n for k, n in m.items() if k.startswith("act_")) or 1
        for a in ACTS:
            v[f"{a} % of body-turns"] = 100 * m["act_" + a] / tot
        v["pacing % of alive turns"] = 100 * m["pace"] / max(1, m["alive"])
        ff = first_hit[tm]
        v["first camp hit, median body"] = statistics.median([x or 2000 for x in ff]) if ff else None
        v["bodies whose first hit is after r100"] = sum(1 for x in ff if x is None or x > 100)
        v["first capture"] = min(capfirst[tm].values()) if capfirst[tm] else 2000
        v["captures"] = sum(caps[tm].values())
        v["gems captured"] = sum(capg[tm].values())
        for kd in KINDS:
            v[f"gems from {kd} groups"] = sum(n for gid, n in capg[tm].items() if kind.get(gid) == kd)
        for z in ZONES:
            v[f"gems from {z}-zone groups"] = sum(n for gid, n in capg[tm].items() if gid in zone and zone[gid][tm] == z)
        so = sorties[tm]
        empty = [s for s in so if not s["done"] and s["end"] != "game_end" and s["maxd"] >= 10]
        v["empty deep sorties"] = len(empty)
        v["empty deep sortie turns, % of alive"] = 100 * sum(s["turns"] for s in empty) / max(1, m["alive"])
        ended = [s for s in so if s["end"] != "game_end"]
        v["sorties ending in a recall %"] = 100 * sum(s["end"] == "recall" for s in ended) / len(ended) if ended else None
        prod = [s for s in so if s["done"]]
        v["productive sorties ending in a recall %"] = 100 * sum(s["end"] == "recall" for s in prod) / len(prod) if prod else None
        bk = banks[tm]
        v["tributes"] = len(bk)
        v["tribute size"] = sum(b[0] for b in bk) / len(bk) if bk else None
        v["tributes under 25 gems %"] = 100 * sum(b[0] < 25 for b in bk) / len(bk) if bk else None
        v["gems per bank trip-turn"] = sum(b[0] for b in bk) / max(1, sum(b[1] for b in bk)) if bk else None
        v["bank trips with a recall %"] = 100 * sum(b[2] for b in bk) / len(bk) if bk else None
        dd = deaths[tm]
        v["deaths"] = len(dd)
        for z in ZONES:
            v[f"deaths in the {z} zone"] = sum(d[1] == z for d in dd)
        v["deaths to camps"] = sum(d[0] for d in dd)
        v["deaths while retreating %"] = 100 * sum(d[2] for d in dd) / len(dd) if dd else None
        mine = [h for hs in bhits.values() for h in hs if h[1] == tm]
        v["boss windows: bodies within 6 %"] = 100 * bnear[tm] / balive[tm] if balive[tm] else None
        v["boss damage"] = sum(h[3] for h in mine) if boss else None
        v["boss hitters"] = len({h[2] for h in mine}) if boss else None
        v["boss first hit"] = min((h[0] for h in mine), default=2000) if boss else None
        v["boss captures"] = sum(1 for e in g.events if e[1] == "capture" and e[2] in boss and e[3] == tm) if boss else None
        teams.append(v)
    return {"spec": spec, "map": g.meta.get("map") or os.path.basename(str(spec)), "us": g.us, "teams": teams}


def collect(jobs_list, jobs):
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(max(1, min(jobs, len(jobs_list)))) as pool:
        return pool.map(game_metrics, jobs_list, chunksize=1)


def boot_ci(vals, n=2000, seed=7):
    k = len(vals)
    if k < 2:
        return float("nan"), float("nan")
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(vals) for _ in range(k)) / k for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def table(rows, key_of, label_x, label_y, unit):
    """rows: per-game results; key_of(row) = the pairing unit (a map, or a game). X = row["us"]'s team."""
    rows = [r for r in rows if "error" not in r]
    if not rows:
        print("mechanism metrics: no readable games")
        return
    names = list(rows[0]["teams"][0])
    units = sorted({key_of(r) for r in rows})
    print(f"  {'metric':40s} {label_x[:12]:>12s} {label_y[:12]:>12s} {'diff':>9s}  95% CI over {len(units)} {unit}s")
    shown = 0
    for k in names:
        xs = [r["teams"][r["us"]][k] for r in rows if r["teams"][r["us"]][k] is not None]
        ys = [r["teams"][1 - r["us"]][k] for r in rows if r["teams"][1 - r["us"]][k] is not None]
        per = collections.defaultdict(list)
        for r in rows:
            a, b = r["teams"][r["us"]][k], r["teams"][1 - r["us"]][k]
            if a is not None and b is not None:
                per[key_of(r)].append(a - b)
        diffs = [sum(v) / len(v) for v in per.values()]
        if not diffs:
            continue
        lo, hi = boot_ci(diffs)
        star = "*" if lo > 0 or hi < 0 else " "
        mx = sum(xs) / len(xs) if xs else float("nan")
        my = sum(ys) / len(ys) if ys else float("nan")
        print(f"  {k:40s} {mx:12.1f} {my:12.1f} {sum(diffs) / len(diffs):+9.1f}{star} [{lo:+.1f}, {hi:+.1f}]")
        shown += 1
    # 95% intervals on many metrics: about 1 in 20 excludes 0 by chance (a mirror run, mirror_m18k, shows 2 of 39)
    print(f"  {shown} metrics: about {0.05 * shown:.0f} stars are expected by chance alone")


def run_rows(d, bot=None, jobs=6):
    """Per-game metrics of an abl run dir (cached in mech.json), with "us" = bot's team in each game."""
    games = [ln.split() for ln in open(os.path.join(d, "games.list")) if ln.strip()]
    bot = bot or games[0][1]
    if not any(bot in g[1:3] for g in games):  # else every game would read seat B as "us", mixing both bots
        sys.exit(f"mech.py: {bot} plays no game in {d}/games.list (bots: {', '.join(sorted({x for g in games for x in g[1:3]}))})")
    cache = os.path.join(d, "mech.json")
    try:
        c = json.load(open(cache))
        rows = c["rows"] if c.get("v") == MECH_VER else None
    except (OSError, ValueError, AttributeError):
        rows = None
    if rows is None:
        todo = [(os.path.join(d, "rep", f"{gid}.repl26a"), "A") for gid, a, b, m in games
                if os.path.exists(os.path.join(d, "rep", f"{gid}.repl26a"))]
        rows = collect(todo, jobs)
        for r, (gid, a, b, m) in zip(rows, [x for x in games if os.path.exists(os.path.join(d, "rep", f"{x[0]}.repl26a"))]):
            r["map"], r["a"], r["b"] = m, a, b
        try:
            json.dump({"v": MECH_VER, "rows": rows}, open(cache, "w"))
        except OSError:
            pass
    for r in rows:
        if "error" not in r:
            r["us"] = 0 if r["a"] == bot else 1
    other = next((x for g in games for x in g[1:3] if x != bot), "?")
    return rows, bot, other


def print_run(d, bot=None, jobs=6):
    rows, bot, other = run_rows(d, bot, jobs)
    ok = [r for r in rows if "error" not in r]
    n = sum(1 for ln in open(os.path.join(d, "games.list")) if ln.strip())
    miss = f" ({n - len(ok)} of {n} without a readable replay)" if len(ok) < n else ""
    print(f"mechanism metrics (tools/lab/mech.py): {bot} vs {other}, {len(ok)} games{miss}; both sides of a map are one trial; "
          f"* = the 95% CI of the per-map difference excludes 0")
    table(ok, lambda r: r["map"], bot, other, "map")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a.pop(0)
    jobs = opt(a, "--jobs", 6, int)
    if cmd == "run":
        bot = opt(a, "--us", None)
        if not a:
            sys.exit(__doc__)
        print_run(a[0], bot, jobs)
    elif cmd == "live":
        specs = RP.expand_specs(a)
        if not specs:
            sys.exit(__doc__)
        rows = [r for r in collect([(s, None) for s in specs], jobs) if "error" not in r]
        print(f"mechanism metrics (tools/lab/mech.py): us vs them, {len(rows)} live games, paired by game; "
              f"* = the 95% CI of the per-game difference excludes 0")
        table(rows, lambda r: r["spec"], "us", "them", "game")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
