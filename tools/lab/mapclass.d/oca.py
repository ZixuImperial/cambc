"""oca (b2390 OCA, 13 Nov; Deep spec_oca_1113.md): the CONTESTED OPENER class from the map file, draft-time only, no map identity.
Groups = 4-connected camp tiles. A group with no attacker (every member a gem or gold cluster), >= 20 gems, whose walk from each spawn
(8-way steps over tiles that are not wall, hole, altar or camp, to a tile next to a member) is <= 8 for both spawns, the two within 2.
The bot decides it from its own group walks (d_home / d_enemy, econ_opening_pick.cc oca::find); this plugin approximates them.
oca = 1 when such a group exists; oca_gems = the richest such group's gems; oca_walk = its walk from spawn A (99 if none).
-> --class 'oca:>=1'."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
CLU = {2, 3}
_c = {}


def _bfs(m, starts):
    W, H = m["W"], m["H"]
    blk = m["wall"] | m["hole"] | m["altar"] | set(m["camps"])
    d = {s: 0 for s in starts}
    q = deque(starts)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in blk and n not in d:
                    d[n] = d[(x, y)] + 1
                    q.append(n)
    return d


def _feat(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    camps = m["camps"]
    seen, groups = set(), []
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
        groups.append(comp)
    da, db = _bfs(m, list(m["spawnA"])), _bfs(m, list(m["spawnB"]))

    def walk(d, g):
        best = 99
        for (x, y) in g:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    best = min(best, d.get((x + dx, y + dy), 99))
        return best + 1  # the bot counts the step onto the member (d_home 4 where this BFS gives 3; checked on 2 maps)

    r = (0, 0, 99)
    for g in groups:
        gems = sum(GEMS.get(camps[t], 0) for t in g)
        if gems < 20 or not all(camps[t] in CLU for t in g):
            continue
        a, b = walk(da, g), walk(db, g)
        if a <= 8 and b <= 8 and abs(a - b) <= 2 and gems > r[1]:
            r = (1, gems, a)
    _c[path] = r
    return r


def oca(path):
    return _feat(path)[0]


def oca_gems(path):
    return _feat(path)[1]


def oca_walk(path):
    return _feat(path)[2]


CLASSES = {"oca": oca, "oca_gems": oca_gems, "oca_walk": oca_walk}
