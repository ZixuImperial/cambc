"""maxside (b2061 BKL, 11 Nov): the longer map side, max(W, H). --class 'maxside:>=70,nalt:<=1' = big one-altar maps."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def maxside(path):
    d = map26a.load(path)
    return max(d["W"], d["H"])


CLASSES = {"maxside": maxside}
