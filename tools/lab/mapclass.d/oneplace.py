"""oneplace (12 Nov, Tool Builder; b2226 LAC G_WIN Step 0, Aggression chain): every altar sits in one place.
  oneplace_spacing  max pairwise Chebyshev distance between altar TILES (0 with one altar tile; -1 with none)
  oneplace          1 when 0 <= oneplace_spacing <= 5 (single-altar maps count), else 0      -> --class 'oneplace:>=1'
  bush_near_altar   1 when some bush tile is within Chebyshev 5 of some altar tile, else 0
Static map fields only, no map identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_c = {}


def _f(path):
    if path not in _c:
        d = map26a.load(path)
        alt, bush = list(d["altar"]), list(d["bush"])
        sp = max((max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a in alt for b in alt), default=-1)
        bn = any(max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 5 for a in alt for b in bush)
        _c[path] = dict(oneplace_spacing=float(sp), oneplace=1.0 if 0 <= sp <= 5 else 0.0, bush_near_altar=float(bn))
    return _c[path]


CLASSES = {k: (lambda k: lambda path: _f(path)[k])(k) for k in ("oneplace", "oneplace_spacing", "bush_near_altar")}
