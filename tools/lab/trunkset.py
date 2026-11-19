#!/usr/bin/env python3
"""trunkset: one shared measurement set per trunk, so agents stop each playing their own base. Tool builder, 2 Nov.

usage: python3 -I tools/lab/trunkset.py TRUNK [--n 300] [--opp nova_spar_nochase2]     (does nothing if the set exists)
Plays TRUNK vs OPP on N unseen fresh-pool maps (half pathological), both seats, at the release build, with replays, into
/data/zw4424/trunkset/TRUNK: maps/, rep/MAP_A.repl26a (TRUNK as team A) and _B, set.json (one row per game: replay, map, seat, labels,
fam). Read it with readmany.py: `readmany.py READER.py /data/zw4424/trunkset/TRUNK --out OUT.jsonl`, or replay.py on one file.
A line goes to condor-work/reports/trunksets.md. About 35 MB a set on shared scratch, none on /homes. Scratch is temporary: a set is
regenerable in distribution, not game for game, since its maps are single-use; copy anything you must keep. Nothing here deletes old sets:
retiring them is a separate, explicit step.
These maps are measurement data once used: do not gate a candidate on them."""
import json
import os
import subprocess
import sys
import time

X = "/data/zw4424/trunkset"
REPO = "/homes/zw4424/cambc"
LOG = "/homes/zw4424/condor-work/reports/trunksets.md"


def main():
    a = sys.argv[1:]
    sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
    import idopp
    n, opp = 300, idopp.id_opp()
    if "--n" in a:
        i = a.index("--n"); n = int(a[i + 1]); del a[i:i + 2]
    if "--opp" in a:
        i = a.index("--opp"); opp = a[i + 1]; del a[i:i + 2]
    if len(a) != 1:
        sys.exit(__doc__)
    bot = a[0]
    d = f"{X}/{bot}" + ("" if opp == "nova_spar_nochase2" else f"_vs_{opp}")
    if os.path.exists(f"{d}/set.json"):
        print(f"trunkset: {d} exists")
        return 0
    if not os.path.isdir(f"{REPO}/bots/{bot}/src"):
        sys.exit(f"trunkset: no bot {bot}")
    os.makedirs(f"{d}/rep", exist_ok=True)
    t0 = time.time()
    if not os.path.exists(f"{d}/maps/otf.json"):
        r = subprocess.run(["python3", "-I", f"{REPO}/tools/lab/stratmaps.py", f"{d}/maps", "--n", str(n), "--take", "--who", f"trunkset:{bot}"],
                           cwd=REPO, capture_output=True, text=True)
        print((r.stdout + r.stderr).strip().splitlines()[0] if (r.stdout + r.stderr).strip() else "stratmaps: no output", flush=True)
        if r.returncode:
            sys.exit("trunkset: no maps")
    meta = json.load(open(f"{d}/maps/otf.json"))
    rows, man = [], []
    B, O = f"{REPO}/bots/{bot}", f"{REPO}/bots/{opp}"
    for m in meta["maps"]:
        nm = m["name"]
        for seat, x, y in (("a", B, O), ("b", O, B)):
            rp = f"rep/{nm}_{seat.upper()}.repl26a"
            rows.append(dict(replay=rp, map=nm, seat=seat, family=m.get("family"), labels=m.get("labels", {})))
            if not os.path.exists(f"{d}/{rp}"):
                man.append(f"{x} {y} {d}/maps/{nm}.map26a {rp}")
    if man:
        open(f"{d}/man.txt", "w").write("\n".join(man) + "\n")
        r = subprocess.run(["nice", "-n", "10", "python3", "-I", f"{REPO}/tools/lab/cqbatch.py", "man.txt", "--release", "--log-limit", "0", "--per-job", "25"],
                           cwd=d, capture_output=True, text=True, env=dict(os.environ, CQB_PRIO="6"))
        print((r.stdout or "").strip().splitlines()[-1][:160] if (r.stdout or "").strip() else (r.stderr or "")[-160:], flush=True)
    have = [g for g in rows if os.path.exists(f"{d}/{g['replay']}")]
    if len(have) < 0.95 * len(rows):
        sys.exit(f"trunkset: only {len(have)} of {len(rows)} games returned; rerun to play the rest")
    json.dump(dict(bot=bot, opp=opp, made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), games=have), open(f"{d}/set.json.part", "w"))
    os.replace(f"{d}/set.json.part", f"{d}/set.json")
    with open(LOG, "a") as f:
        f.write(f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {bot} vs {opp}: {len(have)} games, {len(meta['maps'])} maps, {d}\n")
    print(f"trunkset: {len(have)} games in {time.time() - t0:.0f} s -> {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
