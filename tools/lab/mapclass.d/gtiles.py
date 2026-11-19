"""gtiles: tile count of the map's largest camp-group region (b2035 11 Nov, spec_ovp_1111 camp-region class): max over 4-connected camp
groups of the number of member (spawn) tiles. Caches numbers only.
  gtiles : that count -> e.g. stratmaps --class 'gtiles:>=20'"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}


def gtiles(path, _m=None):
    if path not in _cache:
        camps = map26a.load(path)['camps']
        seen, best = set(), 0
        for p in camps:
            if p in seen:
                continue
            st, n = [p], 0
            seen.add(p)
            while st:
                c = st.pop()
                n += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    q = (c[0] + dx, c[1] + dy)
                    if q in camps and q not in seen:
                        seen.add(q)
                        st.append(q)
            best = max(best, n)
        _cache[path] = best
    return _cache[path]


CLASSES = {"gtiles": gtiles}
