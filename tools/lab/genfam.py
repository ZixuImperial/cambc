#!/usr/bin/env python3
"""genfam.py - gen_nf_<fam>_NNN: NEW map families with features the older generators (almost) never produce (1 Nov,
mapgen1101; owner: "add some more different features and pathological maps"). Report: condor-work/reports/analysts/
mapgen_1101.md (inventory of the old families' coverage, validation games, bug leads).

Every map is mirror-symmetric (the engine mirrors each wall, hole, bush, altar and camp from one stored copy, so both
teams get the same map: GameRules.md:141-167), 30..100 a side (the rules' range; 'brawl' sits at the bottom), 3-5 a
side, spawn area 9..16 tiles (3x3/4x3/4x4/5x2: a 4x2 spawn fails at game start, maps.md), spawns joined on foot
(camps passable), >= 1 walkable altar (except where the family says), <= 255 stored camp pairs, >= 40 reachable gems
(except goldonly). It is built with the engine's MapBuilder (genmaps.build_and_check), decoded back and checked tile
for tile, then checked for its family's property on the decoded map (mapfeat + extfeat()).

families (gen_nf_<fam>_NNN, seeds 91,000,000 + 1,000,000 k + 1000 i + attempt, k = position in FAMS):
  vault    a normal economy + 10-36 vault groups nobody can ever capture (genfuel's sealed/lake/block vaults, plus a few
           dash/crystal near-misses), anywhere on the map: pathing and fuel stress (owner's earlier question)
  isle     6-16 one-to-nine-tile islands in a 1-tile hole moat (dash only; ~15% a 2-tile moat: crystal only), most with a
           camp; a 1x1 island holds one camp (melee bodies cannot hit it: GameRules.md:159 no landing on a hole), some
           maps an island altar too
  road     one long winding road: a spanning-tree maze of 2-3 wide roads on each half, joined across the axis once,
           spawn at the far end: walk >= 2.5 x Chebyshev spawn distance (00swirl, 00road-of-riches)
  corr     corridor-only: a 1-2 wide maze with a few loops and small rooms (altars and groups sit in rooms/dead ends)
  heavy    only elk / golem / monolith camps (no clusters, no wolves)
  mgate    every altar gated by monolith or golem camps (adj_gate: the tribute tiles are walls/holes + 1-2 heavy camps;
           ring_gates: a wall ring with heavy camps in its gaps)
  gemonly  only gem clusters: no camp gold at all (kill gold only)
  goldonly only gold clusters: no gems, no tribute possible: every game runs to r2000 and gold earned decides
  huge     95-100 a side, 3-6 groups a side, long spawns
  brawl    30-34 a side, spawns 2-8 tiles apart, 4-5 a side
  bush     40-80% of the walkable tiles are bush
  crystal  6-16 crystal-only pockets (a floor ring inside two hole rings: no walk, no 2-step dash) and a few dash ones
  zone     every group in one band: near the spawns (home), in the middle third (mid) or at the centre (center)
  skew     rotational maps whose big walls/holes/bushes straddle the centre (each side looks different; still fair)
  hoard    one self-symmetric central group of 20-60 camps (gem core, elk/golem rim) holding >= 50% of the gems
  altmany  6-12 altars a side
  altfar   one far altar: a shared one far from both spawns, or each side's farthest own tile
  block    a wall across the mirror axis whose 1-3 gaps are plugged by camp groups: the spawns meet only through camps
           (wolf / elk / golem / gold / monolith plugs that respawn)

usage:
  nice -n 10 python3 -I tools/lab/genfam.py FAM [FAM ...] --n N [--start K] [--install] [--show]
  nice -n 10 python3 -I tools/lab/genfam.py FAM --seed S --tmp DIR    one never-saved map (OTF style) in DIR
  python3 -I tools/lab/genfam.py --list
Outputs: /data/USER/genmaps_nf/<NAME>.{map26a,json,meta.json,txt}, maplist_<fam>.txt, maplist.txt (all);
--install copies the .map26a into /data/USER/work301/maps (abl.sh, condab, cqbatch find maps there by name).
tools/lab/freshmaps.py samples these families (and the older ones) for the fresh-map leg.
"""
import json
import os
import random
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import genfuel as F  # noqa: E402
import mapfeat  # noqa: E402

PREFIX, SEED0, OUT, INSTALL = 'gen_nf_', 91000000, '/data/USER/genmaps_nf', '/data/USER/work301/maps'
# 12 Nov ~14:2xZ (owner; creators: tournament maps always have gems, "no point testing 0 gem maps"): 'goldonly' (no gems at all) is
# out of the default mix; its builder stays for an explicit request
FAMS = ['vault', 'isle', 'road', 'corr', 'heavy', 'mgate', 'gemonly', 'huge', 'brawl', 'bush', 'crystal',
        'zone', 'skew', 'hoard', 'altmany', 'altfar', 'block']
FLOOR, WALL, HOLE, BUSH, ALTAR = G.FLOOR, G.WALL, G.HOLE, G.BUSH, G.ALTAR
WOLF, ELK, GEM, GOLD, MONO, GOLEM = G.WOLF, G.ELK, G.GEM, G.GOLD, G.MONO, G.GOLEM
N8, N4 = G.N8, G.N4

# ---------------------------------------------------------------- module-level patches (forkserver workers re-import)
_tpl0 = G.tpl


def _tpl(name, rng):
    if name == 'gem1':
        return [(0, 0, GEM)]
    if name == 'gold1':
        return [(0, 0, GOLD)]
    if name == 'gem_row':
        n, h = rng.randint(2, 6), rng.random() < 0.5
        return [((i, 0) if h else (0, i)) + (GEM,) for i in range(n)]
    if name == 'golem_pair':
        return [(0, 0, GOLEM), (1, 0, GOLEM)] if rng.random() < 0.5 else [(0, 0, GOLEM), (0, 1, GOLEM)]
    if name == 'heavy_pack':
        c = G.blob(rng, rng.randint(2, 4))
        return [p + (rng.choice([ELK, ELK, GOLEM]),) for p in c]
    if name == 'elk_trio':
        return [(x, y, ELK) for x, y in G.blob(rng, 3)]
    return _tpl0(name, rng)


G.tpl = _tpl
G.MIXES.setdefault('nf_heavy', {'elk': 3, 'elk_pair': 2, 'elk_trio': 1, 'golem': 2, 'golem_pair': 1, 'heavy_pack': 2})
G.MIXES.setdefault('nf_gem', {'gem_patch': 4, 'gem_field': 2, 'gem_row': 2, 'gem1': 1})
G.MIXES.setdefault('nf_gold', {'gold_row': 3, 'gold_patch': 3, 'gold1': 1})
NORMAL_MIXES = ['balanced', 'balanced', 'cluster_heavy', 'elk_heavy', 'wolf_packs', 'golems', 'gem_poor', 'gold_rich']


# ---------------------------------------------------------------- features
def groups_of(camps):
    gid, out = {}, []
    for p in sorted(camps):
        if p in gid:
            continue
        g, st = [p], [p]
        gid[p] = len(out)
        while st:
            c = st.pop()
            for dx, dy in N4:
                n = (c[0] + dx, c[1] + dy)
                if n in camps and n not in gid:
                    gid[n] = len(out)
                    g.append(n)
                    st.append(n)
        out.append(g)
    return out


def extfeat(d):
    """Extras beyond mapfeat's columns (inventory 1 Nov): cheb (Chebyshev spawn gap), wind (s2s walk / cheb), nbr (mean
    walkable 8-neighbours of a walkable tile: 7.5 open .. ~3 corridors), cblk ('cut' = the spawns meet only through
    camps, else s2s with camps blocking / s2s), top (biggest group's gem share), ncamp, maxg (largest group), altacc
    (team A's altar access class: open / ring / adjgate / mixed / none)."""
    W, H = d['W'], d['H']
    bad = set(d['wall']) | set(d['hole']) | set(d['altar'])
    spA, spB, camps = d['spawnA'], d['spawnB'], d['camps']

    def bfs(blockc):
        dist = {s: 0 for s in spA}
        dq = deque(spA)
        while dq:
            c = dq.popleft()
            for dx, dy in N8:
                n = (c[0] + dx, c[1] + dy)
                if (n in dist or not (0 <= n[0] < W and 0 <= n[1] < H) or n in bad or n in spB
                        or (blockc and n in camps)):
                    continue
                dist[n] = dist[c] + 1
                dq.append(n)
        return dist

    def s2s(dist):
        adj = [dist[n] for n in dist if any((n[0] + dx, n[1] + dy) in spB for dx, dy in N8)]
        return min(adj) + 1 if adj else None
    wA = bfs(False)
    s, sb = s2s(wA), s2s(bfs(True))
    cheb = min(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a in spA for b in spB)
    nb = [sum(1 for dx, dy in N8 if (p[0] + dx, p[1] + dy) in wA) for p in wA]
    gg = [sum(mapfeat.GEMS[camps[p]] for p in g) for g in groups_of(camps)]
    return dict(cheb=cheb, wind=round(s / max(1, cheb), 2) if s else None, nbr=round(sum(nb) / max(1, len(nb)), 2),
                cblk='cut' if (s and sb is None) else (round(sb / s, 2) if s else None),
                top=round(max(gg) / max(1, sum(gg)), 2) if gg else 0, ncamp=len(camps),
                maxg=max((len(g) for g in groups_of(camps)), default=0),
                altacc=G.altar_access(d)['A'] if d['altar'] else 'none')


# ---------------------------------------------------------------- shared helpers
def base_rec(r, **over):
    rec = dict(kind='normal', checks=2, size=r.choice(['S', 'M', 'M', 'L', 'L']),
               aspect=r.choice(['square', 'square', 'wide', 'tall']), T=r.choice([3, 4, 5, 5]), sym=r.choice([0, 1, 2, 2]),
               style=r.choice(['open', 'corridors', 'maze', 'holes', 'bushbelt', 'mixed']), mix=r.choice(NORMAL_MIXES),
               mono=r.choice([0, 0, 0, 1, 1, 2]), altar=r.choice(['near', 'far', 'central', 'shared', 'shared', 'many']),
               spawn=r.choice(['long', 'long', 'medium', 'medium', 'short']))
    rec.update(over)
    return rec


def n_side_of(m, rng):
    return max(3, min(16, round((m.W * m.H / 2) ** 0.5 * rng.uniform(0.17, 0.4))))


def drop_all_groups(m):
    while m.groups:
        G.drop_group(m)
    m.camp.clear()


def remove_group(m, tiles):
    for x, y in tiles:
        m.camp.pop((x, y), None)
        m.camp.pop(m.mir(x, y), None)
    m.groups = [(t, k) for t, k in m.groups if t is not tiles]


def thin_groups(m, rng, keep):
    gs = [t for t, k in m.groups]
    rng.shuffle(gs)
    while len(m.groups) > keep and gs:
        remove_group(m, gs.pop())


def free_box(m, box):
    """No camp, altar, protected or spawn-near tile in or next to box (and box not touching its mirror image)."""
    bs = set(box)
    for x, y in box:
        if not m.inb(x, y) or (x, y) in m.protect or m.dspawn(x, y) < 3 or m.get(x, y) == ALTAR:
            return False
        for dx, dy in N8 + [(0, 0)]:
            n = (x + dx, y + dy)
            if n in m.camp or (m.inb(*n) and m.get(*n) == ALTAR):
                return False
    return not any(m.mir(*p) in bs for p in box)


# ---------------------------------------------------------------- family builders: build(rec, seed) -> Map
def b_normal(rec, seed):
    return G.generate(rec, seed)


def b_vault(rec, seed):
    m = G.generate(rec, seed)
    F.KINDS_UN, F.KINDS_NEAR, F.BIG = ['sealed', 'sealed', 'lake', 'lake', 'block'], ['dash', 'crystal', 'detour'], False
    vr = random.Random(seed * 7 + 3)
    m.nf_vaults = F.add_vaults(m, vr, rec['nv'], rec['nnear'])
    return m


def my_island(m, rng, w, h, moat):
    for _ in range(300):
        x0, y0 = rng.randint(moat + 1, m.W - w - moat - 1), rng.randint(moat + 1, m.H - h - moat - 1)
        box = [(x, y) for x in range(x0 - moat - 1, x0 + w + moat + 1) for y in range(y0 - moat - 1, y0 + h + moat + 1)]
        if not free_box(m, box):
            continue
        for x, y in box:
            d = max(max(x0 - x, x - (x0 + w - 1), 0), max(y0 - y, y - (y0 + h - 1), 0))
            m.put(x, y, FLOOR if d == 0 or d > moat else HOLE)
            if d <= moat:
                m.prot(x, y)
        return [(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)]
    return None


def b_isle(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 13 + 5)
    m.nf_isl = []
    for i in range(rec['nisl']):
        w, h = rng.choice([(1, 1), (1, 1), (1, 2), (2, 1), (2, 2), (2, 2), (2, 3), (3, 2), (3, 3)])
        moat = 2 if rng.random() < 0.15 else 1
        isl = my_island(m, rng, w, h, moat)
        if not isl:
            continue
        names = ['gem1', 'gold1', 'wolf', 'gem1'] if len(isl) == 1 else ['gem_patch', 'wolf', 'elk', 'gem1', 'elk_guard', 'gold1']
        n = G.place_in_island(m, rng, isl, names, 1 if len(isl) <= 2 else rng.randint(1, 2))
        m.nf_isl.append((w, h, moat, n))
    if rec['isl_altar']:
        isl = my_island(m, rng, 3, 3, 1)
        if isl:
            c = isl[4]
            G.add_altar(m, rng, c[0], c[1], double=False)
    G.repair(m, rng, True)
    return m


def gen_maze(rec, seed):
    """Maze terrain built on team A's half (a coarse grid of cw-wide cells, wt-thick walls, a DFS spanning tree, extra
    loops with p_loop, rooms = 2x2 cell blocks), mirrored by Map.put, joined across the axis at `cross` cells; the spawn
    goes into the cell farthest (in the tree) from the first crossing."""
    rng = random.Random(seed)
    W, H = G.dims(rng, rec['size'], rec['aspect'])
    if rec.get('dims'):
        W, H = rec['dims']
    m = G.Map(W, H, rec['sym'], rec['T'])
    for i in range(W * H):
        m.g[i] = WALL
    cw, wt = rec['cw'], rec['wt']
    step = cw + wt

    def side(x, y):
        return (x - (W - 1) / 2) if m.sym == 0 else (y - (H - 1) / 2)
    nx, ny = (W - 2) // step, (H - 2) // step

    def tiles(i, j):
        x, y = 1 + i * step, 1 + j * step
        return [(x + a, y + b) for a in range(cw) for b in range(cw)]
    cells = {(i, j) for i in range(nx) for j in range(ny)
             if all(m.inb(x, y) and side(x, y) <= -1 for x, y in tiles(i, j))}
    if len(cells) < 8:
        raise RuntimeError('maze too small')
    open_ = set()

    def carve(a, b):
        (i, j), (p, q) = a, b
        x, y = 1 + min(i, p) * step, 1 + min(j, q) * step
        if i != p:
            open_.update((x + cw + t, y + u) for t in range(wt) for u in range(cw))
        else:
            open_.update((x + u, y + cw + t) for t in range(wt) for u in range(cw))
    for c in cells:
        open_.update(tiles(*c))
    start = rng.choice(sorted(cells))
    seen, st, adj = {start}, [start], {c: [] for c in cells}
    while st:
        cur = st[-1]
        nb = [(cur[0] + dx, cur[1] + dy) for dx, dy in N4]
        nb = [n for n in nb if n in cells and n not in seen]
        if not nb:
            st.pop()
            continue
        n = rng.choice(nb)
        carve(cur, n)
        adj[cur].append(n)
        adj[n].append(cur)
        seen.add(n)
        st.append(n)
    for i, j in sorted(cells):
        for dx, dy in ((1, 0), (0, 1)):
            n = (i + dx, j + dy)
            if n in cells and n not in adj[(i, j)] and rng.random() < rec['p_loop']:
                carve((i, j), n)
                adj[(i, j)].append(n)
                adj[n].append((i, j))
    for _ in range(rec['rooms']):
        i, j = rng.choice(sorted(cells))
        blk = [(i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)]
        if all(b in cells for b in blk):
            x, y = 1 + i * step, 1 + j * step
            open_.update((x + a, y + b) for a in range(2 * cw + wt) for b in range(2 * cw + wt))
            for a in blk:
                for b in blk:
                    if a != b and abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 and b not in adj[a]:
                        adj[a].append(b)
    # crossings: the cells whose neighbour towards the axis is not an A cell
    toward = (1, 0) if m.sym == 0 else (0, 1)
    edge = sorted(c for c in cells if (c[0] + toward[0], c[1] + toward[1]) not in cells)
    cross = rng.sample(edge, min(len(edge), rec['cross']))
    for c in cross:
        x, y = tiles(*c)[0]
        mx, my = m.mir(x, y)
        for p in G.line_cells(x, y, mx, my):
            open_.update((p[0] + a, p[1] + b) for a in range(cw) for b in range(cw))
    for x, y in open_:  # Map.put writes the mirror tile too
        if m.inb(x, y):
            m.put(x, y, FLOOR)
    # spawn: the cell farthest in the tree from the first crossing
    dist, dq = {cross[0]: 0}, deque([cross[0]])
    while dq:
        c = dq.popleft()
        for n in adj[c]:
            if n not in dist:
                dist[n] = dist[c] + 1
                dq.append(n)
    far = sorted(dist, key=lambda c: -dist[c])[:max(1, len(dist) // 12)]
    T = rec['T']
    sw, sh = {3: [(3, 3)], 4: [(3, 3), (4, 3)], 5: [(3, 3), (4, 4), (5, 2)]}[T][rng.randrange(1 if T == 3 else 2 if T == 4 else 3)]
    for _ in range(60):
        c = rng.choice(far)
        x, y = tiles(*c)[0]
        x0, y0 = min(max(0, x - rng.randint(0, max(0, sw - cw))), W - sw), min(max(0, y - rng.randint(0, max(0, sh - cw))), H - sh)
        r = (x0, y0, x0 + sw, y0 + sh)
        if all(side(px, py) <= -2 for px in range(r[0], r[2]) for py in range(r[1], r[3])):
            m.spawn = r
            break
    else:
        raise RuntimeError('no maze spawn')
    for x in range(m.spawn[0], m.spawn[2]):  # spawn tiles floor; no extra ring (it would shortcut the maze)
        for y in range(m.spawn[1], m.spawn[3]):
            m.put(x, y, FLOOR)
    G.repair(m, rng, True)
    G.place_altars(m, rng, rec['altar'])
    G.repair(m, rng, True)
    if not m.altars:
        raise RuntimeError('no altar')
    if rec.get('mono'):
        G.place_monoliths(m, rng, rec['mono'], True)
    G.place_groups(m, rng, rec['mix'], n_side_of(m, rng), True, strict=True)
    return m


def b_gate(rec, seed):
    return G.generate_gate(rec, seed)


def b_bush(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 17 + 1)
    walk = [p for p in m.bfs('A') if m.get(*p) == FLOOR]
    target = rec['bushf'] * len(walk)

    def nbush():
        return sum(1 for p in walk if m.get(*p) == BUSH)
    for _ in range(4000):
        if nbush() >= target:
            break
        x, y = rng.choice(walk)
        for dx, dy in G.blob(rng, rng.randint(6, 40), N8):
            p = (x + dx, y + dy)
            if (m.inb(*p) and m.get(*p) == FLOOR and p not in m.camp and m.mir(*p) not in m.camp
                    and m.cheb_rect(m.rectA(), *p) > 0 and m.cheb_rect(m.rectB(), *p) > 0):
                m.put(p[0], p[1], BUSH)
    return m


def b_crystal(rec, seed):
    m = G.generate(rec, seed)
    F.KINDS_UN, F.KINDS_NEAR, F.BIG = ['lake'], ['crystal', 'crystal', 'crystal', 'dash'], False
    vr = random.Random(seed * 7 + 3)
    m.nf_vaults = F.add_vaults(m, vr, rec['nv'], rec['nv'])
    return m


def b_zone(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 19 + 3)
    drop_all_groups(m)
    zw = {'home': (1, 0, 0), 'mid': (0, 1, 0), 'center': (0, 0.25, 0.75)}[rec['zone']]
    if rec.get('mono'):
        G.place_monoliths(m, rng, rec['mono'], True)
    G.place_groups(m, rng, rec['mix'], n_side_of(m, rng), True, zone_w=zw, strict=True)
    return m


def b_skew(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 23 + 9)
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    for _ in range(rec['blobs']):
        v = rng.choice([WALL, WALL, HOLE, BUSH])
        x = int(cx + rng.uniform(-0.22, 0.22) * m.W)
        y = int(cy + rng.uniform(-0.22, 0.22) * m.H)
        for dx, dy in G.blob(rng, rng.randint(25, 110), N8):
            p = (x + dx, y + dy)
            if not m.inb(*p) or p in m.protect or m.dspawn(*p) < 2 or m.get(*p) == ALTAR:
                continue
            if any((p[0] + a, p[1] + b) in m.camp or (m.inb(p[0] + a, p[1] + b) and m.get(p[0] + a, p[1] + b) == ALTAR)
                   for a, b in N8 + [(0, 0)]):
                continue
            m.put(p[0], p[1], v)
    G.repair(m, rng, True)
    if not G.access_ok(m, True, True):
        raise RuntimeError('skew blobs cut access')
    return m


def b_hoard(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 29 + 11)
    F.place_hoards(m, rng, 1, rec['hsize'])
    hoard = next(t for t, k in m.groups if k == 'hoard')
    S = set(hoard) | {m.mir(*p) for p in hoard}
    for p in sorted(S):  # rim camps become heavy guards (still one cardinally joined group)
        if any((p[0] + dx, p[1] + dy) not in S for dx, dy in N4) and rng.random() < rec['rim']:
            t = rng.choice([ELK, ELK, GOLEM])
            m.camp[p] = t
            m.camp[m.mir(*p)] = t
    m.nf_share = F.thin_base(m, rng, rec['share'], 4)
    return m


def b_altmany(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 31 + 13)
    want = rec['nalt']
    cand = [c for c in G.altar_candidates(m) if c[4] < 0.48]
    rng.shuffle(cand)
    for c in cand:
        if len(m.altars) >= 2 * want:
            break
        x, y = c[0], c[1]
        if m.get(x, y) != FLOOR or m.mir(x, y) == (x, y) or any(max(abs(x - a[0]), abs(y - a[1])) < 4 for a in m.altars):
            continue
        if any((x + dx, y + dy) in m.camp for dx, dy in N8 + [(0, 0)]):
            continue
        m.put(x, y, ALTAR)
        m.altars.append((x, y))
        m.altars.append(m.mir(x, y))
        if not G.access_ok(m, True, True):
            m.put(x, y, FLOOR)
            m.altars = m.altars[:-2]
    return m


def b_altfar(rec, seed):
    m = G.generate(rec, seed)
    rng = random.Random(seed * 37 + 17)
    for x, y in m.altars:
        m.put(x, y, FLOOR)
    m.altars = []
    cand = [c for c in G.altar_candidates(m) if not any((c[0] + dx, c[1] + dy) in m.camp for dx, dy in N8 + [(0, 0)])]
    if rec['far'] == 'shared':
        cand = [c for c in cand if c[3] is not None and 0.44 <= c[4] <= 0.56]
        cand.sort(key=lambda c: -min(c[2], c[3]))
    else:
        cand = [c for c in cand if c[4] < 0.45]
        cand.sort(key=lambda c: -c[2])
    for c in cand[:30]:
        m.put(c[0], c[1], ALTAR)
        m.altars = [(c[0], c[1])]
        if G.access_ok(m, True, True):
            return m
        m.put(c[0], c[1], FLOOR)
        m.altars = []
    raise RuntimeError('no far altar')


def b_block(rec, seed):
    """A normal base, then a wall band across the mirror axis (protected; x band for sym 0, row band otherwise) whose
    1-3 gaps are plugged by camp groups. Groups and altars on or next to the band are removed first."""
    m = G.generate(rec, seed)
    rng = random.Random(seed * 41 + 19)
    W, H, th = m.W, m.H, rec['th']
    L = H if m.sym == 0 else W        # the band runs along this axis
    A = W if m.sym == 0 else H        # and is thick across this one
    a0 = (A - 1) // 2 - (th - 1) // 2 if A % 2 else A // 2 - max(1, (th + 1) // 2)
    band = ([(x, y) for x in range(a0, W - a0) for y in range(H)] if m.sym == 0
            else [(x, y) for y in range(a0, H - a0) for x in range(W)])
    bset = set(band)
    if any(m.dspawn(*p) < 2 for p in band):
        raise RuntimeError('band too close to a spawn')
    near = {(x + dx, y + dy) for x, y in band for dx, dy in N8} | bset
    for t, k in list(m.groups):
        if any(p in near or m.mir(*p) in near for p in t):
            remove_group(m, t)
    for p in list(m.camp):
        if p in near:
            m.camp.pop(p, None)
            m.camp.pop(m.mir(*p), None)
    for a in list(m.altars):
        if a in near or m.mir(*a) in near:
            m.put(a[0], a[1], FLOOR)
            m.altars.remove(a)
    gaps, tries = [], 0
    while len(gaps) < rec['gaps'] and tries < 300:
        tries += 1
        s0 = rng.randint(2, L - 3 - rec['gw'])
        if all(abs(s0 - g0) >= rec['gw'] + 4 and abs((L - 1 - s0) - g0) >= rec['gw'] + 4 for g0 in gaps):
            gaps.append(s0)
    if not gaps:
        raise RuntimeError('no gap')
    gap_tiles = {p for p in band if any(g0 <= (p[1] if m.sym == 0 else p[0]) < g0 + rec['gw'] for g0 in gaps)}
    gap_tiles |= {m.mir(*p) for p in gap_tiles}
    for p in band:
        m.put(p[0], p[1], FLOOR if p in gap_tiles else WALL)
        m.prot(*p)
    for x, y in sorted(gap_tiles):  # open both ends of every gap
        for dx, dy in N8:
            q = (x + dx, y + dy)
            if (m.inb(*q) and q not in bset and q not in m.camp and m.get(*q) != ALTAR and q not in m.protect
                    and m.dspawn(*q) > 0):
                m.put(q[0], q[1], FLOOR)
    plugs, done = [], set()
    for g in groups_of({p: 1 for p in gap_tiles}):
        key = min(g)
        if key in done:
            continue
        done |= {key, min(m.mir(*p) for p in g)}
        kind = rng.choice(rec['plug'])
        for p in g:
            m.camp[p] = kind
            m.camp[m.mir(*p)] = kind
        m.groups.append((g, 'plug'))
        plugs.append(int(kind))
    m.nf_plugs = plugs
    G.repair(m, rng, False)
    if not m.altars:
        G.place_altars(m, rng, 'near')
    reach = m.bfs('A', block_camps=True)
    for t, k in m.groups:
        if not any((x + dx, y + dy) in reach or m.mir(x + dx, y + dy) in reach for x, y in t for dx, dy in N8):
            raise RuntimeError('block: a group is cut off')
    if not any((a[0] + dx, a[1] + dy) in reach for a in m.altars for dx, dy in N8):
        raise RuntimeError('block: no own altar')
    return m


# ---------------------------------------------------------------- recipes: recipe(fam, i, r) -> rec (r = per-map Random)
def recipe(fam, r):
    if fam == 'vault':
        rec = base_rec(r, size=r.choice(['M', 'L', 'L', 'XL']), aspect='square')
        big = rec['size'] in ('L', 'XL')
        rec.update(nv=r.randint(16, 36) if big else r.randint(10, 18), nnear=r.randint(0, 3))
    elif fam == 'isle':
        rec = base_rec(r, size=r.choice(['M', 'L', 'L']), style=r.choice(['open', 'holes', 'mixed', 'bushbelt']),
                       nisl=r.randint(6, 16), isl_altar=r.random() < 0.4)
    elif fam in ('road', 'corr'):
        rec = base_rec(r, size=r.choice(['M', 'L', 'L', 'XL']), sym=r.choice([0, 1, 2]), altar=r.choice(['near', 'far', 'shared', 'many']))
        if fam == 'road':
            rec.update(cw=r.choice([2, 2, 3]), wt=r.choice([1, 1, 2, 3]), p_loop=0.0, rooms=r.randint(2, 4), cross=1)
        else:
            rec.update(cw=r.choice([1, 1, 2]), wt=1, p_loop=r.uniform(0.04, 0.25), rooms=r.randint(3, 7), cross=r.randint(1, 3))
    elif fam == 'heavy':
        rec = base_rec(r, mix='nf_heavy', mono=r.choice([1, 1, 2, 3]))
    elif fam == 'mgate':
        kind = r.choice(['adj_gate', 'adj_gate', 'ring_gates'])
        rec = base_rec(r, kind=kind, gate_over=dict(camp=r.choice([MONO, MONO, GOLEM])), mono=0)
        if kind == 'ring_gates':
            rec['gate_over']['gates'] = r.choice([1, 2, 2, 4])
    elif fam == 'gemonly':
        rec = base_rec(r, mix='nf_gem', mono=0)
    elif fam == 'goldonly':
        rec = base_rec(r, mix='nf_gold', mono=0)
    elif fam == 'huge':
        Wd = r.randint(95, 100)
        rec = base_rec(r, size='XL', aspect='square', dims=(Wd, r.choice([Wd, Wd, r.randint(90, 100)])), spawn='long',
                       style=r.choice(['open', 'holes', 'bushbelt', 'mixed', 'corridors']), keep=r.randint(6, 12))
    elif fam == 'brawl':
        Wd = r.randint(30, 34)
        rec = base_rec(r, size='S', aspect='square', dims=(Wd, Wd), spawn='short', T=r.choice([4, 5, 5]),
                       mix=r.choice(['balanced', 'wolf_packs', 'cluster_heavy', 'elk_heavy']), mono=0,
                       style=r.choice(['open', 'open', 'holes', 'bushbelt', 'mixed']))
    elif fam == 'bush':
        rec = base_rec(r, style=r.choice(['open', 'bushbelt', 'holes', 'mixed']), bushf=r.uniform(0.45, 0.85))
    elif fam == 'crystal':
        rec = base_rec(r, size=r.choice(['M', 'L', 'L', 'XL']), aspect='square', nv=r.randint(6, 16))
    elif fam == 'zone':
        rec = base_rec(r, zone=r.choice(['home', 'mid', 'center']))
    elif fam == 'skew':
        rec = base_rec(r, sym=2, spawn=r.choice(['medium', 'medium', 'long', 'short']), blobs=r.randint(3, 7),
                       style=r.choice(['open', 'mixed', 'holes']))
    elif fam == 'hoard':
        rec = base_rec(r, size=r.choice(['M', 'L', 'L']), mono=0, altar=r.choice(['near', 'far', 'many', 'shared']),
                       hsize=r.randint(20, 60), rim=r.uniform(0.3, 0.9), share=r.uniform(0.55, 0.8))
    elif fam == 'altmany':
        rec = base_rec(r, size=r.choice(['M', 'L', 'L', 'XL']), altar='many', nalt=r.randint(6, 12))
    elif fam == 'altfar':
        rec = base_rec(r, far=r.choice(['shared', 'own']), spawn=r.choice(['long', 'medium']))
    elif fam == 'block':
        sym = r.choice([0, 1, 2])
        rec = base_rec(r, sym=sym, spawn=r.choice(['long', 'medium']), style=r.choice(['open', 'holes', 'mixed', 'bushbelt']),
                       altar=r.choice(['near', 'far', 'many']), th=r.choice([1, 1, 2, 3, 4]), gaps=r.choice([1, 1, 2, 3]),
                       gw=r.choice([1, 1, 2, 3]), plug=r.choice([[WOLF], [WOLF, ELK], [ELK, GOLEM], [GOLD], [MONO], [WOLF, GOLD, ELK, GOLEM]]))
        if MONO in rec['plug']:  # a monolith plug is 20,000 HP and 200 gems a tile: keep it 1 wide and <= 2 thick
            rec.update(gw=1, th=min(rec['th'], 2))
    else:
        raise KeyError(fam)
    return rec


BUILD = {'vault': b_vault, 'isle': b_isle, 'road': gen_maze, 'corr': gen_maze, 'heavy': b_normal, 'mgate': b_gate,
         'gemonly': b_normal, 'goldonly': b_normal, 'huge': b_normal, 'brawl': b_normal, 'bush': b_bush,
         'crystal': b_crystal, 'zone': b_zone, 'skew': b_skew, 'hoard': b_hoard, 'altmany': b_altmany,
         'altfar': b_altfar, 'block': b_block}


def post(fam, m, rec, rng):
    if fam == 'huge':
        thin_groups(m, rng, rec['keep'] // 2)


# ---------------------------------------------------------------- family checks on the decoded design
def check(fam, m, rec, f, x):
    """None = the map has its family's property, else the reason it is rejected."""
    if len(G.spec_of(m)['camps']) > 255:
        return 'too many camps (u8 count)'
    if f['s2s'] is None:
        return 'spawns not connected'
    reach_gems = f['gems'] * (1 - f['none'] - f['cry'])
    if fam != 'goldonly' and reach_gems < 40:
        return f"reachable gems {reach_gems:.0f}"
    if fam not in ('mgate',) and not isinstance(f['alt_d'], int):
        return f"no walkable altar ({f['alt_d']})"
    if f['grp'] < 6 and fam not in ('hoard',):
        return f"groups {f['grp']}"
    c = {
        'vault': lambda: len(getattr(m, 'nf_vaults', [])) >= max(6, rec['nv'] // 2) and f['none'] > 0,
        'isle': lambda: f['dash'] + f['cry'] >= 0.12 and len(getattr(m, 'nf_isl', [])) >= 5,
        'road': lambda: (x['wind'] or 0) >= 2.5,
        'corr': lambda: x['nbr'] <= (4.2 if rec['cw'] == 1 else 5.6),
        'heavy': lambda: f['heavy'] >= 0.98 and f['clu'] == 0,
        'mgate': lambda: x['altacc'] in ('adjgate', 'ring'),
        'gemonly': lambda: f['gold'] == 0,
        'goldonly': lambda: f['gems'] == 0 and f['gold'] >= 600,
        'huge': lambda: m.W >= 95 and f['grp'] <= 16,
        'brawl': lambda: m.W <= 34 and f['s2s'] <= 12,
        'bush': lambda: f['bush'] >= 30,
        'crystal': lambda: f['cry'] >= 0.12,
        'zone': lambda: True,
        'skew': lambda: m.sym == 2,
        'hoard': lambda: x['top'] >= 0.5,
        'altmany': lambda: f['alt'] >= 12,
        'altfar': lambda: f['alt'] <= 2 and f['alt_d'] >= max(15, 0.5 * f['s2s']),
        'block': lambda: x['cblk'] == 'cut',
    }[fam]
    return None if c() else 'family property missing'


# ---------------------------------------------------------------- driver
def make(fam, seed, rec):
    rng = random.Random(seed * 3 + 1)
    m = BUILD[fam](rec, seed)
    post(fam, m, rec, rng)
    ok, info = G.validate(m, dict(rec, kind='nf', checks=2))
    if not ok:
        raise RuntimeError(info)
    d = G.decode_like(m)
    f, x = mapfeat.analyse(d, 'design'), extfeat(d)
    why = check(fam, m, rec, f, x)
    if why:
        raise RuntimeError(why)
    return m


def build_one(fam, name, seed, rec, outdir):
    m = make(fam, seed, rec)
    sp, mp = os.path.join(outdir, name + '.json'), os.path.join(outdir, name + '.map26a')
    json.dump(G.spec_of(m), open(sp, 'w'))
    d = G.build_and_check(m, sp, mp)
    f, x = mapfeat.analyse(d, name), extfeat(d)
    why = check(fam, m, rec, f, x)
    if why:
        raise RuntimeError('built map: ' + why)
    return m, mp, dict(f, **x)


def main():
    a = sys.argv[1:]
    if '--list' in a or not a:
        print(__doc__)
        return
    fams = [x for x in a if x in FAMS]
    opt = {k: a[a.index(k) + 1] for k in ('--n', '--start', '--seed', '--tmp') if k in a}
    if not fams:
        sys.exit(f'name a family: {FAMS}')
    if '--seed' in opt:  # one never-saved map
        fam, seed, tmp = fams[0], int(opt['--seed']), opt.get('--tmp')
        if not tmp:
            sys.exit('--seed needs --tmp DIR')
        os.makedirs(tmp, exist_ok=True)
        for att in range(40):
            rec = recipe(fam, random.Random(seed * 101 + att))
            try:
                m, mp, f = build_one(fam, f'nf_{fam}_s{seed}', seed + att, rec, tmp)
            except Exception as e:  # noqa: BLE001  any failed design: next seed
                print(f'{fam} seed {seed + att}: {e}', file=sys.stderr)
                continue
            print(mp)
            return
        sys.exit(f'{fam}: no valid map from seed {seed}')
    n, start = int(opt.get('--n', 20)), int(opt.get('--start', 1))
    os.makedirs(OUT, exist_ok=True)
    for fam in fams:
        k = FAMS.index(fam)
        names = []
        for i in range(start, start + n):
            name = f'{PREFIX}{fam}_{i:03d}'
            r = random.Random(SEED0 + 1000000 * k + 999 * i + 7)
            rec0 = recipe(fam, r)
            for att in range(40):
                seed = SEED0 + 1000000 * k + 1000 * i + att
                rec = rec0 if att < 20 else recipe(fam, random.Random(seed))  # a fresh recipe after 20 failures
                try:
                    m, mp, f = build_one(fam, name, seed, rec, OUT)
                except Exception as e:  # noqa: BLE001  any failed design: next seed
                    print(f'{name} seed {seed}: {str(e)[:120]}', file=sys.stderr)
                    continue
                break
            else:
                print(f'{name}: no valid map in 40 attempts', file=sys.stderr)
                continue
            extra = {k2: getattr(m, k2) for k2 in ('nf_vaults', 'nf_isl', 'nf_plugs', 'nf_share') if hasattr(m, k2)}
            json.dump(dict(name=name, fam=fam, seed=seed, recipe=rec, features=f, **extra),
                      open(os.path.join(OUT, name + '.meta.json'), 'w'), indent=1, default=str)
            open(os.path.join(OUT, name + '.txt'), 'w').write(m.ascii() + '\n')
            if '--install' in a:
                G.install(mp, os.path.join(INSTALL, name + '.map26a'))
            names.append(name)
            print(f"{name} seed {seed} {m.W}x{m.H} T{m.T} sym{m.sym}: gems {f['gems']} gold {f['gold']} grp {f['grp']} "
                  f"s2s {f['s2s']} wind {f['wind']} nbr {f['nbr']} alt {f['alt']}/{f['alt_d']} acc {f['altacc']} "
                  f"dash {f['dash']} cry {f['cry']} none {f['none']} heavy {f['heavy']} bush {f['bush']} top {f['top']} "
                  f"cblk {f['cblk']} camps {f['ncamp']}", flush=True)
            if '--show' in a:
                print(m.ascii())
        lp = os.path.join(OUT, f'maplist_{fam}.txt')
        old = set(open(lp).read().split()) if os.path.exists(lp) else set()
        open(lp, 'w').write(''.join(x + '\n' for x in sorted(old | set(names))))
    allp = os.path.join(OUT, 'maplist.txt')
    alln = set()
    for fam in FAMS:
        lp = os.path.join(OUT, f'maplist_{fam}.txt')
        if os.path.exists(lp):
            alln |= set(open(lp).read().split())
    open(allp + '.new', 'w').write(''.join(x + '\n' for x in sorted(alln)))
    os.replace(allp + '.new', allp)


if __name__ == '__main__':
    main()
