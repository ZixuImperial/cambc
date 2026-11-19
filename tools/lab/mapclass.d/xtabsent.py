"""xtabsent (13 Nov, TB for b2390 DTB bit 2): 1 when the draft memory can carry NO EXACT_TRAVEL block, 0 otherwise. Draft-time, map only.
  The draft builds the block only when xt_size_ok(n, na): 2 <= n <= 200 camp groups (M.ng, as ngroups.py counts them), na <= 40 altar tiles
  (M.na, as naltars.py), and 16 + 3*(n+na) + 16 + n <= 736 (plan_exact_travel.cc:141, :188-191). A block lost at pack time is NOT seen here,
  so this class can only miss maps, never add ones that keep the block.  -> stratmaps --class 'xtabsent:>=1'
  xt_n / xt_na : the two counts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_cache = {}


def _f(path):
    if path not in _cache:
        d = map26a.load(path)
        n, na = mapfeat.analyse(d)["grp"], len(d["altar"])
        ok = 2 <= n <= 200 and na <= 40 and 16 + 3 * (n + na) + 16 + n <= 736
        _cache[path] = (0 if ok else 1, n, na)
    return _cache[path]


CLASSES = {"xtabsent": lambda p, _m=None: _f(p)[0], "xt_n": lambda p, _m=None: _f(p)[1], "xt_na": lambda p, _m=None: _f(p)[2]}
