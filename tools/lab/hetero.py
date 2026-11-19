#!/usr/bin/env python3
"""hetero: WHERE does a change help? Per-map heterogeneity of a read, by map features, with honest statistics. Tool builder, 4 Nov
(owner via the Builder, after an organiser's advice: "an individual change can be good on some maps and worse on others; you need a
good data-analysis pipeline for working out which maps it's good on and why"). Statistics: Deep research's dr56 design
(/data/USER/st/dr56/hetero_stats.md); features: dr56/feats.py (mapfeat + mid/own share), computed per map once and cached.

usage: python3 -I tools/lab/hetero.py read TAG [TAG ...] [--cand BOT] [--perm 2000] [--min-half 300] [--brief] [--out NAME] [--firing]
       python3 -I tools/lab/hetero.py flag REGEX [...]        all panel reads whose candidate bot name matches REGEX, pooled
       python3 -I tools/lab/hetero.py confirm RULE --n N --out TAG [--from TAG ...]   (RULE like 'mono>0.4' or 'T<=3')
       python3 -I tools/lab/hetero.py calibrate [--k 127]      the pipeline on fc11's null-null trunk-code reads
       python3 -I tools/lab/hetero.py feats TAG ... | --flag REGEX | --calib   features only (> 1,500 missing maps: on Condor)
  TAG = a panel dir under /data/USER/st/panel (inforead irb*, shipcheck/gate fresh legs, trunk-code tc*, stylepanel). Its
  fp_games.jsonl gives every game; the candidate is the first game's A bot (condab's order) unless --cand. Unit = the map pair
  (both seats; a one-seat map is dropped). Outcome s = mean candidate score over the two seats; margin m = mean (cand - foe
  tributed gems) / 1000, clipped to [-1, 1].
  1. Features: dr56's ~23 draft-time features (a bot can compute them, so a rule can become a gate) + generator labels (fam, econ,
     altar, terrain: descriptive only, a bot can't read them). Maps are rebuilt from otf.json seeds when the read kept no files.
  2. Rules: feature > cut, cuts at the 25/33/50/67/75% quantiles of the analysed maps (never chosen on the outcome). Contrast =
     leaf minus complement, within each read (centred), pooled across reads by inverse variance.
  3. Any heterogeneity: max |z| over all rules, null by permutation of s within each read (--perm). BH q over per-rule p.
  4. Honest effect: maps split 50/50 per read (fixed seed); the rule is chosen on one half, estimated on the other, then the
     halves swap (cross-fit). Only the estimation-half numbers are the effect. Leaf and complement each need >= 15% of maps and
     >= --min-half maps per half. Shrunk prediction for a confirm read: discovery contrast x max(0, 1 - E[max z^2 null] / z^2).
  5. Several reads: Cochran Q on the chosen rule's per-read contrasts; a significant Q means the effect depends on the read/base.
  6. Report condor-work/reports/hetero/<NAME>.md + a 5-line summary; --brief prints one 'where it helps' line.
  7. (dr56 §8) For the chosen rule: firing share (maps whose two seats aren't mirror games) in the leaf v the rest, the contrast on
     changed maps only, and the leaf's share of the 81 published ladder maps. A leaf that only fires more often reads like a map
     effect: when firing is decided before play (a draft-gated flag), re-run with --firing (changed maps only).
  confirm: new fresh maps (stratmaps, never saved) filtered so half are in the rule's leaf and half not; writes
  /data/USER/st/panel/<TAG>/otf.json and prints the inforead command that plays exactly those maps (inforead --resume path).
"""
import collections
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools", "lab"))
PANEL = "/data/USER/st/panel"
ROOT = "/data/USER/st/hetero"
CACHE = f"{ROOT}/feats.jsonl"
DR = "/data/USER/st/dr56"
OUT = "/homes/USER/condor-work/reports/hetero"
FEATS = ["T", "area", "aspect", "gems", "gold", "ggr", "gpb", "apb", "grp", "clu", "heavy", "mono", "dash", "cry", "s2s", "alt",
         "alt_d", "mid", "top1", "d50", "hole", "bush", "wall"]  # dr56 list, frozen per tool version (draft-time computable)
LABELS = ["fam", "econ", "altar", "terrain", "area_l", "spawn", "pool"]  # generator labels: descriptive only
QS = (25, 33, 50, 67, 75)


def jl(p):
    out = []
    for ln in open(p, errors="replace"):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


# ---------------- per-map features (cached) ----------------

def need_maps(tags):
    """The map names of these reads (their otf.json and played games): all a read's analysis looks up in the cache."""
    need = set()
    for t in tags:
        need.update(m["name"] for m in (otf_of(t) or {}).get("maps", []))
        p = f"{PANEL}/{t}/fp_games.jsonl"
        if os.path.exists(p):
            need.update(g.get("map") for g in jl(p))
    return need


def load_cache(need=None):
    """map -> features. With NEED, only those maps' rows are parsed (4 Nov: the whole 450k-row cache cost ~1.2 GB per run, and
    ten runs at once held 12 GB)."""
    c = {}
    if os.path.exists(CACHE):
        for ln in open(CACHE, errors="replace"):
            if need is not None:
                i = ln.find('"map": "')
                if i < 0 or ln[i + 8:ln.find('"', i + 8)] not in need:
                    continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            c[r["map"]] = r
    elif os.path.exists(f"{DR}/feats.jsonl"):  # seed from Deep research's run (same extractor)
        os.makedirs(ROOT, exist_ok=True)
        with open(CACHE, "w") as f:
            for r in jl(f"{DR}/feats.jsonl"):
                r.pop("p", None)
                c[r["map"]] = r
                f.write(json.dumps(r) + "\n")
    return c


def _one(job):
    """(name, otf map entry, kept map path or None, tmp dir) -> (name, features or None). hetfeat = dr56's extractor."""
    name, m, kept, _ = job
    import hetfeat
    return name, hetfeat.feats_of(m, kept)


def ensure_feats(tags, cache):
    """Features for every map of the given reads; missing ones are computed (kept file, else rebuilt from the seed)."""
    jobs = []
    tmp = f"{ROOT}/tmp{os.getpid()}"
    for t in tags:
        o = otf_of(t)
        for m in (o or {}).get("maps", []):
            if m["name"] not in cache:
                kept = f"{PANEL}/{t}/{m['name']}.map26a"
                jobs.append((m["name"], m, kept if os.path.exists(kept) else None, tmp))
    if not jobs:
        return 0
    if len(jobs) > CONDOR_MIN:  # many maps: on Condor nodes (readmany), ~100 maps a chunk
        condor_feats([(n, m) for n, m, kept, _ in jobs], cache)  # 8 Nov: kept maps too: rebuilt from their seeds, 60 of 60 identical to the local features (it was 1.9 cores on HOST)
        jobs = [j for j in jobs if j[0] not in cache]  # anything the nodes could not build stays local
        if not jobs:
            return 0
    from multiprocessing import Pool
    t0, n = time.time(), 0
    os.makedirs(ROOT, exist_ok=True)
    with Pool(min(4, max(2, (os.cpu_count() or 4) // 4)), initializer=os.nice, initargs=(10,)) as pool, open(CACHE, "a") as f:
        for name, ft in pool.imap_unordered(_one, jobs, chunksize=8):
            if ft:
                ft.pop("p", None)
                ft["map"] = name
                cache[name] = ft
                f.write(json.dumps(ft) + "\n")
                n += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"features: {n} of {len(jobs)} new maps in {time.time() - t0:.0f} s (cache {CACHE})", file=sys.stderr)
    return n


CONDOR_MIN = 150


def condor_feats(items, cache, chunk=100):
    """[(name, otf map entry)] -> features computed by readmany jobs (tools/lab/hetfeat.py read()), merged into the cache."""
    run = f"{ROOT}/chunks/run{os.getpid()}"
    os.makedirs(run, exist_ok=True)
    paths = []
    for k in range(0, len(items), chunk):
        p = f"{run}/c{k // chunk:05d}.json"
        json.dump([m for _, m in items[k:k + chunk]], open(p, "w"))
        paths.append(p)
    open(f"{run}/list.txt", "w").write("\n".join(paths) + "\n")
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/readmany.py"), os.path.join(REPO, "tools/lab/hetfeat.py"),
                        f"{run}/list.txt", "--out", f"{run}/out.jsonl", "--per-job", "3"],
                       cwd=REPO, capture_output=True, text=True)
    n = bad = 0
    with open(CACHE, "a") as f:
        for ln in open(f"{run}/out.jsonl") if os.path.exists(f"{run}/out.jsonl") else []:
            g = json.loads(ln)
            for name, ft in (g.get("res") or {}).items():
                if ft:
                    ft["map"] = name
                    cache[name] = ft
                    f.write(json.dumps(ft) + "\n")
                    n += 1
                else:
                    bad += 1
    print(f"features on Condor: {n} of {len(items)} maps ({bad} failed to rebuild) in {time.time() - t0:.0f} s; readmany rc "
          f"{r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}", file=sys.stderr)
    shutil.rmtree(run, ignore_errors=True)


_otf = {}
FIRING_ONLY = False


def otf_of(tag):
    if tag not in _otf:
        p = f"{PANEL}/{tag}/otf.json"
        try:
            _otf[tag] = json.load(open(p))
        except (OSError, ValueError):
            _otf[tag] = None
    return _otf[tag]


# ---------------- reads ----------------

def load_read(tag, cand=None):
    """-> (cand, base, [map rows]) for one panel dir."""
    p = f"{PANEL}/{tag}/fp_games.jsonl"
    gs = jl(p) if os.path.exists(p) else []
    if not gs:
        return None, None, []
    cand = cand or gs[0]["a"]
    other = collections.Counter(g["b"] if g["a"] == cand else g["a"] for g in gs if cand in (g["a"], g["b"]))
    base = other.most_common(1)[0][0] if other else None
    lab = {m["name"]: m for m in (otf_of(tag) or {}).get("maps", [])}
    per = collections.defaultdict(dict)
    for g in gs:
        if g["a"] == cand and g["b"] == base:
            side, so, sf = "A", g.get("sa") or {}, g.get("sb") or {}
        elif g["b"] == cand and g["a"] == base:
            side, so, sf = "B", g.get("sb") or {}, g.get("sa") or {}
        else:
            continue
        w = g.get("win")
        s = 1.0 if w == side else 0.0 if w in ("A", "B") else 0.5
        m = max(-1.0, min(1.0, ((so.get("gems") or 0) - (sf.get("gems") or 0)) / 1000))
        per[g["map"]][side] = (s, m, tuple(so.get(k) for k in ("gems", "deaths", "earnedGold")), tuple(sf.get(k) for k in ("gems", "deaths", "earnedGold")))
    rows = []
    for name, d in per.items():
        if len(d) < 2:
            continue
        L = (lab.get(name) or {}).get("labels") or {}
        ch = not (d["A"][2] == d["B"][3] and d["A"][3] == d["B"][2])  # unchanged: the two seats' games are mirrors (dr56 scores.py)
        rows.append(dict(read=tag, map=name, s=(d["A"][0] + d["B"][0]) / 2, m=(d["A"][1] + d["B"][1]) / 2, ch=ch,
                         **{k: L.get("area" if k == "area_l" else k) for k in LABELS}))
    return cand, base, rows


def read_tags_for(regex):
    """Panel dirs whose candidate (first game's A bot) matches regex."""
    out = []
    rx = re.compile(regex)
    def _mt(x):  # a read dir removed between the glob and here
        try:
            return os.path.getmtime(x)
        except OSError:
            return -1.0
    for f in sorted(glob.glob(f"{PANEL}/*/fp_games.jsonl"), key=_mt):
        try:
            with open(f) as fh:
                g = json.loads(fh.readline())
        except (OSError, ValueError):
            continue
        if rx.search(g.get("a", "")):
            out.append(os.path.basename(os.path.dirname(f)))
    return out


# ---------------- statistics ----------------

def split_half(name, read):
    return int(hashlib.sha1(f"{read}|{name}|hetero1".encode()).hexdigest()[:8], 16) & 1


class Data:
    def __init__(self, rows, cache):
        self.rows = [r for r in rows if r["map"] in cache]
        self.miss = len(rows) - len(self.rows)
        n = len(self.rows)
        self.y = np.array([r["s"] for r in self.rows])
        self.mg = np.array([r["m"] for r in self.rows])
        self.ch = np.array([bool(r.get("ch", True)) for r in self.rows])
        reads = sorted({r["read"] for r in self.rows})
        self.reads = reads
        self.ri = np.array([reads.index(r["read"]) for r in self.rows])
        self.half = np.array([split_half(r["map"], r["read"]) for r in self.rows])
        X = np.full((n, len(FEATS)), np.nan)
        for i, r in enumerate(self.rows):
            f = cache[r["map"]]
            for j, k in enumerate(FEATS):
                v = f.get(k)
                if isinstance(v, (int, float)):
                    X[i, j] = v
        for j in range(len(FEATS)):  # missing -> median (alt_d on altar-less maps), counted in the report
            col = X[:, j]
            med = np.nanmedian(col) if np.isfinite(col).any() else 0.0
            col[~np.isfinite(col)] = med
        self.X = X
        rules = []
        for j, k in enumerate(FEATS):
            cuts = sorted({float(np.percentile(X[:, j], q)) for q in QS})
            for c in cuts:
                hi = X[:, j] > c
                if 0 < hi.sum() < n:
                    rules.append((k, c, hi))
        self.rules = rules
        self.H = np.array([r[2] for r in rules], dtype=float) if rules else np.zeros((0, n))

    def contrast(self, mask, Y):
        """Pooled within-read contrast (leaf hi minus lo) for every rule on the maps in mask; Y (n x P) outcome columns.
        -> d (R x P), z (R x P), nh, nl (R) and per-read pieces for Q."""
        R, P = self.H.shape[0], Y.shape[1]
        num, den = np.zeros((R, P)), np.zeros((R, 1))
        nh_t, nl_t = np.zeros(R), np.zeros(R)
        per = []
        for r in range(len(self.reads)):
            sel = mask & (self.ri == r)
            if sel.sum() < 4:
                continue
            Hr, Yr = self.H[:, sel], Y[sel]
            nh = Hr.sum(1)
            nl = sel.sum() - nh
            ok = (nh >= 2) & (nl >= 2)
            sh = Hr @ Yr
            tot = Yr.sum(0, keepdims=True)
            with np.errstate(divide="ignore", invalid="ignore"):
                d = sh / nh[:, None] - (tot - sh) / nl[:, None]
                var = Yr.var(0, ddof=1, keepdims=True) * (1 / nh[:, None] + 1 / nl[:, None])
                w = np.where(ok[:, None] & (var > 0), 1 / var, 0.0)
            d = np.nan_to_num(d)
            num += w * d
            den += w[:, :1]
            nh_t += nh
            nl_t += nl
            per.append((r, d[:, 0], w[:, 0]))
        with np.errstate(divide="ignore", invalid="ignore"):
            dp = np.where(den > 0, num / den, 0.0)
            z = np.where(den > 0, num / np.sqrt(den), 0.0)
        return dp, z, nh_t, nl_t, per

    def eligible(self, mask, min_half):
        n = mask.sum()
        nh = (self.H[:, mask] > 0).sum(1)
        return (nh >= max(0.15 * n, min_half)) & (n - nh >= max(0.15 * n, min_half))


def perm_cols(d, P, seed=1):
    """Column 0 = observed outcome, columns 1..P = within-read permutations."""
    rng = np.random.default_rng(seed)
    Y = np.empty((len(d.y), P + 1))
    Y[:, 0] = d.y
    for r in range(len(d.reads)):
        idx = np.where(d.ri == r)[0]
        for p in range(1, P + 1):
            Y[idx, p] = d.y[rng.permutation(idx)]
    return Y


def wilson_ci(mean, n, sd):
    se = sd / math.sqrt(max(1, n))
    return mean - 1.96 * se, mean + 1.96 * se


def describe(d, mask, sel):
    """Leaf mean score with CI on the maps in mask & sel."""
    v = d.y[mask & sel]
    if len(v) < 2:
        return float("nan"), (float("nan"), float("nan")), len(v)
    return float(v.mean()), wilson_ci(float(v.mean()), len(v), float(v.std(ddof=1))), len(v)


def analyse(d, P, min_half):
    from scipy.stats import chi2
    n = len(d.y)
    allm = np.ones(n, bool)
    res = dict(n=n, reads=len(d.reads), mean=float(d.y.mean()) if n else float("nan"))
    if n < 2 or not d.rules:
        res["note"] = "no maps with features"
        return res
    res["ci"] = wilson_ci(res["mean"], n, float(d.y.std(ddof=1)))
    # 3. any heterogeneity: max |z| over eligible rules, permutation null (full data, within read)
    Y = perm_cols(d, P)
    _, z, nh, nl, _ = d.contrast(allm, Y)
    el = (nh >= 0.15 * n) & (nl >= 0.15 * n)
    res["n_rules"] = int(el.sum())
    if not el.any():
        res["note"] = "no rule leaves >= 15% of maps on both sides"
        return res
    az = np.abs(z[el])
    mx = az.max(0)
    res["zmax"] = float(mx[0])
    res["p_max"] = float((mx[1:] >= mx[0]).mean()) if P else float("nan")
    res["null_zmax95"] = float(np.percentile(mx[1:], 95)) if P else float("nan")
    ez2 = float((mx[1:] ** 2).mean()) if P else 1.0
    pr = ((az[:, 1:] >= az[:, :1]).sum(1) + 1) / (P + 1) if P else np.ones(az.shape[0])
    order = np.argsort(pr)
    q = np.empty_like(pr)
    m = len(pr)
    prev = 1.0
    for k in range(m - 1, -1, -1):  # BH step-up
        i = order[k]
        prev = min(prev, pr[i] * m / (k + 1))
        q[i] = prev
    elidx = np.where(el)[0]
    dfull, zfull, _, _, _ = d.contrast(allm, d.y[:, None])
    res["rules"] = sorted([dict(f=d.rules[i][0], c=d.rules[i][1], d=float(dfull[i, 0]), z=float(zfull[i, 0]), p=float(pr[k]),
                                q=float(q[k]), share=float(d.H[i].mean())) for k, i in enumerate(elidx)], key=lambda r: r["p"])
    # 4. honest cross-fit
    def crossfit(split, mh):
        out = []
        for disc in (0, 1):
            A, B = split == disc, split != disc
            ok = d.eligible(A, mh) & d.eligible(B, mh)
            if not ok.any():
                out.append(None)
                continue
            dA, zA, _, _, _ = d.contrast(A, d.y[:, None])
            zz = np.where(ok, np.abs(zA[:, 0]), -1)
            i = int(np.argmax(zz))
            sign = 1 if dA[i, 0] > 0 else -1
            leaf = d.H[i] > 0 if sign > 0 else d.H[i] == 0
            dB, zB, _, _, perB = d.contrast(B, d.y[:, None])
            lm, lci, ln = describe(d, B, leaf)
            cm, cci, cn = describe(d, B, ~leaf)
            k = max(0.0, 1 - ez2 / max(1e-9, zA[i, 0] ** 2))
            Q = sum(w * (dd - dB[i, 0]) ** 2 for _, dd, w in [(r, x[i], w_[i]) for r, x, w_ in perB] if w > 0)
            kq = sum(1 for _, x, w_ in perB if w_[i] > 0)
            out.append(dict(rule=i, f=d.rules[i][0], c=d.rules[i][1], op=">" if sign > 0 else "<=", z_disc=float(abs(zA[i, 0])),
                            d_disc=float(abs(dA[i, 0])), d_est=float(sign * dB[i, 0]), z_est=float(sign * zB[i, 0]),
                            leaf=(lm, lci, ln), comp=(cm, cci, cn), shrunk=float(abs(dA[i, 0]) * k),
                            Q=float(Q), Q_p=float(chi2.sf(Q, kq - 1)) if kq > 1 else float("nan"), share=float(leaf.mean())))
        return out

    halves = crossfit(d.half, min_half)
    # dr56 §8 READ SPLIT: discover on even reads, estimate on odd reads (and swap): the honest analogue of a confirm on a new set
    res["readsplit"] = crossfit(d.ri % 2, min(min_half, 100)) if len(d.reads) >= 4 else None
    res["halves"] = halves
    hv = [h for h in halves if h]
    if hv:
        same = len(hv) == 2 and hv[0]["rule"] == hv[1]["rule"] and hv[0]["op"] == hv[1]["op"]
        # cross-fit: the two honest estimates are independent; averaging them (same rule) is honest, taking the larger is not
        # (calibration: max of halves passed z >= 1.645 on 11.8% of null reads). Disagreeing halves: the weaker one stands.
        if same:
            best = dict(hv[0])
            best["d_est"] = (hv[0]["d_est"] + hv[1]["d_est"]) / 2
            best["z_est"] = (hv[0]["z_est"] + hv[1]["z_est"]) / math.sqrt(2)
            lm = [h["leaf"] for h in hv]
            n_ = lm[0][2] + lm[1][2]
            mm = (lm[0][0] * lm[0][2] + lm[1][0] * lm[1][2]) / max(1, n_)
            hw = max((lm[0][1][1] - lm[0][1][0]), (lm[1][1][1] - lm[1][1][0])) / 2 / math.sqrt(2)
            best["leaf"] = (mm, (mm - hw, mm + hw), n_)
            cm = [h["comp"] for h in hv]
            best["comp"] = ((cm[0][0] * cm[0][2] + cm[1][0] * cm[1][2]) / max(1, cm[0][2] + cm[1][2]), cm[0][1], cm[0][2] + cm[1][2])
        else:
            best = min(hv, key=lambda h: h["z_est"])
        res["best"] = best
        res["agree"] = same
        i = best["rule"]
        leaf = d.H[i] > 0 if best["op"] == ">" else d.H[i] == 0
        best["fire_leaf"] = float(d.ch[leaf].mean()) if leaf.any() else float("nan")
        best["fire_rest"] = float(d.ch[~leaf].mean()) if (~leaf).any() else float("nan")
        # dr56 §8: a firing-share leaf (the flag fires more often there, same effect per firing) reads like a map-dependent
        # effect. The contrast on changed maps only separates the two, but is honest only when firing is decided before play.
        dc, zc, nhc, nlc, _ = d.contrast(d.ch, d.y[:, None])
        sg = 1 if best["op"] == ">" else -1
        best["ch_d"], best["ch_z"], best["ch_n"] = float(sg * dc[i, 0]), float(sg * zc[i, 0]), int(d.ch.sum())
        best["ladder"] = ladder_share(best["f"], best["op"], best["c"])
        lm = best["leaf"][0]
        res["gated_gain"] = best["share"] * (lm - 0.5)  # candidate only on leaf maps, base elsewhere
    # per-feature tercile table (descriptive)
    tab = []
    for j, k in enumerate(FEATS):
        cuts = np.percentile(d.X[:, j], [33.3, 66.7])
        bins = [d.X[:, j] <= cuts[0], (d.X[:, j] > cuts[0]) & (d.X[:, j] <= cuts[1]), d.X[:, j] > cuts[1]]
        tab.append((k, [describe(d, allm, b) for b in bins], [float(x) for x in cuts]))
    res["terciles"] = tab
    lab = collections.defaultdict(list)
    for r, s in zip(d.rows, d.y):
        if r.get("fam"):
            lab[r["fam"]].append(s)
    res["fams"] = sorted(((k, float(np.mean(v)), len(v)) for k, v in lab.items() if len(v) >= 20), key=lambda x: x[1])
    return res


LADDER = "/data/USER/st/dr56/ladderfeats.json"  # dr56: the same features on the 81 published ladder maps


def ladder_share(f, op, c):
    try:
        L = [x for x in json.load(open(LADDER)) if isinstance(x.get(f), (int, float))]
    except (OSError, ValueError):
        return None
    if not L:
        return None
    return sum((x[f] > c) if op == ">" else (x[f] <= c) for x in L) / len(L)


def fmt_rule(h):
    return f"{h['f']} {h['op']} {h['c']:g}"


def examples(d, h, k=3):
    """Leaf maps (estimation side) the candidate won/lost on both seats: for replay walks (the WHY step)."""
    leaf = (d.H[h["rule"]] > 0) if h["op"] == ">" else (d.H[h["rule"]] == 0)
    est = d.half != (0 if h is not None else 0)
    won = [(r["read"], r["map"]) for r, s, l in zip(d.rows, d.y, leaf) if l and s == 1.0][:k]
    lost = [(r["read"], r["map"]) for r, s, l in zip(d.rows, d.y, leaf) if l and s == 0.0][:k]
    return won, lost


def rs_note(res, b):
    rsx = [h for h in (res.get("readsplit") or []) if h]
    if not rsx:
        return ""
    same = [h for h in rsx if h["f"] == b["f"] and h["op"] == b["op"]]
    return (f"; read split: {len(same)}/{len(rsx)} pick {b['f']} {b['op']}" + (f" (est. {', '.join(f'{h['d_est']:+.3f} z {h['z_est']:.1f}' for h in same)})" if same else ""))


def summary_line(res):
    if "best" not in res:
        return f"where it helps: no split read ({res.get('note') or 'too few maps per half'}; n {res['n']}; p_max {res.get('p_max', float('nan')):.2f})"
    b = res["best"]
    if not res.get("agree"):
        return (f"where it helps: no stable rule (cross-fit halves pick different rules; p_max {res['p_max']:.3f}, n {res['n']}; "
                f"overall {res['mean']:.3f})")
    sig = "heterogeneous" if res["p_max"] < 0.05 else "no real heterogeneity"
    lad = f"{100 * b['ladder']:.0f}%" if b.get("ladder") is not None else "?"
    firing = abs(b["fire_leaf"] - b["fire_rest"]) >= 0.10
    return (f"where it helps: {fmt_rule(b)} (leaf {100 * b['share']:.0f}% of fresh maps, {lad} of ladder maps) leaf {b['leaf'][0]:.3f} "
            f"[{b['leaf'][1][0]:.3f}, {b['leaf'][1][1]:.3f}] honest n{b['leaf'][2]}, rest {b['comp'][0]:.3f}; p_max {res['p_max']:.3f} ({sig}); "
            f"fires on {100 * b['fire_leaf']:.0f}% of leaf v {100 * b['fire_rest']:.0f}% of rest maps, changed-maps contrast {b['ch_d']:+.3f} "
            f"z {b['ch_z']:.1f}" + (" -> FIRING SHARE differs: much of the leaf gap is how often the change fires there; the changed-maps contrast is the "
                                      "map-dependent part (honest only if firing is decided before play; then re-run with --firing)" if firing else "")
            + rs_note(res, b) + f"; gated gain {100 * res['gated_gain']:+.2f} pts v ungated {100 * (res['mean'] - .5):+.2f}")


def report(tags, cand, P, min_half, brief, name):
    cache = load_cache(need_maps(tags))
    rows, cb = [], collections.Counter()
    for t in tags:
        c, b, rs = load_read(t, cand)
        if rs:
            rows += rs
            cb[(c, b)] += len(rs)
    if not rows:
        sys.exit(f"hetero: no paired maps in {tags}")
    ensure_feats(sorted({r["read"] for r in rows}), cache)
    if FIRING_ONLY:  # dr56 §8: only when firing is decided before play (e.g. a draft-gated flag); never for mid-game changes
        rows = [r for r in rows if r.get("ch")]
    d = Data(rows, cache)
    res = analyse(d, P, min_half)
    line = summary_line(res)
    if brief:
        print(line)
        return res
    name = name or (tags[0] if len(tags) == 1 else f"pool_{hashlib.sha1(' '.join(tags).encode()).hexdigest()[:8]}")
    L = [f"# hetero: {name}", "",
         f"_{res['n']} map pairs from {len(d.reads)} read(s) ({d.miss} without features); {time.strftime('%Y-%m-%d %H:%MZ', time.gmtime())}; "
         f"tools/lab/hetero.py, statistics per /data/USER/st/dr56/hetero_stats.md. Reads: {', '.join(d.reads)}. "
         f"Candidate v base: {'; '.join(f'{c} v {b} ({n})' for (c, b), n in cb.items())}._", "",
         "## Summary", "", f"- overall candidate score {res['mean']:.3f} [{res['ci'][0]:.3f}, {res['ci'][1]:.3f}]",
         f"- any heterogeneity: max |z| {res.get('zmax', float('nan')):.2f} over {res.get('n_rules', 0)} rules, permutation p_max "
         f"{res.get('p_max', float('nan')):.3f} (null 95% max |z| {res.get('null_zmax95', float('nan')):.2f}, {P} permutations within read)",
         f"- {line}"]
    if "best" in res:
        b = res["best"]
        L += [f"- cross-fit halves {'AGREE' if res['agree'] else 'DISAGREE'} on the rule; shrunk prediction for a confirm read: "
              f"contrast {b['shrunk']:+.3f} (discovery {b['d_disc']:+.3f}, honest {b['d_est']:+.3f} z {b['z_est']:.2f})",
              f"- across reads: Cochran Q {b['Q']:.1f} p {b['Q_p']:.3f}" + (" (the contrast depends on the read/base: don't pool)" if b['Q_p'] < 0.05 else ""),
              "", "## Honest cross-fit (rule chosen on one half, estimated on the other)", "",
              "| discovery half | rule | disc z | est. contrast | est. z | leaf score [CI] n | rest score [CI] n |", "|---|---|---|---|---|---|---|"]
        for k, h in enumerate(res["halves"]):
            if h:
                L.append(f"| {k} | {fmt_rule(h)} | {h['z_disc']:.2f} | {h['d_est']:+.3f} | {h['z_est']:.2f} | {h['leaf'][0]:.3f} [{h['leaf'][1][0]:.3f}, "
                         f"{h['leaf'][1][1]:.3f}] {h['leaf'][2]} | {h['comp'][0]:.3f} [{h['comp'][1][0]:.3f}, {h['comp'][1][1]:.3f}] {h['comp'][2]} |")
            else:
                L.append(f"| {k} | no rule with >= 15% and >= {min_half} maps per side in both halves | | | | | |")
        rsx = res.get("readsplit")
        if rsx:
            L += ["", "Read split (dr56 §8: rule found on even reads, estimated on odd reads, and swapped):", ""]
            for k, h in enumerate(rsx):
                L.append(f"- discover on {'even' if k == 0 else 'odd'} reads: " + (f"{fmt_rule(h)}, estimate {h['d_est']:+.3f} z {h['z_est']:.2f}, "
                         f"leaf {h['leaf'][0]:.3f} n{h['leaf'][2]} v rest {h['comp'][0]:.3f}" if h else "no eligible rule"))
        won, lost = examples(d, b)
        L += ["", f"Leaf maps won on both seats (walk these for WHY): {', '.join(f'{m} ({r})' for r, m in won) or '-'}; lost on both: "
              f"{', '.join(f'{m} ({r})' for r, m in lost) or '-'}."]
    L += ["", "## Screening list (full data; BH q <= .10 is listed as a lead, not a result)", "", "| rule | contrast hi-lo | z | perm p | BH q | share hi |", "|---|---|---|---|---|---|"]
    for r in res.get("rules", [])[:15]:
        L.append(f"| {r['f']} > {r['c']:g} | {r['d']:+.3f} | {r['z']:.2f} | {r['p']:.3f} | {r['q']:.3f}{' *' if r['q'] <= .10 else ''} | {100 * r['share']:.0f}% |")
    L += ["", "## Score by feature tercile (descriptive)", "", "| feature | cuts | low | mid | high |", "|---|---|---|---|---|"]
    for k, bins, cuts in res.get("terciles", []):
        L.append(f"| {k} | {cuts[0]:g} / {cuts[1]:g} | " + " | ".join(f"{m:.3f} n{n}" for m, _, n in bins) + " |")
    if res.get("fams"):
        L += ["", "Generator families (descriptive, n >= 20; a bot can't read these): " + ", ".join(f"{k} {m:.3f} n{n}" for k, m, n in res["fams"])]
    os.makedirs(OUT, exist_ok=True)
    p = f"{OUT}/{name}.md"
    open(p, "w").write("\n".join(L) + "\n")
    print("\n".join(L[4:9 + (2 if "best" in res else 0)]))
    print(f"report: {p}")
    return res


# ---------------- confirm ----------------

def parse_rule(s):
    m = re.fullmatch(r"\s*([A-Za-z_0-9]+)\s*(>|<=)\s*(-?[0-9.]+)\s*", s)
    if not m or m.group(1) not in FEATS:
        sys.exit(f"hetero: RULE must be FEATURE>CUT or FEATURE<=CUT with FEATURE in {FEATS}")
    return m.group(1), m.group(2), float(m.group(3))


def confirm(a):
    f, op, c = parse_rule(a[0])
    n = int(a[a.index("--n") + 1]) if "--n" in a else 300
    tag = a[a.index("--out") + 1] if "--out" in a else f"hc{int(time.time()) % 10**8}"
    if os.path.exists(f"{PANEL}/{tag}"):
        sys.exit(f"hetero confirm: {PANEL}/{tag} exists")
    cache = load_cache()
    want = {True: n // 2, False: n - n // 2}
    got = {True: [], False: []}
    tries = 0
    while (len(got[True]) < want[True] or len(got[False]) < want[False]) and tries < 12:
        tries += 1
        work = f"{ROOT}/confirm_{tag}_{tries}"
        r = subprocess.run([sys.executable, "-I", "tools/lab/stratmaps.py", work, "--n", "300", "--take", "--who", f"hetero:{tag}"],
                           cwd=REPO, capture_output=True, text=True)
        o = json.load(open(f"{work}/otf.json")) if r.returncode == 0 and os.path.exists(f"{work}/otf.json") else None
        if not o:
            print(f"stratmaps failed: {(r.stdout + r.stderr)[-300:]}", file=sys.stderr)
            break
        _otf[f"_c{tries}"] = o
        jobs = [(m["name"], m, f"{work}/{m['name']}.map26a" if os.path.exists(f"{work}/{m['name']}.map26a") else None, f"{ROOT}/tmpc")
                for m in o["maps"] if m["name"] not in cache]
        from multiprocessing import Pool
        with Pool(8, initializer=os.nice, initargs=(10,)) as pool:
            for name, ft in pool.imap_unordered(_one, jobs, chunksize=8):
                if ft:
                    ft.pop("p", None)
                    ft["map"] = name
                    cache[name] = ft
                    open(CACHE, "a").write(json.dumps(ft) + "\n")
        for m in o["maps"]:
            ft = cache.get(m["name"])
            if not ft or not isinstance(ft.get(f), (int, float)):
                continue
            inleaf = ft[f] > c if op == ">" else ft[f] <= c
            if len(got[inleaf]) < want[inleaf]:
                got[inleaf].append(m)
        shutil.rmtree(work, ignore_errors=True)
        print(f"confirm: batch {tries}: leaf {len(got[True])}/{want[True]}, rest {len(got[False])}/{want[False]}", file=sys.stderr)
    maps = got[True] + got[False]
    random.Random(tag).shuffle(maps)
    os.makedirs(f"{PANEL}/{tag}")
    json.dump(dict(maps=maps, tag=tag, pool="hetero-confirm", made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   rule=a[0], log=[]), open(f"{PANEL}/{tag}/otf.json", "w"))
    print(f"wrote {PANEL}/{tag}/otf.json: {len(got[True])} leaf ({a[0]}) + {len(got[False])} rest maps, never saved")
    print(f"pre-register the rule and the shrunk prediction (date -u) BEFORE playing, then:\n  python3 -I tools/lab/inforead.py CAND BASE --who WHO --maps-from {tag}"
          f"   # plays exactly these maps (h2h only unless --opps)\n  python3 -I tools/lab/hetero.py read <the inforead TAG> --perm 0   # leaf v rest")


# ---------------- calibration ----------------

def calibrate(a):
    k = int(a[a.index("--k") + 1]) if "--k" in a else 127
    P = int(a[a.index("--perm") + 1]) if "--perm" in a else 500
    tags = [r["tag"] for r in json.load(open("/data/USER/st/fc11/tc_table.json")) if os.path.exists(f"{PANEL}/{r['tag']}/fp_games.jsonl")][:k]
    cache = load_cache()
    ensure_feats(tags, cache)
    ps, hon = [], []
    for t in tags:
        _, _, rows = load_read(t)
        d = Data(rows, cache)
        res = analyse(d, P, 0)
        if "p_max" in res:
            ps.append(res["p_max"])
        b = res.get("best")
        if b:
            hon.append(b["z_est"] >= 1.645)
    ps = np.array(ps)
    out = (f"calibration on {len(ps)} null-null trunk-code reads (fc11; {P} permutations): p_max < .05 in {100 * (ps < .05).mean():.1f}% "
           f"(want ~5%), < .10 in {100 * (ps < .10).mean():.1f}%; honest est. z >= 1.645 in {100 * np.mean(hon) if hon else float('nan'):.1f}% "
           f"of {len(hon)} reads with a split (min-half 0: single 600-map reads)")
    print(out)
    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/calibration.md", "w").write(out + "\n")


def hetero_slot():
    """One of HETERO_SLOTS (default 2) machine-wide run slots (flock): reads start hetero detached after every read, and 10+ ran
    at once (4 Nov ~23:00Z: ~1.2 GB and a worker pool each; owner: careful with RAM and CPU). -> the open lock file."""
    import fcntl
    d = f"{ROOT}/slots"
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    while True:
        if time.time() - t0 > float(os.environ.get("HETERO_WAIT", "1800")):  # 10 Nov: 63 reads queued up to 6 h for 2 slots (2.4 GB idle)
            print(f"hetero: skipped: both run slots busy for {os.environ.get('HETERO_WAIT', '1800')} s (information row only)", flush=True)
            sys.exit(0)
        for k in range(int(os.environ.get("HETERO_SLOTS", "2"))):
            f = open(f"{d}/slot{k}.lock", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except OSError:
                f.close()
        time.sleep(2)


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("read", "flag", "confirm", "calibrate", "feats"):
        sys.exit(__doc__)
    opt = lambda k, dflt: a[a.index(k) + 1] if k in a else dflt
    if a[0] == "confirm":
        return confirm(a[1:])
    if a[0] == "calibrate":
        return calibrate(a[1:])
    if a[0] == "feats":  # features only (no analysis): hetero.py feats TAG ... | --flag REGEX | --calib
        tags = [x for x in a[1:] if not x.startswith("--")]
        if "--flag" in a:
            tags = read_tags_for(a[a.index("--flag") + 1])
        if "--calib" in a:
            tags = [r["tag"] for r in json.load(open("/data/USER/st/fc11/tc_table.json"))]
        tags = [t for t in tags if otf_of(t)]
        return ensure_feats(tags, load_cache(need_maps(tags)))
    pos, skip = [], False
    for x in a[1:]:  # positionals: everything that is neither an option nor the value right after one
        if skip:
            skip = False
        elif x in ("--cand", "--perm", "--min-half", "--out"):
            skip = True
        elif not x.startswith("--"):
            pos.append(x)
    tags = pos if a[0] == "read" else [t for rx in pos for t in read_tags_for(rx)]
    if not tags:
        sys.exit("hetero: no reads")
    global FIRING_ONLY
    FIRING_ONLY = "--firing" in a
    slot = hetero_slot()  # noqa: F841  (held until exit)
    report(tags, opt("--cand", None), int(opt("--perm", 2000)), int(opt("--min-half", 300)), "--brief" in a, opt("--out", None))


if __name__ == "__main__":
    main()
