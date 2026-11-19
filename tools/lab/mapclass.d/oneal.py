"""oneal: OAT one-altar class (Builder b2388, RC C1172, 13 Nov). Draft-time, map features only.
  A seat 'has one altar' when exactly ONE altar tile passes the bot's home_altar_dist filter (econ_value.cc:70-79):
    d_home != UNREACH  : an 8-way walk from the seat's spawn tiles reaches a tile next to it, blocked by walls, holes, altar tiles and the
                         foe's spawn (mapinfo.cc:44 'block'), camps passable (killable);
    !gated             : the same walk with camps ALSO blocking (mapinfo.cc:537 block_camps) reaches it too (mapinfo.cc:452);
    access == ACC_WALK : implied by d_home != UNREACH.
  oneal     : number of seats (0-2) with exactly one such altar tile.   -> stratmaps --class 'oneal:>=1'
  oneal_n_a / oneal_n_b : each seat's count of such altar tiles."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}
D8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def _bfs(W, H, block, src):
    seen = {s for s in src if s not in block}
    q = deque(seen)
    while q:
        x, y = q.popleft()
        for dx, dy in D8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in seen:
                seen.add(n)
                q.append(n)
    return seen


def feats(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    W, H = d["W"], d["H"]
    base = set(d["wall"]) | set(d["hole"]) | set(d["altar"])
    camps = set(d["camps"])
    out = {}
    for side, own, foe in (("a", d["spawnA"], d["spawnB"]), ("b", d["spawnB"], d["spawnA"])):
        blk = base | set(foe)
        r_open = _bfs(W, H, blk, own)            # f_home: camps passable
        r_cb = _bfs(W, H, blk | camps, own)       # f_home_cb: camps block
        n = 0
        for x, y in d["altar"]:
            nb = [(x + dx, y + dy) for dx, dy in D8]
            if any(p in r_open for p in nb) and any(p in r_cb for p in nb):
                n += 1
        out[side] = n
    out["oneal"] = (out["a"] == 1) + (out["b"] == 1)
    _cache[path] = out
    return out


CLASSES = {"oneal": lambda p, _m=None: feats(p)["oneal"], "oneal_n_a": lambda p, _m=None: feats(p)["a"],
           "oneal_n_b": lambda p, _m=None: feats(p)["b"]}
