"""cxefork: rollouts from one game state. Each game plays BASE v OPP to the first turn of round R, then cxe forks one child per
ALT (one at a time); in the child, BASE's instances get ALT's data bytes (an ALT must be a data flip of BASE: identical code),
and every branch plays on to round R+K-1 (or the end). The base branch is the parent game itself, so base and ALT share every
turn before R exactly (checked: a fork at 0 equals the straight ALT game byte for byte; an identity fork equals the straight
base game; the parent is unchanged by forking).
usage: python3 -I tools/cxe/cxefork.py BASE OPP --at R [--k K] --alt FLIP [--alt FLIP2 ...] [--maps N | --maplist FILE]
           [--mapdir DIR] [--seed 1] [--seats AB|A|B] [--jobs 4] [--record] [--out DIR]
Branch value per team (V = tributed gems + carried gems + .35 x earned gold, as the ceiling ledgers count it) and kills come
from each branch's replay at its last round (the engine's statistics are empty for a game stopped before its end). Prints, per ALT, its paired change against the base branch
over all games (us minus them in V, wins at the end when games finish) and writes OUT/branches.tsv (one row per game x branch).
Games run through cxerun's machine-wide slots (owner 4 Nov: keep HOST's CPU low). Raw cxe: cxe A.so B.so MAP OUT
--fork-at R [--fork-k K] [--alt-team A|B] --alt ALT.so ... (README 'Fork')."""
import math
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402
import cxedec  # noqa: E402
import wasmparse  # noqa: E402

MAPDIR = "/data/USER/ablproj_4.0.0/maps"


def code_of(wasm):
    """Everything but the data segments' bytes (a data flip leaves all of it unchanged)."""
    m = wasmparse.Module(wasm)
    return (repr((m.types, m.imports, m.funcs, m.tables, m.mems, m.globals, m.exports, m.elems, m.start)),
            [bytes(b[s:e]) for b, s, e in m.bodies], [(k, o, len(d)) for k, o, d in m.datas])


def check_flip(base, alt):
    if code_of(cxebuild.wasm_for(base)) != code_of(cxebuild.wasm_for(alt)):
        sys.exit(f"cxefork: {alt} is not a data flip of {base} (code or data layout differs); build it with flip.sh on {base}")


def branch(replay):
    """-> (last round, outcome 0 none/1 A/2 B, {team: (V, kills)}) from the replay's last per-round row."""
    d = cxedec.decode(replay)
    if not d:
        return None
    c = {k: i for i, k in enumerate(d["roundCols"])}
    row = d["rounds"][-1]
    val = {t: (row[c["sub" + t]] + row[c["carried" + t]] + 0.35 * row[c["earned" + t]], row[c["kills" + t]]) for t in "AB"}
    return row[0], (d.get("final") or {}).get("outcome", 0), val


def main():
    a = sys.argv[1:]
    if len(a) < 2 or "--at" not in a or "--alt" not in a:
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    base, opp = a[0], a[1]
    alts = [a[i + 1] for i, x in enumerate(a) if x == "--alt"]
    R, K = int(opt("--at")), int(opt("--k", "0"))
    for x in alts:
        check_flip(base, x)
    so = {b: cxebuild.build_bot(b) for b in [base, opp] + alts}
    mapdir = opt("--mapdir", MAPDIR)
    if opt("--maplist"):
        maps = [ln.strip() for ln in open(opt("--maplist")) if ln.strip()]
    else:
        maps = random.Random(int(opt("--seed", "1"))).sample(sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a")), int(opt("--maps", "10")))
    maps = [m if os.path.isabs(m) else os.path.join(mapdir, m if m.endswith(".map26a") else m + ".map26a") for m in maps]
    out = opt("--out") or os.path.join(cxebuild.ROOT, "fork", f"{base}_{R}_{time.strftime('%m%d%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    fa = ["--fork-at", str(R)] + (["--fork-k", str(K)] if K else []) + sum((["--alt", so[x]] for x in alts), [])
    rec = ["--record"] if "--record" in a else []
    games = []
    with open(os.path.join(out, "manifest.txt"), "w") as f:
        for i, m in enumerate(maps):
            for seat in opt("--seats", "AB"):
                pre = os.path.join(out, f"g{i}{seat}")
                pair = (so[base], so[opp]) if seat == "A" else (so[opp], so[base])
                f.write(" ".join(list(pair) + [m, pre] + fa + (["--alt-team", "B"] if seat == "B" else []) + rec) + "\n")
                games.append((pre, os.path.basename(m)[:-7], seat))
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "cxerun.py"), os.path.join(out, "manifest.txt"),
                        "--jobs", opt("--jobs", "4")], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:] + r.stderr[-2000:])
    rows, delta = [], {x: [] for x in alts}
    for pre, mp, seat in games:
        us, th = seat, "AB"[seat == "A"]
        br = {}
        for j, name in [(-1, base)] + list(enumerate(alts)):
            p = pre + (f".alt{j}" if j >= 0 else "") + ".repl26a"
            b = branch(p) if os.path.exists(p) else None
            if not b:
                continue
            rnd, oc, val = b
            (vu, ku), (vt, kt) = val[us], val[th]
            win = 0.5 if not oc else float("AB"[oc - 1] == us)
            br[name] = (vu - vt, win, open(p, "rb").read())
            rows.append(f"{mp}\t{seat}\t{name}\t{rnd}\t{vu:.0f}\t{vt:.0f}\t{ku}\t{kt}\t{'-AB'[oc]}")
        if base in br:
            for x in alts:
                if x in br:
                    delta[x].append((br[x][0] - br[base][0], br[x][1] - br[base][1], br[x][2] != br[base][2]))
    open(os.path.join(out, "branches.tsv"), "w").write("map\tseat\tbranch\tlast_round\tV_us\tV_them\tkills_us\tkills_them\twinner\n" + "\n".join(rows) + "\n")
    print(f"cxefork {base} v {opp}: fork at round {R}" + (f", {K} rounds on" if K else ", to the end") + f"; {len(games)} games, {time.time() - t0:.0f} s")
    for x in alts:
        d = delta[x]
        if not d:
            print(f"  {x}: no paired games")
            continue
        n = len(d)
        mv = sum(v for v, _, _ in d) / n
        sv = math.sqrt(sum((v - mv) ** 2 for v, _, _ in d) / max(n - 1, 1) / n)
        ch = sum(1 for v, _, _ in d if v)
        pl = sum(1 for _, _, c in d if c)
        dw = sum(w for _, w, _ in d)
        print(f"  {x}: V(us - them) change {mv:+.1f} [{mv - 1.96 * sv:+.1f}, {mv + 1.96 * sv:+.1f}] over {n} games (play changed in {pl}, value in {ch}); "
              f"wins {dw:+.1f}")
    print(f"branches: {out}/branches.tsv")


if __name__ == "__main__":
    main()
