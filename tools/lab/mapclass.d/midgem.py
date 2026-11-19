"""midgem (repo copy of /data/zw4424/st/combat_py/midgem/midgem.py, Tool Builder 11 Nov for CLS b1899; Combat 973226 + Planner, 11 Nov; Stage A of the gem-centre crew line).
midgem_share = gems of camp groups whose zone is 'mid' / all camp gems. Zone = replay.py's rule: r = dA/(dA+dB) by 8-way walk
distance from each spawn over tiles that are not wall/hole (camp tiles count as walkable), taken at the group tile nearest the
group's centroid; mid if .4 <= r <= .6 (symmetric, so the same for both seats). Gems per camp tile: mapfeat.GEMS.
midgem = 1 when midgem_share >= .70, else 0. None when the map has no camp gems. Draft-time map features only, no map identity."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


def _bfs(d, src):
    W, H = d['W'], d['H']
    block = set(d['wall']) | set(d['hole'])
    dist = {p: 0 for p in src}
    q = deque(src)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if (dx or dy) and 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                    dist[p] = dist[(x, y)] + 1
                    q.append(p)
    return dist


def _parts(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d['camps']
    da, db = _bfs(d, list(d['spawnA'])), _bfs(d, list(d['spawnB']))
    seen, tot, mid = set(), 0, 0
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
        g = sum(mapfeat.GEMS[camps[p]] for p in comp)
        tot += g
        cx, cy = sum(p[0] for p in comp) / len(comp), sum(p[1] for p in comp) / len(comp)
        t = min((p for p in comp if p in da and p in db), key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2, default=None)
        if t is not None:
            r = da[t] / max(1, da[t] + db[t])
            if .4 <= r <= .6:
                mid += g
    _c[path] = mid / tot if tot else None
    return _c[path]


def midgem_share(path, _g=None):
    s = _parts(path)
    return None if s is None else round(s, 4)


def midgem(path, _g=None):
    s = _parts(path)
    return 1 if s is not None and s >= .70 else 0


CLASSES = {"midgem": midgem, "midgem_share": midgem_share}


if __name__ == '__main__':
    import glob
    for a in sys.argv[1:]:
        for f in sorted(glob.glob(a)):
            print(midgem_share(f), midgem(f), os.path.basename(f))
