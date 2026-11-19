"""shyrm (b2340, 12 Nov; Prism Planner's SHYR rare read, spec_shy_ifl_1112.md last section): rich MIXED camp groups, draft-time map
features only (camps, walls, holes, altars, spawns), no map identity.
  shyrm_n : camp groups (4-connected camp components, GR:206) with gems >= 60 AND gold > 0 (gems / gold per mapfeat.GEMS / GOLD) that a
            body can walk next to from either team's spawn (8-way walk; walls, holes, altars and camps block).
  shyrm   : 1 when shyrm_n >= 2, else 0.   -> stratmaps --class 'shyrm:>=1'"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '/homes/zw4424/cambc/tools/lab')
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


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


def groups(path):
    """[(gems, gold, reachable)] per camp group."""
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps, W, H = d["camps"], d["W"], d["H"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = set(_bfs(W, H, block, d["spawnA"])) | set(_bfs(W, H, block, d["spawnB"]))
    seen, out = set(), []
    for c in sorted(camps):
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
        gold = sum(mapfeat.GOLD[camps[p]] for p in comp)
        rch = any((x + dx, y + dy) in reach for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        out.append((gems, gold, rch))
    _c[path] = out
    return out


def shyrm_n(path, _g=None):
    return sum(1 for gm, gd, r in groups(path) if gm >= 60 and gd > 0 and r)


def shyrm(path, _g=None):
    return 1 if shyrm_n(path) >= 2 else 0


CLASSES = {"shyrm_n": shyrm_n, "shyrm": shyrm}
