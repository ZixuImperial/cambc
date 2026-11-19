"""gplsub (13 Nov, b2396; b2392's pre-registered subset reads, /data/USER/st/b2392/sub/prereg.md). Draft-time map data only, seat-A view.
Groups, rates and walks as gpl.py (4-connected camp tiles; rates x100 / respawn; walk = 8-dir BFS from each spawn rectangle over tiles that
are not wall / hole / altar, read at the group's first tile or neighbour reachable from both spawns; rho = walk_A / (walk_A + walk_B)).
  rushsub    1 iff gpl_type is 3 or 4 (concentrated centre: compact >= .40 since type 7 exists) AND the richest CENTRE gem group (by gem rate, .40 <= rho <= .60) has walk_A - walk_B <= 2 AND
             its clear crew-rounds <= 40 (sum over its camps: cluster 10, wolf 22, elk 24, golem 41, monolith 62), else 0
  oca_class  1 iff some gem group has no attacker (every camp a cluster), >= 20 gems, both spawn walks <= 8 and |walk_A - walk_B| <= 2
             (b2390 OCA, nova_b2390_oca econ_opening_pick.cc:345-348: n_att == 0, gems >= OCA_G 20, d_home / d_enemy <= OCA_W 8,
             |dh - de| <= OCA_DW 2), else 0
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
from gplfeat import _bfs, _comps, GEMS, GOLD, RESP, DIRS8, CLEAR  # noqa: E402
import math  # noqa: E402

HP = {0: 1350, 1: 2400, 2: 120, 3: 120, 4: 20000, 5: 5000}  # GameRules camp table (:180-185)
GEM_GOLD = 10.0  # one gem = 10 gold (the hot-spot exchange rate)

_spec = importlib.util.spec_from_file_location("mapclass_d_gpl_for_gplsub", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpl.py"))
_gpl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gpl)
_c = {}


def _groups(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    camps = m["camps"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = _bfs(m, list(m["spawnA"]), blocked), _bfs(m, list(m["spawnB"]), blocked)
    out = []
    for pts in _comps(set(camps), ((1, 0), (-1, 0), (0, 1), (0, -1))):
        ty = [camps[p] for p in pts]
        resp = max(RESP.get(t, 50) for t in ty)
        gems = sum(GEMS.get(t, 0) for t in ty)
        w = None
        for (x, y) in pts:
            for dx, dy in ((0, 0),) + DIRS8:
                q = (x + dx, y + dy)
                if q in dA and q in dB:
                    w = (dA[q], dB[q])
                    break
            if w:
                break
        out.append(dict(gems=gems, grate=gems * 100.0 / resp, w=w, clusters_only=all(t in (2, 3) for t in ty),
                        clear=sum(CLEAR.get(t, 20) for t in ty), gold=sum(GOLD.get(t, 0) for t in ty),
                        orate=sum(GOLD.get(t, 0) for t in ty) * 100.0 / resp, hp=sum(HP.get(t, 0) for t in ty),
                        cx=sum(p[0] for p in pts) / len(pts), cy=sum(p[1] for p in pts) / len(pts)))
    _c[path] = out
    return out


def _rush(path):
    """13 Nov (owner: "why do we use a fixed ratio"): continuous draft-time RUSH VALUE in gold units (gems x GEM_GOLD):
      rush_value = P_hold x V_region - home_rate x (walk + clear)
    V_region = capture value (gold + gems x 10) of the centre region (centre groups, rho .40-.60, within Chebyshev 6 of the richest centre gem
    group). A rush commits the whole team (team size from the map), so at even power it arrives with more bodies than a foe that splits:
    P_hold = Econ's calibration (spec_gpl A14, d >= +1 at power ratio .95-1.05) .79 when we reach the region no later than 2 rounds after
    them, else d = 0: .50. clear = sum HP / (team x 30) rounds (early bodies ~30 damage a turn on camps). home_rate = own-zone value per
    round (sum of (gold rate + gem rate x 10) / 100 over rho < .40 groups). Deep's stage A race fit (t_them = their walk only) is NOT used: it
    charges our clear but not theirs, so every heavy centre read P ~ 0. Returns (rush_value, V_region, forgone)."""
    import map26a as _m
    team = max(1, int(_m.load(path).get("champs_per_team", 4)))
    gs = [g for g in _groups(path) if g["w"]]
    rho = lambda g: g["w"][0] / max(1e-9, g["w"][0] + g["w"][1])
    cen = [g for g in gs if 0.40 <= rho(g) <= 0.60 and g["grate"] > 0]
    if not cen:
        return 0.0, 0.0, 0.0
    top = max(cen, key=lambda g: g["grate"])
    reg = [g for g in gs if 0.40 <= rho(g) <= 0.60 and max(abs(g["cx"] - top["cx"]), abs(g["cy"] - top["cy"])) <= 6]
    v = sum(g["gold"] + GEM_GOLD * g["gems"] for g in reg)
    wa = min(g["w"][0] for g in reg)
    wb = min(g["w"][1] for g in reg)
    p_hold = 0.79 if wa <= wb + 2 else 0.50
    clear = sum(g["hp"] for g in reg) / (team * 30.0)
    home = sum((g["orate"] + GEM_GOLD * g["grate"]) / 100.0 for g in gs if rho(g) < 0.40)
    forgone = home * (wa + clear)
    return p_hold * v - forgone, v, forgone


def rush_value(path):
    return _rush(path)[0]


def rush_order(path):
    """1 RUSH->UPGRADE (rush value > 0); 2 UPGRADE->RUSH (rush value <= 0 but the region's value beats the forgone home income); 0 neither."""
    rv, raw, fg = _rush(path)
    return 1 if rv > 0 else 2 if raw > fg else 0


def rushsub(path):
    """13 Nov (owner, no fixed ratio; b2392 prereg addenda 5/6): rush value > 0 on any gpl type (the 3/4 gate and the walk-margin <= 2 /
    clear <= 40 cuts are gone)."""
    return int(_rush(path)[0] > 0)  # 13 Nov (owner "rush maps should be more common"): any gpl type, no 3/4 gate


def oca_class(path):
    for g in _groups(path):
        if g["clusters_only"] and g["gems"] >= 20 and g["w"] and g["w"][0] <= 8 and g["w"][1] <= 8 and abs(g["w"][0] - g["w"][1]) <= 2:
            return 1
    return 0


CLASSES = {"rushsub": rushsub, "oca_class": oca_class, "rush_value": rush_value, "rush_order": rush_order}
