"""Signal or noise? Map-pair statistics for two bots over every game ever played between them.

usage: python3 -I tools/lab/abstat.py X Y [--set pool,heldout,...] [--maps FILE] [--no-screen] [--per-map]
       python3 -I tools/lab/abstat.py --run DIR [DIR ...]       abl.sh output dirs only (no index)
  X, Y: bots under bots/ (their CURRENT source), 'name@hash', or a bare 12-hex source hash.
  Games come from tools/lab/abindex.py: every local abl.sh run on this machine (/data/zw4424/abl) and the Condor
  screen cache, matched by source hash, so h2h, held-out, screen and sprt runs of the same two versions pool
  automatically, whatever the run names.
  --set: only these map families (pool, patho = the 4 hand-made ones, heldout = gen_NN, dev = gen_dev_NN,
  fresh = gen_s_NNN, genpatho = gen_p_NNN, custom = gen_c_<name>: tools/lab/genbig.py, unseen = gen_u_/gen_up_,
  gate = gen_g_, gate2 = gen_g2_..gen_g9_, ideology = gen_i_, altar1 = gen_a_, gen = any other generated family).

WHY MAP PAIRS. Games are deterministic and both sides of a map are played, so the unit of evidence is the map:
X scores 1 (won both sides), 0.5 (split) or 0 (lost both). For close variants about 60% of maps split, because
the side decides the game more often than the bot (measured over 53 nova_m* A/B runs, 2026-10-24): a split says
nothing about which bot is better. The confidence interval comes from the spread of map scores, so it reflects
how far the result should carry to unseen maps. Win counts with a binomial SD overstate the evidence.

OUTPUT: per map family and pooled: maps, won both/split/lost both, score with its 95% CI, LOS (sign test on the
maps one bot won on both sides), gem share (95% CI, map bootstrap), gem margin per map; a verdict; and a warning
when two families disagree beyond noise (for example pool maps vs generated maps: a sign of tuning to the pool).
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abindex  # noqa: E402

FAMILIES = ("pool", "patho", "heldout", "dev", "fresh", "genpatho", "custom", "unseen", "gate", "gate2", "ideology",
            "altar1", "bank", "bankho", "bank2", "bankho2", "gen", "other")  # bank / bankho: mapbank.py's frozen decision / held-out banks (30 Oct)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def summarize(rows, boot=1000):
    """rows: [(map, family, score in {0, .5, 1}, x gems, y gems)] -> dict of statistics."""
    n = len(rows)
    if n == 0:
        return None
    s = [r[2] for r in rows]
    w, l = s.count(1.0), s.count(0.0)
    mean = sum(s) / n
    var = sum((v - mean) ** 2 for v in s) / (n - 1) if n > 1 else 0.25
    se = math.sqrt(var / n)
    gx, gy = sum(r[3] for r in rows), sum(r[4] for r in rows)
    rng = random.Random(7)
    shares = []
    for _ in range(boot):
        bx = by = 0
        for _ in range(n):
            r = rows[rng.randrange(n)]
            bx += r[3]; by += r[4]
        shares.append(bx / max(1, bx + by))
    shares.sort()
    marg = [(r[3] - r[4]) for r in rows]
    mm = sum(marg) / n
    msd = math.sqrt(sum((v - mm) ** 2 for v in marg) / (n - 1)) if n > 1 else 0
    return dict(n=n, w=w, d=n - w - l, l=l, score=mean, sd=math.sqrt(var), se=se,
                lo=max(0.0, mean - 1.96 * se), hi=min(1.0, mean + 1.96 * se),
                los=phi((w - l) / math.sqrt(w + l)) if w + l else 0.5,
                share=gx / max(1, gx + gy), share_lo=shares[int(0.025 * boot)], share_hi=shares[int(0.975 * boot) - 1],
                margin=mm / 2, margin_ci=1.96 * msd / math.sqrt(n) / 2 if n > 1 else 0)


def line(st):
    return (f"{st['n']:3d} maps: won both {st['w']}, split {st['d']}, lost both {st['l']} | score {st['score']:.3f} "
            f"[{st['lo']:.3f}, {st['hi']:.3f}] LOS {st['los'] * 100:.0f}% | gem share {st['share']:.3f} "
            f"[{st['share_lo']:.3f}, {st['share_hi']:.3f}] | margin/game {st['margin']:+.0f} +-{st['margin_ci']:.0f}")


def verdict(st, x="X", y="Y"):
    if st["n"] < 10:
        return f"too few maps ({st['n']}) for a verdict"
    if st["lo"] > 0.5:
        v = f"{x} BETTER than {y} (95% CI above 0.5; one fixed sample: confirm on unseen maps with sprt.py)"
    elif st["hi"] < 0.5:
        v = f"{x} WORSE than {y} (95% CI below 0.5)"
    else:
        need = math.ceil((1.96 * max(st["sd"], 0.2) / 0.03) ** 2)
        v = f"NO SIGNIFICANT DIFFERENCE (CI {st['lo']:.3f}-{st['hi']:.3f} includes 0.5)"
        v += ("; any real difference is within about +-0.03" if st["n"] >= need else
              f"; a CI of +-0.03 needs about {need} maps (tools/lab/sprt.py plays more maps until it can decide)")
    return v


def zcrit(p):
    """Two-sided critical z for level p (bisection on phi)."""
    lo, hi = 0.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 2 * (1 - phi(mid)) > p:
            lo = mid
        else:
            hi = mid
    return hi


def disagreement(fams):
    """Pairs of families (>= 15 maps each) whose scores differ beyond noise, at a family-wise 5% level
    (Bonferroni over the pairs compared: with 4 families that is |z| > 2.64, not 2)."""
    out = []
    keys = [k for k in fams if fams[k]["n"] >= 15]
    pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]]
    crit = zcrit(0.05 / max(1, len(pairs)))
    for a, b in pairs:
        A, B = fams[a], fams[b]
        z = (A["score"] - B["score"]) / math.sqrt(A["se"] ** 2 + B["se"] ** 2 + 1e-12)
        if abs(z) > crit:
            out.append(f"{a} {A['score']:.3f} vs {b} {B['score']:.3f} (z {z:+.1f}, bar {crit:.2f})")
    return out


# MAP BANDS (Econ 30 Oct, econ/mapband.py on 870 live games: our losses sit at altars > 4, s2s walk <= 35, area <= 1581):
# rows per band after the families, labelled so family parsers ([a-z]+ maps:) do not read them. Features from mapfeat, cached
# per map name + file mtime in /data/zw4424/mapbank/mapfeat_cache.json.
BANDS = [("alt<=2", 0, -1e9, 2), ("alt3-4", 0, 2, 4), ("alt>4", 0, 4, 1e9), ("s2s<=35", 1, -1e9, 35), ("s2s35-56", 1, 35, 56),
         ("s2s>56", 1, 56, 1e9), ("area<=1581", 2, -1e9, 1581), ("area>1581", 2, 1581, 1e9)]
FEAT_CACHE = "/data/zw4424/mapbank/mapfeat_cache.json"


def map_feats(names):
    """{name: (altars, s2s walk, area)} for the names whose map file abindex knows; cached on disk."""
    import json
    try:
        cache = json.load(open(FEAT_CACHE))
    except (OSError, ValueError):
        cache = {}
    known = abindex.maps()
    out, dirty = {}, False
    for n in names:
        if n not in known:
            continue
        path, mt = known[n][1], known[n][2]
        c = cache.get(n)
        if not c or c[3] != mt:
            try:
                import mapfeat
                r = mapfeat.analyse_path(path)
                c = cache[n] = [r["alt"], r["s2s"], r["W"] * r["H"], mt]
                dirty = True
            except Exception:  # noqa: BLE001  a map mapfeat cannot read gets no band
                continue
        out[n] = tuple(c[:3])
    if dirty:
        try:
            tmp = FEAT_CACHE + f".tmp{os.getpid()}"
            json.dump(cache, open(tmp, "w"))
            os.replace(tmp, FEAT_CACHE)
        except OSError:
            pass
    return out


def report(rows, x, y, half=0, per_map=False):
    fams = {}
    for f in FAMILIES:
        st = summarize([r for r in rows if r[1] == f])
        if st:
            fams[f] = st
    print(f"{x} vs {y}: {len(rows)} complete map pairs ({2 * len(rows)} games)"
          + (f"; {half} maps with one side only (ignored)" if half else ""))
    for f, st in fams.items():
        print(f"  {f:8s}{line(st)}")
    tot = summarize(rows)
    if tot is None:
        print("  no complete map pairs")
        return None
    print(f"  {'ALL':8s}{line(tot)}")
    if os.environ.get("ABSTAT_BANDS", "1") != "0" and len(rows) >= 100:
        try:
            ft = map_feats([r[0] for r in rows])
            for lab, k, lo, hi in BANDS:
                st = summarize([r for r in rows if r[0] in ft and ft[r[0]][k] is not None and lo < ft[r[0]][k] <= hi])
                if st:
                    print(f"  band {lab:<10s} {line(st).lstrip()}")
        except Exception as e:  # noqa: BLE001  bands are informative only
            print(f"  (bands unavailable: {type(e).__name__})")
    for d in disagreement(fams):
        print(f"  !! families disagree beyond noise: {d}")
    print(f"  verdict: {verdict(tot, x, y)}")
    if per_map:
        for r in rows:
            print(f"    {r[0]:24s} {r[1]:8s} {r[2]:.1f}  gems {r[3]}-{r[4]}")
    return tot


def rows_from_runs(dirs, x=None):
    """Map pairs straight from abl.sh output dirs (games.jsonl); X = x or the first bot of the first run."""
    import json
    y = None
    games = {}
    rep_conflicts = 0
    for d in dirs:
        for ln in open(os.path.join(d, "games.jsonl")):
            g = json.loads(ln)
            if not g.get("ok") or g.get("win") not in ("A", "B"):
                continue
            if x is None:
                x = g["a"]
            if y is None and x in (g["a"], g["b"]):
                y = g["b"] if g["a"] == x else g["a"]
            if {g["a"], g["b"]} != {x, y}:
                continue
            old = games.get((g["a"], g["map"]))
            if old is not None and old["win"] != g["win"]:
                rep_conflicts += 1  # REPEAT > 1 and the repeats differ: the bots are not deterministic
            games[(g["a"], g["map"])] = g
    rows = []
    half = 0
    for m in sorted({k[1] for k in games}):
        g1, g2 = games.get((x, m)), games.get((y, m))
        if g1 is None or g2 is None:
            half += 1
            continue
        s = ((g1["win"] == "A") + (g2["win"] == "B")) / 2
        rows.append((m, abindex.map_set(m), s, g1["sa"].get("gems", 0) + g2["sb"].get("gems", 0),
                     g1["sb"].get("gems", 0) + g2["sa"].get("gems", 0)))
    if rep_conflicts:
        print(f"!! {rep_conflicts} repeated games had different winners: these bots are not deterministic, so map "
              f"pairs keep only the last repeat and the cache/sprt reuse assumptions do not hold", file=sys.stderr)
    return rows, half, x, y


def main():
    args = sys.argv[1:]
    per_map = "--per-map" in args
    if "--run" in args:
        dirs = [a for a in args[args.index("--run") + 1:] if not a.startswith("--")]
        rows, half, x, y = rows_from_runs(dirs)
        report(rows, x, y, half, per_map)
        return
    pos, sets, maplist, screen = [], None, None, True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--set":
            sets = set(args[i + 1].split(",")); i += 1
        elif a == "--maps":
            maplist = {l.strip() for l in open(args[i + 1]) if l.strip()}; i += 1
        elif a == "--no-screen":
            screen = False
        elif not a.startswith("--"):
            pos.append(a)
        i += 1
    if len(pos) != 2:
        print(__doc__)
        sys.exit(1)
    (nx, hx), (ny, hy) = abindex.resolve(pos[0]), abindex.resolve(pos[1])
    if not hx or not hy:
        sys.exit(f"cannot resolve {pos[0] if not hx else pos[1]}: no bots/<name>/src (use name@hash)")
    ix = abindex.Index({hx, hy}, screen=screen)
    rows, half = abindex.map_pairs(ix, hx, hy)
    if sets:
        rows = [r for r in rows if r[1] in sets]
    if maplist:
        rows = [r for r in rows if r[0] in maplist]
    if ix.conflicts:
        print(f"!! {len(ix.conflicts)} games disagree between sources (determinism failure): {ix.conflicts[:3]}")
    report(rows, f"{nx}@{hx}", f"{ny}@{hy}", half, per_map)
    if not rows:
        import time
        for n, h in ((nx, hx), (ny, hy)):
            other = {k: v for k, v in abindex.recorded(n).items() if k != h}
            if other:
                print(f"  {n}@{h} has no games with the other bot; recorded versions of {n}: " + ", ".join(
                    f"{n}@{k} ({time.strftime('%m-%d %H:%M', time.localtime(v))})" for k, v in sorted(other.items(), key=lambda kv: -kv[1])[:5]))


if __name__ == "__main__":
    main()
