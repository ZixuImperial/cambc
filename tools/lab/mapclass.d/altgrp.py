"""altgrp (b2087 LAC, Prism Planner spec_lac_1112): altgrp1 = 1 if every altar tile is within Chebyshev 8 of every other
(one altar group), else 0; None with no altar. Draft-time map feature only (altar tiles), no map identity."""
import os
import sys

sys.path.insert(0, '/homes/USER/cambc/tools/lab')
import map26a  # noqa: E402


def altgrp1(path):
    a = list(map26a.load(path)['altar'])
    if not a:
        return None
    return 1.0 if all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 8 for p in a for q in a) else 0.0


CLASSES = {"altgrp1": altgrp1}
