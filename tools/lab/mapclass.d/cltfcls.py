"""cltfcls (b2273 CLTF read split, owner via Planner 12 Nov; draft-time map features only, no map identity, seat-free on mirrored maps).
  cltf_ng      = number of camp groups (4-connected camp tiles) that a walk from either spawn reaches (8-way BFS; walls, holes, altars
                 block; camps passable, as dead), i.e. farmable groups.
  cltf_cshare  = value of the farmable groups with contest d_A / (d_A + d_B) in [.4, .6] / value of all farmable groups; value = gold +
                 10 x gems (GameRules camp table: wolf 40/4, elk 90/15, golem 160/36, gem cluster 0/7, gold cluster 20/0, monolith 300/200).
  cltf_in      = 1 when cltf_ng >= NG_CUT and cltf_cshare <= CS_CUT (cuts fixed from the stock before the read: see CUTS)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

CUTS = {"NG_CUT": 20, "CS_CUT": 0.3619}  # fixed 12 Nov from 448 stock fresh maps (b2273 maps300c + maps150z) before any CLTF read: NG median, CS lower tercile
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
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
    seen = set()
    ng = 0
    tot = con = 0.0
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
        b = min((dB[t] for t in comp if t in dB), default=None)
        if a is None and b is None:
            continue
        ng += 1
        v = sum(GOLD.get(camps[t], 0) + 10 * GEMS.get(camps[t], 0) for t in comp)
        tot += v
        if a is not None and b is not None and a + b > 0 and .4 <= a / (a + b) <= .6:
            con += v
    r = (ng, con / tot if tot > 0 else 0.0)
    _c[path] = r
    return r


def cltf_ng(path):
    return _feat(path)[0]


def cltf_cshare(path):
    return _feat(path)[1]


def cltf_in(path):
    ng, cs = _feat(path)
    return 1 if ng >= CUTS["NG_CUT"] and cs <= CUTS["CS_CUT"] else 0


CLASSES = {"cltf_ng": cltf_ng, "cltf_cshare": cltf_cshare, "cltf_in": cltf_in}
