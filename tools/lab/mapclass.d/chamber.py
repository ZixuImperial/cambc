"""chamber (b2393 CHB, 13 Nov; spec_gpl_1113 Amendments 17/21): the tight gem-chamber class from the map file, draft-time only, no
map identity. Groups = 4-connected camp tiles. Around each altar tile: the walk-reachable groups with no attacker (every member a gem or
gold cluster) and gems > 0 that have a member within Chebyshev CHB_R (6) of it. The best altar tile's region is the chamber when it holds
>= 4 such groups and >= 50% of the map's gems (the bot's chb_decide, econ_opening_pick.cc, uses its group anchors).
chb_share = the best region's share of the map's gems (0..1); chb_n = its group count; chamber = 1 when the class holds.
-> --class 'chamber:>=1'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
CLU = {2, 3}
_c = {}


def _feat(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    camps = m["camps"]
    seen, groups = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        groups.append(comp)
    total = sum(GEMS.get(camps[t], 0) for g in groups for t in g)
    best = (0, 0)
    for a in m["altar"]:
        s = n = 0
        for g in groups:
            gems = sum(GEMS.get(camps[t], 0) for t in g)
            if gems > 0 and all(camps[t] in CLU for t in g) and min(max(abs(t[0] - a[0]), abs(t[1] - a[1])) for t in g) <= 6:
                s += gems
                n += 1
        if s > best[0]:
            best = (s, n)
    share = best[0] / total if total > 0 else 0.0
    r = (share, best[1], 1 if best[1] >= 4 and share >= 0.5 else 0)
    _c[path] = r
    return r


def chb_share(path):
    return _feat(path)[0]


def chb_n(path):
    return _feat(path)[1]


def chamber(path):
    return _feat(path)[2]


CLASSES = {"chamber": chamber, "chb_share": chb_share, "chb_n": chb_n}
