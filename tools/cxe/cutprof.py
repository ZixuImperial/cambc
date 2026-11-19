#!/usr/bin/env python3
"""cutprof: what spent the fuel in the rounds where the bot ran out (Tool builder 2, 5 Nov; owner: "check why our fuel runs out").
fuelprof names the function a turn was in when it ran dry; that is usually just the last thing the turn did. This plays each
map once to find the rounds with a fuel cut (replay turn END 1), then replays the game up to round R-1 and up to R with the
per-function profile on (cxe --rounds; games are deterministic), and the difference is what round R cost, function by function.

usage: python3 -I tools/cxe/cutprof.py BOT --mapdir DIR [--opp BOT2] [--diff [--per-map 3]] [--top 30]
  Each map is played once (the profiled bot as --seat A (default) or B; run twice for both seats) with the "cutprof" build (tools/cxe/w2c_cutprof.py): every fuel cut is
  credited to every function on the instance's call stack, so the report names the CALLERS that spent the cut turns
  (functions on the stack at X% of the cuts), not only the leaf where the fuel ran out.
  --diff     also replay each game to round R-1 and R for its first --per-map cut rounds and print what those rounds cost per
             function (three processes per cut round: keep it for a few maps; maple05's /var dislikes process churn)
Writes /data/zw4424/st/cxe/cutprof/<bot>_<stamp>/report.txt: per cut round (map, round, which side cut, the round's fuel and
top functions), then the functions summed over all cut rounds next to their share of an average round (what the cut rounds
spend that ordinary rounds don't)."""
import collections
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
import cxebuild  # noqa: E402
import wasmparse  # noqa: E402
from fuelprof import demangle  # noqa: E402


def run(exe, x, y, mp, out, rounds=None, prof=None):
    env = dict(os.environ)
    if prof:
        env["CXE_FUELPROF"] = prof
    cmd = ["nice", "-n", "19", exe, x, y, mp, out] + (["--rounds", str(rounds)] if rounds is not None else [])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    return r.stdout


def readprof(p):
    d = collections.defaultdict(collections.Counter)
    if os.path.exists(p):
        for ln in open(p):
            t, fi, f, _c = ln.split()
            v = int(f)
            if v >= 1 << 63:  # 12 Nov (TB, RC X633): a function undercounted across a fuel-slice refill wraps uint64 (~1.8e19); read it signed, floor 0
                v = max(0, v - (1 << 64))
            d[int(t)][int(fi)] += v
        os.remove(p)
    return d


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("--") or "--mapdir" not in a:
        sys.exit(__doc__)
    bot = a[0]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    if "--seats" in a:  # 12 Nov (RC: --seats 2 was silently ignored; one run profiled seat A only)
        sys.exit("cutprof: no --seats; run once with --seat A and once with --seat B")
    opp, mapdir = opt("--opp", bot), opt("--mapdir", None)
    per_map, top, diff = int(opt("--per-map", 3)), int(opt("--top", 30)), "--diff" in a
    # 12 Nov (RC X538: 191 of 296 cuts were seat B, never profiled): --seat B plays the profiled bot as team B
    TS = 1 if str(opt("--seat", "A")).upper() == "B" else 0
    import replay as R
    exe = cxebuild.build_host()
    so_p = cxebuild.build_bot(bot, "cutprof")
    so_o = cxebuild.build_bot(opp)  # the playing build: same fuel, same game; its cuts stay out of the stack counts
    out = os.path.join(cxebuild.ROOT, "cutprof", f"{os.path.basename(os.path.normpath(bot))}_{time.strftime('%m%d%H%M%S')}_{os.getpid()}")
    os.makedirs(out, exist_ok=True)
    maps = sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a"))
    cut_rows, tot_cut, tot_all, rounds_all = [], collections.Counter(), collections.Counter(), 0
    icut, ncut = collections.Counter(), 0
    nowhole = 0
    stacks = []  # 12 Nov (RC X531): (map, [func index bottom..top]) per cut, from the CXE_CUTSTK file
    for i, m in enumerate(maps):
        mp = os.path.join(mapdir, m)
        g0 = f"{out}/m{i}"
        os.environ["CXE_CUTPROF"] = f"{g0}.cs"
        os.environ["CXE_CUTSTK"] = f"{g0}.stk"
        full = run(exe, *((so_o, so_p) if TS else (so_p, so_o)), mp, g0, prof=f"{g0}.fp")
        del os.environ["CXE_CUTPROF"], os.environ["CXE_CUTSTK"]
        if os.path.exists(f"{g0}.stk"):
            for ln in open(f"{g0}.stk"):
                x = ln.split()
                if x and x[0] == "S":
                    stacks.append((m, [int(v) for v in x[1:]]))
            os.remove(f"{g0}.stk")
        whole = readprof(f"{g0}.fp")
        if not whole.get(TS):  # 12 Nov (RC X633: avg-round share read 0.00% in four batch runs): count games whose whole-game profile came back empty
            nowhole += 1
        if os.path.exists(f"{g0}.cs"):
            for ln in open(f"{g0}.cs"):
                x = ln.split()
                if x[0] == "N":
                    ncut += int(x[1])
                elif x[0] == "I":
                    icut[int(x[1])] += int(x[2])
            os.remove(f"{g0}.cs")
        rep = f"{g0}.repl26a"
        if not os.path.exists(rep):
            print(f"{m}: no replay ({full.strip()[-120:]})")
            continue
        g = R.load(rep, "B" if TS else "A")
        nr = g.last_round
        rounds_all += nr
        for t in (TS,):  # our bot's team in this game (the other is the same bot when no --opp)
            tot_all.update(whole[t])
        cuts = collections.Counter()
        for tr in g.turns:
            if tr[g.ci["end"]] == 1 and g.team_of[tr[1]] == TS:
                cuts[tr[0]] += 1
        if os.environ.get("CUTPROF_BODIES"):  # 12 Nov (TB; Planner: which body / kit was cut): one line per cut turn of the profiled team
            with open(os.environ["CUTPROF_BODIES"], "a") as bf:
                for tr in g.turns:
                    if tr[g.ci["end"]] == 1 and g.team_of[tr[1]] == TS:
                        bf.write(f"{m}\t{'AB'[TS]}\t{tr[0]}\t{tr[1]}\t{g.who(tr[1])}\n")
        os.remove(rep)
        for r in (sorted(cuts)[:per_map] if diff else []):
            pa, pb = f"{g0}_r{r - 1}.fp", f"{g0}_r{r}.fp"
            run(exe, *((so_o, so_p) if TS else (so_p, so_o)), mp, f"{g0}_a", rounds=r - 1, prof=pa)  # 11 Nov (RC X268 CPR1): round 1's baseline is --rounds 0 (the draft alone)
            run(exe, *((so_o, so_p) if TS else (so_p, so_o)), mp, f"{g0}_b", rounds=r, prof=pb)
            for q in (f"{g0}_a.repl26a", f"{g0}_b.repl26a"):
                if os.path.exists(q):
                    os.remove(q)
            A, B = readprof(pa), readprof(pb)
            d = collections.Counter({fi: B[TS][fi] - A[TS].get(fi, 0) for fi in B[TS] if B[TS][fi] - A[TS].get(fi, 0) > 0})
            tot_cut.update(d)
            cut_rows.append((m, r, cuts[r], sum(d.values()), d))
        print(f"{m}: {nr} rounds, {sum(cuts.values())} cut turns of team {"B" if TS else "A"} in {len(cuts)} rounds; profiled {min(per_map, len(cuts))}", flush=True)
    mod = wasmparse.Module(cxebuild.wasm_of(bot, release=False))
    ids = set(tot_cut) | set(tot_all) | set(icut) | {fi for _, st in stacks for fi in st}
    raw = {fi: mod.names.get(fi, f"f{fi}") for fi in ids}
    dm = demangle(sorted(set(raw.values())))
    nm = {fi: dm.get(r, r)[:110] for fi, r in raw.items()}
    if stacks:  # one row per cut: map, depth, the stack bottom -> top (the leaf last); stack_counts.tsv: identical stacks counted
        with open(os.path.join(out, "stacks.tsv"), "w") as f:
            f.write("map\tdepth\tstack (bottom > top)\n")
            for mname, st in stacks:
                f.write(f"{mname}\t{len(st)}\t{' > '.join(nm.get(fi, f'f{fi}') for fi in st)}\n")
        sc = collections.Counter(tuple(st) for _, st in stacks)
        with open(os.path.join(out, "stack_counts.tsv"), "w") as f:
            f.write("cuts\tstack (bottom > top)\n")
            for st, c in sc.most_common():
                f.write(f"{c}\t{' > '.join(nm.get(fi, f'f{fi}') for fi in st)}\n")
    L = [f"cutprof {bot} v {opp}: {len(maps)} maps, {ncut} fuel cuts of {bot} (team {"B" if TS else "A"})", "",
         "functions on the call stack at the cuts (a function at 100% runs in every turn: the turn loop; read down to the first",
         "specific ones: they started the work that ran the turn dry):", f"{'cuts':>6} {'share':>6}  function"]
    for fi, v in icut.most_common(top + 15):
        L.append(f"{v:6d} {100 * v / max(1, ncut):5.1f}%  {nm[fi]}")
    L.append("")
    for m, r, n, f, d in cut_rows:
        L.append(f"{m} r{r}: {n} of our turns cut; the round cost {f:,} fuel; top: " + "; ".join(f"{nm[fi][:60]} {v:,}" for fi, v in d.most_common(5)))
    if not cut_rows:  # 12 Nov (RC: "29 cuts but 0 cut rounds" read as a bug): the per-round table needs --diff (R-1 v R replays)
        L += ["", "per-round cost of the cut rounds: not measured (run with --diff [--per-map N] for it)"]
    L += ["", f"summed over the {len(cut_rows)} cut rounds, against an average round of these games ({rounds_all} rounds):",
          f"{'cut-round fuel':>15} {'share':>6} {'avg-round share':>15}  function"]
    tc, ta = sum(tot_cut.values()) or 1, sum(tot_all.values()) or 1
    if nowhole or not tot_all:
        L.append(f"!! average-round baseline: {nowhole} of {len(maps)} games returned no whole-game profile for team {'AB'[TS]}"
                 + (" (column below is meaningless)" if not tot_all else " (column below covers the others)"))
    for fi, v in tot_cut.most_common(top):
        L.append(f"{v:15,} {100 * v / tc:5.1f}% {100 * tot_all[fi] / ta:14.2f}%  {nm[fi]}")
    open(f"{out}/report.txt", "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nreport: {out}/report.txt")


if __name__ == "__main__":
    main()
