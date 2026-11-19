"""ccb: RC X277's contested-centre class (p6/x277_holeclass.md; logic copied from p6/x277/feat.py; pre-registered confirm b1827, 11 Nov).
G = the biggest gem group (4-connected camp tiles; gems per tile: wolf 4, elk 15, gem 7, gold 0, monolith 200, golem 36).
  ccb     : 1 when G gems >= 100, G gems / all camp gems >= .30 and |dA - dB| / max(dA, dB) <= .15, else 0
            (dA, dB = 8-way walk from each spawn to a land tile next to G; walls, holes, altars, camps and the foe spawn block)
  ccb_bal : the walk balance itself (None when either spawn cannot reach G)
e.g. stratmaps --class 'ccb:1'. Map data only; no caches written."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_cache = {}


def _feat(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    W, H = d['W'], d['H']
    camps, alt = d['camps'], set(d['altar'])
    block = set(d['wall']) | set(d['hole']) | alt | set(camps)
    spA, spB = list(d['spawnA']), list(d['spawnB'])

    def bfs(starts, esp):
        dist = {s: 0 for s in starts}
        q = deque(starts)
        esp = set(esp)
        while q:
            c = q.popleft()
            for dx, dy in N8:
                n = (c[0] + dx, c[1] + dy)
                if 0 <= n[0] < W and 0 <= n[1] < H and n not in dist and n not in block and n not in esp:
                    dist[n] = dist[c] + 1
                    q.append(n)
        return dist
    wA, wB = bfs(spA, spB), bfs(spB, spA)
    seen, best = set(), None
    tot = sum(GEMS[camps[p]] for p in camps)
    for c in sorted(camps):
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
        gem = sum(GEMS[camps[p]] for p in comp)
        if best is None or gem > best[0]:
            best = (gem, comp)
    if not best or tot <= 0:
        _cache[path] = (0, 0.0, None)
        return _cache[path]
    gem, g = best
    nb = {(x + dx, y + dy) for x, y in g for dx, dy in N8} - set(g)
    da = min([wA[p] for p in nb if p in wA], default=None)
    db = min([wB[p] for p in nb if p in wB], default=None)
    bal = None if da is None or db is None else abs(da - db) / max(1, max(da, db))
    _cache[path] = (gem, gem / tot, bal)
    return _cache[path]


def ccb(path, _m=None):
    gem, share, bal = _feat(path)
    return 1 if gem >= 100 and share >= 0.30 and bal is not None and bal <= 0.15 else 0


def ccb_bal(path, _m=None):
    return _feat(path)[2]


CLASSES = {"ccb": ccb, "ccb_bal": ccb_bal}
