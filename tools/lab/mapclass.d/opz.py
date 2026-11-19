"""opz (b2373 OPZ, spec_erx_1113): a fast attacker-free mid group, the bot's opz_seed. Draft-time map features only.
Per seat: some camp group (cardinally connected camps) with no attacker camp (only gem / gold clusters), >= 15 gems, reachable on foot
from both spawns (8-way BFS, blocked: walls, holes, altars and the other side's spawn; camps passable, as M.f_home / f_enemy), with
|d_home - d_enemy| <= 15% of the larger (group distance = the nearest member). Classes: opz_a / opz_b (1/0), opz_any (either seat)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
ATTACKER = {0, 1, 4, 5}  # wolf, elk, monolith, golem (GameRules monster table); 2 gem cluster, 3 gold cluster
N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
_c = {}


def _bfs(W, H, roots, block):
    d = {}
    q = deque()
    for p in roots:
        if p not in block:
            d[p] = 0
            q.append(p)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                d[n] = d[(x, y)] + 1
                q.append(n)
    return d


def _seat(path, seat):
    key = (path, seat)
    if key in _c:
        return _c[key]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    camps = m["camps"]
    ours = set(m["spawnA"] if seat == "a" else m["spawnB"])
    theirs = set(m["spawnB"] if seat == "a" else m["spawnA"])
    base = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dh = _bfs(W, H, ours, base | theirs)
    de = _bfs(W, H, theirs, base | ours)
    seen, hit = set(), 0
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
        if any(camps[p] in ATTACKER for p in comp) or sum(GEMS[camps[p]] for p in comp) < 15:
            continue
        a = min((dh[p] for p in comp if p in dh), default=None)
        b = min((de[p] for p in comp if p in de), default=None)
        if a is None or b is None:
            continue
        if 100 * abs(a - b) <= 15 * max(a, b):
            hit = 1
    _c[key] = hit
    return hit


def opz_a(path):
    return _seat(path, "a")


def opz_b(path):
    return _seat(path, "b")


def opz_any(path):
    return max(opz_a(path), opz_b(path))


CLASSES = {"opz_a": opz_a, "opz_b": opz_b, "opz_any": opz_any}
