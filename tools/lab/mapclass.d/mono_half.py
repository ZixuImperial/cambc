"""mono_half (b2041, 12 Nov; Planner's JKP 'Second count': a monolith in each half). A group (4-connected camp tiles, mono_own's rule)
with >= 1 monolith tile is in A's own half when dA/(dA+dB) < .45, B's when > .55 (walk model as mono_own). mono_half = number of
sides (0-2) with such a group.  -> --class 'mono_half:>=2'. Draft-time map features only; per-process memo only."""
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
    seen, side = set(), [0, 0]
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
        if not any(camps[p] == MONO for p in comp):
            continue
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
        if r < 0.45:
            side[0] = 1
        elif r > 0.55:
            side[1] = 1
    _c[path] = sum(side)
    return _c[path]


def mono_half(path, _g=None):
    return _calc(path)


CLASSES = {"mono_half": mono_half}
