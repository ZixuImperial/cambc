"""cry (b1940, 11 Nov): mapfeat's 'cry' = share of camp gems in groups reachable only by crystal (teleport) from the spawns -> --class 'cry:>0'.
Rough proxy for the bot's crystal-stage work (any_teleport_groups(): an ACC_TP group with gems+gold > 0, econ_crystal_plan.cc:95)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_c = {}


def cry(path):
    if path not in _c:
        _c[path] = float(mapfeat.analyse(map26a.load(path)).get("cry") or 0.0)
    return _c[path]


CLASSES = {"cry": cry}
