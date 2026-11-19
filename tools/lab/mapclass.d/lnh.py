"""lnh (13 Nov, b2376 for Econ's LNH / owner replay 01a1d490): the cluster count of the map's biggest 'lane', a camp group (4-connected,
one camp per tile) with no attacking member (no wolf, elk, monolith or golem) made of gem / gold clusters. LNH's class is 'lnh:>=10'
(the bot's lane: n_att == 0 and n_clu >= LNH_CLU 10). Draft-time map features only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLUSTER = (2, 3)  # camp_type gem_cluster, gold_cluster


def lnh(path, _g=None):
    import genmaps as G
    camps = G.map26a.load(path)["camps"]
    seen, best = set(), 0
    for c in camps:
        if c in seen:
            continue
        st, n, att = [c], 0, False
        seen.add(c)
        while st:
            x, y = st.pop()
            t = camps[(x, y)]
            if t in CLUSTER:
                n += 1
            else:
                att = True
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        if not att:
            best = max(best, n)
    return best


CLASSES = {"lnh": lnh}
