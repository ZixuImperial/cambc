"""swgpack (b2395, spec_swg_1113 SWG bit 1): the most wolves in one wolf-only camp group (4-connected camps; clusters allowed, no elk,
golem or monolith); the bot's swg_pack() is n_wolf >= 12. --class 'swgpack:>=12'"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a


def _swgpack(path, _g=None):
    camps = map26a.load(path)["camps"]
    seen, best = set(), 0
    for c in camps:
        if c in seen:
            continue
        st, nw, heavy = [c], 0, False
        seen.add(c)
        while st:
            q0 = st.pop()
            t = camps[q0]
            nw += t == 0
            heavy |= t in (1, 4, 5)
            x, y = q0
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        if not heavy:
            best = max(best, nw)
    return float(best)


CLASSES = {"swgpack": _swgpack}
