#!/usr/bin/env python3
"""stratmaps: N NEW maps, stratified across map kinds, for one test run (never saved to the pool). Tool builder, 1 Nov (owner:
"local testing must use newly randomly generated maps of different kinds").

usage: python3 -I tools/lab/stratmaps.py DIR [--n 300] [--jobs 8] [--weird 0.5] [--wfams w_a,w_b]   (--weird 1: genweird families only;
       --wfams: only these genweird families)
       python3 -I tools/lab/stratmaps.py DIR --n N --take [--who NAME]: take unseen pre-generated sets from tools/lab/freshpool.py's
       pool (single use, logged), else generate here as above
Writes DIR/<name>.map26a and DIR/otf.json in condab's OTF format (OTF_DIR=DIR plays them: copied into the batch, never installed
or indexed), plus the kind labels of every map. Seeds come from os.urandom, so every run gets different maps; each map's seed and
recipe are logged in otf.json (rebuild one: condab.py --otf-regen SEED 'RECIPE' OUT.map26a).
Families (shares of N): normal 28% (genmaps SCHED columns, each a balanced shuffled list, so every level of team size, size,
spawn distance, altar placement, terrain style and camp mix gets its share), bank2-like 20% (the same, sizes S:M:L 1:2:4 and spawns
short:medium:long 1:2:3 as mapbank2's ladder-matched bank), gated 10% (genmaps GATE_KINDS), long 7% (genmaps LONG), patho 5%,
nf 26% (1 Nov, owner: "randomly generate but not save them"): the map generator's 18 tools/lab/genfam.py families (vault isle
road corr heavy mgate gemonly goldonly huge brawl bush crystal zone skew hoard altmany altfar block), evenly, each a genfam
recipe + build_one with os.urandom seeds in this run's work dir (never installed; the gen_nf_* stock maps are not used),
weird 50% (1 Nov, owner: "design weirder maps", "think of more pathological maps", after the 03fan/03twisty/03homonoliths
tournament): tools/lab/genweird.py's 22 families evenly (spawn monoliths, heavy-only gems, gem-only, central monolith field,
dash/ring altars, road pockets, bush mazes, 30x30 boards, huge boards, islands, huge few-group boards, twisty mazes, 1-wide chokes,
far spawns, pocketed altars, elk/golem only, giant hoard + tiny groups, no bush, bush everywhere, instant contact, 8+ altars,
wolf fans, ...; owner 1 Nov ~19:30: "half pathological, half normal"). The other shares are scaled by 0.50 (normal 14,
bank2 10, gate 5, long 3.5, patho 2.5, nf 15).
manygrp 6% (11 Nov, RC X306: pool and BIG top out at 64 camp groups, ladder 04gem-caverns has 114; the v712 TSO1 fuel regression
hid there): gencruel's w_manygrp (ladder-shaped boards with 65-130 camp groups), taken proportionally from every share above
(weird 47, normal 13.2, bank2 9.4, gate 4.7, long 3.3, patho 2.35, nf 14.1). Env STRAT_MANYGRP_SHARE (default 0.06; 0 = off, the
old mix) sets it; it applies only without --wfams (an explicit family list is used as given), counts as pool 'weird' in the labels,
and the pilot farm passes it on to the nodes.
Kind labels (measured with mapfeat where the map decides, else the recipe):
  fam   normal / bank2 / gate / long / patho / nf_<genfam family> / w_<genweird family>   team  T3 / T4 / T5
  area  S (<= 1600 tiles) / M (<= 3000) / L          spawn close (s2s <= 35) / mid / far (> 56)
  altar one (<= 2 altar tiles) / multi / gated        terrain holes (hole share >= 15%) / corridor (corridors, maze) / open / mixed
  econ  gem-only (no gold) / gold-heavy (gold_rich) / heavy-camp (golems, elk_heavy) / gem-poor / balanced
  pool  weird (genweird families: ~300 of a 600-map draw; the per-kind z check covers them pooled, and each family with >= 10 maps) / std
A map that fails generation or the checks after 40 seeds is dropped and logged.
Class filter (10 Nov, Planner: heavy-class reads): --class 'heavy_ge:>=0.5' (NAME:OPvalue, OP >= > <= <, comma = all must hold;
classes in tools/lab/mapclass.py and tools/lab/mapclass.d/: heavy_ge2 (Econ's current heavy class), heavy_ge (v1), mono_share, ...) runs rounds of the usual path (pool / here / pilots, same options)
into DIR/.cls/rK, about N / hit-rate maps a round, keeps the maps that pass until N, caps the tries (--class-max, default 25 x N maps,
8 rounds) and reports the hit rate and any shortfall (exit 1 when short; otf.json holds what passed). Each kept map's otf.json entry
gets "class": {NAME: value}; --class-tag NAME[,NAME] adds values for every map (with or without --class). Without either option the
output is unchanged."""
import argparse
import json
import multiprocessing
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WEIRD = 0.50  # genweird share (owner 1 Nov ~19:30: "half pathological, half normal"; was 0.15); the six older shares keep their
#                ratios in the remaining 0.50
BASE_SHARES = (("normal", 0.28), ("bank2", 0.20), ("gate", 0.10), ("long", 0.07), ("patho", 0.05), ("nf", 0.30))


def shares(weird=WEIRD):
    return tuple((f, s * (1 - weird)) for f, s in BASE_SHARES) + (("weird", weird),)


MANYGRP = float(os.environ.get("STRAT_MANYGRP_SHARE", 0.06))  # 11 Nov (RC X306): gencruel w_manygrp share, from every other share


BUSHROUTES = float(os.environ.get("STRAT_BUSHROUTES_SHARE", 0.08))  # 11 Nov (owner: "a lot of bushy maps, especially on key routes or hotspots")
RICHCENTRE = float(os.environ.get("STRAT_RICHCENTRE_SHARE", 0.04))  # 11 Nov (owner: "resource heavy centred maps ... contested")
COLS = float(os.environ.get("STRAT_COL_SHARE", 0.01))  # 12 Nov (Aggression, owner: long capture standoff; tournament 05 shape): w_goldcol, w_gemcol each
HMS = float(os.environ.get("STRAT_HMS_SHARE", 0.02))  # 11 Nov (Builder: DGR/HFT rare lines need hms-class maps, owner never-burn-out; the rare
ELKCTR = float(os.environ.get("STRAT_ELK_SHARE", 0.01))  # 12 Nov (b2112 ELK, class-only rare line elk5: its bank harvests w_elkctr from the fresh mix)
GOLDRING = float(os.environ.get("STRAT_GOLDRING_SHARE", 0.01))  # 12 Nov (Coordinator: GOP A collapse class, grc1 maps like the ladder's 03colosseum/04sanctum): w_goldring1 slice so a gop rare bank can fill
CAMPRING = float(os.environ.get("STRAT_CAMPRING_SHARE", 0.01))  # 12 Nov (Builder, GSX bit 32 / econ_ring.cc ring_map_sealed): w_campring (spawn sealed by camps) slice for its rare bank
JACKPOT2 = float(os.environ.get("STRAT_JACKPOT2_SHARE", 0.02))  # 12 Nov (Builder: JKC fuel re-read jkc3, w_jackpot2 && !siege_map; 2%: only ~38% of generated w_jackpot2 pass open_gem_share >= .15)
JACKPOT = float(os.environ.get("STRAT_JACKPOT_SHARE", 0.02))  # 12 Nov (Builder/Planner: w_jackpot is the same JKC cell; 16/24 pass open_gem_share >= .15)
MONOTANK = float(os.environ.get("STRAT_MONOTANK_SHARE", 0.01))  # 12 Nov (Builder: srj1 bug-bar rare line, spawnecon class 0/2,044 plain fresh; monotank 11/12, monocorner 6/12)
MONOCORNER = float(os.environ.get("STRAT_MONOCORNER_SHARE", 0.01))
# bank collects only from common fresh sets, so a gencruel family outside the mix could never fill one): w_hms 255-440 groups
EXTRA = (("manygrp", "w_manygrp", MANYGRP), ("bushroutes", "w_bushroutes", BUSHROUTES), ("richcentre", "w_richcentre", RICHCENTRE),
         ("hms", "w_hms", HMS), ("goldcol", "w_goldcol", COLS), ("gemcol", "w_gemcol", COLS), ("elkctr", "w_elkctr", ELKCTR), ("goldring", "w_goldring1", GOLDRING), ("campring", "w_campring", CAMPRING), ("jackpot2", "w_jackpot2", JACKPOT2), ("jackpot", "w_jackpot", JACKPOT), ("monotank", "w_monotank", MONOTANK), ("monocorner", "w_monocorner", MONOCORNER))
# 12 Nov ~04:5xZ (Planner: bank-feeding slices must not bias fresh-led reads; the bars were calibrated before them): the slices that exist
# only to fill rare banks (hms, goldcol, gemcol, elkctr, goldring, campring, jackpot2, jackpot) are scaled together to at most
# STRAT_BANK_CAP (5%) of a fresh set; manygrp / bushroutes / richcentre (11 Nov, before the calibration) stay as set. Before this: 11%.
BANK_ONLY = ("hms", "goldcol", "gemcol", "elkctr", "goldring", "campring", "jackpot2", "jackpot", "monotank", "monocorner")
BANK_CAP = float(os.environ.get("STRAT_BANK_CAP", 0.05))
_bt = sum(v for k, _, v in EXTRA if k in BANK_ONLY)
if _bt > BANK_CAP > 0:
    EXTRA = tuple((k, f, v * BANK_CAP / _bt if k in BANK_ONLY else v) for k, f, v in EXTRA)


def mix_shares(weird=WEIRD, wfams=None):
    """shares() plus the gencruel slices w_manygrp / w_bushroutes / w_richcentre (none with an explicit --wfams list), each taken
    proportionally from every other share."""
    ex = [] if wfams else [(k, min(max(v, 0.0), 1.0)) for k, _, v in EXTRA if v > 0]
    tot = min(sum(v for _, v in ex), 0.9)
    return tuple((f, s * (1 - tot)) for f, s in shares(weird)) + tuple(ex)


SHARES = shares()
NF_SEEDS = 8  # genfam builds are slower (vault ~45 s a try)
SEEDS = 40


def balanced(vals, n, rng):
    L = (list(vals) * (n // max(1, len(vals)) + 1))[:n]
    rng.shuffle(L)
    return L


def recipes(n, rng, weird=WEIRD, wfams=None, nfams=None):
    import genmaps as G
    import genbig
    if nfams:  # 11 Nov (b1963): only these genfam families (nf_X), evenly
        import genfam
        return [dict(genfam.recipe(f, random.Random(rng.getrandbits(64))), fam="nf_" + f, nf=f) for f in balanced(nfams, n, rng)]
    counts = {f: int(round(s * n)) for f, s in mix_shares(weird, wfams)}
    counts["weird" if weird >= 1 else "normal"] += n - sum(counts.values())
    counts["weird" if weird >= 1 else "normal"] = max(0, counts["weird" if weird >= 1 else "normal"])
    out = []
    for fam in ("normal", "bank2"):
        k = counts[fam]
        cols = {key: balanced(sorted(set(v), key=str), k, rng) for key, v in G.SCHED.items()}
        if fam == "bank2":
            cols["size"] = balanced(["S"] + ["M"] * 2 + ["L"] * 4, k, rng)
            cols["spawn"] = balanced(["short"] + ["medium"] * 2 + ["long"] * 3, k, rng)
        out += [dict({key: cols[key][i] for key in G.SCHED}, kind="normal", checks=2, fam=fam) for i in range(k)]
    g = {key: balanced(sorted(set(v), key=str), counts["gate"], rng) for key, v in G.SCHED.items()}
    gk = balanced(G.GATE_KINDS, counts["gate"], rng)
    for i in range(counts["gate"]):
        rec = dict({key: g[key][i] for key in G.SCHED}, kind=gk[i], checks=2, fam="gate")
        if rec["mix"] == "gem_poor":
            rec["mix"] = "balanced"
        out.append(rec)
    out += [dict(G.LONG[i % len(G.LONG)], checks=2, fam="long") for i in range(counts["long"])]
    pr = genbig.patho_recipes(100)
    out += [dict(pr[rng.randrange(len(pr))], checks=2, fam="patho") for _ in range(counts["patho"])]
    import genfam  # owner 1 Nov ("randomly generate but not save them"): the map generator's 18 families, per run, unsaved
    for f in balanced(genfam.FAMS, counts["nf"], rng):
        out.append(dict(genfam.recipe(f, random.Random(rng.getrandbits(64))), fam="nf_" + f, nf=f))
    import genweird
    for f in balanced(wfams or genweird.FAMS, counts["weird"], rng):
        out.append(dict(genweird.recipe(f, random.Random(rng.getrandbits(64))), fam=f, weird=f))
    for key, fam, _ in EXTRA:  # 11 Nov: gencruel slices, built by genweird.build_one like any opt-in gencruel family
        for _ in range(counts.get(key, 0)):
            out.append(dict(genweird.recipe(fam, random.Random(rng.getrandbits(64))), fam=fam, weird=fam))
    rng.shuffle(out)
    return out


def labels(rec, f):
    area = f.get("W", 0) * f.get("H", 0)
    s2s = f.get("s2s") or 0
    gated = rec["kind"] in ("ring_camps", "ring_gates", "adj_gate") or rec.get("altar") == "gated" or rec.get("nf") in ("mgate", "block")
    st = rec.get("style")
    hole = f.get("hole") or 0
    mix = rec.get("mix")
    econ = ("gem-only" if not f.get("gold") else "gold-heavy" if mix == "gold_rich" else
            "heavy-camp" if mix in ("golems", "elk_heavy") else
            "gem-poor" if mix == "gem_poor" else "balanced")
    return dict(fam=rec["fam"], team=f"T{f.get('T') or rec.get('T')}", area="S" if area <= 1600 else "M" if area <= 3000 else "L",
                spawn="close" if s2s <= 35 else "far" if s2s > 56 else "mid",
                altar="gated" if gated else "one" if (f.get("alt") or 0) <= 2 else "multi",
                terrain="holes" if hole >= 15 or st == "holes" else "corridor" if st in ("corridors", "maze") else
                "open" if st == "open" else "mixed", econ=econ, pool="weird" if rec["fam"].startswith("w_") else "std")


def build(job):
    i, rec, work, name = job
    import condab
    import genmaps as G
    import mapcheck
    import mapfeat
    os.makedirs(work, exist_ok=True)
    gen_rec = {k: v for k, v in rec.items() if k not in ("fam", "nf", "weird")}
    why = ""
    if rec.get("nf"):  # genfam family: its own build and family property check, in this slot's work dir (removed later)
        import genfam
        for a in range(NF_SEEDS):
            seed = int.from_bytes(os.urandom(6), "big")
            if a:  # a recipe draw can miss the family's property every time (vault: ~half the draws): draw again
                gen_rec = genfam.recipe(rec["nf"], random.Random(seed ^ 0x5F5F))
            try:
                _, mp, f = genfam.build_one(rec["nf"], name, seed, dict(gen_rec), work)
                return dict(i=i, ok=True, mp=mp, seed=seed, rec=dict(gen_rec, nf=rec["nf"]), fam=rec["fam"], f=f, att=a + 1)
            except Exception as e:  # noqa: BLE001  (generator and check errors: try another seed)
                why = str(e)[:80]
        return dict(i=i, ok=False, why=why, fam=rec["fam"], kind=rec["kind"])
    if rec.get("weird"):  # genweird family: same pattern as genfam (fresh recipe per retry, own family check)
        import genweird
        for a in range(NF_SEEDS):
            seed = int.from_bytes(os.urandom(6), "big")
            if a:
                gen_rec = genweird.recipe(rec["weird"], random.Random(seed ^ 0x5F5F))
            try:
                mp, f = genweird.build_one(rec["weird"], name, seed, dict(gen_rec), work)
                return dict(i=i, ok=True, mp=mp, seed=seed, rec=dict(gen_rec, weird=rec["weird"]), fam=rec["fam"], f=f, att=a + 1)
            except Exception as e:  # noqa: BLE001
                why = str(e)[:80]
        return dict(i=i, ok=False, why=why, fam=rec["fam"], kind=rec["kind"])
    for a in range(SEEDS):
        seed = int.from_bytes(os.urandom(6), "big")
        mp, f = condab._otf_build(G, mapcheck, mapfeat, gen_rec, seed, work, name)
        if mp:
            return dict(i=i, ok=True, mp=mp, seed=seed, rec=gen_rec, fam=rec["fam"], f=f, att=a + 1)
        why = str(f)[:80]
    return dict(i=i, ok=False, why=why, fam=rec["fam"], kind=rec["kind"])


LIGHT_LOAD = float(os.environ.get("STRAT_LIGHT_LOAD", 20))
LIGHT_WAIT = float(os.environ.get("STRAT_LIGHT_WAIT", 1800))
light_until = 0.0  # set before the pool forks: one wait budget per run, not per map


def light_build(job):
    """--light: wait while the machine is busy, for at most LIGHT_WAIT s per run, then build anyway: a gate must not fail on load."""
    while os.getloadavg()[0] > LIGHT_LOAD and time.time() < light_until:
        time.sleep(15)
    return build(job)


FARM_SET, FARM_MIN = 300, int(os.environ.get("STRAT_FARM_MIN", 8000))

def farm(a):
    """Large runs (owner 8 Nov, b1689 13,000 maps took 22 min and load 59 here): 300-map chunks on the pilots, same generator and mix, merged into DIR. Unsaved and single-run as ever.
    -> exit code, or None when too few pilots are up (the caller generates here). A second run on the same DIR waits for the first and takes its result."""
    import fcntl
    import glob
    import math
    import shlex
    import shutil
    import subprocess
    import tarfile
    import pilotd
    os.makedirs(a.dir, exist_ok=True)
    lock = open(os.path.join(a.dir, ".stratfarm.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    if os.path.exists(os.path.join(a.dir, "otf.json")):
        print(f"stratmaps: {a.dir} already has its maps")
        return 0
    if len(pilotd.alive_pilots()) < int(os.environ.get("FRESH_PILOT_MIN", 4)):
        return None
    run = f"/homes/zw4424/condor-runs/stratfarm/{os.getpid()}_{int(time.time())}"
    os.makedirs(run + "/out")
    k = math.ceil(a.n / FARM_SET)
    extra = f"--weird {a.weird}" + (f" --wfams {shlex.quote(a.wfams)}" if a.wfams else "") + (f" --nfams {shlex.quote(a.nfams)}" if a.nfams else "")
    open(run + "/job.sh", "w").write(f"""#!/bin/sh
d=/tmp/zw4424-sfarm-$$-$1
trap 'rm -rf "$d"' EXIT
cd /homes/zw4424/cambc && STRAT_ON_NODE=1 STRAT_MANYGRP_SHARE={MANYGRP} STRAT_BUSHROUTES_SHARE={BUSHROUTES} STRAT_RICHCENTRE_SHARE={RICHCENTRE} nice -n 10 python3 -I tools/lab/stratmaps.py "$d" --n {FARM_SET} --jobs "${{2:-4}}" {extra}  # 10 Nov: a short set (w_checker_big rejects many seeds) still returns what it made
[ -f "$d/otf.json" ] || exit 1
tar -czf {run}/out/.$1.tmp -C "$d" . && mv {run}/out/.$1.tmp {run}/out/$1.tgz
""")
    prio = int(os.environ.get("STRAT_FARM_PRIO", 9))  # just behind shipcheck legs (10)
    maps, x, nxt = [], os.path.join(a.dir, ".x"), 0
    t0, end = time.time(), time.time() + int(os.environ.get("STRAT_FARM_WALL", 3600))
    # 9 Nov (Builder, b1770): weird families (--wfams w_onemono,w_onepack) reject some seeds, so a set can come back short (284 of 300) and
    # the whole call failed (changedprobe stopped at 11 changed maps). A short return is topped up with more sets, up to 2 extra rounds.
    for rnd in range(3):
        want = a.n - len(maps)
        if want <= 0:
            break
        k = math.ceil(want / FARM_SET)
        ids = [f"s{nxt + i:04d}" for i in range(k)]
        nxt += k
        for sid in ids:
            pilotd.enqueue(f"{run}/{sid}", [(0, [sid, 4])], prio, node=run + "/job.sh")
        print(f"stratmaps: {want} maps as {k} sets on the pilots ({run}){' (top-up)' if rnd else ''}", flush=True)
        # 13 Nov (TB, tb_prof868: a set's pilot item vanished, in none of queue / claimed / done, and this loop waited forever): every 2 min,
        # a set with no output and no item queued or claimed on two looks in a row is queued again (at most 2 times a set)
        gone_, redo_, last_ = {}, {}, time.time()
        while time.time() < end and sum(os.path.exists(f"{run}/out/{sid}.tgz") for sid in ids) < k:
            time.sleep(10)
            if time.time() - last_ < 120:
                continue
            last_ = time.time()
            try:
                pilotd.poke(pilotd.q("queue"))
                pilotd.poke(pilotd.q("claimed"))
                live_ = set()
                for d_ in ("queue", "claimed"):
                    for n_ in pilotd.ls(pilotd.q(d_)):
                        if run.rsplit("/", 1)[-1].replace("_", "-") not in n_:
                            continue  # another batch (the batch id carries this run dir's name)
                        try:
                            live_.add(json.load(open(pilotd.q(d_, n_))).get("run", ""))
                        except (OSError, ValueError):
                            live_.add("?")
            except Exception:  # noqa: BLE001  never break the wait
                continue
            for sid in ids:
                if os.path.exists(f"{run}/out/{sid}.tgz") or redo_.get(sid, 0) >= 2:
                    continue
                if f"{run}/{sid}" in live_ or "?" in live_:
                    gone_[sid] = 0
                    continue
                gone_[sid] = gone_.get(sid, 0) + 1
                if gone_[sid] >= 2:
                    redo_[sid] = redo_.get(sid, 0) + 1
                    gone_[sid] = 0
                    pilotd.enqueue(f"{run}/{sid}", [(0, [sid, 4])], prio, node=run + "/job.sh")
                    print(f"stratmaps: set {sid} was lost on the pilots (no output, not queued): queued again ({redo_[sid]} of 2)", flush=True)
        for sid in ids:
            f = f"{run}/out/{sid}.tgz"
            if not os.path.exists(f):
                continue
            os.makedirs(x, exist_ok=True)
            with tarfile.open(f) as t:
                t.extractall(x, filter="data")
            got = json.load(open(x + "/otf.json"))["maps"][:max(a.n - len(maps), 0)]
            for m in got:
                os.replace(f"{x}/{m['name']}.map26a", os.path.join(a.dir, m["name"] + ".map26a"))
            maps += got
            shutil.rmtree(x)
        if time.time() >= end:
            break
    shutil.rmtree(run, ignore_errors=True)
    if len(maps) < 0.95 * a.n:
        print(f"stratmaps: only {len(maps)} of {a.n} maps came back from the pilots", file=sys.stderr)
        return 1
    log = f"stratmaps: {len(maps)} of {a.n} maps in {time.time() - t0:.0f} s, on the pilots"
    json.dump(dict(maps=maps, log=[log], tag="farm", made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(os.path.join(a.dir, "otf.json.part"), "w"))
    os.replace(os.path.join(a.dir, "otf.json.part"), os.path.join(a.dir, "otf.json"))
    print(log)
    return 0


def main():
    global light_until
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--weird", type=float, default=WEIRD, help="genweird share (1 = weird families only)")
    ap.add_argument("--take", action="store_true", help="take pre-generated sets from the freshpool (single use), else generate")
    ap.add_argument("--who", default=None, help="consumer name for the pool's take log (default: DIR's name)")
    ap.add_argument("--wfams", default=None, help="comma list of genweird families (default: all)")
    ap.add_argument("--nfams", default=None, help="comma list of genfam families (crystal,isle,brawl,...; no nf_ prefix): only these (11 Nov)")
    ap.add_argument("--jobs", type=int, default=None, help="default by /proc/loadavg: 8 below 40, 4 below 60, else 2")
    ap.add_argument("--light", action="store_true", help="at most 2 jobs at nice 19, waiting while load > 20 (also any --take that generates here)")
    ap.add_argument("--class", dest="cls", default=None, help="keep only maps with NAME:OPvalue (e.g. heavy_ge:>=0.5; see mapclass.py)")
    ap.add_argument("--class-tag", default=None, help="comma list of classes whose value goes into every otf.json entry")
    ap.add_argument("--class-max", type=int, default=None, help="--class: at most this many maps tried (default 25 x N)")
    a = ap.parse_args()
    # 13 Nov (RC: tb_prof872 passed nf_vault in --wfams; genweird raised KeyError 'nf_vault' on every try): nf_ names belong to --nfams
    # (genfam, given without the prefix): move them there and say so
    if a.wfams and any(x.strip().startswith("nf_") for x in a.wfams.split(",")):
        nf_ = [x.strip()[3:] for x in a.wfams.split(",") if x.strip().startswith("nf_")]
        a.wfams = ",".join(x.strip() for x in a.wfams.split(",") if x.strip() and not x.strip().startswith("nf_")) or None
        a.nfams = ",".join([x for x in (a.nfams or "").split(",") if x] + nf_)
        print(f"stratmaps: moved {', '.join('nf_' + x for x in nf_)} from --wfams to --nfams ({a.nfams}); --wfams is now {a.wfams}", file=sys.stderr)
    a.jobs_given = a.jobs is not None
    if a.cls:
        return class_run(a)
    rc = run(a)
    if a.class_tag and rc == 0:
        class_tag(a.dir, a.class_tag.split(","))
    return rc


def class_tag(d, names, conds=()):
    """Add "class": {NAME: value} to every map entry of d/otf.json -> number of maps tagged."""
    import mapclass
    p = os.path.join(d, "otf.json")
    meta = json.load(open(p))
    for m in meta["maps"]:
        m.setdefault("class", {}).update(mapclass.values(os.path.join(d, m["name"] + ".map26a"), names))
    json.dump(meta, open(p + ".part", "w"))
    os.replace(p + ".part", p)
    return len(meta["maps"])


def class_run(a):
    """--class: rounds of the plain path (a child stratmaps per round, so --take, the pilots and --light behave as usual) into
    DIR/.cls/rK; the maps that pass move into DIR; the rest are deleted with the round dir.
    11 Nov (Coordinator: 3 class draws scored pools locally at once at load 76): one --class draw at a time per machine
    (flock /data/zw4424/st/bq/.stratcls.lock; on a Condor node, /tmp), the rest wait."""
    import fcntl
    lp = "/data/zw4424/st/bq/.stratcls.lock" if os.path.exists("/data/zw4424/st/bq/live.txt") else "/tmp/zw4424-stratcls.lock"
    # 11 Nov (Builder/b1844: a GF/GR draw waited 25+ min behind two others): STRAT_CLASS_SLOTS (3) draws at once, one lock file a slot
    # 13 Nov (TB: ~20 rare class reads each drew 3 class batches through 3 slots, so checks sat 40+ min 'waiting on batches'; the
    # classification runs on the pilots, so the home cost is a few chunk tarballs a draw): 12 slots, re-read each loop from
    # bq/strat_class_slots (one number) so a change reaches draws that are already waiting
    def _slots():
        try:
            return max(1, int(open("/data/zw4424/st/bq/strat_class_slots").read().split()[0]))
        except (OSError, ValueError, IndexError):
            return max(1, int(os.environ.get("STRAT_CLASS_SLOTS", "12")))
    slots = _slots()
    t0, _lk = time.time(), None
    while _lk is None:
        slots = _slots()
        for i in range(slots):
            fh = open(f"{lp}.{i}", "a")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _lk = fh
                break
            except OSError:
                fh.close()
        if _lk is None:
            time.sleep(5)
    if time.time() - t0 > 5:
        print(f"stratmaps: waited {time.time() - t0:.0f} s for a --class slot ({slots} at once)", file=sys.stderr)
    a._cls_lock = _lk  # held until the process ends
    return _class_run(a)


def _cls_on_pilots(srcs, names, wait=None):
    """12 Nov (owner: "move any testing you do here to other machines"): class values for many maps computed on the pilots. Maps go up in
    chunks of STRAT_CLS_CHUNK (500) as one tarball each on the home (1 file a chunk); a node unpacks to /tmp, runs mapclass.values and
    writes one JSON. -> {src: values} for the chunks that came back within `wait` s (the rest are classified locally by the caller)."""
    import tarfile as _tf
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pilotd
    if not pilotd.alive_pilots():
        return {}
    chunk = int(os.environ.get("STRAT_CLS_CHUNK", 500))
    run = f"/homes/zw4424/condor-runs/stratfarm/cls_{os.getpid()}_{int(time.time())}"
    os.makedirs(run + "/out")
    open(run + "/job.sh", "w").write(f"""#!/bin/sh
d=/tmp/zw4424-scls-$$-$1
trap 'rm -rf "$d"' EXIT
mkdir -p "$d" && tar -xzf {run}/$1.tgz -C "$d" || exit 1
cd /homes/zw4424/cambc && nice -n 10 python3 -I -c '
import sys, os, json, glob
sys.path.insert(0, "tools/lab")
import mapclass
names = sys.argv[1].split(",")
out = {{}}
for p in sorted(glob.glob(sys.argv[2] + "/*.map26a")):
    try:
        out[os.path.basename(p)] = mapclass.values(p, names)
    except Exception as e:
        out[os.path.basename(p)] = str(e)[:100]
json.dump(out, open(sys.argv[3] + ".tmp", "w"))
os.replace(sys.argv[3] + ".tmp", sys.argv[3])
' "{",".join(names)}" "$d" {run}/out/$1.json
""")
    ids = []
    by = {}
    for i in range(0, len(srcs), chunk):
        cid = f"c{i // chunk:04d}"
        part = srcs[i:i + chunk]
        with _tf.open(f"{run}/{cid}.tgz", "w:gz", compresslevel=1) as t:
            for p in part:
                t.add(p, arcname=os.path.basename(p))
                by[os.path.basename(p)] = p
        pilotd.enqueue(f"{run}/{cid}", [(0, [cid, 2])], int(os.environ.get("STRAT_FARM_PRIO", 9)), node=run + "/job.sh")
        ids.append(cid)
    end = time.time() + (wait or int(os.environ.get("STRAT_CLS_WAIT", 900)))
    while time.time() < end and sum(os.path.exists(f"{run}/out/{c}.json") for c in ids) < len(ids):
        time.sleep(5)
    pre = {}
    for c in ids:
        try:
            for k, v in json.load(open(f"{run}/out/{c}.json")).items():
                if k in by:
                    pre[by[k]] = v
        except (OSError, ValueError):
            pass
    shutil.rmtree(run, ignore_errors=True)
    print(f"stratmaps: class values for {len(pre)} of {len(srcs)} maps from the pilots ({len(ids)} chunk(s))", flush=True)
    return pre


def _cls_vals(arg):
    """pool worker for _class_run: the class values of one map, or the error text (a str) when it cannot be read"""
    src, names = arg
    try:
        import mapclass
        return mapclass.values(src, names)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:60]}"


def _class_run(a):
    import math
    import shutil
    import subprocess
    import mapclass
    conds = mapclass.parse(a.cls)
    names = list(dict.fromkeys([c[0] for c in conds] + (a.class_tag.split(",") if a.class_tag else [])))
    for n_ in names:
        if n_ not in mapclass.CLASSES:
            raise SystemExit(f"stratmaps: unknown class {n_!r}")
    os.makedirs(a.dir, exist_ok=True)
    if os.path.exists(os.path.join(a.dir, "otf.json")):
        print(f"stratmaps: {a.dir} already has its maps")
        return 0
    cap = a.class_max or 25 * a.n
    who = a.who or os.path.basename(os.path.abspath(a.dir))
    me = os.path.abspath(__file__)
    keep, logs, tags, tried, passed, t0 = [], [], [], 0, 0, time.time()
    hit = 1 / 3  # prior (heavy_ge >= .5: ~.33 of the default mix); then the observed rate
    for rnd in range(8):
        need = a.n - len(keep)
        if rnd > 0 and not a.class_max and keep and hit >= 0.01:  # 12 Nov (TB, osq1s 13306: osq hit .025, 1,025 of 1,650 at the 25x cap): a rare
            cap = max(cap, min(int(os.environ.get("STRAT_CLASS_CAPX", "80")) * a.n, int(math.ceil(tried + need / hit * 1.3))))  # class gets the tries it needs, up to 80x
        if need <= 0 or tried >= cap:
            break
        k = min(cap - tried, max(need, int(math.ceil(need / max(hit, 0.02) * 1.1))))
        if not os.environ.get("STRAT_ON_NODE") and (k >= 2 * FARM_SET or (k >= FARM_SET // 2 and os.getloadavg()[0] > 16)):
            k = int(math.ceil(k / FARM_SET)) * FARM_SET  # this round farms: whole 300-map sets (a node makes a whole set anyway)
        sub = os.path.join(a.dir, ".cls", f"r{rnd}")
        shutil.rmtree(sub, ignore_errors=True)
        cmd = [sys.executable, "-I", me, sub, "--n", str(k), "--weird", str(a.weird)]
        cmd += (["--wfams", a.wfams] if a.wfams else []) + (["--nfams", a.nfams] if a.nfams else []) + (["--jobs", str(a.jobs)] if a.jobs_given else [])
        cmd += (["--light"] if a.light else []) + (["--take", "--who", who] if a.take else [])
        print(f"stratmaps: class round {rnd}: {k} maps for {need} more ({a.cls}, hit rate so far {hit:.3f})", flush=True)
        r = subprocess.run(cmd)
        p = os.path.join(sub, "otf.json")
        if not os.path.exists(p):
            print(f"stratmaps: class round {rnd} made no maps (rc {r.returncode})", file=sys.stderr)
            tried += k
            continue
        meta = json.load(open(p))
        tags.append(str(meta.get("tag")))
        logs += meta.get("log", [])
        # 11 Nov (TB: lah1's ngroups>=35 draw classified ~10k maps in one process for 40+ min, the whole shipcheck waiting): classify the
        # round in parallel (STRAT_CLASS_PAR, default 6; 3 above load 60), each worker its own process
        srcs = [os.path.join(sub, m["name"] + ".map26a") for m in meta["maps"]]
        par = int(os.environ.get("STRAT_CLASS_PAR", "6"))
        if os.getloadavg()[0] > 60:
            par = min(par, 3)
        pre = {}
        if not os.environ.get("STRAT_ON_NODE") and os.environ.get("STRAT_CLS_PILOTS", "1") != "0" and len(srcs) >= int(os.environ.get("STRAT_CLS_PILOTS_MIN", "50")):  # 12 Nov ~22:3xZ (owner "iterate faster"): 200 -> 50, local CPU is the cap
            try:  # 12 Nov: classify on the pilots first; whatever does not come back is classified here below
                pre = _cls_on_pilots(srcs, names)
            except Exception as e:  # noqa: BLE001
                print(f"stratmaps: pilot classification failed ({type(e).__name__}: {e}); classifying here", file=sys.stderr)
                pre = {}
        left = [x for x in srcs if x not in pre]
        if par > 1 and len(left) >= 200:
            import concurrent.futures as cf
            with cf.ProcessPoolExecutor(max_workers=par, initializer=os.nice, initargs=(5,)) as ex:
                for src, v in zip(left, ex.map(_cls_vals, [(x, names) for x in left], chunksize=25)):
                    pre[src] = v
        for m in meta["maps"]:
            tried += 1
            src = os.path.join(sub, m["name"] + ".map26a")
            try:
                vals = pre.get(src) if src in pre else mapclass.values(src, names)
                if isinstance(vals, str):
                    raise ValueError(vals)
            except Exception as e:  # noqa: BLE001  (unreadable map: not counted in)
                logs.append(f"class: {m['name']} unreadable: {str(e)[:60]}")
                continue
            if not mapclass.passes(vals, conds):
                continue
            passed += 1
            if len(keep) >= a.n:
                continue
            dst = os.path.join(a.dir, m["name"] + ".map26a")
            if os.path.exists(dst):
                continue
            os.replace(src, dst)
            keep.append(dict(m, **{"class": vals}))
        shutil.rmtree(sub, ignore_errors=True)
        hit = passed / tried if tried else hit
    shutil.rmtree(os.path.join(a.dir, ".cls"), ignore_errors=True)
    keep.sort(key=lambda m: m["name"])
    short = a.n - len(keep)
    line = (f"stratmaps: class {a.cls}: {len(keep)} of {a.n} maps from {tried} tried (hit rate {passed / max(1, tried):.3f}) "
            f"in {time.time() - t0:.0f} s" + (f"; SHORT by {short} (cap {cap} tries)" if short > 0 else ""))
    json.dump(dict(maps=keep, log=logs + [line], tag="+".join(tags), class_filter=a.cls, class_tried=tried, class_passed=passed,
                   made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(os.path.join(a.dir, "otf.json.part"), "w"))
    os.replace(os.path.join(a.dir, "otf.json.part"), os.path.join(a.dir, "otf.json"))
    print(line, file=sys.stderr if short > 0 else sys.stdout)
    return 0 if short <= 0 else 1


def run(a):
    global light_until
    hi = False
    if a.jobs is None:  # 1 Nov (Builder: load 95 on 16 cores): fan out by the machine's load
        la = os.getloadavg()[0]
        a.jobs = 8 if la < 40 else 4 if la < 60 else 2
    if a.n >= FARM_MIN:
        rc = farm(a)
        if rc is not None:
            return rc
        print("stratmaps: too few pilots up, generating here", file=sys.stderr)
    if a.take and a.weird == WEIRD and not a.wfams and not a.nfams:  # 1 Nov (owner: faster iterations): the pool's sets are the default mix
        import freshpool
        who = a.who or os.path.basename(os.path.abspath(a.dir))
        k = freshpool.take(a.dir, a.n, who)
        hi = freshpool.high_prio(who)
        # 4 Nov (Tool builder 2): a low-priority reader waits up to 30 min for node builds (each take queues them; ~100 s a set)
        # instead of generating here under load; a shipcheck waits 5 min, then builds here with a short load wait (below)
        t_end = time.time() + float(os.environ.get("STRAT_POOL_WAIT", 300 if hi else 1800))
        while not k and time.time() < t_end and (freshpool.building() or not hi):  # 2 Nov: a set takes ~100 s on a node; generating here took 830 s (bundle 36)
            time.sleep(15)
            k = freshpool.take(a.dir, a.n, who)
        if k:
            print(f"stratmaps: {k} maps from the fresh pool into {a.dir}")
            return 0
        print("stratmaps: fresh pool short, generating here", file=sys.stderr)
    # 10 Nov ~23:15Z (owner: "lighten the main machine"; rare probes' harvest shortfalls of 20-143 maps generated here at load 50):
    # above STRAT_LOCAL_LOAD (30) any draw of >= 10 maps goes to the pilots
    if not os.environ.get("STRAT_ON_NODE") and (a.n >= 2 * FARM_SET or (a.n >= FARM_SET // 2 and os.getloadavg()[0] > 16)
                                                or (a.n >= 10 and os.getloadavg()[0] > float(os.environ.get("STRAT_LOCAL_LOAD", 30)))):  # owner 8 Nov: Condor whenever it beats this machine
        rc = farm(a)
        if rc is not None:
            return rc
    # 10 Nov ~22:35Z (b1823: `--take --wfams` sat at zero CPU twice): --take never reaches the pool with --wfams (or a non-default
    # --weird), so it must not force the light wait (load > 20 all evening). Light only when asked, or when a pool take fell short.
    hi = locals().get("hi", False)
    pool_tried = a.take and a.weird == WEIRD and not a.wfams and not a.nfams
    if a.light or pool_tried:  # 1 Nov (owner: ash09 is shared, keep it light): generating here must stay in the background
        a.light, a.jobs = True, min(a.jobs, 2)
        light_until = time.time() + (120 if hi else LIGHT_WAIT)  # 4 Nov: a shipcheck doesn't sit out a busy evening
        os.nice(19)
    os.makedirs(a.dir, exist_ok=True)
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    tag = os.urandom(3).hex()
    recs = recipes(a.n, rng, a.weird, a.wfams.split(",") if a.wfams else None, [x.replace("nf_", "") for x in a.nfams.split(",")] if a.nfams else None)
    work = os.path.join(a.dir, "work")
    jobs = [(i, r, os.path.join(work, f"w{i}"), f"fm_{tag}_{i}") for i, r in enumerate(recs, 1)]
    t0 = time.time()
    try:
        os.nice(10)
    except OSError:
        pass
    maps, log = [], []
    with multiprocessing.get_context("fork").Pool(a.jobs) as P:
        for res in P.imap_unordered(light_build if a.light else build, jobs):
            if not res["ok"]:
                log.append(f"dropped slot {res['i']} ({res['fam']} {res['kind']}): {res['why']}")
                continue
            name = f"fm_{tag}_{res['i']}"
            dst = os.path.join(a.dir, name + ".map26a")
            os.replace(res["mp"], dst)
            f, rec = res["f"], res["rec"]
            maps.append(dict(name=name, family=res["fam"], kind=rec["kind"], size=rec.get("size"), seed=res["seed"], recipe=rec,
                             W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"), s2s=f.get("s2s"), attempts=res["att"],
                             labels=labels(dict(rec, fam=res["fam"]), f)))
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    maps.sort(key=lambda m: int(m["name"].rsplit("_", 1)[1]))
    log.append(f"stratmaps: {len(maps)} of {a.n} maps in {time.time() - t0:.0f} s, tag {tag}")
    json.dump(dict(maps=maps, log=log, tag=tag, made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
              open(os.path.join(a.dir, "otf.json.part"), "w"))
    os.replace(os.path.join(a.dir, "otf.json.part"), os.path.join(a.dir, "otf.json"))
    print(log[-1])
    for ln in log[:-1][:10]:
        print("  " + ln)
    return 0 if maps else 1


def drop_zero_gem(d):
    """Owner 12 Nov ~14:1xZ (creators: tournament maps always have gems; "no point testing 0 gem maps"): every set this tool hands out
    (generated, farmed, class-drawn or taken from the pool) loses its maps with no gem-carrying camp (all camps gold, or no camps).
    -> maps dropped. STRAT_ZERO_GEM=1 keeps them."""
    p = os.path.join(d, "otf.json")
    if os.environ.get("STRAT_ZERO_GEM") == "1" or not os.path.exists(p):
        return 0
    import map26a
    import genmaps as G
    meta = json.load(open(p))
    keep, gone = [], []
    for m in meta.get("maps", []):
        f = os.path.join(d, m["name"] + ".map26a")
        try:
            zero = all(t == G.GOLD for t in map26a.load(f)["camps"].values())
        except Exception:  # noqa: BLE001  (an unreadable map is the consumer's problem, as before)
            zero = False
        (gone if zero else keep).append(m)
    if not gone:
        return 0
    for m in gone:
        try:
            os.remove(os.path.join(d, m["name"] + ".map26a"))
        except OSError:
            pass
    meta["maps"] = keep
    meta.setdefault("log", []).append(f"stratmaps: dropped {len(gone)} zero-gem map(s) (owner 12 Nov: tournament maps always have gems)")
    json.dump(meta, open(p + ".zg", "w"))
    os.replace(p + ".zg", p)
    print(f"stratmaps: dropped {len(gone)} zero-gem map(s) of {len(gone) + len(keep)}", file=sys.stderr)
    return len(gone)


if __name__ == "__main__":
    rc = main()
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        try:
            drop_zero_gem(sys.argv[1])
        except Exception as e:  # noqa: BLE001
            print(f"stratmaps: zero-gem filter failed: {e}", file=sys.stderr)
    sys.exit(rc)
