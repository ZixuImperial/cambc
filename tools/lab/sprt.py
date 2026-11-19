#!/usr/bin/env python3
"""Sequential A/B: play map pairs until the evidence decides, instead of a fixed 88 games that cannot.

usage: python3 -I tools/lab/sprt.py CAND BASE [NAME] [--d1 0.05] [--d0 0] [--nonreg] [--alpha 0.05] [--beta 0.05]
                    [--batch 40] [--min-maps 80] [--max-maps N] [--maps FILE] [--no-patho] [--with-pool] [--dry-run]
                    [--allow-heldout]
  CAND, BASE: bot dirs under bots/. NAME (default CAND_vs_BASE) names the batches: abl.sh runs sprt_NAME_b1,
  sprt_NAME_b2, ... in /data/USER/abl; the report is /data/USER/sprt/NAME.txt (progress log NAME.log).

TEST. Each map gives CAND a score of 1 (won both sides), 0.5 (split) or 0 (lost both); see tools/lab/abstat.py.
A GSPRT on the mean score tests H0: score = 0.5 + d0 against H1: score = 0.5 + d1 (default 0.50 vs 0.55), with
error rates alpha (declaring a gain when there is none) and beta (missing a gain of d1), both 5% by default.
After each batch: LLR = n (mu1 - mu0)(2 mean - mu0 - mu1) / (2 var), the normal-approximation log-likelihood ratio
with the sample variance. It stops at LLR >= ln((1-beta)/alpha) (+2.94: H1) or <= ln(beta/(1-alpha)) (-2.94: H0),
never before --min-maps maps. H1 means the data favour a gain of d1 over no gain (the true score is probably above
the midpoint 0.525); H0 means they favour no gain (a gain under about d1/2, or a loss).
--nonreg tests "not worse": H0 0.45 vs H1 0.50 (for refactors, fuel and speed fixes); H1 = no regression beyond
about 0.025, H0 = probably worse.
OPERATING CHARACTERISTICS (simulated for exactly these defaults: 60% split maps, checks at 80, 120, ..., 444 maps):
true score 0.50 gives H1 2.6% / H0 84.6% / inconclusive 12.8%; true 0.55 gives H1 85.2% / H0 2.5% / inconclusive
12.4% (median 240 maps either way); 0.58 or 0.45 decide after a median 80-120 maps; 0.52-0.53 end inconclusive
about 40% of the time. With the lock free a batch of 40 maps (80 games) takes about 25 s.

MAPS: only maps that nobody selects or tunes on count. Candidates are picked after a good pool h2h and tuned while
watching pool results; counting those 44 maps in the test pushed the simulated false-gain rate from 3% to 10%
(picked after a good h2h) and 17% (tuned to the pool). So the decision uses the fresh generated maps gen_s_001..400
(tools/lab/genbig.py), with one map in ten taken from the custom maps (gen_c_*) and the generated pathological maps
(gen_p_*), a constant 10% to the end, minus every map of abl.sh's default list (the pool: since 25 Oct it holds the
15 custom maps, so they are pool maps now and the odd slots are all gen_p_*). --no-patho leaves the odd maps out;
--maps FILE replaces the list; --with-pool puts the pool maps (abl.sh's default list) first again (only for a change
that was neither picked nor tuned on pool results). Pool results the index already has are printed under the verdict
for information, not counted. The held-out gen_NN and dev gen_dev_NN maps are never used, so tools/lab/heldout.sh
stays an independent check; --maps refuses the validation families (heldout gen_NN, unseen gen_u_/gen_up_, gate2
gen_g2_..g9_, altar1 gen_a_: screening only) unless --allow-heldout. Decision maps that other runs (an h2h on a list, a per-kind run, a Condor screen)
already played count too; the test names those runs at the start and in the report.
REUSE. Every game already played on the decision maps between these two source versions (an earlier or interrupted
sprt, any Condor screen: tools/lab/abindex.py) counts and is not replayed. Each batch takes abl.sh's machine-wide
lock on its own, so other A/Bs interleave. If either bot's source changes during the test it stops.
"""
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abindex  # noqa: E402
import abstat  # noqa: E402

REPO = abindex.REPO
FRESH = "/data/USER/genmaps_s/maplist.txt"
ODD = ["/data/USER/genmaps_c/maplist.txt", "/data/USER/genmaps_p/maplist.txt"]  # custom first, then gen_p
WORK_MAPS = "/data/USER/work301/maps"
VALIDATION = ("heldout", "unseen", "gate2", "altar1")  # abindex.map_set families kept for validation or screening only


def opt(args, name, default, cast=float):
    if name in args:
        i = args.index(name)
        v = cast(args[i + 1])
        del args[i:i + 2]
        return v
    return default


def llr(scores, mu0, mu1):
    n = len(scores)
    if n < 2:
        return 0.0
    m = sum(scores) / n
    v = max(sum((s - m) ** 2 for s in scores) / (n - 1), 0.01)
    return n * (mu1 - mu0) * (2 * m - mu0 - mu1) / (2 * v)


def outside(ix, hc, hb, in_order, own="sprt_"):
    """(maps, {run: maps}) of the complete decision-map pairs that no sprt batch played: an h2h or per-kind run, a mix
    run, a Condor screen. They count like any result, but a candidate picked or tuned on those runs biases the test
    (MAPS above). Batches of any sprt of these two versions (a resumed, parallel or --nonreg test) are fine."""
    names = abindex.map_names()
    n, by = 0, {}
    for mh, (g1, g2) in ix.pairs(hc, hb).items():
        if g1 is None or g2 is None or names.get(mh) not in in_order:
            continue
        srcs = {s for g in (g1, g2) for s in [g["src"]] + g.get("also", [])}
        if any(s.startswith("abl:" + own) for s in srcs):
            continue
        n += 1
        for s in srcs:
            s = s.split(":", 1)[-1]
            by[s] = by.get(s, 0) + 1
    return n, by


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    nonreg = "--nonreg" in args
    patho = "--no-patho" not in args
    with_pool = "--with-pool" in args
    allow_heldout = "--allow-heldout" in args
    args = [a for a in args if a not in ("--dry-run", "--nonreg", "--no-patho", "--with-pool", "--allow-heldout")]
    d0, d1 = (-0.05, 0.0) if nonreg else (0.0, 0.05)
    d0, d1 = opt(args, "--d0", d0), opt(args, "--d1", d1)
    alpha, beta = opt(args, "--alpha", 0.05), opt(args, "--beta", 0.05)
    batch, min_maps = opt(args, "--batch", 40, int), opt(args, "--min-maps", 80, int)
    max_maps = opt(args, "--max-maps", 0, int)
    maps_file = opt(args, "--maps", None, str)
    if len(args) < 2 or any(a.startswith("--") for a in args):
        print(__doc__)
        sys.exit(1)
    cand, base = args[0], args[1]
    name = args[2] if len(args) > 2 else f"{cand}_vs_{base}"
    hc, hb = abindex.bot_hash(cand), abindex.bot_hash(base)
    if not hc or not hb:
        sys.exit(f"no bots/{cand if not hc else base}/src: sprt needs the source to play new games "
                 f"(abstat.py shows the results recorded for archived bots)")
    if hc == hb:
        sys.exit(f"{cand} and {base} have the same source ({hc})")
    # the pool = abl.sh's default list (every non-generated map plus the custom gen_c_* maps): every h2h plays it, so
    # candidates are picked and tuned on it and none of its maps may count in the decision
    pool = sorted(f[:-7] for f in os.listdir(WORK_MAPS)
                  if f.endswith(".map26a") and (not f.startswith("gen_") or f.startswith("gen_c_")))
    pool_set = set(pool)
    if maps_file:
        order = [l.strip() for l in open(maps_file) if l.strip()]
        held = [m for m in order if abindex.map_set(m) in VALIDATION]
        if held and not allow_heldout:
            sys.exit(f"{maps_file} lists {len(held)} validation maps ({' '.join(held[:5])}{' ...' if len(held) > 5 else ''}): "
                     f"families {', '.join(VALIDATION)} are kept for validation, never for decisions (--allow-heldout overrides)")
    else:
        read = lambda f: [l.strip() for l in open(f) if l.strip()] if os.path.exists(f) else []  # noqa: E731
        fresh = read(FRESH)
        odd = [m for f in ODD for m in read(f) if m not in pool_set] if patho else []
        if not fresh:
            sys.exit(f"no fresh maps ({FRESH}): run python3 tools/lab/genbig.py --install first")
        order = []
        while fresh:  # nine fresh maps, then one custom/pathological map (a constant 10%; leftovers stay unused)
            order += fresh[:9]
            fresh = fresh[9:]
            if odd:
                order.append(odd.pop(0))
        if with_pool:
            order = pool + order
    order = [m for m in order if os.path.exists(os.path.join(WORK_MAPS, m + ".map26a"))]
    if max_maps:
        order = order[:max_maps]
    in_order = set(order)
    mu0, mu1 = 0.5 + d0, 0.5 + d1
    lo_b, hi_b = math.log(beta / (1 - alpha)), math.log((1 - beta) / alpha)
    os.makedirs("/data/USER/sprt", exist_ok=True)
    report = f"/data/USER/sprt/{name}.txt"
    log = open(f"/data/USER/sprt/{name}.log", "a")
    t0 = time.time()

    def say(s):
        print(s, flush=True)
        log.write(s + "\n"); log.flush()

    fams = {}
    for m in order:
        fams[abindex.map_set(m)] = fams.get(abindex.map_set(m), 0) + 1
    say(f"## sprt {name}: {cand}@{hc} vs {base}@{hb}; H0 score {mu0:.3f} vs H1 {mu1:.3f} (alpha {alpha}, beta {beta}); "
        f"bounds {lo_b:+.2f}/{hi_b:+.2f}; decision maps {len(order)} ({', '.join(f'{f} {c}' for f, c in sorted(fams.items()))}), "
        f"batches of {batch}, at least {min_maps}")
    k, failed, result = 0, set(), None
    while True:
        ix = abindex.Index({hc, hb})
        if ix.conflicts:
            say(f"!! {len(ix.conflicts)} determinism conflicts in the index: {ix.conflicts[:2]}")
        rows, _ = abindex.map_pairs(ix, hc, hb)
        rows = [r for r in rows if r[0] in in_order]
        if k == 0 and not failed:  # first look: decision maps that earlier runs already played
            n_out, by = outside(ix, hc, hb, in_order)
            if n_out:
                say(f"!! {n_out} decision maps were already played by other runs ({', '.join(f'{r} {c}' for r, c in sorted(by.items(), key=lambda kv: -kv[1])[:6])}): "
                    f"they count. If {cand} was picked or tuned on those runs, this test is biased: leave those maps out (--maps)")
        done = {r[0] for r in rows}
        scores = [r[2] for r in rows]
        L = llr(scores, mu0, mu1)
        st = abstat.summarize(rows, boot=200) if rows else None
        fam = {}
        for r in rows:
            fam[r[1]] = fam.get(r[1], 0) + 1
        if st:
            say(f"## {time.strftime('%T')} +{time.time() - t0:.0f}s: {st['n']} maps ({', '.join(f'{f} {c}' for f, c in sorted(fam.items()))}): "
                f"score {st['score']:.3f} [{st['lo']:.3f}, {st['hi']:.3f}], won both {st['w']} / split {st['d']} / lost both "
                f"{st['l']}, gem share {st['share']:.3f}; LLR {L:+.2f}")
        if len(rows) >= min_maps and L >= hi_b:
            result = "H1"
            break
        if len(rows) >= min_maps and L <= lo_b:
            result = "H0"
            break
        todo = [m for m in order if m not in done and m not in failed][:batch]
        if not todo:
            result = "INCONCLUSIVE"
            break
        if dry:
            say(f"## dry run: next batch {len(todo)} maps: {' '.join(todo[:8])}{' ...' if len(todo) > 8 else ''}")
            result = "DRY-RUN"
            break
        k += 1
        run = f"sprt_{name}_b{k}"
        while os.path.exists(os.path.join(abindex.ABL, run)):
            k += 1
            run = f"sprt_{name}_b{k}"
        ml = f"/data/USER/abl/.{run}.maps"
        open(ml, "w").write("".join(m + "\n" for m in todo))
        say(f"## batch {k}: {len(todo)} maps ({2 * len(todo)} games) -> abl.sh run {run}")
        r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/abl.sh"), cand, base, run, ml],
                           capture_output=True, text=True)
        log.write(r.stdout + r.stderr)
        os.remove(ml)
        if r.returncode != 0:
            say(f"!! abl.sh failed (exit {r.returncode}): {(r.stdout + r.stderr)[-400:]}")
            result = "ERROR"
            break
        if abindex.bot_hash(cand) != hc or abindex.bot_hash(base) != hb:
            say("!! a bot's source changed during the test: stopping (rerun to test the new version)")
            result = "ERROR"
            break
        ix2 = abindex.Index({hc, hb})
        got = {r2[0] for r2 in abindex.map_pairs(ix2, hc, hb)[0]}
        miss = [m for m in todo if m not in got]
        if len(miss) == len(todo):
            say(f"!! batch {k} produced no complete map pair (see {abindex.ABL}/{run}/run.log): stopping")
            result = "ERROR"
            break
        if miss:
            say(f"!! {len(miss)} maps failed in batch {k} and are skipped: {' '.join(miss[:10])}")
            failed.update(miss)
    say(f"## finished in {time.time() - t0:.0f}s")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        abstat.report(rows, f"{cand}@{hc}", f"{base}@{hb}")
        n_out, by = outside(ix, hc, hb, in_order)
        if n_out:
            print(f"  {n_out} of the {len(rows)} decision maps were played by other runs, not by an sprt: "
                  + ", ".join(f"{r} {c}" for r, c in sorted(by.items(), key=lambda kv: -kv[1])[:8]))
        prow = [r for r in abindex.map_pairs(ix, hc, hb)[0] if r[0] in pool_set and r[0] not in in_order]
        pst = abstat.summarize(prow, boot=200)
        if pst:
            print(f"  for information, NOT counted (pool maps are where candidates are picked and tuned):\n"
                  f"  {'pool':8s}{abstat.line(pst)}")
    text = buf.getvalue()
    mid = (mu0 + mu1) / 2
    meaning = {"H1": f"{cand} is better than {base}: the data favour a gain of {d1:+.2f} over none (true score "
                     f"probably above {mid:.3f})" if not nonreg else
               f"{cand} does not regress against {base} beyond about {mid - 0.5:+.3f}",
               "H0": f"{cand} is not better than {base}: the data favour no gain over {d1:+.2f} (a gain under about "
                     f"{mid - 0.5:+.3f}, or a loss)" if not nonreg else
               f"{cand} is probably WORSE than {base} (score below about {mid:.3f})",
               "INCONCLUSIVE": "maps ran out before a decision: any difference is small; read the estimate and its CI",
               "ERROR": "the test stopped early (see above)", "DRY-RUN": "nothing played"}[result]
    tail = (f"SPRT RESULT {result}: {meaning}. {len(rows)} maps, LLR {L:+.2f} (bounds {lo_b:+.2f}/{hi_b:+.2f}), "
            f"H0 {mu0:.3f} vs H1 {mu1:.3f}, alpha {alpha} beta {beta}")
    say(text.rstrip())
    say(tail)
    if dry:  # a dry run only looks: it must not replace the report (or game report) of a real test of this NAME
        sys.exit(0)
    open(report, "w").write(text + tail + "\n")
    if result in ("H1", "H0", "INCONCLUSIVE"):
        try:  # how the games were won and lost (tools/lab/gamerep.py), from the features abl.sh now keeps per game
            import gamerep
            games, total, _ = gamerep.load_local(f"{cand}@{hc}", f"{base}@{hb}")
            games = [g for g in games if g["map"] in in_order]  # the test's decision maps, not the pool or held-out runs
            if games:
                full = gamerep.report(games, f"Local games: {cand} vs {base}", cand, "local",
                                      [f"From sprt.py {name}: {len(games)} games on its decision maps have features "
                                       f"({total} games between the two versions in all)."])
                full += "\n".join(gamerep.paired(games, cand, base)) + "\n"
                gp = f"/data/USER/sprt/{name}_games.md"
                open(gp, "w").write(full)
                summ = full.split("## Summary (details in the numbered sections)")[1].split("\n## 1.")[0].strip()
                say(f"## how the games went ({len(games)} games; full report {gp}):\n{summ}")
                moved = [r.split("|")[1].strip() + " " + r.split("|")[3].strip() for r in full.split("## 12.")[-1].splitlines()
                         if r.startswith("|") and "*" in r and "## 12." in full]
                say("## behaviour changes beyond noise (CAND - BASE, same map and seat): " + ("; ".join(moved) or "none"))
        except Exception as e:  # noqa: BLE001 (the verdict above stands either way)
            say(f"## game report unavailable ({e})")
    sys.exit(0 if result in ("H1", "H0", "INCONCLUSIVE", "DRY-RUN") else 1)


if __name__ == "__main__":
    main()
