"""holex (Path Finding HXT spec, analysts/nonreducing_steps_1111.md section 6; Tool Builder 11 Nov): camp groups whose walk distance from spawn A
falls by >= 15 when hole crossings are allowed. Walk: 8-way moves over tiles that are not wall, hole or altar (camp tiles passable, the enemy
spawn blocked), cost 1 each; a hole crossing adds a move of 2 tiles in one of the 8 directions over exactly one hole tile onto a walkable tile,
also cost 1 (a dash). A group's distance = the least distance to a walkable tile next to it. holex_n = groups whose distance drops by >= 15
(unreachable without crossings counts as a drop when reachable with them); holex = 1 when holex_n >= 3. Map grid only."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_c = {}


def _bfs(d, cross):
    W, H = d["W"], d["H"]
    wall, hole, alt, esp = set(d["wall"]), set(d["hole"]), set(d["altar"]), set(d["spawnB"])

    def ok(p):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in wall and p not in hole and p not in alt and p not in esp
    dist = {p: 0 for p in d["spawnA"]}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if ok(n) and n not in dist:
                dist[n] = dist[(x, y)] + 1
                q.append(n)
            if cross and n in hole:
                n2 = (x + 2 * dx, y + 2 * dy)
                if ok(n2) and n2 not in dist:
                    dist[n2] = dist[(x, y)] + 1
                    q.append(n2)
    return dist


def holex_n(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    if not d["hole"]:
        _c[path] = 0
        return 0
    camps = d["camps"]
    a, b = _bfs(d, False), _bfs(d, True)
    seen, n = set(), 0
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
        adj = {(p[0] + dx, p[1] + dy) for p in comp for dx, dy in N8} | set(comp)
        da = min((a[t] for t in adj if t in a), default=None)
        db = min((b[t] for t in adj if t in b), default=None)
        if db is not None and (da is None or da - db >= 15):
            n += 1
    _c[path] = n
    return n


def holex(path):
    return 1 if holex_n(path) >= 3 else 0


CLASSES = {"holex_n": holex_n, "holex": holex}


# ---- holexb: the bot's HXB draft rule (b1926 / Path Finding, 11 Nov; mapinfo.cc:617-632) ------------------------------------------------
# thin holes = holes with walkable tiles (not wall/hole/altar) on both sides along one of the 4 axes; f_home = 8-way BFS from spawn A
# blocking walls, altars, spawn B and every hole (camps pass); f_home_dash = the same but thin holes pass (cost 1 like any tile) and altars
# with walkable tiles on both sides along an axis pass too; group distance = min over its camp tiles; listed = ACC_WALK groups (a tile next
# to the group reachable from spawn A with camps, walls, holes, altars and spawn B blocked) with f_home - f_home_dash >= 15 (at most 8);
# holexb = 1 when >= 3 listed.
_cb = {}


def _field(d, block):
    W, H = d["W"], d["H"]
    dist = {p: 0 for p in d["spawnA"]}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in dist:
                dist[n] = dist[(x, y)] + 1
                q.append(n)
    return dist


def holexb_n(path):
    if path in _cb:
        return _cb[path]
    d = map26a.load(path)
    W, H = d["W"], d["H"]
    wall, hole, alt, camps, esp = set(d["wall"]), set(d["hole"]), set(d["altar"]), d["camps"], set(d["spawnB"])
    if not hole:
        _cb[path] = 0
        return 0
    wk = lambda p: 0 <= p[0] < W and 0 <= p[1] < H and p not in wall and p not in hole and p not in alt  # noqa: E731
    axes = ((1, 0), (0, 1), (1, 1), (1, -1))
    both = lambda p: any(wk((p[0] + a, p[1] + b)) and wk((p[0] - a, p[1] - b)) for a, b in axes)  # noqa: E731
    thin = {p for p in hole if both(p)}
    alt_pass = {p for p in alt if both(p)}
    fh = _field(d, wall | alt | esp | hole)
    fd = _field(d, wall | (alt - alt_pass) | esp | (hole - thin))
    fw = _field(d, wall | alt | esp | hole | set(camps))  # camps blocked: ACC_WALK
    seen, n = set(), 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q2 in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q2 in camps and q2 not in seen:
                    seen.add(q2)
                    st.append(q2)
        if not any((p[0] + dx, p[1] + dy) in fw for p in comp for dx, dy in N8):
            continue
        a = min((fh[p] for p in comp if p in fh), default=None)
        b = min((fd[p] for p in comp if p in fd), default=None)
        if a is not None and b is not None and a - b >= 15:
            n += 1
    _cb[path] = min(n, 8)
    return _cb[path]


def holexb(path):
    return 1 if holexb_n(path) >= 3 else 0


CLASSES.update({"holexb_n": holexb_n, "holexb": holexb})


# ---- offwalk (b1971 DPX, Deep /data/USER/st/deepan/offwalk/result.md; 11 Nov) ------------------------------------------------------------
# gem groups (gems > 0) on spawn A's side (group centroid nearer spawn A's centre, Chebyshev) with NO walk path (no tile of the centroid's 3x3
# reachable by 8-way walking from spawn A; walls, holes, altars, spawn B block) that a 2-step dash over ONE hole tile reaches (holex's
# crossing). offwalk = that count (mirrored maps: the same for the other seat)  -> --class 'offwalk:>=1'
_cw = {}


def offwalk(path):
    if path in _cw:
        return _cw[path]
    d = map26a.load(path)
    if not d["hole"]:
        _cw[path] = 0
        return 0
    import mapfeat
    a, b = _bfs(d, False), _bfs(d, True)
    ca = [sum(c) / len(c) for c in zip(*d["spawnA"])]
    cb = [sum(c) / len(c) for c in zip(*d["spawnB"])]
    camps = d["camps"]
    seen, n = set(), 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q2 in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q2 in camps and q2 not in seen:
                    seen.add(q2)
                    st.append(q2)
        if sum(mapfeat.GEMS[camps[p]] for p in comp) <= 0:
            continue
        gx, gy = sum(p[0] for p in comp) / len(comp), sum(p[1] for p in comp) / len(comp)
        if max(abs(gx - ca[0]), abs(gy - ca[1])) >= max(abs(gx - cb[0]), abs(gy - cb[1])):
            continue
        box = {(int(round(gx)) + dx, int(round(gy)) + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        adj = {(p[0] + dx, p[1] + dy) for p in comp for dx, dy in N8} | set(comp)
        if any(t in a for t in box):
            continue
        if any(t in b for t in adj):
            n += 1
    _cw[path] = n
    return n


CLASSES.update({"offwalk": offwalk})
