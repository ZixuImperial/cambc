#!/usr/bin/env python3
"""genweird: WEIRD / pathological map families for per-run fresh sets. Tool builder, 1 Nov (owner: "we should design weirder
maps like this for the next competition", "think of more pathological maps"; tournament 1 Nov 14:47Z on unseen 03homonoliths
(the only gems a 3-monolith group beside each spawn), 03fan (41x41, 1 altar, 32 small wolf groups) and 03twisty (90x70, 14
groups, winding paths: 76% of turns walking)). Never saved or installed: stratmaps.py (share 'weird') builds them in a run's
work dir from os.urandom seeds.

Families (the kind label is the family name; every map is legal (GameRules: 30x30 to 100x100, so no board under 30 a side) and
mirror-symmetric: genmaps validate + engine mkmap build/decode check + the family's own property check on the built map):
  w_spawnmono   gold-only clusters + a 2-4 monolith group within Chebyshev 1-3 of each spawn: the only gems (03homonoliths)
  w_heavygems   every gem sits in a heavy camp (golems, monoliths); all clusters gold, no wolves or elk
  w_gemonly     gem clusters only, no gold anywhere (genfam gemonly)
  w_centralmono one self-symmetric field of 6-14 monoliths at the centre (genfam hoard, every hoard tile a monolith)
  w_dashaltar   altars only on dash/crystal islands (genmaps patho dash_altar) or inside a camp ring (gate ring_camps)
  w_pocket      spawn at the far end of a 2-3 wide road maze: long wall detours (genfam road)
  w_bushmaze    genfam corr/road maze (mean walkable neighbours <= 5.6) with 45-85% of the walkable floor bush
  w_tiny        30-32 a side, the smallest legal board
  w_huge        95-100 a side, 6-12 groups (genfam huge)
  w_islands     6-16 small dash/crystal islands (genfam isle)
  w_hugefew     80-100 a side, 10-16 groups whose nearest other group is a median 10+ tiles away
  w_twisty      maze, 1-3 wide: spawn-to-spawn walk >= 3x Chebyshev, altar walk >= 2.5x, median group walk >= 2x (03twisty)
  w_choke       1-wide corridors (mean walkable neighbours <= 4.2): bodies block each other (genfam corr cw 1)
  w_farspawn    no camp within 40 walk of either spawn
  w_altpocket   one shared central altar (one per side), half the draws inside a 5x5 wall pocket whose single gate faces away
                from team A (walk >= Chebyshev + 6), half just far from both spawns. Mirror symmetry makes 'every altar
                nearer the enemy' impossible: each altar has a twin nearer us.
  w_dangeronly  elk/golem-only camps, no clusters (genfam heavy)
  w_hoardtiny   one 15-25 camp hoard vs many 1-tile groups (genfam hoard with a gem1/gold1/wolf mix)
  w_nobush      no bush tile at all
  w_bushall     bush on 88-98% of the walkable floor
  w_contact     30-34 a side, spawns <= 10 walk apart (genfam brawl)
  w_altmany     8+ altar tiles (genfam altmany)
  w_fan         39-45 a side, one shared altar, 24+ wolf-only groups (03fan; the radial layout itself is not reproduced)
  w_starve      60-90 a side, one shared altar, 4-8 groups of single gem clusters and wolves: 10-80 gems on the whole map
                (tournament 03ultrastarvation: 67x73, 6 groups, 4 single 7-gem clusters + 2 wolves, games end ~250 tributed)
 1 Nov ~19:45 (owner via Builder: "more CREATIVE families", "starved maps with limited of some resources"):
  w_smallc      (not in the pool draw: --wfams only; 10 Nov, Econ spec SCF; v3 14:50Z) the 01elk_arena band: ONE central gem group C =
                an elk pair + gem clusters, 4,500-6,000 HP, respawn <= 60, >= 90% of the map's gems, walk 6-11 from each spawn to C,
                C on the direct spawn-to-spawn line, 10-18 gold-only groups (01elk_arena: we are 0/19). smallc_scan.py qualifies it
  w_smallc_wide (--wfams only) the broader v2: elk or wolf pairs, cluster-rich centres up to 6,000 HP, walk 5-15
  w_seencarry   (not in the pool draw: --wfams only) w_midgems on small/medium OPEN boards, short spawns, no bush: foe carriers in sight
  w_midgems     gold-only base + every gem group in the contested zone (walk share 0.42-0.58): the symmetric form of 'each side's
                gems in the other half' (under mirror symmetry every gem group near the enemy has a twin near us)
  w_inverted    spawns near the centre, every camp out at the edges and corners
  w_thin        30-34 x 90-100 boards, mirrored across the long side (spawns far apart)
  w_holefield   1-3-tile checkerboard of holes over the open floor (dash-heavy movement; repair keeps every route walkable)
  w_campwall    a wall band across the middle whose gaps are plugged by dense wolf/elk rows (spawns meet only through camps)
  w_homealtar   an altar 3-11 from each spawn, no camp within 20 walk (bank race)
  w_dashgolem   dash-only altar islands (patho dash_altar) + a golem-heavy mix with monoliths
  w_deadend     a loop-free maze (every branch a dead end) with rich cluster/golem camps
  w_centralblob one central self-symmetric 15-40-camp group holds every gem; only gold clusters elsewhere
  w_5v5tiny     5 a side on the minimum 30x30 board
  w_goldrich    gold everywhere, gems scarce (gold >= 8x gems)       w_goldstarve  gem clusters only, <= 200 gold on the map
  w_splitlane   the same wall band with 2-3 OPEN 1-2-wide crossings
  w_bushaltar   every altar ringed by bush (radius 1-2)              w_microisles  14-24 tiny dash/crystal islands, one group each
  w_wardstarve  a narrow maze whose floor is 92-99% bush             w_altarstarve one shared altar far from both spawns (>= 25 walk)
  w_campstarve  40-60 board with 3-5 groups in all                   w_heavystarve 1-2 golem/monolith groups per side, nothing else
  w_space       1-wide corridors between 3-thick walls (>= 55% wall) w_timestarve only golems/monoliths (80/150-round respawns)
 3 Nov (owner via Builder: "maps with spawns right next to each other"; 00reverse-spiral, spawns touching):
  w_spawnadj    S/M board, team A's spawn near the centre and the mirrored B spawn 1, 2 or 3 apart (rect gap, Chebyshev; drawn
                2:1:1); on half the draws a 1-tile wall or hole cup round each spawn whose open side faces away from the other
                spawn (the 00reverse-spiral shape: the line between them, flanks and their 0-3-tile extensions protected; at gap 3
                the line is 2 thick when the mirror axis runs between the spawns)
Starved variants (owner 2 Nov), named with --wfams or in smoke runs, not in FAMS until read:
  w_cryststarve  w_starve with gold groups in the open and every gem in a walled 3x3 pocket: teleport crystal only (10-84 gems)
  w_nocamps      no camp at all: no gems, no gold from camps; only fights and the round-2000 tie-break decide
  w_nogems       w_starve with gold only: nobody can tribute, so gold earned decides at round 2000
Cruel and tight families (4 Nov, Tool builder 2; tools/lab/gencruel.py, opt-in by name like the starved ones): w_cramped
  w_spawncloset w_alcove w_bushplug w_snake w_campring w_revolving w_hiddencamp w_checker w_evenrace w_moatcamp w_goldcrystal
API: FAMS; recipe(fam, rng) -> dict; build_one(fam, name, seed, rec, outdir) -> (map path, features), raising on a miss.
usage (smoke test: N maps per family, hit rate and seconds; writes the maps into OUTDIR):
  python3 -I tools/lab/genweird.py OUTDIR [N] [FAM,FAM,...]      (-h / --help: this text, nothing written)"""
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import genfam as NF  # noqa: E402
import mapfeat  # noqa: E402
import gencruel  # noqa: E402  (4 Nov, Tool builder 2: cruel + tight families, opt-in by name)

FAMS = ["w_spawnmono", "w_heavygems", "w_gemonly", "w_centralmono", "w_dashaltar", "w_pocket", "w_bushmaze", "w_tiny",
        "w_huge", "w_islands", "w_hugefew", "w_twisty", "w_choke", "w_farspawn", "w_altpocket", "w_dangeronly", "w_hoardtiny",
        "w_nobush", "w_bushall", "w_contact", "w_altmany", "w_fan", "w_starve",
        # 1 Nov ~19:45, owner via Builder ("more CREATIVE families"; "starved maps with limited of some resources")
        "w_midgems", "w_inverted", "w_thin", "w_holefield", "w_campwall", "w_homealtar", "w_dashgolem", "w_deadend",
        "w_centralblob", "w_5v5tiny", "w_goldrich", "w_splitlane", "w_bushaltar", "w_microisles",
        "w_goldstarve", "w_wardstarve", "w_altarstarve", "w_campstarve", "w_heavystarve", "w_space", "w_timestarve",
        # 3 Nov, owner via Builder: spawns right next to each other
        "w_spawnadj"]
WOLF, ELK, GEM, GOLD, MONO, GOLEM = G.WOLF, G.ELK, G.GEM, G.GOLD, G.MONO, G.GOLEM
FLOOR, WALL, BUSH, ALTAR = G.FLOOR, G.WALL, G.BUSH, G.ALTAR
N4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
G.MIXES.setdefault("w_heavygold", {"gold_row": 3, "gold_patch": 3, "golem": 2, "golem_pair": 1, "monolith": 1})
G.MIXES.setdefault("w_tinybits", {"gem1": 3, "gold1": 2, "wolf": 2})
G.MIXES.setdefault("w_wolves", {"wolf": 3, "wolf_pack": 2})
G.MIXES.setdefault("w_starve", {"gem1": 2, "wolf": 1})
G.MIXES.setdefault("w_goldbits", {"gold1": 3, "wolf": 1})
G.MIXES.setdefault("w_goldrich", {"gold_row": 4, "gold_patch": 3, "gold_guard": 2, "wolf": 1, "gem1": 0.5})
G.MIXES.setdefault("w_goldstarve", {"gem_patch": 4, "gem_field": 2, "gem_row": 2, "gem1": 1, "gold1": 0.3})
G.MIXES.setdefault("w_heavyonly", {"golem": 2, "golem_pair": 1, "monolith": 1})
# genfam family -> its builder and check do the work (genfam.build_one); check() below adds the weird property on top
NF_BASE = {"w_gemonly": "gemonly", "w_pocket": "road", "w_huge": "huge", "w_islands": "isle",
           "w_twisty": None, "w_choke": "corr", "w_dangeronly": "heavy", "w_hoardtiny": "hoard", "w_bushall": "bush",
           "w_contact": "brawl", "w_altmany": "altmany", "w_campwall": "block", "w_deadend": "corr", "w_microisles": "isle",
           "w_space": "corr"}


def recipe(fam, r):
    if fam in gencruel.FAMS:
        return gencruel.recipe(fam, r)
    if fam in NF_BASE:
        base = NF_BASE[fam] or r.choice(["road", "corr"])
        rec = dict(NF.recipe(base, r), wbase=base)
        if fam == "w_twisty":
            rec.update(size=r.choice(["L", "XL", "XL"]), cw=r.choice([1, 2, 2, 3]), wt=r.choice([1, 2, 3]), p_loop=r.uniform(0, 0.05),
                       cross=1)
        elif fam == "w_choke":
            rec.update(cw=1, wt=r.choice([1, 1, 2]))
        elif fam == "w_hoardtiny":
            rec.update(hsize=r.randint(15, 25), mix="w_tinybits", rim=r.uniform(0.0, 0.5), share=r.uniform(0.75, 0.9))
        elif fam == "w_bushall":
            rec["bushf"] = r.uniform(0.88, 0.98)
        elif fam == "w_altmany":
            rec["nalt"] = r.randint(4, 8)
        elif fam == "w_campwall":  # the spawns meet only through dense wolf/elk plugs (genfam block's 'cut' check)
            rec.update(plug=r.choice([[WOLF], [WOLF, ELK], [ELK], [WOLF, WOLF, ELK]]), gw=r.choice([1, 2, 3]), gaps=r.choice([1, 2, 3]),
                       th=r.choice([1, 2, 3]))
        elif fam == "w_deadend":  # a tree maze (no loops): every branch is a dead end, rich clusters in them
            rec.update(p_loop=0.0, mix=r.choice(["cluster_heavy", "cluster_heavy", "golems"]), rooms=r.randint(3, 6))
        elif fam == "w_microisles":
            rec["nisl"] = r.randint(14, 24)
        elif fam == "w_space":  # 1-wide corridors between 3-thick walls: little walkable area, few routes
            rec.update(cw=1, wt=3, size=r.choice(["S", "M"]))
        return rec
    if fam == "w_bushmaze":
        return dict(NF.recipe(r.choice(["corr", "road"]), r), bushf=r.uniform(0.45, 0.85))
    if fam == "w_spawnmono":
        return NF.base_rec(r, mix="nf_gold", mono=0, size=r.choice(["S", "S", "M"]), nm=r.randint(2, 4))
    if fam == "w_multimono":  # b1427: not in FAMS, so no pool draw holds it; --wfams w_multimono only
        return NF.base_rec(r, mono=0, size=r.choice(["S", "M", "M", "L"]), nm=r.randint(2, 3), gc=r.randint(0, 6), mmode=r.choice(["side", "side", "central"]))
    if fam == "w_heavygems":
        return NF.base_rec(r, mix="w_heavygold", mono=r.choice([1, 1, 2]))
    if fam == "w_centralmono":
        return NF.base_rec(r, size=r.choice(["M", "L", "L"]), mono=0, altar=r.choice(["near", "far", "many", "shared"]),
                           hsize=r.randint(6, 14), rim=0.0, share=r.uniform(0.6, 0.85))
    if fam == "w_dashaltar":
        import genbig
        if r.random() < 0.5:
            pool = [x for x in genbig.patho_recipes(100) if x["kind"] == "dash_altar"]
        else:
            pool = [x for x in genbig.gate_recipes(60) if x["kind"] == "ring_camps"]
        return dict(r.choice(pool), checks=2)
    if fam == "w_tiny":
        d = r.choice([30, 30, 31, 32])
        return NF.base_rec(r, size="S", aspect="square", dims=(d, d), T=r.choice([3, 3, 4]), spawn="short", mono=0,
                           mix=r.choice(["balanced", "cluster_heavy", "gem_poor"]), altar=r.choice(["near", "shared", "central"]))
    if fam == "w_hugefew":
        Wd = r.randint(80, 100)
        return NF.base_rec(r, size="XL", aspect="square", dims=(Wd, r.choice([Wd, r.randint(80, 100)])), spawn="long",
                           style=r.choice(["open", "holes", "bushbelt", "mixed", "corridors"]), keep=r.randint(10, 16), mono=0)
    if fam == "w_farspawn":
        Wd = r.randint(70, 100)
        return NF.base_rec(r, size="XL", aspect="square", dims=(Wd, r.choice([Wd, r.randint(70, 100)])), spawn="long")
    if fam == "w_altpocket":
        return NF.base_rec(r, far="shared", pocket=r.random() < 0.5, spawn=r.choice(["long", "medium"]))
    if fam == "w_nobush":
        return NF.base_rec(r, style=r.choice(["open", "corridors", "maze", "holes", "mixed"]))
    if fam == "w_fan":
        d = r.randint(39, 45)
        return NF.base_rec(r, size="M", aspect="square", dims=(d, d), mix="w_wolves", mono=0, far="shared",
                           style=r.choice(["open", "open", "holes", "mixed"]), nwolf=r.randint(12, 16))
    if fam in ("w_smallc", "w_smallc_wide"):  # 10 Nov (Econ, spec SCF): small boards and short/medium spawns keep the centre within 15 walk;
        # heavy = the guards' preferred composition (a lighter one is used if the built group's HP would pass 6,000).
        # 10 Nov ~14:40Z (Econ: first central captures r144-205 v ~r60 on 01elk_arena): v1's centres held too few gems for their HP (median
        # 75 gems / 5,640 HP v the saved class maps' 182 / 4,020), so bots came late (first capture either side r89-137 v r58-91 on the saved
        # class maps, same foes). v2: cluster-rich centres (more gem clusters per guard; wolf pairs favoured), walk 5-15, gold-only groups
        # 10-18 (now w_smallc_wide). v3 = w_smallc (Econ ~14:45Z, from b1813's replays: first hit on C r26 v r7 on 01elk_arena, it's
        # the build): one elk pair + gem clusters only, 4,500-6,000 HP, walk 6-11 from each spawn to C, C on the direct spawn-to-spawn line.
        narrow = fam == "w_smallc"
        heavy = "elk2" if narrow else r.choice(["elk2", "wolf2", "wolf2", "wolf2"])
        cs = (8, 12) if narrow else {"elk2": (6, 12), "wolf2": (12, 26)}[heavy]
        return NF.base_rec(r, size=r.choice(["S", "M", "M"]), spawn=r.choice(["medium", "medium", "long"] if narrow else ["short", "medium", "medium", "long"]), mix="nf_gold", mono=0,
                           style=r.choice(["open", "holes", "bushbelt", "mixed", "corridors"]), csize=r.randint(*cs), heavy=heavy,
                           strict_heavy=narrow)
    if fam == "w_bushcamp":  # 12 Nov (TB; Coordinator ruling, BWT / RC C670): OPT-IN ONLY (not in FAMS): rarefill bwt. Small boards of many
        # small gem/wolf camp groups (as 05birthday_cake: 35x37, 2-3 camps a group), one member of several groups on an isolated bush tile
        return NF.base_rec(r, size=r.choice(["S", "S", "M"]), aspect="square", mono=0, nhide=r.randint(3, 6), camp_bush=1)
    if fam == "w_seencarry":  # 10 Nov (Builder: FST-SEEN, a Prism bug only with a foe carrier in sight): small open boards, no bush, every gem
        # group in the contested zone near short spawns, so carriers walk where both teams see them. Not in FAMS: --wfams w_seencarry only
        return NF.base_rec(r, size=r.choice(["S", "M"]), style="open", spawn="short", mix="nf_gold", mono=0, ngem=r.randint(5, 10))
    if fam == "w_midgems":  # mirror symmetry: 'each side's gems in the other half' always has a twin near us; the intent
        # (resources that force contact) = gold-only base + every gem group in the contested zone (equal walk from both spawns)
        return NF.base_rec(r, mix="nf_gold", mono=0, ngem=r.randint(5, 10))
    if fam == "w_inverted":
        return NF.base_rec(r, spawn="short", size=r.choice(["M", "L"]), aspect="square", mono=0)
    if fam == "w_thin":
        a, b = r.randint(30, 34), r.randint(90, 100)
        tall = r.random() < 0.5  # the mirror runs across the long side (sym 1 for a tall board, 0 for a wide one, or 2)
        return NF.base_rec(r, dims=(a, b) if tall else (b, a), spawn="long", sym=r.choice([1 if tall else 0, 2]),
                           style=r.choice(["open", "corridors", "mixed", "holes"]))
    if fam == "w_holefield":
        return NF.base_rec(r, style=r.choice(["open", "open", "mixed"]), blk=r.choice([1, 2, 2, 3]))
    if fam == "w_homealtar":
        return NF.base_rec(r, altar="near", size=r.choice(["M", "L", "L", "XL"]), spawn=r.choice(["medium", "long"]))
    if fam == "w_dashgolem":  # dash-only altar islands (genmaps patho dash_altar) with a golem-heavy camp mix
        import genbig
        rec = dict(r.choice([x for x in genbig.patho_recipes(100) if x["kind"] == "dash_altar"]), checks=2)
        rec.update(mix="golems", mono=r.choice([1, 2]))
        return rec
    if fam == "w_centralblob":
        return NF.base_rec(r, size=r.choice(["M", "L", "L"]), mono=0, altar=r.choice(["near", "far", "many", "shared"]),
                           hsize=r.randint(15, 40), rim=r.uniform(0.2, 0.5), share=r.uniform(0.85, 0.95))
    if fam == "w_5v5tiny":
        return NF.base_rec(r, size="S", aspect="square", dims=(30, 30), T=5, spawn=r.choice(["short", "medium"]), mono=0,
                           mix=r.choice(["balanced", "cluster_heavy", "wolf_packs"]), altar=r.choice(["near", "shared", "central"]))
    if fam == "w_goldrich":
        return NF.base_rec(r, mix="w_goldrich", mono=0)
    if fam == "w_splitlane":  # genfam block's wall band down the middle, its 2-3 gaps left OPEN (narrow crossings)
        rec = NF.recipe("block", r)
        rec.update(gaps=r.choice([2, 2, 3]), gw=r.choice([1, 1, 2]), th=r.choice([1, 2, 3]), plug=[WOLF])
        return rec
    if fam == "w_bushaltar":
        return NF.base_rec(r, altar=r.choice(["near", "far", "shared", "many"]), ring=r.choice([1, 2, 2]))
    if fam == "w_goldstarve":
        return NF.base_rec(r, mix="w_goldstarve", mono=0)
    if fam == "w_wardstarve":  # vision scarcity: a narrow maze whose floor is 92-99% bush
        return dict(NF.recipe("corr", r), bushf=r.uniform(0.92, 0.99))
    if fam == "w_onealtar":  # 8 Nov (Combat, KPW): exactly one altar tile, on the mirror axis; bush 4-6 from it; mixed groups
        sym = r.choice([0, 1])
        a, b = r.randint(15, 35) * 2 + 1, r.randint(35, 71)  # the side the axis crosses is odd, so one tile sits on it
        return NF.base_rec(r, sym=sym, dims=(a, b) if sym == 0 else (b, a), mix=r.choice(["balanced", "cluster_heavy", "wolf_packs", "gem_poor"]),
                           spawn=r.choice(["long", "medium", "medium", "short"]), altar="central", bushr=(r.randint(4, 5), r.randint(5, 6)), bushp=r.uniform(0.25, 0.6))
    if fam == "w_altarstarve":
        return NF.base_rec(r, far="shared", spawn="long", style=r.choice(["corridors", "maze", "mixed"]), size=r.choice(["L", "XL"]))
    if fam == "w_campstarve":
        d = r.randint(40, 60)
        return NF.base_rec(r, dims=(d, r.randint(40, 60)), mix=r.choice(["balanced", "cluster_heavy"]), mono=0, keep=2)
    if fam == "w_heavystarve":
        return NF.base_rec(r, mix="w_heavyonly", mono=0, keep=r.choice([1, 2]))
    if fam == "w_timestarve":  # only golems / monoliths (80 / 150-round respawns): the timing of returns matters
        return NF.base_rec(r, mix="w_heavyonly", mono=r.choice([1, 2]))
    if fam in ("w_cryststarve", "w_nogems"):
        return NF.base_rec(r, size="XL", aspect="square", dims=(r.randint(50, 80), r.randint(50, 80)), T=r.choice([3, 3, 4, 5]),
                           mix="w_goldbits", mono=0, far="shared", keep=r.randint(2, 4), spawn=r.choice(["long", "medium"]), npocket=r.randint(1, 5))
    if fam == "w_nocamps":
        return NF.base_rec(r, size="L", aspect="square", dims=(r.randint(30, 70), r.randint(30, 70)), T=r.choice([3, 4, 5]),
                           mix="w_goldbits", mono=0, far="shared", keep=1, spawn=r.choice(["long", "medium"]))
    if fam == "w_spawnadj":  # gap 1 (touching) : 2 : 3 = 2:1:1; half the draws get a wall or hole cup (fext, lext extensions)
        cup = r.choice(["wall", "hole"]) if r.random() < 0.5 else ""
        return NF.base_rec(r, size=r.choice(["S", "S", "M"]), T=r.choice([3, 4, 5]), spawn="short", gap=r.choice([1, 1, 2, 3]),
                           cup=cup, fext=r.randint(0, 3), lext=r.randint(0, 3))
    if fam == "w_starve":
        return NF.base_rec(r, size="XL", aspect="square", dims=(r.randint(60, 90), r.randint(60, 90)), T=r.choice([3, 3, 4]),
                           mix="w_starve", mono=0, far="shared", keep=r.randint(2, 4), spawn=r.choice(["long", "medium"]))
    raise KeyError(fam)


# ---------------------------------------------------------------- custom builders
def _spawnmono(m, rec, rng):
    """A cardinally joined group of rec['nm'] monoliths with every tile 1-3 (Chebyshev) from spawn A; the mirror gets B's."""
    cand = [(x, y) for x in range(m.W) for y in range(m.H)
            if 1 <= m.cheb_rect(m.rectA(), x, y) <= 3 and m.get(x, y) == FLOOR and (x, y) not in m.camp]
    rng.shuffle(cand)
    for start in cand[:200]:
        grp, frontier = [start], [start]
        while len(grp) < rec["nm"] and frontier:
            c = frontier.pop(rng.randrange(len(frontier)))
            for dx, dy in rng.sample(N4, 4):
                n = (c[0] + dx, c[1] + dy)
                if n in grp or not m.inb(*n) or m.get(*n) != FLOOR or n in m.camp or not 1 <= m.cheb_rect(m.rectA(), *n) <= 3:
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
        G.put_group(m, [(x, y, MONO) for x, y in grp], "spawnmono")
        return True
    return False


def _multimono(m, rec, rng):
    """b1427: a cardinally joined group of rec['nm'] monoliths (+ rec['gc'] attached gem clusters) >= 8 from each spawn: one per side, or one self-symmetric at the centre."""
    def free(p):
        return m.inb(*p) and m.get(*p) == FLOOR and p not in m.camp and m.cheb_rect(m.rectA(), *p) >= 8 and m.cheb_rect(m.rectB(), *p) >= 8

    def clear(tiles):
        return not any((p[0] + dx, p[1] + dy) in m.camp or (m.inb(p[0] + dx, p[1] + dy) and m.get(p[0] + dx, p[1] + dy) == ALTAR)
                       for p in tiles for dx, dy in N8)

    def joined(tiles):
        tiles = set(tiles)
        seen, todo = set(), [next(iter(tiles))]
        while todo:
            c = todo.pop()
            if c in seen:
                continue
            seen.add(c)
            todo += [(c[0] + dx, c[1] + dy) for dx, dy in N4 if (c[0] + dx, c[1] + dy) in tiles]
        return seen == tiles

    cand = [(x, y) for x in range(m.W) for y in range(m.H) if free((x, y))]
    if rec["mmode"] == "central":
        cand.sort(key=lambda p: (abs(p[0] - m.mir(*p)[0]) + abs(p[1] - m.mir(*p)[1]), rng.random()))
    else:
        rng.shuffle(cand)
    for start in cand[:200]:
        grp, frontier = [start], [start]
        while len(grp) < rec["nm"] and frontier:
            c = frontier.pop(rng.randrange(len(frontier)))
            for dx, dy in rng.sample(N4, 4):
                n = (c[0] + dx, c[1] + dy)
                if n not in grp and free(n):
                    grp.append(n)
                    frontier.append(n)
                    if len(grp) == rec["nm"]:
                        break
        own, mir = set(grp), {m.mir(*p) for p in grp}
        if rec["mmode"] == "central":
            own |= mir
            mir = own
            if len(own) < 2 or not joined(own) or not all(free(p) for p in own):
                continue
        elif len(grp) < 2 or own & mir or any((p[0] + dx, p[1] + dy) in mir for p in own for dx, dy in N8):
            continue
        if not clear(own):
            continue
        tiles = [(x, y, MONO) for x, y in sorted(own)]
        rim = sorted({(p[0] + dx, p[1] + dy) for p in own for dx, dy in N4} - own)
        rng.shuffle(rim)
        for p in rim[:rec["gc"]]:
            if free(p) and p not in mir and m.mir(*p) not in own and (rec["mmode"] == "central" or not any((p[0] + dx, p[1] + dy) in mir for dx, dy in N8)):
                tiles.append((p[0], p[1], GEM))
        G.put_group(m, tiles, "multimono")
        return True
    return False


def _gwalk(dist, tiles):
    """Walk from the spawn to stand next to any of tiles (camp and altar tiles are not walkable): min over 8-neighbours + 1."""
    best = None
    for x, y in tiles:
        for dx, dy in N8:
            v = dist.get((x + dx, y + dy))
            if v is not None and (best is None or v + 1 < best):
                best = v + 1
    return best


def _near_groups(m, lim):
    """Team A copies of the groups a body reaches within lim walk from either spawn."""
    dA = m.bfs("A")
    out = []
    for tiles, _ in m.groups:
        w = [v for v in (_gwalk(dA, tiles), _gwalk(dA, [m.mir(*p) for p in tiles])) if v is not None]
        if w and min(w) < lim:
            out.append(tiles)
    return out


def _farspawn(m, rng, rec):
    """Remove every group a body reaches within 40 walk from either spawn; refill (mid/centre zones) up to 3 times."""
    for _ in range(3):
        for t in _near_groups(m, 40):
            NF.remove_group(m, t)
        if len(m.groups) >= 5:
            return
        G.place_groups(m, rng, rec["mix"], 8, True, zone_w=(0.0, 0.4, 0.6), strict=True)
    for t in _near_groups(m, 40):
        NF.remove_group(m, t)


def _pocket(m, rng):
    """A 5x5 wall ring (radius 2) around team A's altar with one gate on the side facing away from spawn A; put() mirrors."""
    ax, ay = m.altars[0]
    if m.cheb_rect(m.rectA(), ax, ay) > m.cheb_rect(m.rectB(), ax, ay):
        ax, ay = m.mir(ax, ay)
    sx, sy = (m.spawn[0] + m.spawn[2]) / 2, (m.spawn[1] + m.spawn[3]) / 2
    away = max(N4, key=lambda d: (ax + 2 * d[0] - sx) ** 2 + (ay + 2 * d[1] - sy) ** 2)
    gate = (2 * away[0], 2 * away[1])
    box = {(ax + dx, ay + dy) for dx in range(-3, 4) for dy in range(-3, 4)}
    if any(not m.inb(*p) or m.dspawn(*p) < 2 or p in m.camp or m.mir(*p) in box for p in box):
        return False
    if any(p in box for p in m.altars if p != (ax, ay)):
        return False
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            r = max(abs(dx), abs(dy))
            if r == 0:
                continue
            m.put(ax + dx, ay + dy, WALL if r == 2 and (dx, dy) != gate else FLOOR)
    for p in box:
        m.prot(*p)
    return G.access_ok(m, True, True)


def _bushfill(m, rng, frac):
    """genfam b_bush's fill on any map: bush blobs on walkable floor (no camp, not in a spawn) until frac of it is bush."""
    walk = [p for p in m.bfs("A") if m.get(*p) == FLOOR]
    target = frac * len(walk)
    for _ in range(4000):
        if sum(1 for p in walk if m.get(*p) == BUSH) >= target:
            break
        x, y = rng.choice(walk)
        for dx, dy in G.blob(rng, rng.randint(6, 40), N8):
            p = (x + dx, y + dy)
            if (m.inb(*p) and m.get(*p) == FLOOR and p not in m.camp and m.mir(*p) not in m.camp
                    and m.cheb_rect(m.rectA(), *p) > 0 and m.cheb_rect(m.rectB(), *p) > 0):
                m.put(p[0], p[1], BUSH)


def _ring_place(m, rng, mix, n, ok):
    """n groups of MIXES[mix] at anchors where ok(x, y) (genmaps group_ok: legal, mirrored, spaced)."""
    names = sorted(G.MIXES[mix])
    wts = [G.MIXES[mix][k] for k in names]
    cand = [(x, y) for x in range(m.W) for y in range(m.H) if m.get(x, y) == FLOOR and ok(x, y)]
    placed = 0
    for _ in range(n * 60):
        if placed >= n or not cand:
            break
        ax, ay = rng.choice(cand)
        tiles = [(ax + dx, ay + dy, t) for dx, dy, t in G.tpl(rng.choices(names, wts)[0], rng)]
        if G.group_ok(m, tiles) and all(ok(x, y) for x, y, _ in tiles):
            G.put_group(m, tiles, "placed")
            if G.access_ok(m, True, True):
                placed += 1
            else:
                G.drop_group(m)
    return placed


def _crystal_pockets(m, rng, n):
    """n mirrored gem clusters, each on the centre of a 3x3 floor inside a closed wall ring: no walk or dash gets in, and a crystal from just outside lands inside."""
    cand = [(x, y) for x in range(4, m.W - 4) for y in range(4, m.H - 4)]
    rng.shuffle(cand)
    done = 0
    for cx, cy in cand:
        if done >= n:
            break
        box = {(cx + dx, cy + dy) for dx in range(-3, 4) for dy in range(-3, 4)}
        if any(m.dspawn(*p) < 3 or p in m.camp or m.get(*p) != FLOOR or m.mir(*p) in box for p in box):
            continue
        if any(max(abs(a - cx), abs(b - cy)) <= 4 for a, b in m.altars):
            continue
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                m.put(cx + dx, cy + dy, WALL if max(abs(dx), abs(dy)) == 2 else FLOOR)
        for p in box:
            m.prot(*p)
        G.put_group(m, [(cx, cy, GEM)], "placed")
        if m.bfs("A") is None:
            return done
        done += 1
    return done


def make(fam, seed, rec):
    rng = random.Random(seed * 5 + 7)
    rec = dict(rec)
    if fam in gencruel.FAMS:
        m = gencruel.make(fam, rec, seed, rng)
        v = getattr(gencruel, "VALIDATE", {}).get(fam)  # 5 Nov: w_guardaltar's altars are camp-gated on purpose
        ok, info = v(m, rec) if v else G.validate(m, dict(rec, kind="nf", checks=2))
        if not ok:
            raise RuntimeError(f"validate: {str(info)[:80]}")
        return m
    if fam in ("w_cryststarve", "w_nogems", "w_nocamps"):
        m = NF.b_altfar(rec, seed)
        NF.thin_groups(m, rng, rec["keep"])
        if fam == "w_nocamps":
            for t in [t for t, _ in m.groups]:
                NF.remove_group(m, t)
            m.camp.clear()
        else:
            for p in [p for p, t in m.camp.items() if t == GEM]:
                m.camp[p] = GOLD  # a wolf group's bonus cluster: only the pockets hold gems
        if fam == "w_cryststarve" and _crystal_pockets(m, rng, rec["npocket"]) < rec["npocket"]:
            raise RuntimeError("no room for the pockets")
        return m
    if fam in CUSTOM2:
        m = CUSTOM2[fam](rec, seed, rng)
        ok, info = G.validate(m, dict(rec, kind="nf", checks=2))
        if not ok:
            raise RuntimeError(f"validate: {str(info)[:80]}")
        return m
    if fam == "w_centralmono":
        m = NF.b_hoard(rec, seed)
        hoard = next(t for t, k in m.groups if k == "hoard")
        for p in set(hoard) | {m.mir(*q) for q in hoard}:
            m.camp[p] = MONO
    elif fam == "w_bushmaze":
        m = NF.gen_maze(rec, seed)
        _bushfill(m, rng, rec["bushf"])
    elif fam == "w_hugefew":
        m = NF.b_normal(rec, seed)
        NF.thin_groups(m, rng, rec["keep"] // 2)
    elif fam in ("w_altpocket", "w_fan", "w_starve"):
        m = NF.b_altfar(rec, seed)
        if fam == "w_altpocket" and rec["pocket"] and not _pocket(m, rng):
            raise RuntimeError("no room for an altar pocket")
        if fam == "w_starve":
            NF.thin_groups(m, rng, rec["keep"])
        if fam == "w_fan":
            G.place_groups(m, rng, "w_wolves", max(0, rec["nwolf"] - len(m.groups)), True, strict=True)
    else:
        m = G.generate(rec, seed)
        if fam == "w_spawnmono" and not _spawnmono(m, rec, rng):
            raise RuntimeError("no room for a spawn monolith group")
        if fam == "w_multimono" and not _multimono(m, rec, rng):
            raise RuntimeError("no room for a monolith group")
        if fam == "w_farspawn":
            _farspawn(m, rng, rec)
        if fam == "w_nobush":
            for i, v in enumerate(m.g):
                if v == BUSH:
                    m.g[i] = FLOOR
    ok, info = G.validate(m, dict(rec, kind="nf", checks=2))
    if not ok:
        raise RuntimeError(f"validate: {str(info)[:80]}")
    return m


def _m_midgems(rec, seed, rng):
    m = G.generate(rec, seed)
    dA, dB = m.bfs("A"), m.bfs("B")

    def mid(x, y):
        a, b = dA.get((x, y)), dB.get((x, y))
        return a is not None and b is not None and m.dspawn(x, y) >= 4 and 0.42 <= a / max(1, a + b) <= 0.58
    if _ring_place(m, rng, "nf_gem", rec["ngem"], mid) < 2:
        raise RuntimeError("no contested room for gems")
    return m


def _m_seencarry(rec, seed, rng):
    m = _m_midgems(rec, seed, rng)
    for i, v in enumerate(m.g):
        if v == BUSH:
            m.g[i] = FLOOR
    return m


SC_HP = {WOLF: 1350, ELK: 2400, GEM: 120, GOLD: 120, MONO: 20000, GOLEM: 5000}  # GameRules camp table (smallc_scan.py's numbers)
SC_GEMS = {WOLF: 4, ELK: 15, GEM: 7, GOLD: 0, MONO: 200, GOLEM: 36}
SC_RSP = {WOLF: 40, ELK: 60, GEM: 50, GOLD: 50, MONO: 150, GOLEM: 80}
SC_COMP = {"elk2": (ELK, 1), "wolf2": (WOLF, 1), "wolf4": (WOLF, 2)}  # guard type, mirrored pairs of it
G.MIXES.setdefault("w_goldonly", {"gold_row": 3, "gold_patch": 3, "gold1": 2})


SC_GAP = 4  # v4: every other group is at least this much farther from a spawn than C


def _sc_walk(d, tiles):
    """walk from the spawn of distance field d to beside any of tiles"""
    return min((d[(a + dx, b + dy)] for a, b in tiles for dx, dy in N8 + [(0, 0)] if (a + dx, b + dy) in d), default=10 ** 6)


def _m_smallc(rec, seed, rng):
    """w_smallc: gold-only base, then one self-symmetric gem group at the centre on the spawn-to-spawn path (genfuel.place_hoards),
    with 1-2 mirrored pairs of its tiles turned into elk or wolves; top up to >= 10 gold-only groups."""
    import genfuel
    m = G.generate(rec, seed)
    for p, t in list(m.camp.items()):  # every camp outside C is a gold cluster: C holds all the gems
        if t != GOLD:
            m.camp[p] = GOLD
    genfuel.place_hoards(m, rng, 1, rec["csize"])  # raises when there is no room
    hoard = next(t for t, k in m.groups if k == "hoard")
    S = set(hoard) | {m.mir(*p) for p in hoard}
    pairs = sorted({tuple(sorted((p, m.mir(*p)))) for p in S if m.mir(*p) != p})
    order = [rec["heavy"]] if rec.get("strict_heavy") else [rec["heavy"]] + [k for k in ("elk2", "wolf2", "wolf4") if k != rec["heavy"]]
    for comp in order:
        gt, npair = SC_COMP[comp]
        if len(pairs) < npair + 1 or SC_HP[gt] * 2 * npair + SC_HP[GEM] * (len(S) - 2 * npair) > 6000:
            continue
        for a, b in rng.sample(pairs, npair):
            m.camp[a] = m.camp[b] = gt
        break
    else:
        raise RuntimeError(f"centre of {len(S)} camps fits no guard mix under 6,000 HP")
    gold_groups = sum(1 for g in NF.groups_of(m.camp) if all(m.camp[p] == GOLD for p in g))
    if gold_groups < 10:
        G.place_groups(m, rng, "w_goldonly", (10 - gold_groups + 1) // 2 + 1, True, strict=True)
    if rec.get("strict_heavy"):  # v4 (Econ SCC, 10 Nov): C is the nearest group to each spawn, as on 01elk_arena (gold sat between spawn and
        # C on v3's slow maps): drop every other group whose walk from a spawn is under C's + SC_GAP, then top up gold farther out
        for _ in range(3):
            dA = m.bfs("A")
            wc = _sc_walk(dA, S)
            near = [t for t, k in m.groups if k != "hoard" and _sc_walk(dA, set(t) | {m.mir(*p) for p in t}) < wc + SC_GAP]
            for t in near:
                NF.remove_group(m, t)
            ng = sum(1 for g in NF.groups_of(m.camp) if all(m.camp[p] == GOLD for p in g))
            if ng >= 10 and not near:
                break
            if ng < 10:
                G.place_groups(m, rng, "w_goldonly", (10 - ng + 1) // 2 + 2, True, strict=True)
    gold = [t for t, k in m.groups if k != "hoard" and all(m.camp.get(p) == GOLD for p in t)]
    rng.shuffle(gold)
    while gold and sum(1 for g in NF.groups_of(m.camp) if all(m.camp[p] == GOLD for p in g)) > 18:  # v2: 10-18 (the saved class: 10-16)
        NF.remove_group(m, gold.pop())
    return m


def _m_inverted(rec, seed, rng):
    m = G.generate(rec, seed)
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    sx, sy = (m.spawn[0] + m.spawn[2]) / 2, (m.spawn[1] + m.spawn[3]) / 2
    if max(abs(sx - cx) / m.W, abs(sy - cy) / m.H) > 0.25:
        raise RuntimeError("spawns not central")
    NF.drop_all_groups(m)
    lim = 0.32 * min(m.W, m.H)
    far = lambda x, y: max(abs(x - cx), abs(y - cy)) >= lim and m.dspawn(x, y) >= 6  # noqa: E731
    if _ring_place(m, rng, rec["mix"], NF.n_side_of(m, rng), far) < 4:
        raise RuntimeError("edge groups short")
    return m


def _m_thin(rec, seed, rng):
    return G.generate(rec, seed)


def _m_holefield(rec, seed, rng):
    m = G.generate(rec, seed)
    b = rec["blk"]
    near = {(x + dx, y + dy) for (x, y) in list(m.camp) + list(m.altars) for dx, dy in N8 + [(0, 0)]}
    for y in range(m.H):
        for x in range(m.W):
            if ((x // b + y // b) % 2 == 0 and m.get(x, y) in (FLOOR, BUSH) and (x, y) not in near
                    and m.mir(x, y) not in near and (x, y) not in m.protect and m.dspawn(x, y) > 2):
                m.put(x, y, G.HOLE)
    G.repair(m, rng, True)
    return m


def _m_homealtar(rec, seed, rng):
    m = G.generate(rec, seed)
    for _ in range(3):
        for t in _near_groups(m, 20):
            NF.remove_group(m, t)
        if len(m.groups) >= 4:
            break
        G.place_groups(m, rng, rec["mix"], 6, True, zone_w=(0.0, 0.4, 0.6), strict=True)
    for t in _near_groups(m, 20):
        NF.remove_group(m, t)
    return m


def _m_centralblob(rec, seed, rng):
    m = NF.b_hoard(rec, seed)
    for t, k in list(m.groups):
        if k != "hoard" and any(m.camp.get(p) != GOLD for p in t):
            NF.remove_group(m, t)
    return m


def _m_splitlane(rec, seed, rng):
    m = NF.b_block(rec, seed)
    for t, k in list(m.groups):
        if k == "plug":
            NF.remove_group(m, t)
    return m


def _m_bushaltar(rec, seed, rng):
    m = G.generate(rec, seed)
    r = rec["ring"]
    for ax, ay in list(m.altars):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                x, y = ax + dx, ay + dy
                if m.inb(x, y) and m.get(x, y) == FLOOR and (x, y) not in m.camp and m.mir(x, y) not in m.camp and m.dspawn(x, y) > 0:
                    m.put(x, y, BUSH)
    return m


def _m_wardstarve(rec, seed, rng):
    m = NF.gen_maze(rec, seed)
    _bushfill(m, rng, rec["bushf"])
    return m


def _m_thinned(rec, seed, rng):
    m = G.generate(rec, seed)
    NF.thin_groups(m, rng, rec["keep"])
    return m


def _m_altarstarve(rec, seed, rng):
    return NF.b_altfar(rec, seed)


def _m_bushcamp(rec, seed, rng):
    """w_bushcamp (BWT): a normal map, then in nhide small camp groups (<= 3 camps, mirrored pairs) one member's tile becomes BUSH and every
    free (non-camp) bush tile beside it becomes FLOOR, so that member's cardinal bush cluster holds only camp tiles (tools/lab/mapclass.d/hidmem.py)."""
    m = G.generate(rec, seed)
    small = [g for g in NF.groups_of(m.camp) if 2 <= len(g) <= 3 and all(m.camp[p] in (WOLF, GEM, GOLD, ELK) for p in g)]
    rng.shuffle(small)
    done, used = 0, set()
    for g in small:
        if done >= rec.get("nhide", 4):
            break
        p = rng.choice(sorted(g))
        q = m.mir(*p)
        if p in used or q in used or m.dspawn(*p) <= 0:
            continue
        for t in {p, q}:
            m.put(t[0], t[1], BUSH)
            for dx, dy in N4:
                n = (t[0] + dx, t[1] + dy)
                if m.inb(*n) and m.get(*n) == BUSH and n not in m.camp:
                    m.put(n[0], n[1], FLOOR)
                    nm = m.mir(*n)
                    if m.inb(*nm) and m.get(*nm) == BUSH and nm not in m.camp:
                        m.put(nm[0], nm[1], FLOOR)
        used |= {p, q}
        done += 1
    if not done:
        raise RuntimeError("no small camp group to hide a member in")
    return m


def _m_onealtar(rec, seed, rng):
    """One altar tile on the mirror axis (put() leaves a self-mirror tile single), most contested first; then bush at Chebyshev bushr from it."""
    m = G.generate(rec, seed)
    for x, y in m.altars:
        m.put(x, y, FLOOR)
    m.altars = []
    cand = [c for c in G.altar_candidates(m) if m.mir(c[0], c[1]) == (c[0], c[1]) and c[3] is not None
            and not any((c[0] + dx, c[1] + dy) in m.camp for dx, dy in N8 + [(0, 0)])]
    cand.sort(key=lambda c: abs(c[4] - 0.5))
    for c in cand[:30]:
        m.put(c[0], c[1], ALTAR)
        m.altars = [(c[0], c[1])]
        if G.access_ok(m, True, True):
            lo, hi = rec["bushr"]
            for x in range(m.W):
                for y in range(m.H):
                    d = max(abs(x - c[0]), abs(y - c[1]))
                    if lo <= d <= hi and m.get(x, y) == FLOOR and (x, y) not in m.protect and rng.random() < rec["bushp"]:
                        m.put(x, y, BUSH)
            return m
        m.put(c[0], c[1], FLOOR)
        m.altars = []
    raise RuntimeError("no axis tile for the altar")


def _sgap(m):
    """Spawn-rect gap: min Chebyshev from a team A spawn tile to B's rect (1 = touching, 2 = one tile between; 0 = overlap)."""
    r, rb = m.rectA(), m.rectB()
    return min(m.cheb_rect(rb, x, y) for x in range(r[0], r[2]) for y in range(r[1], r[3]))


def _adj_spawn(want):
    """genmaps.place_spawn for w_spawnadj: every A rect in the central window (genmaps' 'short' window, both axes) whose mirror
    sits 1-3 away; the gap nearest want (mirror parity can rule a gap out: sym 0 on an odd-width board has only 2)."""
    def place(m, rng, mode, sw, sh):
        W, H = m.W, m.H
        cand = {}
        for x0 in range(max(0, W // 2 - sw - 4), min(W - sw, W // 2 + 3) + 1):
            for y0 in range(max(0, H // 2 - sh - 4), min(H - sh, H // 2 + 3) + 1):
                m.spawn = (x0, y0, x0 + sw, y0 + sh)
                g = _sgap(m)
                if 1 <= g <= 3:
                    cand.setdefault(g, []).append(m.spawn)
        if not cand:
            raise RuntimeError("no adjacent spawn")
        m.spawn = rng.choice(cand[min(cand, key=lambda k: (abs(k - want), k))])
        return m.spawn
    return place


def _cup_tiles(m, fext, lext):
    """Team A's cup (put() mirrors it into B's): the Chebyshev-1 ring round A's rect minus the inner tiles of the side facing
    away from B (the exit), the two flanks run on fext tiles past the exit, the side facing B (the line between the spawns)
    run on lext tiles past both flanks. Tiles in B's rect (gap 1) are left out."""
    r, rb = m.rectA(), m.rectB()
    sepx = max(rb[0] - r[2], r[0] - rb[2])
    sepy = max(rb[1] - r[3], r[1] - rb[3])
    if sepx >= sepy:  # (u, v) = (along the A -> B axis, across it)
        xy, u0, u1, v0, v1, d = (lambda u, v: (u, v)), r[0], r[2], r[1], r[3], 1 if rb[0] >= r[2] else -1
    else:
        xy, u0, u1, v0, v1, d = (lambda u, v: (v, u)), r[1], r[3], r[0], r[2], 1 if rb[1] >= r[3] else -1
    ue, ub = (u0 - 1, u1) if d > 0 else (u1, u0 - 1)  # exit side, side facing B
    out = [(u, v) for u in range(u0 - 1, u1 + 1) for v in range(v0 - 1, v1 + 1)
           if (u in (u0 - 1, u1) or v in (v0 - 1, v1)) and not (u == ue and v0 <= v < v1)]
    out += [(ue - d * k, v) for k in range(1, fext + 1) for v in (v0 - 1, v1)]
    out += [(ub, v) for k in range(1, lext + 1) for v in (v0 - 1 - k, v1 + k)]
    tiles = []
    for u, v in out:
        x, y = xy(u, v)
        if m.inb(x, y) and m.cheb_rect(rb, x, y) > 0:
            tiles.append((x, y))
    return tiles


def _m_spawnadj(rec, seed, rng):
    """genmaps.generate with place_spawn swapped for _adj_spawn and, on cup draws, clear_spawn followed by the protected cup,
    so terrain repair, altars and camps all respect it. Both swaps are undone before returning (genmaps stays as it was)."""
    tiles = []

    def clear(m):
        _G_CLEAR(m)
        if rec.get("cup"):
            v = WALL if rec["cup"] == "wall" else G.HOLE
            tiles[:] = _cup_tiles(m, rec.get("fext", 0), rec.get("lext", 0))
            for x, y in tiles:
                m.put(x, y, v)
                m.prot(x, y)
    G.place_spawn, G.clear_spawn = _adj_spawn(rec["gap"]), clear
    try:
        m = G.generate(rec, seed)
    finally:
        G.place_spawn, G.clear_spawn = _G_PLACE, _G_CLEAR
    if any(m.get(x, y) not in (WALL, G.HOLE) for x, y in tiles):
        raise RuntimeError("cup opened")
    return m


_G_PLACE, _G_CLEAR = G.place_spawn, G.clear_spawn


CUSTOM2 = {"w_midgems": _m_midgems, "w_seencarry": _m_seencarry, "w_smallc": _m_smallc, "w_smallc_wide": _m_smallc, "w_inverted": _m_inverted, "w_thin": _m_thin, "w_holefield": _m_holefield,
           "w_homealtar": _m_homealtar, "w_centralblob": _m_centralblob, "w_5v5tiny": _m_thin, "w_goldrich": _m_thin,
           "w_splitlane": _m_splitlane, "w_bushaltar": _m_bushaltar, "w_goldstarve": _m_thin, "w_wardstarve": _m_wardstarve,
           "w_altarstarve": _m_altarstarve, "w_campstarve": _m_thinned, "w_heavystarve": _m_thinned, "w_timestarve": _m_thin,
           "w_spawnadj": _m_spawnadj, "w_onealtar": _m_onealtar, "w_bushcamp": _m_bushcamp}


# ---------------------------------------------------------------- family checks on the built map
def check(fam, m, f, x):
    """None = the built map has the family's property, else the reason it is rejected."""
    if len(G.spec_of(m)["camps"]) > 255:
        return "too many camps (u8 count)"
    if f["s2s"] is None and fam != "w_nointer":  # 11 Nov: w_nointer's halves never meet on purpose (gencruel checks it)
        return "spawns not connected"
    if fam != "w_dashaltar" and not isinstance(f["alt_d"], int):
        return "no walkable altar"
    types = set(m.camp.values())
    if fam in gencruel.CHECKS:
        return gencruel.check(fam, m, f, x)
    if fam == "w_bushcamp":  # at least one camp member whose cardinal bush cluster holds only camp tiles
        bush = {(x, y) for x in range(m.W) for y in range(m.H) if m.get(x, y) == BUSH}
        for p in m.camp:
            if p in bush:
                seen, st, ok = {p}, [p], True
                while st and ok:
                    c = st.pop()
                    for dx, dy in N4:
                        n = (c[0] + dx, c[1] + dy)
                        if n in bush and n not in seen:
                            if n not in m.camp:
                                ok = False
                                break
                            seen.add(n)
                            st.append(n)
                if ok:
                    return None
        return "no hidden camp member"
    if fam == "w_onealtar":
        alt = [(x, y) for x in range(m.W) for y in range(m.H) if m.get(x, y) == ALTAR]
        return None if len(alt) == 1 and m.mir(*alt[0]) == alt[0] else f"{len(alt)} altar tiles"
    if fam == "w_nocamps":
        return None if not m.camp and f["gems"] == 0 and f["gold"] == 0 else "camps left"
    if fam == "w_nogems":
        return None if f["gems"] == 0 and f["gold"] > 0 else f"gems {f['gems']} gold {f['gold']}"
    if fam == "w_cryststarve":
        return None if 10 <= f["gems"] <= 84 and f["cry"] == 1 and f["gold"] > 0 else f"gems {f['gems']} cry {f['cry']} gold {f['gold']}"
    if fam == "w_multimono" and not any(sum(1 for p in grp if m.camp.get(p) == MONO) >= 2 for grp in NF.groups_of(m.camp)):
        return "no group of 2+ monoliths"
    reach = f["gems"] * (1 - f["none"] - f["cry"])
    if fam == "w_starve":
        ng = len(NF.groups_of(m.camp))
        return None if 4 <= ng <= 8 and 10 <= reach and f["gems"] <= 80 and f["alt"] <= 2 else f"starve: {ng} groups {f['gems']} gems"
    if reach < (10 if fam in ("w_campstarve", "w_heavystarve") else 20 if fam in ("w_tiny", "w_goldrich", "w_5v5tiny") else 40):
        return f"reachable gems {reach:.0f}"
    dA = m.bfs("A") if fam in ("w_twisty", "w_farspawn", "w_altpocket", "w_homealtar", "w_midgems", "w_seencarry") else None
    ng = len(NF.groups_of(m.camp))
    if fam in CHECK2:
        why = CHECK2[fam](m, f, x, types, dA, ng)
        return None if why is None else why
    if fam == "w_spawnmono":
        near = [p for p, t in m.camp.items() if t == MONO and 1 <= m.dspawn(*p) <= 3]
        return None if types <= {GOLD, MONO} and len(near) >= 4 else "not gold + spawn monoliths"
    if fam == "w_heavygems":
        return None if types <= {GOLD, GOLEM, MONO} and (types & {GOLEM, MONO}) else "gems outside heavy camps"
    if fam == "w_centralmono":
        cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
        central = [p for p, t in m.camp.items() if t == MONO and abs(p[0] - cx) <= m.W / 4 and abs(p[1] - cy) <= m.H / 4]
        return None if len(central) >= 6 else "no central monolith field"
    if fam == "w_tiny":
        return None if m.W <= 32 and m.H <= 32 else "not tiny"
    if fam == "w_hugefew":
        gs = NF.groups_of(m.camp)
        if not (m.W >= 80 and 10 <= len(gs) <= 16):
            return f"groups {len(gs)} on {m.W}x{m.H}"
        nn = [min(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for o in gs if o is not g for a in g for b in o) for g in gs]
        return None if statistics.median(nn) >= 10 else "groups not far apart"
    if fam == "w_twisty":
        if (x["wind"] or 0) < 3:
            return f"wind {x['wind']}"
        ad = min(((_gwalk(dA, [p]) or 10 ** 6) / max(1, m.cheb_rect(m.rectA(), *p))) for p in m.altars)
        if ad < 2.5:
            return f"altar walk {ad:.1f}x"
        gr = [(_gwalk(dA, t) or 10 ** 6) / max(1, min(m.cheb_rect(m.rectA(), *p) for p in t)) for t in NF.groups_of(m.camp)]
        return None if gr and statistics.median(gr) >= 2 else "group walks short"
    if fam == "w_farspawn":
        near = min((_gwalk(dA, [p]) or 10 ** 6) for p in m.camp) if m.camp else 0
        return None if near >= 40 and len(NF.groups_of(m.camp)) >= 8 else f"nearest camp walk {near}"
    if fam == "w_altpocket":
        if f["alt"] > 2:
            return f"altars {f['alt']}"
        ax, ay = min(m.altars, key=lambda p: m.cheb_rect(m.rectA(), *p))
        w = _gwalk(dA, [(ax, ay)]) or 10 ** 6
        return None if w >= m.cheb_rect(m.rectA(), ax, ay) + 6 or f["alt_d"] >= max(15, 0.5 * f["s2s"]) else "altar not pocketed/far"
    if fam == "w_hoardtiny":
        return None if x["maxg"] >= 15 else f"hoard {x['maxg']} camps"
    if fam == "w_bushmaze":
        return None if f["bush"] >= 25 and x["nbr"] <= 5.6 else f"bush {f['bush']}% nbr {x['nbr']}"
    if fam == "w_nobush":
        return None if f["bush"] == 0 else "bush left"
    if fam == "w_bushall":
        return None if f["bush"] >= 45 else f"bush {f['bush']}%"
    if fam == "w_contact":
        return None if f["s2s"] <= 10 else f"s2s {f['s2s']}"
    if fam == "w_altmany":
        return None if f["alt"] >= 8 else f"altars {f['alt']}"
    if fam == "w_fan":
        return None if types == {WOLF} and len(NF.groups_of(m.camp)) >= 24 and f["alt"] <= 2 else "not a wolf fan"
    return None


def _ck_smallc(m, f, x, types, dA, ng, elk=False):
    """smallc_scan.py's test, tightened to the generator spec: the richest group C holds >= 90% of the gems, no golem/monolith in C,
    summed HP <= 6,000, respawn <= 60, walk from each spawn to beside C <= 15, >= 10 gold-only groups."""
    gs = NF.groups_of(m.camp)
    gems = [sum(SC_GEMS[m.camp[p]] for p in g) for g in gs]
    tot = sum(gems)
    if not tot:
        return "no gems"
    i = max(range(len(gs)), key=lambda k: gems[k])
    C = gs[i]
    if gems[i] < 0.9 * tot:
        return f"centre {gems[i]} of {tot} gems"
    if any(m.camp[p] in (GOLEM, MONO) for p in C):
        return "golem/monolith in the centre"
    hp, rsp = sum(SC_HP[m.camp[p]] for p in C), max(SC_RSP[m.camp[p]] for p in C)
    if hp > 6000 or rsp > 60 or (elk and (hp < 4500 or not any(m.camp[p] == ELK for p in C))):
        return f"centre hp {hp} respawn {rsp}"
    beside = {(a + dx, b + dy) for a, b in C for dx, dy in N8 + [(0, 0)]}
    for team in ("A", "B"):
        d = m.bfs(team)
        w = min((d[q] for q in beside if q in d), default=10 ** 6)
        if not ((6 if elk else 5) <= w <= (11 if elk else 15)):
            return f"walk {team} {w}"
    if elk:  # v4: C is the nearest group to each spawn by SC_GAP (gold between spawn and C made v3's centres slow)
        for team in ("A", "B"):
            d = m.bfs(team)
            wc = _sc_walk(d, C)
            other = min((_sc_walk(d, g) for g in gs if g is not C), default=10 ** 6)
            if other < wc + SC_GAP:
                return f"group {other} from spawn {team} v C {wc}"
    if elk:  # C on the direct line: some tile beside C lies on a shortest spawn-to-spawn walk (within 2 of it)
        dA, dB = m.bfs("A"), m.bfs("B")
        s2s = min((dA[q] for q in dA if m.cheb_rect(m.rectB(), *q) <= 1), default=None)
        if s2s is None or not any(q in dA and q in dB and dA[q] + dB[q] <= s2s + 2 for q in beside):
            return "centre off the spawn-to-spawn line"
    ngold = sum(1 for k, g in enumerate(gs) if gems[k] == 0 and all(m.camp[p] == GOLD for p in g))
    return None if 10 <= ngold <= 18 else f"gold-only groups {ngold}"


def _ck_midgems(m, f, x, types, dA, ng):
    dB = m.bfs("B")
    for p, t in m.camp.items():
        if t != GOLD:
            a, b = _gwalk(dA, [p]), _gwalk(dB, [p])
            if a is None or b is None or not 0.38 <= a / max(1, a + b) <= 0.62:
                return "a gem camp outside the contested zone"
    return None if types & {GEM} else "no gems"


def _ck_inverted(m, f, x, types, dA, ng):
    cx, cy = (m.W - 1) / 2, (m.H - 1) / 2
    lim = 0.3 * min(m.W, m.H)
    return None if all(max(abs(p[0] - cx), abs(p[1] - cy)) >= lim for p in m.camp) and ng >= 6 else "a camp near the centre"


CHECK2 = {
    "w_smallc": lambda m, f, x, t, d, ng: _ck_smallc(m, f, x, t, d, ng, elk=True),
    "w_smallc_wide": _ck_smallc,
    "w_midgems": _ck_midgems,
    "w_seencarry": lambda m, f, x, t, d, ng: _ck_midgems(m, f, x, t, d, ng) or (None if BUSH not in m.g else "bush left"),
    "w_inverted": _ck_inverted,
    "w_thin": lambda m, f, x, t, d, ng: (None if min(m.W, m.H) <= 34 and max(m.W, m.H) >= 90 and f["s2s"] >= 45
                                         else f"{m.W}x{m.H} s2s {f['s2s']}"),
    "w_holefield": lambda m, f, x, t, d, ng: None if f["hole"] >= 18 else f"holes {f['hole']}%",
    "w_campwall": lambda m, f, x, t, d, ng: None if x["cblk"] == "cut" else "spawns meet without the camp wall",
    "w_homealtar": lambda m, f, x, t, d, ng: (None if isinstance(f["alt_d"], int) and f["alt_d"] <= 12 and ng >= 6 and
                                               min((_gwalk(d, [p]) or 10 ** 6) for p in m.camp) >= 20 else "altar far or camps near"),
    "w_dashgolem": lambda m, f, x, t, d, ng: None,
    "w_deadend": lambda m, f, x, t, d, ng: None if x["nbr"] <= 5.6 else f"nbr {x['nbr']}",
    "w_centralblob": lambda m, f, x, t, d, ng: None if x["top"] >= 0.85 else f"blob share {x['top']}",
    "w_5v5tiny": lambda m, f, x, t, d, ng: None if f["T"] == 5 and m.W <= 30 and m.H <= 30 else "not 5v5 30x30",
    "w_goldrich": lambda m, f, x, t, d, ng: None if f["gold"] >= 8 * max(1, f["gems"]) else f"gold {f['gold']} gems {f['gems']}",
    "w_splitlane": lambda m, f, x, t, d, ng: None if x["cblk"] != "cut" else "crossings still plugged",
    "w_bushaltar": lambda m, f, x, t, d, ng: None,
    "w_microisles": lambda m, f, x, t, d, ng: None if f["dash"] + f["cry"] >= 0.12 else "islands short",
    "w_goldstarve": lambda m, f, x, t, d, ng: None if f["gold"] <= 200 else f"gold {f['gold']}",
    "w_wardstarve": lambda m, f, x, t, d, ng: None if f["bush"] >= 30 and x["nbr"] <= 5.6 else f"bush {f['bush']} nbr {x['nbr']}",
    "w_altarstarve": lambda m, f, x, t, d, ng: (None if f["alt"] <= 2 and f["alt_d"] >= max(25, 0.5 * f["s2s"])
                                                else f"altar d {f['alt_d']}"),
    "w_campstarve": lambda m, f, x, t, d, ng: None if 3 <= ng <= 5 else f"groups {ng}",
    "w_heavystarve": lambda m, f, x, t, d, ng: None if t <= {GOLEM, MONO} and 2 <= ng <= 4 else f"groups {ng} {sorted(t)}",
    "w_space": lambda m, f, x, t, d, ng: None if f["wall"] + f["hole"] >= 55 else f"walls {f['wall'] + f['hole']}%",
    "w_timestarve": lambda m, f, x, t, d, ng: None if t <= {GOLEM, MONO} else "non-heavy camps",
    "w_spawnadj": lambda m, f, x, t, d, ng: None if 1 <= _sgap(m) <= 3 else f"spawn gap {_sgap(m)}",
}


def build_one(fam, name, seed, rec, outdir):
    """-> (map path, features). Raises RuntimeError when the seed misses the family or the checks."""
    rec = dict(rec)
    if fam in ("w_dashaltar", "w_dashgolem"):
        import condab
        import mapcheck
        gate = rec["kind"] in G.GATE_KINDS
        mp, f = condab._otf_build(G, mapcheck, mapfeat, rec, seed, outdir, name, gen=G.generate_gate if gate else None)
        if not mp:
            raise RuntimeError(f"otf build: {f}")
        return mp, f
    if fam in NF_BASE:
        m, mp, f = NF.build_one(rec.pop("wbase"), name, seed, rec, outdir)
        why = check(fam, m, f, f)
    else:
        m = make(fam, seed, rec)
        sp, mp = os.path.join(outdir, name + ".json"), os.path.join(outdir, name + ".map26a")
        json.dump(G.spec_of(m), open(sp, "w"))
        d = G.build_and_check(m, sp, mp)
        f = mapfeat.analyse(d, name)
        x = NF.extfeat(d)
        why = check(fam, m, f, x)
        f = dict(f, **x)
    if why:
        raise RuntimeError("built map: " + why)
    return mp, f


if __name__ == "__main__":  # smoke test: N maps per family into a scratch dir -> hit rate and seconds
    import time
    if any(a.startswith("-") for a in sys.argv[1:]):  # 3 Nov: '--help' was taken as OUTDIR (a self-test into ./--help)
        print(__doc__)
        sys.exit(0 if set(sys.argv[1:]) & {"-h", "--help"} else 2)
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/genweird_smoke"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    fams = sys.argv[3].split(",") if len(sys.argv) > 3 else FAMS
    os.makedirs(out, exist_ok=True)
    for fam in fams:
        ok, tries, t0, why = 0, 0, time.time(), {}
        for i in range(n):
            for a in range(10):
                tries += 1
                seed = int.from_bytes(os.urandom(6), "big")
                try:
                    build_one(fam, f"{fam}_{i}", seed, recipe(fam, random.Random(seed)), out)
                    ok += 1
                    break
                except Exception as e:  # noqa: BLE001
                    k = str(e)[:60]
                    why[k] = why.get(k, 0) + 1
        top = sorted(why.items(), key=lambda kv: -kv[1])[:2]
        print(f"{fam:14s} {ok}/{n} in {tries} tries {time.time() - t0:.0f}s {top}", flush=True)
