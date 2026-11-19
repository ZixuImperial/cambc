"""hidmem (12 Nov, Tool Builder; Coordinator / RC C670, BWT: a camp member hidden on an isolated bush tile; owner's Prism-stutter replay).
A camp tile counts when it sits on a bush tile whose CARDINAL bush cluster (4-connected bush tiles) holds no non-camp tile: nobody can
stand in that cluster, so the member is never seen from inside it (bush clusters are transparent only from within, GR:351).
  hidmem      number of such camp tiles            -> --class 'hidmem:>=1'
  hidmem_grp  number of camp groups holding one
Static map fields only, no map identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_c = {}


def _f(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    bush, camps = set(d["bush"]), d["camps"]
    seen, hid = set(), []
    for b in sorted(bush):
        if b in seen:
            continue
        comp, st = [b], [b]
        seen.add(b)
        while st:
            x, y = st.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in bush and n not in seen:
                    seen.add(n)
                    comp.append(n)
                    st.append(n)
        if all(p in camps for p in comp):
            hid += comp
    groups, gseen = 0, set()
    hs = set(hid)
    for p in hid:  # camp groups (4-connected camp tiles) holding a hidden member
        if p in gseen:
            continue
        st, grp = [p], {p}
        while st:
            x, y = st.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in grp:
                    grp.add(n)
                    st.append(n)
        gseen |= grp & hs
        groups += 1
    r = dict(hidmem=float(len(hid)), hidmem_grp=float(groups))
    _c[path] = r
    return r


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("hidmem", "hidmem_grp")}
