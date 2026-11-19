"""stellar: Stellar's map classes for STM's class reads (b1813; CI Planner topdraft_tsr_1110 and spec_mod_1110 amendment 1). Draft-time map data only.
  stellar_sm : 1 when area <= 1500, spawn-centre Chebyshev distance (s2s) <= 20 and camp tiles per 100 tiles >= 6 (SBG's Stellar maps: small,
               close, camp-dense; camps relaxed from >= 90 to density by the CI Planner, SBG's maps 8.7), else 0
  stellar_cd : 1 when gem/gold cluster camp tiles >= 38 and >= .65 of camp tiles (CLUSTER-DENSE), else 0"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapclass  # noqa: E402
import genmaps as G  # noqa: E402


def stellar_sm(path, _m=None):
    d = G.map26a.load(path)
    area = d["W"] * d["H"]
    dens = 100.0 * len(d["camps"]) / max(1, area)
    return 1 if area <= 1500 and mapclass._s2s(path) <= 20 and dens >= 6.0 else 0


def stellar_cd(path, _m=None):
    camps = G.map26a.load(path)["camps"]  # {tile: type}; 2 gem cluster, 3 gold cluster
    ncl = sum(1 for t in camps.values() if t in (2, 3))
    return 1 if ncl >= 38 and ncl >= 0.65 * max(1, len(camps)) else 0


CLASSES = {"stellar_sm": stellar_sm, "stellar_cd": stellar_cd}
