"""gopa (b2146 GOP A, RC C559b, 12 Nov): mirrors the bot's gop_class() (nova_b2146_gopb econ_value.cc:272):
gopa = 1 when altgrp1 == 1 (every altar tile within Chebyshev 8 of every other; the bot's map_class4() bit 64) AND groups >= 35
(mapfeat.analyse()['grp'], the bot's M.ng) AND 100*G >= 35*(G + 2*M), G / M = gold / gems summed over the camps (mapfeat.GOLD/GEMS);
else 0; None with no altar. Note the 2x gem weight: gold_share.py and grc1 use G/(G+10M) (grc1 also needs exactly 1 altar, heavy <= .10).
b2146 check: 60/60 w_goldring1 maps in class, 2/150 fresh maps; colosseum share2x .804, sanctum .838; 04plaza (ng 20) and 04yin_yang
(altgrp 0) out. Draft-time map features only, no map identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/homes/USER/cambc/tools/lab")
import map26a  # noqa: E402
import mapfeat  # noqa: E402
from altgrp import altgrp1  # noqa: E402


def gopa(path):
    a = altgrp1(path)
    if a is None:
        return None
    m = map26a.load(path)
    t = list(m["camps"].values())
    g = sum(mapfeat.GOLD[x] for x in t)
    gm = sum(mapfeat.GEMS[x] for x in t)
    ng = mapfeat.analyse(m)["grp"]
    return 1.0 if a and ng >= 35 and 100 * g >= 35 * (g + 2 * gm) else 0.0


CLASSES = {"gopa": gopa}
