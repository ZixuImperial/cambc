#!/usr/bin/env python3
"""Ideology maps: seeded variants of the live maps we lose most on (cambc-b3, 25 Oct; reports/heavyloss_summary_1025.md).

Each kind copies the idea of one live pool map, not its layout: sizes, team size, counts and positions are drawn per map,
so a bot tuned on one variant still meets new geometry. Built and checked with tools/lab/genmaps.py's machinery (mirror
symmetry by the engine, MapBuilder build, decode check, mapfeat features).
  lanes        01corridors: parallel walled lanes joined only at the spawn rows; every camp group sits on the middle rows
               (one per lane, merged with its mirror row); a monolith group in the centre lane; the altars in a camp-free
               lane; a few dashable hole segments in the lane walls.
  arena        01elk_arena: spawns close together facing a walled central arena that holds the only gem group (elks and
               gem clusters) and the altars; gold-only groups elsewhere.
  monocontest  00contest: (nearly) all gems in two monoliths on the off-diagonal, equally far from both spawns; altars in
               a central bush box; gold elsewhere.
  hooks        01hooks: a small map; a central walled box with the altar, elk+gem groups and gold; each side's elk group at
               the end of a hooked wall pocket; scarce value.
  corners      00corners: spawns at the middle of the left and right edges; altars in the four corners and one central;
               many small own-side groups; hole bands near one edge.
  dashcentre   00gemfight: a big wolf+gem group and the altars inside a one-tile ring of holes with two far gaps (short by
               dash, long on foot); small groups outside.
  swirl        00swirl: spawns about 12 apart near the centre; two spiral hole bands from the corners; many mixed groups.
  bossaltar    01boss_battle: a wall band across the middle whose only gap holds the single altar beside a monolith pair;
               many elk groups on each side.

usage: python3 -I tools/lab/genideo.py [--kinds lanes,arena,...] [--n 4] [--outdir /data/zw4424/genmaps_i]
                                       [--repo-maps] [--install] [--seed-base 7000000]
  outputs <name>.{json,map26a,meta.json,txt}, index.json, maplist.txt, previews.txt in the outdir; names gen_i_<kind>_NN.
  --repo-maps copies the .map26a files into the repo's maps/ directory; --install copies them into
  /data/zw4424/work301/maps (local abl.sh runs: `sh tools/lab/abl.sh A B NAME /data/zw4424/genmaps_i/maplist.txt`).
  Every name starts with gen_, so abl.sh's default list never changes; sprt.py does not use this family.
  Seeds: seed-base + 100000 x kind + 1000 x i + attempt (7,000,000+; gen_u uses 5,000,000+, gen_up 6,000,000+).
"""
import argparse
import json
import os
import random
import shutil
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import mapfeat  # noqa: E402

FLOOR, WALL, HOLE, BUSH, ALTAR = G.FLOOR, G.WALL, G.HOLE, G.BUSH, G.ALTAR
WOLF, ELK, GEM, GOLD, MONO, GOLEM = G.WOLF, G.ELK, G.GEM, G.GOLD, G.MONO, G.GOLEM
REPO_MAPS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'maps')
INSTALL = '/data/zw4424/work301/maps'
CH = {'w': WOLF, 'e': ELK, 'g': GEM, '$': GOLD, 'M': MONO, 'G': GOLEM}

# small groups as rows of characters ('.' = no camp); every camp of a template is 4-connected to the others
SMALL = {
    'gold': ['$$'], 'gold3': ['$$$'], 'gold_l': ['$$', '$.'], 'wolf_gold': ['w$'], 'wolf_gold2': ['$ww$'],
    'elk_gold': ['e$'], 'elk_gem': ['eg'], 'elk_gem2': ['ge', '.g'], 'elk_pair': ['ee'], 'elk_pair_gold': ['ee', '$g'],
    'wolf_elk_gem': ['weg'], 'elk_wolf': ['ew', 'e.'], 'gem_wolf': ['gww$'], 'elk_guard': ['.g', 'eg', '.g'],
    'wolf_pack': ['ww', 'w.'], 'elk_gold2': ['e$', '$.'],
}


def tiles_of(rows, x, y):
    out = []
    for dy, row in enumerate(rows):
        for dx, c in enumerate(row):
            if c in CH:
                out.append((x + dx, y + dy, CH[c]))
    return out


def rect(m, x0, y0, x1, y1, v, prot=False):
    for x in range(x0, x1):
        for y in range(y0, y1):
            if m.inb(x, y):
                m.put(x, y, v)
                if prot:
                    m.prot(x, y)


def free_for_group(m, tiles, gap=1):
    """Tiles are floor, off both spawns (3+), and no other camp or altar within `gap` (Chebyshev) of the group, its mirror
    copy kept apart too (or the group lies on itself under the mirror)."""
    own = {(x, y) for x, y, _ in tiles}
    for x, y, _ in tiles:
        if not m.inb(x, y) or m.get(x, y) != FLOOR or (x, y) in m.camp or m.dspawn(x, y) < 3:
            return False
        for dx in range(-gap, gap + 1):
            for dy in range(-gap, gap + 1):
                n = (x + dx, y + dy)
                if n in own:
                    continue
                if n in m.camp or (m.inb(*n) and m.get(*n) == ALTAR):
                    return False
    mirrored = {m.mir(x, y) for x, y in own}
    if mirrored & own:
        return mirrored == own
    return all(max(abs(a - c), abs(b - d)) > gap for a, b in mirrored for c, d in own)


def scatter(m, rng, names, n, ok=lambda x, y: True, tries=300, gap=1):
    """Place n small groups (template names drawn from `names`) at random anchors where ok(x, y) holds."""
    placed = 0
    cells = [(x, y) for x in range(m.W) for y in range(m.H) if ok(x, y) and m.get(x, y) == FLOOR]
    if not cells:
        return 0
    for _ in range(n):
        for _ in range(tries):
            name = rng.choice(names)
            rows = SMALL[name]
            if rng.random() < 0.5:  # transpose for variety
                w = max(len(r) for r in rows)
                rows = [''.join(r[i] if i < len(r) else '.' for r in rows) for i in range(w)]
            x, y = rng.choice(cells)
            t = tiles_of(rows, x, y)
            if t and all(ok(a, b) for a, b, _ in t) and free_for_group(m, t, gap):
                G.put_group(m, t, name)
                placed += 1
                break
    return placed


def walk_reach(m):
    return m.bfs('A')


# ------------------------------------------------------------------------------------------------ kinds
def gen_lanes(rng):
    n = rng.choice([9, 11, 13, 13, 15])
    lw = rng.choice([3, 3, 3, 4])
    W = n * (lw + 1) - 1
    H = rng.choice([34, 36, 40, 40, 44])
    T = rng.choice([4, 5, 5])
    m = G.Map(W, H, 1, T)
    home = 3
    for k in range(1, n):
        x = k * (lw + 1) - 1
        rect(m, x, home, x + 1, H // 2, WALL)
    c = n // 2
    lx = lambda i: i * (lw + 1)  # noqa: E731
    x0 = lx(c) + (lw - 3) // 2
    m.spawn = (x0, 0, x0 + 3, 3)
    yb = rng.choice([home, home, home + 1])
    if rng.random() < 0.7:
        for i in range(n):
            rect(m, lx(i), yb, lx(i) + lw, yb + 1, BUSH)
    if rng.random() < 0.7:
        for i in range(n):
            rect(m, lx(i), H // 2 - 3, lx(i) + lw, H // 2 - 2, BUSH)
    y = H // 2 - 1
    side = rng.choice([-1, 1])
    alane = c + side * rng.randint(2, max(2, c - 1))
    ax = lx(alane) + lw // 2
    m.put(ax, y, ALTAR)
    m.altars.append((ax, y))
    centre = ['g', 'M', 'g'] + (['g'] if lw == 4 else [])
    near = ['geg', 'e$e', 'gew', '$e$', 'eeg', 'ge$']
    far = ['w$w', '$w.', '$ww', 'w$.', '$e$', 'w$$', '.$w']
    for i in range(n):
        if i == alane:
            continue
        d = abs(i - c)
        row = ''.join(centre) if d == 0 else rng.choice(near if d <= 3 else far)
        row = (row + '.' * lw)[:lw] if len(row) < lw else row[:lw]
        if lw == 4 and d:
            row = row[:3] + rng.choice(['.', '$', 'w'])
        t = [(lx(i) + j, y, CH[ch]) for j, ch in enumerate(row) if ch in CH]
        if t:
            G.put_group(m, t, 'lane_%d' % i)
    for _ in range(rng.randint(2, 5)):  # dashable hole segments in lane walls
        k = rng.randint(1, n - 1)
        xh = k * (lw + 1) - 1
        y0 = rng.randint(home + 3, max(home + 3, H // 2 - 6))
        rect(m, xh, y0, xh + 1, y0 + 3, HOLE)
    return m


def gen_arena(rng):
    S = rng.choice([40, 44, 46, 50, 54])
    T = rng.choice([4, 5, 5])
    m = G.Map(S, S, 2, T)
    cx = cy = (S - 1) / 2
    gap = rng.randint(7, 11)  # spawn-to-centre
    sw = 4 if T == 5 else 3
    x0 = int(cx - gap - sw + 1)
    y0 = int(cy - sw / 2 + 0.5)
    m.spawn = (x0, y0, x0 + sw, y0 + sw)
    G.t_open(m, rng, 0.8)
    R = rng.randint(5, 7)
    ix, iy = int(cx), int(cy)
    for x in range(ix - R - 1, ix + R + 3):  # arena: walls on the top and bottom (both mirror copies), open toward spawns
        for y in range(iy - R - 1, iy + R + 3):
            if m.inb(x, y):
                m.put(x, y, FLOOR)
    for x in range(ix - R + 2, ix + R):
        for yy in (iy - R, iy - R + 1):
            m.put(x, yy, WALL if rng.random() < 0.85 or yy == iy - R else BUSH)
    for x in range(ix - R + 3, ix + R - 1):
        if m.get(x, iy - R + 2) == FLOOR:
            m.put(x, iy - R + 2, BUSH)
    clear = lambda x, y: m.cheb_rect(m.rectA(), x, y) > 1 and m.cheb_rect(m.rectB(), x, y) > 1  # noqa: E731
    for x in range(m.spawn[0] - 1, m.spawn[2] + 1):
        for y in range(m.spawn[1] - 1, m.spawn[3] + 1):
            if m.inb(x, y):
                m.put(x, y, FLOOR)
    # the central group: elks and gem clusters around the centre (its own mirror image)
    n_elk = rng.choice([1, 1, 2])
    blob = G.blob(rng, rng.randint(4, 7))
    tiles = {}
    for dx, dy in blob:  # gems on the blob and its mirror first, then elks (and their mirrors) win, so the guard survives
        p = (ix + dx, iy + dy)
        tiles[p] = tiles[m.mir(*p)] = GEM
    for p in [(ix + dx, iy + dy) for dx, dy in blob][:n_elk]:
        tiles[p] = tiles[m.mir(*p)] = ELK
    t = [(x, y, v) for (x, y), v in tiles.items() if m.inb(x, y) and m.get(x, y) == FLOOR]
    G.put_group(m, t, 'centre')
    # make the merged centre one 4-connected group: fill tiles between a camp and its mirror if needed
    comp = components(m)
    cents = {comp[(x, y)] for x, y, _ in t if (x, y) in comp}
    if len(cents) > 1:
        raise RuntimeError('centre split')
    ax, ay = ix - R + 3, iy - R + 3
    if m.get(ax, ay) != FLOOR or (ax, ay) in m.camp:
        raise RuntimeError('altar spot')
    m.put(ax, ay, ALTAR)
    m.altars.append((ax, ay))
    scatter(m, rng, ['gold', 'gold', 'gold3', 'gold_l', 'wolf_gold'], rng.randint(7, 12),
            ok=lambda x, y: max(abs(x - cx), abs(y - cy)) > R + 3 and clear(x, y))
    return m


def gen_monocontest(rng):
    S = rng.choice([44, 48, 50, 56])
    T = rng.choice([4, 5, 5])
    m = G.Map(S, S, 2, T)
    sw = 3
    off = rng.randint(2, 4)
    m.spawn = (off, off, off + sw, off + sw)
    G.t_open(m, rng, 0.6)
    ix = iy = (S - 1) // 2
    r = rng.randint(3, 4)
    for x in range(ix - r - 1, ix + r + 3):
        for y in range(iy - r - 1, iy + r + 3):
            if m.inb(x, y):
                m.put(x, y, FLOOR)
    for x in range(ix - r, ix + r + 2):  # bush box with a wall on one side of each mirror copy
        m.put(x, iy - r, BUSH)
        m.put(ix - r, x - ix + iy, BUSH)
    for x in range(ix - r - 1, ix + r + 1):
        if rng.random() < 0.75:
            m.put(x, iy - r - 1, WALL)
    m.put(ix, iy, ALTAR)
    m.altars.append((ix, iy))
    for x in range(m.spawn[0] - 1, m.spawn[2] + 1):
        for y in range(m.spawn[1] - 1, m.spawn[3] + 1):
            m.put(x, y, FLOOR)
    # monoliths on the off-diagonal: equally far from both spawns
    for _ in range(200):
        dmono = rng.randint(6, 10)
        mx, my = ix + dmono, iy - dmono + rng.randint(-1, 1)
        if m.inb(mx, my) and m.get(mx, my) == FLOOR and m.dspawn(mx, my) >= 6:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if m.inb(mx + dx, my + dy) and m.get(mx + dx, my + dy) != ALTAR:
                        m.put(mx + dx, my + dy, FLOOR)
            if rng.random() < 0.7:  # cover wall on the monolith's left
                rect(m, mx - 4, my - 3, mx - 3, my + 2, WALL)
            G.put_group(m, [(mx, my, MONO)], 'monolith')
            break
    else:
        raise RuntimeError('no monolith spot')
    scatter(m, rng, ['gold', 'gold', 'gold3', 'gold_l'], rng.randint(8, 12),
            ok=lambda x, y: max(abs(x - ix), abs(y - iy)) > r + 2)
    return m


def gen_hooks(rng):
    S = rng.choice([31, 33, 35, 37, 39])
    T = rng.choice([4, 4, 5])
    m = G.Map(S, S, 2, T)
    m.spawn = (1, 1, 4, 4)
    c = (S - 1) // 2
    b = rng.randint(3, 4)
    # central box: walls on the left and right (mirrors fill the other), openings top and bottom
    for y in range(c - b, c + b + 1):
        m.put(c - b - 1, y, WALL)
    for x in range(c - b - 1, c - 1):
        m.put(x, c - b - 1, WALL)
    m.put(c, c, ALTAR)
    m.altars.append((c, c))
    G.put_group(m, [(c, c - 2, GEM), (c, c - 3, ELK)], 'box_elk')
    G.put_group(m, [(c - 2, c - 3, GOLD), (c - 2, c - 2, GOLD)], 'box_gold')
    # hooked pockets: an L wall with the elk+gem group in its crook, one per side (mirror copy is the enemy's)
    for _ in range(100):
        hx, hy = rng.randint(c - b - 7, c - 2), rng.randint(5, c - b - 2)
        L = rng.randint(4, 7)
        cells = [(hx + i, hy) for i in range(L)] + [(hx + L - 1, hy + j) for j in range(1, 4)]
        if any(not m.inb(*p) or m.get(*p) != FLOOR or m.dspawn(*p) < 3 for p in cells):
            continue
        for p in cells:
            m.put(p[0], p[1], WALL)
        t = [(hx + L - 3, hy + 1, ELK), (hx + L - 3, hy + 2, GEM)]
        if free_for_group(m, t):
            G.put_group(m, t, 'hook_elk')
            break
        for p in cells:
            m.put(p[0], p[1], FLOOR)
    else:
        raise RuntimeError('no hook')
    for _ in range(rng.randint(1, 3)):  # extra L walls
        x, y, L = rng.randint(4, S - 6), rng.randint(4, S - 6), rng.randint(3, 6)
        if rng.random() < 0.5:
            cells = [(x + i, y) for i in range(L)] + [(x, y + j) for j in range(1, 3)]
        else:
            cells = [(x, y + i) for i in range(L)] + [(x + j, y + L - 1) for j in range(1, 3)]
        if all(m.inb(*p) and m.get(*p) == FLOOR and m.dspawn(*p) >= 2 and p not in m.camp for p in cells):
            for p in cells:
                m.put(p[0], p[1], WALL)
    scatter(m, rng, ['gold', 'gold_l', 'wolf_gold', 'elk_gem'], rng.randint(2, 4),
            ok=lambda x, y: max(abs(x - c), abs(y - c)) > b + 2)
    return m


def gen_corners(rng):
    S = rng.choice([59, 63, 67, 71])
    T = rng.choice([4, 5, 5])
    m = G.Map(S, S, 0, T)
    c = (S - 1) // 2
    sx = rng.randint(10, 14)
    m.spawn = (sx, c - 1, sx + 3, c + 2)
    for (x, y) in ((1, 1), (1, S - 2)):
        m.put(x, y, ALTAR)
        m.altars.append((x, y))
    m.put(c, c + 1, ALTAR)
    m.altars.append((c, c + 1))
    for y in range(0, rng.randint(9, 13)):  # hole band near the top edge
        hx = c - rng.randint(8, 11)
        m.put(hx, y, HOLE)
        m.put(hx + 1, y, HOLE)
    G.t_open(m, rng, 0.5)
    for x in range(m.spawn[0] - 1, m.spawn[2] + 1):
        for y in range(m.spawn[1] - 1, m.spawn[3] + 1):
            m.put(x, y, FLOOR)
    for (x, y) in m.altars:
        for dx, dy in G.N8:
            if m.inb(x + dx, y + dy) and m.get(x + dx, y + dy) in (WALL, HOLE):
                m.put(x + dx, y + dy, FLOOR)
    G.put_group(m, [(c - 2, c - 1, ELK), (c - 1, c - 1, GEM)], 'centre_eg')
    G.put_group(m, [(c - 2, c + 3, GOLD), (c - 1, c + 3, WOLF)], 'centre_wg')
    scatter(m, rng, ['wolf_gold', 'elk_gold', 'elk_gem', 'wolf_elk_gem', 'elk_pair_gold', 'elk_gem2', 'gold'],
            rng.randint(10, 15), ok=lambda x, y: x < c - 2)
    return m


def gen_dashcentre(rng):
    S = rng.choice([30, 32, 34, 36, 38])
    T = rng.choice([4, 4, 5])
    m = G.Map(S, S, 2, T)
    m.spawn = (1, 1, 4, 4)
    c = (S - 1) / 2
    R = rng.randint(int(S * 0.3), int(S * 0.36))
    ic = int(c)
    ring = set()
    for x in range(S):
        for y in range(S):
            d = max(abs(x - c), abs(y - c))
            if abs(d - R) < 0.5 or (abs(abs(x - c) + abs(y - c) - 1.35 * R) < 0.5 and d < R + 1):
                ring.add((x, y))
    # gaps: two far openings, perpendicular to the spawn diagonal (mirror pair)
    gx, gy = int(c + R), int(c - R)
    for p in list(ring):
        if max(abs(p[0] - gx), abs(p[1] - gy)) <= 1:
            ring.discard(p)
    for p in ring:
        m.put(p[0], p[1], HOLE)
    t = [(ic + dx, ic + dy, GEM) for dx, dy in G.blob(rng, rng.randint(5, 8))]
    for i in range(min(2, len(t))):
        t[i] = (t[i][0], t[i][1], WOLF)
    t = [(x, y, v) for x, y, v in t if m.get(x, y) == FLOOR]
    G.put_group(m, t, 'centre')
    comp = components(m)
    if len({comp[(x, y)] for x, y, _ in t}) > 1:
        raise RuntimeError('centre split')
    for _ in range(100):
        ax, ay = ic + rng.randint(-R + 2, R - 2), ic + rng.randint(-R + 2, R - 2)
        if m.get(ax, ay) == FLOOR and (ax, ay) not in m.camp and all((ax + dx, ay + dy) not in m.camp for dx, dy in G.N8) \
                and m.mir(ax, ay) != (ax, ay) and max(abs(ax - ic), abs(ay - ic)) >= 3:
            m.put(ax, ay, ALTAR)
            m.altars.append((ax, ay))
            break
    else:
        raise RuntimeError('no altar inside')
    for _ in range(int(S * S * 0.004)):
        G.paint_blob(m, rng, BUSH, rng.randint(3, 6), rng.randrange(S), rng.randrange(S), only=FLOOR)
    for x in range(0, 6):
        for y in range(0, 6):
            m.put(x, y, FLOOR)
    scatter(m, rng, ['elk_gem', 'gold', 'wolf_gold', 'elk_gold', 'gem_wolf'], rng.randint(4, 7),
            ok=lambda x, y: max(abs(x - c), abs(y - c)) > R + 1)
    return m


def gen_swirl(rng):
    W, H = rng.choice([(45, 30), (48, 32), (42, 30), (50, 34)])
    T = rng.choice([4, 4, 5])
    m = G.Map(W, H, 2, T)
    cx, cy = (W - 1) / 2, (H - 1) / 2
    sx = int(cx + rng.randint(3, 5))
    sy = int(cy - rng.randint(6, 8))
    m.spawn = (sx, sy, sx + 3, sy + 3)
    band = rng.randint(3, 5)
    for x in range(W):  # spiral arm: a thick curved band from the top-left corner sweeping around
        for y in range(H):
            u, v = x / W, y / H
            r = ((u - 0.5) ** 2 + (v - 0.5) ** 2) ** 0.5
            if r > 0.36 and (u + v) < 0.85 and r < 0.36 + band / W * 1.6:
                m.put(x, y, HOLE)
    for _ in range(rng.randint(2, 3)):
        x, y, L = sx + rng.randint(-6, 6), sy + rng.randint(3, 7), rng.randint(4, 7)
        cells = [(x + i, y) for i in range(L)] + [(x + L - 1, y + j) for j in range(1, 4)]
        if all(m.inb(*p) and m.get(*p) == FLOOR and m.dspawn(*p) >= 2 for p in cells):
            for p in cells:
                m.put(p[0], p[1], WALL)
    for x in range(m.spawn[0] - 1, m.spawn[2] + 1):
        for y in range(m.spawn[1] - 1, m.spawn[3] + 1):
            m.put(x, y, FLOOR)
    for _ in range(100):
        ax, ay = int(cx + rng.randint(-3, 3)), int(cy + rng.randint(-6, -2))
        if m.get(ax, ay) == FLOOR and m.dspawn(ax, ay) >= 3 and m.mir(ax, ay) != (ax, ay):
            m.put(ax, ay, ALTAR)
            m.altars.append((ax, ay))
            break
    else:
        raise RuntimeError('no altar')
    scatter(m, rng, ['elk_pair', 'elk_gem', 'gem_wolf', 'wolf_gold2', 'elk_gold', 'elk_guard', 'wolf_pack', 'gold'],
            rng.randint(9, 13), ok=lambda x, y: True)
    return m


def gen_bossaltar(rng):
    W = rng.choice([44, 48, 50, 54])
    H = rng.choice([37, 39, 41, 45])
    T = rng.choice([4, 5, 5])
    m = G.Map(W, H, 1, T)
    c = (H - 1) // 2  # mirror-fixed row
    sw, sh = (5, 2) if T == 5 else (3, 3)  # a 4x2 spawn for 4 champions failed at game start (engine error 7)
    sx = (W - sw) // 2
    m.spawn = (sx, 0, sx + sw, sh)
    G.t_open(m, rng, 0.4)
    # the band: rows c-1 and c (the mirror of c-1 is c+1), crossed only beside the monoliths
    rect(m, 0, c - 1, W, c + 1, WALL)
    gx = rng.randint(W // 2 - 6, W // 2 + 2)
    m.put(gx, c - 1, BUSH)
    m.put(gx + 1, c - 1, FLOOR)
    m.put(gx + 2, c - 1, HOLE)
    m.put(gx + 3, c - 1, HOLE)
    for x in (gx, gx + 1, gx + 2):
        m.put(x, c, FLOOR)
    m.put(gx + 3, c, ALTAR)
    m.altars.append((gx + 3, c))
    if rng.random() < 0.3:  # sometimes one free tribute tile; otherwise the altar is reached only over a monolith tile
        m.put(gx + 4, c - 1, FLOOR)
    G.put_group(m, [(gx + 1, c, MONO), (gx + 2, c, MONO)], 'boss')
    for x in range(m.spawn[0] - 1, m.spawn[2] + 1):
        for y in range(0, m.spawn[3] + 1):
            m.put(x, y, FLOOR)
    scatter(m, rng, ['elk_gold', 'elk_wolf', 'elk_pair_gold', 'elk_gold2', 'wolf_gold', 'elk_guard', 'gold', 'elk_gem'],
            rng.randint(10, 15), ok=lambda x, y: y < c - 2)
    return m


KINDS = {'lanes': gen_lanes, 'arena': gen_arena, 'monocontest': gen_monocontest, 'hooks': gen_hooks,
         'corners': gen_corners, 'dashcentre': gen_dashcentre, 'swirl': gen_swirl, 'bossaltar': gen_bossaltar}


# ------------------------------------------------------------------------------------------------ checks and build
def components(m):
    comp, k = {}, 0
    for p in m.camp:
        if p in comp:
            continue
        dq = deque([p])
        comp[p] = k
        while dq:
            x, y = dq.popleft()
            for dx, dy in G.N4:
                n = (x + dx, y + dy)
                if n in m.camp and n not in comp:
                    comp[n] = k
                    dq.append(n)
        k += 1
    return comp


def check(m, kind):
    for y in range(m.H):
        for x in range(m.W):
            if m.get(x, y) != m.get(*m.mir(x, y)):
                return False, 'asymmetric terrain'
    for p, t in m.camp.items():
        if m.camp.get(m.mir(*p)) != t:
            return False, 'asymmetric camps'
        if m.get(*p) != FLOOR or m.dspawn(*p) == 0:
            return False, 'camp on obstacle or spawn'
    for r in (m.rectA(), m.rectB()):
        for x in range(r[0], r[2]):
            for y in range(r[1], r[3]):
                if not m.inb(x, y) or m.get(x, y) != FLOOR or (x, y) in m.camp:
                    return False, 'spawn obstructed'
    if not m.altars:
        return False, 'no altar'
    if not (30 <= m.W <= 100 and 30 <= m.H <= 100):
        return False, 'size'
    comp = components(m)  # two groups of the design must not merge
    owner = {}
    for i, (tiles, _) in enumerate(m.groups):
        for x, y in tiles:
            for p in ((x, y), m.mir(x, y)):
                c = comp.get(p)
                if c is None:
                    return False, 'missing camp'
                if owner.setdefault(c, i) != i:
                    return False, 'groups merged'
    f = mapfeat.analyse(G.decode_like(m), 'design')
    if f['s2s'] is None:
        return False, 'spawns not connected'
    if not isinstance(f['alt_d'], int):
        return False, 'no walkable altar (alt_d=%s)' % f['alt_d']
    if f['none'] > 0 or f['cry'] > 0:
        return False, 'unreachable camps none=%s cry=%s' % (f['none'], f['cry'])
    if f['gems'] < 40 or f['grp'] < 4:
        return False, 'too little gems=%s grp=%s' % (f['gems'], f['grp'])
    if kind == 'arena' and f['heavy'] < 0.5:
        return False, 'arena centre has no elk guard (heavy=%s)' % f['heavy']
    return True, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kinds', default=','.join(KINDS))
    ap.add_argument('--n', type=int, default=4)
    ap.add_argument('--outdir', default='/data/zw4424/genmaps_i')
    ap.add_argument('--seed-base', type=int, default=7000000)
    ap.add_argument('--repo-maps', action='store_true')
    ap.add_argument('--install', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    ip = os.path.join(a.outdir, 'index.json')
    index = json.load(open(ip)) if os.path.exists(ip) else {}
    for ki, kind in enumerate(a.kinds.split(',')):
        gen = KINDS[kind]
        for i in range(1, a.n + 1):
            name = 'gen_i_%s_%02d' % (kind, i)
            for attempt in range(200):
                seed = a.seed_base + 100000 * list(KINDS).index(kind) + 1000 * i + attempt
                try:
                    m = gen(random.Random(seed))
                    ok, info = check(m, kind)
                except (RuntimeError, IndexError) as e:
                    ok, info = False, str(e)
                if ok:
                    break
            else:
                print('%s: no valid map in 200 attempts (last: %s)' % (name, info), file=sys.stderr)
                continue
            sp, mp = os.path.join(a.outdir, name + '.json'), os.path.join(a.outdir, name + '.map26a')
            json.dump(G.spec_of(m), open(sp, 'w'))
            try:
                d = G.build_and_check(m, sp, mp)
            except (RuntimeError, AssertionError) as e:
                print('%s: build failed: %s' % (name, e), file=sys.stderr)
                continue
            f = mapfeat.analyse(d, name)
            meta = dict(name=name, kind=kind, seed=seed, features=f)
            json.dump(meta, open(os.path.join(a.outdir, name + '.meta.json'), 'w'), indent=1)
            open(os.path.join(a.outdir, name + '.txt'), 'w').write(m.ascii() + '\n')
            index[name] = meta
            print('%s seed %d %dx%d T%d sym%d: gems %d gold %d groups %d heavy %.2f mono %.2f dash %.2f s2s %s alt %s alt_d %s'
                  % (name, seed, m.W, m.H, m.T, m.sym, f['gems'], f['gold'], f['grp'], f['heavy'], f['mono'], f['dash'],
                     f['s2s'], f['alt'], f['alt_d']))
            if a.repo_maps:
                shutil.copyfile(mp, os.path.join(REPO_MAPS, name + '.map26a'))
            if a.install:
                G_install = os.path.join(INSTALL, name + '.map26a')
                if not os.path.exists(G_install) or open(G_install, 'rb').read() != open(mp, 'rb').read():
                    shutil.copyfile(mp, G_install)
    json.dump(index, open(ip, 'w'), indent=1)
    names = sorted(index)
    open(os.path.join(a.outdir, 'maplist.txt'), 'w').write(''.join(n + '\n' for n in names))
    with open(os.path.join(a.outdir, 'previews.txt'), 'w') as pv:
        for n in names:
            f = index[n]['features']
            pv.write('== %s %dx%d T%d sym%d | gems %d groups %d s2s %s alt_d %s\n' % (n, f['W'], f['H'], f['T'], f['sym'],
                                                                                f['gems'], f['grp'], f['s2s'], f['alt_d']))
            pv.write(open(os.path.join(a.outdir, n + '.txt')).read() + '\n')


if __name__ == '__main__':
    main()
