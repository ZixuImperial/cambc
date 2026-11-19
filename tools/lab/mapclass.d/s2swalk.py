"""s2swalk (b2143 NTG, 12 Nov): the shortest 8-way walk from any team-A spawn tile to any team-B spawn tile (walls, holes, altars and
camp tiles block; the B spawn tile is the walk's last step). Draft-time map feature. None when no walk exists.
  stratmaps --class 's2swalk:<=8' : adjacent-spawn maps (NTG trace; witness fm_f5b6a9_98 reads 3)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def s2swalk(path, _g=None):
    d = map26a.load(path)
    W, H = d["W"], d["H"]
    goal = set(d["spawnB"])
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(d["camps"])
    dist = {s: 0 for s in d["spawnA"]}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if not (dx or dy) or n in dist or not (0 <= n[0] < W and 0 <= n[1] < H) or n in block:
                    continue
                if n in goal:
                    return dist[(x, y)] + 1
                dist[n] = dist[(x, y)] + 1
                q.append(n)
    return None


CLASSES = {"s2swalk": s2swalk}
