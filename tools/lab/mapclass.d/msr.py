"""msr (b2154, 12 Nov; RC C561 MSR1 + spec_mshc_1112 + spec_hnc_1112 Step 0 classes). Draft-time map features only, no map identity.
Groups = 4-connected camp components (bot M.groups). siege group = holds a monolith (4) or golem (5) (econ_value.cc:86).
siege_map = open_gem_share < .15 (econ_value.cc:119; same as ogs.py).
  msr     1 when siege_map and some siege group pays >= 100 gems (MSR1 class).
  mshc    number of sides (0-2) for which: siege_map and an own-half monolith group holds >= half of that side's own-half gems
          (own half: walk dA/(dA+dB) < .5 for A; mono_own.py's walk model).
  mshc3   number of sides (0-2), team size 3, not siege_map, with an own-half monolith group (MSH-C's second count bin).
  hnc_a   1 when not siege_map and some walkable group has a golem, no monolith, gems >= 60, HP >= 5,000 and gems < 100 or HP < 9,000.
  spawnecon  number of sides (0-2) for which MCL_BIT_SPAWNECON holds (plan_map_classes.cc spawn_econ_dominant: a monolith group
          within 3 of that side's spawn rectangle, spawn-to-spawn walk >= 50 (walls/holes block), gems of groups near neither spawn
          <= 10% of the biggest such home group).
  nsg     sides (0-2) with an NSG-class group (non-siege map; heavy non-monolith group >= 30 gems with an elk or golem, walk ratio <= .55,
          walk from that side's spawn <= 7 = reach + 3); nsg_narrow: own-side golem / 2+ elk group with a camp within 3 of a spawn tile.
  hnc_b   1 when not siege_map and some group has >= 3 elk, no golem/monolith, and is nearer one side's spawn (walk ratio != .5)."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
HP = {0: 1350, 1: 2400, 2: 120, 3: 120, 4: 20000, 5: 5000}
_c = {}


def _bfs(d, src):
    W, H = d['W'], d['H']
    block = set(d['wall']) | set(d['hole']) | set(d['camps'])
    dist = {p: 0 for p in src}
    q = deque(src)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    return dist


def _calc(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    camps = d['camps']
    da, db = _bfs(d, list(d['spawnA'])), _bfs(d, list(d['spawnB']))
    seen, gs = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        ty = [camps[p] for p in comp]
        ga = gb = None
        for x, y in comp:
            for dx, dy in N8:
                p = (x + dx, y + dy)
                if p in da:
                    ga = da[p] if ga is None else min(ga, da[p])
                if p in db:
                    gb = db[p] if gb is None else min(gb, db[p])
        r = None if ga is None or gb is None else ga / max(1, ga + gb)
        gs.append(dict(gems=sum(mapfeat.GEMS[t] for t in ty), hp=sum(HP[t] for t in ty), mono=ty.count(4), golem=ty.count(5),
                       elk=ty.count(1), r=r, ga=ga, gb=gb, comp=comp))
    tg = sum(g['gems'] for g in gs)
    sg = sum(g['gems'] for g in gs if g['mono'] + g['golem'])
    siege = tg > 0 and (tg - sg) / tg < 0.15
    out = dict(msr=int(siege and any(g['mono'] + g['golem'] and g['gems'] >= 100 for g in gs)))
    nm = n3 = 0
    for side in (0, 1):
        own = [g for g in gs if g['r'] is not None and ((g['r'] < 0.5) if side == 0 else (g['r'] > 0.5))]
        og = sum(g['gems'] for g in own)
        if siege and og > 0 and any(g['mono'] and 2 * g['gems'] >= og for g in own):
            nm += 1
        if not siege and int(d.get('champs_per_team', 0)) == 3 and any(g['mono'] for g in own):
            n3 += 1
    out['mshc'] = nm
    out['mshc3'] = n3
    out['hnc_a'] = int(not siege and any(g['r'] is not None and g['golem'] and not g['mono'] and g['gems'] >= 60 and g['hp'] >= 5000 and
                                          (g['gems'] < 100 or g['hp'] < 9000) for g in gs))
    out['hnc_b'] = int(not siege and any(g['r'] is not None and g['elk'] >= 3 and not g['mono'] and not g['golem'] and g['r'] != 0.5
                                          for g in gs))
    def rect(sp):
        xs = [p[0] for p in sp]; ys = [p[1] for p in sp]
        return (min(xs), min(ys), max(xs), max(ys))
    def rd(r, p):
        return max(max(0, r[0] - p[0], p[0] - r[2]), max(0, r[1] - p[1], p[1] - r[3]))
    ra, rb = rect(list(d['spawnA'])), rect(list(d['spawnB']))
    W, H = d['W'], d['H']
    blk = set(d['wall']) | set(d['hole'])
    dist = {p: 0 for p in d['spawnA']}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in blk and p not in dist:
                dist[p] = dist[(x, y)] + 1
                q.append(p)
    s2s = min([dist[p] for p in d['spawnB'] if p in dist] or [10 ** 6])
    se = 0
    comps = []
    seen2 = set()
    for c in sorted(camps):
        if c in seen2:
            continue
        comp, st = [], [c]
        seen2.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for qq in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if qq in camps and qq not in seen2:
                    seen2.add(qq)
                    st.append(qq)
        comps.append(comp)
    for side in (0, 1):
        mine_r, th_r = (ra, rb) if side == 0 else (rb, ra)
        home = oth = 0
        for comp in comps:
            gm = sum(mapfeat.GEMS[camps[p]] for p in comp)
            mine = any(rd(mine_r, p) <= 3 for p in comp); theirs = any(rd(th_r, p) <= 3 for p in comp)
            if mine and any(camps[p] == 4 for p in comp):
                home = max(home, gm)
            if not mine and not theirs:
                oth += gm
        if home > 0 and s2s < 10 ** 6 and s2s >= 50 and oth * 100 <= home * 10:
            se += 1
    out['spawnecon'] = se
    nw = nn = 0
    for side in (0, 1):
        spn = set(d['spawnA'] if side == 0 else d['spawnB'])
        w = n2 = False
        for g in gs:
            if g['r'] is None or siege or g['mono'] or not (g['golem'] or g['elk']) or g['gems'] < 30:
                continue
            rr = g['r'] if side == 0 else 1 - g['r']
            dh = g['ga'] if side == 0 else g['gb']
            if rr <= 0.55 and dh <= 7:
                w = True
            if rr < 0.5 and (g['golem'] or g['elk'] >= 2) and any(max(abs(x - a), abs(y - b)) <= 3 for (x, y) in g['comp'] for (a, b) in spn):
                n2 = True
        nw += w; nn += n2
    out['nsg'] = nw
    out['nsg_narrow'] = nn
    _c[path] = out
    return out


CLASSES = {k: (lambda kk: (lambda path, _g=None: _calc(path)[kk]))(k) for k in ("msr", "mshc", "mshc3", "hnc_a", "hnc_b", "spawnecon", "nsg", "nsg_narrow")}
