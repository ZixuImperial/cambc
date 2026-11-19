#!/usr/bin/env python3
"""gendom.py N - gen_dom_*: maps with a dominant gem source, for owner idea 7 (hold the dominant group; spec
condor-work/reports/spec_domgroup_1028.md, cambc-8f + cambc-a3). Tooler, 28 Oct.

genbig.py's fresh recipes (sizes, symmetry, team sizes 3-5, terrain, altars, spawn distance, camp mixes: a pool-like map)
plus one dominant structure, with a target t for max(D, Z) spread evenly over 0.30-0.80:
  single  one self-symmetric gem-cluster group across the mirror axis or centre (like 00the-line's g2), sometimes with
          1-2 wolf or elk guards;
  pair    a mirrored pair of such groups in the contested band (walk ratio 0.41-0.49), t <= 0.45 only (one copy is at
          most half the gems);
  zone    a field of small groups (1-3 clusters, sometimes a wolf) around a point near the centre, like 00lost-world's
          field, so no single group dominates but the zone does.
To reach a high t the base map's other gem groups are thinned (whole mirrored pairs, monoliths first), and gold groups are
added back when fewer than 3 base pairs are left; recipes with t > 0.5 get no monoliths.

Features, measured on every built .map26a exactly as cambc-a3's topshare/zoneshare (checked on 949 maps, all equal):
  groups = 4-connected camps (the engine's groups); monolith groups never count in a numerator, but their gems stay in
  the denominator (all camp gems).
  D = gems of the richest non-monolith group / all camp gems.
  Z = max over non-monolith groups g of the gems of the non-monolith groups whose centroid is within 6 (Chebyshev) of
      g's centroid / all camp gems.
  The spec text excludes monoliths from both sides; that variant is in the TSV as D_x / Z_x.
A map is kept when its built max(D, Z) is within 0.06 of its target, and for single/pair D itself is, and for zone
D <= 0.6 Z; otherwise build() tries the next seed.

Seeds 81,000,000+ (seed = 81,000,000 + 1000 i + attempt), prefix gen_dom_, dir /data/USER/genmaps_dom; installed into
/data/USER/work301/maps (abl.sh; condab syncs maps into proj400 itself). Lists: maplist_dev.txt (gen_dom_001-100,
for choosing thresholds) and maplist_ho.txt (101-200, held out: never tune on them), each with a TSV of its features.
The two halves get the same 100 target strata (each shuffled), the same kind mix and independent recipe columns.

usage: nice -n 10 python3 -I tools/lab/gendom.py 200 [--jobs 6]
"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genbig  # noqa: E402
import genmaps as G  # noqa: E402
import map26a  # noqa: E402

PREFIX, SEED0, OUT = 'gen_dom_', 81000000, '/data/USER/genmaps_dom'
WOLF, ELK, GEM, GOLD, MONO, GOLEM = range(6)
GEMS = G.GEMS
TOL = 0.06
# Second pass (28 Oct): these 26 recipes found no map in genbig's 40 attempts with the first placement (v1: a pair copy
# sized like a single group, t r / (1 - t) instead of t r / (1 - 2 t), and one anchor per try). They use v2: the pair
# formula, a varied blob size, and every anchor. All other maps are v1, so a rebuild reproduces them.
V2 = {5, 9, 10, 20, 30, 44, 45, 52, 53, 65, 70, 88, 90, 96, 110, 113, 119, 128, 152, 153, 165, 166, 170, 174, 180, 195}
# gold-only refill for thinned maps (a wolf now and then)
G.MIXES['dom_gold'] = {'gold_row': 3, 'gold_patch': 2, 'gold_guard': 1, 'wolf': 0.5}


# ---------------------------------------------------------------- features (cambc-a3's definitions)
def groups4(camps):
    seen, out = set(), []
    for p in sorted(camps):
        if p in seen:
            continue
        st, mem = [p], []
        seen.add(p)
        while st:
            c = st.pop()
            mem.append(c)
            for dx, dy in G.N4:
                r = (c[0] + dx, c[1] + dy)
                if r in camps and r not in seen:
                    seen.add(r)
                    st.append(r)
        out.append(mem)
    return out


def features(camps):
    """D, Z (denominator all camp gems), D_x, Z_x (monoliths out of both) and the dominant group's / zone's gems."""
    gs = []
    for g in groups4(camps):
        k = collections.Counter(camps[p] for p in g)
        gs.append(dict(gems=sum(GEMS[t] * n for t, n in k.items()), mono=k[MONO] > 0,
                       cx=sum(p[0] for p in g) / len(g), cy=sum(p[1] for p in g) / len(g)))
    tot = sum(g['gems'] for g in gs)
    nm = [g for g in gs if not g['mono']]
    tot_nm = sum(g['gems'] for g in nm)
    dom = max((g['gems'] for g in nm), default=0)
    zone = 0
    for a in nm:
        zone = max(zone, sum(b['gems'] for b in nm if max(abs(a['cx'] - b['cx']), abs(a['cy'] - b['cy'])) <= 6))
    f = dict(D=dom / tot if tot else 0.0, Z=zone / tot if tot else 0.0, D_x=dom / tot_nm if tot_nm else 0.0,
             Z_x=zone / tot_nm if tot_nm else 0.0, gems=tot, dom_gems=dom, zone_gems=zone, groups=len(gs))
    f['maxDZ'] = max(f['D'], f['Z'])
    return f


# ---------------------------------------------------------------- placing the dominant structure
def bfs8(free, srcs):
    d = {p: 0 for p in srcs}
    q, i = list(srcs), 0
    while i < len(q):
        x, y = q[i]
        i += 1
        for dx, dy in G.N8:
            n = (x + dx, y + dy)
            if n not in d and free(n):
                d[n] = d[(x, y)] + 1
                q.append(n)
    return d


def connected4(S):
    S = set(S)
    if not S:
        return False
    st, seen = [next(iter(S))], set()
    while st:
        c = st.pop()
        if c in seen:
            continue
        seen.add(c)
        st += [(c[0] + dx, c[1] + dy) for dx, dy in G.N4 if (c[0] + dx, c[1] + dy) in S]
    return seen == S


def pair_gems(m, tiles):
    cells = set(tiles) | {m.mir(*p) for p in tiles}
    return sum(GEMS[m.camp[p]] for p in cells if p in m.camp)


def all_gems(m):
    return sum(GEMS[t] for t in m.camp.values())


def thin(m, rng, r_max):
    """Remove whole base groups (with their mirror copies) until the map's gems are <= r_max; monoliths go first."""
    idx = [i for i, (tiles, kind) in enumerate(m.groups) if kind != 'island' and pair_gems(m, tiles) > 0]
    rng.shuffle(idx)
    idx.sort(key=lambda i: m.groups[i][1] != 'monolith')
    drop = []
    total = all_gems(m)
    for i in idx:
        if total <= r_max:
            break
        total -= pair_gems(m, m.groups[i][0])
        drop.append(i)
    for i in sorted(drop, reverse=True):
        tiles, _ = m.groups.pop(i)
        for p in tiles:
            m.camp.pop(p, None)
            m.camp.pop(m.mir(*p), None)


def place_dom(m, rng, rec):
    """Add the dominant structure of rec['dom'] in place; RuntimeError if the built features miss the target."""
    t, kind = rec['dom']['t'], rec['dom']['kind']
    strict = rec.get('checks', 1) >= 2
    free = lambda p: m.inb(*p) and m.get(*p) not in (G.WALL, G.HOLE, G.ALTAR)  # noqa: E731
    x0, y0, x1, y1 = m.spawn
    sa = [(x, y) for x in range(x0, x1) for y in range(y0, y1)]
    dA, dB = bfs8(free, sa), bfs8(free, [m.mir(*p) for p in sa])

    def tile_ok(p):
        return (m.inb(*p) and m.get(*p) == G.FLOOR and p not in m.camp and p not in m.protect and m.dspawn(*p) >= 3
                and p in dA and p in dB)

    def ring_ok(S):  # no other camp or altar touches the new cells (it would join the group)
        for x, y in S:
            for dx, dy in G.N8:
                n = (x + dx, y + dy)
                if n not in S and (n in m.camp or (m.inb(*n) and m.get(*n) == G.ALTAR)):
                    return False
        return True

    ratio = lambda p: dA[p] / max(1, dA[p] + dB[p])  # noqa: E731
    cheb = lambda a, b: max(abs(a[0] - b[0]), abs(a[1] - b[1]))  # noqa: E731
    near_axis = [p for p in dA if tile_ok(p) and cheb(p, m.mir(*p)) <= 3]
    area = m.W * m.H
    kmax = max(12, min(60, area // 45))       # clusters in one dominant group (single) or one copy (pair)
    fmax = min(320, 7 * max(10, area // 30))  # gems in a field
    cap = 7 * kmax * (2 if kind == 'single' else 1) if kind != 'zone' else fmax
    base = all_gems(m)
    v2 = rec['dom'].get('v', 1) >= 2
    share = (lambda r: t * r / (1 - 2 * t)) if (v2 and kind == 'pair') else (lambda r: t * r / (1 - t))
    if share(base) > cap:
        thin(m, rng, (cap * (1 - 2 * t) / t if (v2 and kind == 'pair') else cap * (1 - t) / t) * rng.uniform(0.75, 1.0))
    pairs = sum(1 for tiles, k in m.groups if k not in ('island', 'monolith'))
    if pairs < 3:
        G.place_groups(m, rng, 'dom_gold', 3 - pairs + rng.randint(0, 2), strict=strict)
    rest = all_gems(m)
    want = share(rest)                        # gems the structure needs (v2 pair: one copy's)

    snap_camp, snap_groups = dict(m.camp), list(m.groups)

    def restore():
        m.camp.clear()
        m.camp.update(snap_camp)
        m.groups[:] = snap_groups

    def check():  # single/pair: the group itself carries the target; zone: no one group carries most of it
        f = features(m.camp)
        shape = abs(f['D'] - t) <= TOL if kind != 'zone' else f['D'] <= 0.6 * f['Z']
        return abs(f['maxDZ'] - t) <= TOL and shape and G.access_ok(m, True, strict)

    for _ in range(8):
        rng.shuffle(near_axis)
        if kind == 'single':
            k = max(4, min(2 * kmax, round(want / 7)))
            for ax, ay in near_axis[:300]:
                hk = (k + 1) // 2 if not v2 else round((k + 1) / 2 * rng.uniform(0.8, 1.2))
                A = {(ax + dx, ay + dy) for dx, dy in G.blob(rng, max(2, hk))}
                S = A | {m.mir(*p) for p in A}
                if not connected4(S) or not all(tile_ok(p) for p in S) or not ring_ok(S):
                    continue
                for p in S:
                    m.camp[p] = GEM
                pairs_ = sorted({tuple(sorted((p, m.mir(*p)))) for p in S if m.mir(*p) != p})
                if pairs_ and rng.random() < 0.4:  # guards, like the pool's mixed central groups
                    beast = rng.choice([WOLF, WOLF, ELK])
                    for a, b in rng.sample(pairs_, min(len(pairs_), rng.choice([1, 1, 2]))):
                        m.camp[a] = m.camp[b] = beast
                m.groups.append(([p for p in sorted(S) if p <= m.mir(*p)], 'dom'))
                if check():
                    return
                restore()
                if not v2:
                    break
        elif kind == 'pair':
            k = max(4, min(kmax, round(want / 7)))
            band = [p for p in dA if tile_ok(p) and 0.41 <= ratio(p) <= 0.49]
            rng.shuffle(band)
            for ax, ay in band[:300]:
                SA = {(ax + dx, ay + dy) for dx, dy in G.blob(rng, k if not v2 else max(4, round(k * rng.uniform(0.85, 1.15))))}
                SB = {m.mir(*p) for p in SA}
                if SA & SB or not all(tile_ok(p) for p in SA) or not ring_ok(SA | SB):
                    continue
                if any((x + dx, y + dy) in SB for x, y in SA for dx, dy in G.N8):
                    continue
                if not 0.41 <= sum(ratio(p) for p in SA) / len(SA) <= 0.49:
                    continue
                tiles = [(x, y, GEM) for x, y in sorted(SA)]
                if rng.random() < 0.4:
                    j = rng.randrange(len(tiles))
                    tiles[j] = tiles[j][:2] + (rng.choice([WOLF, ELK]),)
                G.put_group(m, tiles, 'dom')
                if check():
                    return
                restore()
                if not v2:
                    break
        else:  # zone: small groups round an anchor near the centre
            if not near_axis:
                break
            a = near_axis[0]
            if m.mir(*a) == a and G.group_ok(m, [(a[0], a[1], GEM)]):  # an axis cluster as the zone's own anchor
                G.put_group(m, [(a[0], a[1], GEM)], 'dom_zone')
            spots = [p for p in dA if tile_ok(p) and cheb(p, a) <= 5 and cheb(m.mir(*p), a) <= 5]
            placed, fails = all_gems(m) - rest, 0
            while placed < want and fails < 200 and spots:
                sx, sy = rng.choice(spots)
                tiles = [(sx + dx, sy + dy, GEM) for dx, dy in G.blob(rng, rng.choice([1, 2, 2, 3]))]
                if rng.random() < 0.25:
                    tiles[-1] = tiles[-1][:2] + (WOLF,)
                if not G.group_ok(m, tiles) or any(cheb((x, y), a) > 5 or cheb(m.mir(x, y), a) > 5 for x, y, _ in tiles):
                    fails += 1
                    continue
                G.put_group(m, tiles, 'dom_zone')
                if not G.access_ok(m, True, strict):
                    G.drop_group(m)
                    fails += 1
                    continue
                placed = all_gems(m) - rest
            if check():
                return
            restore()
    raise RuntimeError(f'no {kind} structure at t={t:.2f}')


_generate = G.generate
_recipes = genbig.recipes


def generate(rec, seed):
    m = _generate(rec, seed)
    if rec.get('dom'):
        place_dom(m, random.Random(seed * 7919 + 29), rec)
    return m


# module level, not under __main__: genbig's pool workers start by forkserver and re-import this script (as __mp_main__)
G.generate = generate


def recipes(n):
    """genbig's fresh recipes plus a dominant structure. Each half (1..n/2, n/2+1..n) gets the same target strata over
    0.30-0.80 in its own order; kinds alternate within a stratum list (single / zone, with pair for low targets)."""
    base = _recipes(n)
    half = n // 2
    r = random.Random(81081)
    out = []
    for h in range(2):
        strata = [0.30 + 0.50 * (j + 0.5) / half for j in range(half)]
        kinds = ['zone' if j % 2 else ('pair' if strata[j] <= 0.45 and j % 4 == 0 else 'single') for j in range(half)]
        order = list(range(half))
        r.shuffle(order)
        for j in order:
            rec = dict(base[len(out)])
            rec['dom'] = dict(t=round(strata[j], 4), kind=kinds[j])
            if len(out) + 1 in V2:
                rec['dom']['v'] = 2
            if strata[j] > 0.5:
                rec['mono'] = 0
            out.append(rec)
    out += [dict(x) for x in base[len(out):]]  # odd n: the last recipe has no structure
    return out


def classify_file(path):
    d = map26a.load(path)
    return features(dict(d['camps']))


if __name__ == '__main__':
    n = sys.argv[1] if len(sys.argv) > 1 else '200'
    jobs = sys.argv[sys.argv.index('--jobs') + 1] if '--jobs' in sys.argv else '6'
    genbig.recipes = recipes
    genbig.FAMILY['fresh'] = (PREFIX, SEED0, OUT)
    sys.argv = ['genbig.py', '--family', 'fresh', '--n', n, '--jobs', jobs, '--install', '--checks', '2']
    genbig.main()
    N = int(n)
    want = {f'{PREFIX}{i:03d}': r for i, r in enumerate(recipes(N), 1)}
    rows, off = {}, []
    for name, rec in sorted(want.items()):
        p = os.path.join(OUT, name + '.map26a')
        if not os.path.exists(p) or not rec.get('dom'):
            continue
        f = classify_file(p)
        meta = json.load(open(os.path.join(OUT, name + '.meta.json')))
        mf = meta['features']
        rows[name] = dict(f, kind=rec['dom']['kind'], target=rec['dom']['t'], W=mf['W'], H=mf['H'], T=mf['T'],
                          s2s=mf['s2s'], mix=rec.get('mix'), mono=rec.get('mono'), seed=meta['seed'])
        if abs(f['maxDZ'] - rec['dom']['t']) > TOL:
            off.append(name)
    json.dump(rows, open(os.path.join(OUT, 'features.json'), 'w'), indent=1)
    cols = ['map', 'half', 'kind', 'target', 'D', 'Z', 'maxDZ', 'D_x', 'Z_x', 'gems', 'dom_gems', 'zone_gems', 'W', 'H',
            'T', 's2s', 'mix', 'mono', 'seed']
    for half, lo, hi in (('dev', 1, N // 2), ('ho', N // 2 + 1, N)):
        names = [k for k in sorted(rows) if lo <= int(k[len(PREFIX):]) <= hi and k not in off]
        open(os.path.join(OUT, f'maplist_{half}.txt'), 'w').write(''.join(x + '\n' for x in names))
        with open(os.path.join(OUT, f'features_{half}.tsv'), 'w') as fh:
            fh.write('\t'.join(cols) + '\n')
            for k in names:
                v = dict(rows[k], map=k, half=half)
                fh.write('\t'.join(f'{v[c]:.4f}' if isinstance(v[c], float) else str(v[c]) for c in cols) + '\n')
    print(f'{len(rows)} classified, {len(off)} off target (left off the lists): {" ".join(off) or "-"}')
