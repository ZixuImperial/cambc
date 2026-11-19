"""rhf (13 Nov, b2364; spec condor-work/reports/analysts/spec_rhf_1113.md, owner replay 01a1d490 01yellow_brick_road): LONG SHARED capture
regions. Static map fields only, no map identity.
  rhf_len    member tiles of the largest qualifying camp group (4-connected camp tiles) whose reward (gold + 10 x gems) >= 300 and whose
             tiles sit between the spawns (Chebyshev share dA / (dA + dB) in [.35, .65] at the group's nearest tile to each spawn)
  rhf        1 when rhf_len >= 10, else 0      -> --class 'rhf:>=1'
Gold / gem tables as mapfeat (wolf 40/4, elk 90/15, gem cluster 0/7, gold cluster 20/0, monolith 300/200, golem 160/36)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
_c = {}


def _f(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d["camps"]
    sa, sb = d["spawnA"], d["spawnB"]
    seen, best = set(), 0
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [c], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    comp.append(n)
                    st.append(n)
        val = sum(GOLD.get(camps[p], 0) + 10 * GEMS.get(camps[p], 0) for p in comp)
        if val < 300 or len(comp) <= best:
            continue
        da = min(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p in comp for q in sa) if sa else 0
        db = min(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p in comp for q in sb) if sb else 0
        if da + db > 0 and 0.35 <= da / (da + db) <= 0.65:
            best = len(comp)
    r = dict(rhf_len=float(best), rhf=1.0 if best >= 10 else 0.0)
    _c[path] = r
    return r


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("rhf", "rhf_len")}
