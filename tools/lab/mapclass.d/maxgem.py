"""maxgem: the biggest 4-connected camp group's gems (wolf 4, elk 15, gem 7, gold 0, monolith 200, golem 36), b2013 11 Nov for the
SGMC siege-margin info rows (X454): stratmaps --class 'maxgem:>=400' draws maps with a 400+ gem group."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}


def _groups(path):
    import genmaps as G
    camps = G.map26a.load(path)["camps"]
    seen, out = set(), []
    for c in camps:
        if c in seen:
            continue
        tot, st = 0, [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            tot += _GEM[camps[(x, y)]]
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        out.append((tot, None))
    return out


def maxgem(path, _g=None):
    g = _g if _g is not None else _groups(path)
    return max((x for x, _ in g), default=None)


CLASSES = {"maxgem": maxgem}
