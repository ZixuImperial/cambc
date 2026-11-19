"""altwalk: FWK far-altar class (b2162 12 Nov, spec_fwk_1112.md: 'home-altar walk > 25 rounds', draft-time). Draft-time map features only.
  altwalk      : mean over the two seats of the 8-way walk from the spawn tiles to the nearest tile next to an altar (walls, holes,
                 altars and camps block); 999 when a seat reaches no altar on foot.   -> stratmaps --class 'altwalk:>25'
  altwalk_farm : mean over seats of the gem-weighted walk from each own-side camp group (d_own <= d_enemy) to the nearest altar-adjacent
                 tile (the farm-to-altar trip a finish-mode bank walks).
  altwalk_a / altwalk_b : each seat's spawn value."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # camp type -> gems (as recallcost)
_cache = {}


def _bfs(W, H, block, src):
    dist = {s: 0 for s in src if s not in block}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in dist:
                    dist[n] = dist[(x, y)] + 1
                    q.append(n)
    return dist


def _near(pts):
    return [(x + dx, y + dy) for x, y in pts for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def _gd(dist, pts):
    return min((dist[p] for p in _near(pts) if p in dist), default=None)


def feats(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    camps = d["camps"]
    W, H = d["W"], d["H"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    altn = [p for p in _near(d["altar"]) if p not in block and 0 <= p[0] < W and 0 <= p[1] < H]
    out = {}
    dA, dB = _bfs(W, H, block, d["spawnA"]), _bfs(W, H, block, d["spawnB"])
    for side, ds in (("a", dA), ("b", dB)):
        v = min((ds[p] for p in altn if p in ds), default=None)
        out[side] = 999 if v is None else v
    out["aw"] = (out["a"] + out["b"]) / 2.0
    # farm-to-altar: groups (4-connected camps), own side per seat, walk from the group's neighbours to the altar field
    dalt = _bfs(W, H, block, altn)
    seen, groups = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [c], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    comp.append(n)
                    st.append(n)
        groups.append((sum(GEM[camps[p]] for p in comp), comp))
    fr = []
    for side, i, j in (("a", dA, dB), ("b", dB, dA)):
        num = den = 0
        for gems, pts in groups:
            a, b, t = _gd(i, pts), _gd(j, pts), _gd(dalt, pts)
            if a is None or t is None or gems <= 0 or (b is not None and b < a):
                continue
            num += gems * t
            den += gems
        fr.append(num / den if den else 999)
    out["farm"] = round(sum(fr) / 2.0, 2)
    _cache[path] = out
    return out


CLASSES = {"altwalk": lambda p, _m=None: feats(p)["aw"], "altwalk_farm": lambda p, _m=None: feats(p)["farm"],
           "altwalk_a": lambda p, _m=None: feats(p)["a"], "altwalk_b": lambda p, _m=None: feats(p)["b"]}
