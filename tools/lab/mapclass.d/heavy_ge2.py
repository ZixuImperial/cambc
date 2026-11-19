"""heavy_ge2: Econ's HEAVY_GE2 (10 Nov 23:48Z; /data/USER/st/deepan/wgolem/heavy_def.txt, HEAVY_GE2 block).
  heavy_ge2 = gems of the ELK (15/tile) and GOLEM (36/tile) camp tiles themselves, in groups with no monolith (wolf, gem and gold tiles
              in the same group do NOT count) / gems of all groups. Class >= .50, off < .20  -> stratmaps --class 'heavy_ge2:>=0.5'
  Only reachable groups count, in both sums (the bot's ACC_WALK): a 4-connected camp group counts when an 8-way walk from either spawn (walls, holes, altars and
  camp tiles blocked; no teleports, so teleport-only groups do not count) reaches a land tile next to it.
  Earlier reads keep the label heavy_ge (v1: whole groups, no reachability). None when no reachable group has gems."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genmaps as G  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # 0 wolf, 1 elk, 2 gem, 3 gold, 4 monolith, 5 golem
_cache = {}


def heavy_ge2(path):
    if path in _cache:
        return _cache[path]
    d = G.map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = set(d["spawnA"]) | set(d.get("spawnB") or ())  # either spawn (Econ 11 Nov: asymmetric maps)
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
        den += sum(GEM[t] for t in types)
        if 4 not in types:
            num += sum(GEM[t] for t in types if t in (1, 5))
    _cache[path] = num / den if den else None
    return _cache[path]


CLASSES = {"heavy_ge2": heavy_ge2}
