"""ssa (13 Nov, TB for Deep's SSA, spec condor-work/reports/analysts/spec_ssa_1112.md REWORK 01:50Z; Builder: MCL_SSA): siege map with a monolith
group next to a spawn that holds >= half of that side's gems. ssa = 1 when, for EITHER seat (seat-free on mirrored maps):
  (a) open gem share < .15 (siegemono.open_share: gems of 4-connected camp groups with no monolith / golem tile over all gems), AND
  (b) a monolith group (4-connected camp tiles, one camp per tile as the engine) has a camp within 1 tile (Chebyshev) of a tile of that seat's
      spawn rect, AND (c) that group holds >= half of the seat's half's gems (the half = camp tiles nearer that seat's spawn centre than the
      other's; ties go to neither)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MONO = 4
_cache = {}


def _groups(camps):
    seen, out = set(), []
    for c in camps:
        if c in seen:
            continue
        st, tiles = [c], []
        seen.add(c)
        while st:
            x, y = st.pop()
            tiles.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        out.append(tiles)
    return out


def ssa(path, _g=None):
    if path in _cache:
        return _cache[path]
    import genmaps as G
    import mapfeat
    import siegemono
    s = siegemono.open_share(path)
    if s is None or s >= 0.15:
        _cache[path] = 0
        return 0
    d = G.map26a.load(path)
    camps = d["camps"]
    sp = {"A": list(d["spawnA"]), "B": list(d.get("spawnB") or [])}
    if not sp["A"] or not sp["B"]:
        _cache[path] = 0
        return 0
    cen = {k: (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v)) for k, v in sp.items()}
    gs = _groups(camps)
    r = 0
    for me, foe in (("A", "B"), ("B", "A")):
        def d2(p, k):
            return (p[0] - cen[k][0]) ** 2 + (p[1] - cen[k][1]) ** 2
        half = sum(mapfeat.GEMS[camps[c]] for c in camps if d2(c, me) < d2(c, foe))
        if half <= 0:
            continue
        spt = set(sp[me])
        for tiles in gs:
            if not any(camps[t] == MONO for t in tiles):
                continue
            near = any((x + dx, y + dy) in spt for x, y in tiles for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if near and 2 * sum(mapfeat.GEMS[camps[t]] for t in tiles) >= half:
                r = 1
                break
        if r:
            break
    _cache[path] = r
    return r


CLASSES = {"ssa": ssa}
