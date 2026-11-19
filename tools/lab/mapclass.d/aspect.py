"""aspect (13 Nov, TB for b2385 / ckx8): map elongation. aspect = max(W, H) / min(W, H) (float); elong = 1 when 2*max >= 5*min (aspect >= 2.5,
integer test, no float edge). --class 'elong:>=1' = elongated maps from any generator."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def aspect(path, _g=None):
    d = map26a.load(path)
    return max(d["W"], d["H"]) / max(1, min(d["W"], d["H"]))


def elong(path, _g=None):
    d = map26a.load(path)
    return 1 if 2 * max(d["W"], d["H"]) >= 5 * min(d["W"], d["H"]) else 0


CLASSES = {"aspect": aspect, "elong": elong}
