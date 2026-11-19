#!/usr/bin/env python3
"""Seeded procedural generator of held-out CAMBC 2026a test maps (engine 1.0.2).

Competition maps are unseen, so every bot change must also be checked on maps nobody tuned on. This script
designs mirror-symmetric maps, checks them (legal, fair, reachable), writes one spec JSON per map and builds the
.map26a with the engine's own MapBuilder (condor-work/sandbox/mkmap.js, engine v1_0_2.wasm). It then decodes
every built map and checks it matches the design tile for tile.

usage:
  python3 tools/lab/genmaps.py [--n 45] [--only N ...] [--install] [--outdir /data/USER/genmaps]
    --install  copy gen_NN.map26a into /data/USER/work301/maps (local A/B, heldout.sh) and
               /homes/USER/condor-work/proj301/maps (Condor)
    --checks 2 also applies the post-build checks added on 25 Oct (see validate()); the default 1 keeps every
               existing seed's map (give new families and batches --checks 2)
  python3 tools/lab/genmaps.py --show N    print one map as ASCII (after a build)
  python3 tools/lab/genmaps.py --dev --install   development twin set gen_dev_01..45 (same recipes, seeds 500000+;
               outdir /data/USER/genmaps_dev, installed in work301/maps only): tune and debug on these, keep
               gen_01..45 for the held-out check (tools/lab/heldout.sh; HELDOUT_LIST=/data/USER/genmaps_dev/maplist.txt
               runs the dev set)
Outputs in OUTDIR: gen_NN.json (spec for mkmap.js), gen_NN.map26a, gen_NN.meta.json (recipe, features),
gen_NN.txt (ASCII), previews.txt (all ASCII maps), index.json, maplist.txt (all), maplist_normal.txt,
maplist_long.txt, maplist_patho.txt. Legend: . floor # wall o hole " bush A altar S/s spawns, camps w wolf e elk g gem cluster
$ gold cluster M monolith G golem.

Maps 1..n-5 are normal: drawn from a balanced schedule of size, team size (3/4/5), symmetry, terrain style (open,
corridors, maze, holes, bushbelt, mixed), camp mix (balanced, cluster_heavy, elk_heavy, wolf_packs, golems,
gem_poor, gold_rich), monoliths per side (0, 1, 2), altar placement (near, far, central, shared, gated, many) and spawn distance
(long, medium, short); repeated entries weight the schedule towards the pool's mix. Normal maps guarantee: spawns
connected on foot, an altar reachable on foot, >= 88% of gems reachable on foot and the rest with a dash (no
crystal-only or unreachable camps), >= 40 gems and >= 6 camp groups, no camp blocking the only path to an altar,
group or the enemy spawn. Maps n-9..n-5 (gen_36..40) are deliberately pathological: dash-only islands (one
crystal-only), altars only on dash/crystal islands, halves separated by a 4-wide hole band, monolith rush, and a
26x26 gem desert (below the rules' 30x30 minimum) with spawns 2 tiles apart. The last 5 (gen_41..45, kind 'long') are
big maps (76-100 a side) and long walking routes ('serpentine' switchback walls, spawn to spawn 75-300), with the
normal maps' guarantees: the 35 normal maps stop at 75 a side and a 71-step spawn-to-spawn walk, while 12 of the 40
pool maps walk more than 80. They come after the pathological maps so that gen_01..40 stay unchanged.
Fairness: the engine mirrors every wall, hole, bush, altar and camp itself (a spec lists one tile per mirror pair),
so both teams get the same map; the decode check confirms it.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

MKMAP = '/homes/USER/condor-work/sandbox/mkmap.js'
WASM = '/homes/USER/condor-work/engine/v1_0_2.wasm'
INSTALL_DIRS = ['/data/USER/work301/maps', '/homes/USER/condor-work/proj301/maps']

FLOOR, WALL, HOLE, BUSH, ALTAR = 0, 1, 2, 3, 4
WOLF, ELK, GEM, GOLD, MONO, GOLEM = range(6)
GEMS = {WOLF: 4, ELK: 15, GEM: 7, GOLD: 0, MONO: 200, GOLEM: 36}
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
N4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]


class Map:
    def __init__(self, W, H, sym, T):
        self.W, self.H, self.sym, self.T = W, H, sym, T
        self.g = bytearray(W * H)
        self.camp = {}
        self.spawn = None          # team A rect (x0, y0, x1, y1), max exclusive
        self.protect = set()       # tiles that repair() must neither carve nor require reachable
        self.groups = []           # placed groups (team A copies): list of (tiles, kind)
        self.altars = []

    def inb(self, x, y):
        return 0 <= x < self.W and 0 <= y < self.H

    def mir(self, x, y):
        if self.sym == 0:
            return self.W - 1 - x, y
        if self.sym == 1:
            return x, self.H - 1 - y
        return self.W - 1 - x, self.H - 1 - y

    def get(self, x, y):
        return self.g[y * self.W + x]

    def put(self, x, y, v):
        if self.inb(x, y):
            self.g[y * self.W + x] = v
            mx, my = self.mir(x, y)
            self.g[my * self.W + mx] = v

    def prot(self, x, y):
        if self.inb(x, y):
            self.protect.add((x, y))
            self.protect.add(self.mir(x, y))

    def rectA(self):
        return self.spawn

    def rectB(self):
        x0, y0, x1, y1 = self.spawn
        a, b = self.mir(x0, y0), self.mir(x1 - 1, y1 - 1)
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]) + 1, max(a[1], b[1]) + 1

    @staticmethod
    def cheb_rect(r, x, y):
        x0, y0, x1, y1 = r
        return max(x0 - x, x - x1 + 1, y0 - y, y - y1 + 1, 0)

    def dspawn(self, x, y):
        return min(self.cheb_rect(self.rectA(), x, y), self.cheb_rect(self.rectB(), x, y))

    def bfs(self, team='A', dash=False, block_camps=False):
        W, H, g, camp = self.W, self.H, self.g, self.camp
        own = self.rectA() if team == 'A' else self.rectB()
        ex0, ey0, ex1, ey1 = self.rectB() if team == 'A' else self.rectA()

        def land(x, y):
            if x < 0 or y < 0 or x >= W or y >= H:
                return False
            v = g[y * W + x]
            if v != FLOOR and v != BUSH:
                return False
            if ex0 <= x < ex1 and ey0 <= y < ey1:
                return False
            return not (block_camps and (x, y) in camp)
        starts = [(x, y) for x in range(own[0], own[2]) for y in range(own[1], own[3])]
        dist = dict.fromkeys(starts, 0)
        dq = deque(starts)
        while dq:
            c = dq.popleft()
            cx, cy = c
            d = dist[c] + 1
            for dx, dy in N8:
                n = (cx + dx, cy + dy)
                if n not in dist and land(*n):
                    dist[n] = d
                    dq.append(n)
            if dash:
                for dx in (-2, -1, 0, 1, 2):
                    for dy in (-2, -1, 0, 1, 2):
                        if abs(dx) != 2 and abs(dy) != 2:
                            continue
                        n = (cx + dx, cy + dy)
                        if n in dist or not land(*n):
                            continue
                        for mx, my in N8:
                            px, py = cx + mx, cy + my
                            if (max(abs(px - n[0]), abs(py - n[1])) == 1 and 0 <= px < W and 0 <= py < H
                                    and g[py * W + px] != WALL):
                                dist[n] = d
                                dq.append(n)
                                break
        return dist

    def s2s(self, reach):
        r = self.rectB()
        return any(self.cheb_rect(r, x, y) == 1 for (x, y) in reach)

    def ascii(self):
        ch = {FLOOR: '.', WALL: '#', HOLE: 'o', BUSH: '"', ALTAR: 'A'}
        cc = {WOLF: 'w', ELK: 'e', GEM: 'g', GOLD: '$', MONO: 'M', GOLEM: 'G'}
        rows = []
        for y in range(self.H):
            s = []
            for x in range(self.W):
                if (x, y) in self.camp:
                    s.append(cc[self.camp[(x, y)]])
                elif self.cheb_rect(self.rectA(), x, y) == 0:
                    s.append('S')
                elif self.cheb_rect(self.rectB(), x, y) == 0:
                    s.append('s')
                else:
                    s.append(ch[self.get(x, y)])
            rows.append(''.join(s))
        return '\n'.join(rows)


# ------------------------------------------------------------------------------------------------ shapes
def blob(rng, n, conn=N4):
    cells, S = [(0, 0)], {(0, 0)}
    while len(cells) < n:
        x, y = rng.choice(cells)
        dx, dy = rng.choice(conn)
        c = (x + dx, y + dy)
        if c not in S:
            S.add(c)
            cells.append(c)
    return cells


def paint_blob(m, rng, v, n, x, y, conn=N4, only=None):
    for dx, dy in blob(rng, n, conn):
        if m.inb(x + dx, y + dy) and (x + dx, y + dy) not in m.protect and (only is None or m.get(x + dx, y + dy) == only):
            m.put(x + dx, y + dy, v)


def line_cells(x0, y0, x1, y1):
    """4-connected digital line (a watertight barrier against 8-way walking)."""
    cells = [(x0, y0)]
    x, y = x0, y0
    while (x, y) != (x1, y1):
        ex, ey = x1 - x, y1 - y
        if abs(ex) * (abs(y1 - y0) + 1) >= abs(ey) * (abs(x1 - x0) + 1) and ex:
            x += 1 if ex > 0 else -1
        elif ey:
            y += 1 if ey > 0 else -1
        else:
            x += 1 if ex > 0 else -1
        cells.append((x, y))
    return cells


def paint_cells(m, cells, v, width=1):
    for x, y in cells:
        for dx in range(width):
            for dy in range(width):
                if m.inb(x + dx, y + dy) and (x + dx, y + dy) not in m.protect:
                    m.put(x + dx, y + dy, v)


# ------------------------------------------------------------------------------------------------ terrain
def t_open(m, rng, k=1.0):
    A = m.W * m.H
    for _ in range(int(A * rng.uniform(0.003, 0.010) * k)):
        paint_blob(m, rng, WALL, rng.randint(1, 8), rng.randrange(m.W), rng.randrange(m.H))
    for _ in range(int(A * rng.uniform(0.003, 0.008) * k)):
        paint_blob(m, rng, BUSH, rng.randint(3, 12), rng.randrange(m.W), rng.randrange(m.H))
    if rng.random() < 0.35:
        for _ in range(int(A * 0.002 * k) + 1):
            paint_blob(m, rng, HOLE, rng.randint(2, 8), rng.randrange(m.W), rng.randrange(m.H))


def t_corridors(m, rng, k=1.0):
    W, H = m.W, m.H
    horiz = rng.random() < 0.5
    L, S = (W, H) if horiz else (H, W)       # lines run along L, stacked across S
    spacing = rng.randint(4, 9)
    thick = rng.choice([1, 1, 1, 2])
    margin = rng.randint(0, 4)
    off = rng.randint(2, spacing)
    for s in range(off, S - 2, spacing):
        if rng.random() > 0.85 * k + 0.1:
            continue
        a, b = rng.randint(0, margin), L - 1 - rng.randint(0, margin)
        cells = [(t, s) if horiz else (s, t) for t in range(a, b + 1)]
        gaps = set()
        for _ in range(rng.randint(1, 3)):
            g0, gw = rng.randint(a, b), rng.randint(1, 3)
            gaps.update(range(g0, g0 + gw))
        cells = [c for c in cells if (c[0] if horiz else c[1]) not in gaps]
        paint_cells(m, cells, WALL, thick)
    # a few chokepoint walls across the lanes
    for _ in range(int(rng.randint(1, 4) * k)):
        t = rng.randint(3, L - 4)
        a = rng.randint(0, S // 3)
        b = rng.randint(a + 3, S - 1)
        cells = [(t, s) if horiz else (s, t) for s in range(a, b + 1)]
        g0 = rng.randint(a, b)
        cells = [c for c in cells if abs((c[1] if horiz else c[0]) - g0) > rng.randint(0, 1)]
        paint_cells(m, cells, WALL, 1)
    for _ in range(int(W * H * rng.uniform(0.002, 0.006))):
        paint_blob(m, rng, BUSH, rng.randint(3, 10), rng.randrange(W), rng.randrange(H))


def t_maze(m, rng, k=1.0):
    W, H = m.W, m.H
    c = rng.choice([1, 2, 2, 3])
    step = c + 1
    full = rng.random() < 0.6
    rx0, ry0 = (1, 1) if full else (rng.randint(W // 6, W // 3), rng.randint(1, H // 4))
    rx1, ry1 = (W - 1, H - 1) if full else (W - rx0, H - ry0)
    nx, ny = max(2, (rx1 - rx0) // step), max(2, (ry1 - ry0) // step)
    openg = bytearray(W * H)
    cells = [(i, j) for i in range(nx) for j in range(ny)]

    def cell_tiles(i, j):
        x, y = rx0 + i * step, ry0 + j * step
        return [(x + a, y + b) for a in range(c) for b in range(c)]
    for i, j in cells:
        for x, y in cell_tiles(i, j):
            if m.inb(x, y):
                openg[y * W + x] = 1
    seen, st = {(0, 0)}, [(0, 0)]
    p_loop = rng.uniform(0.05, 0.25) * (2 - k)

    def carve(a, b):
        (i, j), (p, q) = a, b
        x, y = rx0 + min(i, p) * step, ry0 + min(j, q) * step
        if i != p:
            tiles = [(x + c, y + t) for t in range(c)]
        else:
            tiles = [(x + t, y + c) for t in range(c)]
        for tx, ty in tiles:
            if m.inb(tx, ty):
                openg[ty * W + tx] = 1
    while st:
        cur = st[-1]
        nb = [(cur[0] + dx, cur[1] + dy) for dx, dy in N4]
        nb = [n for n in nb if 0 <= n[0] < nx and 0 <= n[1] < ny and n not in seen]
        if not nb:
            st.pop()
            continue
        n = rng.choice(nb)
        carve(cur, n)
        seen.add(n)
        st.append(n)
    for i, j in cells:
        for dx, dy in ((1, 0), (0, 1)):
            if i + dx < nx and j + dy < ny and rng.random() < p_loop:
                carve((i, j), (i + dx, j + dy))
    xe, ye = rx0 + nx * step - 1, ry0 + ny * step - 1
    for y in range(ry0, min(ye, H)):
        for x in range(rx0, min(xe, W)):
            if (x, y) in m.protect:
                continue
            mx, my = m.mir(x, y)
            o = openg[y * W + x] or openg[my * W + mx]
            if not o:
                m.put(x, y, WALL)
    if rng.random() < 0.6:
        for _ in range(int(W * H * rng.uniform(0.002, 0.006))):
            paint_blob(m, rng, BUSH, rng.randint(2, 6), rng.randrange(W), rng.randrange(H), only=FLOOR)


def t_holes(m, rng, k=1.0):
    W, H = m.W, m.H
    A = W * H
    for _ in range(int(A * rng.uniform(0.0015, 0.004) * k) + 1):
        paint_blob(m, rng, HOLE, rng.randint(4, 30), rng.randrange(W), rng.randrange(H))
    # 1-wide rivers (dashable) with walkable bridges
    for _ in range(rng.randint(1, 3)):
        pts = [(rng.randrange(W), rng.randrange(H)) for _ in range(rng.randint(2, 4))]
        if rng.random() < 0.6:
            side = rng.randrange(4)
            pts[0] = [(0, pts[0][1]), (W - 1, pts[0][1]), (pts[0][0], 0), (pts[0][0], H - 1)][side]
        cells = []
        for a, b in zip(pts, pts[1:]):
            cells += line_cells(*a, *b)
        bridge_every = rng.randint(6, 14) if rng.random() < 0.85 else 10 ** 6
        cells = [c for i, c in enumerate(cells) if i % bridge_every >= rng.randint(1, 2) or bridge_every > 10 ** 5]
        paint_cells(m, cells, HOLE, 1)
    for _ in range(int(A * rng.uniform(0.001, 0.004))):
        paint_blob(m, rng, BUSH, rng.randint(3, 10), rng.randrange(W), rng.randrange(H))


def t_bushbelt(m, rng, k=1.0):
    W, H = m.W, m.H
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(['h', 'v', 'd'])
        w = rng.randint(2, 4)
        if kind == 'h':
            y = rng.randrange(H)
            cells = [(x, y) for x in range(W)]
        elif kind == 'v':
            x = rng.randrange(W)
            cells = [(x, y) for y in range(H)]
        else:
            cells = line_cells(rng.randrange(W // 3), rng.randrange(H), W - 1 - rng.randrange(W // 3), rng.randrange(H))
        if rng.random() < 0.6:
            g0 = rng.randrange(len(cells))
            cells = [c for i, c in enumerate(cells) if abs(i - g0) > rng.randint(1, 3)]
        paint_cells(m, cells, BUSH, w)
    for _ in range(int(W * H * rng.uniform(0.002, 0.006))):
        paint_blob(m, rng, BUSH, rng.randint(4, 14), rng.randrange(W), rng.randrange(H))
    t_open(m, rng, 0.5)


def t_mixed(m, rng, k=1.0):
    fs = rng.sample([t_open, t_corridors, t_maze, t_holes, t_bushbelt], 2)
    for f in fs:
        f(m, rng, 0.6)


def t_serpentine(m, rng, k=1.0):
    """Switchback walls across the spawn-to-spawn direction, each with one gap at alternating ends: long walking
    routes like the pool's long-route maps (00road-of-riches, 01starvation, 01concentrated-wealth, 01fracture:
    spawn to spawn 120-243). Walls go between team A's spawn and the mirror axis, so use the 'long' spawn mode."""
    W, H = m.W, m.H
    across = m.sym != 1                      # walls are columns x = p, or rows y = p on y-mirror maps
    L, S = (W, H) if across else (H, W)
    a0 = (m.spawn[2] if across else m.spawn[3]) + 2
    hi = (L - 4) // 2                        # leave a central corridor at least 2 wide
    thick = rng.choice([1, 1, 2])
    gap = rng.randint(2, 4)
    n = rng.randint(1, 3 if S <= 60 else 2)
    pos, p = [], a0 + rng.randint(0, 3)
    while len(pos) < n and p + thick - 1 <= hi:
        pos.append(p)
        p += thick + rng.randint(3, 8)
    low = rng.random() < 0.5
    t_open(m, rng, 0.4)                      # scatter first: the walls and gaps are drawn over it (a bush blob
    for i, p in enumerate(pos):              # on a wall would be a walkable shortcut)
        g0 = rng.randint(0, 2) if (i % 2 == 0) == low else S - gap - rng.randint(0, 2)
        for s in range(S):
            for t in range(-1, thick + 1):
                x, y = (p + t, s) if across else (s, p + t)
                if not m.inb(x, y) or (x, y) in m.protect:
                    continue
                if g0 <= s < g0 + gap:
                    m.put(x, y, FLOOR)       # the gap and its approach stay open; camps stay out
                    m.prot(x, y)
                elif 0 <= t < thick:
                    m.put(x, y, WALL)        # protected, so repair() never carves a shortcut through it
                    m.prot(x, y)


STYLES = {'open': t_open, 'corridors': t_corridors, 'maze': t_maze, 'holes': t_holes, 'bushbelt': t_bushbelt,
          'mixed': t_mixed, 'serpentine': t_serpentine}


# ------------------------------------------------------------------------------------------------ spawns
def place_spawn(m, rng, mode, sw, sh):
    W, H, sym = m.W, m.H, m.sym
    for _ in range(2000):
        if sym in (0, 1):
            L, S = (W, H) if sym == 0 else (H, W)
            sl, ss = (sw, sh) if sym == 0 else (sh, sw)
            if mode == 'long':
                a = rng.randint(0, max(0, L // 10))
            elif mode == 'medium':
                a = rng.randint(L // 8, max(L // 8, L // 4))
            else:
                a = (L - rng.randint(1, 7)) // 2 - sl
            b = rng.randint(0, S - ss)
            x0, y0 = (a, b) if sym == 0 else (b, a)
        else:
            if mode == 'long':
                if rng.random() < 0.7:
                    x0, y0 = rng.randint(0, W // 10), rng.randint(0, H // 10)
                else:
                    x0, y0 = rng.randint(0, W // 10), rng.randint(H // 5, H // 2)
            elif mode == 'medium':
                x0, y0 = rng.randint(W // 8, W // 3), rng.randint(H // 8, H // 3)
            else:
                x0 = (W - rng.randint(1, 7)) // 2 - sw
                y0 = rng.randint(max(0, H // 2 - sh - 4), min(H - sh, H // 2 + 2))
        r = (x0, y0, x0 + sw, y0 + sh)
        if x0 < 0 or y0 < 0 or x0 + sw > W or y0 + sh > H:
            continue
        m.spawn = r
        rb = m.rectB()
        # at least one free tile between the two spawn areas
        if min(m.cheb_rect(rb, x, y) for x in range(r[0], r[2]) for y in range(r[1], r[3])) < 2:
            continue
        return r
    raise RuntimeError('no spawn')


def clear_spawn(m):
    x0, y0, x1, y1 = m.spawn
    for x in range(x0 - 1, x1 + 1):
        for y in range(y0 - 1, y1 + 1):
            if m.inb(x, y):
                m.put(x, y, FLOOR)
                m.protect.discard((x, y))
                m.protect.discard(m.mir(x, y))


# ------------------------------------------------------------------------------------------------ connectivity
def repair(m, rng, need_s2s=True):
    W, H = m.W, m.H
    rB = m.rectB()
    for _ in range(600):
        reach = m.bfs('A')
        targets = None
        if need_s2s and not m.s2s(reach):
            targets = {(x, y) for x in range(rB[0] - 1, rB[2] + 1) for y in range(rB[1] - 1, rB[3] + 1)
                       if m.inb(x, y) and m.cheb_rect(rB, x, y) == 1}
        else:
            bad = None
            for y in range(H):
                for x in range(W):
                    if (m.g[y * W + x] in (FLOOR, BUSH) and (x, y) not in reach and m.mir(x, y) not in reach
                            and (x, y) not in m.protect and m.cheb_rect(rB, x, y) > 0):
                        bad = (x, y)
                        break
                if bad:
                    break
            if bad is None:
                return
            comp, st = {bad}, [bad]
            while st:
                cx, cy = st.pop()
                for dx, dy in N8:
                    n = (cx + dx, cy + dy)
                    if (n not in comp and m.inb(*n) and m.get(*n) in (FLOOR, BUSH) and n not in m.protect
                            and m.cheb_rect(rB, *n) > 0):
                        comp.add(n)
                        st.append(n)
            if len(comp) <= 3:
                for x, y in comp:
                    m.put(x, y, WALL)
                continue
            targets = comp
        # carve a 4-connected path from the reached area to the targets
        prev = {p: None for p in reach}
        dq = deque(reach)
        hit = None
        while dq and hit is None:
            cx, cy = dq.popleft()
            for dx, dy in rng.sample(N4, 4):
                n = (cx + dx, cy + dy)
                if n in prev or not m.inb(*n) or n in m.protect or m.get(*n) == ALTAR or m.cheb_rect(rB, *n) == 0:
                    continue
                prev[n] = (cx, cy)
                if n in targets:
                    hit = n
                    break
                dq.append(n)
        if hit is None:
            raise RuntimeError('cannot connect')
        p = hit
        while p is not None:
            if m.get(*p) in (WALL, HOLE):
                m.put(p[0], p[1], FLOOR)
            p = prev[p]


# ------------------------------------------------------------------------------------------------ islands
def island(m, rng, w, h, moat=1, bridge=False, near=None):
    W, H = m.W, m.H
    for _ in range(400):
        if near:
            x0 = near[0] + rng.randint(-6, 6) - w // 2
            y0 = near[1] + rng.randint(-6, 6) - h // 2
        else:
            x0, y0 = rng.randint(moat + 1, W - w - moat - 1), rng.randint(moat + 1, H - h - moat - 1)
        box = [(x, y) for x in range(x0 - moat - 1, x0 + w + moat + 1) for y in range(y0 - moat - 1, y0 + h + moat + 1)]
        if x0 < 1 or y0 < 1 or x0 + w > W - 1 or y0 + h > H - 1:
            continue
        if any(m.inb(x, y) and ((x, y) in m.protect or m.dspawn(x, y) < 3 or m.get(x, y) == ALTAR) for x, y in box):
            continue
        bs = set(box)
        if any(m.mir(x, y) in bs for x, y in box):
            continue
        for x, y in box:
            if not m.inb(x, y):
                continue
            dx = max(x0 - x, x - (x0 + w - 1), 0)
            dy = max(y0 - y, y - (y0 + h - 1), 0)
            d = max(dx, dy)
            if d == 0:
                m.put(x, y, FLOOR)
                m.prot(x, y)
            elif d <= moat:
                m.put(x, y, HOLE)
                m.prot(x, y)
            else:
                m.put(x, y, FLOOR)
        if bridge:
            bx, by = x0 + w // 2, y0 - 1
            for t in range(moat):
                m.put(bx, by - t, FLOOR)
        return [(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)]
    return None


# ------------------------------------------------------------------------------------------------ altars
def altar_candidates(m):
    dA, dB = m.bfs('A'), m.bfs('B')
    mx = max(dA.values()) + 1
    out = []
    for (x, y), da in dA.items():
        if m.get(x, y) != FLOOR or (x, y) in m.protect or m.dspawn(x, y) < 3:
            continue
        if sum(1 for dx, dy in N8 if m.inb(x + dx, y + dy) and m.get(x + dx, y + dy) in (FLOOR, BUSH)) < 5:
            continue
        db = dB.get((x, y))
        # separated halves: no enemy distance, so contestedness is the own distance scaled to [0, 0.5)
        ci = (da / (da + db) if da + db else 0.5) if db is not None else 0.5 * da / mx
        out.append((x, y, da, db, ci))
    return out


def add_altar(m, rng, x, y, double=None):
    m.put(x, y, ALTAR)
    m.altars.append((x, y))
    if double is None:
        double = rng.random() < 0.25
    if double:
        for dx, dy in rng.sample(N4, 4):
            n = (x + dx, y + dy)
            if m.inb(*n) and m.get(*n) == FLOOR and n not in m.protect and m.dspawn(*n) >= 3 and m.mir(*n) != (x, y):
                m.put(n[0], n[1], ALTAR)
                m.altars.append(n)
                break


def shrine(m, rng, ax, ay):
    """Altar inside a 5x5 wall ring with a single 1-tile gate facing team A's spawn."""
    box = [(ax + dx, ay + dy) for dx in range(-3, 4) for dy in range(-3, 4)]
    if any(not m.inb(*p) or p in m.protect or m.dspawn(*p) < 2 for p in box):
        return False
    bs = set(box)
    if any(m.mir(*p) in bs for p in box):
        return False
    sx = (m.spawn[0] + m.spawn[2]) / 2 - ax
    sy = (m.spawn[1] + m.spawn[3]) / 2 - ay
    gate = (2 * (1 if sx > 0 else -1), 0) if abs(sx) >= abs(sy) else (0, 2 * (1 if sy > 0 else -1))
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            d = max(abs(dx), abs(dy))
            x, y = ax + dx, ay + dy
            if d == 3:
                m.put(x, y, FLOOR)
            elif d == 2 and (dx, dy) != gate:
                m.put(x, y, WALL)
                m.prot(x, y)
            else:
                m.put(x, y, FLOOR)
                m.prot(x, y)
    add_altar(m, rng, ax, ay, double=False)
    return True


def place_altars(m, rng, mode):
    cand = altar_candidates(m)
    if not cand:
        raise RuntimeError('no altar candidates')
    own = [c for c in cand if c[4] < 0.45]
    mid = [c for c in cand if 0.47 <= c[4] <= 0.53]
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    cdist = lambda c: max(abs(c[0] - cx), abs(c[1] - cy))  # noqa: E731
    placed = 0

    def pick(lst):
        return rng.choice(lst) if lst else None
    if mode == 'near':
        lim = rng.randint(5, 11)
        c = pick([c for c in own if 3 <= c[2] <= lim]) or min(own or cand, key=lambda c: c[2])
        add_altar(m, rng, c[0], c[1])
        placed = 1
    elif mode == 'far':
        own_s = sorted(own or cand, key=lambda c: c[2])
        c = pick(own_s[int(len(own_s) * 0.85):])
        add_altar(m, rng, c[0], c[1])
        placed = 1
    elif mode == 'central':
        lst = sorted(mid or cand, key=cdist)[:6]
        c = pick(lst)
        add_altar(m, rng, c[0], c[1])
        placed = 1
    elif mode == 'shared':
        R = min(m.W, m.H) / 4
        lst = [c for c in mid if cdist(c) >= R] or mid or cand
        for c in rng.sample(lst, min(len(lst), rng.randint(1, 2))):
            if m.get(c[0], c[1]) == FLOOR:
                add_altar(m, rng, c[0], c[1])
                placed += 1
    elif mode == 'gated':
        lst = [c for c in cand if 0.15 <= c[4] <= 0.42]
        rng.shuffle(lst)
        for c in lst[:200]:
            if shrine(m, rng, c[0], c[1]):
                placed = 1
                break
        if not placed:
            c = pick(own or cand)
            add_altar(m, rng, c[0], c[1])
            placed = 1
    elif mode == 'many':
        k = rng.randint(3, 6)
        lst = own[:] or cand[:]
        rng.shuffle(lst)
        for c in lst:
            if placed >= k:
                break
            if m.get(c[0], c[1]) == FLOOR and all(max(abs(c[0] - a[0]), abs(c[1] - a[1])) >= 6 for a in m.altars):
                add_altar(m, rng, c[0], c[1])
                placed += 1
    # sometimes an extra shared altar
    if mode not in ('central', 'shared') and rng.random() < 0.25 and mid:
        c = pick(sorted(mid, key=cdist)[:10])
        if m.get(c[0], c[1]) == FLOOR:
            add_altar(m, rng, c[0], c[1])
    return placed


# ------------------------------------------------------------------------------------------------ camps
def tpl(name, rng):
    if name == 'gem_patch':
        return [(x, y, GEM) for x, y in blob(rng, rng.randint(2, 6))]
    if name == 'gem_field':
        return [(x, y, GEM) for x, y in blob(rng, rng.randint(7, 12))]
    if name == 'mixed_clusters':
        return [(x, y, GEM if rng.random() < 0.55 else GOLD) for x, y in blob(rng, rng.randint(3, 8))]
    if name == 'gold_row':
        n = rng.randint(2, 5)
        h = rng.random() < 0.5
        return [((i, 0) if h else (0, i)) + (GOLD,) for i in range(n)]
    if name == 'gold_patch':
        return [(x, y, GOLD) for x, y in blob(rng, rng.randint(3, 7))]
    if name == 'wolf':
        return [(0, 0, WOLF)]
    if name == 'wolf_pack':
        return [(x, y, WOLF) for x, y in blob(rng, rng.randint(2, 4))]
    if name == 'elk':
        return [(0, 0, ELK)]
    if name == 'elk_pair':
        return [(0, 0, ELK), (1, 0, ELK)] if rng.random() < 0.5 else [(0, 0, ELK), (0, 1, ELK)]
    if name == 'elk_guard':
        c = blob(rng, rng.randint(3, 5))
        return [c[0] + (ELK,)] + [p + (GEM,) for p in c[1:]]
    if name == 'gold_guard':
        c = blob(rng, rng.randint(3, 6))
        return [c[0] + (ELK,)] + [p + (GOLD,) for p in c[1:]]
    if name == 'wolf_clusters':
        c = blob(rng, rng.randint(3, 6))
        return [c[0] + (WOLF,)] + [p + (GEM if rng.random() < 0.6 else GOLD,) for p in c[1:]]
    if name == 'golem':
        return [(0, 0, GOLEM)]
    if name == 'golem_pack':
        c = blob(rng, rng.randint(2, 3))
        return [c[0] + (GOLEM,)] + [p + (WOLF,) for p in c[1:]]
    if name == 'monolith':
        return [(0, 0, MONO)]
    raise KeyError(name)


# Every mix keeps some elk: in the pool most gems sit in elk/golem/monolith-guarded groups (heavy share median 0.81).
MIXES = {
    'balanced': {'elk': 3, 'elk_guard': 2, 'elk_pair': 1, 'gem_patch': 2, 'gold_row': 2, 'wolf_pack': 2, 'wolf': 1,
                 'wolf_clusters': 1, 'golem': 0.5},
    'cluster_heavy': {'gem_patch': 4, 'gem_field': 2, 'mixed_clusters': 2, 'gold_row': 1, 'wolf': 1, 'elk_guard': 1.5,
                      'elk': 1},
    'elk_heavy': {'elk': 4, 'elk_pair': 3, 'elk_guard': 2, 'gem_patch': 1, 'gold_row': 1, 'wolf': 1},
    'wolf_packs': {'wolf_pack': 5, 'wolf': 2, 'wolf_clusters': 2, 'gem_patch': 1, 'gold_row': 1, 'elk': 1.5},
    'golems': {'golem': 3, 'golem_pack': 3, 'wolf_pack': 1, 'gem_patch': 1, 'gold_row': 1, 'elk': 1},
    'gem_poor': {'gold_row': 4, 'gold_patch': 2, 'wolf': 2, 'gem_patch': 0.4, 'elk': 0.6},
    'gold_rich': {'gold_row': 4, 'gold_patch': 3, 'gold_guard': 2, 'elk': 2, 'wolf_pack': 1, 'gem_patch': 1.5},
}


def group_ok(m, tiles, allow_protected=False):
    own = {(x, y) for x, y, _ in tiles}
    for x, y, _ in tiles:
        if not m.inb(x, y) or m.get(x, y) != FLOOR or (x, y) in m.camp or m.dspawn(x, y) < 3:
            return False
        if (x, y) in m.protect and not allow_protected:
            return False
        for dx, dy in N8:
            n = (x + dx, y + dy)
            if n in own:
                continue
            if n in m.camp or (m.inb(*n) and m.get(*n) == ALTAR):
                return False
    mirrored = {m.mir(x, y) for x, y in own}
    if mirrored & own:
        return len(own) == 1 and mirrored == own          # a single camp on the mirror axis
    for x, y in mirrored:
        if any((x + dx, y + dy) in own for dx, dy in N8):
            return False
    return True


def put_group(m, tiles, kind):
    for x, y, t in tiles:
        m.camp[(x, y)] = t
        m.camp[m.mir(x, y)] = t
    m.groups.append(([(x, y) for x, y, _ in tiles], kind))


def drop_group(m):
    tiles, _ = m.groups.pop()
    for x, y in tiles:
        m.camp.pop((x, y), None)
        m.camp.pop(m.mir(x, y), None)


def access_ok(m, need_s2s=True, strict=False):
    """Every group, every altar and the enemy spawn stay reachable for team A without killing a camp. Protected altars
    (island altars, shrines) are skipped; strict (recipe 'checks' >= 2) checks a protected altar too when it can be
    walked to at all, so a camp can no longer close a shrine's only gate (gen_s_298)."""
    reach = m.bfs('A', block_camps=True)
    for tiles, kind in m.groups:
        if kind == 'island':
            continue
        if not any((x + dx, y + dy) in reach for x, y in tiles for dx, dy in N8):
            return False
    walk = m.bfs('A') if strict else None
    for x, y in m.altars:
        nbs = [(x + dx, y + dy) for dx, dy in N8 if m.inb(x + dx, y + dy)]
        if ((x, y) in m.protect or m.mir(x, y) in m.protect) and not (
                strict and any(p in walk or m.mir(*p) in walk for p in nbs)):
            continue
        if not any(p in reach or m.mir(*p) in reach for p in nbs):
            return False
    if need_s2s and not m.s2s(reach):
        return False
    return True


def zone_candidates(m):
    dA, dB = m.bfs('A'), m.bfs('B')
    mx = max(dA.values()) + 1
    Z = {'home': [], 'mid': [], 'center': []}
    for (x, y), da in dA.items():
        if m.get(x, y) != FLOOR or (x, y) in m.protect or m.dspawn(x, y) < 3:
            continue
        db = dB.get((x, y))
        ci = da / (da + db) if db is not None else 0.5 * da / mx
        if 0.06 <= ci < 0.36:
            Z['home'].append((x, y))
        elif 0.36 <= ci < 0.46:
            Z['mid'].append((x, y))
        elif 0.46 <= ci <= 0.5:
            Z['center'].append((x, y))
    for k in Z:
        Z[k].sort()
    return Z


def place_groups(m, rng, mix, n_side, need_s2s=True, zone_w=(0.45, 0.33, 0.22), strict=False):
    Z = zone_candidates(m)
    names = sorted(MIXES[mix])
    weights = [MIXES[mix][k] for k in names]
    placed = 0
    for _ in range(n_side):
        name = rng.choices(names, weights)[0]
        for attempt in range(80):
            zone = rng.choices(['home', 'mid', 'center'], zone_w)[0]
            if not Z[zone]:
                continue
            ax, ay = rng.choice(Z[zone])
            tiles = [(ax + dx, ay + dy, t) for dx, dy, t in tpl(name, rng)]
            if not group_ok(m, tiles):
                continue
            put_group(m, tiles, name)
            if access_ok(m, need_s2s, strict):
                placed += 1
                break
            drop_group(m)
    return placed


def place_monoliths(m, rng, k, strict=False):
    """k monoliths per side; if the map has mirror-axis tiles, maybe one shared central monolith instead."""
    Z = zone_candidates(m)
    axis = [p for p in Z['center'] if m.mir(*p) == p]
    n = 0
    if axis and rng.random() < 0.5:
        cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
        axis.sort(key=lambda p: max(abs(p[0] - cx), abs(p[1] - cy)))
        for p in axis[:20]:
            tiles = [(p[0], p[1], MONO)]
            if group_ok(m, tiles):
                put_group(m, tiles, 'monolith')
                if access_ok(m, strict=strict):
                    return 1
                drop_group(m)
    pool = Z['mid'] + Z['center'] + Z['home'][len(Z['home']) // 2:]
    for _ in range(400):
        if n >= k or not pool:
            break
        p = rng.choice(pool)
        tiles = [(p[0], p[1], MONO)]
        if not group_ok(m, tiles) or m.mir(*p) == p:
            continue
        put_group(m, tiles, 'monolith')
        if access_ok(m, strict=strict):
            n += 1
        else:
            drop_group(m)
    return n


def place_in_island(m, rng, interior, names, n):
    placed = 0
    for _ in range(n):
        for attempt in range(60):
            ax, ay = rng.choice(interior)
            tiles = [(ax + dx, ay + dy, t) for dx, dy, t in tpl(rng.choice(names), rng)]
            if all((x, y) in interior for x, y, _ in tiles) and group_ok(m, tiles, allow_protected=True):
                put_group(m, tiles, 'island')
                placed += 1
                break
    return placed


# ------------------------------------------------------------------------------------------------ camp-gated altars
# (genbig.py family "gate", cambc-4f 25 Oct: Sprint 2 had a central altar inside a closed ring of 48 wolves (S2-13) and an
# altar whose only tribute tiles were monolith tiles (S2-10); 2 of 953 local maps had a ring and 1 a camp on a tribute
# tile, so A/Bs never saw a bot that cannot bank there.) Every altar of such a map is gated:
#   ring_camps  a closed square ring of one camp group (wolves, gold clusters or elks) at Chebyshev 2-4, 1-2 thick
#   ring_gates  a closed square wall (or hole) ring at Chebyshev 2-4 whose gaps each hold one camp (wolf, elk, gold)
#   adj_gate    every tribute tile (Chebyshev 1 of the altar) is a wall, a hole or a camp (elk, golem, monolith)
# Classified like /data/USER/mf/py/altaraccess.py: ring = a free tribute tile is reachable only by crossing camps;
# adjgate = only camps on tribute tiles are reachable.
GATE_KINDS = ['ring_camps', 'ring_gates', 'adj_gate']


def gate_site_ok(m, x, y, rad):
    """Room for a gate structure of Chebyshev radius rad at (x, y): in bounds with a 1-tile margin, 3+ tiles from both
    spawns, no camp or protected tile within rad + 1, and either the site is its own mirror image (one shared structure)
    or the structure and its mirror copy keep 2 tiles apart."""
    box = [(x + dx, y + dy) for dx in range(-rad - 1, rad + 2) for dy in range(-rad - 1, rad + 2)]
    if any(not m.inb(*p) or m.dspawn(*p) < 3 or p in m.protect or p in m.camp or m.get(*p) == ALTAR for p in box):
        return False
    if m.mir(x, y) == (x, y):
        return True
    mx, my = m.mir(x, y)
    return max(abs(mx - x), abs(my - y)) > 2 * rad + 3


def gate_sites(m, rad):
    """Candidate centres: the map's own mirror-fixed tiles near the centre first, then tiles a third to half way
    between the spawns (contestedness 0.2-0.45, so each team has its own copy)."""
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    fixed = sorted({(x, y) for x in range(m.W) for y in range(m.H) if m.mir(x, y) == (x, y)},
                   key=lambda p: max(abs(p[0] - cx), abs(p[1] - cy)))
    side = [(c[0], c[1]) for c in altar_candidates(m) if 0.2 <= c[4] <= 0.45]
    return [p for p in fixed[:12] if gate_site_ok(m, p[0], p[1], rad)], [p for p in side if gate_site_ok(m, p[0], p[1], rad)]


def build_gate(m, rng, kind, x, y, P):
    """Clear the box, then build the structure around an altar at (x, y); every tile of it is protected (repair()
    neither carves it nor requires it to be reachable)."""
    rad = P['rad']
    for dx in range(-rad - 1, rad + 2):
        for dy in range(-rad - 1, rad + 2):
            m.put(x + dx, y + dy, FLOOR)  # the outer margin stays unprotected: repair() connects it to the map
            if max(abs(dx), abs(dy)) <= rad:
                m.prot(x + dx, y + dy)
    if kind in ('ring_camps', 'ring_gates'):
        r0, t = P['r'], P['t']
        ring = [(x + dx, y + dy) for dx in range(-rad, rad + 1) for dy in range(-rad, rad + 1)
                if r0 <= max(abs(dx), abs(dy)) < r0 + t]
        if kind == 'ring_camps':
            put_group(m, [(px, py, P['camp']) for px, py in ring], 'gate_ring')
        else:
            corners = [(x + sx * r0, y + sy * r0) for sx in (-1, 1) for sy in (-1, 1)]
            sides = [(x + r0, y), (x - r0, y), (x, y + r0), (x, y - r0)]
            pool = corners if rng.random() < 0.7 else corners + sides
            gates = set(rng.sample(pool, P['gates']))
            gates |= {m.mir(*p) for p in gates if max(abs(m.mir(*p)[0] - x), abs(m.mir(*p)[1] - y)) == r0}
            for p in ring:
                if p not in gates:
                    m.put(p[0], p[1], P['wall'])
            for p in sorted(gates):
                put_group(m, [(p[0], p[1], P['camp'])], 'gate')
    else:
        nb = [(x + dx, y + dy) for dx, dy in N8]
        sides = [(x + dx, y + dy) for dx, dy in N4]
        gates = set(rng.sample(sides, P['gates']))
        gates |= {m.mir(*p) for p in gates if max(abs(m.mir(*p)[0] - x), abs(m.mir(*p)[1] - y)) == 1}
        for p in nb:
            if p not in gates:
                m.put(p[0], p[1], P['wall'] if rng.random() < 0.6 else (HOLE if P['wall'] == WALL else WALL))
        for p in sorted(gates):
            put_group(m, [(p[0], p[1], P['camp'])], 'gate')
    add_altar(m, rng, x, y, double=False)


def gate_params(rng, kind, over=None):
    """The structure's parameters; `over` (a recipe's gate_over) fixes some of them (gen_g2's failure shapes)."""
    if kind == 'ring_camps':
        r = rng.choice([2, 3, 3, 4])
        t = 2 if r >= 3 and rng.random() < 0.5 else 1
        camp = rng.choices([WOLF, GOLD, ELK], [0.6, 0.25, 0.15 if r == 2 and t == 1 else 0])[0]
        P = dict(r=r, t=t, camp=camp)
    elif kind == 'ring_gates':
        r = rng.choice([2, 3, 4])
        P = dict(r=r, t=1, gates=rng.choice([1, 1, 2, 4]), camp=rng.choice([WOLF, WOLF, ELK, GOLD]),
                 wall=WALL if rng.random() < 0.8 else HOLE)
    else:
        P = dict(r=1, t=0, gates=rng.choice([1, 2]), camp=rng.choice([ELK, GOLEM, MONO, MONO]), wall=rng.choice([WALL, HOLE]))
    P.update(over or {})
    P['rad'] = 2 if kind == 'adj_gate' else P['r'] + P['t'] if kind == 'ring_camps' else P['r'] + 1
    return P


def generate_gate(rec, seed):
    """A normal map (same recipe columns) whose altars are replaced by one camp-gated altar: shared at the map's
    mirror-fixed centre when there is room (half the time), else one per side."""
    rng = random.Random(seed * 31 + 7)
    P = gate_params(rng, rec['kind'], rec.get('gate_over'))
    central = rng.random() < 0.5
    m = generate(dict(rec, kind='normal', reserve=P['rad'] + 1 if central else 0), seed)
    for x, y in m.altars:
        m.put(x, y, FLOOR)
    m.altars = []
    res = getattr(m, 'reserved', None)
    if res:  # the reserved centre box is its own mirror image: release it for the shared structure
        cx, cy, R = res
        m.protect -= {(cx + dx, cy + dy) for dx in range(-R, R + 1) for dy in range(-R, R + 1)}
    fixed, side = gate_sites(m, P['rad'])
    if res and (cx, cy) in fixed:
        x, y = cx, cy
    elif side:
        x, y = rng.choice(side)
    elif fixed:
        x, y = fixed[0]
    else:
        raise RuntimeError('no room for a gated altar')
    build_gate(m, rng, rec['kind'], x, y, P)
    repair(m, rng, True)
    m.gate = dict(P, x=x, y=y, shared=m.mir(x, y) == (x, y))
    return m


def altar_access(d):
    """Altar access per spawn, as /data/USER/mf/py/altaraccess.py (cambc-4f) classifies it: open / adjgate / ring /
    mixed / none. d: map26a.load() or decode_like() format."""
    W, H = d['W'], d['H']
    camps = set(d['camps'])
    base = set(d['wall']) | set(d['hole']) | set(d['altar'])
    out = {}
    for side, spawn, enemy in (('A', d['spawnA'], d['spawnB']), ('B', d['spawnB'], d['spawnA'])):
        blocked = base | set(enemy)
        trib = {(ax + dx, ay + dy) for ax, ay in d['altar'] for dx, dy in N8
                if 0 <= ax + dx < W and 0 <= ay + dy < H and (ax + dx, ay + dy) not in blocked}
        free, gate = trib - camps, trib & camps

        def reach(block):
            seen = set(spawn)
            dq = deque(spawn)
            while dq:
                px, py = dq.popleft()
                for dx, dy in N8:
                    q = (px + dx, py + dy)
                    if 0 <= q[0] < W and 0 <= q[1] < H and q not in block and q not in seen:
                        seen.add(q)
                        dq.append(q)
            return seen
        if free & reach(blocked | camps):
            out[side] = 'open'
            continue
        r_open = reach(blocked)
        ring, adj = bool(free & r_open), bool(gate & r_open)
        out[side] = 'mixed' if ring and adj else 'ring' if ring else 'adjgate' if adj else 'none'
    return out


def validate_gate(m, rec):
    """validate()'s legality and symmetry checks, a normal map's reach and size checks, and the gated access."""
    ok, info = validate(m, dict(rec, kind='gate'))
    if not ok:
        return ok, info
    f = info
    if f['s2s'] is None:
        return False, 'spawns not connected'
    if f['gems'] < 40 or f['grp'] < 6:
        return False, f"too little: gems={f['gems']} groups={f['grp']}"
    want = 'adjgate' if rec['kind'] == 'adj_gate' else 'ring'
    acc = altar_access(decode_like(m))
    if acc != {'A': want, 'B': want}:
        return False, f"altar access {acc}, want {want}"
    return True, f


# ------------------------------------------------------------------------------------------------ recipes
# Each category list is repeated and shuffled over the normal maps (balanced marginals, random combinations).
# Repeated entries weight the draw towards the pool (40% of pool maps have monoliths, 65% are 5v5, 62% are
# rotations, 65% have a shared altar, few have touching spawns) while still covering every category.
SCHED = {
    'style': ['open', 'corridors', 'maze', 'holes', 'bushbelt', 'mixed'],
    'mix': ['balanced', 'balanced', 'balanced', 'cluster_heavy', 'elk_heavy', 'elk_heavy', 'wolf_packs', 'golems',
            'gem_poor', 'gold_rich'],
    'mono': [0, 0, 0, 0, 0, 1, 1, 2],
    'altar': ['near', 'far', 'central', 'central', 'shared', 'shared', 'gated', 'many'],
    'spawn': ['long', 'long', 'long', 'medium', 'medium', 'short'],
    'sym': [0, 1, 2, 2, 2],
    'T': [3, 4, 5, 5, 5],
    'size': ['S', 'M', 'M', 'L', 'L'],
    'aspect': ['square', 'square', 'wide', 'tall'],
}
PATHO = ['islands', 'dash_altar', 'split', 'monolith_rush', 'tiny_desert']
# gen_41..45 (added by the validation pass): big maps (76-100 a side) and long walking routes, which the 35 normal
# maps miss (their spawn-to-spawn walk tops out at 71 and their side at 75, while 12 of the 40 pool maps walk more than
# 80 and 6 are 76-100 a side). Fixed recipes, appended after the pathological maps so gen_01..40 stay unchanged.
LONG = [dict(kind='long', size='XL', aspect='square', T=5, sym=2, style='open', mix='balanced', mono=1, altar='shared', spawn='long'),
        dict(kind='long', size='XL', aspect='square', T=5, sym=0, style='serpentine', mix='elk_heavy', mono=0, altar='far', spawn='long'),
        dict(kind='long', size='L', aspect='tall', T=4, sym=2, style='serpentine', mix='golems', mono=1, altar='central', spawn='long'),
        dict(kind='long', size='M', aspect='square', T=5, sym=1, style='serpentine', mix='balanced', mono=0, altar='shared', spawn='long'),
        dict(kind='long', size='XL', aspect='wide', T=5, sym=0, style='corridors', mix='wolf_packs', mono=2, altar='many', spawn='long')]


def schedule(n):
    n_norm = n - len(PATHO) - len(LONG)
    r = random.Random(2026)
    cols = {}
    for k, vals in SCHED.items():
        L = (vals * (n_norm // len(vals) + 1))[:n_norm]
        r.shuffle(L)
        cols[k] = L
    rec = [dict({k: cols[k][i] for k in SCHED}, kind='normal') for i in range(n_norm)]
    for i, p in enumerate(PATHO):
        rec.append(dict(kind=p, sym=[2, 0, 1, 2, 2][i], T=[5, 4, 5, 3, 5][i], size='M', aspect='square', mono=0,
                        style=['holes', 'open', 'corridors', 'open', 'open'][i],
                        mix=['balanced', 'balanced', 'balanced', 'balanced', 'gem_poor'][i],
                        altar=['near', 'near', 'near', 'near', 'near'][i],
                        spawn=['long', 'medium', 'medium', 'medium', 'short'][i]))
    rec += [dict(r) for r in LONG]
    return rec


def dims(rng, size, aspect):
    # the rules allow 30..100 per side; the pool spans 28..100. Only the tiny_desert pathological map goes below.
    # all three draws happen whatever the size (the dict is built eagerly): keep it that way, or the random stream
    # and with it every existing map changes. XL (gen_41..45 only) draws once more afterwards.
    a = {'S': rng.randint(30, 38), 'M': rng.randint(39, 55), 'L': rng.randint(56, 75)}.get(size)
    if size == 'XL':
        a = rng.randint(76, 100)
    if aspect == 'square':
        return a, a
    b = max(30, round(a / rng.uniform(1.3, 2.2)))
    return (a, b) if aspect == 'wide' else (b, a)


def generate(rec, seed):
    rng = random.Random(seed)
    kind = rec['kind']
    W, H = dims(rng, rec['size'], rec['aspect'])
    if kind == 'tiny_desert':
        W = H = 30 if rec.get('min30') else 26  # 8 Nov (Combat, b1741): 26 is below the rules' 30x30 minimum (GameRules:143); old recipes
        # (no min30) rebuild their own 26x26 map, so a read resumed from its seeds gets the map it played
    if rec.get('dims'):  # fixed board size (gen_g2 large boards); the dims() draw above still happens
        W, H = rec['dims']
    T = rec['T']
    m = Map(W, H, rec['sym'], T)
    sw, sh = {3: [(3, 3)], 4: [(3, 3), (4, 3)], 5: [(3, 3), (4, 4), (5, 2)]}[T][rng.randrange(1 if T == 3 else 2 if T == 4 else 3)]
    if rng.random() < 0.5:
        sw, sh = sh, sw
    place_spawn(m, rng, 'short' if kind == 'tiny_desert' else rec['spawn'], sw, sh)
    STYLES[rec['style']](m, rng)
    clear_spawn(m)
    if rec.get('reserve'):  # gate family only (no random draw): keep the mirror-fixed centre free for a shared gated altar
        R, cx, cy = rec['reserve'], (W - 1) // 2, (H - 1) // 2
        if m.mir(cx, cy) == (cx, cy) and all(m.inb(cx + dx, cy + dy) and m.dspawn(cx + dx, cy + dy) >= 3
                                             for dx in (-R, R) for dy in (-R, R)):
            for dx in range(-R, R + 1):
                for dy in range(-R, R + 1):
                    m.put(cx + dx, cy + dy, FLOOR)
                    m.prot(cx + dx, cy + dy)
            m.reserved = (cx, cy, R)
    need_s2s = kind != 'split'
    islands = []
    if kind == 'split':
        # an impassable 4-5 tile hole band on the mirror axis: the teams never meet (a crystal reaches 3)
        for y in range(H):
            for x in range(W):
                mx, my = m.mir(x, y)
                if (m.sym == 0 and abs(x - mx) <= 4) or (m.sym == 1 and abs(y - my) <= 4) or \
                   (m.sym == 2 and abs(y - (H - 1) / 2) <= 2.0):
                    m.put(x, y, HOLE)
                    m.prot(x, y)
        clear_spawn(m)
    if rec['style'] == 'holes' and kind == 'normal' and rng.random() < 0.5:
        isl = island(m, rng, rng.randint(3, 5), rng.randint(3, 5))
        if isl:
            islands.append((isl, ['gold_row', 'gem_patch', 'wolf']))
    if kind == 'islands':
        for i in range(rng.randint(5, 8)):
            isl = island(m, rng, rng.randint(4, 8), rng.randint(4, 7), moat=2 if i == 0 else 1)
            if isl:
                islands.append((isl, ['gem_patch', 'elk', 'elk_guard', 'wolf_pack', 'gold_row']))
    repair(m, rng, need_s2s)
    if kind == 'dash_altar':
        for i in range(2):
            isl = island(m, rng, 3, 3, moat=1 + i)
            if isl:
                c = isl[4]
                add_altar(m, rng, c[0], c[1], double=False)
        repair(m, rng, need_s2s)
    else:
        place_altars(m, rng, rec['altar'])
        repair(m, rng, need_s2s)
    if not m.altars:
        raise RuntimeError('no altar')
    area_side = W * H / 2
    n_side = max(3, min(16, round(area_side ** 0.5 * rng.uniform(0.17, 0.4))))
    strict = rec.get('checks', 1) >= 2
    if rec.get('mono'):
        place_monoliths(m, rng, rec['mono'], strict)
    if kind == 'monolith_rush':
        place_monoliths(m, rng, rng.randint(3, 4), strict)
        n_side = 3
    if rec['mix'] == 'gem_poor':
        n_side = max(3, n_side // 2)
    if kind == 'tiny_desert':
        n_side = 4
    place_groups(m, rng, rec['mix'], n_side, need_s2s, strict=strict)
    for isl, names in islands:
        place_in_island(m, rng, isl, names, 1 if kind == 'normal' else rng.randint(1, 3))
    return m


def validate(m, rec):
    """Legality, symmetry and reachability checks on the design. Returns (ok, reason)."""
    W, H = m.W, m.H
    for y in range(H):
        for x in range(W):
            if m.get(x, y) != m.get(*m.mir(x, y)):
                return False, 'asymmetric terrain'
    for p, t in m.camp.items():
        if m.camp.get(m.mir(*p)) != t:
            return False, 'asymmetric camps'
        if (m.get(*p) != FLOOR and not (rec.get("camp_bush") and m.get(*p) == BUSH)) or m.dspawn(*p) == 0:  # 12 Nov: camp_bush (w_bushcamp only) allows bush
            return False, 'camp on obstacle'
    for r in (m.rectA(), m.rectB()):
        for x in range(r[0], r[2]):
            for y in range(r[1], r[3]):
                if not m.inb(x, y) or m.get(x, y) != FLOOR:
                    return False, 'spawn obstructed'
    if not m.altars:
        return False, 'no altar'
    x0, y0, x1, y1 = m.spawn
    if not 9 <= (x1 - x0) * (y1 - y0) <= 16:  # MapBuilder accepts it, but the game fails to load (engine error 7)
        return False, 'spawn area outside 9..16 tiles'
    strict = rec.get('checks', 1) >= 2
    d = decode_like(m)
    f = mapfeat.analyse(d, 'design', legacy=not strict)  # version 1 rules keep every existing seed's map
    if strict:
        why = strict_checks(m, rec, d)
        if why:
            return False, why
    if rec['kind'] == 'long' and not (f['s2s'] is not None and 75 <= f['s2s'] <= 300):
        return False, f"long route s2s={f['s2s']}"
    if rec['kind'] in ('normal', 'long'):
        if f['s2s'] is None:
            return False, 'spawns not connected'
        if f['cry'] > 0 or f['none'] > 0 or f['dash'] > 0.12:
            return False, f"reach dash={f['dash']} cry={f['cry']} none={f['none']}"
        if not isinstance(f['alt_d'], int):
            return False, 'no walkable altar'
        if f['gems'] < 40 or f['grp'] < 6:
            return False, f"too little: gems={f['gems']} groups={f['grp']}"
    elif rec['kind'] == 'islands':
        if f['dash'] + f['cry'] < 0.4 or f['s2s'] is None or not isinstance(f['alt_d'], int):
            return False, f"islands dash={f['dash']}"
    elif rec['kind'] == 'dash_altar':
        if f['alt_d'] != 'd' or f['s2s'] is None:
            return False, f"dash_altar alt_d={f['alt_d']}"
    elif rec['kind'] == 'split':
        if f['s2s'] is not None or not isinstance(f['alt_d'], int) or f['gems'] < 40:
            return False, 'split not split'
    elif rec['kind'] == 'monolith_rush':
        if f['mono'] < 0.8 or f['s2s'] is None:
            return False, f"mono={f['mono']}"
    elif rec['kind'] == 'tiny_desert':
        if f['gems'] > 80 or f['s2s'] is None or f['s2s'] > 4:
            return False, f"desert gems={f['gems']} s2s={f['s2s']}"
    return True, f


def team_reach(d, crystal=True, block_camps=False):
    """Tiles team A reaches under the engine rules (mapfeat.py): walking, dashing and, with crystal, one crystal jump
    (Chebyshev 3, any terrain) then walking and dashing on. Camps are passable unless block_camps."""
    W, H = d['W'], d['H']
    bad = set(d['wall']) | set(d['hole']) | set(d['altar']) | set(d['spawnB'])
    if block_camps:
        bad |= set(d['camps'])
    wall = d['wall']

    def land(p):
        return 0 <= p[0] < W and 0 <= p[1] < H and p not in bad

    def close(starts, dash):
        seen, dq = set(starts), deque(starts)
        while dq:
            cx, cy = dq.popleft()
            for dx, dy in N8:
                n = (cx + dx, cy + dy)
                if n not in seen and land(n):
                    seen.add(n)
                    dq.append(n)
            if dash:
                for dx in (-2, -1, 0, 1, 2):
                    for dy in (-2, -1, 0, 1, 2):
                        n = (cx + dx, cy + dy)
                        if max(abs(dx), abs(dy)) != 2 or n in seen or not land(n):
                            continue
                        if any(max(abs(cx + mx - n[0]), abs(cy + my - n[1])) == 1 and 0 <= cx + mx < W
                               and 0 <= cy + my < H and (cx + mx, cy + my) not in wall for mx, my in N8):
                            seen.add(n)
                            dq.append(n)
        return seen
    r = close(list(d['spawnA']), not block_camps)
    if crystal:
        hop = {(x + dx, y + dy) for x, y in r for dx in range(-3, 4) for dy in range(-3, 4)}
        r = close(list(r | {p for p in hop if land(p)}), True)
    return r


def strict_checks(m, rec, d):
    """Checks added on 25 Oct (recipe 'checks' >= 2), run after the design is built so that a map that passes them is
    the same map as before: the 'split' halves never meet, not even by dashing or with a crystal (clear_spawn() used
    to cut the hole band beside a spawn: gen_up_006, gen_p_022, 035, 092), and on normal and long maps every altar has a
    free tribute tile that team A reaches without killing a camp (access_ok() skips protected altars, so a camp could
    close a shrine's only gate: gen_s_298). Returns the reason for a rejection, or None."""
    if rec['kind'] == 'split':
        for crystal in (False, True):
            r = team_reach(d, crystal)
            if any(m.mir(*p) in r for p in r):
                return 'split halves meet by ' + ('a crystal jump' if crystal else 'dashing')
    if rec['kind'] in ('normal', 'long'):
        r = team_reach(d, crystal=False, block_camps=True)
        def free(a):
            return [(a[0] + dx, a[1] + dy) for dx, dy in N8 if (a[0] + dx, a[1] + dy) not in d['camps']]
        for a in d['altar']:
            if not any(p in r for p in free(a) + free(m.mir(*a))):
                return f'altar {a} gated by camps'
    return None


def decode_like(m):
    """The design in map26a.decode's format (so mapfeat analyses designs and built maps the same way)."""
    W = m.W
    sets = {k: set() for k in (WALL, HOLE, BUSH, ALTAR)}
    for i, v in enumerate(m.g):
        if v in sets:
            sets[v].add((i % W, i // W))
    x0, y0, x1, y1 = m.rectA()
    rb = m.rectB()
    return dict(W=m.W, H=m.H, champs_per_team=m.T, symmetry=m.sym, wall=sets[WALL], hole=sets[HOLE], bush=sets[BUSH],
                altar=sets[ALTAR], camps=dict(m.camp),
                spawnA={(x, y) for x in range(x0, x1) for y in range(y0, y1)},
                spawnB={(x, y) for x in range(rb[0], rb[2]) for y in range(rb[1], rb[3])})


def spec_of(m):
    W = m.W

    def canon(x, y):
        mx, my = m.mir(x, y)
        return y * W + x <= my * W + mx
    tiles = lambda v: [[i % W, i // W] for i, t in enumerate(m.g) if t == v and canon(i % W, i // W)]  # noqa: E731
    return dict(w=m.W, h=m.H, sym=m.sym, champs=m.T, spawn=list(m.spawn), altars=tiles(ALTAR), walls=tiles(WALL),
                holes=tiles(HOLE), bushes=tiles(BUSH),
                camps=[[x, y, t] for (x, y), t in sorted(m.camp.items(), key=lambda kv: (kv[0][1], kv[0][0])) if canon(x, y)])


_MK = {}  # pid -> one `node mkmap.js --serve` per process (a forked pool worker starts its own)


def mkmap(spec_path, map_path):
    """-> (rc, stderr). 5 Nov: one node process per map filled /var (root logs every program start); the server builds each map
    on a fresh engine instance, byte-identical (30/30 checked). Any server failure falls back to a process for that map."""
    if os.environ.get("MKMAP_SERVE", "1") != "0":
        p = _MK.get(os.getpid())
        try:
            if p is None or p.poll() is not None:
                p = _MK[os.getpid()] = subprocess.Popen(['node', MKMAP, '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            p.stdin.write(json.dumps(dict(wasm=WASM, out=map_path, spec=spec_path)) + '\n')
            p.stdin.flush()
            line = p.stdout.readline()
            if line:
                r = json.loads(line)
                return r['rc'], r['err']
        except (OSError, ValueError, BrokenPipeError):
            pass
        _MK.pop(os.getpid(), None)
    r = subprocess.run(['node', MKMAP, WASM, map_path, spec_path], capture_output=True, text=True)
    return r.returncode, r.stderr


def build_and_check(m, spec_path, map_path):
    rc, err = mkmap(spec_path, map_path)
    if rc != 0 or 'verify failed' in err:
        raise RuntimeError('mkmap: ' + err[-500:])
    d = map26a.load(map_path)
    want = decode_like(m)
    assert (d['W'], d['H'], d['symmetry'], d['champs_per_team']) == (m.W, m.H, m.sym, m.T), 'header'
    assert d['spawnA_rect'] == tuple(m.spawn), 'spawn'
    for k in ('wall', 'hole', 'bush', 'altar'):
        assert d[k] == want[k], k
    assert d['spawnB'] == want['spawnB'], 'spawnB'
    assert d['camps'] == m.camp, 'camps'
    return d


def install(src, dst):
    """Copy only when the content differs, so a map file's mtime changes exactly when its content changes:
    tools/lab/abindex.py drops local results played before a map's file changed."""
    if os.path.exists(dst) and open(dst, 'rb').read() == open(src, 'rb').read():
        return False
    shutil.copyfile(src, dst)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=45)
    ap.add_argument('--only', type=int, nargs='*')
    ap.add_argument('--outdir')
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--show', type=int)
    ap.add_argument('--dev', action='store_true')
    ap.add_argument('--checks', type=int, default=1)
    a = ap.parse_args()
    # --dev: the development twin (same recipes, other seeds), named gen_dev_NN so abl.sh's default list skips it
    prefix, base = ('gen_dev_', 500000) if a.dev else ('gen_', 0)
    a.outdir = a.outdir or ('/data/USER/genmaps_dev' if a.dev else '/data/USER/genmaps')
    install_dirs = INSTALL_DIRS[:1] if a.dev else INSTALL_DIRS
    if a.show:
        print(open(os.path.join(a.outdir, f'{prefix}{a.show:02d}.txt')).read())
        return
    os.makedirs(a.outdir, exist_ok=True)
    recs = schedule(a.n)
    if a.checks >= 2:
        recs = [dict(r, checks=a.checks) for r in recs]
    index = {}
    ip = os.path.join(a.outdir, 'index.json')
    if os.path.exists(ip) and a.only:
        index = json.load(open(ip))
    for i, rec in enumerate(recs, 1):
        if a.only and i not in a.only:
            continue
        name = f'{prefix}{i:02d}'
        for attempt in range(40):
            seed = base + 1000 * i + attempt
            try:
                m = generate(rec, seed)
                ok, info = validate(m, rec)
            except RuntimeError as e:
                ok, info = False, str(e)
            if ok:
                break
            print(f'{name} seed {seed}: rejected ({info})', file=sys.stderr)
        else:
            raise SystemExit(f'{name}: no valid map in 40 attempts')
        sp, mp = os.path.join(a.outdir, name + '.json'), os.path.join(a.outdir, name + '.map26a')
        json.dump(spec_of(m), open(sp, 'w'))
        d = build_and_check(m, sp, mp)
        f = mapfeat.analyse(d, name)
        meta = dict(name=name, seed=seed, recipe=rec, features=f)
        json.dump(meta, open(os.path.join(a.outdir, name + '.meta.json'), 'w'), indent=1)
        open(os.path.join(a.outdir, name + '.txt'), 'w').write(m.ascii() + '\n')
        index[name] = meta
        print(f"{name} seed {seed} {rec['kind']:13s} {m.W}x{m.H} T{m.T} sym{m.sym} {rec.get('style')}/{rec.get('mix')}/"
              f"{rec.get('altar')}/{rec.get('spawn')}: gems {f['gems']} clu {f['clu']} heavy {f['heavy']} "
              f"dash {f['dash']} s2s {f['s2s']} alt {f['alt']} alt_d {f['alt_d']}")
        if a.install:
            for dd in install_dirs:
                install(mp, os.path.join(dd, name + '.map26a'))
    json.dump(index, open(ip, 'w'), indent=1)
    names = sorted(index)
    open(os.path.join(a.outdir, 'maplist.txt'), 'w').write(''.join(n + '\n' for n in names))
    open(os.path.join(a.outdir, 'maplist_normal.txt'), 'w').write(
        ''.join(n + '\n' for n in names if index[n]['recipe']['kind'] == 'normal'))
    open(os.path.join(a.outdir, 'maplist_long.txt'), 'w').write(
        ''.join(n + '\n' for n in names if index[n]['recipe']['kind'] == 'long'))
    open(os.path.join(a.outdir, 'maplist_patho.txt'), 'w').write(
        ''.join(n + '\n' for n in names if index[n]['recipe']['kind'] not in ('normal', 'long')))
    with open(os.path.join(a.outdir, 'previews.txt'), 'w') as pv:
        for n in names:
            r, f = index[n]['recipe'], index[n]['features']
            pv.write(f"== {n} {r['kind']} {f['W']}x{f['H']} T{f['T']} sym{f['sym']} style={r['style']} mix={r['mix']} "
                     f"mono={r.get('mono', 0)} altar={r['altar']} spawn={r['spawn']} | gems {f['gems']} s2s {f['s2s']}\n")
            pv.write(open(os.path.join(a.outdir, n + '.txt')).read() + '\n')


if __name__ == '__main__':
    main()
