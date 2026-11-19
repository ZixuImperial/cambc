"""pgc (b2346 PGC, spec_pgc_1112 + RC C850; for TB's pgc1 rare bank): the bot's PGC class test recomputed from the static map.
Draft-time map features only, no map identity. Per seat (our spawn = that seat's), as draft_values.cc pgc_share1000 / pgc_one_altar_group:
  groups = cardinally connected camp tiles (members in map26a camp order, as the engine's camp_group.camps());
  block = walls | holes | altars | the ENEMY spawn (M.block); block_camps = block | camp tiles;
  approach(g) = the 8 neighbours of g's FIRST TWO members that are in bounds, not in block and not camp tiles (mapinfo.cc step_groups / step_approach);
  altar_adj = the 8 neighbours of each altar not in block_camps; f_altar = 8-way BFS from altar_adj over block_camps;
  d_altar(g) = min f_altar over approach(g) + 1 (unreachable: never counts) (MapInfo group_dist_blocked, the draft's path);
  share = gems of groups with no attacker (every member a gem / gold cluster: strength 0) and gems > 0 and d_altar <= R, over all gems (x1000, floor);
  one altar group = every altar within Chebyshev 8 of every other.
Classes: pgc_a / pgc_b (1 when share12 >= 400 AND one altar group, for that seat), pgc_min (both seats), pgc_any (either);
pgc_sh12_a / pgc_sh12_b (the share x1000 itself). e.g. 'pgc_any:>=1'. Not the bot's full PGC fire (that also needs walk_alt and
!pz_viable, draft internals): the map half of it, the same as the diag's tag-240 values."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

STR = {0: 20, 1: 60, 2: 0, 3: 0, 4: 200, 5: 120}  # wolf, elk, gem cluster, gold cluster, monolith, golem (GameRules)
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
R, SH1000 = 12, 400
_c = {}


def _groups(m):
    camps = m["camps"]
    order = {p: i for i, p in enumerate(camps)}
    seen, out = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        comp.sort(key=lambda p: order[p])
        out.append(comp)
    return out


def _bfs(W, H, block, roots):
    d, q = {}, deque()
    for p in roots:
        if p not in block and p not in d:
            d[p] = 0
            q.append(p)
    while q:
        x, y = q.popleft()
        v = d[(x, y)] + 1
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in d:
                d[n] = v
                q.append(n)
    return d


def _seat(path, seat):
    key = (path, seat)
    if key in _c:
        return _c[key]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    camps = m["camps"]
    theirs = set(m["spawnB"] if seat == "a" else m["spawnA"])
    altars = list(m["altar"])
    block = set(m["wall"]) | set(m["hole"]) | set(altars) | theirs
    camp_tiles = set(camps)
    block_camps = block | camp_tiles
    G = _groups(m)
    tot = near = 0
    if altars:
        roots = {(ax + dx, ay + dy) for ax, ay in altars for dx, dy in N8
                 if 0 <= ax + dx < W and 0 <= ay + dy < H and (ax + dx, ay + dy) not in block_camps}
        fa = _bfs(W, H, block_camps, roots)
    else:
        fa = {}
    for comp in G:
        types = [camps[p] for p in comp]
        gems = sum(GEMS[t] for t in types)
        tot += gems
        if gems <= 0 or any(STR[t] > 0 for t in types) or not altars:
            continue
        best = None
        for (x, y) in comp[:2]:
            for dx, dy in N8:
                q = (x + dx, y + dy)
                if 0 <= q[0] < W and 0 <= q[1] < H and q not in block and q not in camp_tiles and q in fa:
                    if best is None or fa[q] < best:
                        best = fa[q]
        if best is not None and best + 1 <= R:
            near += gems
    sh = (1000 * near // tot) if tot > 0 else 0
    one = bool(altars) and all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 8 for a in altars for b in altars)
    _c[key] = (sh, one)
    return _c[key]


def pgc_sh12_a(path):
    return _seat(path, "a")[0]


def pgc_sh12_b(path):
    return _seat(path, "b")[0]


def _cls(path, seat):
    sh, one = _seat(path, seat)
    return 1 if (sh >= SH1000 and one) else 0


def pgc_a(path):
    return _cls(path, "a")


def pgc_b(path):
    return _cls(path, "b")


def pgc_min(path):
    return min(_cls(path, "a"), _cls(path, "b"))


def pgc_any(path):
    return max(_cls(path, "a"), _cls(path, "b"))


CLASSES = {"pgc_a": pgc_a, "pgc_b": pgc_b, "pgc_min": pgc_min, "pgc_any": pgc_any, "pgc_sh12_a": pgc_sh12_a, "pgc_sh12_b": pgc_sh12_b}
