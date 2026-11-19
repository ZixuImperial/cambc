"""ring (12 Nov, Tool Builder; b2225 RPZ1 Step 0): the bot's M.ring (mapinfo.cc gate_step ~660-702): ring_camps = camps with an 8-neighbour
the ALTAR field reaches (walls, holes, camps block) AND an 8-neighbour our SPAWN field reaches (camps block); ring = any such camp, counted
only for altars our spawn cannot walk to with camps blocked (an enclosure: the altar sits inside a ring of camps). Per seat, from that
seat's spawn. Static map fields only.
  ring_a / ring_b   1 / 0 from seat A's / B's spawn;  ring_n  ring camps (seat A);  ring  = 1 when both seats see a ring"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_c = {}


def _bfs(W, H, src, block):
    seen = {p for p in src if p not in block}
    q = deque(seen)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in seen:
                seen.add(n)
                q.append(n)
    return seen


def _seat(d, key):
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(camps)
    sp = _bfs(W, H, list(d.get(key) or ()), block)
    n = 0
    for a in d["altar"]:
        nb = [(a[0] + dx, a[1] + dy) for dx, dy in N8]
        if any(p in sp for p in nb):
            continue  # walkable from our spawn with camps blocked: not enclosed
        af = _bfs(W, H, [p for p in nb if 0 <= p[0] < W and 0 <= p[1] < H] + [a], block)
        for c in camps:
            ns = [(c[0] + dx, c[1] + dy) for dx, dy in N8]
            if any(p in af for p in ns) and any(p in sp for p in ns):
                n += 1
    return n


def _f(path):
    if path not in _c:
        d = map26a.load(path)
        a, b = _seat(d, "spawnA"), _seat(d, "spawnB")
        _c[path] = dict(ring_a=float(a > 0), ring_b=float(b > 0), ring_n=float(a), ring=float(a > 0 and b > 0))
    return _c[path]


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("ring", "ring_a", "ring_b", "ring_n")}
