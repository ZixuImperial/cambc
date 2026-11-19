#!/usr/bin/env python3
"""gencruel: CRUEL map families (Tool builder 2, 4 Nov; owner: "weirder maps so we overfit less", "the map maker can be more
cruel", "also include tight spaces", "camps trapped in an area so you need a ranged attack to even get in", "apart from spawn
be tight"). Each family targets one rule a bot can get wrong. Opt-in: not in genweird.FAMS, so stratmaps draws them only by
name (stratmaps.py DIR --n N --weird 1 --wfams w_snake,w_moatcamp,...) until each has a smoke read v live.

Tight spaces
  w_cramped     30-40 board, 4-5 a side, a 1-wide corridor maze everywhere EXCEPT a 2-tile open apron round each spawn
  w_spawncloset each spawn walled in, one 1-wide exit tunnel 2-5 long: every body leaves and returns single file
  w_alcove      every camp a single tile in a 1-tile alcove (walls on 7 sides): one melee body at a time, crews can't help
  w_bushplug    1-wide corridor maze whose narrow tiles are often a single bush: an unseen occupant blocks the move
Rule traps
  w_snake       1-3 long cardinally-joined camp chains a side (12-30 camps: wolves with gem/gold clusters): one group, one wake,
                one huge capture region, rewards summed
  w_campring    a closed ring of camps at Chebyshev 3 round each spawn (wolf ring, or wolves gated by clusters): fight out at r1
  w_revolving   rich 5x5 rooms whose only door is a camp tile: kill it to get in, and it respawns behind you
  w_hiddencamp  every camp ringed by bush: camps see you, you can't see them until you're next to them
  w_checker_big (10 Nov) w_checker on L boards (49+ a side), 2-3 fields of 8-10 a side: 90-130 camp groups (bot M.ng), the TWS1 draft-fuel band
  w_checker     fields of camps touching only at corners: every camp is its own 1-tile group, and the empty squares between
                them meet only diagonally (corner squeezes)
  w_evenrace    odd board, every camp and altar ON the mirror line: every race exactly equidistant, turn order decides
  w_moatcamp    camp rings on islands inside a hole moat: from the shore the ring is exactly 3 away, so only RANGED bodies
                can kill them (holes let sight through); capture needs a crystal (moat 2) or a dash over the hole (moat 1)
  w_goldcrystal gems in the open (clusters only, no wolves), every gold camp in a walled 3x3 pocket: gold only by crystal
  w_guardaltar  (5 Nov, Econ: 01boss-battle, 02guardians) the only altar (shared at the centre) or each side's own altar has
                every tribute tile a wall, a hole or a MONOLITH tile: nobody banks until that monolith dies. 1-2 monoliths
                (40% of them 2 tiles long, as on boss-battle); genmaps.generate_gate's adj_gate with monoliths, judged by
                validate_gate (access 'adjgate' for both sides) instead of the open-access check
  w_lines       (5 Nov, Combat cambc-71: 04lines' 31-camp gold rows, 01yellow-brick-road) 3-6 camp groups whose region is ONE
                tile tall and 15-35 long (gold, sometimes gems mixed in), sometimes one on the mirror axis; normal spawns
                and altars: capture standoffs and holders spread along a long region
  w_monocorner  (6 Nov, Econ: 03homonoliths, lost to a team 462 below us) a 2-4 monolith group in a walled pocket or corner
                behind each spawn (1-3 from the spawn rect, farther from the enemy than the spawn): <= 8-15 tiles a foe can stand on
                within 3 of it (spawn tiles not counted; the real map has 12), spawn-to-spawn walk >= 40 (real 58), gold clusters
                only elsewhere, other gold .2-.45 of the monolith gold (real .29), 3-5 a side
  w_monotank    (6 Nov, Econ: the 03homonoliths walk 01a1ae2d) w_monocorner whose group has a TANK TILE (tank_tiles below): a
                spawn tile in range 5 of every monolith and no farther from each than any non-spawn tile a melee or range-3 hitter
                could hit it from (ties allowed, as on 03homonoliths), so the camp's hits go to the body there, and the spawn heals it at each turn end
  w_onepack     (6 Nov, Builder: 00stampede, live 3-10; b852's gencentral retired, 0 of 1,497 fresh maps in the class) one
                central self-symmetric gem pack (gem clusters, rim of wolves/elks, no golem or monolith) that a base-stat team can't
                clear in one pass, >= 95% of the gems, walk >= 30 from each spawn, gold clusters nearer (>= 400 gold): passes the
                bot's ONE_PACK test (onepack() below, a port of draft.cpp one_pack/op_load, b1326's donor)
  w_onemono     (6 Nov, Econ OGS read: 00rows, our worst map at .11 live, and 00anvil) w_onepack's sibling where the central
                self-symmetric pack is a MONOLITH siege: 2-4 monoliths (mirrored pairs, or the centre tile) among gem clusters,
                or ONE monolith on a self-mirror centre tile (as 00anvil), >= 70% of the map's gems (70-95%: some small gem groups
                stay elsewhere), walk >= 10 from each spawn (Econ's gate is the 70% share; 6 Nov: walk and gold rules relaxed). Measured: 00rows pack 470 of 584 gems (80%), 2 monoliths, walk 34; 00anvil 200 of 258
                (78%), 1 monolith, walk 13
  w_longpath    (11 Nov, owner map long_path: 100x100, s2s 4781) ONE serpentine corridor 1-3 wide (walls 1-3) filling each
                half on a cell grid (by columns, or by rows on x/y-mirror boards; shallower turns on some draws), joined on the
                axis; spawn in a corner block with its altar (a second altar in a niche on half the draws); camps in wall niches
                along the route (and inside it when 2+ wide), never on it. Check: s2s >= 15x the spawn Chebyshev gap (or
                >= 1500 on 70+ boards), no camp on the route, >= 6 groups, wall >= 35%
  w_crosswires  (11 Nov, owner map crosswires: 40x40 lattice, 58 groups, 30 altars) 30-56 a side, walls with a hole border on
                most draws; walkable tiles meet only DIAGONALLY: walled-in spawn left through ring corners, a diagonal corridor
                (corner squeezes) to the axis, edge strips of hole/floor/1-tile camps/altars (tribute tiles are camps: kill
                to bank), checkerboard bands of 1-tile camps, rooms (bush, clusters, 2x2 heavy) linked by a diagonal corridor,
                a floor/hole DASH line or nothing (crystal), checkerboard hole fields. Check: wall+hole >= 60%, >= 30 camp
                groups (>= 60% one tile), >= 10 altars, spawns never meet by orthogonal steps, some gems dash/crystal only
  w_manygrp     (11 Nov, RC X306: the pool and BIG top out at 64 camp groups, ladder 04gem-caverns has 114; the v712 TSO1 fuel
                regression only showed there) ladder-shaped many-group boards: 56-90 a side (04gem-caverns 65x65 114 groups,
                04sanctum 69x69 60, 04gem-rush 80x81 58), normal terrain styles (open/mixed/corridors/holes/bushbelt), normal
                altars, then 33-65 small groups a side spread over the board: a scatter of 1-tile gem clusters (caverns, rush),
                1-tile mixed singles, sanctum-like 2-6 tile groups (wolf+clusters, gold rows, gem patches, elk guards), or a
                blend; <= 240 camps. Check: 65 <= mapfeat grp <= 130 on the built map, board >= 50 a side
  w_goldrace1   (11 Nov, Econ spec_grc_1111 GRC: 03colosseum / 04sanctum / 02the_pack, the grc1 class) area 2,400-4,800, mirrored
                spawns 38-42 apart (Chebyshev between spawn-rect centres, mapclass s2s), ONE altar tile on the self-mirror tile at
                the board centre (odd side(s) on the mirror axis), no elk/golem/monolith; 14-28 small groups a side: gold
                clusters of 5 and of 1 tile, wolf+gem pairs, steered to a gold_share G/(G+10M) target in .43-.52. Check: 1 altar
                tile, gold_share .40-.55, no heavy camp, 25 <= mapfeat grp <= 60, area and s2s in range. Opt-in by name only
                (never in genweird.FAMS or the stratmaps default mix): stratmaps.py DIR --n N --weird 1 --wfams w_goldrace1
  w_elkctr      (12 Nov, Planner) jackpot layout whose centre is a gem diamond + 3-6 elk (no golem / monolith anywhere); 40/40 in
                mapclass elkctr (ladder 6: 00collision 00eight 00pilgrimage 00stampede 00swirl 01starfish). --wfams w_elkctr (opt-in)
  w_keystone    (12 Nov, Deep KSD + Aggression LSO) jackpot layout with a gem-clusters-only centre (Strength 0); 33/40 in mapclass
                keystone_s0 (draw with --class keystone_s0:>=1). --wfams w_keystone (opt-in)
  w_jackpot2    (12 Nov, Planner JKP re-read) w_jackpot with a heavy centre: 2 monoliths or monolith + 2 golems, centre HP >= 40,000 (00rows
                41,200); 40/40 in mapclass jackpot. --wfams w_jackpot2 (opt-in)
  w_goldcol / w_gemcol (12 Nov, Aggression, owner: long capture standoff) one straight 1xN column (N 30-45) of gold / gem clusters, one
                group, on the axis or one a side, flanked by nothing/bush/wall; 20/20 rspan and gtiles >= 20. --wfams w_goldcol,w_gemcol
  w_hms         (11 Nov, Builder DGR/HFT: the hms class, as b1789's hand-built maps) 255-440 camp groups, mostly lone wolves, 55-99 a side;
                20/20 in range (274-436), cxe plays them. --wfams w_hms (rare banks: --rare-fams w_hms); class ngroups:>=255
  w_jackpot     (11 Nov, Deep/Planner: mapclass jackpot = JACKPOT + GOLD HALVES, 00rows) one self-mirror centre group (monolith + gem
                diamond + elk tips, 312-400 gems), gem-poor gold halves; 40/40 maps in class. --wfams w_jackpot
  w_nointer     (11 Nov, owner via Path Finding: enemy-less farming race) 40-80 a side, the mirror axis is an 8-9 tile WALL band
                (no sight, walk, dash, crystal or ward across), own altars + heavy groups each half. --wfams w_nointer; class nointer
  w_goldring1   (11 Nov, spec_bly_1111 GPK class for the BLY foe: 1 altar, gold_share .37-.56, 36-70 groups, no heavy; 20/20 maps in class)
                Opt-in: stratmaps.py DIR --n N --weird 1 --wfams w_goldring1
  w_altargems1  (11 Nov, Econ spec_als_1111 ALS: 04comb's altar-side cluster groups; the als1 class) 55-79 a side, ONE altar tile on
                a self-mirror tile (anywhere on the mirror axis, the centre on rotated boards) >= 25 walk tiles (8-way, walls/holes
                block) from each spawn; small altar-side gem groups (2-3 gem clusters + 1 wolf, 18-25 gems) with a tile within
                Chebyshev 6 of it holding 25-40% of the camp gems (steered to a target in .27-.38); the rest gold+elk groups
                (elk, elk pairs, elk + gold, gold rows/patches) in the home/mid zones, every tile > 8 from the altar; no golem or
                monolith. Check: 1 altar tile, als_share (mapclass.d/als1.py) .25-.40, altar walk >= 25 from each spawn, no
                golem/monolith. Opt-in by name only: stratmaps.py DIR --n N --weird 1 --wfams w_altargems1
API (genweird calls these): FAMS, recipe(fam, rng), make(fam, rec, seed, rng) -> Map, check(fam, m, f, x) -> None or why."""
import random

import genfam as NF
import genfuel as GF
import genmaps as G

FLOOR, WALL, HOLE, BUSH, ALTAR = G.FLOOR, G.WALL, G.HOLE, G.BUSH, G.ALTAR
WOLF, ELK, GEM, GOLD, MONO, GOLEM = G.WOLF, G.ELK, G.GEM, G.GOLD, G.MONO, G.GOLEM
N4, N8 = G.N4, G.N8
FAMS = ["w_cramped", "w_spawncloset", "w_alcove", "w_bushplug", "w_snake", "w_campring", "w_revolving", "w_hiddencamp",
        "w_checker", "w_evenrace", "w_moatcamp", "w_goldcrystal", "w_guardaltar", "w_lines", "w_monocorner", "w_monotank", "w_onepack", "w_onemono",
        "w_checker_big", "w_longpath", "w_crosswires", "w_manygrp", "w_goldrace1", "w_altargems1", "w_richcentre", "w_bushroutes",
        "w_goldring1", "w_nointer", "w_jackpot", "w_hms", "w_goldcol", "w_gemcol", "w_jackpot2", "w_keystone", "w_elkctr"]
G.MIXES.setdefault("w_gembits", {"gem1": 3})


def _cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _walk(m, x, y):
    return m.inb(x, y) and m.get(x, y) in (FLOOR, BUSH)


def _box_free(m, cx, cy, r, dmin, sep=2):
    """Every tile within r of (cx, cy) walkable floor/bush, no camp, no altar, not protected, >= dmin from both spawns; the box
    and its mirror image at least sep apart."""
    box = [(cx + dx, cy + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
    for p in box:
        if not _walk(m, *p) or p in m.camp or p in m.protect or m.dspawn(*p) < dmin:
            return False
        if any(m.inb(p[0] + dx, p[1] + dy) and m.get(p[0] + dx, p[1] + dy) == ALTAR for dx, dy in N8):
            return False
    mx, my = m.mir(cx, cy)
    return _cheb((cx, cy), (mx, my)) > 2 * r + sep


def _put_camp(m, p, t):
    m.camp[p] = t
    m.camp[m.mir(*p)] = t


def _connected(m, block_camps=False):
    return m.s2s(m.bfs("A", block_camps=block_camps))


def _altars_walkable(m):
    walk = m.bfs("A")
    return any((a[0] + dx, a[1] + dy) in walk or m.mir(a[0] + dx, a[1] + dy) in walk for a in m.altars for dx, dy in N8)


def _snap(m):
    return bytes(m.g), dict(m.camp), list(m.groups), list(m.altars)


def _restore(m, s):
    m.g[:] = s[0]
    m.camp, m.groups, m.altars = dict(s[1]), list(s[2]), list(s[3])


def _drop_near(m, r, dist):
    """Remove every group with a tile within dist of rect r (genfam.remove_group also clears the mirror)."""
    for t, _ in list(m.groups):
        if any(m.cheb_rect(r, *p) <= dist for p in t):
            NF.remove_group(m, t)
    for p in [p for p in m.camp if m.cheb_rect(r, *p) <= dist or m.cheb_rect(r, *m.mir(*p)) <= dist]:
        m.camp.pop(p, None)


def _pick(rng, wts):
    ks = list(wts)
    return rng.choices(ks, [wts[k] for k in ks])[0]


# ---------------------------------------------------------------- recipes
def recipe(fam, r):
    if fam in ("w_cramped", "w_bushplug"):
        d = (r.randint(30, 40), r.randint(30, 40)) if fam == "w_cramped" else None
        rec = NF.base_rec(r, size=r.choice(["M", "L"]), sym=r.choice([0, 1, 2]), altar=r.choice(["near", "far", "shared", "many"]),
                          T=r.choice([4, 5, 5]) if fam == "w_cramped" else r.choice([3, 4, 5]), mix=r.choice(["cluster_heavy", "balanced"]))
        rec.update(cw=1, wt=r.choice([1, 1, 2]), p_loop=r.uniform(0.08, 0.3), rooms=r.randint(2, 5), cross=r.randint(1, 3),
                   plug=r.uniform(0.25, 0.5))
        if d:
            rec["dims"] = d
        return rec
    if fam == "w_spawncloset":
        return NF.base_rec(r, size=r.choice(["M", "L", "L"]), spawn=r.choice(["medium", "long"]), tun=r.randint(2, 5))
    if fam == "w_alcove":
        return NF.base_rec(r, size=r.choice(["M", "L"]), style=r.choice(["open", "mixed", "bushbelt", "corridors"]), nalc=r.randint(8, 16))
    if fam == "w_snake":
        return NF.base_rec(r, size=r.choice(["L", "L", "XL"]), style=r.choice(["open", "mixed", "holes", "bushbelt"]),
                           nsnake=r.randint(1, 3), slen=(r.randint(12, 18), r.randint(18, 30)), nsmall=r.randint(2, 4))
    if fam == "w_campring":
        return NF.base_rec(r, size=r.choice(["M", "L", "L"]), spawn=r.choice(["medium", "long"]),
                           ring=r.choice(["wolf", "wolf", "gated", "elkwolf"]))
    if fam == "w_revolving":
        return NF.base_rec(r, size=r.choice(["L", "XL"]), style=r.choice(["open", "mixed", "bushbelt"]), nroom=r.randint(1, 3),
                           door=r.choice([WOLF, WOLF, ELK, GOLEM]), keep=r.randint(3, 6))
    if fam == "w_hiddencamp":
        return NF.base_rec(r, mix=r.choice(["cluster_heavy", "golems", "balanced", "elk_heavy"]),
                           style=r.choice(["open", "mixed", "corridors"]), rad=r.choice([1, 1, 2]))
    if fam == "w_checker_big":  # 10 Nov (Builder/b1828, TWS1 draft-fuel band): w_checker on large boards, 90-130 bot-view groups (M.ng = 4-connected camp groups)
        return NF.base_rec(r, size="L", style=r.choice(["open", "mixed"]), nfield=r.randint(2, 3), fw=r.randint(8, 10), fh=r.randint(8, 10), nsmall=r.randint(1, 2))
    if fam == "w_checker":
        return NF.base_rec(r, size=r.choice(["M", "L"]), style=r.choice(["open", "mixed"]), nfield=r.randint(1, 2),
                           fw=r.randint(5, 9), fh=r.randint(5, 9), nsmall=r.randint(1, 3))
    if fam == "w_evenrace":
        sym = r.choice([0, 1])
        a, b = r.randint(15, 32) * 2 + 1, r.randint(30, 64)  # the mirrored axis is odd, so its centre line is a column / row of tiles
        return NF.base_rec(r, size="M", sym=sym, dims=(a, b) if sym == 0 else (b, a), style=r.choice(["open", "mixed", "corridors", "bushbelt"]),
                           nrun=r.randint(5, 10), nalt=r.choice([1, 1, 2]))
    if fam == "w_moatcamp":
        return NF.base_rec(r, size=r.choice(["L", "L", "XL"]), style=r.choice(["open", "mixed", "bushbelt"]), nisl=r.randint(2, 4),
                           moat=r.choice([1, 2, 2]), keep=r.randint(2, 5))
    if fam == "w_goldcrystal":
        return NF.base_rec(r, size="XL", aspect="square", dims=(r.randint(50, 80), r.randint(50, 80)), T=r.choice([3, 3, 4, 5]),
                           mix="w_gembits", mono=0, far="shared", keep=r.randint(4, 7), spawn=r.choice(["long", "medium"]),
                           npocket=r.randint(2, 5))
    if fam == "w_lines":
        return NF.base_rec(r, size=r.choice(["L", "L", "XL"]), style=r.choice(["open", "open", "mixed", "bushbelt", "corridors"]),
                           nline=r.randint(2, 3), axis=r.random() < 0.4, gemmix=r.random() < 0.35, lmax=r.randint(22, 35))
    if fam == "w_onemono":
        return NF.base_rec(r, mix="nf_gold", mono=0, size=r.choice(["M", "L", "L", "XL"]), T=r.choice([3, 3, 4, 5]),
                           altar=r.choice(["near", "far", "shared", "many"]), hsize=r.randint(6, 18), npair=r.choice([0, 0, 1, 1, 2]),
                           share=r.uniform(0.70, 0.95))
    if fam == "w_onepack":
        return NF.base_rec(r, mix="nf_gold", mono=0, size=r.choice(["L", "XL", "XL"]), spawn="long",
                           T=r.choice([3, 4, 5, 5]), altar=r.choice(["near", "far", "shared", "many"]), hsize=r.randint(18, 40),
                           rim=r.uniform(0.35, 0.8), elk=r.uniform(0.3, 0.8))
    if fam in ("w_monocorner", "w_monotank"):
        return NF.base_rec(r, mix="nf_gold", mono=0, size=r.choice(["M", "L", "L"]), spawn=r.choice(["long", "long", "medium"]),
                           T=r.choice([3, 4, 5]), altar=r.choice(["central", "shared", "near", "far"]), nm=r.randint(2, 4),
                           cap=r.randint(8, 15), gr=r.uniform(0.2, 0.45))
    if fam == "w_guardaltar":
        rec = NF.base_rec(r, size=r.choice(["M", "L", "L"]), style=r.choice(["open", "mixed", "corridors", "bushbelt"]))
        rec.update(kind="adj_gate", gate_over=dict(camp=MONO, gates=r.choice([1, 1, 2])), mono2=r.random() < 0.4)
        return rec
    if fam == "w_longpath":  # 11 Nov: pitch (cw + wt) capped by board size so the route is >= 15x the spawn gap
        a = r.choice([r.randint(48, 61), r.randint(62, 79), r.randint(80, 100), r.randint(80, 100)])
        b = a if r.random() < 0.6 else r.randint(max(44, a * 2 // 3), a)
        pmax = 3 if b < 62 else 4 if b < 80 else 5
        cw = min(r.choice([1, 1, 2, 3]), pmax - 1)
        rec = NF.base_rec(r, size="XL" if a >= 76 else "L", sym=r.choice([0, 0, 1, 2]), T=r.choice([3, 4, 5]), dims=(a, b) if r.random() < 0.5 else (b, a))
        rec.update(cw=cw, wt=r.randint(1, max(1, min(3, pmax - cw))), orient=r.choice(["col", "col", "row"]), jit=r.choice([0, 0, 0.15, 0.3]),
                   bushp=r.choice([0, 0, 0.05, 0.15]), alt2=r.random() < 0.5, mix=r.choice(["gold", "gold", "balanced", "gems", "heavy"]),
                   ng=r.randint(4, 12) + a // 15, nin=r.randint(1, 4), flip=r.random() < 0.5)
        return rec
    if fam == "w_crosswires":
        a = r.randint(30, 56)
        b = a if r.random() < 0.5 else r.randint(30, 56)
        rec = NF.base_rec(r, size="M", sym=r.choice([0, 1, 2, 2]), T=r.choice([3, 4, 5, 5]), dims=(a, b))
        na = r.randint(3, 7)
        rec.update(hborder=r.random() < 0.6, nstrip=max(r.randint(1, 3), -(-5 // (na + 1))), na=na, openp=r.choice([0, 0.3, 0.6]),
                   npocket=r.randint(2, 5), nstair=r.randint(3, 6), holef=r.uniform(0.06, 0.2), bushp=r.choice([0, 0, 0.08]),
                   nway=r.randint(2, 5), exits=r.choice([1, 1, 2]), linkw=r.choice([(1, 1, 1), (1, 2, 2), (2, 1, 1)]))
        return rec
    if fam in ("w_goldcol", "w_gemcol"):  # 12 Nov (Aggression, owner: "make these map types if you need for testing"; long capture standoff,
        # spec_lso_1112): one straight 1xN camp column (N 30-45, a single cardinally connected group; gold clusters or gem clusters) on an
        # otherwise ordinary map: on the mirror axis (one shared group) or one per side, flanked by nothing, bushes or walls
        a = r.randint(50, 90)
        b = a if r.random() < 0.5 else r.randint(max(46, a - 25), a)
        W, H = (a, b) if r.random() < 0.5 else (b, a)
        sym = r.choice([0, 1, 2])
        if sym == 0:
            W += (W % 2 == 0)
        if sym == 1:
            H += (H % 2 == 0)
        rec = NF.base_rec(r, size="XL" if max(W, H) >= 76 else "L", sym=sym, T=r.choice([3, 4, 5, 5]), dims=(W, H), mono=r.choice([0, 0, 1]),
                          altar=r.choice(["near", "far", "many", "shared"]), style=r.choice(["open", "open", "mixed", "corridors", "bushbelt"]),
                          spawn=r.choice(["long", "medium", "short"]))
        rec.update(colN=r.randint(30, 45), colkind=GOLD if fam == "w_goldcol" else GEM, colplace=r.choice(["axis", "axis", "side", "side", "side"]),
                   colflank=r.choice(["none", "none", "bush", "bush", "wall"]), colflankp=r.uniform(0.3, 0.9))
        return rec
    if fam == "w_hms":  # 11 Nov (Builder: DGR b2060 / HFT b2043, owner never-burn-out): the hms class, 255-432 camp groups (lone wolves
        # mostly) on 55-99 boards, as b1789's hand-built hms_* maps; mapclass ngroups:>=255. w_manygrp's builder with a 500-camp cap
        a = r.randint(55, 99)
        b = a if r.random() < 0.6 else r.randint(max(55, a - 14), a)
        rec = NF.base_rec(r, size="XL" if a >= 76 else "L", sym=r.choice([0, 1, 2, 2]), T=r.choice([3, 4, 5, 5]),
                          dims=(a, b) if r.random() < 0.5 else (b, a), style=r.choice(["open", "open", "open", "mixed", "corridors"]),
                          altar=r.choice(["near", "far", "many", "many"]), mono=r.choice([0, 0, 1]), spawn=r.choice(["long", "medium"]))
        rec.update(mgmix=r.choice(["wolfswarm", "wolfswarm", "swarmmix"]), ngs=r.randint(135, 220), mgcap=490,
                   zw=r.choice([(0.4, 0.35, 0.25), (0.34, 0.33, 0.33)]))
        return rec
    if fam == "w_manygrp":  # 11 Nov (RC X306): the ladder's many-group band, 65-130 mapfeat groups
        a = r.randint(56, 90)
        b = a if r.random() < 0.6 else r.randint(max(50, a - 20), a)
        rec = NF.base_rec(r, size="XL" if a >= 76 else "L", sym=r.choice([0, 1, 2, 2]), T=r.choice([3, 4, 5, 5, 5]),
                          dims=(a, b) if r.random() < 0.5 else (b, a), style=r.choice(["open", "open", "mixed", "mixed", "corridors", "holes", "bushbelt"]),
                          altar=r.choice(["central", "central", "shared", "near", "far", "many"]), mono=0,
                          spawn=r.choice(["long", "long", "medium"]))  # ladder many-group maps: s2s 68-164
        rec.update(mgmix=r.choice(["gemscatter", "singles", "small", "blend", "blend"]), ngs=r.randint(33, 65),
                   zw=r.choice([(0.45, 0.33, 0.22), (0.34, 0.33, 0.33), (0.5, 0.3, 0.2)]))
        return rec
    if fam == "w_goldrace1":  # 11 Nov (Econ GRC): grc1-class boards; the mirrored side is odd so the centre altar is one self-mirror tile
        sym = r.choice([0, 0, 1, 2, 2])
        while True:
            W, H = r.randint(45, 73), r.randint(45, 73)
            if sym in (0, 2) and W % 2 == 0:
                W += 1 if W < 73 else -1
            if sym in (1, 2) and H % 2 == 0:
                H += 1 if H < 73 else -1
            if 2400 <= W * H <= 4800 and (W if sym == 0 else H if sym == 1 else max(W, H)) >= 49:
                break
        rec = NF.base_rec(r, size="L", sym=sym, T=r.choice([3, 4, 5, 5]), dims=(W, H), mono=0, altar="central", mix="balanced",
                          style=r.choice(["open", "open", "mixed", "mixed", "corridors", "holes", "bushbelt"]), spawn="long")
        rec.update(ngs=r.randint(14, 28), gs=r.uniform(0.43, 0.52), p5=r.uniform(0.3, 0.7), noise=r.choice([0.1, 0.2, 0.3]),
                   zw=r.choice([(0.45, 0.33, 0.22), (0.34, 0.33, 0.33), (0.4, 0.4, 0.2)]), s2s=(38, 42))
        return rec
    if fam == "w_bushroutes":  # 11 Nov (owner: "a lot of bushy maps, especially on key routes or hotspots, for vision limiting")
        rec = NF.base_rec(r, size=r.choice(["S", "M", "M", "L", "L"]), style=r.choice(["open", "open", "mixed", "corridors", "holes"]))
        rec.update(proute=r.uniform(0.35, 0.75), widen=r.choice([0, 1, 1]), phot=r.uniform(0.25, 0.6), hotr=r.choice([2, 3, 3, 4]))
        return rec
    if fam == "w_richcentre":  # 11 Nov (owner: "resource heavy centred maps, as we are bad with contested stuff due to coordination")
        rec = NF.base_rec(r, size=r.choice(["M", "L", "L"]), mono=0, mix="balanced", spawn=r.choice(["medium", "long", "long"]),
                          altar=r.choice(["near", "far", "shared", "many"]), style=r.choice(["open", "open", "mixed", "holes", "bushbelt"]))
        rec.update(rad=r.randint(7, 12), npair=r.randint(2, 4), gmin=3, gmax=r.randint(4, 7), pgolem=r.uniform(0.15, 0.35),
                   pelk=r.uniform(0.25, 0.45), outer=r.choice(["gold", "gold", "mixed"]))
        return rec
    if fam == "w_elkctr":  # 12 Nov (Planner: ladder 4.3%, fresh 0.67%; 0/12 v the top 3; siege/crew never considers such groups):
        # mapclass elkctr: the biggest gem group is a mid elk group (>= 3 elk, no golem / monolith), >= 20% of the gem flow
        rec = recipe("w_jackpot", r)
        rec.update(heavy="elk", nelk=r.randint(3, 6), ring3=0, elk=0, nwolf=r.randint(4, 12), ngold=r.randint(1, 4))
        return rec
    if fam == "w_keystone":  # 12 Nov (Deep KSD + Aggression LSO, owner's 00the_line / 03one_gem line): mapclass keystone_s0, one
        # mid group of gem clusters only (Strength 0) holding most of the gem flow, wolf / gold halves; w_jackpot's builder
        rec = recipe("w_jackpot", r)
        rec.update(heavy="gems", ring3=r.randint(0, 12), elk=0)
        return rec
    if fam == "w_jackpot2":  # 12 Nov (Planner, JKP centre re-read; 00rows' centre needs a second trip): w_jackpot with a heavy centre,
        # two monoliths, or a monolith + golem(s): HP >= 40,000 (two 20,000-HP monoliths ~ 00rows' 41,200)
        rec = recipe("w_jackpot", r)
        rec.update(heavy=r.choice(["mono2", "mono2", "monogolem"]))
        return rec
    if fam == "w_jackpot":  # 11 Nov (Deep/Planner, owner's 00rows gate cell: the JACKPOT + GOLD HALVES class, mapclass jackpot; ~0.65% of
        # fresh): one self-mirror centre group (monolith + gem diamond + elk tips, >= 300 gems) and gold-heavy, gem-poor home halves
        sym = r.choice([0, 1, 2, 2])
        while True:
            W, H = r.randint(41, 75), r.randint(41, 75)
            W += (W % 2 == 0)
            H += (H % 2 == 0)
            if 1800 <= W * H <= 5200:
                break
        rec = NF.base_rec(r, size="L", sym=sym, T=r.choice([3, 4, 5, 5]), dims=(W, H), mono=0, altar=r.choice(["near", "far", "many"]),
                          mix="balanced", style=r.choice(["open", "open", "mixed", "corridors", "bushbelt", "holes"]), spawn=r.choice(["long", "medium"]))
        rec.update(nwolf=r.randint(6, 15), ngold=r.randint(1, 4), elk=r.choice([0, 2, 4]), ring3=r.randint(0, 12),
                   zw=r.choice([(0.8, 0.2, 0.0), (0.7, 0.3, 0.0), (1.0, 0.0, 0.0)]))
        return rec
    if fam == "w_nointer":  # 11 Nov (owner via Path Finding: the pair form "must do better on enemy-less maps"): a pure farming
        # race; genmaps' 'split' design (halves never meet) with the band turned to WALL and widened (see _m_nointer)
        W = H = r.randint(40, 80)
        if r.random() < 0.5:
            H = max(40, min(80, W + r.randint(-12, 12)))
        return NF.base_rec(r, kind="split", size="L", dims=(W, H), sym=r.choice([0, 1, 2]), altar=r.choice(["near", "far", "many", "many"]),
                           mono=r.choice([0, 1, 1, 2]), spawn=r.choice(["long", "medium"]))
    if fam == "w_goldring1":  # 11 Nov (Planner/Econ spec_bly_1111: the GPK class for the BLY foe: 1 altar, gold_share >= .35,
        # ngroups >= 35, heavy_ge2 <= .10; 0 of 400 BIG2 maps have it). w_goldrace1's builder, more groups, any spawn distance.
        rec = recipe("w_goldrace1", r)
        lo = r.choice([18, 24, 30, 36, 44])
        rec.update(ngs=r.randint(20, 32), s2s=(lo, lo + 8))
        return rec
    if fam == "w_altargems1":  # 11 Nov (Econ ALS): the mirrored side is odd, so the axis altar is one self-mirror tile
        sym = r.choice([0, 0, 1, 2, 2])
        W, H = r.randint(55, 79), r.randint(55, 79)
        if sym in (0, 2) and W % 2 == 0:
            W += 1 if W < 79 else -1
        if sym in (1, 2) and H % 2 == 0:
            H += 1 if H < 79 else -1
        rec = NF.base_rec(r, size="L", sym=sym, T=r.choice([3, 4, 5, 5]), dims=(W, H), mono=0, altar="central", mix="balanced",
                          style=r.choice(["open", "open", "mixed", "mixed", "corridors", "holes", "bushbelt"]),
                          spawn=r.choice(["long", "long", "medium"]))
        rec.update(ngs=r.randint(8, 18), ash=r.uniform(0.27, 0.38), noise=r.choice([0.1, 0.2]), zw=r.choice([(0.7, 0.3, 0.0), (0.55, 0.45, 0.0)]))
        return rec
    raise KeyError(fam)


# ---------------------------------------------------------------- builders
def _m_cramped(rec, seed, rng):
    m = NF.gen_maze(rec, seed)
    r = m.rectA()
    for x in range(r[0] - 2, r[2] + 2):  # the open apron: tight everywhere except round the spawns (owner)
        for y in range(r[1] - 2, r[3] + 2):
            if m.inb(x, y) and m.get(x, y) in (WALL, HOLE, BUSH) and (x, y) not in m.camp:
                m.put(x, y, FLOOR)
    return m


def _m_spawncloset(rec, seed, rng):
    m = G.generate(rec, seed)
    r, L = m.rectA(), rec["tun"]
    if m.cheb_rect(m.rectB(), r[0], r[1]) < 2 * L + 8:
        raise RuntimeError("spawns too close for closets")
    if any(m.cheb_rect(r, *a) <= L + 2 or m.cheb_rect(r, *m.mir(*a)) <= L + 2 for a in m.altars):
        raise RuntimeError("altar inside the closet zone")
    _drop_near(m, r, L + 2)
    cx, cy = (r[0] + r[2] - 1) / 2, (r[1] + r[3] - 1) / 2
    tx, ty = (m.W - 1) / 2 - cx, (m.H - 1) / 2 - cy
    d = max(N4, key=lambda v: v[0] * tx + v[1] * ty + rng.random())  # the exit faces the board centre
    if d[0]:
        ex = r[2] if d[0] > 0 else r[0] - 1
        ey = rng.randint(r[1], r[3] - 1)
    else:
        ey = r[3] if d[1] > 0 else r[1] - 1
        ex = rng.randint(r[0], r[2] - 1)
    tun = [(ex + k * d[0], ey + k * d[1]) for k in range(L)]
    if not all(m.inb(*p) and m.dspawn(*m.mir(*p)) > 0 and m.mir(*p) not in tun for p in tun):
        raise RuntimeError("tunnel off the board")
    ring = [(x, y) for x in range(r[0] - 1, r[2] + 1) for y in range(r[1] - 1, r[3] + 1) if m.cheb_rect(r, x, y) == 1]
    for p in ring:
        if m.inb(*p) and p not in tun:
            m.put(*p, WALL)
    for px, py in tun:
        m.put(px, py, FLOOR)
        for s in (1, -1):
            q = (px + s * d[1], py + s * d[0])  # the tunnel's two sides
            if m.inb(*q) and m.cheb_rect(r, *q) >= 1 and q not in m.camp:
                m.put(*q, WALL)
    end = (tun[-1][0] + d[0], tun[-1][1] + d[1])
    if not _walk(m, *end):
        m.put(*end, FLOOR)
    if not _connected(m, True) or not _altars_walkable(m):
        raise RuntimeError("closet cuts the map")
    return m


def _m_alcove(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    cand = [(x, y) for x in range(2, m.W - 2) for y in range(2, m.H - 2) if m.dspawn(x, y) >= 5]
    rng.shuffle(cand)
    wts = {GEM: 3, GOLD: 2, WOLF: 2, ELK: 1, GOLEM: 1}
    placed = 0
    for c in cand:
        if placed >= rec["nalc"]:
            break
        if not _box_free(m, c[0], c[1], 2, 5):
            continue
        d = rng.choice(N4)
        o = (c[0] + d[0], c[1] + d[1])
        s = _snap(m)
        for dx, dy in N8:
            q = (c[0] + dx, c[1] + dy)
            if q != o:
                m.put(*q, WALL)
        m.put(*c, FLOOR)
        m.put(*o, FLOOR)
        G.put_group(m, [(c[0], c[1], _pick(rng, wts))], "alcove")
        reach = m.bfs("A", block_camps=True)
        if (o in reach or m.mir(*o) in reach) and m.s2s(reach):
            placed += 1
        else:
            _restore(m, s)
    if placed < 6:
        raise RuntimeError(f"alcoves {placed}")
    return m


def _m_bushplug(rec, seed, rng):
    m = NF.gen_maze(rec, seed)
    plugs = []
    tiles = [(x, y) for x in range(m.W) for y in range(m.H)]
    rng.shuffle(tiles)
    for p in tiles:
        if m.get(*p) != FLOOR or p in m.camp or m.dspawn(*p) < 3:
            continue
        if sum(_walk(m, p[0] + dx, p[1] + dy) for dx, dy in N8) > 3:  # a corridor tile, not a junction or room
            continue
        if any((p[0] + dx, p[1] + dy) in m.camp or (m.inb(p[0] + dx, p[1] + dy) and m.get(p[0] + dx, p[1] + dy) == ALTAR) for dx, dy in N8):
            continue
        if any(_cheb(p, q) <= 3 or _cheb(m.mir(*p), q) <= 3 for q in plugs) or rng.random() > rec["plug"]:
            continue
        m.put(*p, BUSH)
        plugs.append(p)
    return m


def _snake_tiles(m, rng, n, wts):
    """A self-avoiding 4-connected walk of n floor tiles (not touching other camps, altars or its mirror)."""
    for _ in range(60):
        s = (rng.randrange(2, m.W - 2), rng.randrange(2, m.H - 2))
        if not _walk(m, *s) or m.dspawn(*s) < 4:
            continue
        path, d = [s], rng.choice(N4)
        while len(path) < n:
            opts = [v for v in N4 if (path[-1][0] + v[0], path[-1][1] + v[1]) not in path]
            opts = [v for v in opts if _walk(m, path[-1][0] + v[0], path[-1][1] + v[1]) and m.dspawn(path[-1][0] + v[0], path[-1][1] + v[1]) >= 3]
            if not opts:
                break
            d = d if d in opts and rng.random() < 0.6 else rng.choice(opts)
            path.append((path[-1][0] + d[0], path[-1][1] + d[1]))
        if len(path) < n:
            continue
        tiles = [(x, y, _pick(rng, wts)) for x, y in path]
        if not any(t == GEM for _, _, t in tiles):
            tiles[len(tiles) // 2] = (*path[len(path) // 2], GEM)
        for x, y in path:  # the snake may touch itself (still one group); drop floor->bush mismatch for group_ok
            if m.get(x, y) == BUSH:
                m.put(x, y, FLOOR)
        if G.group_ok(m, tiles):
            return tiles
    return None


def _m_snake(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    wts = {WOLF: 6, GEM: 3, GOLD: 2}
    got = 0
    for _ in range(rec["nsnake"] * 4):
        if got >= rec["nsnake"]:
            break
        tiles = _snake_tiles(m, rng, rng.randint(*rec["slen"]), wts)
        if not tiles:
            continue
        G.put_group(m, tiles, "snake")
        if _connected(m, True):
            got += 1
        else:
            G.drop_group(m)
    if not got:
        raise RuntimeError("no snake fits")
    G.place_groups(m, rng, "balanced", rec["nsmall"], True, strict=True)
    return m


def _m_campring(rec, seed, rng):
    m = G.generate(rec, seed)
    r, R = m.rectA(), 3
    if m.cheb_rect(m.rectB(), r[0], r[1]) < 2 * R + 6:
        raise RuntimeError("spawns too close for rings")
    if any(m.cheb_rect(r, *a) <= R + 1 or m.cheb_rect(r, *m.mir(*a)) <= R + 1 for a in m.altars):
        raise RuntimeError("altar inside the ring")
    _drop_near(m, r, R + 1)
    ring = [(x, y) for x in range(r[0] - R, r[2] + R) for y in range(r[1] - R, r[3] + R) if m.inb(x, y) and m.cheb_rect(r, x, y) == R]
    tiles = []
    for i, p in enumerate(sorted(ring)):
        v = m.get(*p)
        if v == HOLE:
            m.put(*p, WALL)  # a hole gap would let dashers out without a fight
            continue
        if v == WALL:
            continue
        m.put(*p, FLOOR)
        k = rec["ring"]
        t = (WOLF if k == "wolf" else GOLD if (k == "gated" and i % 3 == 0) else WOLF if k == "gated" else ELK if i % 4 == 0 else WOLF)
        tiles.append((p[0], p[1], t))
    G.put_group(m, tiles, "ring")
    for x, y in [(x, y) for x in range(r[0] - R + 1, r[2] + R - 1) for y in range(r[1] - R + 1, r[3] + R - 1)]:
        if m.cheb_rect(r, x, y) == R - 1 and m.get(x, y) == HOLE:
            m.put(x, y, FLOOR)
    if not _connected(m) or not _altars_walkable(m):
        raise RuntimeError("ring map not connected")
    return m


def _m_revolving(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.thin_groups(m, rng, rec["keep"])
    cand = [(x, y) for x in range(5, m.W - 5) for y in range(5, m.H - 5)]
    rng.shuffle(cand)
    rooms = 0
    for c in cand:
        if rooms >= rec["nroom"]:
            break
        if not _box_free(m, c[0], c[1], 4, 4):
            continue
        d = rng.choice(N4)
        door = (c[0] + 3 * d[0], c[1] + 3 * d[1])
        s = _snap(m)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                p = (c[0] + dx, c[1] + dy)
                m.put(*p, WALL if max(abs(dx), abs(dy)) == 3 and p != door else FLOOR)
                m.prot(*p)
        inner = [(c[0] + dx, c[1] + dy, GEM if rng.random() < 0.7 else GOLD) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        G.put_group(m, inner, "room")
        G.put_group(m, [(door[0], door[1], rec["door"])], "door")
        blk = m.bfs("A", block_camps=True)
        if m.s2s(blk) and c not in blk and m.mir(*c) not in blk and _altars_walkable(m):
            rooms += 1
        else:
            _restore(m, s)
            m.protect -= {(c[0] + dx, c[1] + dy) for dx in range(-3, 4) for dy in range(-3, 4)}
    if not rooms:
        raise RuntimeError("no room fits")
    return m


def _m_hiddencamp(rec, seed, rng):
    m = G.generate(rec, seed)
    rad = rec["rad"]
    for p, t in list(m.camp.items()):
        rr = rad if t in (GOLEM, MONO, ELK) else 1
        for dx in range(-rr, rr + 1):
            for dy in range(-rr, rr + 1):
                q = (p[0] + dx, p[1] + dy)
                if m.inb(*q) and m.get(*q) == FLOOR and q not in m.camp and m.dspawn(*q) >= 2:
                    m.put(*q, BUSH)
    return m


def _m_checker(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    wts = {GEM: 3, GOLD: 3, WOLF: 2, ELK: 1}
    fields = 0
    for _ in range(400):
        if fields >= rec["nfield"]:
            break
        w, h = rec["fw"], rec["fh"]
        x0, y0 = rng.randrange(1, max(2, m.W - w - 1)), rng.randrange(1, max(2, m.H - h - 1))
        cx, cy = x0 + w // 2, y0 + h // 2
        r = max(w, h) // 2 + 1
        if not _box_free(m, cx, cy, r, 4):
            continue
        s = _snap(m)
        for x in range(x0, x0 + w):
            for y in range(y0, y0 + h):
                m.put(x, y, FLOOR)
                if (x + y) % 2 == 0:
                    G.put_group(m, [(x, y, _pick(rng, wts))], "checker")
        if _connected(m) and len(G.spec_of(m)["camps"]) <= 200:
            fields += 1
        else:
            _restore(m, s)
    if not fields:
        raise RuntimeError("no checker field fits")
    G.place_groups(m, rng, "balanced", rec["nsmall"], True, strict=True)
    return m


def _m_evenrace(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    for a in m.altars:
        m.put(*a, FLOOR)
    m.altars = []
    axis = [(x, y) for x in range(m.W) for y in range(m.H) if m.mir(x, y) == (x, y)]
    rng.shuffle(axis)
    along = (0, 1) if m.sym == 0 else (1, 0)
    for p in axis:  # altars on the line, away from the spawns
        if len(m.altars) >= rec["nalt"]:
            break
        if m.get(*p) in (FLOOR, BUSH) and m.dspawn(*p) >= 6 and all(_cheb(p, a) >= 8 for a in m.altars):
            m.put(*p, FLOOR)
            G.add_altar(m, rng, p[0], p[1], double=False)
    if not m.altars:
        raise RuntimeError("no axis altar")
    wts = {GEM: 4, GOLD: 3, WOLF: 2, ELK: 1, GOLEM: 1}
    runs = 0
    for p in axis:
        if runs >= rec["nrun"]:
            break
        n = rng.randint(1, 3)
        tiles = [(p[0] + k * along[0], p[1] + k * along[1]) for k in range(n)]
        if not all(m.inb(*q) and m.get(*q) in (FLOOR, BUSH) and m.dspawn(*q) >= 3 and q not in m.camp for q in tiles):
            continue
        own = set(tiles)
        if any((q[0] + dx, q[1] + dy) not in own and ((q[0] + dx, q[1] + dy) in m.camp or
               (m.inb(q[0] + dx, q[1] + dy) and m.get(q[0] + dx, q[1] + dy) == ALTAR)) for q in tiles for dx, dy in N8):
            continue
        t = _pick(rng, wts)
        s = _snap(m)
        for q in tiles:
            m.put(*q, FLOOR)
            m.camp[q] = t  # on the axis: its own mirror
        m.groups.append((tiles, "axis"))
        reach = m.bfs("A", block_camps=True)
        if m.s2s(reach) and any((q[0] + dx, q[1] + dy) in reach for q in tiles for dx, dy in N8):
            runs += 1
        else:
            _restore(m, s)
    if runs < 4:
        raise RuntimeError(f"axis runs {runs}")
    return m


def _m_moatcamp(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.thin_groups(m, rng, rec["keep"])
    mw = rec["moat"]
    R = 1 + mw + 1  # ring 1, moat mw, a shore row
    wts = {GEM: 4, WOLF: 3, GOLD: 2, ELK: 1}
    isl = 0
    cand = [(x, y) for x in range(R + 1, m.W - R - 1) for y in range(R + 1, m.H - R - 1)]
    rng.shuffle(cand)
    for c in cand:
        if isl >= rec["nisl"]:
            break
        if not _box_free(m, c[0], c[1], R, 4):
            continue
        s = _snap(m)
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                k = max(abs(dx), abs(dy))
                p = (c[0] + dx, c[1] + dy)
                m.put(*p, FLOOR if k <= 1 or k == R else HOLE)
                if k < R:
                    m.prot(*p)
        ring = [(c[0] + dx, c[1] + dy, _pick(rng, wts)) for dx, dy in N8]  # the centre stays free floor
        if not any(t == GEM for _, _, t in ring):
            ring[0] = (ring[0][0], ring[0][1], GEM)
        G.put_group(m, ring, "moat")
        if _connected(m, True) and _altars_walkable(m):
            isl += 1
        else:
            _restore(m, s)
    if not isl:
        raise RuntimeError("no moat island fits")
    return m


def _m_goldcrystal(rec, seed, rng):
    m = NF.b_altfar(rec, seed)
    NF.thin_groups(m, rng, rec["keep"])
    for p in [p for p, t in m.camp.items() if t != GEM]:
        m.camp[p] = GEM
    cand = [(x, y) for x in range(4, m.W - 4) for y in range(4, m.H - 4)]
    rng.shuffle(cand)
    done = 0
    for cx, cy in cand:  # genweird._crystal_pockets with gold: a 3x3 floor inside a closed wall ring, reachable by crystal only
        if done >= rec["npocket"]:
            break
        if not _box_free(m, cx, cy, 3, 3) or any(_cheb((cx, cy), a) <= 4 for a in m.altars):
            continue
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                m.put(cx + dx, cy + dy, WALL if max(abs(dx), abs(dy)) == 2 else FLOOR)
                m.prot(cx + dx, cy + dy)
        G.put_group(m, [(cx, cy, GOLD)], "pocket")
        done += 1
    if done < rec["npocket"] or not _connected(m):
        raise RuntimeError("no room for the gold pockets")
    return m


def _m_guardaltar(rec, seed, rng):
    m = G.generate_gate(dict(rec, kind="adj_gate"), seed)
    if rec.get("mono2"):  # a 2-tile monolith (boss-battle's MM): the gate tile's outer neighbour joins its group
        ax, ay = m.gate["x"], m.gate["y"]
        for tiles, kind in m.groups:
            if kind != "gate" or len(tiles) != 1:
                continue
            (px, py), q = tiles[0], None
            q = (2 * px - ax, 2 * py - ay)
            if m.inb(*q) and m.get(*q) == FLOOR and q not in m.camp and m.mir(*q) not in m.camp and m.mir(*q) != (px, py):
                m.camp[q] = MONO
                m.camp[m.mir(*q)] = MONO
                tiles.append(q)
    return m


MONO_GOLD, CLUSTER_GOLD = 300, 20  # GameRules.md:188 (Monolith 300 gold) and the gold cluster's 20 (docs/rules/00_brief.md:34)


def _mc_stand(m, grp):
    """tiles a foe can stand on within Chebyshev 3 of the group: floor or bush, no camp, no altar, not a spawn tile"""
    rA, rB = m.rectA(), m.rectB()
    out = set()
    for gx, gy in grp:
        for x in range(gx - 3, gx + 4):
            for y in range(gy - 3, gy + 4):
                if _walk(m, x, y) and (x, y) not in m.camp and m.cheb_rect(rA, x, y) > 0 and m.cheb_rect(rB, x, y) > 0:
                    out.add((x, y))
    return out


def tank_tiles(stand, spawn, grp, reach=5, hit=3, strict=True):
    """Tank tiles of a camp group (Econ 6 Nov, 03homonoliths): spawn tiles t (stand(t) true) within `reach` (monolith range 5,
    GameRules.md:209) of every group tile g, and strictly nearer each g than every non-spawn tile s a hitter can use
    (stand(s), Chebyshev(s, g) <= hit: melee 1 and ranged 3, GameRules.md:254). A woken camp hits the NEAREST champion
    (GameRules.md:192; a tie goes to the one that acted first, docs/rules/20_interactions.md Q6; enemies cannot enter a spawn, Q9), so a body on t draws every
    hit while mates hit from farther, and the spawn heals it at each turn end. stand(p): a champion can stand on tile p
    (floor or bush, no camp, wall, hole or altar). spawn: set of the team's spawn tiles. -> list of tank tiles (empty: none).
    strict=False allows ties (a hitter tile as near as t; the engine then hits whoever acted first last round): 03homonoliths'
    own tile (1,1) is a tank only this way, since (2,0) and (0,2) are as near its outer monoliths."""
    """
    The same test works on a decoded map26a (tools/lab/map26a.load) as a map feature."""
    spawn, out = set(spawn), []
    for t in spawn:
        if not stand(t):
            continue
        ok = True
        for g in grp:
            dt = _cheb(t, g)
            lim = min(dt if strict else dt - 1, hit)
            if dt > reach or any(stand((x, y)) and (x, y) not in spawn
                                 for x in range(g[0] - lim, g[0] + lim + 1) for y in range(g[1] - lim, g[1] + lim + 1)):
                ok = False
                break
        if ok:
            out.append(t)
    return out


def _mc_tanks(m, grp):
    sp = {(x, y) for x in range(m.rectA()[0], m.rectA()[2]) for y in range(m.rectA()[1], m.rectA()[3])}
    return tank_tiles(lambda p: _walk(m, *p) and p not in m.camp, sp, grp, strict=False)  # as 03homonoliths' (1,1): ties allowed


def _mc_walk(m):
    dA, rB = m.bfs("A"), m.rectB()
    return min([d for p, d in dA.items() if m.cheb_rect(rB, *p) == 1] or [0])


def _m_monocorner(rec, seed, rng):
    m = G.generate(rec, seed)
    if _mc_walk(m) < 40:
        raise RuntimeError("spawns closer than 40 walk")
    rA, sc = m.rectA(), ((m.rectA()[0] + m.rectA()[2] - 1) / 2, (m.rectA()[1] + m.rectA()[3] - 1) / 2)
    bc = m.mir(round(sc[0]), round(sc[1]))
    behind = lambda x, y: _cheb((x, y), bc) > _cheb((round(sc[0]), round(sc[1])), bc)  # farther from the enemy spawn than ours
    cand = [(x, y) for x in range(m.W) for y in range(m.H) if 1 <= m.cheb_rect(rA, x, y) <= 3 and m.get(x, y) == FLOOR
            and (x, y) not in m.camp and behind(x, y)]
    rng.shuffle(cand)
    for start in cand[:150]:
        grp, frontier = [start], [start]
        while len(grp) < rec["nm"] and frontier:
            c = frontier.pop(rng.randrange(len(frontier)))
            for dx, dy in rng.sample(N4, 4):
                n = (c[0] + dx, c[1] + dy)
                if (n in grp or not m.inb(*n) or m.get(*n) != FLOOR or n in m.camp or not 1 <= m.cheb_rect(rA, *n) <= 3
                        or not behind(*n)):
                    continue
                grp.append(n)
                frontier.append(n)
                if len(grp) == rec["nm"]:
                    break
        if len(grp) < 2:
            continue
        own, mir = set(grp), {m.mir(*p) for p in grp}
        if own & mir or any((p[0] + dx, p[1] + dy) in mir for p in own for dx, dy in N8):
            continue
        if any((p[0] + dx, p[1] + dy) in m.camp or (m.inb(p[0] + dx, p[1] + dy) and m.get(p[0] + dx, p[1] + dy) == ALTAR)
               for p in own for dx, dy in N8):
            continue
        snap = _snap(m)
        G.put_group(m, [(x, y, MONO) for x, y in grp], "monocorner")
        if rec.get("tank"):  # w_monotank: the spawn tile nearest the group must out-near every hitter tile (wall those)
            sp = [(x, y) for x in range(rA[0], rA[2]) for y in range(rA[1], rA[3])]
            for g in grp:
                lim = min(3, min(_cheb(t, g) for t in sp) - 1)
                for x in range(g[0] - lim, g[0] + lim + 1):
                    for y in range(g[1] - lim, g[1] + lim + 1):
                        if _walk(m, x, y) and (x, y) not in m.camp and m.cheb_rect(rA, x, y) > 0 and (x, y) not in m.protect:
                            m.put(x, y, WALL)
            if not _connected(m) or not _mc_tanks(m, grp) or not any(
                    (q[0] + dx, q[1] + dy) in m.bfs("A") for q in grp for dx, dy in N8):
                _restore(m, snap)
                continue
        # the pocket: wall the standable tiles farthest from our spawn first, keeping the map connected and the group reachable
        for p in sorted(_mc_stand(m, grp), key=lambda p: -m.cheb_rect(rA, *p)):
            if len(_mc_stand(m, grp)) <= rec["cap"]:
                break
            if p in m.protect or m.dspawn(*p) <= 1:
                continue
            v = m.get(*p)
            m.put(p[0], p[1], WALL)
            dA = m.bfs("A")
            if not _connected(m) or not any((q[0] + dx, q[1] + dy) in dA for q in grp for dx, dy in N8):
                m.put(p[0], p[1], v)
        if len(_mc_stand(m, grp)) > rec["cap"] or _mc_walk(m) < 40:
            _restore(m, snap)
            continue
        for x, y in grp:
            m.prot(x, y)
        # the rest of the gold: gold clusters only, at most gr x the monolith gold (a side)
        others = [(t, k) for t, k in m.groups if k != "monocorner"]
        rng.shuffle(others)
        budget = rec["gr"] * MONO_GOLD * len(grp)
        gold = sum(CLUSTER_GOLD * len(t) for t, _ in others)
        while others and gold > budget:
            t, _ = others.pop()
            gold -= CLUSTER_GOLD * len(t)
            NF.remove_group(m, t)
        for p in [p for p, t in m.camp.items() if t not in (GOLD, MONO)]:
            m.camp.pop(p)
        if not any(t == GOLD for t in m.camp.values()):
            _restore(m, snap)
            continue
        return m
    raise RuntimeError("no room for a corner monolith pocket")


# camp stats, GameRules.md:182-188: (HP, strength, gold, gems)
CAMP_STATS = {WOLF: (1350, 20, 40, 4), ELK: (2400, 60, 90, 15), GOLEM: (5000, 120, 160, 36), GEM: (120, 0, 0, 7), GOLD: (120, 0, 20, 0),
              MONO: (20000, 200, 300, 200)}


def _op_load(att, t):
    """draft.cpp op_load (b1326): base stats 60 dps and 1000 HP a body; attackers die in Str/HP order, all living ones hitting"""
    if len(att) > 48:
        return 99.0
    a = sorted(att, key=lambda hs: -hs[1] / hs[0])
    out, dmg = float(sum(s for _, s in a)), 0.0
    for h, st in a:
        dmg += out * h / (t * 60.0)
        out -= st
    return dmg / (t * 1000.0)


def onepack(camps, dist, t):
    """Port of the bot's ONE_PACK test (draft.cpp one_pack, b1326 donor nova_b1326_opv). camps: {tile: camp type}; dist(tiles) ->
    walk distance from our spawn to the group (UNREACH None); t: team size. Groups = cardinally joined camps. -> (on, why)"""
    left, groups = set(camps), []
    while left:
        st = [left.pop()]
        g = list(st)
        while st:
            c = st.pop()
            for dx, dy in N4:
                n = (c[0] + dx, c[1] + dy)
                if n in left:
                    left.discard(n)
                    st.append(n)
                    g.append(n)
        groups.append(g)
    tot = lock = cheap = nlock = 0
    dl = dc = None
    boss = False
    for g in groups:
        gems = sum(CAMP_STATS[camps[p]][3] for p in g)
        gold = sum(CAMP_STATS[camps[p]][2] for p in g)
        att = [(CAMP_STATS[camps[p]][0], CAMP_STATS[camps[p]][1]) for p in g if CAMP_STATS[camps[p]][1] > 0]
        ld = _op_load(att, t)
        tot += gems
        if ld >= 1.0 and gems > 0:
            nlock += 1
            lock += gems
            dl = dist(g)
            boss = any(camps[p] in (MONO, GOLEM) for p in g)
        elif ld < 0.25:
            cheap += gold
            if gold > 0 and dist(g) is not None:
                dc = dist(g) if dc is None else min(dc, dist(g))
    on = nlock == 1 and not boss and 100 * lock >= 95 * tot and dl is not None and dl >= 30 and cheap >= 400 and dc is not None and dc < dl
    return on, f"locks {nlock} boss {boss} gem share {lock / max(1, tot):.2f} walk {dl} cheap gold {cheap} nearest cheap {dc}"


def _op_map(m):
    dA = m.bfs("A")
    def dist(g):
        ds = [dA[(p[0] + dx, p[1] + dy)] for p in g for dx, dy in N8 if (p[0] + dx, p[1] + dy) in dA]
        return min(ds) if ds else None
    return onepack(m.camp, dist, m.T)


def _m_onepack(rec, seed, rng):
    m = G.generate(rec, seed)
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    for t, k in list(m.groups):  # room for the pack at the centre
        if any(max(abs(p[0] - cx), abs(p[1] - cy)) <= 9 for p in t):
            NF.remove_group(m, t)
    GF.place_hoards(m, rng, 1, rec["hsize"])
    hoard = next(t for t, k in m.groups if k == "hoard")
    hd = min(m.cheb_rect(m.rectA(), *p) for p in hoard)
    if hd < 22:
        raise RuntimeError(f"pack too near the spawns ({hd})")
    S = set(hoard) | {m.mir(*p) for p in hoard}
    for p in sorted(S):
        m.camp[p] = GEM
    for p in sorted(S):  # rim guards: wolves and elks only (a golem or monolith makes it a boss pack, not ONE_PACK)
        if any((p[0] + dx, p[1] + dy) not in S for dx, dy in N4) and rng.random() < rec["rim"]:
            g = ELK if rng.random() < rec["elk"] else WOLF
            m.camp[p] = g
            m.camp[m.mir(*p)] = g
    for t, k in list(m.groups):  # everything else: gold clusters only (camps become clusters, so the cheap gold is >= 400)
        if k != "hoard":
            for p in t:
                if p in m.camp:
                    m.camp[p] = GOLD
                    m.camp[m.mir(*p)] = GOLD
    on, why = _op_map(m)
    if not on:
        raise RuntimeError("not ONE_PACK: " + why)
    return m


def _om_groups(camps):
    left, out = set(camps), []
    while left:
        st = [left.pop()]
        g = list(st)
        while st:
            c = st.pop()
            for dx, dy in N4:
                n = (c[0] + dx, c[1] + dy)
                if n in left:
                    left.discard(n)
                    st.append(n)
                    g.append(n)
        out.append(g)
    return out


def onemono(camps, dist, mir):
    """w_onemono's feature (Econ's OGS class): the monolith group holding the most gems is self-symmetric, holds >= 70% of the
    map's gems and is >= 10 walk from our spawn. camps {tile: type}; dist(tiles) -> walk or None; mir(x, y) -> mirror tile.
    -> (on, why). 00rows: share .80, walk 34; 00anvil: share .78, walk 13 (both pass)."""
    gs = _om_groups(camps)
    gem = lambda g: sum(CAMP_STATS[camps[p]][3] for p in g)
    tot = sum(CAMP_STATS[t][3] for t in camps.values())
    packs = sorted((g for g in gs if any(camps[p] == MONO for p in g)), key=gem, reverse=True)
    if not packs:
        return False, "no monolith group"
    pk = packs[0]
    sym = set(pk) == {mir(*p) for p in pk}
    share, walk = gem(pk) / max(1, tot), dist(pk)
    gold_d = [dist(g) for g in gs if g is not pk and gem(g) == 0 and any(camps[p] == GOLD for p in g)]
    near = min([d for d in gold_d if d is not None] or [None]) if gold_d else None
    on = sym and share >= 0.70 and walk is not None and walk >= 10
    return on, f"monoliths {sum(camps[p] == MONO for p in pk)} sym {sym} gem share {share:.2f} walk {walk} nearest gold {near}"


def _om_map(m):
    dA = m.bfs("A")
    def dist(g):
        ds = [dA[(p[0] + dx, p[1] + dy)] for p in g for dx, dy in N8 if (p[0] + dx, p[1] + dy) in dA]
        return min(ds) if ds else None
    return onemono(m.camp, dist, m.mir)


def _m_onemono(rec, seed, rng):
    m = G.generate(rec, seed)
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    for t, k in list(m.groups):
        if any(max(abs(p[0] - cx), abs(p[1] - cy)) <= 9 for p in t):
            NF.remove_group(m, t)
    GF.place_hoards(m, rng, 1, rec["hsize"])
    hoard = next(t for t, k in m.groups if k == "hoard")
    S = set(hoard) | {m.mir(*p) for p in hoard}
    if min(m.cheb_rect(m.rectA(), *p) for p in S) < 8:
        raise RuntimeError("pack too near the spawns")
    for p in S:
        m.camp[p] = GEM
    own = sorted(p for p in S if m.mir(*p) != p)
    rng.shuffle(own)
    done, used = 0, set()
    for p in own:  # monoliths in mirrored pairs (the pack stays self-symmetric)
        if done >= rec["npair"]:
            break
        if p in used or m.mir(*p) in used:
            continue
        m.camp[p] = MONO
        m.camp[m.mir(*p)] = MONO
        used |= {p, m.mir(*p)}
        done += 1
    if rec["npair"] == 0:  # one monolith on a self-mirror tile of the pack (00anvil); needs an odd board side on the mirror axis
        mid = [p for p in S if m.mir(*p) == p]
        if not mid:
            raise RuntimeError("no self-mirror tile for a single monolith")
        m.camp[rng.choice(mid)] = MONO
        done = 1
    if not done:
        raise RuntimeError("no monolith pair fits the pack")
    others = [t for t, k in m.groups if k != "hoard"]
    for t in others:
        for p in t:
            if p in m.camp:
                m.camp[p] = GOLD
                m.camp[m.mir(*p)] = GOLD
    pack = sum(CAMP_STATS[m.camp[p]][3] for p in S)
    rng.shuffle(others)
    want = pack * (1 - rec["share"]) / rec["share"]  # gems to put back outside the pack
    got = 0
    for t in others[1:]:  # keep at least one gold-only group (others[0])
        if got + 2 * 7 * len(t) > want:
            continue
        for p in t:
            if p in m.camp:
                m.camp[p] = GEM
                m.camp[m.mir(*p)] = GEM
        got += 2 * 7 * len(t)
    on, why = _om_map(m)
    if not on:
        raise RuntimeError("not ONE_MONO: " + why)
    return m


def _line_ok(m, tiles):
    """a line site: every tile in bounds, floor/bush, >= 4 from both spawns, no camp or altar on it or beside it (the mirror copy
    included), and the line and its mirror either the same set or apart by >= 2"""
    own = set(tiles)
    mirr = {m.mir(*p) for p in tiles}
    for p in tiles:
        if not m.inb(*p) or m.get(*p) not in (FLOOR, BUSH, WALL) or m.dspawn(*p) < 4:
            return False
        for dx, dy in N8 + [(0, 0)]:
            q = (p[0] + dx, p[1] + dy)
            if q in m.camp or (m.inb(*q) and m.get(*q) == ALTAR):
                return False
    return mirr == own or min(_cheb(p, q) for p in own for q in mirr) >= 3


def _m_lines(rec, seed, rng):
    m = G.generate(rec, seed)
    want = rec["nline"] + (1 if rec["axis"] else 0)
    made, tries = 0, 0
    while made < want and tries < 400:
        tries += 1
        axis_line = rec["axis"] and made == 0
        horiz = rng.random() < 0.5
        span = m.W if horiz else m.H
        L = rng.randint(15, max(15, min(rec["lmax"], span - 6)))
        if L > span - 4:
            continue
        if axis_line:  # a line that is its own mirror image: on the fixed row / column of sym 0/1, through the centre for sym 2
            fixed = [(x, y) for x in range(m.W) for y in range(m.H) if m.mir(x, y) == (x, y)]
            if m.sym == 2:
                cx, cy = (m.W - 1) // 2, (m.H - 1) // 2
                if (m.W % 2 == 0) or (m.H % 2 == 0):
                    continue
                s0 = (cx - L // 2, cy) if horiz else (cx, cy - L // 2)
                L = L if L % 2 == 1 else L - 1
            elif not fixed:
                continue
            else:
                horiz = (m.sym == 1)  # sym 1 mirrors y: the fixed tiles form a row
                L = min(L, (m.W if horiz else m.H) - 6)
                c = fixed[0][1] if horiz else fixed[0][0]
                s0 = ((m.W - L) // 2, c) if horiz else (c, (m.H - L) // 2)
        else:
            x0 = rng.randint(2, m.W - (L if horiz else 1) - 2)
            y0 = rng.randint(2, m.H - (1 if horiz else L) - 2)
            s0 = (x0, y0)
        tiles = [(s0[0] + k, s0[1]) if horiz else (s0[0], s0[1] + k) for k in range(L)]
        if not _line_ok(m, tiles):
            continue
        s = _snap(m)
        t0 = GOLD
        cells = []
        for p in tiles:
            m.put(*p, FLOOR)
            t = GEM if rec["gemmix"] and rng.random() < 0.3 else t0
            cells.append((p[0], p[1], t))
        if axis_line:
            for x, y, t in cells:
                m.camp[(x, y)] = t
            m.groups.append(([(x, y) for x, y, _ in cells], "line"))
        else:
            G.put_group(m, cells, "line")
        if _connected(m, block_camps=True) and G.access_ok(m) and _altars_walkable(m):
            made += 1
        else:
            _restore(m, s)
    if made < max(2, want - 1):
        raise RuntimeError(f"lines placed {made} of {want}")
    return m


# ---------------------------------------------------------------- 11 Nov: w_longpath, w_crosswires (owner maps long_path, crosswires)
def _spawn_wh(rng, T):
    sw, sh = rng.choice({3: [(3, 3)], 4: [(3, 3), (4, 3)], 5: [(3, 3), (4, 4), (5, 2)]}[T])
    return (sh, sw) if rng.random() < 0.5 else (sw, sh)


def _xform(m, flip, transpose):
    """A copy of m flipped top-bottom and/or transposed (sym 0 -> 1); both commute with the mirror, so the copy stays fair."""
    W, H = m.W, m.H

    def f(x, y):
        if flip:
            y = H - 1 - y
        return (y, x) if transpose else (x, y)
    nW, nH = (H, W) if transpose else (W, H)
    n = G.Map(nW, nH, {0: 1, 1: 0, 2: 2}[m.sym] if transpose else m.sym, m.T)
    for y in range(H):
        for x in range(W):
            a, b = f(x, y)
            n.g[b * nW + a] = m.g[y * W + x]
    n.camp = {f(*p): t for p, t in m.camp.items()}
    n.groups = [([f(*p) for p in t], k) for t, k in m.groups]
    n.altars = [f(*p) for p in m.altars]
    n.protect = {f(*p) for p in m.protect}
    x0, y0, x1, y1 = m.spawn
    a, b = f(x0, y0), f(x1 - 1, y1 - 1)
    n.spawn = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]) + 1, max(a[1], b[1]) + 1)
    return n


def _put_raw(m, tiles, kind):
    """put_group without group_ok's spacing (these families pack camps diagonally on purpose): FLOOR tiles off the spawns,
    no tile next to its own mirror image."""
    for x, y, _ in tiles:
        if not m.inb(x, y) or m.get(x, y) != FLOOR or (x, y) in m.camp or m.dspawn(x, y) < 1:
            return False
        q = m.mir(x, y)
        if q != (x, y) and _cheb((x, y), q) <= 1:
            return False
    G.put_group(m, tiles, kind)
    return True


LP_MIX = {"gold": {GOLD: 6, GEM: 1}, "balanced": {GEM: 3, GOLD: 3, WOLF: 2, ELK: 1}, "gems": {GEM: 4, WOLF: 2, GOLD: 1},
          "heavy": {GOLD: 3, GEM: 2, GOLEM: 1, MONO: 0.4}}


def _m_longpath(rec, seed, rng):
    """One serpentine corridor (cw wide, walls wt thick) filling A's half on a cell grid (boustrophedon by columns, or by rows
    on x-mirror boards), joined to its mirror on the axis; spawn in a corner block with its altar; camps in niches cut into
    the corridor walls (only where the cut joins tiles <= 2*cw+2 apart on the route, so no shortcut) and, when cw >= 2,
    inside the corridor (never closing it). Built in the x-mirror / point-mirror frame, then flipped / transposed."""
    W, H = rec["dims"]
    if rec["sym"] == 1:
        W, H = H, W
    m = G.Map(W, H, 2 if rec["sym"] == 2 else 0, rec["T"])
    m.g[:] = bytes([WALL]) * (W * H)
    cw, wt = rec["cw"], rec["wt"]
    p = cw + wt
    sw, sh = _spawn_wh(rng, m.T)
    sx, sy = rng.randint(0, 2), rng.randint(0, 2)
    m.spawn = (sx, sy, sx + sw, sy + sh)
    bw, bh = sx + sw + rng.randint(2, 3), sy + sh + rng.randint(2, 3)
    for x in range(bw):
        for y in range(bh):
            m.put(x, y, FLOOR)
    xb = W // 2 - 1 if W % 2 == 0 else W // 2  # A-side axis wall column
    x0, y0 = rng.randint(0, 1), rng.randint(0, 1)
    nc = (xb - x0 - cw) // p + 1
    nr = (H - rng.randint(0, 1) - y0 - cw) // p + 1
    if nc < 3 or nr < 3:
        raise RuntimeError(f"grid {nc}x{nr}")
    orient = rec["orient"] if m.sym == 0 else "col"
    # lanes v (columns for 'col', rows for 'row'), positions u along a lane; cells next to the spawn block are skipped
    nv, nu = (nc, nr) if orient == "col" else (nr, nc)
    if orient == "row" and nv % 2 == 0:
        nv -= 1  # the last row must run towards the axis
    ij = (lambda v, u: (v, u)) if orient == "col" else (lambda v, u: (u, v))

    def lim(v):
        for u in range(nu):
            i, j = ij(v, u)
            if not (x0 + i * p <= bw and y0 + j * p <= bh):
                return u
        return nu
    lims = [lim(v) for v in range(nv)] + [0]
    if lims[0] >= nu - 2:
        raise RuntimeError("spawn block fills the first lane")
    jc = max(0, min(nr - 1, round(((H - 1) / 2 - y0 - (cw - 1) / 2) / p)))
    path, start = [], lims[0]
    for v in range(nv):
        fwd = v % 2 == 0
        jit = rng.random() < rec["jit"] and v < nv - 2  # a shallower turn (never into the last lane)
        lo = max(lims[v], lims[v + 1])
        if v == nv - 1:
            end = nu - 1 if orient == "row" else (jc if m.sym == 2 else rng.randint(0, nu - 1))
            end = max(start, end) if fwd else max(lims[v], min(start, end))
        elif fwd:
            end = rng.randint(max(start + 1, nu // 2), nu - 1) if jit and start + 1 <= nu - 1 else nu - 1
        else:
            end = rng.randint(lo, min(start - 1, nu // 2)) if jit and lo <= min(start - 1, nu // 2) else lo
        us = range(start, end + 1) if fwd else range(start, end - 1, -1)
        path += [ij(v, u) for u in us]
        start = end
    if orient == "col":  # spawn block -> first cell (down column 0, or across row 0)
        for s in range(bh, y0 + path[0][1] * p):
            for u in range(cw):
                m.put(x0 + u, s, FLOOR)
    else:
        for s in range(bw, x0 + path[0][0] * p):
            for u in range(cw):
                m.put(s, y0 + u, FLOOR)

    def tiles(c):
        xs, ys = x0 + c[0] * p, y0 + c[1] * p
        return [(xs + a, ys + b) for a in range(cw) for b in range(cw)]
    for k, c in enumerate(path):
        v = BUSH if rng.random() < rec["bushp"] else FLOOR
        for t in tiles(c):
            m.put(*t, v)
        if k:
            a, b = path[k - 1], c
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1, (a, b)
            xa, ya = x0 + min(a[0], b[0]) * p, y0 + min(a[1], b[1]) * p
            for s in range(wt):
                for u in range(cw):
                    m.put(*((xa + cw + s, ya + u) if a[1] == b[1] else (xa + u, ya + cw + s)), FLOOR)
    e = path[-1]
    ex, ey = x0 + e[0] * p, y0 + e[1] * p
    if m.sym == 0:
        rows = [ey + u for u in range(cw)] if rng.random() < 0.5 else [ey + rng.randrange(cw)]
    else:
        yc = min(range(ey, ey + cw), key=lambda r: abs(r - (H - 1) / 2))
        rows = list(range(min(yc, H - 1 - yc), max(yc, H - 1 - yc) + 1))
    for r in rows:
        for xx in range(ex + cw, xb + 1):
            if r in range(ey, ey + cw) or xx == xb:
                m.put(xx, r, FLOOR)
    # altar in the spawn block (2 from the spawn), sometimes a second one in a corridor niche below
    blk = [(x, y) for x in range(bw) for y in range(bh) if m.cheb_rect(m.spawn, x, y) == 2
           and any(m.inb(x + dx, y + dy) and m.get(x + dx, y + dy) == FLOOR and m.cheb_rect(m.spawn, x + dx, y + dy) >= 1 for dx, dy in N8)]
    if not blk:
        raise RuntimeError("no altar tile")
    G.add_altar(m, rng, *rng.choice(blk), double=False)
    dist = m.bfs("A")
    lo_side = lambda q: q[0] < xb and q[1] >= 0  # noqa: E731

    def niche(q, extra=()):
        if not m.inb(*q) or m.get(*q) != WALL or not lo_side(q) or m.dspawn(*q) < 3:
            return False
        ns = [dist[n] for n in ((q[0] + dx, q[1] + dy) for dx, dy in N8) if n in dist and n not in extra]
        return bool(ns) and max(ns) - min(ns) <= 2 * cw + 2
    walls = [(x, y) for x in range(xb) for y in range(H) if m.get(x, y) == WALL and niche((x, y))]
    rng.shuffle(walls)
    if rec["alt2"]:
        for q in walls[:40]:
            if q[0] > x0 and any(m.get(q[0] + dx, q[1] + dy) == FLOOR for dx, dy in N4 if m.inb(q[0] + dx, q[1] + dy)):
                G.add_altar(m, rng, *q, double=False)
                walls.remove(q)
                break
    mix, got = LP_MIX[rec["mix"]], 0
    for q in walls:
        if got >= rec["ng"]:
            break
        if not niche(q):
            continue
        tl = [q]
        d = next(((dx, dy) for dx, dy in N4 if (q[0] - dx, q[1] - dy) in dist), None)
        if d and rng.random() < 0.5:
            q2 = (q[0] + d[0], q[1] + d[1])
            if niche(q2, extra=(q,)) and all((q2[0] + a, q2[1] + b) not in dist or (q2[0] + a, q2[1] + b) == q
                                             for a, b in N8):
                tl.append(q2)
        s = _snap(m)
        for t in tl:
            m.put(*t, FLOOR)
        grp = [(x, y, _pick(rng, mix)) for x, y in tl]
        if G.group_ok(m, grp):
            G.put_group(m, grp, "niche")
            got += 1
        else:
            _restore(m, s)
    if cw >= 2:
        cells = list(path[2:])
        rng.shuffle(cells)
        for c in cells[:rec["nin"] * 3]:
            t = rng.choice(tiles(c))
            grp = [(t[0], t[1], _pick(rng, mix))]
            if m.get(*t) == FLOOR and G.group_ok(m, grp):
                G.put_group(m, grp, "lane")
                if not _connected(m, True):
                    G.drop_group(m)
    if len(m.groups) < 3:
        raise RuntimeError(f"camp groups {len(m.groups)}")
    if rec["flip"] or rec["sym"] == 1:
        m = _xform(m, rec["flip"], rec["sym"] == 1)
    return m


def _ck_longpath(m, f, x):
    s, ch = f["s2s"], x["cheb"]
    if s is None:
        return "spawns not connected"
    if not (s >= 15 * ch or (min(m.W, m.H) >= 70 and s >= 1500)):
        return f"s2s {s} cheb {ch}"
    if x["cblk"] != 1.0:
        return f"camps on the route (cblk {x['cblk']})"
    return None if f["grp"] >= 6 and f["wall"] >= 35 else f"groups {f['grp']} wall {f['wall']}"


CW_MIX = {MONO: 3, GOLEM: 3, ELK: 2, WOLF: 1, GEM: 1, GOLD: 1}


def _m_crosswires(rec, seed, rng):
    """A wall board (hole border on most draws) whose walkable tiles meet only diagonally: the spawn rect is walled in and
    left through ring corners, one diagonal corridor (corner squeezes, waypoints) runs to the mirror axis, altar strips
    along the edges (hole row / floor row / 1-tile camp row / altar row, every tribute tile a camp but the entrance's),
    checkerboard bands of 1-tile camps off the corridor, rooms (bush, gem/gold clusters, 2x2 heavy) linked by a diagonal
    corridor, a floor/hole dash line or nothing (crystal only), and checkerboard hole fields in the walls."""
    W, H = rec["dims"]
    m = G.Map(W, H, rec["sym"], rec["T"])
    m.g[:] = bytes([WALL]) * (W * H)
    bd = HOLE if rec["hborder"] else WALL
    for x in range(W):
        m.put(x, 0, bd)
        m.put(x, H - 1, bd)
    for y in range(H):
        m.put(0, y, bd)
        m.put(W - 1, y, bd)
    sym = m.sym
    cx, cy = (W - 1) / 2, (H - 1) / 2

    def axd(q):
        return abs(q[0] - cx) if sym == 0 else abs(q[1] - cy)

    def inA(q, gap=2):
        return 1 <= q[0] <= W - 2 and 1 <= q[1] <= H - 2 and (q[0] < cx if sym == 0 else q[1] < cy) and axd(q) >= gap
    sw, sh = _spawn_wh(rng, m.T)
    sx = rng.randint(2, 4) if rng.random() < 0.6 or sym == 0 else W - 1 - sw - rng.randint(2, 4)
    sy = rng.randint(2, 4) if rng.random() < 0.6 or sym != 0 else H - 1 - sh - rng.randint(2, 4)
    m.spawn = (sx, sy, sx + sw, sy + sh)
    for x in range(sx, sx + sw):
        for y in range(sy, sy + sh):
            m.put(x, y, FLOOR)
    res = {(x, y) for x in range(sx - 1, sx + sw + 1) for y in range(sy - 1, sy + sh + 1)}  # the spawn ring
    keep = {(x, y) for x in range(sx - 3, sx + sw + 3) for y in range(sy - 3, sy + sh + 3)}  # strips and rooms stay off
    corners = [(sx - 1, sy - 1, -1, -1), (sx + sw, sy - 1, 1, -1), (sx - 1, sy + sh, -1, 1), (sx + sw, sy + sh, 1, 1)]
    corners = [c for c in corners if inA((c[0] + 2 * c[2], c[1] + 2 * c[3]))]
    if not corners:
        raise RuntimeError("no spawn exit")
    rng.shuffle(corners)
    exits = corners[:rec["exits"]]
    camps_mix = dict(CW_MIX)

    # ---- altar strips
    def strip_tiles(edge, a, L):
        def at(i, k):
            return {"top": (a + i, 1 + k), "bot": (a + i, H - 2 - k), "left": (1 + k, a + i), "right": (W - 2 - k, a + i)}[edge]
        return at
    strips, nalt = [], 0
    for _ in range(300):
        if len(strips) >= rec["nstrip"]:
            break
        edge = rng.choice(["top", "bot", "left", "right"])
        na = rec["na"]
        L = 2 * na + 1
        span = W if edge in ("top", "bot") else H
        if span - L - 4 < 4:
            continue
        a = rng.randint(4, span - L - 4)
        at = strip_tiles(edge, a, L)
        box = [at(i, k) for i in range(-1, L + 1) for k in range(0, 5)]
        if not all(inA(q, 1) for q in box) or any(q in res or q in keep for q in box):
            continue
        open_ = rng.random() < rec["openp"]
        ng0, na0 = len(m.groups), len(m.altars)
        for i in range(L):
            if i % 2:
                m.put(*at(i, 0), HOLE)
            if i % 2 == 0 or open_:
                m.put(*at(i, 1), FLOOR)
        m.put(*at(-1, 2), FLOOR)  # entrances at both ends (camp row): each touches an altar diagonally
        m.put(*at(L, 2), FLOOR)
        for i in range(L):
            if i % 2:
                q = at(i, 2)
                m.put(*q, FLOOR)
                _put_raw(m, [(q[0], q[1], _pick(rng, camps_mix))], "strip")
            else:
                G.add_altar(m, rng, *at(i, 3), double=False)
                nalt += 1
        res |= set(box)
        strips.append(dict(ents=[at(-2, 1), at(-2, 3), at(-2, 2), at(L + 1, 1), at(L + 1, 3), at(L + 1, 2)], box=box, groups=m.groups[ng0:], altars=m.altars[na0:], na=na + 1))
    if nalt < 5:
        raise RuntimeError(f"altars {nalt} a side")

    # ---- rooms
    rooms = []
    for _ in range(300):
        if len(rooms) >= rec["npocket"]:
            break
        kind = rng.choice(["bush", "cluster", "cluster", "heavy"] if rooms else ["cluster", "heavy"])  # the first room (dash/crystal) holds camps
        pw, ph = {"bush": rng.choice([(5, 3), (3, 5), (3, 3)]), "cluster": rng.choice([(3, rng.randint(3, 8)), (rng.randint(3, 6), 3), (5, 3)]),
                  "heavy": (2, 2)}[kind]
        if rng.random() < 0.5:
            pw, ph = ph, pw
        x, y = rng.randint(2, W - 3 - pw), rng.randint(2, H - 3 - ph)
        box = [(x + i, y + j) for i in range(-1, pw + 1) for j in range(-1, ph + 1)]
        if not all(inA(q, 2) for q in box) or any(q in res or q in keep for q in box) or m.dspawn(x, y) < 4:
            continue
        inner = [(x + i, y + j) for i in range(pw) for j in range(ph)]
        for q in inner:
            m.put(*q, BUSH if kind == "bush" else FLOOR)
        if kind == "bush":
            mid = [q for q in inner if (q[0] - x == pw // 2) if pw >= 3] or [q for q in inner if q[1] - y == ph // 2]
            for q in mid:
                if rng.random() < 0.7:
                    m.put(*q, HOLE)
            g = None
        else:
            t = rng.choice([GEM, GOLD]) if kind == "cluster" else rng.choice([MONO, GOLEM, GOLEM])
            tl = [(q[0], q[1], t) for q in inner]
            g = tl if _put_raw(m, tl, kind) else None
            if g is None:
                for q in inner:
                    m.put(*q, WALL)
                continue
        res |= set(box)
        rooms.append(dict(inner=inner, corner=[(x - 1, y - 1), (x + pw, y - 1), (x - 1, y + ph), (x + pw, y + ph), (x - 1, y), (x + pw, y + ph - 1)],
                          link=rng.choice(["dash", "cry"]) if not rooms else rng.choices(["walk", "dash", "cry"], rec["linkw"])[0], tiles=[q for q in inner] if g else None))

    # ---- main diagonal corridor: spawn exit -> waypoints -> a tile next to its own mirror image
    def sgn(v):
        return (v > 0) - (v < 0)

    DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def walk(a, goals, bad, gap=2):
        """shortest run of diagonal steps (corner squeezes) from a to any tile of goals, avoiding bad tiles and staying in A's
        half; ties broken at random. -> tiles after a, ending on the goal, or None."""
        goals = set(goals)
        prev, dq = {a: None}, [a]
        for c in dq:
            dirs = DIAG[:]
            rng.shuffle(dirs)
            for i, j in dirs:
                n = (c[0] + i, c[1] + j)
                if n in prev:
                    continue
                if n in goals:
                    out = [n]
                    while c != a:
                        out.append(c)
                        c = prev[c]
                    return out[::-1]
                if bad(n) or not inA(n, gap):
                    continue
                prev[n] = c
                dq.append(n)
        return None

    if sym == 0:
        tx = [int(cx) if W % 2 else W // 2 - 1]
        targets = [(tx[0], y) for y in range(3, H - 3)]
    elif sym == 1:
        ty = int(cy) if H % 2 else H // 2 - 1
        targets = [(x, ty) for x in range(3, W - 3)]
    else:  # point mirror: a tile near the centre whose mirror image is next to it or 2 away across the (self-mirror) centre
        targets = [(x, y) for x in range(int(cx) - 2, int(cx) + 3) for y in range(int(cy) - 2, int(cy) + 2)
                   if (y < cy or (y == cy and x <= cx)) and (_cheb((x, y), m.mir(x, y)) <= 1 or
                       (_cheb((x, y), m.mir(x, y)) == 2 and (x - m.mir(x, y)[0]) % 2 == 0 and (y - m.mir(x, y)[1]) % 2 == 0))]
    main = set()
    for ex in exits:
        E = (ex[0], ex[1])
        E2 = (E[0] + ex[2], E[1] + ex[3])  # first step straight out of the ring corner
        if not inA(E2, 2) or E2 in res:
            continue
        bad = lambda q: q in res and q != E  # noqa: E731
        route = None
        for tr in range(60):
            par = [t for t in targets if (t[0] + t[1]) % 2 == (E[0] + E[1]) % 2 and not bad(t)] or targets
            goal = rng.choice(par)
            ways = []
            for _w in range(rec["nway"] if tr < 40 else 0):
                w = (rng.randint(2, W - 3), rng.randint(2, H - 3))
                if (w[0] + w[1]) % 2 != (E[0] + E[1]) % 2:
                    w = (w[0] + 1, w[1])
                if inA(w, 3) and not bad(w):
                    ways.append(w)
            pts, seg, ok = [E2] + ways, [E, E2], True
            for b in ways:
                s = walk(seg[-1], [b], bad)
                if s is None:
                    ok = False
                    break
                seg += s
            if ok:
                s = walk(seg[-1], par, bad, gap=1)
                if s is not None:
                    route = seg + s
                    break
        if route is None:
            continue
        t = route[-1]
        mt = m.mir(*t)
        if _cheb(t, mt) == 2:  # join through the centre tile
            route.append(((t[0] + mt[0]) // 2, (t[1] + mt[1]) // 2))
        for q in route:
            m.put(*q, BUSH if rng.random() < rec["bushp"] and m.dspawn(*q) > 1 else FLOOR)
        main |= set(route)
        res |= set(route)
    if not main:
        raise RuntimeError("no diagonal route")
    # ---- branches to strips and rooms
    mainl = sorted(main)

    def branch(start, dash):
        tg = [q for q in mainl if (q[0] + q[1]) % 2 == (start[0] + start[1]) % 2]
        bad = lambda q: q in res or m.get(*q) not in (WALL, HOLE)  # noqa: E731
        s = walk(start, tg, bad)
        if s is None:
            return False
        seq = [start] + s[:-1]
        for i, q in enumerate(reversed(seq)):
            m.put(*q, HOLE if dash and i % 2 == 0 else FLOOR)
        res.update(seq)
        return True
    for st in strips:  # the last entrance: one orthogonal step, for the other parity
        if not any(inA(e, 2) and e not in res and branch(e, False) for e in st["ents"]):
            for t, _ in st["groups"]:
                NF.remove_group(m, t)
            m.altars = [a for a in m.altars if a not in st["altars"]]
            for q in st["box"]:
                m.put(*q, WALL)
            nalt -= st["na"]
    if nalt < 5:
        raise RuntimeError(f"linked altars {nalt} a side")
    for r in rooms:
        if r["link"] == "cry":
            continue
        cs = [c for c in r["corner"] if inA(c, 2)]
        rng.shuffle(cs)
        if not any(branch(c, r["link"] == "dash") for c in cs[:3]):
            r["link"] = "cry"
    # ---- checkerboard bands of 1-tile camps off the corridor
    stair = 0
    for _ in range(600):
        if stair >= rec["nstair"]:
            break
        P = rng.choice(mainl)
        d = rng.choice([(1, 1), (1, -1), (-1, 1), (-1, -1)])
        Ls = rng.randint(4, 10)
        band = [(P[0] + k * d[0], P[1] + k * d[1]) for k in range(1, Ls + 1)]
        band += [(P[0] + k * d[0] + d[0], P[1] + k * d[1] - d[1]) for k in range(1, Ls)]
        bs = set(band)
        if any(not inA(q, 2) or q in res or m.get(*q) != WALL or m.dspawn(*q) < 3 for q in band):
            continue
        if any(m.inb(q[0] + a, q[1] + b) and (q[0] + a, q[1] + b) not in bs and not (_cheb((q[0] + a, q[1] + b), P) <= 2 and (q[0] + a, q[1] + b) in main)
               and m.get(q[0] + a, q[1] + b) in (FLOOR, BUSH, HOLE) for q in band for a, b in N8):
            continue
        for q in band:
            m.put(*q, FLOOR)
        mix = rng.choice([{GOLD: 3, GEM: 2, WOLF: 1}, CW_MIX, {GEM: 1, GOLD: 1}])
        for q in band:
            _put_raw(m, [(q[0], q[1], _pick(rng, mix))], "stair")
        res |= {(q[0] + a, q[1] + b) for q in band for a, b in N8} | bs
        stair += 1
    # ---- checkerboard hole fields in the walls (never next to the spawn rect)
    want, made = rec["holef"] * W * H, sum(1 for v in m.g if v == HOLE)
    for _ in range(200):
        if made >= want:
            break
        fw, fh = rng.randint(3, 10), rng.randint(3, 10)
        x, y = rng.randint(1, W - 1 - fw), rng.randint(1, H - 1 - fh)
        par = rng.randint(0, 1)
        for i in range(fw):
            for j in range(fh):
                q = (x + i, y + j)
                if inA(q, 1) and (q[0] + q[1]) % 2 == par and m.get(*q) == WALL and m.cheb_rect(m.spawn, *q) > 1 and q not in res:
                    m.put(*q, HOLE)
                    made += 2
    # ---- rooms nobody can reach even with a crystal lose their camps (walled up)
    reach = G.team_reach(G.decode_like(m), crystal=True)
    for r in rooms:
        if r["tiles"] and not any(q in reach for q in r["inner"]):
            grp = next((t for t, _ in m.groups if t and t[0] == r["inner"][0]), None)
            if grp is not None:
                NF.remove_group(m, grp)
            for q in r["inner"]:
                m.put(*q, WALL)
    return m


def _ck_crosswires(m, f, x):
    seen, sizes = set(), []
    for p in m.camp:
        if p in seen:
            continue
        st, n = [p], 0
        seen.add(p)
        while st:
            c = st.pop()
            n += 1
            for dx, dy in N4:
                q = (c[0] + dx, c[1] + dy)
                if q in m.camp and q not in seen:
                    seen.add(q)
                    st.append(q)
        sizes.append(n)
    alt = sum(1 for v in m.g if v == ALTAR)
    one = sum(1 for s in sizes if s == 1)
    # orthogonal-only walking (camps passable): the spawns must NOT meet, so every route uses corner squeezes
    land = lambda q: m.inb(*q) and m.get(*q) in (FLOOR, BUSH)  # noqa: E731
    A, B = m.rectA(), m.rectB()
    st = [(a, b) for a in range(A[0], A[2]) for b in range(A[1], A[3])]
    sn = set(st)
    n4 = False
    while st and not n4:
        c = st.pop()
        for dx, dy in N4:
            q = (c[0] + dx, c[1] + dy)
            if q in sn or not land(q):
                continue
            if m.cheb_rect(B, *q) == 0:
                n4 = True
                break
            sn.add(q)
            st.append(q)
    if f["wall"] + f["hole"] < 60:
        return f"wall+hole {f['wall'] + f['hole']}"
    if len(sizes) < 30 or one < 0.6 * len(sizes):
        return f"groups {len(sizes)} one-tile {one}"
    if alt < 10:
        return f"altars {alt}"
    if n4:
        return "spawns meet orthogonally"
    return None if f["dash"] + f["cry"] > 0 else "no dash/crystal-only gems"


def _v_guardaltar(m, rec):
    ok, info = G.validate_gate(m, dict(rec, kind="adj_gate"))
    if ok:
        why = _ck_guardaltar(m, info, {})
        if why:
            return False, why
    return ok, info


# ---------------------------------------------------------------- 11 Nov: w_manygrp (RC X306, ladder 04gem-caverns / 04sanctum / 04gem-rush)
MG_MIX = {"gemscatter": {"gem1": 10, "gold1": 1, "wolf": 1},  # 04gem-caverns, 04gem-rush: every group one gem cluster
          "singles": {"gem1": 4, "gold1": 3, "wolf": 3, "elk": 1},
          "small": {"wolf_pack": 2, "wolf_clusters": 3, "gold_row": 3, "gem_patch": 3, "elk_guard": 1, "gold_guard": 1,  # 04sanctum: 2-5 tile wolf/gold/gem groups
                    "elk_pair": 0.5, "gem1": 2, "gold1": 2, "wolf": 2, "elk": 1},
          "blend": {"gem1": 5, "gold1": 3, "wolf": 3, "elk": 1, "gem_patch": 2, "gold_row": 2, "wolf_clusters": 2, "wolf_pack": 1,
                    "elk_guard": 0.5, "golem": 0.3},
          "wolfswarm": {"wolf": 30, "gem1": 2, "gold1": 1.5, "elk": 1.5},  # 11 Nov w_hms: b1789's hand-built hms maps, 75-96% lone wolves
          "swarmmix": {"wolf": 20, "gem1": 4, "gold1": 3, "elk": 2}}
MG_CAMPS = 240  # u8 camp count (genweird rejects > 255)


def _m_manygrp(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    Z = G.zone_candidates(m)
    wts = MG_MIX[rec["mgmix"]]
    want, placed, fails = rec["ngs"], 0, 0
    strict = rec.get("checks", 1) >= 2
    cap = rec.get("mgcap", MG_CAMPS)  # both halves; spec_of's u8 counts one half (w_hms: 490 -> <= 245 a half)
    while placed < want and fails < 60 and len(m.camp) < cap:
        name = _pick(rng, wts)
        ok = False
        for _ in range(40):
            zone = rng.choices(["home", "mid", "center"], rec["zw"])[0]
            if not Z[zone]:
                continue
            ax, ay = rng.choice(Z[zone])
            tiles = [(ax + dx, ay + dy, t) for dx, dy, t in G.tpl(name, rng)]
            if not G.group_ok(m, tiles) or len(m.camp) + 2 * len(tiles) > cap:
                continue
            G.put_group(m, tiles, "mg_" + name)
            if G.access_ok(m, True, strict):
                ok = True
                break
            G.drop_group(m)
        if ok:
            placed += 1
        else:
            fails += 1
    if placed < 33:
        raise RuntimeError(f"only {placed} groups a side fit")
    return m


# ---------------------------------------------------------------- 11 Nov: w_goldrace1 (Econ spec_grc_1111: the grc1 gold-race class)
GR_GOLD = {WOLF: 40, ELK: 90, GEM: 0, GOLD: 20, MONO: 300, GOLEM: 160}  # mapfeat.GOLD / GEMS (camp tile values)
GR_GEMS = {WOLF: 4, ELK: 15, GEM: 7, GOLD: 0, MONO: 200, GOLEM: 36}


def gr_share(camps):
    """gold_share = G / (G + 10 M) over every camp tile (mapclass.d/gold_share.py)."""
    g = sum(GR_GOLD[t] for t in camps.values())
    return g / max(1, g + 10 * sum(GR_GEMS[t] for t in camps.values()))


def gr_s2s(m):
    """mapclass _s2s: Chebyshev distance between the spawn-rect centres (A's centre, rounded, mirrored)."""
    x0, y0, x1, y1 = m.spawn
    ax, ay = (x0 + x1 - 1) / 2.0, (y0 + y1 - 1) / 2.0
    bx, by = m.mir(round(ax), round(ay))
    return max(abs(ax - bx), abs(ay - by))


def _gr_spawn(lo, hi):
    """genmaps.place_spawn for w_goldrace1: a random A rect whose mapclass s2s is in [lo, hi] (and a free tile between the rects)."""
    def place(m, rng, mode, sw, sh):
        cand = []
        for x0 in range(m.W - sw + 1):
            for y0 in range(m.H - sh + 1):
                m.spawn = (x0, y0, x0 + sw, y0 + sh)
                if lo <= gr_s2s(m) <= hi:
                    cand.append(m.spawn)
        rng.shuffle(cand)
        for r in cand:
            m.spawn = r
            rb = m.rectB()
            if min(m.cheb_rect(rb, x, y) for x in range(r[0], r[2]) for y in range(r[1], r[3])) >= 2:
                return r
        raise RuntimeError(f"no spawn rect at s2s {lo}-{hi}")
    return place


def _gr_tpl(name, rng):
    if name == "gold5":
        return [(x, y, GOLD) for x, y in G.blob(rng, 5)]
    if name == "gold1":
        return [(0, 0, GOLD)]
    dx, dy = rng.choice(N4)
    return [(0, 0, WOLF), (dx, dy, GEM)]  # wolfgem


def _m_goldrace1(rec, seed, rng):
    place0 = G.place_spawn
    G.place_spawn = _gr_spawn(*rec["s2s"])
    try:
        m = G.generate(rec, seed)
    finally:
        G.place_spawn = place0
    NF.drop_all_groups(m)
    for i, v in enumerate(m.g):  # every altar the generator placed goes; one goes back on the centre tile
        if v == ALTAR:
            m.g[i] = FLOOR
    m.altars = []
    ax, ay = (m.W - 1) // 2, (m.H - 1) // 2
    if m.mir(ax, ay) != (ax, ay):
        raise RuntimeError("centre tile not self-mirror")
    box = [(ax + dx, ay + dy) for dx in range(-2, 3) for dy in range(-2, 3)]
    if any(p in m.protect or m.dspawn(*p) < 3 for p in box):
        raise RuntimeError("centre box protected or near a spawn")
    for p in box:
        m.put(*p, FLOOR)
    G.repair(m, rng, True)
    m.put(ax, ay, ALTAR)
    m.altars = [(ax, ay)]
    strict = rec.get("checks", 1) >= 2
    if not G.access_ok(m, True, strict):
        raise RuntimeError("centre altar not reachable")
    Z = G.zone_candidates(m)
    want, placed, fails = rec["ngs"], 0, 0
    lo, hi = 0.41, 0.54
    while fails < 60 and (placed < want or (placed < want + 6 and not lo <= gr_share(m.camp) <= hi)):
        s = gr_share(m.camp) if m.camp else 1.0
        if rng.random() < rec["noise"]:
            name = rng.choice(["gold5", "gold1", "wolfgem"])
        elif s < rec["gs"]:
            name = "gold5" if rng.random() < rec["p5"] else "gold1"
        else:
            name = "wolfgem"
        ok = False
        for _ in range(40):
            zone = rng.choices(["home", "mid", "center"], rec["zw"])[0]
            if not Z[zone]:
                continue
            bx, by = rng.choice(Z[zone])
            tiles = [(bx + dx, by + dy, t) for dx, dy, t in _gr_tpl(name, rng)]
            if not G.group_ok(m, tiles):
                continue
            G.put_group(m, tiles, "gr_" + name)
            if G.access_ok(m, True, strict):
                ok = True
                break
            G.drop_group(m)
        if ok:
            placed += 1
        else:
            fails += 1
    if placed < 14:
        raise RuntimeError(f"only {placed} groups a side fit")
    return m


# ---------------------------------------------------------------- 11 Nov: w_altargems1 (Econ spec_als_1111: the als1 class)
AG_R, AG_FAR, AG_WALK = 6, 8, 25


def ag_share(m):
    """mapclass.d/als1.py als_share on the design: gems of 4-connected camp groups with a tile within 6 of an altar / all gems."""
    alts = [(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR]
    seen, tot, near = set(), 0, 0
    for c in m.camp:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            p = st.pop()
            comp.append(p)
            for dx, dy in N4:
                q = (p[0] + dx, p[1] + dy)
                if q in m.camp and q not in seen:
                    seen.add(q)
                    st.append(q)
        g = sum(GR_GEMS[m.camp[p]] for p in comp)
        tot += g
        if any(_cheb(p, a) <= AG_R for p in comp for a in alts):
            near += g
    return near / tot if tot else 0.0


def ag_walk(m, a):
    """8-way walk tiles (walls/holes block; mapfeat-style) from each spawn rect to a tile next to altar a, + 1 (the step onto it)."""
    out = []
    for team in ("A", "B"):
        d = m.bfs(team)
        out.append(min((d[(a[0] + dx, a[1] + dy)] for dx, dy in N8 if (a[0] + dx, a[1] + dy) in d), default=None))
    return [None if v is None else v + 1 for v in out]


def _ag_tpl(name, rng):
    if name == "near":  # 2-3 gem clusters + 1 wolf: 18 or 25 gems
        c = G.blob(rng, rng.randint(3, 4))
        return [c[0] + (WOLF,)] + [p + (GEM,) for p in c[1:]]
    if name == "elk_gold":
        c = G.blob(rng, rng.randint(2, 5))
        return [c[0] + (ELK,)] + [p + (GOLD,) for p in c[1:]]
    if name == "gold_patch":
        return [(x, y, GOLD) for x, y in G.blob(rng, rng.randint(3, 6))]
    return G.tpl(name, rng)  # elk, elk_pair, gold_row


AG_FARMIX = {"elk": 2, "elk_pair": 2, "elk_gold": 3, "gold_row": 1.5, "gold_patch": 1}


def _m_altargems1(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    for i, v in enumerate(m.g):
        if v == ALTAR:
            m.g[i] = FLOOR
    m.altars = []
    dA = m.bfs("A")
    axis = [p for p in dA if m.mir(*p) == p and m.get(*p) == FLOOR and m.dspawn(*p) >= 3
            and all(m.inb(p[0] + dx, p[1] + dy) for dx in (-3, 3) for dy in (-3, 3))]
    rng.shuffle(axis)
    alt = None
    for p in axis[:40]:
        box = [(p[0] + dx, p[1] + dy) for dx in range(-2, 3) for dy in range(-2, 3)]
        if any(q in m.protect or m.dspawn(*q) < 3 for q in box):
            continue
        s = _snap(m)
        for q in box:
            m.put(*q, FLOOR)
        G.repair(m, rng, True)
        m.put(*p, ALTAR)
        m.altars = [p]
        w = ag_walk(m, p)
        if None not in w and min(w) >= AG_WALK and G.access_ok(m, True, True):
            alt = p
            break
        _restore(m, s)
    if alt is None:
        raise RuntimeError("no axis altar >= 25 walk from the spawns")
    Z = G.zone_candidates(m)
    near_c = sorted(p for p in m.bfs("A") if m.get(*p) == FLOOR and _cheb(p, alt) <= AG_R - 2 and m.dspawn(*p) >= 3)
    far_c = {k: [p for p in Z[k] if _cheb(p, alt) > AG_FAR + 3] for k in Z}
    want, placed, fails, nn = rec["ngs"], 0, 0, 0
    lo, hi = 0.26, 0.39
    while fails < 60 and (placed < want or (placed < want + 8 and not lo <= ag_share(m) <= hi)):
        s = ag_share(m) if m.camp else 1.0
        near = (rng.random() < 0.5) if rng.random() < rec["noise"] else s < rec["ash"]
        name = "near" if near else _pick(rng, AG_FARMIX)
        ok = False
        for _ in range(40):
            if near:
                if not near_c:
                    break
                bx, by = rng.choice(near_c)
            else:
                zone = rng.choices(["home", "mid", "center"], rec["zw"])[0]
                if not far_c[zone]:
                    continue
                bx, by = rng.choice(far_c[zone])
            tiles = [(bx + dx, by + dy, t) for dx, dy, t in _ag_tpl(name, rng)]
            if near and not any(_cheb((tx, ty), alt) <= AG_R for tx, ty, _ in tiles):
                continue
            if not near and any(_cheb((tx, ty), alt) <= AG_FAR or _cheb(m.mir(tx, ty), alt) <= AG_FAR for tx, ty, _ in tiles):
                continue
            if not G.group_ok(m, tiles):
                continue
            G.put_group(m, tiles, "ag_" + name)
            if G.access_ok(m, True, True):
                ok = True
                break
            G.drop_group(m)
        if ok:
            placed += 1
            nn += near
        else:
            fails += 1
    if placed < 8 or not nn:
        raise RuntimeError(f"only {placed} groups a side fit ({nn} altar-side)")
    return m


def _ck_altargems1(m, f, x):
    alts = [(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR]
    why = []
    if len(alts) != 1:
        return f"altar tiles {len(alts)}"
    s, w = ag_share(m), ag_walk(m, alts[0])
    if not 0.25 <= s <= 0.40:
        why.append(f"als_share {s:.3f}")
    if None in w or min(w) < AG_WALK:
        why.append(f"altar walk {w}")
    bad = {t for t in m.camp.values() if t in (GOLEM, MONO)}
    if bad:
        why.append(f"golem/monolith {sorted(bad)}")
    if f["none"] > 0:
        why.append(f"unreachable gems {f['none']}")
    return "; ".join(why) or None


NI_HALF = 4  # band = tiles whose distance to the mirror axis is <= NI_HALF: 8-9 tiles of WALL (rules: walls block sight and
# dashes; a crystal hops 3; a ward goes <= 2 away; sight 8), so no body can see, reach or ward the other half


def ni_band(m, x, y):
    if m.sym == 0:
        return abs(x - (m.W - 1) / 2) <= NI_HALF
    if m.sym == 1:
        return abs(y - (m.H - 1) / 2) <= NI_HALF
    return abs(y - (m.H - 1) / 2) <= NI_HALF  # point mirror: the top half maps onto the bottom half


def _m_nointer(rec, seed, rng):
    m = G.generate(rec, seed)
    for t in [t for t, _ in m.groups if any(ni_band(m, x, y) or ni_band(m, *m.mir(x, y)) for x, y in t)]:
        NF.remove_group(m, t)
    m.altars = [a for a in m.altars if not ni_band(m, *a)]
    for y in range(m.H):
        for x in range(m.W):
            if ni_band(m, x, y):
                m.camp.pop((x, y), None)
                m.put(x, y, WALL)
                m.prot(x, y)
    if not m.altars:
        raise RuntimeError("no altar off the band")
    if not G.access_ok(m, False, True):
        raise RuntimeError("own half not reachable")
    return m


def _v_nointer(m, rec):
    """genweird.make's validate: the 'split' rules (halves never meet by walk, dash or crystal; a walkable altar; >= 40 gems)."""
    return G.validate(m, dict(rec, kind="split", checks=2))


def _ck_nointer(m, f):
    bad = [(x, y) for y in range(m.H) for x in range(m.W) if ni_band(m, x, y) and m.get(x, y) != WALL]
    if bad:
        return f"band not wall at {bad[0]}"
    if f["s2s"] is not None:
        return "spawns connected"
    if not (40 <= min(m.W, m.H) and max(m.W, m.H) <= 80):
        return f"board {m.W}x{m.H}"
    heavy = {t for t in m.camp.values() if t in (ELK, GOLEM, MONO)}
    if not heavy:
        return "no heavy camps"
    return None


def _m_jackpot(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.drop_all_groups(m)
    cx, cy = (m.W - 1) // 2, (m.H - 1) // 2
    if m.mir(cx, cy) != (cx, cy):
        raise RuntimeError("centre tile not self-mirror")
    box = [(cx + dx, cy + dy) for dx in range(-4, 5) for dy in range(-4, 5)]
    if any(m.dspawn(*q) < 3 for q in box) or any(m.get(*q) == ALTAR for q in box):
        raise RuntimeError("centre box near a spawn or an altar")
    for q in box:
        m.put(*q, FLOOR)
    G.repair(m, rng, True)
    heavy = rec.get("heavy")
    if heavy == "elk":  # w_elkctr: a small gem diamond with nelk elk on its radius-2 ring (no golem, no monolith)
        tiles = [(cx + dx, cy + dy, GEM) for dx in range(-1, 2) for dy in range(-1, 2) if abs(dx) + abs(dy) <= 1]
        ring = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if abs(dx) + abs(dy) == 2]
        rng.shuffle(ring)
        tiles += [(cx + dx, cy + dy, ELK) for dx, dy in ring[: rec["nelk"]]]
    elif heavy == "gems":  # w_keystone: gem clusters only (no monolith, no elk): a Strength-0 keystone
        tiles = [(cx + dx, cy + dy, GEM) for dx in range(-2, 3) for dy in range(-2, 3) if abs(dx) + abs(dy) <= 2]
    elif heavy:  # w_jackpot2: the heavy pair sits on the two tiles beside the centre (a mirror pair, or two self-mirror tiles)
        pair = [(cx - 1, cy), (cx + 1, cy)] if m.sym != 0 else [(cx, cy - 1), (cx, cy + 1)]
        tiles = [(cx, cy, GEM)] + [(x, y, MONO) for x, y in pair] if heavy == "mono2" else [(cx, cy, MONO)] + [(x, y, GOLEM) for x, y in pair]
        tiles += [(cx + dx, cy + dy, GEM) for dx in range(-2, 3) for dy in range(-2, 3)
                  if 0 < abs(dx) + abs(dy) <= 2 and (cx + dx, cy + dy) not in pair]
    else:
        tiles = [(cx, cy, MONO)] + [(cx + dx, cy + dy, GEM) for dx in range(-2, 3) for dy in range(-2, 3) if 0 < abs(dx) + abs(dy) <= 2]
    tips = [(3, 0), (-3, 0), (0, 3), (0, -3)][: rec["elk"]]
    tiles += [(cx + dx, cy + dy, ELK) for dx, dy in tips]
    r3 = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4) if abs(dx) + abs(dy) == 3 and (dx, dy) not in tips]
    rng.shuffle(r3)  # a varied centre: 0-12 more gem tiles on the radius-3 diamond (each touches the radius-2 ring)
    tiles += [(cx + dx, cy + dy, GEM) for dx, dy in r3[: rec.get("ring3", 0)]]
    G.put_group(m, tiles, "jp_centre")
    strict = rec.get("checks", 1) >= 2
    if not G.access_ok(m, True, strict):
        raise RuntimeError("centre group blocks access")
    Z = G.zone_candidates(m)
    want = [("wolf", rec["nwolf"]), ("gold5", rec["ngold"])]
    for name, k in want:
        placed, fails = 0, 0
        while placed < k and fails < 50:
            ok = False
            for _ in range(40):
                zone = rng.choices(["home", "mid", "center"], rec["zw"])[0]
                if not Z[zone]:
                    continue
                bx, by = rng.choice(Z[zone])
                tt = [(bx, by, WOLF)] if name == "wolf" else [(bx + dx, by + dy, GOLD) for dx, dy in G.blob(rng, 5)]
                if not G.group_ok(m, tt):
                    continue
                G.put_group(m, tt, "jp_" + name)
                if G.access_ok(m, True, strict):
                    ok = True
                    break
                G.drop_group(m)
            placed, fails = placed + ok, fails + (not ok)
        if placed < max(2, k - 2):
            raise RuntimeError(f"only {placed} {name} groups fit")
    return m


def _ck_jackpot(m, f):
    """design-side JACKPOT check (mapclass.d/jackpot.py decides on the built map): the centre group holds >= 300 gems and > half of all"""
    cen = sum(G.GEMS[t] for (x, y), t in m.camp.items() if max(abs(x - (m.W - 1) // 2), abs(y - (m.H - 1) // 2)) <= 3)
    tot = sum(G.GEMS[t] for t in m.camp.values())
    if cen < 300 or cen < 0.5 * tot:
        return f"centre {cen} of {tot} gems"
    return None


def col_span(camp):
    """(span, tiles) of the largest 4-connected camp group: span = max(dx, dy) of its bounding box (mapclass rspan / gtiles)."""
    seen, best = set(), (0, 0)
    for c in camp:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camp and q not in seen:
                    seen.add(q)
                    st.append(q)
        xs, ys = [p[0] for p in comp], [p[1] for p in comp]
        best = max(best, (max(max(xs) - min(xs), max(ys) - min(ys)), len(comp)))
    return best


def _m_column(rec, seed, rng):
    """w_goldcol / w_gemcol: an ordinary design, then one straight 1xN column of rec['colkind'] camps (one group), flanked as asked."""
    m = G.generate(rec, seed)
    N, kind = rec["colN"], rec["colkind"]
    strict = rec.get("checks", 1) >= 2
    snap = _snap(m)
    for _ in range(40):
        _restore(m, snap)
        vert = rng.random() < 0.5
        if rec["colplace"] == "axis" and m.sym in (0, 1):
            vert = m.sym == 0
            ax = (m.W - 1) // 2 if vert else (m.H - 1) // 2
            L = m.H if vert else m.W
            if L - 4 < N:
                continue
            s0 = rng.randint(2, L - 2 - N)
            tiles = [(ax, s0 + i) if vert else (s0 + i, ax) for i in range(N)]
        else:
            L = m.H if vert else m.W
            if L - 4 < N:
                continue
            s0 = rng.randint(2, L - 2 - N)
            o = rng.randint(3, (m.W if vert else m.H) - 4)
            tiles = [(o, s0 + i) if vert else (s0 + i, o) for i in range(N)]
            if any(m.mir(*q) in tiles for q in tiles) or any(abs(m.mir(*q)[0 if vert else 1] - (o)) <= 2 for q in tiles[:1]):
                continue  # one column a side, never touching its mirror copy
        if any(m.dspawn(*q) < 3 or m.get(*q) == ALTAR for q in tiles):
            continue
        near = {(x + dx, y + dy) for x, y in tiles for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        for t in [t for t, _ in m.groups if any(q in near or m.mir(*q) in near for q in t)]:
            NF.remove_group(m, t)
        for q in tiles:
            m.put(*q, FLOOR)
        if rec["colflank"] != "none":
            fl = WALL if rec["colflank"] == "wall" else BUSH
            for x, y in tiles:
                for q in ((x + 1, y), (x - 1, y)) if vert else ((x, y + 1), (x, y - 1)):
                    if m.inb(*q) and q not in tiles and rng.random() < rec["colflankp"] and m.dspawn(*q) >= 3 and m.get(*q) != ALTAR:
                        m.put(*q, fl)
        G.put_group(m, [(x, y, kind) for x, y in tiles], "col")
        if G.access_ok(m, True, strict):
            return m
    raise RuntimeError("no column placement kept access")


def _ck_column(m, f):
    span, n = col_span(m.camp)
    return None if span >= 20 and n >= 20 else f"largest group span {span}, tiles {n}"


HP_T = {WOLF: 1350, ELK: 2400, GEM: 120, GOLD: 120, MONO: 20000, GOLEM: 5000}


def _ck_jackpot2(m):
    """w_jackpot2: the centre group's camp HP >= 40,000 (two monoliths; 00rows 41,200)"""
    cx, cy = (m.W - 1) // 2, (m.H - 1) // 2
    hp = sum(HP_T[t] for (x, y), t in m.camp.items() if max(abs(x - cx), abs(y - cy)) <= 3)
    return None if hp >= 40000 else f"centre HP {hp}"


def _ck_goldring1(m, f):
    """spec_bly_1111 GPK class on the built map (mapclass naltars / gold_share / ngroups / heavy_ge2 rules, no heavy camps at all)."""
    alts = [(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR]
    gs = gr_share(m.camp)
    heavy = {t for t in m.camp.values() if t in (ELK, GOLEM, MONO)}
    why = ([f"altar tiles {len(alts)}"] if len(alts) != 1 else []) + ([f"gold_share {gs:.3f}"] if not 0.37 <= gs <= 0.56 else []) \
        + ([f"heavy camps {sorted(heavy)}"] if heavy else []) + ([f"groups {f['grp']}"] if not 36 <= f["grp"] <= 70 else []) \
        + ([f"area {m.W * m.H}"] if not 2400 <= m.W * m.H <= 4800 else [])
    return "; ".join(why) or None


def _ck_goldrace1(m, f, x):
    alts = [(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR]
    gs, area, s2s = gr_share(m.camp), m.W * m.H, gr_s2s(m)
    heavy = {t for t in m.camp.values() if t in (ELK, GOLEM, MONO)}
    why = []
    if len(alts) != 1:
        why.append(f"altar tiles {len(alts)}")
    if not 0.40 <= gs <= 0.55:
        why.append(f"gold_share {gs:.3f}")
    if heavy:
        why.append(f"heavy camps {sorted(heavy)}")
    if not 25 <= f["grp"] <= 60:
        why.append(f"groups {f['grp']}")
    if not 2400 <= area <= 4800:
        why.append(f"area {area}")
    if not 38 <= s2s <= 42:
        why.append(f"s2s {s2s}")
    if f["none"] > 0:
        why.append(f"unreachable gems {f['none']}")
    return "; ".join(why) or None


# ---------------------------------------------------------------- 11 Nov: w_richcentre (owner: resource-heavy contested centres)
def _rc_groups(m):
    seen, out = set(), []
    for c in m.camp:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in m.camp and q not in seen:
                    seen.add(q)
                    st.append(q)
        out.append(comp)
    return out


def _m_richcentre(rec, seed, rng):
    """several SEPARATE heavy groups (elk / golem / gem clusters, no monolith) spread over a contested centre of radius rad, mirrored, so a
    team must split or group up to take them; everything else becomes small gold/wolf groups. Check: >= 60% of the camp gems in groups
    within rad+1 of the centre, >= 4 such groups, elk+golem >= 35% of those gems."""
    m = G.generate(rec, seed)
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    R = rec["rad"]
    for t, _ in list(m.groups):
        if any(max(abs(p[0] - cx), abs(p[1] - cy)) <= R + 2 for p in t):
            NF.remove_group(m, t)
    for p in [p for p in m.camp if max(abs(p[0] - cx), abs(p[1] - cy)) <= R + 2]:
        m.camp.pop(p, None)
    placed, tries = 0, 0
    while placed < rec["npair"] and tries < 400:
        tries += 1
        sx, sy = int(round(cx + rng.uniform(-R, R))), int(round(cy + rng.uniform(-R, R)))
        if _cheb((sx, sy), m.mir(sx, sy)) < 5:  # a pair, not one self-mirror blob
            continue
        n = rng.randint(rec["gmin"], rec["gmax"])
        tiles, front = [(sx, sy)], [(sx, sy)]
        while len(tiles) < n and front:
            x, y = front[rng.randrange(len(front))]
            q = (x + rng.choice((-1, 1)), y) if rng.random() < 0.5 else (x, y + rng.choice((-1, 1)))
            if q not in tiles and max(abs(q[0] - cx), abs(q[1] - cy)) <= R:
                tiles.append(q)
                front.append(q)
        ok = True
        for p in tiles:
            mp = m.mir(*p)
            if (not _walk(m, *p) or p in m.protect or m.dspawn(*p) < 6 or _cheb(p, mp) < 3
                    or any((p[0] + dx, p[1] + dy) in m.camp for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2))
                    or any(m.inb(p[0] + dx, p[1] + dy) and m.get(p[0] + dx, p[1] + dy) == ALTAR for dx, dy in N8)):
                ok = False
                break
        if not ok or len(tiles) < rec["gmin"]:
            continue
        grp = []
        for p in tiles:
            u = rng.random()
            t = GOLEM if u < rec["pgolem"] else ELK if u < rec["pgolem"] + rec["pelk"] else GEM
            grp.append((p[0], p[1], t))
        G.put_group(m, grp, "richcentre")
        placed += 1
    if placed < 2:
        raise RuntimeError("no room for the central groups")
    for t, k in list(m.groups):  # outside: small gold / wolf groups only, so the centre holds the gems
        if k == "richcentre":
            continue
        for p in t:
            if p in m.camp:
                v = GOLD if rec["outer"] == "gold" or rng.random() < 0.6 else WOLF
                m.camp[p] = v
                m.camp[m.mir(*p)] = v
    if not _connected(m):
        raise RuntimeError("not connected")
    m._rc_rad = R + 1
    return m


def _ck_richcentre(m, f, x):
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    gems = {WOLF: 4, ELK: 15, GEM: 7, GOLD: 0, MONO: 200, GOLEM: 36}
    tot = sum(gems.get(t, 0) for t in m.camp.values())
    cen = [g for g in _rc_groups(m) if any(max(abs(p[0] - cx), abs(p[1] - cy)) <= m_rad(m) for p in g)]
    cg = sum(gems.get(m.camp[p], 0) for g in cen for p in g)
    heavy = sum(gems.get(m.camp[p], 0) for g in cen for p in g if m.camp[p] in (ELK, GOLEM))
    why = []
    if not tot or cg / tot < 0.60:
        why.append(f"centre gem share {cg / max(1, tot):.2f}")
    if len(cen) < 4:
        why.append(f"central groups {len(cen)}")
    if cg and heavy / cg < 0.35:
        why.append(f"heavy share {heavy / cg:.2f}")
    if f["none"] > 0:
        why.append(f"unreachable gems {f['none']}")
    return "; ".join(why) or None


def m_rad(m):
    return getattr(m, "_rc_rad", 13)

# ---------------------------------------------------------------- 11 Nov: w_bushroutes (owner: bush on key routes and hotspots)
def _br_keys(m):
    """(route tiles, hotspot tiles) of a built map: one shortest 8-way walk from spawn A to spawn B, to the 3 richest groups and to each
    altar; hotspots = walkable tiles within 3 of the centre, each altar and the 3 richest groups (mapclass.d/bushroute.py's measure)."""
    from collections import deque
    gems = {WOLF: 4, ELK: 15, GEM: 7, GOLD: 0, MONO: 200, GOLEM: 36}
    gold = {WOLF: 40, ELK: 90, GEM: 0, GOLD: 20, MONO: 300, GOLEM: 160}
    ok = lambda p: m.inb(*p) and m.get(*p) in (FLOOR, BUSH)  # noqa: E731
    x0, y0, x1, y1 = m.rectA()
    src = [(x, y) for x in range(x0, x1) for y in range(y0, y1)]
    bx0, by0, bx1, by1 = m.rectB()
    dst = {(x, y) for x in range(bx0, bx1) for y in range(by0, by1)}
    par, dist, q = {p: None for p in src}, {p: 0 for p in src}, deque(src)
    while q:
        c = q.popleft()
        for dx, dy in N8:
            n = (c[0] + dx, c[1] + dy)
            if (ok(n) or n in dst) and n not in dist:
                dist[n], par[n] = dist[c] + 1, c
                q.append(n)

    def route(targets):
        t = min((x for x in targets if x in dist), key=lambda x: dist[x], default=None)
        out = []
        while t is not None:
            out.append(t)
            t = par[t]
        return out
    grs = sorted(_rc_groups(m), key=lambda g: -sum(gems.get(m.camp[p], 0) + gold.get(m.camp[p], 0) / 10 for p in g))[:3]
    alts = [(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR]
    rt = set(route(dst))
    for g in grs:
        rt |= set(route({(p[0] + dx, p[1] + dy) for p in g for dx, dy in N8}))
    for a in alts:
        rt |= set(route({(a[0] + dx, a[1] + dy) for dx, dy in N8}))
    rt = {p for p in rt if ok(p) and p not in m.camp and p not in dst and m.cheb_rect(m.rectA(), *p) > 0}
    cs = [((m.W - 1) // 2, (m.H - 1) // 2)] + alts + [p for g in grs for p in g]
    return rt, cs


def _m_bushroutes(rec, seed, rng):
    m = G.generate(rec, seed)
    rt, cs = _br_keys(m)
    free = lambda p: m.inb(*p) and m.get(*p) == FLOOR and p not in m.camp and p not in m.protect and m.dspawn(*p) >= 2  # noqa: E731
    for p in sorted(rt):
        if rng.random() < rec["proute"]:
            for dx in range(-rec["widen"], rec["widen"] + 1):
                for dy in range(-rec["widen"], rec["widen"] + 1):
                    q = (p[0] + dx, p[1] + dy)
                    if free(q) and (q == p or rng.random() < 0.5):
                        m.put(q[0], q[1], BUSH)
    r = rec["hotr"]
    for cx, cy in cs:
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                q = (cx + dx, cy + dy)
                if free(q) and rng.random() < rec["phot"]:
                    m.put(q[0], q[1], BUSH)
    if not _connected(m):
        raise RuntimeError("not connected")
    return m


def _ck_bushroutes(m, f, x):
    rt, cs = _br_keys(m)
    ok = lambda p: m.inb(*p) and m.get(*p) in (FLOOR, BUSH)  # noqa: E731
    hot = {(cx + dx, cy + dy) for cx, cy in cs for dx in range(-3, 4) for dy in range(-3, 4) if ok((cx + dx, cy + dy))}
    br = sum(m.get(*p) == BUSH for p in rt) / max(1, len(rt))
    bh = sum(m.get(*p) == BUSH for p in hot) / max(1, len(hot))
    why = []
    if br < 0.25:
        why.append(f"route bush {br:.2f}")
    if bh < 0.25:
        why.append(f"hotspot bush {bh:.2f}")
    if f["none"] > 0:
        why.append(f"unreachable gems {f['none']}")
    return "; ".join(why) or None

BUILD = {"w_cramped": _m_cramped, "w_spawncloset": _m_spawncloset, "w_alcove": _m_alcove, "w_bushplug": _m_bushplug,
         "w_snake": _m_snake, "w_campring": _m_campring, "w_revolving": _m_revolving, "w_hiddencamp": _m_hiddencamp,
         "w_checker": _m_checker, "w_checker_big": _m_checker, "w_evenrace": _m_evenrace, "w_moatcamp": _m_moatcamp, "w_goldcrystal": _m_goldcrystal,
         "w_guardaltar": _m_guardaltar, "w_lines": _m_lines, "w_monocorner": _m_monocorner,
         "w_monotank": lambda rec, seed, rng: _m_monocorner(dict(rec, tank=True), seed, rng), "w_onepack": _m_onepack, "w_onemono": _m_onemono,
         "w_longpath": _m_longpath, "w_crosswires": _m_crosswires, "w_manygrp": _m_manygrp, "w_goldrace1": _m_goldrace1, "w_goldring1": _m_goldrace1, "w_nointer": _m_nointer, "w_jackpot": _m_jackpot, "w_hms": _m_manygrp, "w_goldcol": _m_column, "w_gemcol": _m_column, "w_jackpot2": _m_jackpot, "w_keystone": _m_jackpot, "w_elkctr": _m_jackpot,
         "w_altargems1": _m_altargems1, "w_richcentre": _m_richcentre, "w_bushroutes": _m_bushroutes}
VALIDATE = {"w_guardaltar": _v_guardaltar, "w_nointer": _v_nointer}  # genweird.make: families whose access rule differs from the normal open-access check


def make(fam, rec, seed, rng):
    return BUILD[fam](rec, seed, rng)


# ---------------------------------------------------------------- property checks on the built map
def _nwalk(m, p):
    return sum(_walk(m, p[0] + dx, p[1] + dy) and (p[0] + dx, p[1] + dy) not in m.camp for dx, dy in N8)


def _ck_spawncloset(m, f, x):
    r = m.rectA()
    exits = [(a, b) for a in range(r[0] - 1, r[2] + 1) for b in range(r[1] - 1, r[3] + 1) if m.cheb_rect(r, a, b) == 1 and _walk(m, a, b)]
    return None if len(exits) == 1 else f"spawn exits {len(exits)}"


def _ck_campring(m, f, x):
    r = m.rectA()
    blk = m.bfs("A", block_camps=True)
    out = max((m.cheb_rect(r, *p) for p in blk), default=0)
    return None if out <= 2 else f"walks out of the ring to {out}"


def _ck_revolving(m, f, x):
    blk, walk = m.bfs("A", block_camps=True), m.bfs("A")
    rooms = [t for t, k in m.groups if k == "room"]
    shut = [t for t in rooms if not any((p[0] + dx, p[1] + dy) in blk for p in t for dx, dy in N8)
            and any((p[0] + dx, p[1] + dy) in walk for p in t for dx, dy in N8)]
    return None if rooms and len(shut) == len(rooms) else f"rooms {len(rooms)} shut {len(shut)}"


def _ck_moatcamp(m, f, x):
    walk = m.bfs("A")
    for t, k in m.groups:
        if k != "moat":
            continue
        dmin = min(_cheb(p, q) for p in t for q in ((p[0] + dx, p[1] + dy) for dx in range(-3, 4) for dy in range(-3, 4)) if q in walk) \
            if any((p[0] + dx, p[1] + dy) in walk for p in t for dx in range(-3, 4) for dy in range(-3, 4)) else 99
        if not 2 <= dmin <= 3:
            return f"moat ring at walk distance {dmin} (melee 1, ranged 3)"
    return None if any(k == "moat" for _, k in m.groups) else "no moat island"


def _ck_checker(m, f, x):
    n = sum(1 for p in m.camp if not any((p[0] + dx, p[1] + dy) in m.camp for dx, dy in N4)
            and any((p[0] + dx, p[1] + dy) in m.camp for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1))))
    return None if n >= 16 else f"corner-only camps {n}"


def _ck_checker_big(m, f, x):
    bad = _ck_checker(m, f, x)
    if bad:
        return bad
    seen, ng = set(), 0
    for p in m.camp:
        if p in seen:
            continue
        ng += 1
        st = [p]
        seen.add(p)
        while st:
            c = st.pop()
            for dx, dy in N4:
                q = (c[0] + dx, c[1] + dy)
                if q in m.camp and q not in seen:
                    seen.add(q)
                    st.append(q)
    if min(m.W, m.H) < 49:
        return f"board {m.W}x{m.H} under 49 a side"
    return None if 90 <= ng <= 130 else f"camp groups {ng} not in 90-130"


def _ck_evenrace(m, f, x):
    off = [p for p in list(m.camp) + list(m.altars) if m.mir(*p) != p]
    return None if not off and f["gems"] >= 14 else f"off-axis {len(off)} gems {f['gems']}"


def _ck_goldcrystal(m, f, x):
    walk = m.bfs("A")
    gold = [p for p, t in m.camp.items() if t == GOLD]
    open_ = [p for p in gold if any((p[0] + dx, p[1] + dy) in walk for dx, dy in N8)]
    other = [t for t in m.camp.values() if t not in (GEM, GOLD)]
    return None if gold and not open_ and not other else f"gold {len(gold)} walkable {len(open_)} other {len(other)}"


def _ck_guardaltar(m, f, x):
    """every tribute tile of every altar is a wall, a hole or a monolith tile, at least one monolith tile is reachable without
    killing a camp, and the spawns connect without killing one"""
    reach = m.bfs("A", block_camps=True)
    alts = {(i % m.W, i // m.W) for i, v in enumerate(m.g) if v == ALTAR}
    mono_ok = False
    for a in alts:
        for dx, dy in N8:
            q = (a[0] + dx, a[1] + dy)
            if not m.inb(*q) or q in alts:
                continue
            if q in m.camp:
                if m.camp[q] != MONO:
                    return f"tribute tile {q} holds a non-monolith camp"
                mono_ok = mono_ok or any((q[0] + ex, q[1] + ey) in reach for ex, ey in N8)
            elif m.get(*q) not in (WALL, HOLE):
                return f"free tribute tile {q}"
    if not alts or not mono_ok:
        return "no reachable monolith gate" if alts else "no altar"
    return None if m.s2s(reach) else "spawns not connected without killing a camp"


def _ck_monocorner(m, f, x):
    mono = [p for p, t in m.camp.items() if t == MONO and m.cheb_rect(m.rectA(), *p) <= 3]
    if len(mono) < 2:
        return f"spawn-A monoliths {len(mono)}"
    stand, walk = len(_mc_stand(m, mono)), _mc_walk(m)
    other = sum(CLUSTER_GOLD for t in m.camp.values() if t == GOLD) / 2
    ratio = other / (MONO_GOLD * len(mono))
    types = set(m.camp.values())
    return (None if stand <= 15 and walk >= 40 and 0 < ratio <= 0.5 and types <= {GOLD, MONO} and 3 <= m.T <= 5
            else f"stand {stand} walk {walk} gold ratio {ratio:.2f} types {sorted(types)} T {m.T}")


def _ck_monotank(m, f, x):
    why = _ck_monocorner(m, f, x)
    mono = [p for p, t in m.camp.items() if t == MONO and m.cheb_rect(m.rectA(), *p) <= 3]
    return why or (None if _mc_tanks(m, mono) else "no tank tile")


def _ck_lines(m, f, x):
    """at least 3 camp groups (mirror copies counted) whose tiles form one 1-tall run of >= 15"""
    n = 0
    for t, k in m.groups:
        if k != "line":
            continue
        xs, ys = {p[0] for p in t}, {p[1] for p in t}
        if (len(ys) == 1 and len(xs) == len(t) and max(xs) - min(xs) + 1 == len(t) or
                len(xs) == 1 and len(ys) == len(t) and max(ys) - min(ys) + 1 == len(t)) and len(t) >= 15:
            n += 1 if {m.mir(*p) for p in t} == set(t) else 2
    return None if n >= 3 else f"long lines {n}"


CHECKS = {
    "w_cramped": lambda m, f, x: None if min(m.W, m.H) <= 40 and m.T >= 4 and x["nbr"] <= 5.0 else f"{m.W}x{m.H} nbr {x['nbr']}",
    "w_spawncloset": _ck_spawncloset,
    "w_alcove": lambda m, f, x: (None if m.camp and all(_nwalk(m, p) == 1 for p in m.camp) else
                                 f"open camps {sum(_nwalk(m, p) != 1 for p in m.camp)}"),
    "w_bushplug": lambda m, f, x: None if f["bush"] >= 3 and x["nbr"] <= 4.8 else f"bush {f['bush']}% nbr {x['nbr']}",
    "w_snake": lambda m, f, x: None if x["maxg"] >= 12 else f"longest group {x['maxg']}",
    "w_campring": _ck_campring,
    "w_revolving": _ck_revolving,
    "w_hiddencamp": lambda m, f, x: (None if sum(all(m.get(p[0] + dx, p[1] + dy) != FLOOR or (p[0] + dx, p[1] + dy) in m.camp
                                                     for dx, dy in N8 if m.inb(p[0] + dx, p[1] + dy)) for p in m.camp) >= 0.8 * len(m.camp)
                                     else "camps not hidden"),
    "w_checker": _ck_checker,
    "w_checker_big": _ck_checker_big,
    "w_evenrace": _ck_evenrace,
    "w_moatcamp": _ck_moatcamp,
    "w_goldcrystal": _ck_goldcrystal,
    "w_guardaltar": _ck_guardaltar,
    "w_lines": _ck_lines,
    "w_monocorner": _ck_monocorner,
    "w_monotank": _ck_monotank,
    "w_onepack": lambda m, f, x: None if _op_map(m)[0] else "not ONE_PACK: " + _op_map(m)[1],
    "w_onemono": lambda m, f, x: None if _om_map(m)[0] else "not ONE_MONO: " + _om_map(m)[1],
    "w_longpath": _ck_longpath,
    "w_crosswires": _ck_crosswires,
    "w_manygrp": lambda m, f, x: (None if 65 <= f["grp"] <= 130 and min(m.W, m.H) >= 50
                                  else f"groups {f['grp']} board {m.W}x{m.H} (want 65-130 groups, >= 50 a side)"),
    "w_goldrace1": _ck_goldrace1,
    "w_goldring1": lambda m, f, x: _ck_goldring1(m, f),
    "w_nointer": lambda m, f, x: _ck_nointer(m, f),
    "w_jackpot": lambda m, f, x: _ck_jackpot(m, f),
    "w_jackpot2": lambda m, f, x: _ck_jackpot(m, f) or _ck_jackpot2(m),
    "w_elkctr": lambda m, f, x: None if not any(t in (MONO, GOLEM) for t in m.camp.values()) else "golem/monolith on the map",
    "w_keystone": lambda m, f, x: None if not any(t in (WOLF, ELK, MONO, GOLEM) for (x_, y_), t in m.camp.items()
                                               if max(abs(x_ - (m.W - 1) // 2), abs(y_ - (m.H - 1) // 2)) <= 3) else "attacking camp in the centre",
    "w_goldcol": lambda m, f, x: _ck_column(m, f),
    "w_gemcol": lambda m, f, x: _ck_column(m, f),
    "w_hms": lambda m, f, x: None if 255 <= f["grp"] <= 440 else f"groups {f['grp']} (want 255-440)",
    "w_altargems1": _ck_altargems1,
    "w_richcentre": _ck_richcentre,
    "w_bushroutes": _ck_bushroutes,
}


def check(fam, m, f, x):
    return CHECKS[fam](m, f, x)


if __name__ == "__main__":
    print(__doc__)
    _ = random
