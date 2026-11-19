#!/usr/bin/env python3
"""genfuel.py [N] [--start K] [--show] - gen_fuel_*: FUEL STRESS maps (owner 31 Oct). Tooler.

Not a strength test: never tune on these maps. They exist so a fuel regression (more exhaustions a game) shows up
locally before it ships.

Idea (owner): adgato-gemcombat5 holds 3 camp groups no champion can ever capture (a mirrored pair of 3-cluster gem
groups at (36-37,47-48) / (61-62,47-48) and a 3-cluster column at (49,22-24) on the axis): each sits inside a solid
wall block (1-4 thick), inside a hole lake, so the nearest walkable tile is 6-7 tiles away. A dash crosses at most 2
steps and never a wall, a crystal reaches 3 and cannot land on a wall or hole (GameRules.md:147-159), every attack
and spell reaches <= 4, and walls block sight: they are never seen, killed or captured. Here the same trap is upscaled.

Each map = a normal, big (80-99 square) genmaps economy (walk-reachable camps, >= 1 walkable altar, connected spawns,
genmaps' validation unchanged), PLUS 8-30 physical 'vault' groups stamped on top (mirror pairs), of varied kinds
(gem, gold, wolf, elk, golem, monolith, mixed), about half placed near the spawn-to-spawn walk so they are in sight:
  unobtainable (no tile of the group reachable by walking, dashing or one crystal jump; nearest walkable tile >= R+1):
    sealed : walls round the group (1-3 thick), holes out to R (the gemcombat5 shape; hidden behind the walls)
    lake   : holes only out to R (R 3-5: visible over the holes from the shore, never capturable)
    block  : solid walls out to R (invisible)
  near-misses:
    dash   : a floor ring round the group, one hole ring, a floor shore: reachable only by a 2-step dash (or a crystal)
    crystal: a floor ring, two hole rings, a floor shore: reachable only by a crystal jump
    detour : a 2-ring wall spiral (gaps on opposite sides): walkable, but only by a long detour
Every vault is checked on the decoded design: unobtainable groups not in G.team_reach(crystal=True) (camps treated as
landable, the conservative case), dash groups reached with a dash and not on foot, crystal groups only with the crystal,
detour groups on foot; and after each stamp every original group stays walkable, every altar keeps a walkable free
tribute tile and the spawns stay connected. The built file is decoded back and checked tile for tile (genmaps).
Then validate the files in the engine: a 1-round game each (see the cambc-lab skill, maps.md 'fuel' row).

Seeds 86,000,000 + 1000 i + attempt; prefix gen_fuel_; dir /data/USER/maps_fuel (+ maplist.txt, NAME.meta.json,
NAME.txt previews); installed into /data/USER/work301/maps (abl.sh, condab and cqbatch find them by name).
usage: nice -n 10 python3 -I tools/lab/genfuel.py [N] [--start K] [--show] [--big | --hoard]

--big (gen_fuelb_*, seeds 87,000,000+, list maplist_big.txt): the HOARD variant. The v1 maps (small vault groups) gave
~0.01 exhaustions a game, the same as bank v2, while the index's worst maps (gen_hbd/gen_dq/gen_nt) each hold ONE
reachable 80-90-camp gem group. Here each map gets 2-5 vault groups a side of 12-54 camps (a filled rectangle, mostly gem
clusters, some wolf/elk/gold), all placed near the spawn-to-spawn walk: mostly 'lake' (visible over the holes, never
capturable), some 'sealed' (hidden), and at most one 'dash' near-miss (a giant group only dashers can capture).

--hoard (gen_fuelh_*, seeds 88,000,000+, list maplist_hoard.txt; 01 Nov): 1-2 REACHABLE near-total all-gem groups of 80-120
camps (one self-symmetric across the centre, or a mirrored pair beside the axis: contest ~0.5, on the spawn-to-spawn walk;
terrain under and round them carved to floor), the base thinned until they hold >= 85% of the walkable gems (>= 4 base
groups kept; genmaps validation re-run), plus 2-4 small visible 'lake' vaults a side. 80-99 square, 4-5 a side. The shape of
gen_nt_025 (96 gem clusters, 92% of the gems), where v363 exhausts ~11 times a side a game. Not in any default list.
"""
import json
import os
import random
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import mapfeat  # noqa: E402

PREFIX, SEED0, OUT = 'gen_fuel_', 86000000, '/data/USER/maps_fuel'
HOARD = False  # --hoard: reachable near-total gem groups (gen_fuelh_*, seeds 88M+, maplist_hoard.txt)
LIST = 'maplist.txt'
BIG = False  # --big: the hoard variant (main() sets PREFIX, SEED0, LIST and the vault kinds)
INSTALL = '/data/USER/work301/maps'
FLOOR, WALL, HOLE, BUSH, ALTAR = G.FLOOR, G.WALL, G.HOLE, G.BUSH, G.ALTAR
KINDS_UN = ['sealed', 'sealed', 'lake', 'lake', 'block']
KINDS_NEAR = ['dash', 'crystal', 'detour']
CAMPS = {'gem': [G.GEM], 'gold': [G.GOLD], 'wolf': [G.WOLF], 'elk': [G.ELK], 'golem': [G.GOLEM],
         'mono': [G.MONO], 'mixed': [G.GEM, G.GOLD, G.WOLF, G.ELK]}
CAMP_W = {'gem': 4, 'gold': 2, 'wolf': 2, 'elk': 2, 'golem': 1, 'mono': 0.6, 'mixed': 1.2}
MAXN = {'gem': 6, 'gold': 6, 'wolf': 3, 'elk': 2, 'golem': 2, 'mono': 1, 'mixed': 5}


def recipe_hoard(i):
    """--hoard (01 Nov, Builder/owner "one specifically made for fuel exhaustion"): what bites is ONE reachable near-total
    gem group (gen_nt_025: 96 gem clusters in the centre, 672 of 732 gems, ~11 exhaustions a side a game on v363), not
    unobtainable vaults. Base: 80-99 square, 4-5 a side, centre kept free (no central/shared altar), no monolith."""
    r = random.Random(SEED0 + 999 * i + 7)
    W = r.randint(80, 99)
    rec = dict(kind='normal', size='XL', aspect='square', dims=(W, W), checks=2,
               style=r.choice(['open', 'open', 'holes', 'bushbelt', 'mixed']), mix=r.choice(['balanced', 'cluster_heavy']),
               mono=0, altar=r.choice(['near', 'far', 'many']), spawn=r.choice(['long', 'long', 'medium']),
               sym=r.choice([0, 1, 2, 2]), T=r.choice([4, 5, 5]))
    return rec, r.choice([1, 1, 2]), r.randint(80, 120), r.randint(2, 4)


def connected4(S):
    S = set(S)
    if not S:
        return False
    st, seen = [next(iter(S))], set()
    while st:
        c = st.pop()
        if c not in seen:
            seen.add(c)
            st += [(c[0] + dx, c[1] + dy) for dx, dy in G.N4 if (c[0] + dx, c[1] + dy) in S]
    return seen == S


def place_hoards(m, rng, nh, size):
    """nh 1: one self-symmetric all-gem group of `size` camps across the mirror centre; nh 2: a mirrored pair of `size`
    camps each beside the axis (contest ~0.5). Terrain under the group and a 1-tile ring round it is carved to floor (both
    mirror sides, never a spawn, altar or protected tile), so the group is walkable and the spawns can walk round it."""
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    path = s2s_path(m)
    def ok_tile(p):
        x, y = p
        return (m.inb(x, y) and m.dspawn(x, y) >= 4 and p not in m.protect and m.get(x, y) != ALTAR
                and all(not (m.inb(x + dx, y + dy) and m.get(x + dx, y + dy) == ALTAR) for dx, dy in G.N8))
    mid = sorted(path, key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))[:40] if path else [(int(cx), int(cy))]
    for _ in range(400):
        ax, ay = rng.choice(mid)
        if nh == 1:
            A = {(ax + dx, ay + dy) for dx, dy in G.blob(rng, size // 2 + 1)}
            S = A | {m.mir(*p) for p in A}
            if not size * 0.9 <= len(S) <= size * 1.15 or not connected4(S):
                continue
            groups = [S]
        else:
            off = rng.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
            ax, ay = ax + off[0] * rng.randint(6, 10), ay + off[1] * rng.randint(6, 10)
            A = {(ax + dx, ay + dy) for dx, dy in G.blob(rng, size)}
            B = {m.mir(*p) for p in A}
            if A & B or any((x + dx, y + dy) in B for x, y in A for dx, dy in G.N8) or not connected4(A):
                continue
            groups = [A, B]
        allp = set().union(*groups)
        ring = {(x + dx, y + dy) for x, y in allp for dx, dy in G.N8} - allp
        if not all(ok_tile(p) for p in allp) or any(p in m.camp for p in allp | ring):
            continue
        ring |= {m.mir(*p) for p in ring}
        if any(not m.inb(*p) or m.dspawn(*p) == 0 or p in m.protect or m.get(*p) == ALTAR for p in ring if m.inb(*p)):
            continue
        old = {p: m.get(*p) for p in allp | ring if m.inb(*p)}
        for p in old:
            m.put(*p, FLOOR)
        for p in allp:
            m.camp[p] = G.GEM
        m.groups.append(([p for p in sorted(groups[0]) if nh == 2 or p <= m.mir(*p)], 'hoard'))
        if G.access_ok(m, True, True):
            return [len(g) for g in groups]
        for p in allp:
            m.camp.pop(p, None)
        m.groups.pop()
        for p, v in old.items():
            m.put(*p, v)
    raise RuntimeError('no room for the hoard group(s)')


def thin_base(m, rng, target, keep):
    """Drop whole base groups (gem-richest first) until the hoard holds >= target of the walkable camp gems, keeping
    at least `keep` base groups and every access check."""
    def gems(tiles):
        return sum(G.GEMS[m.camp[p]] for p in tiles if p in m.camp)
    hoard = [t for t, k in m.groups if k == 'hoard']
    hg = sum(gems(set(t) | {m.mir(*p) for p in t}) for t in hoard) / (1 if len(hoard) == 1 else 1)
    base = [(t, k) for t, k in m.groups if k != 'hoard']
    def share():
        bg = sum(gems(set(t) | {m.mir(*p) for p in t}) for t, _ in base)
        return hg / max(1, hg + bg)
    for t, k in sorted(base, key=lambda tk: -gems(tk[0])):
        if share() >= target or len(base) <= keep:
            break
        if gems(t) == 0:
            continue
        saved = {p: m.camp[p] for x in t for p in (x, m.mir(*x)) if p in m.camp}
        for p in saved:
            m.camp.pop(p)
        m.groups.remove((t, k))
        base.remove((t, k))
        if not G.access_ok(m, True, True):
            m.camp.update(saved)
            m.groups.append((t, k))
            base.append((t, k))
    return round(share(), 3)


def recipe(i):
    if HOARD:
        return recipe_hoard(i)
    r = random.Random(SEED0 + 999 * i + 7)
    W = r.randint(80, 99)
    rec = dict(kind='normal', size='XL', aspect='square', dims=(W, W), checks=2,
               style=r.choice(['open', 'corridors', 'holes', 'bushbelt', 'mixed', 'open']),
               mix=r.choice(['balanced', 'balanced', 'cluster_heavy', 'cluster_heavy', 'elk_heavy', 'wolf_packs',
                             'golems', 'gold_rich']),
               mono=r.choice([0, 0, 1]), altar=r.choice(['near', 'far', 'central', 'shared', 'many']),
               spawn=r.choice(['long', 'long', 'medium']), sym=r.choice([0, 1, 2, 2]), T=r.choice([3, 4, 5, 5]))
    nv = r.randint(4, 15)                  # vault groups a side (8-30 physical)
    nnear = r.randint(1, max(1, nv // 3))  # of which near-misses
    if BIG:
        nv, nnear = r.randint(2, 5), r.randint(0, 1)
    return rec, nv, nnear


def polyomino(rng, n):
    s = [(0, 0)]
    while len(s) < n:
        x, y = rng.choice(s)
        dx, dy = rng.choice(G.N4)
        p = (x + dx, y + dy)
        if p not in s and abs(p[0]) <= 2 and abs(p[1]) <= 1:
            s.append(p)
    return s


def hoard_shape(rng):
    w, h = rng.randint(3, 9), rng.randint(3, 6)
    while w * h > 54 or w * h < 12:
        w, h = rng.randint(3, 9), rng.randint(3, 6)
    shape = [(x - w // 2, y - h // 2) for x in range(w) for y in range(h)]
    types = [G.GEM if rng.random() < 0.85 else rng.choice([G.WOLF, G.ELK, G.GOLD]) for _ in shape]
    return 'hoard', shape, types


def camp_shape(rng):
    if BIG:
        return hoard_shape(rng)
    kind = rng.choices(list(CAMP_W), weights=list(CAMP_W.values()))[0]
    n = rng.randint(1, MAXN[kind])
    shape = polyomino(rng, n)
    types = [rng.choice(CAMPS[kind]) for _ in shape]
    if kind == 'mixed' and len(set(types)) == 1 and n > 1:
        types[0] = G.GEM if types[0] != G.GEM else G.ELK
    return kind, shape, types


def cheb_field(core, R):
    """{tile: Chebyshev distance to the core} for every tile within R of the core (core tiles excluded)."""
    out = {}
    for cx, cy in core:
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                p = (cx + dx, cy + dy)
                if p in core:
                    continue
                d = max(abs(dx), abs(dy))
                if d < out.get(p, 99):
                    out[p] = d
    return out


def vault_plan(rng, vk, core):
    """{tile: terrain} for a vault of kind vk round the core tiles (camp tiles get FLOOR), and its radius."""
    plan = {p: FLOOR for p in core}
    if vk in ('sealed', 'lake', 'block'):
        R = rng.randint(4, 5) if vk == 'sealed' else rng.randint(3, 5)
        tw = rng.randint(1, 3)
        for p, d in cheb_field(core, R).items():
            plan[p] = WALL if vk == 'block' or (vk == 'sealed' and d <= tw) else HOLE
        return plan, R
    if vk == 'dash':
        R = 3
        for p, d in cheb_field(core, R).items():
            plan[p] = HOLE if d == 2 else FLOOR
        return plan, R
    if vk == 'crystal':
        R = 4
        for p, d in cheb_field(core, R).items():
            plan[p] = HOLE if d in (2, 3) else FLOOR
        return plan, R
    # detour: square rings round the core's bounding box: d1 floor, d2 wall (gap), d3 floor, d4 wall (gap opposite),
    # d5 floor; box rings so the gaps are single tiles in the middle of a side
    xs, ys = [p[0] for p in core], [p[1] for p in core]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    R = 5
    side = rng.randrange(4)
    for x in range(x0 - R, x1 + R + 1):
        for y in range(y0 - R, y1 + R + 1):
            if (x, y) in core:
                continue
            d = max(x0 - x, x - x1, y0 - y, y - y1, 0)
            plan[(x, y)] = WALL if d in (2, 4) else FLOOR
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    for d, s in ((2, side), (4, (side + 2) % 4)):
        gx, gy = [(mx, y0 - d), (x1 + d, my), (mx, y1 + d), (x0 - d, my)][s]
        plan[(gx, gy)] = FLOOR
    return plan, R


def walk_reach(m):
    return m.bfs('A')


def stamp_ok(m, plan, core):
    """Cheap overlap checks: inside the board, off spawns/altars/protected tiles/other camps, disjoint from its mirror."""
    tiles = set(plan)
    mir = {m.mir(*p) for p in tiles}
    for p in tiles:
        if not m.inb(*p) or m.dspawn(*p) < 4 or p in m.protect:
            return False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (p[0] + dx, p[1] + dy)
                if n in mir:
                    return False
                if m.inb(*n) and m.get(*n) == ALTAR:
                    return False
    for (cx, cy) in m.camp:
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if (cx + dx, cy + dy) in tiles:
                    return False
    for ax, ay in m.altars:
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if (ax + dx, ay + dy) in tiles or m.mir(ax + dx, ay + dy) in tiles:
                    return False
    return True


def base_state(m, groups):
    """(walkable original groups, altars with a walkable free tribute tile reached without killing a camp, spawns
    connected): genmaps.access_ok's rules. A vault stamp must keep every part that held before it."""
    walk = m.bfs('A')
    reach = m.bfs('A', block_camps=True)
    gw = frozenset(i for i, tiles in enumerate(groups) if any(p in walk for p in tiles))
    al = set()
    for x, y in m.altars:
        nbs = [(x + dx, y + dy) for dx, dy in G.N8 if m.inb(x + dx, y + dy) and (x + dx, y + dy) not in m.camp]
        if any(p in reach or m.mir(*p) in reach for p in nbs):
            al.add((x, y))
    return gw, frozenset(al), m.s2s(reach)


def base_ok(m, groups, before):
    now = base_state(m, groups)
    return before[0] <= now[0] and before[1] <= now[1] and (now[2] or not before[2])


def vault_ok(m, vk, core):
    d = G.decode_like(m)
    cry = G.team_reach(d, crystal=True)
    if vk in ('sealed', 'lake', 'block'):
        return not any(p in cry or m.mir(*p) in cry for p in core)
    walk = m.bfs('A')
    onfoot = any(p in walk for p in core)
    if vk == 'detour':
        return onfoot
    dash = m.bfs('A', dash=True)
    ondash = any(p in dash for p in core)
    if vk == 'dash':
        return ondash and not onfoot
    return (not ondash) and any(p in cry for p in core)  # crystal


def s2s_path(m):
    dist = m.bfs('A')
    rb = m.rectB()
    ends = [p for p in dist if m.cheb_rect(rb, *p) == 1]
    if not ends:
        return []
    cur = min(ends, key=lambda p: dist[p])
    path = [cur]
    while dist[cur] > 0:
        cur = min(((cur[0] + dx, cur[1] + dy) for dx, dy in G.N8 if (cur[0] + dx, cur[1] + dy) in dist),
                  key=lambda p: dist[p])
        path.append(cur)
    return path


def add_vaults(m, rng, nv, nnear):
    orig = [list(t) for t, _ in m.groups] + [[p] for p in m.camp if not any(p in t or m.mir(*p) in t
                                                                            for t, _ in m.groups)]
    before = base_state(m, orig)
    if not before[1] or not before[2]:
        return []
    path = s2s_path(m)
    pathset = set(path) | {m.mir(*p) for p in path}
    kinds = [rng.choice(KINDS_NEAR) for _ in range(nnear)] + [rng.choice(KINDS_UN) for _ in range(nv - nnear)]
    rng.shuffle(kinds)
    placed = []
    for i, vk in enumerate(kinds):
        near_path = (BIG or i % 2 == 0) and pathset
        for _ in range(500):
            ck, shape, types = camp_shape(rng)
            if near_path:
                px, py = rng.choice(path)
                cx, cy = px + rng.randint(-9, 9), py + rng.randint(-9, 9)
            else:
                cx, cy = rng.randrange(m.W), rng.randrange(m.H)
            core = [(cx + dx, cy + dy) for dx, dy in shape]
            plan, R = vault_plan(rng, vk, set(core))
            if not stamp_ok(m, plan, core):
                continue
            old = {p: m.get(*p) for p in plan}
            for p, v in plan.items():
                m.put(*p, v)
            for p, t in zip(core, types):
                m.camp[p] = t
                m.camp[m.mir(*p)] = t
            if base_ok(m, orig, before) and vault_ok(m, vk, core):
                placed.append(dict(kind=vk, camps=ck, n=len(core), R=R, at=list(core[0]),
                                   types=[G.GEMS[t] for t in types], near_path=bool(near_path)))
                break
            for p in core:
                m.camp.pop(p, None)
                m.camp.pop(m.mir(*p), None)
            for p, v in old.items():
                m.put(*p, v)
    return placed


def main():
    global PREFIX, SEED0, LIST, BIG, KINDS_UN, KINDS_NEAR
    a = sys.argv[1:]
    global HOARD
    if '--big' in a:
        PREFIX, SEED0, LIST, BIG = 'gen_fuelb_', 87000000, 'maplist_big.txt', True
        KINDS_UN, KINDS_NEAR = ['lake', 'lake', 'lake', 'sealed'], ['dash']
    if '--hoard' in a:
        PREFIX, SEED0, LIST, HOARD = 'gen_fuelh_', 88000000, 'maplist_hoard.txt', True
        KINDS_UN, KINDS_NEAR = ['lake'], ['dash']
    n = int(a[0]) if a and a[0].isdigit() else 1
    start = int(a[a.index('--start') + 1]) if '--start' in a else 1
    os.makedirs(OUT, exist_ok=True)
    names = []
    for i in range(start, start + n):
        name = f'{PREFIX}{i:04d}'
        if HOARD:
            rec, nh, hsize, nv = recipe(i)
            nnear = 0
        else:
            rec, nv, nnear = recipe(i)
        hinfo = None
        for attempt in range(40):
            seed = SEED0 + 1000 * i + attempt
            try:
                m = G.generate(rec, seed)
                ok, info = G.validate(m, rec)
            except RuntimeError as e:
                ok, info = False, str(e)
            if not ok:
                print(f'{name} seed {seed}: base rejected ({info})', file=sys.stderr)
                continue
            vr = random.Random(seed * 7 + 3)
            if HOARD:
                try:
                    hs = place_hoards(m, vr, nh, hsize)
                except RuntimeError as e:
                    print(f'{name} seed {seed}: {e}', file=sys.stderr)
                    continue
                sh = thin_base(m, vr, 0.85, 4)
                ok, info = G.validate(m, rec)
                if not ok or sh < 0.80:
                    print(f'{name} seed {seed}: hoard map rejected ({info if not ok else f"hoard share {sh}"})', file=sys.stderr)
                    continue
                hinfo = dict(hoards=hs, hoard_share=sh)
            placed = add_vaults(m, vr, nv, nnear)
            if len(placed) < (max(2, nv - 1) if (BIG or HOARD) else max(4, nv * 2 // 3)):
                print(f'{name} seed {seed}: only {len(placed)}/{nv} vaults placed', file=sys.stderr)
                continue
            if len(G.spec_of(m)['camps']) > 255:  # the file stores one camp of each mirror pair in a u8 count
                print(f'{name} seed {seed}: too many camps', file=sys.stderr)
                continue
            sp, mp = os.path.join(OUT, name + '.json'), os.path.join(OUT, name + '.map26a')
            json.dump(G.spec_of(m), open(sp, 'w'))
            try:
                d = G.build_and_check(m, sp, mp)
            except (RuntimeError, AssertionError) as e:
                print(f'{name} seed {seed}: build failed ({e})', file=sys.stderr)
                continue
            break
        else:
            raise SystemExit(f'{name}: no valid map in 40 attempts')
        f = mapfeat.analyse(d, name)
        un = sum(1 for v in placed if v['kind'] in ('sealed', 'lake', 'block'))
        meta = dict(name=name, seed=seed, recipe=rec, vaults_per_side=len(placed), unobtainable_per_side=un,
                    vaults=placed, features=f, **(hinfo or {}))
        json.dump(meta, open(os.path.join(OUT, name + '.meta.json'), 'w'), indent=1, default=str)
        open(os.path.join(OUT, name + '.txt'), 'w').write(m.ascii() + '\n')
        G.install(mp, os.path.join(INSTALL, name + '.map26a'))
        names.append(name)
        kinds = {}
        for v in placed:
            kinds[v['kind']] = kinds.get(v['kind'], 0) + 1
        print(f"{name} seed {seed} {m.W}x{m.H} T{m.T} sym{m.sym} {rec['style']}/{rec['mix']}: {2 * len(placed)} vault "
              f"groups ({2 * un} unobtainable; {kinds}), camps {len(m.camp)}, gems {f['gems']}, grp {f['grp']}, "
              f"s2s {f['s2s']}, altars {f['alt']} (walk {f['alt_d']})" + (f", hoard {hinfo}" if hinfo else ""), flush=True)
        if '--show' in a:
            print(m.ascii())
    lp = os.path.join(OUT, LIST)
    old = set(open(lp).read().split()) if os.path.exists(lp) else set()
    open(lp, 'w').write(''.join(x + '\n' for x in sorted(old | set(names))))


if __name__ == '__main__':
    main()
