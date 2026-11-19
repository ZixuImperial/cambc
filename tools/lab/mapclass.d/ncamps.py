"""ncamps: the map's camp-tile count (was in mapclass.py; restored as a plugin 11 Nov after the stellar move dropped it)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genmaps as G  # noqa: E402


def ncamps(path):
    return len(G.map26a.load(path)["camps"])


CLASSES = {"ncamps": ncamps}
