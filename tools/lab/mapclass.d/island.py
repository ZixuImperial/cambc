"""island (b2391 for the LCE island line, Deep /data/USER/st/deepan/island/result.md Q5; draft-time map features only, no map identity).
WIDE island key: a gem group with no walk path from our spawn that ONE 2-step dash reaches.
  R0 = tiles reached on foot from our spawn (8-way; blocked: walls, holes, altars, the ENEMY spawn; camp tiles passable, as the bot's M.f_home).
  R1 = R0 plus the walk closure of every standable tile t not in R0 at Chebyshev 2 from some s in R0, with a tile next to both that is not
       a wall (holes, camps and open tiles pass as the dash's middle).
  A camp group (4-connected camp tiles, gems > 0) is an island when no member or member neighbour is in R0 and one is in R1.
Classes per seat: isl_a / isl_b (1 or 0), isl_any (either seat), isl_n_a / isl_n_b (island gem groups for that seat).
Matches Deep's scratch isl.py layer-1 count (BIG2 138 of 2,000, fresh 48 of 599, seat A)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
D16 = [(a, b) for a in range(-2, 3) for b in range(-2, 3) if max(abs(a), abs(b)) == 2]
_c = {}


def _seat(path, seat):
    key = (path, seat)
    if key in _c:
        return _c[key]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    camps = m["camps"]
    ours = m["spawnA"] if seat == "a" else m["spawnB"]
    theirs = set(m["spawnB"] if seat == "a" else m["spawnA"])
    wall = set(m["wall"])
    block = wall | set(m["hole"]) | set(m["altar"]) | theirs

    def ok(p):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in block

    def midok(p):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in wall

    def closure(seeds, reach):
        q = deque()
        for p in seeds:
            if p not in reach:
                reach.add(p)
                q.append(p)
        while q:
            x, y = q.popleft()
            for dx, dy in N8:
                n = (x + dx, y + dy)
                if ok(n) and n not in reach:
                    reach.add(n)
                    q.append(n)

    r0 = set()
    closure([p for p in ours if ok(p)], r0)
    r1 = set(r0)
    seeds = []
    if m["hole"]:  # no hole: one dash adds nothing a wall-free walk misses only through walls (a wall middle never passes)
        for (x, y) in r0:
            for dx, dy in D16:
                n = (x + dx, y + dy)
                if not ok(n) or n in r0:
                    continue
                if any(midok((x + a, y + b)) and max(abs(dx - a), abs(dy - b)) <= 1 for a, b in N8):
                    seeds.append(n)
        closure(seeds, r1)
    seen, n_isl = set(), 0
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
        if sum(GEMS.get(camps[p], 0) for p in comp) <= 0:
            continue
        near = set(comp) | {(t[0] + a, t[1] + b) for t in comp for a, b in N8}
        if near & r0:
            continue
        if near & r1:
            n_isl += 1
    _c[key] = n_isl
    return n_isl


def isl_n_a(path):
    return _seat(path, "a")


def isl_n_b(path):
    return _seat(path, "b")


def isl_a(path):
    return 1 if _seat(path, "a") > 0 else 0


def isl_b(path):
    return 1 if _seat(path, "b") > 0 else 0


def isl_any(path):
    return 1 if _seat(path, "a") > 0 or _seat(path, "b") > 0 else 0


CLASSES = {"isl_a": isl_a, "isl_b": isl_b, "isl_any": isl_any, "isl_n_a": isl_n_a, "isl_n_b": isl_n_b}
