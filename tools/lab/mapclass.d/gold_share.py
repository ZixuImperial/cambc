"""gold_share / gcl_share (Deep draft analyst 11 Nov; condor-work/reports/analysts/draft_goldshare_1111.md).
gold_share = G / (G + 10 x M): G = total camp gold, M = total camp gems over every camp tile (mapfeat GOLD/GEMS tables;
             same as fablean goldgem.py's replay-group sums). Thirds on 128 ladder maps: < .22 gem-focused, >= .35 gold-focused.
gcl_share  = gold-cluster tiles / (gold-cluster + gem-cluster tiles); -1 when the map has no cluster.
gsh3       = 0 gem (<.22), 1 mixed, 2 gold (>=.35)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '/homes/zw4424/cambc/tools/lab')
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


def _f(path):
    if path not in _c:
        cs = map26a.load(path)['camps']
        t = list(cs.values())
        g = sum(mapfeat.GOLD[x] for x in t); m = sum(mapfeat.GEMS[x] for x in t)
        gc = sum(1 for x in t if x == 3); mc = sum(1 for x in t if x == 2)
        _c[path] = (g / max(1, g + 10 * m), gc / (gc + mc) if gc + mc else -1.0)
    return _c[path]


def gold_share(path, _m=None):
    return round(_f(path)[0], 4)


def gcl_share(path, _m=None):
    return round(_f(path)[1], 4)


def gsh3(path, _m=None):
    s = _f(path)[0]
    return 0 if s < .22 else 2 if s >= .35 else 1


CLASSES = {"gold_share": gold_share, "gcl_share": gcl_share, "gsh3": gsh3}
