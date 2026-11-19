"""sgs (13 Nov, Deep; candidate class from the owner replay 01a1d4ab-..., /data/zw4424/st/deepan/willowline/result.md). NOT an
archetype: a class for draft reads only (owner: 'only think of an archetype if it benefits us').
sgs_top = the largest camp group's share of the map's gems (group = 4-connected camp tiles; gems wolf 4, elk 15, gem cluster 7,
monolith 200, golem 36).
sgs_d1 = 1 when sgs_top >= .70, both spawns reach that group within 2 walk of each other and at >= 10 walk (8-direction BFS over
non-wall / non-hole / non-altar tiles), and an altar lies within Chebyshev 4 of one of its camps whose two spawn walks differ <= 2.
sgs_d2 = 1 when sgs_d1 and the band of tiles within Chebyshev 4 of the group's camps has wall share <= .05 and bush share <= .10
and the group's extent (max of its x and y spans) is >= 10.
Draft-time, map data only, seat-free."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import gpl  # noqa: E402

_c = {}


def feats(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    camps = m["camps"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = gpl._bfs(m, list(m["spawnA"]), blocked), gpl._bfs(m, list(m["spawnB"]), blocked)

    def walk(p):
        for dx, dy in ((0, 0),) + gpl.DIRS8:
            q = (p[0] + dx, p[1] + dy)
            if q in dA and q in dB:
                return dA[q], dB[q]
        return None

    seen, best, tot = set(), None, 0
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
        gm = sum(gpl.GEMS.get(camps[p], 0) for p in pts)
        tot += gm
        if best is None or gm > best[0]:
            best = (gm, pts)
    if not best or tot <= 0:
        _c[path] = None
        return None
    gm, pts = best
    top = gm / tot
    ws = [w for w in (walk(p) for p in pts) if w]
    wa, wb = (min(w[0] for w in ws), min(w[1] for w in ws)) if ws else (None, None)
    alt_ok = False
    for a in m["altar"]:
        if min(max(abs(a[0] - p[0]), abs(a[1] - p[1])) for p in pts) <= 4:
            w = walk(a)
            if w and abs(w[0] - w[1]) <= 2:
                alt_ok = True
    d1 = int(top >= 0.70 and wa is not None and abs(wa - wb) <= 2 and min(wa, wb) >= 10 and alt_ok)
    band = set()
    for (x, y) in pts:
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                q = (x + dx, y + dy)
                if 0 <= q[0] < m["W"] and 0 <= q[1] < m["H"]:
                    band.add(q)
    wall = sum(1 for q in band if q in m["wall"]) / max(1, len(band))
    bush = sum(1 for q in band if q in m["bush"]) / max(1, len(band))
    ext = max(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts)) + 1
    d2 = int(d1 and wall <= 0.05 and bush <= 0.10 and ext >= 10)
    _c[path] = dict(top=top, d1=d1, d2=d2, wall=wall, bush=bush, ext=ext, wa=wa, wb=wb)
    return _c[path]


def _f(k):
    def fn(path, _g=None):
        v = feats(path)
        return None if v is None else v[k]
    return fn


CLASSES = {"sgs_top": _f("top"), "sgs_d1": _f("d1"), "sgs_d2": _f("d2")}
