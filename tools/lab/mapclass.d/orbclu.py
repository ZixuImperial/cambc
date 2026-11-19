"""orbclu: ORB's clustered-map feature (b2347, spec_orb_1112 / RC C879 E5; the bot's MCL3 bit 32 is set from orb_cluster_x1000()).
orbclu = median over camp groups of the share of all group value (gems + gold per camp tile, mapfeat tables) whose group anchors lie within
Chebyshev 10 of the group's anchor, x 1000. A mirror: groups are 4-connected camp components and the anchor is the component's first camp in
(y, x) order, so values can differ a little from the bot's (its groups come from the engine); the bot's draft value decides in play.
  orbclu : the value  -> e.g. stratmaps --class 'orbclu:>=CUT' (CUT in /data/zw4424/st/b2347/prereg_orb.md)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


def orbclu(path, _m=None):
    if path in _c:
        return _c[path]
    camps = map26a.load(path)["camps"]
    seen, grp = set(), []
    for c in sorted(camps, key=lambda p: (p[1], p[0])):
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
        v = sum(mapfeat.GEMS[camps[p]] + mapfeat.GOLD[camps[p]] for p in comp)
        grp.append((c, v))
    tot = sum(v for _, v in grp)
    if not grp or tot <= 0:
        _c[path] = 0
        return 0
    sh = sorted(1000 * sum(v for b, v in grp if max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 10) // tot for a, _ in grp)
    _c[path] = sh[len(sh) // 2]
    return _c[path]


CLASSES = {"orbclu": orbclu}
