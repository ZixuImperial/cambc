"""recallcost: RECALL_COST (b2115 12 Nov, WSP owner line from 05savanna 01a1cd69; Planner's definition,
/data/zw4424/st/planner/willowspread/py/rc.py, result.md there). Draft-time map features only.
  Per seat: gem-weighted mean 8-way walk from the spawn tiles to the nearest tile next to each 4-connected camp group on that seat's
  side (d_own <= d_enemy); walls, holes, altars and camps block. Map value = mean of the two seats (0 when a seat has no own group).
  recallcost   : that mean       -> stratmaps --class 'recallcost:>=30.4' (fresh top tercile, Planner terciles 18.3 / 30.4)
  recallcost_a / recallcost_b : each seat's value (the bot computes its own seat's)"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # camp type -> gems (wolf, elk, gem cluster, gold cluster, monolith, golem)
_cache = {}


def _bfs(W, H, block, src):
    dist = {s: 0 for s in src if s not in block}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in dist:
                    dist[n] = dist[(x, y)] + 1
                    q.append(n)
    return dist


def _gd(dist, pts):
    return min((dist[(x + dx, y + dy)] for x, y in pts for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (x + dx, y + dy) in dist), default=None)


def feats(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    camps = d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    seen, groups = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [c], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    comp.append(n)
                    st.append(n)
        groups.append((sum(GEM[camps[p]] for p in comp), comp))
    dA, dB = _bfs(d["W"], d["H"], block, d["spawnA"]), _bfs(d["W"], d["H"], block, d["spawnB"])
    rows = []
    for gems, pts in groups:
        a, b = _gd(dA, pts), _gd(dB, pts)
        if a is not None and b is not None:
            rows.append((gems, a, b))
    out = {}
    for side, i, j in (("a", 1, 2), ("b", 2, 1)):
        own = [(r[0], r[i]) for r in rows if r[i] <= r[j]]
        w = sum(g for g, _ in own)
        out[side] = round(sum(g * x for g, x in own) / w, 2) if w else 0.0
    out["rc"] = round((out["a"] + out["b"]) / 2, 2)
    _cache[path] = out
    return out


CLASSES = {"recallcost": lambda p, _m=None: feats(p)["rc"], "recallcost_a": lambda p, _m=None: feats(p)["a"],
           "recallcost_b": lambda p, _m=None: feats(p)["b"]}
