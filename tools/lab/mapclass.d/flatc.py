"""flatc (b2370 TSC, Path Finding spec_tsc_1113.md; draft-time map features only, no map identity).
  flatc_share = share of camp groups (4-connected) whose contest d_A / (d_A + d_B) lies in [.40, .60]; d = 8-way walk from each spawn
                (walls, holes, altars block; camps passable), to the group's nearest member tile; groups reached from neither spawn skipped.
  flatc       = 1 when flatc_share >= .80 (the bot's tsc_flat(), econ_rate_crew.cc; the bot's contest uses its own fields, close to this)."""
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


def flatc_share(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = _bfs(W, H, block, m["spawnA"]), _bfs(W, H, block, m["spawnB"])
    seen = set(); n = flat = 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop(); comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q); st.append(q)
        a = min((dA[t] for t in comp if t in dA), default=None)
        b = min((dB[t] for t in comp if t in dB), default=None)
        if a is None or b is None or a + b == 0:
            continue
        n += 1
        flat += 1 if .40 <= a / (a + b) <= .60 else 0
    r = flat / n if n else 0.0
    _c[path] = r
    return r


def flatc(path):
    return 1 if flatc_share(path) >= .80 else 0


CLASSES = {"flatc": flatc, "flatc_share": flatc_share}
