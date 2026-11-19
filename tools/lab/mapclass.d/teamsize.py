"""teamsize (b2109 LPP, 12 Nov): champions per team on the map (map26a champs_per_team; C&I is one pick, two bodies).
-> --class 'teamsize:<=3' for the small-team maps (3 bodies, 4 with C&I)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def teamsize(path):
    return int(map26a.load(path)["champs_per_team"])


CLASSES = {"teamsize": teamsize}
