"""shv (13 Nov, TB for b2429 SHV): 1 when a camp group (4-connected camp tiles) that holds a monolith or golem tile has a member tile within
Chebyshev 3 of a spawn tile of either team (maps are symmetric, so either side counts), else 0. Mirrors shv_class in econ_team_model.cc
(Chebyshev <= 3 to our spawn tiles, mono/golem groups only). Witness: 03homonoliths (3-monolith groups inside each spawn box).
  shv      -> --class 'shv:>=1'
  shv_n    the number of such groups."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}


def _f(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    camps = d["camps"]
    spawn = set(d["spawnA"]) | set(d["spawnB"])
    seen, n = set(), 0
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
        if not any(camps[g] in (4, 5) for g in grp):
            continue
        if any(max(abs(gx - sx), abs(gy - sy)) <= 3 for gx, gy in grp for sx, sy in spawn):
            n += 1
    _cache[path] = n
    return n


CLASSES = {"shv": lambda p, _m=None: 1 if _f(p) else 0, "shv_n": lambda p, _m=None: _f(p)}
