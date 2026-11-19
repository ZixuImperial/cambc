#!/usr/bin/env python3
"""Large generated map families for sequential tests (tools/lab/sprt.py); nobody tunes on them.

Same recipes, checks and engine build as tools/lab/genmaps.py (it imports it), with their own seeds and schedules:
  fresh  gen_s_001..  (seeds 700000+, /data/zw4424/genmaps_s): N - N/4 normal maps (balanced over size, team size,
         symmetry, terrain, camp mix, monoliths, altars, spawn distance) and N/4 long-route/big maps (genmaps.LONG
         recipes, new seeds), because 12 of the 40 pool maps walk more than 80 tiles spawn to spawn and the normal
         recipes stop at 71.
  patho  gen_p_001..  (seeds 3000000+, /data/zw4424/genmaps_p): the five pathological kinds of genmaps (dash-only
         islands, altars only on dash/crystal islands, halves split by a hole band, monolith rush, 26x26 gem desert
         with spawns 2 apart), each with a random size, symmetry, team size, terrain, camp mix and altar layout, so
         robustness is tested on many maps instead of gen_36..40 and patho4 only.
  gate   gen_g_001..  (seeds 4000000+, /data/zw4424/genmaps_g): every altar gated by camps (genmaps.GATE_KINDS, cambc-4f
         25 Oct): a closed ring of one camp group around the altar (ring_camps), a wall ring whose gaps each hold one camp
         (ring_gates), or tribute tiles that are all walls, holes or camps (adj_gate), each checked with altaraccess's
         classes (ring / adjgate from both spawns) on the design and on the built map. Sprint 2 had 2 such maps in 15;
         local pools had 3 in 953. sprt.py does not use this family (its lists are fresh, custom and patho).
  gate2  gen_g2_001..  (seeds 4500000+, /data/zw4424/genmaps_g2): a held-out twin of gate (cambc-f8 25 Oct: the ALTAR_RING
         fixes were designed on gen_g): new recipe columns and seeds, with fixed shares of the shapes that failed there
         (2-thick camp rings, gold-cluster rings, one-wolf gates, 65-70 wide boards, short spawn-to-spawn). Not in sprt.
  gate3  gen_g3_001..  (seeds 8000000+, /data/zw4424/genmaps_g3): gate2's recipe with new columns and seeds, for the next
         validation round (reading a batch's per-map results spends it as a held-out test).
  gateN  gen_gN_001.. for N = 4..9 (seeds 8000000 + 500000 (N - 3)+, /data/zw4424/genmaps_gN, recipe columns rng
         9229 + 110 (N - 2)): further unread batches of the same recipe, one per validation round.
  custom gen_c_<name> (/data/zw4424/genmaps_c): maps made by hand (cambc mapeditor, or files in the repo's maps/),
         added with --import; each is decoded and analysed (mapfeat) before it is installed, and a map with no
         reachable gems is refused unless --force. (The repo's maps/lost_world.map26a was refused as one until mapfeat
         version 2: in fact 80% of its gems need a crystal jump and then dashes from islet to islet, which no bot does,
         so every game on it ends 0-0 at round 2000 and side B wins the tiebreak.)

usage: python3 tools/lab/genbig.py [--family fresh|patho|gate|gate2..gate9] [--n 400] [--jobs 4] [--install]
                                  [--checks 2]
       python3 tools/lab/genbig.py --import FILE.map26a ... [--install]
  --checks 2 adds the post-build checks of 25 Oct (genmaps.validate: split halves never meet, normal maps have no
  camp-gated altar) to every new map's recipe; give it for every new family or batch. Without it every existing seed
  builds the same map as before. A family's recipe list depends on --n: rebuild (--only) with the --n it was built with
  (gen_u_001..060 were built with --n 60, gen_u_061..300 with --n 300); --only refuses a recipe that differs from the
  map's meta.json.
  outputs in the family dir: <name>.{json,map26a,meta.json,txt}, index.json, maplist.txt (patho and the gate families also
  maplist_<kind>.txt). --install copies the .map26a files into /data/zw4424/work301/maps only (local abl.sh, sprt.py;
  never the NFS Condor project: the home dir has an inode quota). Every name starts with gen_, so abl.sh's default
  list (and with it every h2h result) does not change. Rerunning keeps existing maps; --only N... rebuilds single maps.
"""
import argparse
import json
import multiprocessing
import os
import random
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import mapfeat  # noqa: E402

INSTALL = "/data/zw4424/work301/maps"
# seed = base + 1000 i + attempt: fresh uses 701000..1099039 for 400 maps, patho starts at 3001000, so no two maps of
# any family (genmaps: 1000..45039 held-out, 501000..545039 dev) share a random stream unless fresh grows past 2299 maps
FAMILY = {"fresh": ("gen_s_", 700000, "/data/zw4424/genmaps_s"), "patho": ("gen_p_", 3000000, "/data/zw4424/genmaps_p"),
          "gate": ("gen_g_", 4000000, "/data/zw4424/genmaps_g"), "gate2": ("gen_g2_", 4500000, "/data/zw4424/genmaps_g2"),
          "gate3": ("gen_g3_", 8000000, "/data/zw4424/genmaps_g3")}
for _n in range(4, 10):  # further held-out gate batches, each with its own seed range (40 maps use < 41,000 seeds)
    FAMILY[f"gate{_n}"] = (f"gen_g{_n}_", 8000000 + 500000 * (_n - 3), f"/data/zw4424/genmaps_g{_n}")


def install(src, dst):
    """Copy only when the content differs, so a map file's mtime changes exactly when its content changes:
    tools/lab/abindex.py drops local results played before a map's file changed."""
    if os.path.exists(dst) and open(dst, "rb").read() == open(src, "rb").read():
        return False
    shutil.copyfile(src, dst)
    return True
CUSTOM = "/data/zw4424/genmaps_c"


def recipes(n):
    n_long = n // 4
    n_norm = n - n_long
    r = random.Random(7007)
    cols = {}
    for k, vals in G.SCHED.items():
        L = (vals * (n_norm // len(vals) + 1))[:n_norm]
        r.shuffle(L)
        cols[k] = L
    rec = [dict({k: cols[k][i] for k in G.SCHED}, kind="normal") for i in range(n_norm)]
    rec += [dict(G.LONG[i % len(G.LONG)]) for i in range(n_long)]
    r.shuffle(rec)  # long maps spread over the order, so any prefix of the list has the same mix
    return rec


def patho_recipes(n):
    r = random.Random(8008)
    out = []
    for i in range(n):
        rec = {k: r.choice(v) for k, v in G.SCHED.items()}
        rec["kind"] = G.PATHO[i % len(G.PATHO)]
        if rec["kind"] == "tiny_desert":  # 26x26, spawns 2 apart, at most 80 gems: only the gem-poor mix fits
            rec.update(mix="gem_poor", mono=0, size="M", aspect="square", min30=True)  # 30x30, the legal minimum
        if rec["kind"] == "monolith_rush":  # places its own 3-4 monoliths
            rec["mono"] = 0
        out.append(rec)
    r.shuffle(out)
    return out


def gate_recipes(n):
    """Random recipe columns (as patho), the three gate kinds in turn; no gem-poor mix (a map needs 40+ gems)."""
    r = random.Random(9009)
    out = []
    for i in range(n):
        rec = {k: r.choice(v) for k, v in G.SCHED.items()}
        rec["kind"] = G.GATE_KINDS[i % len(G.GATE_KINDS)]
        if rec["mix"] == "gem_poor":
            rec["mix"] = "balanced"
        out.append(rec)
    r.shuffle(out)
    return out


def gate2_recipes(n, seed=9229):
    """gate2: the gate recipes with new columns, and fixed shares of gen_g's failure shapes, by index before the shuffle."""
    r = random.Random(seed)
    out = []
    for i in range(n):
        rec = {k: r.choice(v) for k, v in G.SCHED.items()}
        rec["kind"] = G.GATE_KINDS[i % len(G.GATE_KINDS)]
        if rec["mix"] == "gem_poor":
            rec["mix"] = "balanced"
        out.append(rec)
    rc = [x for x in out if x["kind"] == "ring_camps"]
    rg = [x for x in out if x["kind"] == "ring_gates"]
    for x in rc[:4]:
        x["gate_over"] = {"r": r.choice([3, 4]), "t": 2}  # 2-thick camp rings
    for x in rc[4:8]:
        x["gate_over"] = {"camp": G.GOLD}  # gold-cluster rings
    for x in rc[8:10]:
        x["gate_over"] = {"r": 3, "t": 2, "camp": G.GOLD}  # both
    for x in rg[:6]:
        x["gate_over"] = {"gates": 1, "camp": G.WOLF}  # one-wolf gates
    for x in out[::5]:
        x["dims"] = [r.randint(65, 70), r.randint(45, 70)]  # large boards, 65-70 wide
    for x in out[2::5]:
        x["spawn"] = "short"  # short spawn-to-spawn
    r.shuffle(out)
    return out


def build(job):
    i, rec, outdir, prefix, seed0 = job
    name = f"{prefix}{i:03d}"
    mp = os.path.join(outdir, name + ".map26a")
    if os.path.exists(mp) and os.path.exists(os.path.join(outdir, name + ".meta.json")):
        return name, json.load(open(os.path.join(outdir, name + ".meta.json"))), "kept"
    gate = rec["kind"] in G.GATE_KINDS
    tries = 120 if gate else 40
    for attempt in range(tries):
        seed = seed0 + 1000 * i + attempt
        if gate and attempt == tries // 2 and rec.get("size") == "S":
            rec = dict(rec, size="M")  # a big gate structure may not fit a small board: the second half tries a medium one
        try:
            m = G.generate_gate(rec, seed) if gate else G.generate(rec, seed)
            ok, info = G.validate_gate(m, rec) if gate else G.validate(m, rec)
        except RuntimeError as e:
            ok, info = False, str(e)
        if ok:
            break
    else:
        return name, None, f"no valid map in {tries} attempts"
    sp = os.path.join(outdir, name + ".json")
    json.dump(G.spec_of(m), open(sp, "w"))
    try:
        d = G.build_and_check(m, sp, mp)
    except (RuntimeError, AssertionError) as e:
        return name, None, f"build failed: {e}"
    meta = dict(name=name, seed=seed, recipe=rec, features=mapfeat.analyse(d, name))
    if gate:
        meta["access"] = G.altar_access(d)
        meta["gate"] = {k: v for k, v in m.gate.items()}
        want = "adjgate" if rec["kind"] == "adj_gate" else "ring"
        if meta["access"] != {"A": want, "B": want}:
            return name, None, f"built map access {meta['access']}, want {want}"
    json.dump(meta, open(os.path.join(outdir, name + ".meta.json"), "w"), indent=1)
    open(os.path.join(outdir, name + ".txt"), "w").write(m.ascii() + "\n")
    return name, meta, "built"


def import_maps(files, to_work, force=False):
    """Hand-made maps -> gen_c_<name>: decode and analyse each one, then copy it in. A map with no reachable gems
    (every game is decided by the side tiebreak at round 2000, so it carries no evidence) needs --force."""
    os.makedirs(CUSTOM, exist_ok=True)
    ip = os.path.join(CUSTOM, "index.json")
    index = json.load(open(ip)) if os.path.exists(ip) else {}
    for f in files:
        stem = os.path.basename(f)
        stem = stem[:-7] if stem.endswith(".map26a") else stem
        name = "gen_c_" + "".join(c if c.isalnum() or c in "_-" else "_" for c in stem)
        try:
            feat = mapfeat.analyse(G.map26a.load(f), name)
        except Exception as e:  # noqa: BLE001 (any decode failure means the file is not a usable map)
            print(f"{f}: not a valid .map26a ({e}); skipped", file=sys.stderr)
            continue
        x0, y0, x1, y1 = G.map26a.load(f)["spawnA_rect"]
        if not 9 <= (x1 - x0) * (y1 - y0) <= 16 and not force:
            print(f"{f}: spawn area {x1 - x0}x{y1 - y0} is outside 9..16 tiles: MapBuilder accepts it, but every game "
                  f"fails to load (engine error 7); skipped", file=sys.stderr)
            continue
        if (feat["gems"] == 0 or feat["none"] >= 0.99) and not force:
            print(f"{f}: no gems reachable on foot, by dash or by crystal (gems {feat['gems']}, unreachable share "
                  f"{feat['none']}): every game ends in the side tiebreak; skipped (--force imports it anyway)",
                  file=sys.stderr)
            continue
        install(f, os.path.join(CUSTOM, name + ".map26a"))
        index[name] = dict(name=name, source=os.path.abspath(f), recipe=dict(kind="custom"), features=feat)
        print(f"{name} {feat['W']}x{feat['H']} T{feat['T']}: gems {feat['gems']} groups {feat['grp']} s2s {feat['s2s']} "
              f"dash {feat['dash']} altar walk {feat['alt_d']}")
        if to_work:
            install(f, os.path.join(INSTALL, name + ".map26a"))
    json.dump(index, open(ip, "w"), indent=1)
    open(os.path.join(CUSTOM, "maplist.txt"), "w").write("".join(n + "\n" for n in sorted(index)))
    print(f"{len(index)} custom maps in {CUSTOM}{'; installed in ' + INSTALL if to_work else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=sorted(FAMILY), default="fresh")
    ap.add_argument("--n", type=int)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--outdir")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--import", dest="imp", nargs="+", metavar="FILE")
    ap.add_argument("--force", action="store_true", help="--import maps with no reachable gems too")
    ap.add_argument("--checks", type=int, default=1, help="2: the 25 Oct post-build checks (new families and batches)")
    a = ap.parse_args()
    if a.imp:
        import_maps(a.imp, a.install, a.force)
        return
    prefix, seed0, outdir = FAMILY[a.family]
    outdir = a.outdir or outdir
    n = a.n or {"fresh": 400, "patho": 100}.get(a.family, 40)
    if a.family in ("fresh", "patho", "gate"):
        recs = {"fresh": recipes, "patho": patho_recipes, "gate": gate_recipes}[a.family](n)
    else:  # gate2, gate3, ...: gate2's recipe with the batch's own columns (9229, 9339, 9449, ...)
        recs = gate2_recipes(n, seed=9229 + 110 * (int(a.family[4:]) - 2))
    if a.checks >= 2:
        recs = [dict(r, checks=a.checks) for r in recs]
    os.makedirs(outdir, exist_ok=True)
    jobs = [(i, rec, outdir, prefix, seed0) for i, rec in enumerate(recs, 1) if not a.only or i in a.only]
    if a.only:
        for i, rec, *_ in jobs:  # the recipe list depends on --n: never replace a map by one of another recipe
            mp = os.path.join(outdir, f"{prefix}{i:03d}.meta.json")
            old = json.load(open(mp))["recipe"] if os.path.exists(mp) else None
            if old and rec["kind"] in G.GATE_KINDS and (old.get("size"), rec.get("size")) == ("M", "S"):
                old = dict(old, size="S")  # build() moved a small gate board to a medium one on its later attempts
            if old and old != rec:
                sys.exit(f"{prefix}{i:03d}: its meta.json recipe differs from recipe {i} of --n {n} (built with "
                         f"another --n or --checks?); nothing rebuilt")
        for job in jobs:
            for ext in (".map26a", ".meta.json"):
                p = os.path.join(outdir, f"{prefix}{job[0]:03d}{ext}")
                if os.path.exists(p):
                    os.remove(p)
    ip = os.path.join(outdir, "index.json")
    index = json.load(open(ip)) if os.path.exists(ip) else {}
    bad = 0
    with multiprocessing.Pool(a.jobs) as pool:
        for name, meta, how in pool.imap(build, jobs):
            if meta is None:
                bad += 1
                print(f"{name}: {how}", file=sys.stderr)
                continue
            index[name] = meta
            if how == "built":
                f, r = meta["features"], meta["recipe"]
                print(f"{name} {r['kind']:13s} {f['W']}x{f['H']} T{f['T']} {r.get('style')}/{r.get('mix')}/{r.get('altar')}/"
                      f"{r.get('spawn')}: gems {f['gems']} s2s {f['s2s']}" + (f" gate {meta['gate']}" if "gate" in meta else ""), flush=True)
            if a.install:
                install(os.path.join(outdir, name + ".map26a"), os.path.join(INSTALL, name + ".map26a"))
    json.dump(index, open(ip, "w"), indent=1)
    names = sorted(index)
    open(os.path.join(outdir, "maplist.txt"), "w").write("".join(n + "\n" for n in names))
    if a.family == "patho" or a.family.startswith("gate"):
        for kind in (G.PATHO if a.family == "patho" else G.GATE_KINDS):
            open(os.path.join(outdir, f"maplist_{kind}.txt"), "w").write(
                "".join(n + "\n" for n in names if index[n]["recipe"]["kind"] == kind))
    print(f"{len(index)} maps in {outdir} ({bad} failed){'; installed in ' + INSTALL if a.install else ''}")


if __name__ == "__main__":
    main()
