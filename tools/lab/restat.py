#!/usr/bin/env python3
"""Re-simulate finished abl.sh runs to recover their per-game statistics (games are deterministic).

usage: python3 -I tools/lab/restat.py RUNDIR... [--keep] [--force]
  RUNDIR: an abl.sh output dir (/data/zw4424/abl/NAME). abl.sh deletes the 1.5 MB statistics files after its summary,
  so older runs have only games.jsonl; this replays their manifest (the same bot builds, maps and sides) and writes
  RUNDIR/games_rich.jsonl (tools/lab/gamefeat.py features) for tools/lab/gamerep.py.
  --keep keeps st/ (statistics) and rep/ (replays: `cambc304 view RUNDIR/rep/ID.repl26a`); --force redoes runs that
  already have games_rich.jsonl.
Each run takes abl.sh's machine-wide lock while it plays (about 25 s per 80 games), in the fixed project
/data/zw4424/ablproj, so cached builds are reused. Every replayed game is checked against games.jsonl (winner, rounds,
both teams' tributed gems): a mismatch means nondeterminism or a changed input, and is reported. Games on a map whose
file changed after the run are skipped. games.jsonl, run/ and summary.txt are never touched.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamefeat  # noqa: E402

# the engine each run was played on (its cli.txt, written by abl.sh; runs without one used cambc 3.0.4): CLI, BASE, PROJ
ENGINES = {"3.0.4": ("/homes/zw4424/condor-work/bin/cambc304", "/data/zw4424/work301", "/data/zw4424/ablproj"),
           "4.0.0": ("/data/zw4424/cambc400/bin/cambc400", "/data/zw4424/work301_4.0.0", "/data/zw4424/ablproj_4.0.0"),
           "5.0.0": ("/data/zw4424/cambc500/bin/cambc500", "/data/zw4424/work301_4.0.0", "/data/zw4424/ablproj_4.0.0")}
LOCK = "/data/zw4424/abl.lock"


def restat(rundir, keep=False, force=False):
    name = os.path.basename(rundir.rstrip("/"))
    if os.path.exists(os.path.join(rundir, "games_rich.jsonl")) and not force:
        return f"{name}: already has games_rich.jsonl (--force redoes it)"
    t_run = os.path.getmtime(os.path.join(rundir, "games.jsonl"))
    try:
        cv = open(os.path.join(rundir, "cli.txt")).read().split()[1]
    except (OSError, IndexError):
        cv = "3.0.4"
    if cv not in ENGINES:
        return f"{name}: played on cambc {cv}, which restat.py has no setup for"
    CLI, BASE, PROJ = ENGINES[cv]
    man = open(os.path.join(rundir, "manifest.txt")).read().split("\n")
    rec = {}
    for ln in open(os.path.join(rundir, "games.jsonl")):
        g = json.loads(ln)
        if g.get("ok"):
            rec[g["id"]] = g
    todo, changed = [], 0
    rd = os.path.abspath(rundir)
    for gid, g in rec.items():
        mp = os.path.join(BASE, "maps", g["map"] + ".map26a")
        if not os.path.exists(mp) or os.path.getmtime(mp) > t_run:
            changed += 1
            continue
        # the manifest names its outputs under the run dir it was written for: point them at RUNDIR, so a copied or
        # renamed run never writes into the original dir (or into another run that has since reused its name)
        f = man[int(gid) - 1].split()
        f[3] = os.path.join(rd, "rep", gid + ".repl26a")
        f[f.index("--statistics") + 1] = os.path.join(rd, "st", gid + ".json")
        todo.append(" ".join(f))
    if not todo:
        return f"{name}: nothing to replay ({changed} games on changed or missing maps)"
    os.makedirs(os.path.join(rundir, "st"), exist_ok=True)
    os.makedirs(os.path.join(rundir, "rep"), exist_ok=True)
    sub = os.path.join(rundir, ".restat_manifest.txt")
    open(sub, "w").write("\n".join(todo) + "\n")
    t0 = time.time()
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        t1 = time.time()
        subprocess.run(["rsync", "-a", os.path.join(BASE, "cambc.toml"), os.path.join(PROJ, "cambc.toml")])
        for d in ("maps", "sdk", "cmake"):
            subprocess.run(["rsync", "-a", os.path.join(BASE, d) + "/", os.path.join(PROJ, d) + "/"])
        with open(os.path.join(rundir, "restat.log"), "w") as log:
            rc = subprocess.run([CLI, "run-batch", sub, "--jobs", "12", "--release", "--log-limit", "0"], cwd=PROJ,
                                stdout=log, stderr=subprocess.STDOUT).returncode
    t2 = time.time()
    os.remove(sub)
    n = gamefeat.extract_run(rundir)
    if n == 0:  # no statistics at all: leave no empty games_rich.jsonl behind (it would block a rerun without --force)
        os.remove(os.path.join(rundir, "games_rich.jsonl"))
    bad, compared = [], 0
    for ln in open(os.path.join(rundir, "games_rich.jsonl")) if n else []:
        x = json.loads(ln)
        g = rec.get(x["id"])
        if g is None or "error" in x:
            continue
        compared += 1
        want = (g["win"], g["rounds"], g["sa"].get("gems"), g["sb"].get("gems"))
        got = (x["outcome"], x["rounds"], x["A"]["score"], x["B"]["score"])
        if want != got:
            bad.append((x["id"], want, got))
    if not keep:
        shutil.rmtree(os.path.join(rundir, "st"), ignore_errors=True)
        shutil.rmtree(os.path.join(rundir, "rep"), ignore_errors=True)
    msg = (f"{name}: replayed {len(todo)} games (waited {t1 - t0:.0f}s for the lock, played in {t2 - t1:.0f}s), features for {n}; "
           f"{len(bad)} of {compared} compared differ from the original results" + (f" (e.g. {bad[:2]})" if bad else "")
           + (f"; skipped {changed} games on changed maps" if changed else "")
           + (f"; !! only {n} of {len(todo)} replays produced statistics (run-batch exit {rc}, see "
              f"{os.path.join(rundir, 'restat.log')})" if n < len(todo) or rc else ""))
    return msg


if __name__ == "__main__":
    a = sys.argv[1:]
    keep, force = "--keep" in a, "--force" in a
    dirs = [x for x in a if not x.startswith("--")]
    if not dirs:
        print(__doc__)
        sys.exit(1)
    for d in dirs:
        print(restat(d, keep, force), flush=True)
