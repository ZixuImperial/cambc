"""own_gold (Econ, 11 Nov; replay version /data/zw4424/st/econ_work_1109/goldring/run.py): own-half gold groups. A 4-connected camp group
counts for a side when its first tile (map26a camp order) is in that side's OWN zone (replay.py's rule: walk ratio dOwn/(dOwn+dFoe) < .4 at
the tile or its first 8-neighbour both sides reach; walls and holes block) and it has gold >= 40 and gems <= 8 (mapfeat GOLD/GEMS per tile).
own_gold = the minimum over the two sides.  -> --class 'own_gold:>=5'. Draft-time map features only. Tool Builder 11 Nov."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_c = {}


def _bfs(d, src):
    W, H = d['W'], d['H']
    block = set(d['wall']) | set(d['hole'])
    dist = {p: 0 for p in src}
    q = deque(src)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    return dist


def own_gold(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d['camps']
    da, db = _bfs(d, list(d['spawnA'])), _bfs(d, list(d['spawnB']))
    seen, cnt = set(), [0, 0]
    for c in camps:
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
        gold = sum(mapfeat.GOLD[camps[p]] for p in comp)
        gems = sum(mapfeat.GEMS[camps[p]] for p in comp)
        if gold < 40 or gems > 8:
            continue
        x, y = c
        for dx, dy in ((0, 0),) + tuple(N8):
            p = (x + dx, y + dy)
            if p in da and p in db:
                ra = da[p] / max(1, da[p] + db[p])
                cnt[0] += ra < 0.4
                cnt[1] += (1 - ra) < 0.4 if da[p] + db[p] else 0
                break
    _c[path] = min(cnt)
    return _c[path]


CLASSES = {"own_gold": own_gold}
