"""ownmono (13 Nov, TB for Econ's SRO re-read): >= 1 camp group (4-connected camp tiles, one camp per tile, the engine's groups as siegemono)
holding a monolith tile whose contest d_me / (d_me + d_foe) <= .45 for either seat (8-way walk from each spawn, walls / holes / altars
blocked, camps passable, as cltfcls; foe unreachable -> 0). Class 'ownmono:>=1'. Draft-time, seat-free."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402
import cltfcls  # noqa: E402

MONO = 4


def ownmono(path, _g=None):
    m = map26a.load(path)
    W, H, camps = m["W"], m["H"], m["camps"]
    block = set(m["wall"]) | set(m["hole"]) | set(m["altar"])
    dA, dB = cltfcls._bfs(W, H, block, m["spawnA"]), cltfcls._bfs(W, H, block, m["spawnB"])
    seen = set()
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        if not any(camps[t] == MONO for t in comp):
            continue
        a = min((dA[t] for t in comp if t in dA), default=None)
        b = min((dB[t] for t in comp if t in dB), default=None)
        for me, foe in ((a, b), (b, a)):
            if me is not None and (0.0 if foe is None else me / max(1, me + foe)) <= .45:
                return 1
    return 0


CLASSES = {"ownmono": ownmono}
