"""altclu (b2370 ASB bit 8, Planner 13 Nov; draft-time map features only, no map identity).
  altclu   = 1 when the map has >= 2 altars and every altar is within Chebyshev 2 of every other (= the bot's asb_cluster(), econ_bank_win.cc).
  altclu_n = number of altars."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def _alt(path):
    return [tuple(a) for a in map26a.load(path)["altar"]]


def altclu(path):
    a = _alt(path)
    return 1 if len(a) >= 2 and all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 for p in a for q in a) else 0


def altclu_n(path):
    return len(_alt(path))


CLASSES = {"altclu": altclu, "altclu_n": altclu_n}
