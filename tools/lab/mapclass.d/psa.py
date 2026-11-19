"""psa: plain map reads for the Prism Planner's class-gated read (spec_psa_1111, 11 Nov; Tool Builder).
  alt1 = number of altars: 8-connected components of altar tiles (a 2x2 altar counts once)   -> 'alt1:<=1'
  team = champions per team (map header champs_per_team)                                       -> 'team:<=5'
  (area = W x H is mapclass's built-in 'area'.) Combine with a comma: --class 'alt1:<=1,area:<1600,team:<=5' (all must hold)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_c = {}


def _load(path):
    """11 Nov: cache the few numbers only. Caching whole map dicts held GBs on a 3,300-map fresh read and OOM-killed shipchecks at 8 GB."""
    if path not in _c:
        d = map26a.load(path)
        _c[path] = dict(altar=tuple(d["altar"]), W=d["W"], H=d["H"], champs_per_team=d.get("champs_per_team"))
    return _c[path]


def alt1(path):
    alt = set(_load(path)["altar"])
    seen, n = set(), 0
    for a in alt:
        if a in seen:
            continue
        n += 1
        st = [a]
        seen.add(a)
        while st:
            x, y = st.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in alt and q not in seen:
                        seen.add(q)
                        st.append(q)
    return n


def team(path):
    return _load(path).get("champs_per_team")


def onealt(path):
    """1 when the map has at most one altar (binary, for FRESH CLASS bins)"""
    return 1 if alt1(path) <= 1 else 0


def small(path):
    d = _load(path)
    return 1 if d["W"] * d["H"] < 1600 else 0


def team4(path):
    t = team(path)
    return None if t is None else (1 if t <= 4 else 0)


def psa_s1(path):
    """Prism Planner's S1 cell: one altar and area < 1,600"""
    return onealt(path) * small(path)


CLASSES = {"alt1": alt1, "team": team, "nalt": alt1, "cpt": team, "onealt": onealt, "small": small, "team4": team4, "psa_s1": psa_s1}  # nalt/cpt: b1903 names (nalt counts ALTARS, not altar tiles)
