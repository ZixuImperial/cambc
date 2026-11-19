"""naltars (b1913 PGN, Prism Planner spec, 11 Nov): altar TILES on the map, as mapfeat's 'alt' and the bot's M.na count them (a 2x2 altar
counts 4; for whole altars use psa.py's alt1/nalt). -> --class 'naltars:>=2,naltars:<=2' for ==2."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def naltars(path):
    return len(map26a.load(path)["altar"])


CLASSES = {"naltars": naltars}
