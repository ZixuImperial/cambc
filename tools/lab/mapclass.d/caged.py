"""caged (13 Nov, TB for b2388 CGB; rule from Path Finding's trace, condor-work/reports/analysts/cage_official_maps_1113.md): a spawn sealed
by a ring of camps. For either seat: R1 = 8-way walk from the spawn tiles with walls, holes, altars, the other spawn AND camp tiles blocked;
R2 = the same walk with camps removed. Caged when (a) R1 touches a camp group holding a KILLABLE attacking camp (wolf, elk or golem: not
monolith-only), (b) |R2| >= CAGE_RATIO (3) x |R1|, and (c) R2 reaches an altar or a camp group R1 does not touch. caged = number of caged
spawns (0-2); class 'caged:>=1'. Draft-time, seat-free. (13 Nov first form, 'touches <= 1 group', fired on island / hole maps: boss_rush,
dash_test, gen_ux_lost_world, fm_b70801_3; dropped.)"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
WOLF, ELK, GOLEM = 0, 1, 5
RATIO = float(os.environ.get("CAGE_RATIO", 3))


def _walk(W, H, start, blk, camps, through_camps):
    seen = set(start)
    q, touched, altars = deque(seen), set(), False
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if not (0 <= p[0] < W and 0 <= p[1] < H) or p in seen:
                continue
            if p in blk:
                if blk[p] == "altar":
                    altars = True
                continue
            if p in camps:
                touched.add(p)
                if not through_camps:
                    continue
            seen.add(p)
            q.append(p)
    return seen, touched, altars


def caged(path, _g=None):
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    comp, k = {}, 0
    for c in camps:  # cardinal camp groups (one camp per tile)
        if c in comp:
            continue
        st = [c]
        comp[c] = k
        while st:
            x, y = st.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in comp:
                    comp[q] = k
                    st.append(q)
        k += 1
    killable = {comp[c] for c, t in camps.items() if t in (WOLF, ELK, GOLEM)}
    base = {p: "wall" for p in d["wall"]}
    base.update({p: "hole" for p in d["hole"]})
    base.update({p: "altar" for p in d["altar"]})
    n = 0
    for me, foe in (("spawnA", "spawnB"), ("spawnB", "spawnA")):
        start = list(d.get(me) or [])
        if not start:
            continue
        blk = dict(base)
        blk.update({p: "spawn" for p in (d.get(foe) or [])})
        r1, t1, _ = _walk(W, H, start, blk, camps, False)
        g1 = {comp[c] for c in t1}
        if not (g1 & killable):
            continue
        r2, t2, alt2 = _walk(W, H, start, blk, camps, True)
        g2 = {comp[c] for c in t2}
        if len(r2) >= RATIO * len(r1) and (alt2 or (g2 - g1)):
            n += 1
    return n


CLASSES = {"caged": caged}
