"""nointer: 1 when the two teams can never meet (owner via Path Finding 11 Nov: enemy-less farming-race maps, gencruel w_nointer),
else 0. Team A's reach under the engine rules (walk, dash, one crystal jump: genmaps.team_reach) never touches the mirror of a tile it
reaches. -> stratmaps --class 'nointer:>=1'. Tool Builder 11 Nov."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genmaps as G  # noqa: E402


def nointer(path):
    d = G.map26a.load(path)
    W, H, s = d["W"], d["H"], d["symmetry"]
    r = G.team_reach(d, True)
    return 0.0 if any(G.map26a.mirror(s, W, H, *p) in r for p in r) else 1.0


CLASSES = {"nointer": nointer}
