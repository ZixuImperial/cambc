"""toa (b1979, CI Planner spec_toa_1111, 11 Nov): Tavi-on-one-altar class reads, port of the study's feat.py
(/data/USER/st/fablean/tavialtar/feat.py, cut C in agg.py:18). Map file only, no writes (safe on Condor nodes).
  toa_g10 = per-capture gold (mapfeat.GOLD: wolf 40, elk 90, gold cluster 20, golem 160, monolith 300) of camp tiles within 10 8-way walk
            steps (walls, holes and altar tiles block) of the altar ring, on maps with exactly ONE altar (8-connected altar tiles); else 0.
  toa_c   = 1 if cut C (one altar and toa_g10 >= 200), else 0          -> --class 'toa_c:>=1'   (== 'toa_g10:>=200')
  toa_g10s = toa_g10 / all map gold (cut A adds toa_g10s >= .25)"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_c = {}


def _calc(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    W, H = d["W"], d["H"]
    alt = set(d["altar"])
    seen, nc = set(), 0
    for a in alt:
        if a in seen:
            continue
        nc += 1
        st = [a]
        seen.add(a)
        while st:
            x, y = st.pop()
            for dx, dy in N8:
                q = (x + dx, y + dy)
                if q in alt and q not in seen:
                    seen.add(q)
                    st.append(q)
    camps = d["camps"]
    gold = sum(mapfeat.GOLD[v] for v in camps.values())
    g10 = 0
    if nc == 1:
        block = set(d["wall"]) | set(d["hole"]) | alt
        ring = {(x + dx, y + dy) for x, y in alt for dx, dy in N8
                if 0 <= x + dx < W and 0 <= y + dy < H and (x + dx, y + dy) not in block}
        dist = {p: 0 for p in ring}
        q = deque(ring)
        while q:
            x, y = q.popleft()
            if dist[(x, y)] >= 10:
                continue
            for dx, dy in N8:
                p = (x + dx, y + dy)
                if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                    dist[p] = dist[(x, y)] + 1
                    q.append(p)
        g10 = sum(mapfeat.GOLD[v] for p, v in camps.items() if dist.get(p, 999) <= 10)
    _c[path] = (g10, gold)
    return _c[path]


def toa_g10(path):
    return _calc(path)[0]


def toa_c(path):
    return 1 if _calc(path)[0] >= 200 else 0


def toa_g10s(path):
    g10, gold = _calc(path)
    return g10 / gold if gold > 0 else 0.0


CLASSES = {"toa_g10": toa_g10, "toa_c": toa_c, "toa_g10s": toa_g10s}
