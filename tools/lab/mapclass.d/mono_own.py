"""mono_own (b2027, 11 Nov; spec condor-work/reports/analysts/spec_dmt_1111.md, class MONO_OWN): own-half monolith-group gems.
A group is a 4-connected component of camp tiles (mapclass.groups' rule); it is a MONO3 group when it holds >= 3 monolith tiles.
Each group's walk distance to a side = min 8-way walk from that side's spawn tiles to any walkable tile next to (or on) the group
(walls and holes block; replay.py/own_gold's walk model). The group is in A's own half when dA/(dA+dB) < .5, B's when > .5 (ties: neither).
mono_own = 2 * min(side A share, side B share), share = that side's own-half MONO3 group gems / all group gems (gems per tile: mapfeat.GEMS).
On a mirror map it is the both-sides own-half MONO3 gem share.  -> --class 'mono_own:>=0.5' (strict adaptation: >=0.8).
mono3_n = number of MONO3 groups (any half). Draft-time map features only; no caches written (per-process memo only)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
MONO = 4
_c = {}


def _bfs(d, src):
    W, H = d['W'], d['H']
    block = set(d['wall']) | set(d['hole']) | set(d['camps'])
    dist = {p: 0 for p in src}
    q = deque(src)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    return dist


def _calc(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d['camps']
    da, db = _bfs(d, list(d['spawnA'])), _bfs(d, list(d['spawnB']))
    seen, tot, own, n3 = set(), 0, [0, 0], 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        gems = sum(mapfeat.GEMS[camps[p]] for p in comp)
        tot += gems
        if sum(camps[p] == MONO for p in comp) < 3:
            continue
        n3 += 1
        ga = gb = None
        for x, y in comp:
            for dx, dy in N8:
                p = (x + dx, y + dy)
                if p in da:
                    ga = da[p] if ga is None else min(ga, da[p])
                if p in db:
                    gb = db[p] if gb is None else min(gb, db[p])
        if ga is None or gb is None:
            continue
        r = ga / max(1, ga + gb)
        if r < 0.5:
            own[0] += gems
        elif r > 0.5:
            own[1] += gems
    v = round(2 * min(own) / tot, 4) if tot else None
    _c[path] = (v, n3)
    return _c[path]


def mono_own(path, _g=None):
    return _calc(path)[0]


def mono3_n(path, _g=None):
    return _calc(path)[1]


CLASSES = {"mono_own": mono_own, "mono3_n": mono3_n}
