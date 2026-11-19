#!/usr/bin/env python3
"""callmax: each function's worst-case fuel PER CALL (inclusive: its callees and host charges), measured, so a guard can be "skip this step
when fuel left < its measured worst case" instead of a 40-60k floor (Tool Builder, 8 Nov; owner via the Coordinator). Plays BOT (the
"callmax" build, tools/cxe/w2c_callmax.py) v itself on every map in MAPDIR on the pilots, both seats, and merges the per-call records.
usage: python3 -I tools/cxe/callmax.py BOT MAPDIR [--top 60] [--min-calls 20] [--match REGEX] [--local]
Report: /data/USER/st/cxe/callmax/<bot>_<stamp>/report.txt (max, p99, p99.9, mean per function) and callmax.tsv (every function).
Caveats: a call that crossed a fuel cut or slice refill (draft and first turns) is counted as 'crossed', not measured; a frame left by an
exception (an AF bail) records nothing, so a step that bails is measured only on its completed calls. Fuel is the playing build's
(the added counters spend no fuel); the build differs from the playing one only in its counters."""
import glob
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402
import wasmparse  # noqa: E402
from fuelprof import demangle  # noqa: E402

ROOT = "/data/USER/st/cxe/callmax"
NB = 40


def pct(h, q):
    n = sum(h)
    if not n:
        return 0
    k, acc = q * n, 0
    for b, c in enumerate(h):
        acc += c
        if acc >= k:
            return 2 ** (b + 1)  # upper edge of the bucket: conservative
    return 2 ** NB


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    bot, mapdir = a[0], a[1]
    opt = lambda k, d, f=str: f(a[a.index(k) + 1]) if k in a else d  # noqa: E731
    top, minc, match = opt("--top", 60, int), opt("--min-calls", 20, int), opt("--match", None)
    out = f"{ROOT}/{bot}_{time.strftime('%m%d%H%M%S', time.gmtime())}_{os.getpid()}"
    os.makedirs(out)
    so = cxebuild.build_bot(bot, "callmax")
    so = so if isinstance(so, str) else so[0]
    maps = sorted(glob.glob(os.path.join(mapdir, "*.map26a")))
    games = [(2 * i + s, m) for i, m in enumerate(maps) for s in (0, 1)]
    done = []
    if "--local" not in a:
        import cxefarm
        fg = [dict(id=k, a=so, b=so, map=m, env={"CXE_CALLMAX": "@D@/cm.tsv"}, files={"cm.tsv": f"{out}/cm_{k}.tsv"}) for k, m in games]
        cxefarm.run(fg, say=lambda x: print(x, flush=True))
    for k, m in games:
        if not os.path.exists(f"{out}/cm_{k}.tsv"):
            subprocess.run(["nice", "-n", "10", cxebuild.build_host(), so, so, m, f"{out}/g{k}"], env=dict(os.environ, CXE_CALLMAX=f"{out}/cm_{k}.tsv"),
                           capture_output=True, timeout=1800)
        if os.path.exists(f"{out}/cm_{k}.tsv"):
            done.append(k)
    agg = {}
    pm = open(f"{out}/permap.tsv", "w")  # 8 Nov (owner: bounds as multipliers of map size, camps...): each game's per-function max, for fitting
    pm.write("map\tgame\tfunc\tmax\tcalls\n")
    for k in done:
        mname = os.path.basename(dict(games)[k])[:-7]
        for ln in open(f"{out}/cm_{k}.tsv"):
            p = ln.rstrip("\n").split("\t")
            if p[0] != "F":
                continue
            fi, n, x, mx, sm, h = int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), list(map(int, p[6:6 + NB]))
            if n:
                pm.write(f"{mname}\t{k}\t{fi}\t{mx}\t{n}\n")
            e = agg.setdefault(fi, [0, 0, 0, 0, [0] * NB])
            e[0] += n
            e[1] += x
            e[2] = max(e[2], mx)
            e[3] += sm
            e[4] = [u + v for u, v in zip(e[4], h)]
        os.remove(f"{out}/cm_{k}.tsv")
        for f in glob.glob(f"{out}/g{k}*"):
            os.remove(f)
    pm.close()
    names = wasmparse.Module(cxebuild.wasm_of(bot)).names
    import json as _j
    _j.dump({str(fi): names.get(fi, f"f{fi}") for fi in agg}, open(f"{out}/names.json", "w"))
    raw = {fi: names.get(fi, f"f{fi}") for fi in agg}
    dm = demangle(sorted(set(raw.values())))
    rows = []
    for fi, (n, x, mx, sm, h) in agg.items():
        nm = dm.get(raw[fi], raw[fi])
        rows.append((mx, pct(h, 0.999), pct(h, 0.99), sm // max(n, 1), n, x, nm))
    with open(f"{out}/callmax.tsv", "w") as f:
        f.write("max\tp999_le\tp99_le\tmean\tcalls\tcrossed\tfunction\n")
        for r in sorted(rows, reverse=True):
            f.write("\t".join(map(str, r)) + "\n")
    sel = [r for r in rows if r[4] >= minc and (not match or re.search(match, r[6]))]
    L = [f"# callmax {bot}: {len(done)} of {len(games)} games on {len(maps)} maps ({mapdir}), {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}",
         "per call, inclusive (callees + host charges). p99/p99.9 are bucket upper edges (powers of 2): conservative. 'crossed' = calls over a cut/refill, not measured.",
         f"{'max':>9} {'p99.9<=':>9} {'p99<=':>9} {'mean':>8} {'calls':>9} {'crossed':>7}  function"]
    for r in sorted(sel, reverse=True)[:top]:
        L.append(f"{r[0]:>9,} {r[1]:>9,} {r[2]:>9,} {r[3]:>8,} {r[4]:>9,} {r[5]:>7}  {r[6][:110]}")
    open(f"{out}/report.txt", "w").write("\n".join(L) + "\n")
    print("\n".join(L[:top + 3]))
    print(f"report: {out}/report.txt")


if __name__ == "__main__":
    main()
