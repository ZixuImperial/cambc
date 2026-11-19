"""safealtar: Deep's Class A (12 Nov, spec_pfm_1112.md, owner's 00collision replay; reference /data/zw4424/st/deepan/owner_cd44b/py/cls.py,
report condor-work/reports/analysts/owner_01a1cd44_collision_prism_1112.md). Draft-time map features only. Tool Builder 12 Nov.
  safealtar = 1 when (1) >= 2 altars; (2) one altar is SAFE for a side: walkable, the other side's walk to it >= 10 steps longer
  (seat-A view; the mirror gives B its own), OR walled (no walk from either spawn) and reachable by a teleport crystal (some tile of its
  enclosure within 3 of a tile team A walks to); (3) the CONTESTED gem groups (walk-ratio dA / (dA + dB) in [.45, .55]) within 4 walk
  steps of a CONTESTED walkable altar (walks within 10% of each other) carry >= 10% of the map's gem flow (gems x 100 / (period + 5), as keystone). Parts: safealtar_walled (an altar of
  the walled kind), safealtar_flow (that flow share).  -> stratmaps --class 'safealtar:>=1'"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jackpot as J  # noqa: E402

_cache = {}


def _feats(path):
    if path in _cache:
        return _cache[path]
    d = J.map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    da, db = J._bfs(W, H, list(d["spawnA"]), block), J._bfs(W, H, list(d["spawnB"]), block)
    inb = lambda q: 0 <= q[0] < W and 0 <= q[1] < H  # noqa: E731
    alts = []
    for a in sorted(d["altar"]):
        adj = [(a[0] + dx, a[1] + dy) for dx, dy in J.N8 if inb((a[0] + dx, a[1] + dy)) and (a[0] + dx, a[1] + dy) not in block]
        A = [da[q] for q in adj if q in da]
        B = [db[q] for q in adj if q in db]
        dA, dB = (min(A) if A else None), (min(B) if B else None)
        cr = None
        if dA is None and adj:
            reg = J._bfs(W, H, adj, block)
            cr = min((da[(x + ex, y + ey)] for (x, y) in reg for ex in range(-3, 4) for ey in range(-3, 4) if (x + ex, y + ey) in da), default=None)
        alts.append((adj, dA, dB, cr))
    # the gem groups that count sit within 4 walk of a CONTESTED walkable altar (both walks within 10% of each other), as the spec says
    conalt = [x for x in alts if x[1] is not None and x[2] is not None and abs(x[1] - x[2]) <= 0.1 * (x[1] + x[2])]
    altadj = [q for adj, *_ in conalt for q in adj]
    dalt = J._bfs(W, H, altadj, block) if altadj else {}
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
        nb = {(x + dx, y + dy) for (x, y) in comp for dx, dy in J.N8}
        a = min((da[p] for p in nb if p in da), default=None)
        b = min((db[p] for p in nb if p in db), default=None)
        al = min((dalt[p] for p in nb if p in dalt), default=None)
        ty = [camps[p] for p in comp]
        gs.append(dict(gems=sum(J.GEMS[t] for t in ty), rsp=max(J.RSP[t] for t in ty), dA=a, dB=b, dalt=al))
    fl = lambda g: g["gems"] * 100.0 / (g["rsp"] + J.CAP)  # noqa: E731
    tgf = sum(fl(g) for g in gs) or 1.0
    walk = [x for x in alts if x[1] is not None and x[2] is not None]
    walled = [x for x in alts if x[1] is None and x[2] is None and x[3] is not None]
    side = [x for x in walk if x[2] - x[1] >= 10]
    con = [g for g in gs if g["dA"] is not None and g["dB"] is not None and .45 <= g["dA"] / max(1, g["dA"] + g["dB"]) <= .55]
    altg = [g for g in con if g["dalt"] is not None and g["dalt"] <= 4]
    share = sum(fl(g) for g in altg) / tgf
    ok = len(alts) >= 2 and (side or walled) and share >= 0.10
    f = dict(safealtar=1.0 if ok else 0.0, safealtar_walled=1.0 if ok and walled else 0.0, safealtar_flow=round(share, 3))
    _cache[path] = f
    return f


def _get(k):
    return lambda path: (_feats(path) or {}).get(k)


CLASSES = {k: _get(k) for k in ("safealtar", "safealtar_walled", "safealtar_flow")}
