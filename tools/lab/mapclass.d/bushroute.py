"""bushroute (owner 11 Nov: "a lot of bushy maps, especially on key routes or hotspots, for vision limiting"; Tool Builder):
  bush_share  = bush tiles / walkable tiles
  bushroute   = share of KEY-ROUTE tiles that are bush: the tiles on one shortest 8-way walk from spawn A to spawn B, to the 3 richest camp
                groups (gems + gold/10) and to each altar (walls, holes block; camps and bush walkable)
  bushhot     = share of HOTSPOT tiles that are bush: walkable tiles within Chebyshev 3 of the board centre, of each altar and of the 3 richest groups
  bushy       = 1 when bushroute >= .20 or bushhot >= .25 (else 0)      -> --class 'bushy:>=1'"""
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
    wall, hole, bush, camps = set(d["wall"]), set(d["hole"]), set(d["bush"]), d["camps"]
    walk = lambda p: 0 <= p[0] < W and 0 <= p[1] < H and p not in wall and p not in hole  # noqa: E731
    src = list(d["spawnA"])
    par, dist, q = {p: None for p in src}, {p: 0 for p in src}, deque(src)
    while q:
        c = q.popleft()
        for dx, dy in N8:
            n = (c[0] + dx, c[1] + dy)
            if walk(n) and n not in dist:
                dist[n], par[n] = dist[c] + 1, c
                q.append(n)

    def route(targets):
        t = min((x for x in targets if x in dist), key=lambda x: dist[x], default=None)
        out = []
        while t is not None:
            out.append(t)
            t = par[t]
        return out
    seen, groups = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nb in camps and nb not in seen:
                    seen.add(nb)
                    st.append(nb)
        groups.append((sum(mapfeat.GEMS[camps[p]] + mapfeat.GOLD[camps[p]] / 10 for p in comp), comp))
    rich = [g for _, g in sorted(groups, key=lambda x: -x[0])[:3]]
    rt = set(route(d["spawnB"]))
    for g in rich:
        rt |= set(route({(p[0] + dx, p[1] + dy) for p in g for dx, dy in N8}))
    for a in d["altar"]:
        rt |= set(route({(a[0] + dx, a[1] + dy) for dx, dy in N8}))
    rt -= set(src) | set(d["spawnB"])
    centres = [((W - 1) // 2, (H - 1) // 2)] + list(d["altar"]) + [p for g in rich for p in g]
    hot = {(x + dx, y + dy) for x, y in centres for dx in range(-3, 4) for dy in range(-3, 4) if walk((x + dx, y + dy))}
    nwalk = sum(1 for x in range(W) for y in range(H) if walk((x, y)))
    r = (len(bush) / max(1, nwalk), sum(p in bush for p in rt) / max(1, len(rt)), sum(p in bush for p in hot) / max(1, len(hot)))
    _c[path] = r
    return r


def bush_share(path):
    return round(_calc(path)[0], 4)


def bushroute(path):
    return round(_calc(path)[1], 4)


def bushhot(path):
    return round(_calc(path)[2], 4)


def bushy(path):
    _, r, h = _calc(path)
    return 1 if r >= 0.20 or h >= 0.25 else 0


CLASSES = {"bush_share": bush_share, "bushroute": bushroute, "bushhot": bushhot, "bushy": bushy}
