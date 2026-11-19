"""ogs (12 Nov, Builder/Planner: JKC's fuel re-read banks w_jackpot2 maps that are NOT siege maps): open_gem_share mirrors the bot's
open_gem_share (econ_comms_fields.cc:108, v801): gems in camp groups with no monolith or golem / all gems (1.0 with no gems). The bot's
siege_map() is open_gem_share < .15 (econ_value.cc:119), so 'not a siege map' is open_gem_share:>=0.15. Groups = 4-connected camp
components, as mapfeat (and the bot's M.groups) build them; siege_group = n_mono + n_golem > 0 (econ_value.cc:86). Camp kinds as
mapfeat: 4 = monolith (200 gems), 5 = golem (36). Draft-time map features only, no map identity."""
import os
import sys

sys.path.insert(0, "/homes/USER/cambc/tools/lab")
import map26a  # noqa: E402
import mapfeat  # noqa: E402

SIEGE_KINDS = (4, 5)  # monolith, golem


def open_gem_share(path):
    camps = map26a.load(path)["camps"]
    seen, allg, open_ = set(), 0, 0
    for p in sorted(camps):
        if p in seen:
            continue
        g, st = [p], [p]
        seen.add(p)
        while st:
            c = st.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n in camps and n not in seen:
                    seen.add(n)
                    g.append(n)
                    st.append(n)
        gems = sum(mapfeat.GEMS[camps[q]] for q in g)
        allg += gems
        if not any(camps[q] in SIEGE_KINDS for q in g):
            open_ += gems
    return round(open_ / allg, 4) if allg > 0 else 1.0


def siege_map(path):
    """1 when open_gem_share < .15 (the bot's siege_map(), econ_value.cc:119), else 0."""
    return 1.0 if open_gem_share(path) < 0.15 else 0.0


CLASSES = {"open_gem_share": open_gem_share, "siege_map": siege_map}
