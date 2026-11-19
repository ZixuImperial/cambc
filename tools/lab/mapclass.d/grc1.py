"""grc1 (Econ, 11 Nov; spec_grc_1111.md): the narrow gold-race class.
grc1 = 1 when gold_share = G / (G + 10 x M) >= .40 AND heavy share (gems on elk/golem/monolith tiles / all gems) <= .10 AND exactly 1 altar; else 0.
Draft-time map features only (camps, altars), no map identity. Ladder bank: 03colosseum, 04sanctum, 02the_pack (3/128)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '/homes/USER/cambc/tools/lab')
import map26a  # noqa: E402
import mapfeat  # noqa: E402

HEAVY_GEMS = (15, 36, 200)  # elk, golem, monolith tiles in mapfeat.GEMS


def _parts(path):
    m = map26a.load(path)
    t = list(m['camps'].values())
    g = sum(mapfeat.GOLD[x] for x in t)
    gems = sum(mapfeat.GEMS[x] for x in t)
    heavy = sum(mapfeat.GEMS[x] for x in t if mapfeat.GEMS[x] in HEAVY_GEMS)
    return g / max(1, g + 10 * gems), heavy / max(1, gems), len(m['altar'])


def grc1(path, _m=None):
    gs, hv, na = _parts(path)
    return 1 if (gs >= .40 and hv <= .10 and na == 1) else 0


def grc1_parts(path, _m=None):
    gs, hv, na = _parts(path)
    return round(gs, 3) * 1000 + round(hv, 2) * 10 + na  # packed for eyeballing only


CLASSES = {"grc1": grc1, "grc1_parts": grc1_parts}
