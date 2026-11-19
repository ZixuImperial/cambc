"""keystone: Deep's KEYSTONE class (12 Nov, owner's 00the_line / 03one_gem line; reference /data/zw4424/st/deepan/theline/cls.py, report
condor-work/reports/analysts/owner_theline_mapclass_1112.md). Draft-time map features only. Tool Builder 12 Nov.
  Groups, zones and respawn periods as mapclass.d/jackpot.py (zone from 8-way walk distance to the spawns; period = slowest kind + 5).
  keystone = 1 when (1) the largest group by gems is in the mid zone and no other group has >= 90% of its gems; (2) its gem FLOW
  (gems x 100 / period) is >= half the map's flow (all groups); (3) team A's own-zone gem cap < 150 per 100 rounds. Else 0.
  keystone_s0 = 1 when keystone and that group has no attacking camp (Strength 0: gem/gold clusters only).
  Parts: keystone_big (its gems), keystone_flow (its flow share), keystone_halfcap.  -> stratmaps --class 'keystone:>=1'"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jackpot as J  # noqa: E402  (group / zone / respawn analysis shared with the jackpot class)

STR = {0: 20, 1: 60, 2: 0, 3: 0, 4: 200, 5: 120}
_cache = {}


def _feats(path):
    if path in _cache:
        return _cache[path]
    d = J.map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    da, db = J._bfs(W, H, list(d["spawnA"]), block), J._bfs(W, H, list(d["spawnB"]), block)
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
        adj = {(x + dx, y + dy) for (x, y) in comp for dx, dy in J.N8}
        a = min((da[p] for p in adj if p in da), default=None)
        b = min((db[p] for p in adj if p in db), default=None)
        if a is None or b is None:
            zone = "none" if a is None and b is None else ("A" if b is None else "B")
        else:
            r = a / max(1, a + b)
            zone = "A" if r < .4 else ("B" if r > .6 else "mid")
        ty = [camps[p] for p in comp]
        gs.append(dict(gems=sum(J.GEMS[t] for t in ty), rsp=max(J.RSP[t] for t in ty), str=sum(STR[t] for t in ty), zone=zone))
    tg = sum(g["gems"] for g in gs)
    if not tg:
        _cache[path] = None
        return None
    gs.sort(key=lambda g: -g["gems"])
    big = gs[0]
    second = gs[1]["gems"] if len(gs) > 1 else 0
    flow = lambda g: g["gems"] * 100.0 / (g["rsp"] + J.CAP)  # noqa: E731
    tf = sum(flow(g) for g in gs)
    fshare = flow(big) / tf if tf else 0.0
    halfcap = sum(flow(g) for g in gs if g["zone"] == "A")
    ok = big["zone"] == "mid" and second < 0.9 * big["gems"] and fshare >= 0.5 and halfcap < 150
    f = dict(keystone=1.0 if ok else 0.0, keystone_s0=1.0 if ok and big["str"] == 0 else 0.0, keystone_big=float(big["gems"]),
             keystone_flow=round(fshare, 3), keystone_halfcap=round(halfcap, 1))
    _cache[path] = f
    return f


def _get(k):
    return lambda path: (_feats(path) or {}).get(k)


CLASSES = {k: _get(k) for k in ("keystone", "keystone_s0", "keystone_big", "keystone_flow", "keystone_halfcap")}
