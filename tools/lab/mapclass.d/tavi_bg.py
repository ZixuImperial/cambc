"""tavi_bg (b1802, CI Planner; TAM-S confirm 11 Nov): 1 when gem/gold cluster tiles >= .80 of camp tiles, no elk, golem or monolith camp,
and gold-cluster tiles / (gold + gem cluster tiles) >= .50 (tavi_b AND gcl_share >= .5); else 0."""
import os
import sys

sys.path.insert(0, '/homes/zw4424/cambc/tools/lab')
import map26a  # noqa: E402


def tavi_bg(path):
    t = list(map26a.load(path)['camps'].values())
    if not t:
        return 0
    gc, mc = sum(1 for v in t if v == 3), sum(1 for v in t if v == 2)
    if (gc + mc) / len(t) < 0.80 or any(v in (1, 4, 5) for v in t) or gc + mc == 0:
        return 0
    return 1 if gc / (gc + mc) >= 0.50 else 0


CLASSES = {"tavi_bg": tavi_bg}
