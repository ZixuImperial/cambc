#!/usr/bin/env python3
"""gplfeat.py (13 Nov, b2396; owner via Builder: "see on which maps each [plan] is good and their map features"): draft-time map
feature vector for the GPL plan chooser. Map data only, no map names; seat-A view (maps mirror, so seat B is the same vector).
Group/zone/rate definitions are gpl.py's (mapclass.d/gpl.py: 4-connected camp groups, rates per 100 rounds over respawn, rho = walk_A /
(walk_A + walk_B), OWN < .40 <= CENTRE <= .60 < THEIR, heavy = golem or monolith).

Features (ids are what the chooser data table uses; keep them stable):
  1 c         centre share of the map gem rate (gpl_c)
  2 h         heavy groups' share of the gem rate (gpl_h)
  3 con20     gem-rate share in groups whose two walks differ by <= 20 (gpl_con20)
  4 own_gem   own-zone gem rate     5 cen_gem  centre gem rate     6 thr_gem  their-zone gem rate
  7 own_gold  own-zone gold rate    8 cen_gold centre gold rate    9 thr_gold their-zone gold rate
 10 walk_c    gem-rate-weighted mean walk from our spawn to centre groups (0 if none)
 11 n_altar   altar count (4-connected altar tiles)
 12 d_altar   walk from our spawn to the nearest altar (tile next to it)
 13 compact   share of the centre+their gem rate within Chebyshev 6 of the richest such group
 14 n_group   group count
 15 own_ratio own-zone gem rate / (own gold rate / 10 + own gem rate): own side gem-led (1) v gold-led (0)
 16 walk_ab   walk between the spawns (map scale)
 17 cmarg     gem-rate-weighted mean |walk_us - walk_them| over CENTRE groups (Deep: centre gem race margin; small = tight race)
 18 team      champions per team (map header)
 -- 13 Nov (Planner, owner: symmetry, respawn timers, gold early when gems are contested). thr_gem / thr_gold (6, 9) equal own_* by
    symmetry: they keep their ids (gpt7 uses id 15) but are in EXCLUDE (never split on).
 19 resp_own  gem-rate-weighted mean respawn of OWN groups      20 resp_cen  same for CENTRE groups
 21 clear_cen gem-rate-weighted mean clear crew-rounds of CENTRE gem groups (sum over camps: wolf 22, elk 24, golem 41, cluster 10,
              monolith 62)
 22 gold_to_compete  rounds of own-zone gold income to buy two emblems (10 shards x 30 = 300 gold; GameRules 289) / walk_c
 23 altar_cen walk from the richest CENTRE gem group to its nearest altar / our spawn's walk to that altar
 -- owner 13 Nov ("Yes we should add all of these"):
 24 route_cover  share of bush tiles on a shortest walk from our spawn to the richest CENTRE gem group
 25 choke_cen    minimum corridor width on that walk (passable tiles across the step direction, both sides, cap 15; every 3rd tile)
 26 carry_region zone of the richest single gem source with rho <= .60 (heavy included): 0 OWN, 1 CENTRE
 27 carry_dom    its gem rate / the next best such group's
 -- owner 13 Nov ("think about hot spots ... area our carry may want to maintain"): HOT SPOT = Chebyshev-5 window (centred on a group
    centroid) whose summed rate (gem rate + gold rate / 10 over the groups whose centroid is inside) is a local maximum (greedy: by sum,
    no accepted window within 5); mirror ties go to the one nearer our spawn.
 28 hs_n      hot spots holding >= 15% of the map total     29 hs_share  the top one's share
 30 hs_zone   top one's zone by rho at its centre: 0 OWN, 1 CENTRE, 2 THEIR     31 hs_marg  walk_us - walk_them to its centre
 32 hs_altar  walk from its centre to the nearest altar     33 hs_resp  rate-weighted respawn of its groups
 34 hs_altar_contested  1 if that nearest altar is within walk 4 of the top hot spot AND our and their spawn walks to it differ
    by <= 4 (owner 13 Nov, incidental denial; gates b2392's hot-spot anchor knob)
 -- Builder 13 Nov (b2373's plan-7 loss replays: fewer bodies together where the foe arrives):
 35 own_to_contest  value-weighted (gem rate + gold rate/10) mean Chebyshev distance from our OWN groups to the richest CENTRE gem group
                    (99 if none): how far our farming spreads us from the first contest
 36 own_disp        value-weighted SD of our walk to the OWN groups (spread of our farm along the walk; 0 if < 2 groups)
Usage: python3 -I tools/lab/gplfeat.py MAP... (prints TSV); module: feats(path) -> dict or None.
"""
import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
RESP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
NAMES = ["c", "h", "con20", "own_gem", "cen_gem", "thr_gem", "own_gold", "cen_gold", "thr_gold", "walk_c", "n_altar", "d_altar",
         "compact", "n_group", "own_ratio", "walk_ab", "cmarg", "team", "resp_own", "resp_cen", "clear_cen", "gold_to_compete",
         "altar_cen", "route_cover", "choke_cen", "carry_region", "carry_dom",
         "hs_n", "hs_share", "hs_zone", "hs_marg", "hs_altar", "hs_resp",
         "hs_altar_contested", "own_to_contest", "own_disp"]
EXCLUDE = {"thr_gem", "thr_gold"}
CLEAR = {0: 22, 1: 24, 2: 10, 3: 10, 4: 62, 5: 41}
FID = {n: i + 1 for i, n in enumerate(NAMES)}


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


def _comps(tiles, conn):
    seen, out = set(), []
    for c in sorted(tiles):
        if c in seen:
            continue
        st, pts = [c], []
        seen.add(c)
        while st:
            x, y = st.pop()
            pts.append((x, y))
            for dx, dy in conn:
                q = (x + dx, y + dy)
                if q in tiles and q not in seen:
                    seen.add(q)
                    st.append(q)
        out.append(pts)
    return out


def feats(path):
    m = map26a.load(path)
    camps = m["camps"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = _bfs(m, list(m["spawnA"]), blocked), _bfs(m, list(m["spawnB"]), blocked)
    sa = [sum(p[i] for p in m["spawnA"]) / len(m["spawnA"]) for i in (0, 1)]
    sb = [sum(p[i] for p in m["spawnB"]) / len(m["spawnB"]) for i in (0, 1)]
    gs = []
    for pts in _comps(set(camps), ((1, 0), (-1, 0), (0, 1), (0, -1))):
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
        if w is None:
            w = (max(abs(cx - sa[0]), abs(cy - sa[1])), max(abs(cx - sb[0]), abs(cy - sb[1])))
        rho = w[0] / max(1e-9, w[0] + w[1])
        gs.append(dict(grate=gems * 100.0 / resp, orate=gold * 100.0 / resp, rho=rho, w=w, cx=cx, cy=cy,
                       heavy=any(t in (4, 5) for t in ty), resp=resp, clear=sum(CLEAR.get(t, 20) for t in ty), pts=pts))
    tot = sum(g["grate"] for g in gs)
    if tot <= 0:
        return None

    def zone(g):
        return 0 if g["rho"] < 0.40 else 1 if g["rho"] <= 0.60 else 2
    zg, zo = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    for g in gs:
        zg[zone(g)] += g["grate"]
        zo[zone(g)] += g["orate"]
    cen = [g for g in gs if zone(g) == 1]
    walk_c = sum(g["w"][0] * g["grate"] for g in cen) / zg[1] if zg[1] > 0 else 0.0
    alt = _comps(set(m["altar"]), DIRS8)
    da = [dA[(x + dx, y + dy)] for pts in alt for (x, y) in pts for dx, dy in DIRS8 if (x + dx, y + dy) in dA]
    fwd = [g for g in gs if zone(g) >= 1 and g["grate"] > 0]
    if fwd:
        top = max(fwd, key=lambda g: g["grate"])
        compact = sum(g["grate"] for g in fwd if max(abs(g["cx"] - top["cx"]), abs(g["cy"] - top["cy"])) <= 6) / sum(g["grate"] for g in fwd)
    else:
        compact = 0.0
    def wmean(gl, key):
        tw = sum(g["grate"] for g in gl)
        return sum(g[key] * g["grate"] for g in gl) / tw if tw > 0 else 0.0
    own = [g for g in gs if zone(g) == 0]
    cg = [g for g in cen if g["grate"] > 0]
    altar_cen = 0.0
    if cg and alt:
        rich = max(cg, key=lambda g: g["grate"])
        dg = _bfs(m, rich["pts"], blocked - set(rich["pts"]))
        best = None
        for pts in alt:
            nb = [(x + dx, y + dy) for (x, y) in pts for dx, dy in DIRS8]
            a_g = min((dg[q] for q in nb if q in dg), default=None)
            a_s = min((dA[q] for q in nb if q in dA), default=None)
            if a_g is not None and (best is None or a_g < best[0]):
                best = (a_g, a_s)
        if best and best[1]:
            altar_cen = best[0] / max(1, best[1])
    route_cover, choke = 0.0, 15.0
    if cg:
        rich = max(cg, key=lambda g: g["grate"])
        ends = [q for (x, y) in rich["pts"] for dx, dy in ((0, 0),) + DIRS8 for q in [(x + dx, y + dy)] if q in dA]
        if ends:
            cur = min(ends, key=lambda q: dA[q])
            path = [cur]
            while dA[cur] > 0:
                cur = min(((cur[0] + dx, cur[1] + dy) for dx, dy in DIRS8 if (cur[0] + dx, cur[1] + dy) in dA
                           and dA[(cur[0] + dx, cur[1] + dy)] == dA[cur] - 1), key=lambda q: q)
                path.append(cur)
            bush = m.get("bush", set())
            route_cover = sum(1 for q in path if q in bush) / len(path)
            W, H = m["W"], m["H"]
            for i in range(1, len(path) - 1, 3):
                dx, dy = path[i - 1][0] - path[i + 1][0], path[i - 1][1] - path[i + 1][1]
                px, py = (-dy, dx)
                px, py = (px > 0) - (px < 0), (py > 0) - (py < 0)
                if px == 0 and py == 0:
                    continue
                wdt = 1
                for sgn in (1, -1):
                    for k in range(1, 8):
                        q = (path[i][0] + sgn * k * px, path[i][1] + sgn * k * py)
                        if not (0 <= q[0] < W and 0 <= q[1] < H) or q in blocked:
                            break
                        wdt += 1
                choke = min(choke, float(wdt))
    near = sorted((g for g in gs if g["rho"] <= 0.60 and g["grate"] > 0), key=lambda g: -g["grate"])
    carry_region = float(zone(near[0])) if near else 0.0
    carry_dom = near[0]["grate"] / near[1]["grate"] if len(near) > 1 else 9.0
    ov = [(g, g["grate"] + g["orate"] / 10.0) for g in own]
    tv = sum(v for _, v in ov)
    if cg and tv > 0:
        rc = max(cg, key=lambda g: g["grate"])
        own_to_contest = sum(v * max(abs(g["cx"] - rc["cx"]), abs(g["cy"] - rc["cy"])) for g, v in ov) / tv
    else:
        own_to_contest = 99.0
    if len(ov) >= 2 and tv > 0:
        mw = sum(v * g["w"][0] for g, v in ov) / tv
        own_disp = math.sqrt(sum(v * (g["w"][0] - mw) ** 2 for g, v in ov) / tv)
    else:
        own_disp = 0.0
    # hot spots
    def near_walk(c):
        best = None
        for r_ in range(0, 4):
            for dx in range(-r_, r_ + 1):
                for dy in range(-r_, r_ + 1):
                    q = (c[0] + dx, c[1] + dy)
                    if q in dA and q in dB:
                        if best is None or dA[q] < best[1]:
                            best = (q, dA[q], dB[q])
            if best:
                return best
        return None
    vals = [g["grate"] + g["orate"] / 10.0 for g in gs]
    tot_v = sum(vals) or 1.0
    cands = []
    for g in gs:
        c = (int(round(g["cx"])), int(round(g["cy"])))
        inside = [i for i, h_ in enumerate(gs) if max(abs(h_["cx"] - c[0]), abs(h_["cy"] - c[1])) <= 5]
        sv = sum(vals[i] for i in inside)
        nw = near_walk(c)
        cands.append((sv, -(nw[1] if nw else 9999), c, inside, nw))
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    acc = []
    for cnd in cands:
        if all(max(abs(cnd[2][0] - a_[2][0]), abs(cnd[2][1] - a_[2][1])) > 5 for a_ in acc):
            acc.append(cnd)
    hs = dict(hs_n=0.0, hs_share=0.0, hs_zone=1.0, hs_marg=0.0, hs_altar=99.0, hs_resp=0.0, hs_altar_contested=0.0)
    if acc:
        top = acc[0]
        hs["hs_n"] = float(sum(1 for a_ in acc if a_[0] / tot_v >= 0.15))
        hs["hs_share"] = top[0] / tot_v
        if top[4]:
            q, wa, wb_ = top[4]
            rr = wa / max(1e-9, wa + wb_)
            hs["hs_zone"] = 0.0 if rr < 0.40 else 1.0 if rr <= 0.60 else 2.0
            hs["hs_marg"] = float(wa - wb_)
            dq = _bfs(m, [q], blocked)
            best_a = None
            for pts in alt:
                nb = [(x + dx, y + dy) for (x, y) in pts for dx, dy in DIRS8]
                dd = min((dq[z] for z in nb if z in dq), default=None)
                if dd is not None and (best_a is None or dd < best_a[0]):
                    best_a = (dd, min((dA[z] for z in nb if z in dA), default=None), min((dB[z] for z in nb if z in dB), default=None))
            if best_a:
                hs["hs_altar"] = float(best_a[0])
                if best_a[0] <= 4 and best_a[1] is not None and best_a[2] is not None and abs(best_a[1] - best_a[2]) <= 4:
                    hs["hs_altar_contested"] = 1.0
        ws_ = sum(vals[i] for i in top[3]) or 1.0
        hs["hs_resp"] = sum(gs[i]["resp"] * vals[i] for i in top[3]) / ws_
    wab = min((dA[p] for p in m["spawnB"] if p in dA), default=max(abs(sa[0] - sb[0]), abs(sa[1] - sb[1])))
    return dict(c=zg[1] / tot, h=sum(g["grate"] for g in gs if g["heavy"]) / tot,
                con20=sum(g["grate"] for g in gs if abs(g["w"][0] - g["w"][1]) <= 20) / tot,
                own_gem=zg[0], cen_gem=zg[1], thr_gem=zg[2], own_gold=zo[0], cen_gold=zo[1], thr_gold=zo[2], walk_c=walk_c,
                n_altar=len(alt), d_altar=min(da) if da else 999, compact=compact, n_group=len(gs),
                own_ratio=zg[0] / (zo[0] / 10.0 + zg[0]) if zg[0] + zo[0] > 0 else 0.5, walk_ab=wab,
                cmarg=sum(abs(g["w"][0] - g["w"][1]) * g["grate"] for g in cen) / zg[1] if zg[1] > 0 else 99.0,
                team=float(m.get("champs_per_team", 0)),
                resp_own=wmean(own, "resp"), resp_cen=wmean(cen, "resp"), clear_cen=wmean(cg, "clear"),
                gold_to_compete=(30000.0 / zo[0] if zo[0] > 0 else 999.0) / max(1.0, walk_c if walk_c > 0 else wab / 2.0),
                altar_cen=altar_cen, route_cover=route_cover, choke_cen=choke, carry_region=carry_region, carry_dom=carry_dom, own_to_contest=own_to_contest, own_disp=own_disp, **hs)


def _one(p):
    try:
        return os.path.basename(p)[:-7], feats(p)
    except Exception:  # noqa: BLE001
        return os.path.basename(p)[:-7], None


def build_cache(out, globs, procs=int(os.environ.get("GPLFEAT_PROCS", "8"))):
    """--cache OUT GLOB...: (re)build the shared feature cache in parallel; keeps rows already computed with the same NAMES."""
    import glob as _g
    import multiprocessing as mp
    have = {}
    if os.path.exists(out):
        with open(out) as fh:
            hdr = fh.readline().rstrip("\n").split("\t")
            if hdr[1:] == NAMES:
                for line in fh:
                    q = line.rstrip("\n").split("\t")
                    have[q[0]] = line
    todo = [p for g in globs for p in _g.glob(g) if p.endswith(".map26a") and os.path.basename(p)[:-7] not in have]
    with mp.Pool(procs) as pool:
        res = pool.map(_one, todo, chunksize=20)
    with open(out + ".new", "w") as fh:
        fh.write("map\t" + "\t".join(NAMES) + "\n")
        for line in have.values():
            fh.write(line)
        for m_, f in res:
            if f:
                fh.write(m_ + "\t" + "\t".join(repr(f[n]) for n in NAMES) + "\n")
    os.replace(out + ".new", out)
    print(f"gplfeat cache: {len(have)} kept, {len(todo)} computed -> {out}")


def slow_pace(f):
    """SLOW-PACE class (13 Nov, for VV's Vesper-on-slow-maps cut; thresholds = pool quantiles over 51,000 P3 maps): mean of resp_own and
    resp_cen >= 75 (pool p66) AND clear_cen >= 50 (pool median) AND NOT gem-starved (own_gem + cen_gem >= 400, pool p33) AND NOT
    heavy-dominant (h < .50, i.e. not gpl_type 1; h counts golems with monoliths). Pool share 7.3%."""
    return int(f is not None and (f["resp_own"] + f["resp_cen"]) / 2 >= 75 and f["clear_cen"] >= 50
               and f["own_gem"] + f["cen_gem"] >= 400 and f["h"] < 0.50)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--class":
    print("map\tslow_pace")
    for p in sys.argv[3:]:
        print(os.path.basename(p) + "\t" + str(slow_pace(_one(p)[1])))
    sys.exit(0)

if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--cache":
    build_cache(sys.argv[2], sys.argv[3:])
    sys.exit(0)

if __name__ == "__main__":
    print("map\t" + "\t".join(NAMES))
    for p in sys.argv[1:]:
        f = feats(p)
        if f:
            print(os.path.basename(p) + "\t" + "\t".join(f"{f[n]:.4g}" for n in NAMES))
