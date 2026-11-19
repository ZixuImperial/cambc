"""ciz (b2339, 12 Nov; spec_ciz_1112.md): the gem-starved class for CIZ (C&I's seat on kill-gold maps).
ciz_gs = all camp gems on the map (wolf 4, elk 15, gem 7, gold 0, monolith 200, golem 36 per camp) / (2 x champs_per_team): the
         bot's F_GEM_TOTAL_PC (draft_fit_features.cc, monoliths included).
ciz    = 1 when ciz_gs <= the b2339 stock cut for the team size (T3 12.33 natural break; T4 9.0 and T5 9.8 bottom 5%), else 0.
-> --class 'ciz:>=1'. Draft-time map features only, no map identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
_CUT = {3: 12.33, 4: 9.0, 5: 9.8}


def ciz_gs(path):
    d = map26a.load(path)
    k = int(d["champs_per_team"])
    return sum(_GEM.get(t, 0) for t in d["camps"].values()) / (2.0 * k)


def ciz(path):
    k = int(map26a.load(path)["champs_per_team"])
    return 1 if k in _CUT and ciz_gs(path) <= _CUT[k] + 1e-6 else 0


CLASSES = {"ciz_gs": ciz_gs, "ciz": ciz}
