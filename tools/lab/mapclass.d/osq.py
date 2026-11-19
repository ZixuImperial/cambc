"""osq (12 Nov, Tool Builder; b2264 OSQ class-gated behaviour read; RC C726/C735): the bot's osq_class() (bots/nova_b2264_osq/src/
plan_map_classes.cc) on the map file, per seat and both.
  Groups: 4-connected camp tiles (the bot's M.groups). Group HP: sum of its camps' rule HP (GameRules.md:183-188).
  d_home / d_enemy: the minimum over the group's camp tiles of an 8-way BFS step count from that seat's spawn tiles, camps PASSABLE
    (mapinfo.h f_home 'camps passable'), blocked by walls, holes, altars and the OTHER seat's spawn (mapinfo.cc f_home / f_enemy).
  ours = d_home reachable and (d_enemy unreachable or d_home < d_enemy); theirs = the mirror; ties and groups neither spawn reaches
  are in neither half (C735: groups only one spawn reaches DO count, unlike Deep's cls.py).
  osq = 1 when every group in either half has HP >= 2,500 and each half holds at least one (seat-symmetric).  --class 'osq:>=1'
  osq_own_heavy_a / _b: own-half groups (that seat) with HP >= 2,500. Static map fields only, no map identity."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

HP = {0: 1350, 1: 2400, 2: 120, 3: 120, 4: 20000, 5: 5000}  # wolf, elk, gem cluster, gold cluster, monolith, golem
HEAVY = 2500
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_c = {}


def _field(W, H, src, block):
    d = {p: 0 for p in src if p not in block and 0 <= p[0] < W and 0 <= p[1] < H}
    q = deque(d)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                d[n] = d[(x, y)] + 1
                q.append(n)
    return d


def _f(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    sa, sb = set(m.get("spawnA") or ()), set(m.get("spawnB") or ())
    base = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    fa, fb = _field(W, H, sa, base | sb), _field(W, H, sb, base | sa)
    seen, groups = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            p = st.pop()
            comp.append(p)
            for n in ((p[0] + 1, p[1]), (p[0] - 1, p[1]), (p[0], p[1] + 1), (p[0], p[1] - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        da = min((fa[p] for p in comp if p in fa), default=None)
        db = min((fb[p] for p in comp if p in fb), default=None)
        groups.append((da, db, sum(HP.get(camps[p], 0) for p in comp)))
    na = nb = 0
    ok = True
    for da, db, hp in groups:
        a = da is not None and (db is None or da < db)
        b = db is not None and (da is None or db < da)
        if not a and not b:
            continue
        if hp < HEAVY:
            ok = False
        if a:
            na += 1
        else:
            nb += 1
    r = dict(osq=float(ok and na > 0 and nb > 0),
             osq_own_heavy_a=float(sum(1 for da, db, hp in groups if da is not None and (db is None or da < db) and hp >= HEAVY)),
             osq_own_heavy_b=float(sum(1 for da, db, hp in groups if db is not None and (da is None or db < da) and hp >= HEAVY)))
    _c[path] = r
    return r


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("osq", "osq_own_heavy_a", "osq_own_heavy_b")}
