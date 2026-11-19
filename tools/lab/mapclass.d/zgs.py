"""zgs (b2370 VGL bit 64, Amendment 6; draft-time map features only, no map identity).
  zgs_share = share of the map's gems that sit in zero-gold groups (gold 0, gems > 0); groups = cardinally connected camps (GR:173),
              all groups (Deep zerogold SPLIT definition, condor-work/readers/deep_zerogold/reader.py), camp table as cltfcls.
  zgs_n     = number of zero-gold gem groups.
  zgs       = 1 when zgs_share >= .5 and zgs_n >= 4 (= the bot's vgl_zgs_class(), econ_value.cc)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
_c = {}


def _feat(path):
    if path in _c:
        return _c[path]
    camps = map26a.load(path)["camps"]
    seen = set()
    tot = zg = nz = 0
    for c in camps:
        if c in seen:
            continue
        st = [c]
        seen.add(c)
        gold = gems = 0
        while st:
            x, y = st.pop()
            gold += GOLD.get(camps[(x, y)], 0)
            gems += GEMS.get(camps[(x, y)], 0)
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        tot += gems
        if gold <= 0 and gems > 0:
            zg += gems
            nz += 1
    r = (zg / tot if tot > 0 else 0.0, nz)
    _c[path] = r
    return r


def zgs_share(path):
    return _feat(path)[0]


def zgs_n(path):
    return _feat(path)[1]


def zgs(path):
    s, n = _feat(path)
    return 1 if s >= 0.5 and n >= 4 else 0


CLASSES = {"zgs": zgs, "zgs_share": zgs_share, "zgs_n": zgs_n}
