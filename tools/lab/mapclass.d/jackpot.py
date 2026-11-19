"""jackpot: Deep's JACKPOT + GOLD HALVES class (11 Nov, owner's 00rows gate cell; reference /data/zw4424/st/deepan/centregem/py/mapan.py,
report condor-work/reports/analysts/owner_goldgem_mapclass_1112.md). Draft-time map features only. Tool Builder 11 Nov.
  groups = 4-connected camp components; zone by walk distance from the two spawns (8-way; walls, holes, altars, camps block):
  r = dA / (dA + dB) < .4 -> A, > .6 -> B, else mid. Respawn period = the slowest camp kind of the group + 5 capture rounds.
  jackpot = 1 when (1) the largest group by gems is in the mid zone and no other group has >= 90% of its gems; (2) it holds >= 300
  gems and >= half of all groups' gems (one cycle); (3) team A's half gem cap < 150 per 100 rounds (sum gems x 100 / period over its
  zone-A groups; the map is mirrored, so B's half is the same); (4) that half's gold cap >= 400 per 100 rounds. Else 0.
  jackpot_big (the big group's gems), jackpot_halfcap and jackpot_goldcap give the parts.  -> stratmaps --class 'jackpot:>=1'"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
RSP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
CAP = 5
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
_cache = {}


def _bfs(W, H, src, block):
    dist = {p: 0 for p in src if p not in block}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    return dist


def _feats(path):
    if path in _cache:
        return _cache[path]
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    da, db = _bfs(W, H, list(d["spawnA"]), block), _bfs(W, H, list(d["spawnB"]), block)
    seen, gs = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        adj = {(x + dx, y + dy) for (x, y) in comp for dx, dy in N8}
        a = min((da[p] for p in adj if p in da), default=None)
        b = min((db[p] for p in adj if p in db), default=None)
        if a is None or b is None:
            zone = "none" if a is None and b is None else ("A" if b is None else "B")
        else:
            r = a / max(1, a + b)
            zone = "A" if r < .4 else ("B" if r > .6 else "mid")
        ty = [camps[p] for p in comp]
        gs.append(dict(gems=sum(GEMS[t] for t in ty), gold=sum(GOLD[t] for t in ty), rsp=max(RSP[t] for t in ty), zone=zone))
    tg = sum(g["gems"] for g in gs)
    if not tg:
        _cache[path] = None
        return None
    gs.sort(key=lambda g: -g["gems"])
    big = gs[0]
    second = gs[1]["gems"] if len(gs) > 1 else 0
    A = [g for g in gs if g["zone"] == "A"]
    halfcap = sum(g["gems"] * 100.0 / (g["rsp"] + CAP) for g in A)
    goldcap = sum(g["gold"] * 100.0 / (g["rsp"] + CAP) for g in A)
    ok = (big["zone"] == "mid" and second < 0.9 * big["gems"] and big["gems"] >= 300 and big["gems"] >= 0.5 * tg
          and halfcap < 150 and goldcap >= 400)
    f = dict(jackpot=1.0 if ok else 0.0, jackpot_big=float(big["gems"]), jackpot_halfcap=round(halfcap, 1), jackpot_goldcap=round(goldcap, 1))
    _cache[path] = f
    return f


def _get(k):
    return lambda path: (_feats(path) or {}).get(k)


CLASSES = {k: _get(k) for k in ("jackpot", "jackpot_big", "jackpot_halfcap", "jackpot_goldcap")}
