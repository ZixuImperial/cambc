"""maxgold (13 Nov, b2390 for Aggression's RGA / VV's class): the gold of the map's richest camp group (4-connected camp groups, one camp per
tile; gold from mapfeat's GOLD table, as lowpay / cltfcls). RGA's class is 'maxgold:>=600'. Draft-time map features only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def maxgold(path, _g=None):
    import genmaps as G
    import mapfeat
    camps = G.map26a.load(path)["camps"]
    seen, best = set(), 0
    for c in camps:
        if c in seen:
            continue
        st, gd = [c], 0
        seen.add(c)
        while st:
            x, y = st.pop()
            gd += mapfeat.GOLD[camps[(x, y)]]
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        best = max(best, gd)
    return best


CLASSES = {"maxgold": maxgold}
