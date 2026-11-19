"""gemonly (13 Nov, TB for b2413 PMG): 1 when total camp gold G < 100, or G / (G + 10 x M) <= .05; else 0. G and M sum mapfeat GOLD / GEMS
over every camp tile, exactly as gold_share.py (and b2413's pgpsplit.py and the bot gate pmg_gemonly in econ_retarget.cc).
  gemonly   -> --class 'gemonly:>=1'
  gem_g     total camp gold G."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


def _f(path):
    if path not in _c:
        t = list(map26a.load(path)["camps"].values())
        g = sum(mapfeat.GOLD[x] for x in t)
        m = sum(mapfeat.GEMS[x] for x in t)
        _c[path] = (1 if (g < 100 or g / max(1, g + 10 * m) <= .05) else 0, g)
    return _c[path]


CLASSES = {"gemonly": lambda p, _m=None: _f(p)[0], "gem_g": lambda p, _m=None: _f(p)[1]}
