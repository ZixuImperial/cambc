#!/usr/bin/env python3
"""faultcheck: does BOT crash or run out of fuel with its flags ON? (8 Nov, Builder: sfx2 passed prearm, whose identity runs at flag 0 and
whose firecount runs a DEBUG build, then hit 276 bot faults and 42,327 fuel cut-offs v live's 314 at shipcheck.)

usage: python3 -I tools/lab/faultcheck.py BOT "FLAG=V ..." [--maps 100] [--vs BOT2] [--keep]
  1. flip.sh BOT nova_fltc_<pid> FLIPS: the RELEASE build with the flips (flip.sh's data-patched wasm, seconds; the same build path
     armq's candidates take);
  2. it plays --vs (default live) on --maps new unsaved maps (stratmaps, half pathological), both seats, 100k fuel, on the pilots;
  3. per side from cxe's --statistics: bot faults (trap or exit) and fuel cut-offs.
  FAIL: any fault on BOT's side, or a fuel runaway: BOT's cut-offs (capped at 5 a game, as shipcheck's cap5 row) over 2x the
  opponent's in the same games AND a one-sided sign test p < .01 (sfx2: 16 v 4 on 100 maps, 9 v 0 and 156 v 1 on 40; clean flips read
  1 v 1 and 4 v 4). A disaster catcher only: shipcheck's fuel rows judge small changes.
  Also FAIL: a game whose engine stdout came back without statistics (the game died inside cxe).
  The temp bot and maps go at the end through rmdata.sh (--keep keeps them).
Prints 'FAULTCHECK PASS|FAIL ...' last. Exit 0 PASS, 1 FAIL, 2 could not run. Logs: /data/USER/st/faultcheck/TAG/."""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = f"{REPO}/tools/lab"
ROOT = "/data/USER/st/faultcheck"
sys.path.insert(0, LAB)
sys.path.insert(0, f"{REPO}/tools/cxe")


def say(s):
    print(f"{time.strftime('%H:%M:%S')} {s}", flush=True)


def side_stats(p, team):
    try:
        d = json.load(open(p))
    except (OSError, ValueError):
        return None
    f = int(d.get("diagnostics", {}).get("botFaults", {}).get(team, 0))
    c = sum(len(e.get("entries", [])) for e in d.get("events", []) if e.get("kind") == "fuelExhausted" and e.get("owner", {}).get("team") == team)
    # 13 Nov (Builder, PTF 143 v 16 'RUNAWAY', nearly all after the actions): a marker bot's after-action cut-offs (cxe fuelExhaustedAfterActions,
    # 0 for every other bot) are information, as in shipcheck's PCQ split: the row counts the cut-offs before the turn's actions
    c -= sum(len(e.get("entries", [])) for e in d.get("events", []) if e.get("kind") == "fuelExhaustedAfterActions" and e.get("owner", {}).get("team") == team)
    return f, c


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith("-"):
        print(__doc__)
        return 2
    bot, fl = a[0], a[1]
    nmaps = int(a[a.index("--maps") + 1]) if "--maps" in a else 100
    vs = a[a.index("--vs") + 1] if "--vs" in a else open("/data/USER/st/bq/live.txt").readline().split()[1]
    keep = "--keep" in a
    tag = "fl" + time.strftime("%m%d%H%M%S", time.gmtime()) + f"_{os.getpid()}"
    run = os.path.join(ROOT, tag)
    os.makedirs(run)
    t0 = time.time()
    tmp = f"nova_fltc_{os.getpid()}"
    rm = []
    try:
        r = subprocess.run(["sh", f"{LAB}/flip.sh", bot, tmp, fl], capture_output=True, text=True, cwd=REPO)
        if os.path.lexists(os.path.join(REPO, "bots", tmp)):
            rm += [os.path.realpath(os.path.join(REPO, "bots", tmp)), os.path.join(REPO, "bots", tmp)]
        if r.returncode:
            print(f"FAULTCHECK ERROR: flip.sh failed: {(r.stdout + r.stderr).strip()[-300:]}")
            return 2
        import cxebuild
        import cxefarm
        so, so_vs = cxebuild.build_bot(tmp), cxebuild.build_bot(vs)
        say(f"{bot} + {fl} (release) v {vs}: built in {time.time() - t0:.0f} s")
        md = os.path.join(run, "maps")
        r = subprocess.run([sys.executable, "-I", f"{LAB}/stratmaps.py", md, "--n", str(nmaps), "--take", "--who", "faultcheck", "--weird", "0.5", "--light"],
                           capture_output=True, text=True)
        maps = sorted(glob.glob(os.path.join(md, "*.map26a")))
        if not maps:
            print(f"FAULTCHECK ERROR: no maps ({(r.stdout + r.stderr).strip()[-200:]})")
            return 2
        gd = os.path.join(run, "g")
        os.makedirs(gd)
        games = []
        for k, m in enumerate(maps):
            for seat in "AB":
                games.append(dict(id=len(games), a=so if seat == "A" else so_vs, b=so_vs if seat == "A" else so, map=m,
                                  args=["--statistics", "@D@/g.json"], files={"g.json": os.path.join(gd, f"g{k}{seat}.json"), "stdout": os.path.join(gd, f"g{k}{seat}.out")}, digest=True,
                                  seat=seat, mapname=os.path.basename(m)[:-7]))
        os.environ["CXEFARM"] = "1"
        t1 = time.time()
        cxefarm.run(games, say=lambda s: None, per=10, cpus=8, prio=int(os.environ.get("FAULTCHECK_PRIO", "20")))
        me = {"faults": 0, "cuts": 0}
        op = {"faults": 0, "cuts": 0}
        bad, n, crash = [], 0, []
        for g in games:
            p = g["files"]["g.json"]
            us, them = ("teamA", "teamB") if g["seat"] == "A" else ("teamB", "teamA")
            x, y = side_stats(p, us), side_stats(p, them)
            if x is None or y is None:
                # 8 Nov: sfx2 batches came back 192/200, 197/200, clean flips 200/200: the engine's own stdout came back but no
                # statistics = the game died inside cxe (a crash the CLI counts as a bot fault); nothing back = a pilot loss (ignored)
                o = g["files"]["stdout"]
                if os.path.exists(o):
                    tail = [ln.strip() for ln in open(o, errors="replace") if ln.strip()][-1:] or ["(empty)"]
                    crash.append(f"{g['mapname']}/{g['seat']}: {tail[0][:100]}")
                continue
            n += 1
            me["faults"] += x[0]
            me["cuts"] += min(5, x[1])  # capped per game as shipcheck's cap5 row: one runaway map must not decide alone
            op["faults"] += y[0]
            op["cuts"] += min(5, y[1])
            if x[0]:
                bad.append(f"{g['mapname']}/{g['seat']}")
        say(f"{n} of {len(games)} games back in {time.time() - t1:.0f} s")
        if n < max(4, len(games) // 2):
            print(f"FAULTCHECK ERROR: only {n} of {len(games)} games came back  [logs {run}]")
            return 2
        k, m = me["cuts"], op["cuts"]
        pv = sum(math.comb(k + m, i) for i in range(k, k + m + 1)) / 2 ** (k + m) if k + m else 1.0  # P(>= k of k+m | equal rates)
        runaway = k > 2 * m and pv < 0.01
        ok = me["faults"] == 0 and not runaway and not crash
        why = (f"faults {me['faults']} (v {op['faults']})" + (f" on {', '.join(bad[:4])}" if bad else "")
               + (f"; {len(crash)} game(s) died in the engine ({crash[0]})" if crash else "")
               + f"; fuel cut-offs (cap 5/game) {k} v {m}, p {pv:.3g}{' RUNAWAY' if runaway else ''}, in {n} games")
        print(f"FAULTCHECK {'PASS' if ok else 'FAIL'} {bot} {fl}: {why} ({time.time() - t0:.0f} s)  [logs {run}]", flush=True)
        return 0 if ok else 1
    finally:
        if not keep:
            shutil.rmtree(os.path.join(run, "g"), ignore_errors=True)
            shutil.rmtree(os.path.join(run, "maps"), ignore_errors=True)
            if rm:
                lst = os.path.join(run, "rm.txt")
                open(lst, "w").write("\n".join(rm) + "\n")
                subprocess.run(["sh", f"{LAB}/rmdata.sh", lst], capture_output=True, text=True)


if __name__ == "__main__":
    sys.exit(main())
