"""kgs (13 Nov, TB for Deep's KGS, spec condor-work/reports/analysts/spec_kgs_1113.md): gem rate concentrated in one or two groups.
Group = 4-connected camp tiles (one camp per tile); gems from the rules table (wolf 4, elk 15, golem 36, gem cluster 7, monolith 200);
respawn = the group's largest camp respawn (wolf 40, elk 60, golem 80, clusters 50, monolith 150; the engine's max_respawn_timer).
rate = gems x 100 / (respawn + 5). kgs_top2 = share of the map's total gem rate in its top two groups (None on zero-gem maps);
kgs1 = 1 when that share >= .80. Draft-time, seat-free."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
RESP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
_c = {}


def kgs_top2(path, _g=None):
    if path in _c:
        return _c[path]
    camps = map26a.load(path)["camps"]
    seen, rates = set(), []
    for c in camps:
        if c in seen:
            continue
        st, gm, rs = [c], 0, 0
        seen.add(c)
        while st:
            x, y = st.pop()
            t = camps[(x, y)]
            gm += GEMS.get(t, 0)
            rs = max(rs, RESP.get(t, 50))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        if gm > 0:
            rates.append(gm * 100.0 / (rs + 5))
    tot = sum(rates)
    r = (sum(sorted(rates, reverse=True)[:2]) / tot) if tot > 0 else None
    _c[path] = r
    return r


def kgs1(path, _g=None):
    v = kgs_top2(path)
    return 1 if v is not None and v >= 0.80 else 0


CLASSES = {"kgs_top2": kgs_top2, "kgs1": kgs1}
