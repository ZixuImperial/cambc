"""alt4p (b2273 BSG bit 16, RC C833; Path Finding chokepoints_1112.md 0A): ALT4POCKET, the bot's MCL4 bit 4 (plan_map_classes.cc
bsg_alt4_pocket) recomputed from the static map. Draft-time map features only, no map identity. Per seat (our spawn = that seat's).
  block = walls | holes | altars | the ENEMY spawn (the bot's M.block); f_home = 8-way BFS from our spawn tiles (camps passable);
  roots = tiles within Chebyshev 1 of an altar that are not blocked (altar_adj_all); f_alt = 8-way BFS from the roots over the same block.
  D = min f_home over the roots; width(k) = tiles with f_home == k and f_home + f_alt <= D + 12, k in [3, D - 2];
  POCKET when the narrowest layer (ties: the larger k) is 1..4 wide, 2k >= D, and the tiles with f_alt <= D - k are <= 25% of the tiles
  both fields reach. Classes: alt4p_a / alt4p_b (1 or 0 for that seat), alt4p_min (both seats), alt4p_any (either). e.g. 'alt4p_min:>=1'."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_c = {}


def _bfs(W, H, block, roots):
    d = {}
    q = deque()
    for p in roots:
        if p not in block and p not in d:
            d[p] = 0
            q.append(p)
    while q:
        x, y = q.popleft()
        v = d[(x, y)] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                    d[n] = v
                    q.append(n)
    return d


def _seat(path, seat):
    key = (path, seat)
    if key in _c:
        return _c[key]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    ours = set(m["spawnA"] if seat == "a" else m["spawnB"])
    theirs = set(m["spawnB"] if seat == "a" else m["spawnA"])
    altars = set(m["altar"])
    block = set(m["wall"]) | set(m["hole"]) | altars | theirs
    roots = {(ax + dx, ay + dy) for ax, ay in altars for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             if 0 <= ax + dx < W and 0 <= ay + dy < H and (ax + dx, ay + dy) not in block}
    r = 0
    if altars and roots:
        fh = _bfs(W, H, block, ours)
        fa = _bfs(W, H, block, roots)
        both = [p for p in fh if p in fa]
        D = min((fh[p] for p in roots if p in fh), default=None)
        if D is not None and D >= 6 and both:
            width = [0] * (D + 1)
            hist = [0] * (D + 1)
            for p in both:
                h, a = fh[p], fa[p]
                if h <= D and h + a <= D + 12:
                    width[h] += 1
                if a <= D:
                    hist[a] += 1
            wmin, kmin = None, -1
            for k in range(3, D - 1):
                if wmin is None or width[k] <= wmin:
                    wmin, kmin = width[k], k
            if kmin >= 0 and 1 <= wmin <= 4 and 2 * kmin >= D and 4 * sum(hist[: D - kmin + 1]) <= len(both):
                r = 1
    _c[key] = r
    return r


def alt4p_a(path):
    return _seat(path, "a")


def alt4p_b(path):
    return _seat(path, "b")


def alt4p_min(path):
    return min(_seat(path, "a"), _seat(path, "b"))


def alt4p_any(path):
    return max(_seat(path, "a"), _seat(path, "b"))


CLASSES = {"alt4p_a": alt4p_a, "alt4p_b": alt4p_b, "alt4p_min": alt4p_min, "alt4p_any": alt4p_any}
