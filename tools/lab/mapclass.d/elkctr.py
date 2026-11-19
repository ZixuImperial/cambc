"""elkctr: the Planner's ELKCTR class (12 Nov; reference /data/zw4424/st/planner/elkctr/py/cls.py). Map-only features. Tool Builder 12 Nov.
  The largest group(s) by gems (4-connected camps; mirror copies tie) hold >= 3 elk and no golem or monolith, and together >= 20% of the
  map's gem flow (gems x 100 / (slowest respawn + 5)).  elkctr = 1 / 0; elkctr_share = that flow share; elkctr_nelk = elk in one top group.
  -> stratmaps --class 'elkctr:>=1'"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
RESP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
_cache = {}


def _feats(path):
    if path in _cache:
        return _cache[path]
    camps = map26a.load(path)["camps"]
    seen, gs = set(), []
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
        ty = [camps[p] for p in comp]
        gems = sum(GEM[t] for t in ty)
        gs.append((gems, gems * 100.0 / (max(RESP[t] for t in ty) + 5), ty))
    if not gs:
        _cache[path] = None
        return None
    tot = sum(g[1] for g in gs)
    mx = max(g[0] for g in gs)
    top = [g for g in gs if g[0] == mx]
    nelk = top[0][2].count(1)
    heavy = any(t in (4, 5) for t in top[0][2])
    tshare = sum(g[1] for g in top) / tot if tot else 0.0
    f = dict(elkctr=1.0 if nelk >= 3 and not heavy and mx > 0 and tshare >= 0.20 else 0.0, elkctr_share=round(tshare, 3), elkctr_nelk=float(nelk))
    _cache[path] = f
    return f


def _get(k):
    return lambda path: (_feats(path) or {}).get(k)


CLASSES = {k: _get(k) for k in ("elkctr", "elkctr_share", "elkctr_nelk")}
