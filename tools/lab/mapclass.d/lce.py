"""lce (b2313 LCE, spec_lce_1112): off-walk gem islands. Draft-time map features only.
lcee_a / lcee_b / lcee_any (RC C902: the bank class): some gem group with no member next to our walk HAS an LCE entry (any board size):
  a member neighbour P that is standable (not wall/hole/altar/enemy spawn/camp tile) and off the walk, and an L at Chebyshev 2 from P that
  is standable and on the walk, with a middle tile m next to both that is not a wall, a camp tile or the enemy spawn (the bot's lce_find).
Per seat: the board is larger than 72x72 (W > 72 and H > 72) and some camp group with gems has no member next to a tile our spawn reaches on
foot (8-way BFS from our spawn tiles, blocked: walls, holes, altars, the ENEMY spawn; camps passable, as the bot's M.f_home).
Classes: lce_a / lce_b (1 or 0 for that seat), lce_any (either seat), lce_n_a / lce_n_b (island gem groups for that seat)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
_c = {}


def _seat(path, seat):
    key = (path, seat)
    if key in _c:
        return _c[key]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    big = W > 72 and H > 72
    camps = m["camps"]
    ours = set(m["spawnA"] if seat == "a" else m["spawnB"])
    theirs = set(m["spawnB"] if seat == "a" else m["spawnA"])
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"]) | theirs
    d = set()
    q = deque()
    for p in ours:
        if p not in block:
            d.add(p)
            q.append(p)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                d.add(n)
                q.append(n)
    seen, n_isl, n_ent = set(), 0, 0
    campset = set(camps)
    walls, esp = set(m["wall"]), theirs

    def stand(p):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in campset
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
        if sum(GEMS[camps[p]] for p in comp) <= 0:
            continue
        if not any(p in d for p in comp) and not any((p[0] + dx, p[1] + dy) in d for p in comp for dx, dy in N8):
            n_isl += 1
            ent = False
            for (cx, cy) in comp:
                for dx, dy in N8:
                    P = (cx + dx, cy + dy)
                    if ent or not stand(P) or P in d:
                        continue
                    for lx in range(-2, 3):
                        for ly in range(-2, 3):
                            if ent or max(abs(lx), abs(ly)) != 2:
                                continue
                            L = (P[0] + lx, P[1] + ly)
                            if not stand(L) or L not in d:
                                continue
                            for mx in (-1, 0, 1):
                                for my in (-1, 0, 1):
                                    mm = (L[0] + mx, L[1] + my)
                                    if (mx or my) and mm != P and max(abs(mm[0] - P[0]), abs(mm[1] - P[1])) <= 1 and 0 <= mm[0] < W and 0 <= mm[1] < H \
                                            and mm not in walls and mm not in campset and mm not in esp:
                                        ent = True
            n_ent += ent
    _c[key] = (n_isl if big else 0, n_ent)
    return _c[key]


def lce_n_a(path):
    return _seat(path, "a")[0]


def lce_n_b(path):
    return _seat(path, "b")[0]


def lce_a(path):
    return 1 if _seat(path, "a")[0] > 0 else 0


def lce_b(path):
    return 1 if _seat(path, "b")[0] > 0 else 0


def lcee_a(path):
    return 1 if _seat(path, "a")[1] > 0 else 0


def lcee_b(path):
    return 1 if _seat(path, "b")[1] > 0 else 0


def lcee_any(path):
    return max(lcee_a(path), lcee_b(path))


def lce_any(path):
    return max(lce_a(path), lce_b(path))


CLASSES = {"lce_a": lce_a, "lce_b": lce_b, "lce_any": lce_any, "lce_n_a": lce_n_a, "lce_n_b": lce_n_b, "lcee_a": lcee_a, "lcee_b": lcee_b, "lcee_any": lcee_any}
