"""heavy_share: Econ's HEAVY_SHARE (spec_a135_1112, A3 GJB; b2153 12 Nov): gems of the golem-only groups (4-connected camp groups with
  >= 1 golem tile and no monolith; every tile of the group counts) / gems of all groups. Reachable groups only (heavy_ge2's walk test:
  8-way from either spawn, walls/holes/altars/camps blocked, a land tile next to the group).  -> stratmaps --class 'heavy_share:>=0.3'
  None when no reachable group has gems."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genmaps as G  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # 0 wolf, 1 elk, 2 gem, 3 gold, 4 monolith, 5 golem
_cache = {}


def heavy_share(path):
    if path in _cache:
        return _cache[path]
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
    seen, num, den = set(), 0, 0
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
        gems = sum(GEM[t] for t in types)
        den += gems
        if 5 in types and 4 not in types:
            num += gems
    _cache[path] = num / den if den else None
    return _cache[path]


CLASSES = {"heavy_share": heavy_share}
