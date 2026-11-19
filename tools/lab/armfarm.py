#!/usr/bin/env python3
"""armfarm: N arms (data-flag values of one build) vs the same BASE on the same maps in one Condor run, a best-arm pick corrected
for multiple comparisons, and a confirmation of the pick on maps it was NOT picked on. KILLGATE tool agent, 1 Nov (owner:
"speed up iterations"). Wraps tools/lab/variantfarm.py (arm copies, compile check, condab launch) and tools/lab/killgate.py
(maps, statistics, the sequential confirmation).

usage: python3 -I tools/lab/armfarm.py BUILD NAME 'X=1' 'X=2' 'X=3,Y=1' ... [--vs BASE] [--maps 600] [--alpha 0.05]
                                       [--confirm big|otf|none] [--otf-n 400] [--cached] [--within LIST]
       python3 -I tools/lab/armfarm.py --arms BOT1,BOT2,... NAME [same options]          (arms already built)
  BUILD   a bot whose switches are '#define X <number>' lines (exactly once in src/) feeding a volatile runtime table (the
          primer's RUNTIME FLAG pattern, e.g. BB693_TAB): then every arm differs from BUILD in data bytes only and plays like
          BUILD wherever its flag does not fire. A switch read by '#if' compiles different code per arm: the arms then also
          differ by recompile reshuffle (fuel timing), which only adds noise; armfarm warns but runs.
  NAME    [a-z0-9]+; arm k = bots/<BUILD>_af<NAME><k> (newbot.sh copy, symlink-free, paramdiff-checked), condab runs af<NAME><k>,
          files in /data/USER/st/kg/af<NAME>/ (table.txt = the one-screen result).
  --vs    the common BASE (default: live, /data/USER/st/bq/live.txt). BUILD itself is an arm when it differs from BASE.
  --maps  selection maps: the first M of a family-stratified order of the 2,621 BIG maps (killgate.big_maps), seeded by NAME.
Steps:
  1. build the arms (variantfarm.build) and start every arm's condab at once (OTF=0; the pilots interleave them, so the arms
     share one Condor queue and one wall time); a syntax-only compile check runs alongside and stops a broken arm.
  2. table: per arm the map-pair score vs BASE [95% CI], LOS, z, changed share, faults, capped fuel; a one-sided p = 1 - LOS
     per arm, Holm-adjusted over the K arms; the best arm = the highest z; its paired D vs the runner-up on the same maps.
  3. the best arm is CONFIRMED on maps it was not picked on (the winner's curse inflates its selection score):
       big   (default) killgate.py BEST BASE af<NAME>c --no-a --exclude <selection maps>: killgate's sequential stage B on the
             remaining 2,621 - M BIG maps (KILL / PROMOTE / FLAT); a PROMOTE there is the arm's evidence for a SHIPCHECK;
       otf   CONFIRM=<otf-n> condab: fresh generated maps, never saved; CONFIRMED when its LOS >= 95%;
       none  table only.
     The selection maps are never pooled into the confirmation. The pick is confirmed even when no arm is Holm-significant
     (an arm can be real and under-powered on M maps); the Holm column says how strong the selection evidence alone is.
  --cached plays nothing (re-reads; validation on arms already played). --within LIST: only BIG maps in LIST (both steps).
Cost: K arms x M maps x 2 games + the confirmation (killgate's average on a null ~1,400 maps, on a true 0.515 ~1,700).
"""
import math
import os
import re
import subprocess
import sys
import threading
import time

REPO = "/homes/USER/cambc"
LAB = os.path.join(REPO, "tools/lab")
Q = "/data/USER/st/bq"
sys.path.insert(0, LAB)
import abindex  # noqa: E402
import killgate as K  # noqa: E402
import variantfarm as VF  # noqa: E402

OUT = []


def say(s):
    line = f"{time.strftime('%H:%M:%S', time.gmtime())} {s}"
    print(line, flush=True)
    OUT.append(line)


def holm(ps):
    """Holm step-down adjusted p-values (same order as ps)."""
    k = len(ps)
    idx = sorted(range(k), key=lambda i: ps[i])
    adj, run = [0.0] * k, 0.0
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (k - r) * ps[i]))
        adj[i] = run
    return adj


def if_switches(build, names):
    """Switch names that some '#if'/'#ifdef'/'#elif' line of BUILD tests (not a data flag)."""
    src = os.path.join(os.path.realpath(os.path.join(REPO, "bots", build)), "src")
    hit = set()
    for f in os.listdir(src):
        if f.endswith((".h", ".cpp", ".cc")):
            for ln in open(os.path.join(src, f), errors="replace"):
                s = ln.strip()
                if s.startswith("#if") or s.startswith("#elif"):
                    hit |= {n for n in names if re.search(rf"\b{re.escape(n)}\b", s)}
    return hit


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)

    def opt(k, d=None):
        return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d
    valued = {"--vs", "--maps", "--alpha", "--confirm", "--otf-n", "--arms", "--within"}
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in valued)]
    pre = opt("--arms")
    if pre:
        build, name, sets = None, pos[0], []
        arms = [(b, b, None) for b in pre.split(",") if b]
    else:
        build, name, sets = pos[0], pos[1], pos[2:]
        arms = []
    if not re.fullmatch(r"[a-z0-9]+", name):
        sys.exit("NAME must be [a-z0-9]+")
    base = opt("--vs") or open(os.path.join(Q, "live.txt")).read().split()[1]
    m_sel = int(opt("--maps", 600))
    alpha = float(opt("--alpha", 0.05))
    mode = opt("--confirm", "big")
    cached = "--cached" in a
    d = os.path.join(K.KG, f"af{name}")
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    hb = abindex.bot_hash(base)
    if build:
        settings = [VF.parse_setting(s) for s in sets]
        if not settings:
            sys.exit("give at least one arm setting 'X=V'")
        flags = {k for st in settings for k in st}
        bad = if_switches(build, flags)
        if bad:
            say(f"!! {', '.join(sorted(bad))} tested by #if: those arms differ by compiled code (recompile reshuffle), "
                f"not data bytes only")
        for k, st in enumerate(settings, 1):
            bot = f"{build}_af{name}{k}"
            lab = ",".join(f"{x}={y}" for x, y in st.items())
            if os.path.exists(os.path.join(REPO, "bots", bot)):
                say(f"{bot} exists: reused as is (delete nothing; pick a new NAME to rebuild)")
            else:
                VF.build(build, bot, st)
                say(f"built {bot}: {lab}")
            arms.append((bot, lab, f"af{name}{k}"))
        if abindex.bot_hash(build) != hb and os.environ.get("AF_NO_ASIS") != "1":  # the donor at its own values (flag 0): the code's own cost as
            arms.append((build, "(build as is)", f"af{name}0"))                    # a null arm, ~1 arm of games; AF_NO_ASIS=1 leaves it out
    else:
        arms = [(b, b, f"af{name}{k}") for k, (b, _, _) in enumerate(arms, 1)]
    hashes = {b: abindex.bot_hash(b) for b, _, _ in arms}
    if len(set(hashes.values())) < len(hashes) or hb in hashes.values():
        sys.exit("two arms (or an arm and BASE) have the same source")
    within = set(K.read_list(opt("--within"))) if opt("--within") else None
    order = K.strat_order([m for m in K.big_maps() if within is None or m in within], "af:" + name + ":" + hb)
    sel = order[:m_sel]
    ml = os.path.join(d, "selection.maps")
    open(ml, "w").write("".join(m + "\n" for m in sel))
    say(f"armfarm {name}: {len(arms)} arms vs {base}@{hb} on {len(sel)} selection maps ({2 * len(sel) * len(arms)} games "
        f"before reuse)")
    played = 0
    if not cached:
        before = {b: len(K.pair_rows(hashes[b], hb, sel)) for b, _, _ in arms}
        procs = {b: VF.launch(b, base, run, ml) for b, _, run in arms}
        say("condab pids " + " ".join(f"{b}:{p.pid}" for b, p in procs.items()))
        if build:
            def check(bot):
                ok, err = VF.compile_check(bot)
                say(f"compile {bot}: {'ok' if ok else 'FAILED: ' + err[:150]}")
                if not ok:
                    VF.stop(procs[bot], "compile check failed")
            th = [threading.Thread(target=check, args=(b,)) for b, _, _ in arms if b != build]
            for t in th:
                t.start()
            for t in th:
                t.join()
        for p in procs.values():
            p.wait()
        played = sum(2 * (len(K.pair_rows(hashes[b], hb, sel)) - before[b]) for b, _, _ in arms)
    t_sel = time.time() - t0
    res = {}
    for b, lab, _ in arms:
        rows = K.pair_rows(hashes[b], hb, sel)
        st = K.summ(rows.values())
        st["ch"] = sum(r["ch"] for r in rows.values()) / max(1, len(rows))
        st["rows"] = rows
        st["sc"] = K.side_counts(rows.values())
        res[b] = st
    ps = [1 - res[b]["los"] for b, _, _ in arms]
    adj = holm(ps)
    L = [f"ARMFARM {name}: {len(arms)} arms vs {base}@{hb}, {len(sel)} selection maps (BIG stratified, seed NAME); "
         f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(t0))}",
         f"  {'arm':40s} {'setting':24s} {'n':>4s} {'score [95% CI]':24s} {'LOS':>6s} {'z':>5s} {'Holm p':>7s} {'chg':>5s} "
         f"{'faults':>6s} {'fuel c/b':>9s}"]
    for (b, lab, _), p in zip(arms, adj):
        s = res[b]
        L.append(f"  {b[:40]:40s} {lab[:24]:24s} {s['n']:4d} {s['mean']:.4f} [{s['lo']:.4f}, {s['hi']:.4f}] "
                 f"{s['los'] * 100:5.1f}% {s['z']:5.2f} {p:7.3f} {s['ch'] * 100:4.0f}% {s['sc']['cf']:6d} "
                 f"{s['sc']['cfuel']:4d}/{s['sc']['bfuel']:<4d}")
    rank = sorted(arms, key=lambda e: -res[e[0]]["z"])
    best = rank[0][0]
    bi = [e[0] for e in arms].index(best)
    L.append(f"  best arm: {best} ({rank[0][1]}), z {res[best]['z']:.2f}, Holm p {adj[bi]:.3f} "
             f"({'significant' if adj[bi] < alpha else 'not significant'} at {alpha} over {len(arms)} arms on the selection maps)")
    if len(rank) > 1:
        r2 = rank[1][0]
        common = sorted(set(res[best]["rows"]) & set(res[r2]["rows"]))
        dd = [res[best]["rows"][m]["s"] - res[r2]["rows"][m]["s"] for m in common]
        if len(dd) > 1:
            mu = sum(dd) / len(dd)
            se = math.sqrt(sum((x - mu) ** 2 for x in dd) / (len(dd) - 1) / len(dd))
            L.append(f"  best - runner-up ({r2}) paired D {mu:+.4f} [{mu - 1.96 * se:+.4f}, {mu + 1.96 * se:+.4f}] on "
                     f"{len(dd)} maps")
    if any(res[b]["sc"]["cf"] for b, _, _ in arms):
        L.append("  !! bot faults in: " + ", ".join(b for b, _, _ in arms if res[b]["sc"]["cf"]))
    L.append(f"  selection: played {played} games, wall {t_sel / 60:.1f} min")
    say(f"selection done: best arm {best}, z {res[best]['z']:.2f}, Holm p {adj[bi]:.3f}")
    conf = "none"
    if mode == "big":
        say(f"confirmation of {best}: killgate stage B on the {len(order) - len(sel)} BIG maps outside the selection")
        cmd = ["nice", "-n", "10", "python3", "-I", os.path.join(LAB, "killgate.py"), best, base, f"af{name}c", "--no-a",
               "--exclude", ml] + (["--cached"] if cached else []) + (["--within", opt("--within")] if within else [])
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        vt = os.path.join(K.KG, f"af{name}c", "verdict.txt")
        txt = open(vt).read() if os.path.exists(vt) else r.stdout[-2000:]
        m = re.search(r"^VERDICT: .*$", txt, re.M)
        conf = m.group(0) if m else f"no verdict (exit {r.returncode}; see {vt})"
        g = re.search(r"^games: .*$", txt, re.M)
        L += ["", f"CONFIRMATION (fresh to the pick: BIG maps outside the selection; {vt})"]
        L += ["  " + x for x in txt.splitlines() if x.startswith(("  ", "STAGE B"))][:14]
        L += [f"  {conf}", f"  {g.group(0) if g else ''}"]
    elif mode == "otf":
        n = int(opt("--otf-n", 400))
        run = f"af{name}o"
        if cached:
            L += ["", "CONFIRMATION otf: not run (--cached)"]
        else:
            say(f"confirmation of {best}: CONFIRM={n} fresh generated maps ({run})")
            VF.launch(best, base, run, None, dict(CONFIRM=str(n))).wait()
            t = open(os.path.join(Q, f"{run}.condor.txt")).read() if os.path.exists(os.path.join(Q, f"{run}.condor.txt")) else ""
            m = re.search(r"^\s+confirm\s+(\d+) maps: won both (\d+), split (\d+), lost both (\d+).*$", t, re.M)
            if m:
                w, l = int(m.group(2)), int(m.group(4))
                los = K.phi((w - l) / math.sqrt(w + l)) if w + l else 0.5
                conf = f"VERDICT: {'CONFIRMED' if los >= 0.95 else 'NOT CONFIRMED'} (LOS {los * 100:.1f}%)"
                L += ["", f"CONFIRMATION otf {run}: {m.group(0).strip()}", f"  {conf}"]
            else:
                L += ["", f"CONFIRMATION otf {run}: no result (see {Q}/{run}.vf.log)"]
    L.append(f"\nwall {(time.time() - t0) / 60:.1f} min; table {d}/table.txt")
    txt = "\n".join(L) + "\n"
    open(os.path.join(d, "table.txt.new"), "w").write(txt)
    os.replace(os.path.join(d, "table.txt.new"), os.path.join(d, "table.txt"))
    print("\n" + txt)


if __name__ == "__main__":
    main()
