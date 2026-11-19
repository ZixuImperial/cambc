"""monoreach (13 Nov, TB for the PGF reads; Builder: 'maps with a walkable monolith group our spawn reaches'): 1 when a camp group
(4-connected camp tiles) holding a monolith tile has a member tile that an 8-way walk from a seat's spawn tiles reaches or touches (walls,
holes, altar tiles and the foe spawn block; camps passable, as oneal.py's d_home walk), for either seat (maps are symmetric); else 0.
  monoreach -> --class 'monoreach:>=1'; also a late split class in the fresh-maps row (stylepanel CLS_LATE)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}
D8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def _f(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    seen, groups = set(), []
    for t in camps:
        if t in seen:
            continue
        grp, q = [], deque([t])
        seen.add(t)
        while q:
            x, y = q.popleft()
            grp.append((x, y))
            for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nb in camps and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        if any(camps[g] == 4 for g in grp):
            groups.append(grp)
    out = 0
    if groups:
        base = set(d["wall"]) | set(d["hole"]) | set(d["altar"])
        for own, foe in ((d["spawnA"], d["spawnB"]), (d["spawnB"], d["spawnA"])):
            blk = base | set(foe)
            r = {s for s in own if s not in blk}
            q = deque(r)
            while q:
                x, y = q.popleft()
                for dx, dy in D8:
                    n = (x + dx, y + dy)
                    if 0 <= n[0] < W and 0 <= n[1] < H and n not in blk and n not in r:
                        r.add(n)
                        q.append(n)
            if any(any((gx + dx, gy + dy) in r for dx, dy in D8 + [(0, 0)]) for grp in groups for gx, gy in grp):
                out = 1
                break
    _cache[path] = out
    return out


CLASSES = {"monoreach": lambda p, _m=None: _f(p)}
