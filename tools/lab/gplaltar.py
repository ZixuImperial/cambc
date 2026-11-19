#!/usr/bin/env python3
"""gplaltar.py (13 Nov, b2396; owner: "account for position and shape routes to the altars etc"): per-altar geometry features, draft-time
map data only, once per map, seat-A view (maps mirror). Altars: O1 = our nearest altar (walk from our spawn), F1 / F2 = the foe's nearest two
(walk from their spawn). Per altar X in (O1, F1, F2), columns X_<name>:
 POSITION  along (0 our spawn .. 1 theirs, projection on the spawn axis), across (|perpendicular| / axis length), zone (0 own / 1 centre /
           2 theirs by rho = walk_us / (walk_us + walk_them) at .40/.60), edge (Chebyshev distance to the nearest map border)
 SHAPE     open3 (passable share of the 7x7 box), block2 (wall/hole tiles within Chebyshev 2), exits (contiguous passable arcs on the
           radius-3 ring), shape (0 dead end: exits <= 1; 1 corridor: open3 < .55; 2 open field)
 ROUTES    from S in (fs = foe spawn, rg = richest gem group, hs = top hot spot): near-shortest tile set = tiles t with d_S(t) + d_X(t) <=
           1.1 x d_S(X) + 1; S_routes = contiguous arcs of that set on the radius-3 ring of X; S_width = min over walk levels (in the
           last 80% of the walk) of the set's tiles per level; S_bush = bush share of the set; S_choke = 1 if some level's set has
           Chebyshev diameter <= 8 (all routes pass within 4 of one tile)
 HOLD      hold_maxw = min over tiles h within 6 of X of max walk from h to the foe-spawn route entries (ring arcs' tiles); hold_cost = walk
           from our farm (nearest own-zone group tile) to that h
Usage: python3 -I tools/lab/gplaltar.py OUT.tsv GLOB... [--procs N]
"""
import collections
import glob
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import map26a  # noqa: E402
from gplfeat import _bfs, _comps, GEMS, GOLD, RESP, DIRS8  # noqa: E402

ALT = ("O1", "F1", "F2")
SRC = ("fs", "rg", "hs")
COLS = []
for X in ALT:
    COLS += [f"{X}_{c}" for c in ("along", "across", "zone", "edge", "open3", "block2", "exits", "shape")]
    for S in SRC:
        COLS += [f"{X}_{S}_{c}" for c in ("routes", "width", "bush", "choke")]
    COLS += [f"{X}_hold_maxw", f"{X}_hold_cost"]


def ring(c, r, W, H):
    x0, y0 = c
    out = []
    for x in range(x0 - r, x0 + r + 1):
        out.append((x, y0 - r))
    for y in range(y0 - r + 1, y0 + r + 1):
        out.append((x0 + r, y))
    for x in range(x0 + r - 1, x0 - r - 1, -1):
        out.append((x, y0 + r))
    for y in range(y0 + r - 1, y0 - r, -1):
        out.append((x0 - r, y))
    return out


def arcs(flags):
    """number of contiguous True runs on a cyclic list"""
    n = len(flags)
    if not any(flags):
        return 0
    if all(flags):
        return 1
    return sum(1 for i in range(n) if flags[i] and not flags[i - 1])


def feats(path):
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    bush = m.get("bush", set())
    camps = m["camps"]
    dA, dB = _bfs(m, list(m["spawnA"]), blocked), _bfs(m, list(m["spawnB"]), blocked)
    sa = [sum(p[i] for p in m["spawnA"]) / len(m["spawnA"]) for i in (0, 1)]
    sb = [sum(p[i] for p in m["spawnB"]) / len(m["spawnB"]) for i in (0, 1)]
    ax = (sb[0] - sa[0], sb[1] - sa[1])
    al2 = ax[0] ** 2 + ax[1] ** 2 or 1.0
    alt = _comps(set(m["altar"]), DIRS8)
    if not alt:
        return None

    def walk_to(d, pts):
        return min((d[(x + dx, y + dy)] for (x, y) in pts for dx, dy in DIRS8 if (x + dx, y + dy) in d), default=None)
    # groups (gplfeat's definitions)
    gs = []
    for pts in _comps(set(camps), ((1, 0), (-1, 0), (0, 1), (0, -1))):
        ty = [camps[p] for p in pts]
        resp = max(RESP.get(t, 50) for t in ty)
        g = sum(GEMS.get(t, 0) for t in ty) * 100.0 / resp
        o = sum(GOLD.get(t, 0) for t in ty) * 100.0 / resp
        wa = min((dA[q] for p in pts for dx, dy in ((0, 0),) + DIRS8 for q in [(p[0] + dx, p[1] + dy)] if q in dA), default=None)
        wb = min((dB[q] for p in pts for dx, dy in ((0, 0),) + DIRS8 for q in [(p[0] + dx, p[1] + dy)] if q in dB), default=None)
        rho = wa / (wa + wb) if wa is not None and wb is not None and wa + wb > 0 else 0.5
        gs.append(dict(pts=pts, g=g, o=o, rho=rho, cx=sum(p[0] for p in pts) / len(pts), cy=sum(p[1] for p in pts) / len(pts)))
    # sources
    srcs = {"fs": list(m["spawnB"])}
    if gs and max(g["g"] for g in gs) > 0:
        srcs["rg"] = max(gs, key=lambda g: g["g"])["pts"]
    vals = [g["g"] + g["o"] / 10.0 for g in gs]
    best = None
    for g in gs:
        c = (int(round(g["cx"])), int(round(g["cy"])))
        sv = sum(v for h, v in zip(gs, vals) if max(abs(h["cx"] - c[0]), abs(h["cy"] - c[1])) <= 5)
        key = (sv, -(dA.get(c, 9999)))
        if best is None or key > best[0]:
            best = (key, c)
    if best:
        c = best[1]
        near = [q for q in ((c[0] + dx, c[1] + dy) for dx in range(-3, 4) for dy in range(-3, 4)) if q in dA]
        if near:
            srcs["hs"] = [min(near, key=lambda q: max(abs(q[0] - c[0]), abs(q[1] - c[1])))]
    sdist = {k: _bfs(m, v, blocked - set(v)) for k, v in srcs.items()}
    own_tiles = [q for g in gs if g["rho"] < 0.40 for p in g["pts"] for dx, dy in ((0, 0),) + DIRS8 for q in [(p[0] + dx, p[1] + dy)] if q in dA]
    dfarm = _bfs(m, own_tiles, blocked) if own_tiles else dA
    # pick altars
    wA = [(walk_to(dA, pts), i) for i, pts in enumerate(alt)]
    wB = [(walk_to(dB, pts), i) for i, pts in enumerate(alt)]
    wA = sorted((w, i) for w, i in wA if w is not None)
    wB = sorted((w, i) for w, i in wB if w is not None)
    pick = {"O1": wA[0][1] if wA else None, "F1": wB[0][1] if wB else None, "F2": wB[1][1] if len(wB) > 1 else None}
    out = {}
    for X, ai in pick.items():
        if ai is None:
            for c in COLS:
                if c.startswith(X + "_"):
                    out[c] = -1.0
            continue
        pts = alt[ai]
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        c = (int(round(cx)), int(round(cy)))
        along = ((cx - sa[0]) * ax[0] + (cy - sa[1]) * ax[1]) / al2
        across = abs((cx - sa[0]) * ax[1] - (cy - sa[1]) * ax[0]) / al2
        wa_, wb_ = walk_to(dA, pts), walk_to(dB, pts)
        rho = wa_ / (wa_ + wb_) if wa_ is not None and wb_ is not None and wa_ + wb_ > 0 else 0.5
        box = [(c[0] + dx, c[1] + dy) for dx in range(-3, 4) for dy in range(-3, 4)]
        passable = lambda q: 0 <= q[0] < W and 0 <= q[1] < H and q not in blocked
        open3 = sum(passable(q) for q in box) / 49.0
        block2 = sum(1 for dx in range(-2, 3) for dy in range(-2, 3) if (c[0] + dx, c[1] + dy) in (set(m["wall"]) | set(m["hole"])))
        rg = ring(c, 3, W, H)
        exits = arcs([passable(q) for q in rg])
        out.update({f"{X}_along": along, f"{X}_across": across, f"{X}_zone": 0.0 if rho < 0.4 else 1.0 if rho <= 0.6 else 2.0,
                    f"{X}_edge": float(min(c[0], c[1], W - 1 - c[0], H - 1 - c[1])), f"{X}_open3": open3, f"{X}_block2": float(block2),
                    f"{X}_exits": float(exits), f"{X}_shape": 0.0 if exits <= 1 else 1.0 if open3 < 0.55 else 2.0})
        dX = _bfs(m, [(x + dx, y + dy) for (x, y) in pts for dx, dy in DIRS8 if passable((x + dx, y + dy))], blocked)
        entries = []
        for S in SRC:
            dS = sdist.get(S)
            tot = walk_to(dS, pts) if dS else None
            if not dS or tot is None:
                out.update({f"{X}_{S}_routes": 0.0, f"{X}_{S}_width": 0.0, f"{X}_{S}_bush": 0.0, f"{X}_{S}_choke": 0.0})
                continue
            lim = 1.1 * tot + 1
            near = {q for q in dS if q in dX and dS[q] + dX[q] <= lim}
            rflags = [q in near for q in rg]
            if S == "fs":
                entries = [q for q in rg if q in near]
            lev = collections.defaultdict(list)
            for q in near:
                lev[dS[q]].append(q)
            lo = int(0.2 * tot)
            widths = [len(v) for k, v in lev.items() if lo <= k <= tot]
            choke = 0.0
            for k, v in lev.items():
                if lo <= k <= tot - 2 and v:
                    xs, ys = [q[0] for q in v], [q[1] for q in v]
                    if max(max(xs) - min(xs), max(ys) - min(ys)) <= 8:
                        choke = 1.0
                        break
            out.update({f"{X}_{S}_routes": float(arcs(rflags)), f"{X}_{S}_width": float(min(widths) if widths else 0),
                        f"{X}_{S}_bush": sum(1 for q in near if q in bush) / max(1, len(near)), f"{X}_{S}_choke": choke})
        hm, hc = 99.0, 99.0
        if entries:
            dE = {}
            for e in entries[:12]:
                de = _bfs(m, [e], blocked)
                for q, v in de.items():
                    if max(abs(q[0] - c[0]), abs(q[1] - c[1])) <= 6:
                        dE[q] = max(dE.get(q, 0), v)
            if dE:
                h = min(dE, key=lambda q: (dE[q], dfarm.get(q, 9999)))
                hm, hc = float(dE[h]), float(dfarm.get(h, 99))
        out.update({f"{X}_hold_maxw": hm, f"{X}_hold_cost": hc})
    return out


def _one(p):
    try:
        return os.path.basename(p)[:-7], feats(p)
    except Exception:  # noqa: BLE001
        return os.path.basename(p)[:-7], None


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--procs")]
    procs = next((int(x.split("=")[1]) for x in sys.argv[1:] if x.startswith("--procs=")), 8)
    out, globs = args[0], args[1:]
    paths = [p for g in globs for p in glob.glob(g) if p.endswith(".map26a")]
    import multiprocessing as mp
    with mp.Pool(procs) as pool:
        res = pool.map(_one, paths, chunksize=10)
    with open(out + ".new", "w") as fh:
        fh.write("map\t" + "\t".join(COLS) + "\n")
        for m_, f in res:
            if f:
                fh.write(m_ + "\t" + "\t".join(f"{f.get(c, -1.0):.4g}" for c in COLS) + "\n")
    os.replace(out + ".new", out)
    print(f"gplaltar: {sum(1 for _, f in res if f)} of {len(paths)} maps -> {out} ({len(COLS)} columns)")


if __name__ == "__main__":
    main()
