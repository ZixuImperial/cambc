"""voc: VV Redesign VOCr class (spec_voc_1111 amendment; b1900 vocfeat.py port of VOP decide(), matches the bot 212/212). Tool Builder 11 Nov.
  voc_n    = b1900's 'rich' count (pre-registered lead, spec split 3) from seat A: gold >= 100, no monolith or golem tile, walk from home <= 24 (no contest term)
  voc_rich = 1 when voc_n >= 4 (both seats give the same value: checked by b1900)      -> --class 'voc_rich:>=1'"""
import sys
from collections import deque
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a
HP = {0: 1350, 1: 2400, 2: 120, 3: 120, 4: 20000, 5: 5000}
STR = {0: 20, 1: 60, 2: 0, 3: 0, 4: 200, 5: 120}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
# basic = str*(8+reset)/8, spells/8 (GameRules stats)
DPS = {'cassi': 30 + 200 / 8, 'issac': 45 * 9 / 8, 'ryth': 45 * 9 / 8 + 100 / 8, 'vesper': 35 * 9 / 8, 'prism': 35 + 225 / 8,
       'stellar': 30 + 289 / 8, 'vendetta': 65 * 9 / 8, 'marcella': 40 * 9 / 8 + 120 / 8, 'tavi': 45 * 9 / 8 + 176 / 8,
       'willow': 55 * 9 / 8, 'ren': 35 + 110 / 8, 'varg': 50 * 9 / 8, 'heart': (30 + 120 / 8) * 1.12}
TANK = ['heart', 'varg', 'ryth', 'marcella', 'ren', 'issac', 'vendetta', 'vesper', 'tavi', 'stellar', 'willow', 'prism', 'cassi']
GMIN, DMAX, CON, TMAX, CREW = 100, 24, 55, 45, 4
N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]


def cheb(p, q):
    return max(abs(p[0] - q[0]), abs(p[1] - q[1]))


def bfs(d, roots, enemy):
    W, H = d['W'], d['H']
    block = set(d['wall']) | set(d['hole']) | set(d['altar']) | set(enemy)
    dist = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        c = q.popleft()
        for dx, dy in N8:
            n = (c[0] + dx, c[1] + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in dist and n not in block:
                dist[n] = dist[c] + 1
                q.append(n)
    return dist


def groups(d):
    camps = d['camps']
    seen, out = set(), []
    for c in camps:  # map26a camp order
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
        comp.sort(key=lambda p: list(camps).index(p))
        ty = [camps[p] for p in comp]
        best, anc = -1, comp[0]
        for p, t in zip(comp, ty):
            if STR[t] > best:
                best, anc = STR[t], p
        out.append(dict(m=comp, gold=sum(GOLD[t] for t in ty), gems=sum(GEMS[t] for t in ty), hp=sum(HP[t] for t in ty),
                        mono=ty.count(4), golem=ty.count(5), elk=ty.count(1), anchor=anc))
    return out


_vc = {}


def voc_n(path):
    if path in _vc:
        return _vc[path]
    d = map26a.load(path)
    G = groups(d)
    home, enemy = d['spawnA'], d['spawnB']
    fh, fe = bfs(d, list(home), enemy), bfs(d, list(enemy), home)
    n = 0
    for g in G:
        dh = min((fh[p] for p in g['m'] if p in fh), default=None)
        de = min((fe[p] for p in g['m'] if p in fe), default=None)
        con = (dh / max(1, dh + de)) if dh is not None and de is not None else (0.0 if dh is not None else 1.0)
        if g['gold'] >= GMIN and not g['mono'] and not g['golem'] and dh is not None and dh <= DMAX:  # b1900 'rich' (spec split 3): NO contest term
            n += 1
    _vc[path] = n
    return n


def voc_rich(path):
    return 1 if voc_n(path) >= 4 else 0


CLASSES = {"voc_n": voc_n, "voc_rich": voc_rich}
