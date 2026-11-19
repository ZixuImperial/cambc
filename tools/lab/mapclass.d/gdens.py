"""gdens: camp groups per 1000 map tiles (mapfeat grp / (W*H) * 1000), b1899 11 Nov for CLS (Planner spec_cls_1111) SPARSE =
bottom third of the fresh pool: gdens <= 6.80 (q33 of 1,200 fresh maps, st/b1869/maps1200b; q50 8.89, q67 11.11).
  stratmaps --class 'gdens:<=6.8'.  Draft-time map features only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_cache = {}


def gdens(path, _m=None):
    if path not in _cache:
        d = map26a.load(path)
        _cache[path] = round(1000.0 * mapfeat.analyse(d)["grp"] / (d["W"] * d["H"]), 4)
    return _cache[path]


CLASSES = {"gdens": gdens}
