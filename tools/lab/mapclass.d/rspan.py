"""rspan: the longest camp-group region on the map (b1959 11 Nov, PNB CHALLENGER): max over 4-connected camp groups of the
Chebyshev span of the group's member tiles (max(dx, dy) of its bounding box), as the bot's static per-group span.
  rspan : that span -> e.g. stratmaps --class 'rspan:>=20' (PNB_SPAN 20; adaptation 15)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_cache = {}


def rspan(path, _m=None):
    if path not in _cache:
        d = map26a.load(path)
        camps = d['camps']
        seen, best = set(), 0
        for p in camps:
            if p in seen:
                continue
            st, g = [p], [p]
            seen.add(p)
            while st:
                c = st.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + dx, c[1] + dy)
                    if n in camps and n not in seen:
                        seen.add(n)
                        g.append(n)
                        st.append(n)
            xs = [q[0] for q in g]
            ys = [q[1] for q in g]
            best = max(best, max(xs) - min(xs), max(ys) - min(ys))
        _cache[path] = best
    return _cache[path]


CLASSES = {"rspan": rspan}
