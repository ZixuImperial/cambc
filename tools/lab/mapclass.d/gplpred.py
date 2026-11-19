"""gplpred (b2392 prereg /data/zw4424/st/b2392/sub/prereg.md ADDENDUM 2; Tool Builder wrapper 13 Nov): b2392's subset predicates on
tools/lab/gplfeat.py feats(path), 1 = member. --class 'gpl_p8:>=1' etc.
  gpl_p8 : n_altar == 1 and hs_altar <= 8 and hs_zone <= 1
  gpl_p7 : own_ratio <= 0.45 and own_to_contest <= 12
  gpl_p10: con20 <= 0.20 and own_disp <= 8"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gplfeat as _G  # noqa: E402

_c = {}


def _f(p):
    if p not in _c:
        try:
            _c[p] = _G.feats(p) or {}
        except Exception:  # noqa: BLE001  a map gplfeat can't read is not a member
            _c[p] = {}
    return _c[p]


def _p8(p, _m=None):
    d = _f(p)
    return int(d.get("n_altar") == 1 and d.get("hs_altar", 99) <= 8 and d.get("hs_zone", 99) <= 1)


def _p7(p, _m=None):
    d = _f(p)
    return int(d.get("own_ratio", 9) <= 0.45 and d.get("own_to_contest", 999) <= 12)


def _p10(p, _m=None):
    d = _f(p)
    return int(d.get("con20", 9) <= 0.20 and d.get("own_disp", 999) <= 8)


CLASSES = {"gpl_p8": _p8, "gpl_p7": _p7, "gpl_p10": _p10}
