"""osg (13 Nov, TB for Deep's OSG, spec condor-work/reports/analysts/spec_osg_1113.md, bank slug osg3): own-side gem groups far from spawn.
Per seat: count camp groups (4-connected camp tiles) with contest d_me / (d_me + d_foe) <= .40 (walk distances: 8-way BFS from each spawn,
walls / holes / altars blocked, camps passable as in cltfcls), >= 2 gem-cluster camp tiles (type 2), and walk >= 30 from my spawn.
osg = the larger seat count; osg2 = 1 when osg >= 2 (class 'osg2:>=1'). Draft-time, seat-free."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402
import cltfcls  # noqa: E402

GEMC = 2
_c = {}


def osg(path, _g=None):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = cltfcls._bfs(W, H, block, m["spawnA"]), cltfcls._bfs(W, H, block, m["spawnB"])
    seen, nA, nB = set(), 0, 0
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
        if sum(1 for t in comp if camps[t] == GEMC) < 2:
            continue
        a = min((dA[t] for t in comp if t in dA), default=None)
        b = min((dB[t] for t in comp if t in dB), default=None)
        if a is None or b is None or a + b == 0:
            continue
        if a >= 30 and a / (a + b) <= .40:
            nA += 1
        if b >= 30 and b / (a + b) <= .40:
            nB += 1
    _c[path] = max(nA, nB)
    return _c[path]


def osg2(path, _g=None):
    return 1 if osg(path) >= 2 else 0


def osg1(path, _g=None):
    """Amendment 3 (Deep 04:12Z, RC C1069): >= 1 own-side group (static contest d_me / (d_me + d_foe) <= .40, mapinfo.cc:415-419; foe
    unreachable -> 0) holding >= 2 gem-cluster tiles, either seat; no walk floor."""
    import map26a as _m
    m = _m.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = cltfcls._bfs(W, H, block, m["spawnA"]), cltfcls._bfs(W, H, block, m["spawnB"])
    seen = set()
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
        if sum(1 for t in comp if camps[t] == GEMC) < 2:
            continue
        a = min((dA[t] for t in comp if t in dA), default=None)
        b = min((dB[t] for t in comp if t in dB), default=None)
        for me, foe in ((a, b), (b, a)):
            if me is None:
                continue
            con = 0.0 if foe is None else me / max(1, me + foe)
            if con <= .40:
                return 1
    return 0


CLASSES = {"osg": osg, "osg2": osg2, "osg1": osg1}
