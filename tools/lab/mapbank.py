#!/usr/bin/env python3
"""mapbank: a FROZEN bank of generated maps, made like condab's on-the-fly (OTF) maps but kept, so their games are cached in
the index (reruns cost nothing) and every candidate meets the same maps. Tool builder, 30 Oct (Builder: at 636 maps only
~+2.7% is detectable; most real gains are +0.5-1.5%).

usage: python3 -I tools/lab/mapbank.py gen bk 0 4000 [--jobs 12]   decision bank gen_bk_00000 .. gen_bk_03999
       python3 -I tools/lab/mapbank.py gen bh 0 1000               HELD-OUT bank gen_bh_00000 .. (never for decisions)
       python3 -I tools/lab/mapbank.py pack bk|bh                  the Condor packs (100 maps per tar, on the home)
       python3 -I tools/lab/mapbank.py list bk N                   the first N bank map names (condab BIG=N uses this)
       python3 -I tools/lab/mapbank.py status
Maps: /data/zw4424/work301/maps/gen_bk_NNNNN.map26a (the map dir abindex and condab already read; the gen_ prefix keeps
them out of every pool listing). Slot i is normal (3 of every 5, sizes S/M/L in turn) or pathological (2 of 5, the types in
turn), as condab's CONFIRM maps (3:2), from recipe and seed draws of random.Random("mapbank:<bank>:<i>"): deterministic.
A slot whose draws all fail is retried with "...:<i>:r<k>" draws. Files are created exclusively, never overwritten.
Index (family, kind, size, W, H, T, gems, s2s, recipe, seed): /data/zw4424/mapbank/<bank>_index.jsonl.
Packs: /homes/zw4424/condor-work/mapbank/gen_<bank>_NNN.tar (maps NNN*100 .. NNN*100+99), read by condab_node.sh when a
job's map is not in the shared project (bank maps are never copied there: the home inode quota).
"""
import json
import os
import random
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor

REPO = "/homes/zw4424/cambc"
MAPS = "/data/zw4424/work301/maps"
IDX = "/data/zw4424/mapbank"
PACKS = "/homes/zw4424/condor-work/mapbank"
WORK = "/data/zw4424/mapbank/work"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))


def name(bank, i):
    return f"gen_{bank}_{i:05d}"


def one(job):
    """Generate slot i of a bank -> index record (or one with error)."""
    bank, i = job
    import condab
    import genbig
    import genmaps as G
    import mapcheck
    import mapfeat
    nm = name(bank, i)
    dst = os.path.join(MAPS, nm + ".map26a")
    if os.path.exists(dst):
        return dict(name=nm, skipped="exists")
    work = os.path.join(WORK, nm)
    os.makedirs(work, exist_ok=True)
    fam = "normal" if i % 5 < 3 else "patho"
    t0 = time.time()
    for retry in range(4):
        rng = random.Random(f"mapbank:{bank}:{i}" + (f":r{retry}" if retry else ""))
        if fam == "normal":
            size = ("S", "M", "L")[(i // 5 * 3 + i % 5) % 3]
            recs = [dict({k: rng.choice(v) for k, v in G.SCHED.items()}, kind="normal", size=size, checks=2)
                    for _ in range(condab.OTF_RECIPES)]
            tries = condab.OTF_SEEDS
        else:
            pool = genbig.patho_recipes(100)
            kinds = list(G.PATHO)
            first = kinds[(i // 5 * 2 + i % 5 - 3) % len(kinds)]
            order = [first] + rng.sample([k for k in kinds if k != first], len(kinds) - 1)
            recs = [dict(rng.choice([x for x in pool if x["kind"] == k]), checks=2) for k in order]
            tries = condab.OTF_PATHO_SEEDS
        for rec in recs:
            for _ in range(tries):
                seed = rng.getrandbits(48)
                mp, f = condab._otf_build(G, mapcheck, mapfeat, rec, seed, work, nm)
                if mp:
                    try:
                        fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    except FileExistsError:
                        os.remove(mp)
                        return dict(name=nm, skipped="exists")
                    with os.fdopen(fd, "wb") as out:
                        out.write(open(mp, "rb").read())
                    os.remove(mp)
                    try:
                        os.rmdir(work)
                    except OSError:
                        pass
                    return dict(name=nm, bank=bank, i=i, family=fam, kind=rec.get("kind"), size=rec.get("size"),
                                W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"), s2s=f.get("s2s"),
                                recipe=rec, seed=seed, retry=retry, secs=round(time.time() - t0, 1))
    return dict(name=nm, error="no valid map after 4 draw sets", secs=round(time.time() - t0, 1))


def gen(bank, lo, hi, jobs):
    os.makedirs(IDX, exist_ok=True)
    idx = os.path.join(IDX, f"{bank}_index.jsonl")
    have = set()
    if os.path.exists(idx):
        have = {json.loads(l)["name"] for l in open(idx) if '"error"' not in l and '"skipped"' not in l}
    todo = [(bank, i) for i in range(lo, hi) if name(bank, i) not in have]
    print(f"bank {bank}: {len(todo)} maps to make ({hi - lo - len(todo)} already indexed), {jobs} processes", flush=True)
    t0, n = time.time(), 0
    with ProcessPoolExecutor(jobs) as ex, open(idx, "a") as out:
        for r in ex.map(one, todo, chunksize=4):
            if "skipped" not in r:
                out.write(json.dumps(r) + "\n")
                out.flush()
            n += 1
            if n % 200 == 0:
                print(f"  {n}/{len(todo)} in {time.time() - t0:.0f} s", flush=True)
    print(f"done: {n} in {time.time() - t0:.0f} s", flush=True)


def pack(bank):
    os.makedirs(PACKS, exist_ok=True)
    recs = [json.loads(l) for l in open(os.path.join(IDX, f"{bank}_index.jsonl")) if '"error"' not in l]
    by = {}
    for r in recs:
        by.setdefault(r["i"] // 100, []).append(r["name"])
    made = 0
    for k, names in sorted(by.items()):
        p = os.path.join(PACKS, f"gen_{bank}_{k:03d}.tar")
        tmp = p + ".tmp"
        with tarfile.open(tmp, "w") as tf:
            for nm in sorted(names):
                tf.add(os.path.join(MAPS, nm + ".map26a"), arcname=nm + ".map26a")
        os.replace(tmp, p)
        made += 1
    print(f"{made} packs in {PACKS}")


def bank_list(bank, n):
    """The first n generated maps of a bank, in index order (slot order)."""
    recs = [json.loads(l) for l in open(os.path.join(IDX, f"{bank}_index.jsonl")) if '"error"' not in l]
    names = sorted(r["name"] for r in recs if os.path.exists(os.path.join(MAPS, r["name"] + ".map26a")))
    return names[:n]


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "gen":
        bank, lo, hi = a[1], int(a[2]), int(a[3])
        if bank not in ("bk", "bh"):
            sys.exit("bank must be bk (decisions) or bh (held-out)")
        gen(bank, lo, hi, int(a[a.index("--jobs") + 1]) if "--jobs" in a else 12)
    elif a[0] == "pack":
        pack(a[1])
    elif a[0] == "list":
        print("\n".join(bank_list(a[1], int(a[2]))))
    elif a[0] == "status":
        for b in ("bk", "bh"):
            p = os.path.join(IDX, f"{b}_index.jsonl")
            recs = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
            ok = [r for r in recs if "error" not in r]
            packs = len([f for f in os.listdir(PACKS) if f.startswith(f"gen_{b}_")]) if os.path.isdir(PACKS) else 0
            print(f"{b}: {len(ok)} maps ({sum(r['family'] == 'normal' for r in ok)} normal, "
                  f"{sum(r['family'] == 'patho' for r in ok)} patho), {len(recs) - len(ok)} failed slots, {packs} packs")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
