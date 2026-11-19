"""deep: b2096 GFD class DEEP (12 Nov, GFP adaptation; RC X524 fcost.py). Draft-time map features only, team A's view.
  deep_charge = min(40000, (espawn + 16) x chunks): the host's charge for a whole-map walk field from our spawn, where espawn is the
                8-way BFS depth from spawnA (walls, holes, altars and the enemy spawn block, as mapinfo's f_home) and chunks = ceil(W/8) x ceil(H/8)
  deep = 1 when deep_charge > 3 W H + 3000 (the bot's size price field_cost), else 0.  -> stratmaps --class 'deep:>=1'
Mirrors mcl4_compute()'s GFD line (MCL4 bit 16). RC X524 fc_*: fresh 3/100, BIG2 28/400, w_longpath 100/100."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}


def _charge(path):
    if path not in _cache:
        d = map26a.load(path)
        W, H = d["W"], d["H"]
        blk = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(d["spawnB"])
        roots = [p for p in d["spawnA"] if p not in blk]
        dist = {r: 0 for r in roots}
        q = collections.deque(roots)
        m = 0
        while q:
            x, y = q.popleft()
            dd = dist[(x, y)]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in dist and n not in blk:
                        dist[n] = dd + 1
                        m = max(m, dd + 1)
                        q.append(n)
        ch = ((W + 7) // 8) * ((H + 7) // 8)
        _cache[path] = (min(40000, (m + 16) * ch), 3 * W * H + 3000)
    return _cache[path]


def deep_charge(path, _m=None):
    return _charge(path)[0]


def deep(path, _m=None):
    c, fc = _charge(path)
    return 1 if c > fc else 0


CLASSES = {"deep": deep, "deep_charge": deep_charge}
