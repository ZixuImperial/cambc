"""als1 (Econ, 11 Nov; spec_als_1111.md): single altar with its gems beside it.
als_share = gems of camp groups with any tile within Chebyshev 6 of an altar / all camp gems (groups = 4-connected camp components,
            gems per mapfeat.GEMS; with several altars, any altar counts); None when the map has no camp gems.
als1      = 1 when exactly 1 altar tile AND als_share >= .20, else 0.
Draft-time map features only (camps, altars), no map identity. Ladder: 14 in-class maps; 04comb reads ~.075 (groups at 5 and 15)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '/homes/USER/cambc/tools/lab')
import map26a  # noqa: E402
import mapfeat  # noqa: E402

ALS_R = 6
_c = {}


def _parts(path):
    if path not in _c:
        d = map26a.load(path)
        camps, alts = d['camps'], list(d['altar'])
        seen, tot, near = set(), 0, 0
        for c in camps:
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
            g = sum(mapfeat.GEMS[camps[p]] for p in comp)
            tot += g
            if any(max(abs(p[0] - a[0]), abs(p[1] - a[1])) <= ALS_R for p in comp for a in alts):
                near += g
        _c[path] = (near / tot if tot else None, len(alts))
    return _c[path]


def als_share(path, _g=None):
    s = _parts(path)[0]
    return None if s is None else round(s, 4)


def als1(path, _g=None):
    s, na = _parts(path)
    return 1 if na == 1 and s is not None and s >= .20 else 0


CLASSES = {"als_share": als_share, "als1": als1}
