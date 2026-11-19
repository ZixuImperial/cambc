#!/usr/bin/env python3
"""heavyfuel: the heavy-turn fuel figure for the change v fuel ratio row (Tool builder, 7 Nov; owner: "fuel on calm turns doesn't matter", so judge turns near the budget, never mean fuel).
cap5 counts turns that RAN OUT; it cannot see a turn that used 95% of its budget and stopped. This plays CAND v BASE, both seats, on one new unsaved fresh set with cxe --fuel-log, and counts
each side's play turns at >= NEAR% of that turn's budget, capped at HEAVY_CAP per side per game (a chain on one spike map must not decide the read, as with cap5), paired by map. The log is
reduced to a 100-bin histogram on the node, so a game returns ~1 KB, not ~1 MB.

usage: python3 -I tools/lab/heavyfuel.py CAND BASE [--n 300] [--out DIR]
Python: heavyfuel.read(cand, base, out, n=300, say=print) -> dict(c, b, se, maps, games, p99c, p99b), or None when under 90% of the games came back.
  c, b: capped heavy turns; se: paired SE over maps; p99c, p99b: each side's 99th-percentile turn as % of budget. Env: HEAVY_NEAR (90), HEAVY_CAP (50)."""
import collections
import math
import os
import shutil
import sys
import time

REPO = "/homes/USER/cambc"
sys.path[:0] = [f"{REPO}/tools/lab", f"{REPO}/tools/cxe"]
NEAR = int(os.environ.get("HEAVY_NEAR", 90))
CAP = int(os.environ.get("HEAVY_CAP", 50))


def hist(path):
    """g.fsum -> {team: Counter(bin -> turns)}; bin = % of the turn's budget used"""
    h = collections.defaultdict(collections.Counter)
    for ln in open(path):
        t, b, c = ln.split()
        h[int(t)][int(b)] += int(c)
    return h


def pct(c, q):
    tot, run = sum(c.values()), 0
    for b in sorted(c):
        run += c[b]
        if run >= q * tot:
            return b
    return 0


def read(cand, base, out, n=300, say=print):
    import changedprobe as CP
    import cxebuild
    import cxefarm
    import smokefarm as SF

    def lib(bot):
        return (SF.patch_so(bot) if SF.flipinfo(bot) else None) or cxebuild.build_bot(bot)
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    bm, err = CP.draw(f"{out}/maps", n, f"heavy{os.getpid()}", None, cls="")  # a pool draw by design (shipcheck scales a rare gain by its changed share)
    if bm is None:
        say(f"heavyfuel: no maps: {err}")
        return None
    cso, bso = lib(cand), lib(base)
    games, plan = [], []
    for m in bm["maps"]:
        mp = f"{out}/maps/{m['name']}.map26a"
        if not os.path.exists(mp):
            continue
        for a, b, team_c in ((cso, bso, 0), (bso, cso, 1)):
            k = len(games)
            games.append(dict(id=k, a=a, b=b, map=mp, args=["--fuel-log"], fuelsum=True, files={"g.fsum": f"{out}/{k}.fsum", "g.fsumw": f"{out}/{k}.fsumw"}))
            plan.append((m["name"], team_c))
    cxefarm.run(games, say=lambda m: None, per=20, cpus=8, prio=int(os.environ.get("PILOTCXE_PRIO", 12)))  # >= CXEFARM_MIN games: the pilots
    per, side, got = collections.defaultdict(lambda: [0, 0]), [collections.Counter(), collections.Counter()], 0
    whole = [0, 0]  # 13 Nov (owner via Shared Mem: intentional v unintentional fuel): whole-turn heavy turns, information when 'pre' differs
    for k, (name, tc) in enumerate(plan):
        try:
            h = hist(f"{out}/{k}.fsum")
        except (OSError, ValueError):
            continue
        got += 1
        for who, t in ((0, tc), (1, 1 - tc)):
            per[name][who] += min(CAP, sum(c for b, c in h[t].items() if b >= NEAR))
            side[who].update(h[t])
        try:  # g.fsumw: the whole turn, post-action spending included (a v2 marker bot's g.fsum counts only the fuel before that phase)
            hw = hist(f"{out}/{k}.fsumw")
            for who, t in ((0, tc), (1, 1 - tc)):
                whole[who] += min(CAP, sum(c for b, c in hw[t].items() if b >= NEAR))
        except (OSError, ValueError):
            pass
    shutil.rmtree(f"{out}/maps", ignore_errors=True)
    if got < 0.9 * len(games) or len(per) < 2:
        say(f"heavyfuel: {got} of {len(games)} games back")
        return None
    d = [p[0] - p[1] for p in per.values()]
    mu = sum(d) / len(d)
    se = math.sqrt(len(d) * sum((x - mu) ** 2 for x in d) / (len(d) - 1))
    r = dict(c=sum(p[0] for p in per.values()), b=sum(p[1] for p in per.values()), se=se, maps=len(d), games=got, p99c=pct(side[0], .99), p99b=pct(side[1], .99), wc=whole[0], wb=whole[1])
    say(f"heavyfuel: {cand} v {base}: heavy turns (>= {NEAR}% of budget, cap {CAP}) {r['c']} v {r['b']}, se {se:.1f}, p99 {r['p99c']}% v {r['p99b']}%, {r['maps']} maps, {time.time() - t0:.0f} s")
    return r


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith("-"):
        sys.exit(__doc__)
    out = a[a.index("--out") + 1] if "--out" in a else f"/data/USER/st/heavy/{a[0]}_{int(time.time())}"
    r = read(a[0], a[1], out, int(a[a.index("--n") + 1]) if "--n" in a else 300)
    if r is None:
        return 1
    for f in os.listdir(out):
        if f.endswith((".fsum", ".fsumw")):
            os.unlink(f"{out}/{f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
