"""kvm (12 Nov, Tool Builder; Deep / RC C579, spec condor-work/reports/analysts/spec_kvm_1112.md): KVM = keep Vendetta on one-altar MONOLITH
maps. Static map fields only, no map identity.
  kvm_alt      altar TILES on the map (as naltars.py / the bot's M.na; DSW cell 6's condition, draft.h row `19, 4, 1, 1`: == 1)
  kvm_monogrp  gems of camp groups (4-connected camp tiles) that contain a MONOLITH (kind 4; golems NOT counted: RC's 'case 19' feature)
               / gems of all camp groups (0 when the map has no gems)
  kvm          1 when kvm_alt == 1 and kvm_monogrp >= .50, else 0      -> --class 'kvm:>=1'
Gem table (mapfeat / GameRules): wolf 4, elk 15, gem cluster 7, gold cluster 0, monolith 200, golem 36."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
_c = {}


def _f(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d["camps"]
    seen, num, den = set(), 0, 0
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
        g = sum(GEMS.get(camps[p], 0) for p in comp)
        den += g
        if any(camps[p] == 4 for p in comp):
            num += g
    alt = len(d["altar"])
    share = num / den if den else 0.0
    r = dict(kvm_alt=float(alt), kvm_monogrp=round(share, 4), kvm=1.0 if alt == 1 and share >= 0.5 else 0.0)
    _c[path] = r
    return r


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("kvm", "kvm_alt", "kvm_monogrp")}
