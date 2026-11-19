"""altgrp10 (b2254 PAD bit 16 PACK, spec_pad_1112): 1 if every altar tile is within Chebyshev 10 of every other (altgrp1 widened from 8
to 10), else 0; None with no altar. Draft-time map feature only (altar tiles), no map identity."""
import sys

sys.path.insert(0, '/homes/zw4424/cambc/tools/lab')
import map26a  # noqa: E402


def altgrp10(path):
    a = list(map26a.load(path)['altar'])
    if not a:
        return None
    return 1.0 if all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 10 for p in a for q in a) else 0.0


CLASSES = {"altgrp10": altgrp10}
