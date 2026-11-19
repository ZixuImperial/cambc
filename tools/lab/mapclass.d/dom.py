"""dom: Path Finding's DOM map trigger (11 Nov, /data/USER/st/pathf/own_cb16s/domk.py, replay side) as a map-side class for rare banks
(DMW b1896, CXR b1894). Tool Builder 11 Nov.
  dom = 1 when one reachable 4-connected camp group with NO monolith and NO golem holds >= 35% and < 80% of all reachable camp gems, >= 30
        gems, and >= 3x the next group's gems; else 0. None when no reachable group has gems.  -> stratmaps --class 'dom:>=1'
  Reachability as heavy_ge2 (8-way walk from either spawn; walls, holes, altars and camp tiles block; teleport-only groups do not count).
  Not modelled from the map alone: the replay trigger's '<= 4 attackers' (a game-time count); a map passing here can still not fire in a game."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genmaps as G  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # 0 wolf, 1 elk, 2 gem, 3 gold, 4 monolith, 5 golem
_cache = {}


def _groups(path):
    d = G.map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = set(d["spawnA"]) | set(d.get("spawnB") or ())
    q = deque(reach)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in reach:
                    reach.add(n)
                    q.append(n)
    seen, out = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        if not any((x + dx, y + dy) in reach for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            continue
        types = [camps[t] for t in comp]
        out.append((sum(GEM[t] for t in types), set(types)))
    return out


def dom(path):
    if path in _cache:
        return _cache[path]
    gs = _groups(path)
    tot = sum(g for g, _ in gs)
    if not tot:
        _cache[path] = None
        return None
    v = 0
    for i, (g, ty) in enumerate(gs):
        if 4 in ty or 5 in ty or g < 30:
            continue
        nxt = max((h for j, (h, _) in enumerate(gs) if j != i), default=0)
        if 0.35 <= g / tot < 0.80 and g >= 3 * nxt:
            v = 1
            break
    _cache[path] = v
    return v


CLASSES = {"dom": dom}
