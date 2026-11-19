#!/usr/bin/env python3
"""Map features of CAMBC 2026a .map26a files (engine 1.0.2 camp values), for comparing generated held-out
maps (tools/lab/genmaps.py) with the pool maps. Adapted from condor-work/reports/needs_oracle/feat.py.

usage:
  python3 tools/lab/mapfeat.py MAP.map26a ...            one row per map
  python3 tools/lab/mapfeat.py --compare                 pool (00*, 01*), pathological pool maps and gen_* side by side
  python3 tools/lab/mapfeat.py --json OUT MAP.map26a ... also write the rows as JSON

Columns (team A's view; maps are mirror-symmetric, so team B's view is the same):
  size WxH, T team size, sym (0 x-mirror, 1 y-mirror, 2 rotation), gems/gold = one capture of every camp (both sides),
  grp = camp groups, clu = gem share from gem clusters, heavy = gem share in groups guarded by an elk, golem or monolith,
  mono = gem share of monoliths, dash = gem share reachable only with a dash (no walking path), cry = only with a
  teleport crystal, none = unreachable, s2s = walking distance spawn to spawn ('-' = spawns never meet on foot),
  alt = altar tiles (both sides), alt_d = walking distance to the nearest altar ('d' = dash needed, '-' = none),
  shr = shared altars (equidistant within 10%), wall/hole/bush = % of tiles.

Reach rules (analysis/mechanics-2026-10-20.md 2.7; camps count as passable, since a camp can be killed): walking is
8-way and may cut corners, blocked by walls, holes, altars and the enemy spawn; a dash lands on a walkable tile within
Chebyshev 2 over a middle tile that is not a wall (holes and altars are fine); a crystal (one per trip, bought on
spawn) jumps from any tile reached by walking and dashing to a walkable tile within Chebyshev 3, and the champion walks
and dashes on from there. Version 1 (legacy=True, VERSION 1) blocked dashes over altars and stopped crystal reach at the
landing tile; the map generators' validators keep it so that every existing seed builds the same map.
"""
import glob
import json
import os
import statistics
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402

VERSION = 2  # reach rules (see above); features carry it as 'v'
GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
STR = {0: 20, 1: 60, 2: 0, 3: 0, 4: 200, 5: 120}
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def analyse(d, name='?', legacy=False):
    """Features of a decoded map (map26a.decode or genmaps.decode_like format). legacy=True: version 1 reach rules
    (no dash over an altar, no walking after a crystal jump), for validators that must keep old seeds' maps."""
    W, H, T = d['W'], d['H'], d['champs_per_team']
    wall, hole, alt, camps = d['wall'], d['hole'], d['altar'], d['camps']
    spA, spB = d['spawnA'], d['spawnB']

    def land(p, esp):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in wall and p not in hole and p not in alt and p not in esp

    def bfs(starts, esp, dash=False):
        dist = {s: 0 for s in starts}
        dq = deque(starts)
        while dq:
            c = dq.popleft()
            dc = dist[c]
            for dx, dy in N8:
                n = (c[0] + dx, c[1] + dy)
                if n not in dist and land(n, esp):
                    dist[n] = dc + 1
                    dq.append(n)
            if dash:
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        if max(abs(dx), abs(dy)) != 2:
                            continue
                        n = (c[0] + dx, c[1] + dy)
                        if n in dist or not land(n, esp):
                            continue
                        for mx, my in N8:
                            m = (c[0] + mx, c[1] + my)
                            if (max(abs(m[0] - n[0]), abs(m[1] - n[1])) == 1 and 0 <= m[0] < W and 0 <= m[1] < H
                                    and m not in wall and not (legacy and m in alt)):
                                dist[n] = dc + 1
                                dq.append(n)
                                break
        return dist

    gid, groups = {}, []
    for p in sorted(camps):
        if p in gid:
            continue
        g, st = [p], [p]
        gid[p] = len(groups)
        while st:
            c = st.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n in camps and n not in gid:
                    gid[n] = len(groups)
                    g.append(n)
                    st.append(n)
        groups.append(g)
    wA, wB = bfs(list(spA), spB), bfs(list(spB), spA)
    dA = bfs(list(spA), spB, True)
    cry = set(dA)
    for c in list(dA):
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                n = (c[0] + dx, c[1] + dy)
                if land(n, spB):
                    cry.add(n)
    if not legacy and any(not any(p in cry for p in g) for g in groups):
        cry = set(bfs(list(cry), spB, True))  # walk and dash on from the landing tiles
    G = []
    for g in groups:
        types = [camps[p] for p in g]
        acc = ('walk' if any(p in wA for p in g) else 'dash' if any(p in dA for p in g)
               else 'cry' if any(p in cry for p in g) else 'none')
        G.append(dict(gem=sum(GEMS[t] for t in types), gold=sum(GOLD[t] for t in types), str=max(STR[t] for t in types),
                      cg=sum(7 for t in types if t == 2), mg=sum(200 for t in types if t == 4), acc=acc))
    tot = sum(x['gem'] for x in G)
    Tt = max(1, tot)
    share = lambda f: round(sum(x['gem'] for x in G if f(x)) / Tt, 2)  # noqa: E731
    adj = [n for n in wA if any((n[0] + dx, n[1] + dy) in spB for dx, dy in N8)]
    s2s = min(wA[n] for n in adj) + 1 if adj else None
    # altars: walking distance from each spawn to the nearest tile next to the altar
    alt_d, alt_dash, shared = None, False, 0
    for a in alt:
        nb = [(a[0] + dx, a[1] + dy) for dx, dy in N8]
        da = min([wA[p] for p in nb if p in wA], default=None)
        db = min([wB[p] for p in nb if p in wB], default=None)
        if da is None and any(p in dA for p in nb):
            alt_dash = True
        if da is not None:
            alt_d = da if alt_d is None else min(alt_d, da)
            if db is not None and abs(da - db) <= 0.1 * max(da, db):
                shared += 1
    n = W * H
    return dict(map=name, W=W, H=H, T=T, sym=d['symmetry'], gems=tot, gold=sum(x['gold'] for x in G), grp=len(G),
                clu=round(sum(x['cg'] for x in G) / Tt, 2), heavy=share(lambda x: x['str'] >= 60),
                mono=round(sum(x['mg'] for x in G) / Tt, 2), dash=share(lambda x: x['acc'] == 'dash'),
                cry=share(lambda x: x['acc'] == 'cry'), none=share(lambda x: x['acc'] == 'none'), s2s=s2s,
                alt=len(alt), alt_d=alt_d if alt_d is not None else ('d' if alt_dash else None), shr=shared,
                wall=round(100 * len(wall) / n), hole=round(100 * len(hole) / n), bush=round(100 * len(d['bush']) / n),
                v=1 if legacy else VERSION)


def analyse_path(path):
    return analyse(map26a.load(path), os.path.basename(path).replace('.map26a', ''))


COLS = ['map', 'size', 'T', 'sym', 'gems', 'gold', 'grp', 'clu', 'heavy', 'mono', 'dash', 'cry', 'none', 's2s', 'alt',
        'alt_d', 'shr', 'wall', 'hole', 'bush']


def row(r):
    r = dict(r, size=f"{r['W']}x{r['H']}")
    return ['-' if r[k] is None else str(r[k]) for k in COLS]


def table(rows):
    cells = [COLS] + [row(r) for r in rows]
    w = [max(len(c[i]) for c in cells) for i in range(len(COLS))]
    return '\n'.join('  '.join(c[i].rjust(w[i]) if i else c[i].ljust(w[i]) for i in range(len(COLS))) for c in cells)


def dist_line(name, rows, k):
    v = [r[k] for r in rows if isinstance(r[k], (int, float))]
    if not v:
        return f'{name:5s} -'
    q = statistics.quantiles(v, n=4) if len(v) > 1 else [v[0]] * 3
    fmt = (lambda x: f'{x:.2f}') if any(isinstance(x, float) for x in v) else (lambda x: f'{x:.0f}')
    return f'{name:5s} min {fmt(min(v))}  q1 {fmt(q[0])}  med {fmt(q[1])}  q3 {fmt(q[2])}  max {fmt(max(v))}'


def compare(maps_dir='/data/zw4424/work301/maps'):
    paths = sorted(glob.glob(os.path.join(maps_dir, '*.map26a')))
    rows = [analyse_path(p) for p in paths]
    pool = [r for r in rows if r['map'][:2] in ('00', '01')]
    gen = [r for r in rows if r['map'].startswith('gen_')]
    patho = [r for r in rows if r not in pool and r not in gen]
    out = ['## pool maps (00*, 01*)', table(pool), '', '## pathological pool maps', table(patho), '',
           '## generated held-out maps (gen_*)', table(gen), '', '## distributions: pool vs generated']
    for r in rows:
        r['area'] = r['W'] * r['H']
        r['alt_dn'] = r['alt_d'] if isinstance(r['alt_d'], int) else None
    for k in ('area', 'T', 'gems', 'gold', 'grp', 'clu', 'heavy', 'mono', 'dash', 's2s', 'alt', 'alt_dn', 'wall', 'hole', 'bush'):
        out.append(f'{k}:')
        out.append('  ' + dist_line('pool', pool, k))
        out.append('  ' + dist_line('gen', gen, k))
    return '\n'.join(out), rows


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--compare':
        text, rows = compare(*a[1:2])
        print(text)
        sys.exit(0)
    js = None
    if a and a[0] == '--json':
        if len(a) < 3:
            sys.exit('usage: mapfeat.py --json OUT MAP.map26a ... (no MAP given after OUT)')
        js, a = a[1], a[2:]
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import safewrite
        safewrite.check_out(js, 'mapfeat.py')
    rows = [analyse_path(p) for p in a]
    print(table(rows))
    if js:
        json.dump(rows, open(js, 'w'))
