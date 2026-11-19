"""ngroups: the map's camp-group count as the bot sees it (M.ng: 4-connected camp groups), b1835 11 Nov for HFT (X275, huge-map first
turns). HFT changes play only where the groups are not built by round 6 (hms maps, 255-432 groups); w_huge, w_hugefew and
w_checker_big (66-274 groups) have them by round 1-4, so HFT does not change them.
  ngroups : the count  -> e.g. stratmaps --class 'ngroups:>=255'
No generator family reaches the hms class yet (b1789's hms_* maps were built by hand), so a class read on it finds no fresh maps today."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

_cache = {}


def ngroups(path, _m=None):
    if path not in _cache:
        _cache[path] = mapfeat.analyse(map26a.load(path))["grp"]
    return _cache[path]


CLASSES = {"ngroups": ngroups}
