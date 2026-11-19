"""gsc: Deep's gold-strategy class (condor-work/reports/analysts/gold_strategy_1110.md; reader condor-work/readers/deep_goldstrat.py).
G = the map's total group gold, the sum of every camp group's gold (draft-time map data; tools/lab/mapfeat.py's 'gold').
  gsc   : 2 gem-rush (G < 1,160), 1 gold-first (G >= 2,120), else 0 parallel   -> draw by G: stratmaps --class 'gsc_g:>=2120' (GF) / 'gsc_g:<1160' (GR); note gsc:>=1 is GF OR GR
  gsc_g : G itself (logged per map with --class-tag gsc,gsc_g)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_cache = {}


def _g(path, _m=None):
    if path not in _cache:
        _cache[path] = mapfeat.analyse(map26a.load(path))["gold"]
    return _cache[path]


def gsc(path, _m=None):
    g = _g(path)
    return 2 if g < 1160 else 1 if g >= 2120 else 0


CLASSES = {"gsc": gsc, "gsc_g": _g}
