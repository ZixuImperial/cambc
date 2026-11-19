"""cxeident: is NEW play-identical to OLD, and how much fuel does it save? The fast check for fuel work (refactors,
caching, bakes) on cxe, the native engine (game-identical to the CLI).
  1. identity: OLD v OPP and NEW v OPP on N maps x 2 seats at unlimited fuel (--fuel 1e9: no cut-offs, fuel_remaining
     never binds): the replays must be byte-identical game by game (the same moves) - the mergecheck 'null identity' read
  2. fuel at unlimited fuel: the bot side's total fuel per game, NEW v OLD (pure cost of the same work)
  3. real budget (100k): the bot side's mean fuel per turn and its fuel cut-offs per game (what the saving buys)
  4. optional --where: per-function fuel of both (fuelprof builds) and the functions whose fuel changed most
usage: python3 -I tools/cxe/cxeident.py OLD NEW [--opp BOT] [--maps 20] [--seed 1] [--jobs 8] [--where] [--budget] [--logic] [--mapdir DIR]\n--logic: identity with fuel_remaining() held constant (cxe CXE_FUEL_CONST): play changes that come only from the bot's\n  self-measured fuel costs don't count, logic changes still do; the fuel lines then read 0.
--budget: 100k games only (owner 7 Nov: no unlimited-fuel tests); a differing game counts as a play change unless either side had a
  fuel cut-off in it; last line 'CHANGED p/ng'.
Games play on the Condor pilots (pilotcxe.py) when pilots are alive, else locally; PILOTCXE=0 / CXE_LOCAL=1 forces local;
CXEIDENT_PILOTS_ONLY=1: never local (exit 3 when the pilots did not play every game).
OPP defaults to OLD. Exit 0 = identical on every game, 1 = some game differs."""
import collections
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402

MAPDIR = "/data/USER/ablproj_4.0.0/maps"


def run_all(exe, games, jobs, out, env=None):
    """games: [(key, so_a, so_b, map path, extra args)] -> runs them: on the Condor pilots first (tools/cxe/pilotcxe.py: the same
    engine and libraries, byte-identical games; owner 6 Nov: "make condor do more work"), local cxe slots via cxerun as the fallback.
    PILOTCXE=0 or CXE_LOCAL=1: local only."""
    try:
        import pilotcxe
        if pilotcxe.run([(a, b, mp, f"{out}/{key}", extra) for key, a, b, mp, extra in games],
                        say=lambda m: print(f"  {m}", file=sys.stderr), env=env):
            return
    except Exception as e:  # noqa: BLE001  the local path below always works
        print(f"  pilotcxe failed ({str(e)[:120]}): local", file=sys.stderr)
    if os.environ.get("CXEIDENT_PILOTS_ONLY") == "1":  # 7 Nov (owner: identity on pilots only, never local): exit 3 = not run
        print("cxeident: pilots did not play every game and CXEIDENT_PILOTS_ONLY=1: identity NOT RUN (exit 3)", flush=True)
        sys.exit(3)
    man = os.path.join(out, f"m{int(time.time() * 1000) % 10 ** 9}.txt")
    with open(man, "w") as f:
        for key, a, b, mp, extra in games:
            f.write(f"{a} {b} {mp} {out}/{key} {extra}\n")
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "cxerun.py"), man, "--jobs", str(jobs)], capture_output=True, text=True)
    os.remove(man)


def side_fuel(path, team):
    """(sum of the team's per-turn fuel, turns, cut turns) from a --fuel-log tsv."""
    s = n = cuts = 0
    if not os.path.exists(path):  # --logic plays no 100k games
        return 0, 0, 0
    for ln in open(path).read().splitlines()[1:]:
        r = ln.split("\t")
        if r[2] == str(team):
            s += int(r[6])
            n += 1
            cuts += r[7] == "2"
    return s, n, cuts


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith("--"):
        sys.exit(__doc__)
    old, new = a[0], a[1]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    opp = opt("--opp", old)
    global MAPDIR
    MAPDIR = opt("--mapdir", MAPDIR)  # 11 Nov (b1966): identity on a chosen map dir (fresh or w_manygrp draws); default the saved pool
    n = int(opt("--maps", 20))
    jobs = int(opt("--jobs", 8))
    maps = random.Random(int(opt("--seed", 1))).sample(sorted(f for f in os.listdir(MAPDIR) if f.endswith(".map26a")), n)
    exe = cxebuild.build_host()
    so = {b: cxebuild.build_bot(b) for b in {old, new, opp}}
    # 9 Nov 21:55Z (Builder, b1777: two identity runs on the same pair in the same second shared this dir, a replay vanished mid-check and
    # identity failed with no bot diff): the run dir carries the pid too, so concurrent runs never share it
    out = os.path.join(cxebuild.ROOT, "ident", f"{os.path.basename(old)}_v_{os.path.basename(new)}_{time.strftime('%m%d%H%M%S')}_{os.getpid()}")
    os.makedirs(out, exist_ok=True)
    games = []
    for i, m in enumerate(maps):
        mp = os.path.join(MAPDIR, m)
        for seat in (0, 1):
            for who in ("o", "n"):
                me = so[old if who == "o" else new]
                x, y = (me, so[opp]) if seat == 0 else (so[opp], me)
                games.append((f"u{i}{seat}{who}", x, y, mp, "--fuel 1000000000 --fuel-log"))
                games.append((f"r{i}{seat}{who}", x, y, mp, "--fuel-log"))
    t0 = time.time()
    env = None
    if "--logic" in a:  # 8 Nov: logic-only identity: fuel_remaining() constant, so cost-only changes (the bot's self-measured costs) don't count
        env = {"CXE_FUEL_CONST": "1000000000"}
        os.environ.update(env)  # the local fallback inherits it
        games = [g for g in games if g[0][0] == "u"]
    if "--budget" in a:  # 7 Nov (owner: no unlimited-fuel tests): identity at the real 100k budget only
        return budget_ident(exe, [g for g in games if g[0][0] == "r"], jobs, out, maps, old, new, opp, n, t0)
    run_all(exe, games, jobs, out, env)
    same, diff, fu = 0, [], collections.Counter()
    real = {"o": [0, 0, 0], "n": [0, 0, 0]}
    real_same = {"o": [0, 0, 0], "n": [0, 0, 0]}  # 12 Nov (RC): 100k fuel over the games that played IDENTICALLY at 100k (a reshuffle is not code cost)
    rsame = 0
    for i, m in enumerate(maps):
        for seat in (0, 1):
            ro, rn = f"{out}/u{i}{seat}o.repl26a", f"{out}/u{i}{seat}n.repl26a"
            if os.path.exists(ro) and os.path.exists(rn) and open(ro, "rb").read() == open(rn, "rb").read():
                same += 1
            else:
                diff.append(f"{m[:-7]} seat {'AB'[seat]}")
            qo, qn = f"{out}/r{i}{seat}o.repl26a", f"{out}/r{i}{seat}n.repl26a"
            ident100 = os.path.exists(qo) and os.path.exists(qn) and open(qo, "rb").read() == open(qn, "rb").read()
            rsame += ident100
            for who in ("o", "n"):
                fu[who] += side_fuel(f"{out}/u{i}{seat}{who}.fuel.tsv", seat)[0]
                s, t, c = side_fuel(f"{out}/r{i}{seat}{who}.fuel.tsv", seat)
                real[who][0] += s
                real[who][1] += t
                real[who][2] += c
                if ident100:
                    real_same[who][0] += s
                    real_same[who][1] += t
                    real_same[who][2] += c
    for f in os.listdir(out):
        if f.endswith((".repl26a", ".fuel.tsv")):
            os.remove(os.path.join(out, f))
    ng = 2 * n
    pct = lambda x, y: 100.0 * (y - x) / x if x else 0.0
    lines = [f"cxeident {old} -> {new} (opponent {opp}): {n} maps x 2 seats, {time.time() - t0:.0f} s",
             f"  identity at unlimited fuel : {same}/{ng} games byte-identical{' (logic only: fuel_remaining constant)' if env else ''}" + ("" if not diff else f"  DIFFER: {', '.join(diff[:6])}"),
             f"  fuel, same work (unlimited): {fu['o'] / ng:,.0f} -> {fu['n'] / ng:,.0f} per game ({pct(fu['o'], fu['n']):+.2f}%)",
             f"  real budget: fuel/turn {real['o'][0] / max(real['o'][1], 1):,.0f} -> {real['n'][0] / max(real['n'][1], 1):,.0f} "
             f"({pct(real['o'][0] / max(real['o'][1], 1), real['n'][0] / max(real['n'][1], 1)):+.2f}%), "
             f"fuel cut-offs {real['o'][2] / ng:.2f} -> {real['n'][2] / ng:.2f} per game (all {ng} games; {ng - rsame} played differently at 100k)",
             f"  real budget, identical games only ({rsame}/{ng} played byte-identically at 100k): fuel/turn "
             f"{real_same['o'][0] / max(real_same['o'][1], 1):,.0f} -> {real_same['n'][0] / max(real_same['n'][1], 1):,.0f} "
             f"({pct(real_same['o'][0] / max(real_same['o'][1], 1), real_same['n'][0] / max(real_same['n'][1], 1)):+.2f}%): the code cost without the reshuffle"]
    if "--where" in a:
        import fuelprof  # noqa: F401  (per-function view through fuelprof's builds)
        prof = {}
        for b in (old, new):
            sp = cxebuild.build_bot(b, "fuelprof")
            tot = collections.Counter()
            for i, m in enumerate(maps[:min(n, 8)]):
                fp = f"{out}/fp.tsv"
                subprocess.run([exe, sp, so[opp], os.path.join(MAPDIR, m), f"{out}/w", "--fuel", "1000000000"],
                               env=dict(os.environ, CXE_FUELPROF=fp), capture_output=True)
                for ln in open(fp):
                    t, fi, f, c = ln.split()
                    if t == "0":
                        tot[int(fi)] += int(f)
            import wasmparse
            names = wasmparse.Module(cxebuild.wasm_of(b, release=False)).names
            prof[b] = collections.Counter({names.get(k, f"f{k}"): v for k, v in tot.items()})
        dm = fuelprof.demangle(sorted(set(prof[old]) | set(prof[new])))
        delta = collections.Counter({k: prof[new].get(k, 0) - prof[old].get(k, 0) for k in set(prof[old]) | set(prof[new])})
        # 5 Nov (fx agent): the list used to show only the 10 biggest DECREASES, so a change whose savings were outweighed
        # elsewhere (FXH-LZ: heap pops cost what the sort saved) looked like a gain; now the net and both directions.
        net = sum(delta.values())
        lines.append(f"  per-function fuel, unlimited fuel, first {min(n, 8)} maps, team A: net {net:+,d} "
                     f"({100.0 * net / max(1, sum(prof[old].values())):+.2f}% of OLD)")
        lines.append("  biggest decreases:")
        for k, v in sorted(delta.items(), key=lambda kv: kv[1])[:10]:
            if v < 0:
                lines.append(f"    {v:+14,d}  {dm.get(k, k)[:120]}")
        lines.append("  biggest increases:")
        for k, v in sorted(delta.items(), key=lambda kv: -kv[1])[:10]:
            if v > 0:
                lines.append(f"    {v:+14,d}  {dm.get(k, k)[:120]}")
    rep = "\n".join(lines)
    open(os.path.join(out, "report.txt"), "w").write(rep + "\n")
    print(rep)
    return 0 if not diff else 1


def budget_ident(exe, games, jobs, out, maps, old, new, opp, n, t0):
    """--budget: OLD and NEW v OPP at 100k only, both seats. A game whose replays differ is a PLAY CHANGE unless either side had a
    fuel cut-off in it (then it is the fuel reshuffle: a cut turn's moves depend on fuel). Prints 'CHANGED p/ng' (p = play changes);
    exit 0 when p == 0, 1 otherwise."""
    run_all(exe, games, jobs, out)
    same, cut, chg, miss = 0, [], [], 0
    for i, m in enumerate(maps):
        for seat in (0, 1):
            ro, rn = f"{out}/r{i}{seat}o.repl26a", f"{out}/r{i}{seat}n.repl26a"
            if not (os.path.exists(ro) and os.path.exists(rn)):
                miss += 1
                continue
            if open(ro, "rb").read() == open(rn, "rb").read():
                same += 1
                continue
            cuts = sum(side_fuel(f"{out}/r{i}{seat}{w}.fuel.tsv", seat)[2] for w in ("o", "n"))
            (cut if cuts else chg).append(f"{m[:-7]} seat {'AB'[seat]}")
    for f in os.listdir(out):
        if f.endswith((".repl26a", ".fuel.tsv")):
            os.remove(os.path.join(out, f))
    ng = 2 * n - miss
    lines = [f"cxeident --budget {old} -> {new} (opponent {opp}): {n} maps x 2 seats at 100k, {time.time() - t0:.0f} s",
             f"  identity at 100k: {same}/{ng} games byte-identical; {len(cut)} differ with a fuel cut-off on either side (reshuffle); "
             f"{len(chg)} play changes" + (f": {', '.join(chg[:6])}" if chg else "") + (f"; {miss} games missing" if miss else ""),
             f"CHANGED {len(chg)}/{ng}"]
    rep = "\n".join(lines)
    open(os.path.join(out, "report.txt"), "w").write(rep + "\n")
    print(rep)
    return 0 if not chg and not miss else 1


if __name__ == "__main__":
    sys.exit(main())
