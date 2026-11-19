"""gpl (13 Nov, Deep; GPL stage A map types from a MAP FILE, for fresh maps; definitions: /data/USER/st/deepan/gpl/prereg.md
stage a + the stamped amendment in stageA.md; ladder-map agreement is printed by `python3 -I tools/lab/mapclass.d/gpl.py --check`).
Group = 4-connected camp tiles (as kgs.py). Per camp (GameRules camp table): gems wolf 4, elk 15, gem cluster 7, gold cluster 0,
monolith 200, golem 36; gold wolf 40, elk 90, gem cluster 0, gold cluster 20, monolith 300, golem 160; respawn = the group's largest
(wolf 40, elk 60, clusters 50, monolith 150, golem 80). Rates are per 100 rounds over the respawn (as stage A: x 100 / respawn).
Walk = 8-direction BFS from each spawn rectangle over tiles that are not wall, hole or altar (replay.walk_fields); a group's walk is
read at its first tile (or a neighbour) reachable from both spawns; rho = walk_A / (walk_A + walk_B) (seat A view; maps mirror).
Zones: OWN rho < .40, CENTRE .40-.60, THEIR > .60. HEAVY group = has a golem or monolith; else GOLD-LED if 10 x gems <= gold.
gpl_c = centre share of the map gem rate; gpl_h = heavy groups' share of it; gpl_sides = 1 when, among groups with rho <= .60, one
half (left/right of the spawn axis is not available from features, so stage A's rule is used: by sign of the group's offset from
the line joining the spawns) holds >= .60 of the gem rate and the other >= .60 of the gold rate.
gpl_type: 1 HEAVY-DOM (h >= .50), 2 SPLIT-SIDES, 3 CENTRE-DOM (c >= .70), 4 CENTRE-GEM (c >= .40), 5 OWN-SUFF (c < .20), 6 UNIFORM,
7 TWO-HALVES / BORDER (13 Nov: a 3 or 4 with gpl_compact < .40; 3/4 are concentrated centres only); then a single CENTRAL altar
(gpl_alt1c) -> 3 whatever the gem type (13 Nov, owner on 00anvil). Second axis gpl_mon (strong monster group: h >= .50 or the centre
gem rate's heavy share >= .50); gpl_code = type + 7 x mon + 1 (2..15) for map_type.h / draft memory id 9.
gpl_con20 = share of the gem rate in groups whose two walks differ by <= 20 (contention class; tercile cuts .606 / .936).
Draft-time, map data only."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
RESP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
_c = {}


def _bfs(m, src, blocked):
    d = {p: 0 for p in src}
    q = collections.deque(src)
    W, H = m["W"], m["H"]
    while q:
        x, y = q.popleft()
        for dx, dy in DIRS8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in blocked and p not in d:
                d[p] = d[(x, y)] + 1
                q.append(p)
    return d


def feats(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    camps = m["camps"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = _bfs(m, list(m["spawnA"]), blocked), _bfs(m, list(m["spawnB"]), blocked)
    sa = [sum(p[i] for p in m["spawnA"]) / len(m["spawnA"]) for i in (0, 1)]
    sb = [sum(p[i] for p in m["spawnB"]) / len(m["spawnB"]) for i in (0, 1)]
    seen, gs = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        st, pts = [c], []
        seen.add(c)
        while st:
            x, y = st.pop()
            pts.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        ty = [camps[p] for p in pts]
        gems, gold, resp = sum(GEMS.get(t, 0) for t in ty), sum(GOLD.get(t, 0) for t in ty), max(RESP.get(t, 50) for t in ty)
        w = None
        for (x, y) in pts:
            for dx, dy in ((0, 0),) + DIRS8:
                q = (x + dx, y + dy)
                if q in dA and q in dB:
                    w = (dA[q], dB[q])
                    break
            if w:
                break
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if w is None:  # off both walk fields: Chebyshev fallback, as stage A
            w = (max(abs(cx - sa[0]), abs(cy - sa[1])), max(abs(cx - sb[0]), abs(cy - sb[1])))
        rho = w[0] / max(1e-9, w[0] + w[1])
        side = (cx - sa[0]) * (sb[1] - sa[1]) - (cy - sa[1]) * (sb[0] - sa[0])
        gs.append(dict(gems=gems, gold=gold, grate=gems * 100.0 / resp, orate=gold * 100.0 / resp, rho=rho, w=w,
                       heavy=any(t in (4, 5) for t in ty), side=side, cx=cx, cy=cy))
    tot = sum(g["grate"] for g in gs)
    if tot <= 0:
        _c[path] = None
        return None
    c = sum(g["grate"] for g in gs if 0.40 <= g["rho"] <= 0.60) / tot
    h = sum(g["grate"] for g in gs if g["heavy"]) / tot
    near = [g for g in gs if g["rho"] <= 0.60]
    tg, to = sum(g["grate"] for g in near), sum(g["orate"] for g in near)
    sg = sum(g["grate"] for g in near if g["side"] > 0) / tg if tg > 0 else 0.5
    so = sum(g["orate"] for g in near if g["side"] > 0) / to if to > 0 else 0.5
    side_gem, side_goldopp = max(sg, 1 - sg), ((1 - so) if sg >= 0.5 else so)
    sides = int(side_gem >= 0.60 and side_goldopp >= 0.60)
    typ = 1 if h >= 0.5 else 2 if sides else 3 if c >= 0.70 else 4 if c >= 0.40 else 5 if c < 0.20 else 6
    # 13 Nov (owner via Planner, 00ambush: "not truly a centre map, there are two halves but they have same resources"): type 7 TWO HALVES /
    # BORDER = a centre type (3 or 4) whose forward gem rate is NOT compact: compact = share of the centre+their gem rate (rho >= .40) within
    # Chebyshev 6 of the richest such group (gplfeat.py 'compact'); compact < .40 -> 7. Types 3/4 keep only concentrated centres.
    fwd = [g for g in gs if g["rho"] >= 0.40 and g["grate"] > 0]
    if fwd:
        top = max(fwd, key=lambda g: g["grate"])
        compact = sum(g["grate"] for g in fwd if max(abs(g["cx"] - top["cx"]), abs(g["cy"] - top["cy"])) <= 6) / sum(g["grate"] for g in fwd)
    else:
        compact = 0.0
    if typ in (3, 4) and compact < 0.40:
        typ = 7
    # 13 Nov (owner via Planner, 00anvil: "centre dominated cause altar but also weird"): ALTAR CENTRALITY. altar_c = share of altars in the
    # CENTRE zone (rho .40-.60 at the altar's nearest walkable neighbour); alt1c = exactly one altar and it is central (rho .40-.60) or within
    # walk 3 of the top hot spot (gplfeat hs_altar). alt1c makes the map centre-dominated whatever the gem type -> 3.
    # Second axis (owner, 00anvil "cause strong monster group"): mon = 1 when the contested resource sits behind a strong monster group:
    # heavy share h >= .50 OR the CENTRE gem rate's heavy share (golem / monolith groups, rho .40-.60) >= .50.
    # Combined code for map_type.h / draft memory id 9 (4 bits): gpl_code = type + 7 x mon + 1 (2..15; 0 = absent).
    alts = []
    seen_a = set()
    for a0 in sorted(m["altar"]):
        if a0 in seen_a:
            continue
        stk, comp = [a0], []
        seen_a.add(a0)
        while stk:
            x, y = stk.pop()
            comp.append((x, y))
            for dx, dy in DIRS8:
                q = (x + dx, y + dy)
                if q in m["altar"] and q not in seen_a:
                    seen_a.add(q)
                    stk.append(q)
        nb = [(x + dx, y + dy) for (x, y) in comp for dx, dy in DIRS8]
        wa = min((dA[q] for q in nb if q in dA), default=None)
        wb = min((dB[q] for q in nb if q in dB), default=None)
        alts.append(wa / (wa + wb) if wa is not None and wb is not None and wa + wb > 0 else None)
    altar_c = sum(1 for r in alts if r is not None and 0.40 <= r <= 0.60) / len(alts) if alts else 0.0
    alt1c = 0
    gf = None
    if len(alts) == 1:
        central = alts[0] is not None and 0.40 <= alts[0] <= 0.60
        try:
            import gplfeat
            gf = gplfeat.feats(path)
        except Exception:  # noqa: BLE001
            gf = None
        if gf:
            central = central or gf["hs_altar"] <= 3
        alt1c = int(central)
    if alt1c:
        typ = 3
    if gf is None:
        try:
            import gplfeat
            gf = gplfeat.feats(path)
        except Exception:  # noqa: BLE001
            gf = None
    cg_ = sum(g["grate"] for g in gs if 0.40 <= g["rho"] <= 0.60)
    hc = sum(g["grate"] for g in gs if g["heavy"] and 0.40 <= g["rho"] <= 0.60) / cg_ if cg_ > 0 else 0.0
    mon = int(h >= 0.5 or hc >= 0.5)
    code = typ + 7 * mon + 1
    con20 = sum(g["grate"] for g in gs if abs(g["w"][0] - g["w"][1]) <= 20) / tot
    _c[path] = dict(c=c, h=h, sides=sides, type=typ, con20=con20, compact=compact, altar_c=altar_c, alt1c=alt1c, mon=mon, code=code)
    return _c[path]


def _f(k):
    def fn(path, _g=None):
        v = feats(path)
        return None if v is None else v[k]
    return fn


TYPES = {1: "HEAVY-DOM", 2: "SPLIT-SIDES", 3: "CENTRE-DOM", 4: "CENTRE-GEM", 5: "OWN-SUFF", 6: "UNIFORM", 7: "TWO-HALVES"}
CLASSES = {"gpl_type": _f("type"), "gpl_c": _f("c"), "gpl_h": _f("h"), "gpl_sides": _f("sides"), "gpl_con20": _f("con20"), "gpl_compact": _f("compact"), "gpl_altar_c": _f("altar_c"),
           "gpl_alt1c": _f("alt1c"), "gpl_mon": _f("mon"), "gpl_code": _f("code")}

if __name__ == "__main__" and "--check" in sys.argv:
    import csv
    ref = {r["map"]: r for r in csv.DictReader(open("/data/USER/st/deepan/gpl/stageA_maps.tsv"), delimiter="\t")}
    n = same = miss = 0
    dc, dh, bad = [], [], collections.Counter()
    for mp, r in sorted(ref.items()):
        p = "/data/USER/ablproj_4.0.0/maps/%s.map26a" % mp
        if not os.path.exists(p):
            miss += 1
            continue
        v = feats(p)
        if v is None:
            continue
        n += 1
        t = TYPES[v["type"]]
        same += t == r["type"]
        if t != r["type"]:
            bad[(r["type"], t)] += 1
        dc.append(abs(v["c"] - float(r["c"])))
        dh.append(abs(v["h"] - float(r["h"])))
    print("maps checked", n, "missing file", miss, "| type agrees", same, "| mean |dc| %.3f max %.3f | mean |dh| %.3f max %.3f" % (
        sum(dc) / max(1, n), max(dc or [0]), sum(dh) / max(1, n), max(dh or [0])))
    print("disagreements (stageA -> map file):", dict(bad))
