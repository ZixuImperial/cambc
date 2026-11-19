"""a2m (b2339, 12 Nov; spec_och_1112.md re-gate, VV cell form): the A2M class (Willow for Vendetta) from the map file, draft-time only.
a2m_chain = 1 when a camp group (4-connected camp tiles) walk-reachable from spawn A (8-way; walls, holes, altars block; camps passable)
            has >= 2 members, every member a cluster (gem or gold), and value > 0: the bot's S.dr_ve > 0 (draft_map_features.cc:589-596).
a2m_far0  = 1 when no farmable group (walk-reachable, no monolith, contest dA / (dA + dB) <= .6, value 10 x gems + gold > 0) walks beyond
            1.5 x the value-weighted median walk (the b2339 stock FAR = 0; dash-only groups are left out here, the bot counts them).
a2m       = 1 on five-pick maps with a2m_chain = 0 and a2m_far0 = 1. -> --class 'a2m:>=1'."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
CLU = {2, 3}
_c = {}


def _bfs(W, H, block, roots):
    d = {}
    q = deque()
    for p in roots:
        if p not in block and p not in d:
            d[p] = 0
            q.append(p)
    while q:
        x, y = q.popleft()
        v = d[(x, y)] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                    d[n] = v
                    q.append(n)
    return d


def _feat(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = _bfs(W, H, block, m["spawnA"]), _bfs(W, H, block, m["spawnB"])
    seen, chain, walks = set(), 0, []
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
        a = min((dA[t] for t in comp if t in dA), default=None)
        if a is None:
            continue
        b = min((dB[t] for t in comp if t in dB), default=None)
        gems = sum(GEMS.get(camps[t], 0) for t in comp)
        gold = sum(GOLD.get(camps[t], 0) for t in comp)
        mono = any(camps[t] == 4 for t in comp)
        if not mono and len(comp) >= 2 and all(camps[t] in CLU for t in comp) and gems + gold > 0:
            chain = 1
        con = a / (a + b) if b is not None and a + b > 0 else 0.0
        val = 10 * gems + gold
        if not mono and con <= 0.6 and val > 0:
            walks.append((a, val))
    far0 = 1
    if walks:
        walks.sort()
        tot = sum(v for _, v in walks)
        acc, med = 0, walks[-1][0]
        for d, v in walks:
            acc += v
            if 2 * acc >= tot:
                med = d
                break
        far0 = 0 if any(2 * d > 3 * med for d, _ in walks) else 1
    r = (int(m["champs_per_team"]), chain, far0)
    _c[path] = r
    return r


def a2m_chain(path):
    return _feat(path)[1]


def a2m_far0(path):
    return _feat(path)[2]


def a2m(path):
    k, chain, far0 = _feat(path)
    return 1 if k == 5 and chain == 0 and far0 == 1 else 0


CLASSES = {"a2m_chain": a2m_chain, "a2m_far0": a2m_far0, "a2m": a2m}
