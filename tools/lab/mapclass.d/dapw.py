"""dapw (b2311 DAP, 12 Nov): the bot's passage class off-bot (econ_passage_hold.cc dap_class_step/finish, Path Finding's layer-width
form, slack 12). Per seat: f_home from our spawn (walls, holes, altars, their spawn block; camps passable), f_enemy from theirs (walls,
holes, altars, our spawn block); D = 1 + min f_home over the tiles 8-adjacent to their spawn; hist[k] = tiles with f_enemy = k in
[4, D-4] and f_home + f_enemy <= D + 12; k* = the narrowest VALID layer (f_enemy layers with D - k <= k + 10, and f_home layers with k <= D - k + 10;
Path Finding's validation 12 Nov: argmin-then-reject dropped 18 true cuts on BIG2).
Value: the smaller valid width over the two seats (the bot plays both), 99 when neither seat has one. Draft-time map feature.
  stratmaps / prearm --class 'dapw:<=4' : DAP class maps (DAP_W 4)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

SLACK = 12


def _bfs(W, H, roots, block):
    dist = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        x, y = q.popleft()
        dv = dist[(x, y)] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in dist:
                    dist[n] = dv
                    q.append(n)
    return dist


def _seat(W, H, mine, theirs, base):
    fh = _bfs(W, H, list(mine), base | set(theirs))
    fe = _bfs(W, H, list(theirs), base | set(mine))
    th = set(theirs)
    best = None
    for (x, y) in th:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if n not in th and n in fh:
                    best = fh[n] if best is None else min(best, fh[n])
    if best is None:
        return None
    D = best + 1
    if D < 12:
        return None
    lim = D + SLACK
    # Path Finding's key validation (12 Nov): the narrowest VALID layer, not the narrowest layer then rejected. f_enemy layers
    # (a gate on our side: D - k <= k + 10) and f_home layers (a gate on their side, which their seat holds: k <= D - k + 10).
    he, hh = {}, {}
    for t, e in fe.items():
        h = fh.get(t)
        if h is None or h + e > lim:
            continue
        if 4 <= e <= D - 4 and D - e <= e + 10:
            he[e] = he.get(e, 0) + 1
        if 4 <= h <= D - 4 and h <= D - h + 10:
            hh[h] = hh.get(h, 0) + 1
    ws = [min(x.values()) for x in (he, hh) if x]
    return min(ws) if ws else None


def dapw(path, _g=None):
    d = map26a.load(path)
    W, H = d["W"], d["H"]
    base = set(d["wall"]) | set(d["hole"]) | set(d["altar"])
    vals = [v for v in (_seat(W, H, d["spawnA"], d["spawnB"], base), _seat(W, H, d["spawnB"], d["spawnA"], base)) if v is not None]
    return min(vals) if vals else 99


CLASSES = {"dapw": dapw}
