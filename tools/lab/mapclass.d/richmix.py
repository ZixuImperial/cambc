"""richmix: camp groups worth a carry's capture: gems >= 60 AND gold > 0 (golem / elk + gem clusters). 12 Nov, TB for the Prism Planner
(rich mixed groups; ladder pool: >= 2 on 43% of maps, fresh 39%). 4-connected groups with mapfeat's GEMS / GOLD tables (as maxgem.py).
richmix = how many such groups the map has; richmix2 = 1 when >= 2 (class form: --class 'richmix2:>=1' or 'richmix:>=2')."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rich(path):
    import genmaps as G
    import mapfeat
    camps = G.map26a.load(path)["camps"]
    seen, n = set(), 0
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
        n += 1 if gm >= 60 and gd > 0 else 0
    return n


def richmix(path, _g=None):
    return _rich(path)


def richmix2(path, _g=None):
    return 1 if _rich(path) >= 2 else 0


CLASSES = {"richmix": richmix, "richmix2": richmix2}
