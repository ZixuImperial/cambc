"""tgo: one camp group holds most of the map's gems (12 Nov, TB for Aggression / Builder TGO #135; Coordinator stamp 'tgo').
Draft-time, from the map alone: 4-connected camp groups as maxgem.py (wolf 4, elk 15, gem 7, gold 0, monolith 200, golem 36);
share = largest group's gems / all camp gems. tgo = 1 when share > .5, or share >= .5 with that group >= 100 gems (Aggression: the
plain >= .5 count also caught twin groups at exactly .50 and one 7-gem map), and in both cases the group holds >= 40 gems; else 0. tgo_share = the share (None: no gems)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maxgem import _groups  # noqa: E402


def _share(path, g):
    g = g if g is not None else _groups(path)
    tot = sum(x for x, _ in g)
    if tot <= 0:
        return None, 0
    big = max(x for x, _ in g)
    return big / tot, big


def tgo_share(path, _g=None):
    s, _ = _share(path, _g)
    return None if s is None else round(s, 4)


def tgo(path, _g=None):
    s, big = _share(path, _g)
    if s is None:
        return 0
    return 1 if big >= 40 and (s > 0.5 or (s >= 0.5 and big >= 100)) else 0  # 20:1xZ Aggression: a 40-gem floor (03one-gem's 7 gems is not a section worth a fight)


CLASSES = {"tgo": tgo, "tgo_share": tgo_share}
