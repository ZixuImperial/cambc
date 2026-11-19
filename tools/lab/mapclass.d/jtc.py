"""jtc (12 Nov, Tool Builder; Deep/RC C643 FINAL key, JTC rare-lane class, spec condor-work/reports/analysts/spec_jtc_1112.md; the bot will store
it as MCL4 bit 2). Static map fields only, no map identity.
  groups = 4-connected camp components (as mapfeat / the bot's M.groups). The class group = the group with the most gems (ties: most camp HP,
  then the first in sorted tile order). jtc = 1 when ALL hold:
    jtc_share  = class group's gems / all camps' gems >= 0.80
    jtc_hp     = class group's total camp HP (GameRules table) >= 5,000
    jtc_siege  = its monolith + golem camps == 0
    jtc_spawn  = steps from the nearer spawn to stand next to the group > 12: 8-way BFS from every spawn tile, walls / holes / altars / camps
                 block (as jackpot.py); steps = min over the group's camp tiles of (min distance of a walkable 8-neighbour) + 1; unreachable = 999
Camp kinds (map26a / mapfeat): 0 wolf, 1 elk, 2 gem cluster, 3 gold cluster, 4 monolith, 5 golem."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
HP = {0: 1350, 1: 2400, 2: 120, 3: 120, 4: 20000, 5: 5000}
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_cache = {}


def _bfs(W, H, src, block):
    dist = {p: 0 for p in src if p not in block}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    return dist


def _feats(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    seen, groups = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [c], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n in camps and n not in seen:
                    seen.add(n)
                    comp.append(n)
                    st.append(n)
        groups.append(comp)
    allg = sum(GEMS.get(k, 0) for k in camps.values())
    if not groups or allg <= 0:
        r = dict(jtc=0.0, jtc_share=0.0, jtc_hp=0.0, jtc_siege=0.0, jtc_spawn=999.0)
        _cache[path] = r
        return r
    gem = lambda g: sum(GEMS.get(camps[p], 0) for p in g)  # noqa: E731
    hp = lambda g: sum(HP.get(camps[p], 0) for p in g)  # noqa: E731
    g = max(groups, key=lambda g: (gem(g), hp(g)))  # max keeps the first of equal groups (sorted tile order)
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    steps = 999
    for spawn in ("spawnA", "spawnB"):
        dist = _bfs(W, H, list(d[spawn]), block)
        for p in g:
            nb = [dist[(p[0] + dx, p[1] + dy)] for dx, dy in N8 if (p[0] + dx, p[1] + dy) in dist]
            if nb:
                steps = min(steps, min(nb) + 1)
    share, ghp = gem(g) / allg, hp(g)
    siege = sum(1 for p in g if camps[p] in (4, 5))
    r = dict(jtc_share=round(share, 4), jtc_hp=float(ghp), jtc_siege=float(siege), jtc_spawn=float(steps),
             jtc=1.0 if share >= 0.80 and ghp >= 5000 and siege == 0 and steps > 12 else 0.0)
    _cache[path] = r
    return r


CLASSES = {k: (lambda k: lambda path: _feats(path)[k])(k) for k in ("jtc", "jtc_share", "jtc_hp", "jtc_siege", "jtc_spawn")}
