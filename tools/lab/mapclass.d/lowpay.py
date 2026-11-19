"""lowpay (13 Nov, TB for the Planner's zgs32 information row, VGL bit 32): share of the map's gems that sit in camp groups paying <= 2.5 gold
per gem (4-connected camp groups, one camp per tile; gold and gems from mapfeat's GOLD / GEMS tables, as cltfcls / richmix). Zero-gold groups
count (0 gold per gem). None when the map has no gems.  lowpay -> share (0-1), e.g. --class 'lowpay:>=0.5'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def lowpay(path, _g=None):
    import genmaps as G
    import mapfeat
    camps = G.map26a.load(path)["camps"]
    seen, tot, low = set(), 0, 0
    for c in camps:
        if c in seen:
            continue
        st, gm, gd = [c], 0, 0
        seen.add(c)
        while st:
            x, y = st.pop()
            t = camps[(x, y)]
            gm += mapfeat.GEMS[t]
            gd += mapfeat.GOLD[t]
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        tot += gm
        if gm > 0 and gd <= 2.5 * gm:
            low += gm
    return low / tot if tot else None


CLASSES = {"lowpay": lowpay}
