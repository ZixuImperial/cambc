"""wbm (b2272, 12 Nov, for WMH/WBM forced-lineup acceptance): the LARGEST mid camp group (cardinally connected camp tiles, GameRules:173;
mid = midgem.py's zone rule r = dA/(dA+dB) in .4-.6 at the tile nearest the centroid). wbm_midg = its gems, wbm_sh = its share of all camp gems.
Main WMH class: wbm_midg >= 50 and wbm_sh >= .25 (spec_wmh_1112.md). Draft-time map features only, no map identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midgem import _bfs  # noqa: E402

_c = {}


def _parts(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d['camps']
    da, db = _bfs(d, list(d['spawnA'])), _bfs(d, list(d['spawnB']))
    seen, tot, best = set(), 0, 0
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
        cx, cy = sum(p[0] for p in comp) / len(comp), sum(p[1] for p in comp) / len(comp)
        t = min((p for p in comp if p in da and p in db), key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2, default=None)
        if t is not None:
            r = da[t] / max(1, da[t] + db[t])
            if .4 <= r <= .6 and g > best:
                best = g
    _c[path] = (best, (best / tot) if tot else None)
    return _c[path]


def wbm_midg(path, _g=None):
    return _parts(path)[0]


def wbm_sh(path, _g=None):
    s = _parts(path)[1]
    return None if s is None else round(s, 4)


CLASSES = {"wbm_midg": wbm_midg, "wbm_sh": wbm_sh}

if __name__ == '__main__':
    for a in sys.argv[1:]:
        print(a, _parts(a))
