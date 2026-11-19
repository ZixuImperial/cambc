"""siegemono (13 Nov, TB for Econ SAX; spec condor-work/reports/analysts/spec_sax_1113.md, RC C976): a siege map with a monolith attack group.
siegemono = 1 when (a) the open gem share < .15 (gems of 4-connected camp groups with no monolith and no golem tile / gems of all groups;
Econ's siege_map() / open_gem_share, econ_comms_fields.cc:108) AND (b) at least one group holds a monolith and >= 2 attacker camps (one camp per tile, as the engine's stored_camps)
(monolith + golem + elk + wolf), as condor-work/econ_tools/siegecls_reader.py. open_share = (a)'s share (float, None without gems)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WOLF, ELK, GEM, GOLD, MONO, GOLEM = 0, 1, 2, 3, 4, 5
ATT = (MONO, GOLEM, ELK, WOLF)
_cache = {}


def _read(path):
    if path in _cache:
        return _cache[path]
    import genmaps as G
    import mapfeat
    camps = G.map26a.load(path)["camps"]
    seen, tot, opn, mono_att = set(), 0, 0, False
    for c in camps:
        if c in seen:
            continue
        st, gm, ty, tiles = [c], 0, [], []
        seen.add(c)
        while st:
            x, y = st.pop()
            t = camps[(x, y)]
            ty.append(t)
            tiles.append((x, y))
            gm += mapfeat.GEMS[t]
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        tot += gm
        if MONO not in ty and GOLEM not in ty:
            opn += gm
        # 13 Nov: the engine's camp groups are the 4-connected camp tiles (ngroups.py = the bot's M.ng) and each tile is one camp (the map's
        # stored_camps list holds one entry per tile), so n_att (mapinfo.cc:257-264, camps with str > 0) = attacker TILES in the group
        if MONO in ty and sum(1 for t in ty if t in ATT) >= 2:
            mono_att = True
    r = (opn / tot if tot else None, mono_att)
    _cache[path] = r
    return r


def _camps(camps, tiles):
    """13 Nov (Econ: n_att counts CAMPS, as mapinfo GroupI): connected attacker tiles of one type = one camp."""
    ts, seen, n = set(tiles), set(), 0
    for c in tiles:
        if c in seen or camps[c] not in ATT:
            continue
        n += 1
        st = [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in ts and q not in seen and camps[q] == camps[c]:
                    seen.add(q)
                    st.append(q)
    return n


def open_share(path, _g=None):
    return _read(path)[0]


def siegemono(path, _g=None):
    s, m = _read(path)
    return 1 if s is not None and s < 0.15 and m else 0


CLASSES = {"siegemono": siegemono, "open_share": open_share}
