#!/usr/bin/env python3
"""eventfork: a paired causal read of a data flip at the moments its code fires (Tool builder, 11 Nov; Path Finding ASK 1).

For each chosen firing (map, seat, round R) the base game DONOR (flag 0) v OPP is played on a Condor pilot to the first turn of R,
then cxe forks two children from that exact state: the FLIP (DONOR's flip.sh data flip: our team's instances get its data bytes)
and a NULL arm (an identity alt: the base .so itself). Parent (base), flip and null each play on to round R+Kmax-1. One cxe call
per fork: `cxe A.so B.so MAP OUT --fork-at R --fork-k Kmax --alt-team SEAT --alt FLIP.so --alt BASE.so` (tools/cxe/README.md 'Fork').
Value per team per round, as cxefork.py and the ceiling ledgers count it: V = tributed gems + carried gems + .35 x earned gold
(the replay's per-round row). Offset k means the row of round R+k-1 (k rounds played from R; a branch whose game ended earlier
uses its last row). Per fork: dF = V(us - them) flip - base, dN = V(us - them) null - base, at each k.

usage:
  python3 -I tools/cxe/eventfork.py DONOR OPP (--flips "FLAG=V ..." | --flipbot NAME) (--fire-from TSV | --fire-from DGDIR --tag T)
        [--class SPEC] [--n 400 | --per-class N | --budget C=N,...] [--per-game 1] [--pick first|random] [--k 30,100]
        [--mapdir DIR] [--maplist FILE] [--seed 1] [--out DIR] [--keep] [--dry]
  python3 -I tools/cxe/eventfork.py DONOR OPP (--flips ... | --flipbot NAME) --check0 N [--mapdir DIR] [--seed 1]
        validation: N maps (seats alternate), a fork at round 0 with alt FLIP v the straight FLIP game, and an identity fork at round
        150 v the straight base game, compared byte for byte.

DONOR    a trunk bot whose idea flag is 0 (flip.sh refuses non-data flags). --flips builds bots/nova_ef_<slug> with tools/lab/flip.sh;
         --flipbot reuses a flip already built on DONOR. Either way the alt must be a pure data flip (code sections compared).
FIRINGS  (a) TSV: columns map, seat, round[, class] (a header line naming the columns is optional; extra columns are kept for
         --class col:NAME). seat = the seat DONOR plays (A|B); map = a name (resolved in --maplist, then --mapdir) or a path.
         (b) a tools/lab/dgkit.py run dir (DGDIR/rep/MAP__a|b.repl26a: our bot is team a in __a games) and --tag T: every record
         with tag T from our team marks a firing at its round. Both record kinds are read: dgkit's `D ROUND SLOT TAG ...` (debug
         diag copy) and dglog.h's `DG TAG ROUND ...` (release diag copy). A diag copy's game may drift from the release base game
         after its first record (debug timing / record fuel): treat later firing rounds as approximate; --per-game 1 --pick first
         (the default) forks at the first firing, where base, diag and flip games are still identical.
CLASSES  --class SPEC groups firings, each class with its own budget and report:
           col:NAME           the TSV's column NAME (a 4th unnamed column is 'class')
           rband:100,300      round bands r<100, 100-299, >=300
           map:NAME:0.3,0.6   tools/lab/mapclass.py class NAME binned at the cuts (draft-time map features only)
         budget: --n N (each class; default 400), --per-class N (the same), or --budget C=N,... (named classes; others get --per-class or 0).
         Within a class, at most --per-game firings per (map, seat) (first by round, or random), then a seeded random sample.
HALVES   split by MAP: every map goes wholly to half A or half B (seeded), so forks of one map never sit in both halves.

Report (OUT/report.txt, rows OUT/forks.tsv): header with the pre-stated drop rules, then per class and k: flip mean dF, SE, spread
(sd per fork), the share of forks whose play changed after R, halves A/B (mean, SE, sd each); null mean dN (the null bias), SE, sd.
DROP RULES (pre-stated, per class at the largest k): null bias |mean dN| > 3 V, or spread sd(dF) > 150 V per fork -> DROP the read.
11 Nov (Path Finding's first reads): (1) STATE: a flip gets its data bytes at the fork, not the memory its flag-on game builds from
round 0. Split an idea into FOO_STATE (writes the memory, changes no decision; play-identical to live by the usual identity check) and
FOO_ACT; pass --state "FOO_STATE=1" (both arms) and --flips "FOO_ACT=1". (2) NULL: the default null (the base) replays the parent
exactly, so it is reported as a plumbing check and not in the drop rule; --null-flips "..." gives a real control (e.g. ACT on, decision
masked). (3) FIRINGS: take rounds from RELEASE records (tools/lab/dglog.h, release build; puppet --diag style), not a debug diag:
debug timing drifts from the release parent, and the changed share fell with the firing round.
Pilots: games run through tools/cxe/cxefarm.py at READ_PRIO (env EVENTFORK_PRIO, else READ_PRIO, else 9); branch replays are decoded
on the node and only the decodes come back (deleted after reading unless --keep). Prior use of the fork engine:
condor-work/reports/build_b1197_rollouts.md (null -0.5 +- .7 V; spread ~103 V per fork at +100)."""
import collections
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "lab"))
import cxebuild  # noqa: E402
import cxefork  # noqa: E402

MAPDIR = "/data/zw4424/ablproj_4.0.0/maps"
NULL_MAX, SPREAD_MAX = 3.0, 150.0
NULLREAL = [False]  # a --null-flips control arm (else the identity null: replays the parent exactly, cannot fail)
PRIO = int(os.environ.get("EVENTFORK_PRIO") or os.environ.get("READ_PRIO") or 9)


def opt(a, k, d=None):
    return a[a.index(k) + 1] if k in a else d


# ---------- firings ----------
def stdout_texts(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return {t: z.read(f"team-{t}.stdout").decode("latin1") for t in "ab" if f"team-{t}.stdout" in z.namelist()}
    pre = path[:-8] if path.endswith(".repl26a") else path
    return {t: open(f"{pre}.team-{t}.stdout", encoding="latin1").read() for t in "ab" if os.path.exists(f"{pre}.team-{t}.stdout")}


def fire_from_dg(d, tag):
    rd = os.path.join(d, "rep") if os.path.isdir(os.path.join(d, "rep")) else d
    out = []
    for f in sorted(os.listdir(rd)):
        m = re.fullmatch(r"(.+)__([ab])\.repl26a", f)
        if not m:
            continue
        mp, us = m[1], m[2]
        txt = stdout_texts(os.path.join(rd, f)).get(us, "")
        for ln in txt.splitlines():
            p = ln.replace("\0", "").split()
            try:
                if len(p) >= 4 and p[0] == "D" and p[3] == tag:
                    out.append(dict(map=mp, seat=us.upper(), round=int(p[1])))
                elif len(p) >= 3 and p[0] == "DG" and p[1] == tag:
                    out.append(dict(map=mp, seat=us.upper(), round=int(p[2])))
            except ValueError:
                pass
    return out


def fire_from_tsv(path):
    rows = [ln.rstrip("\n").split("\t") for ln in open(path) if ln.strip() and not ln.startswith("#")]
    if not rows:
        return []
    if rows[0][0].lower() == "map":
        hdr, rows = [h.strip() for h in rows[0]], rows[1:]
    else:
        hdr = ["map", "seat", "round", "class"] + [f"c{i}" for i in range(4, max(len(r) for r in rows))]
    out = []
    for r in rows:
        x = dict(zip(hdr, r))
        x["seat"], x["round"] = x["seat"].strip().upper()[:1], int(x["round"])
        out.append(x)
    return out


def map_path(name, mapdir, listed):
    if os.path.isabs(name) and os.path.exists(name):
        return name
    b = os.path.basename(name)
    b = b[:-7] if b.endswith(".map26a") else b
    if b in listed:
        return listed[b]
    p = os.path.join(mapdir, b + ".map26a")
    return p if os.path.exists(p) else None


def classify(fires, spec, paths):
    if not spec:
        for f in fires:
            f["cls"] = "all"
        return
    kind, _, rest = spec.partition(":")
    if kind == "col":
        for f in fires:
            f["cls"] = str(f.get(rest or "class", "?"))
    elif kind == "rband":
        cuts = [int(x) for x in rest.split(",")]
        for f in fires:
            i = sum(f["round"] >= c for c in cuts)
            lo, hi = ([0] + cuts)[i], (cuts + [None])[i]
            f["cls"] = f"r{lo}-{hi - 1}" if hi is not None else f"r>={lo}"
    elif kind == "map":
        import mapclass
        name, _, cs = rest.partition(":")
        cuts = [float(x) for x in cs.split(",")] if cs else []
        memo = {}
        for f in fires:
            p = paths[f["map"]]
            if p not in memo:
                v = mapclass.values(p, [name]).get(name)
                if v is None:
                    memo[p] = f"{name}=None"
                elif not cuts:
                    memo[p] = f"{name}={v:.2f}"
                else:
                    i = sum(v >= c for c in cuts)
                    memo[p] = f"{name}<{cuts[0]}" if i == 0 else (f"{name}>={cuts[-1]}" if i == len(cuts) else f"{name}[{cuts[i - 1]},{cuts[i]})")
            f["cls"] = memo[p]
    else:
        sys.exit(f"eventfork: bad --class {spec!r} (col:NAME | rband:C1,C2 | map:NAME:C1,C2)")


def choose(fires, a, rng):
    per_game, pick = int(opt(a, "--per-game", "1")), opt(a, "--pick", "first")
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in fires:
        by[f["cls"]][(f["map"], f["seat"])].append(f)
    budget = {}
    if opt(a, "--budget"):
        for kv in opt(a, "--budget").split(","):
            k, _, v = kv.partition("=")
            budget[k] = int(v)
    chosen = {}
    for c, games in sorted(by.items()):
        cand = []
        for key in sorted(games):
            fs = sorted({x["round"]: x for x in games[key]}.values(), key=lambda x: x["round"])
            cand += fs[:per_game] if pick == "first" else rng.sample(fs, min(per_game, len(fs)))
        n = budget.get(c, int(opt(a, "--per-class") or 0) if (opt(a, "--per-class") or budget) else int(opt(a, "--n", "400")))
        chosen[c] = rng.sample(cand, min(n, len(cand))) if n < len(cand) else cand
    return chosen, {c: sum(len(v) for v in g.values()) for c, g in by.items()}


def halves(maps, seed):
    ms = sorted(set(maps))
    random.Random(f"half{seed}").shuffle(ms)
    return {m: "AB"[i % 2] for i, m in enumerate(ms)}


# ---------- branch values ----------
def rows_of(dec):
    c = {k: i for i, k in enumerate(dec["roundCols"])}
    return c, dec["rounds"]


def v_at(dec, rnd, us):
    c, rows = rows_of(dec)
    th = "AB"[us == "A"]
    row = None
    for r in rows:
        if r[0] <= rnd:
            row = r
        else:
            break
    if row is None:
        return None
    v = {t: row[c["sub" + t]] + row[c["carried" + t]] + 0.35 * row[c["earned" + t]] for t in "AB"}
    return v[us] - v[th]


def changed_after(d1, d2, R):
    a = [r for r in d1["rounds"] if r[0] >= R]
    b = [r for r in d2["rounds"] if r[0] >= R]
    return a != b


def stats(xs):
    n = len(xs)
    if not n:
        return (0, float("nan"), float("nan"), float("nan"))
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return n, m, sd / math.sqrt(n) if n else float("nan"), sd


def fmt(s):
    n, m, se, sd = s
    return f"n {n:4d}  mean {m:+7.1f}  SE {se:5.1f}  sd {sd:6.1f}"


# ---------- libraries ----------
def _flipped(donor, flips, pre):
    slug = re.sub(r"[^a-z0-9]", "", flips.lower())[:16] + hashlib.sha1(f"{donor} {flips}".encode()).hexdigest()[:6]
    bot = f"{pre}_{slug}"
    if not os.path.isdir(os.path.join(REPO, "bots", bot)):
        r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/flip.sh"), donor, bot, flips], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"eventfork: flip.sh failed: {(r.stdout + r.stderr)[-800:]}")
    return bot


def libs(a, donor, opp):
    """-> (base .so, opp .so, flip .so, flip bot, null .so or None). 11 Nov (Path Finding, first reads): --state "FOO_STATE=1" sets the
    bit's memory flags in BOTH arms (the base is DONOR + STATE), so the flipped ACT flag finds the state its flag-on game would have built
    since round 0; --null-flips "..." makes the null arm a real control (e.g. ACT on with its decision masked: the flip's fuel without
    its decision). Without --null-flips the null is the base itself, which replays the parent exactly: a sanity row that cannot fail."""
    state = opt(a, "--state")
    if state:
        donor = _flipped(donor, state, "nova_efs")
    flipbot = opt(a, "--flipbot")
    if not flipbot:
        flips = opt(a, "--flips")
        if not flips:
            sys.exit("eventfork: give --flips \"FLAG=V ...\" or --flipbot NAME")
        flipbot = _flipped(donor, flips, "nova_ef")
    elif state:
        print("eventfork: WARNING: --flipbot with --state: the flip bot must be built on the STATE base (it must carry the STATE flags too)")
    cxefork.check_flip(donor, flipbot)
    nullbot = _flipped(donor, opt(a, "--null-flips"), "nova_efn") if opt(a, "--null-flips") else None
    if nullbot:
        cxefork.check_flip(donor, nullbot)
    if not state:
        print("eventfork: WARNING: no --state. A flip gets its data bytes at the fork round but not the state its flag-on game builds from round 0 "
              "(memory written only under the flag): split the idea into FOO_STATE (both arms, play-identical to live) and FOO_ACT (flipped), "
              "or the read may not test the bit (Path Finding 11 Nov: RTF/HCN)")
    so = {}
    for b in [donor, opp, flipbot] + ([nullbot] if nullbot else []):
        so[b] = so.get(b) or cxebuild.build_bot(b)
    return so[donor], so[opp], so[flipbot], flipbot, (so[nullbot] if nullbot else None)


def farm(games, say):
    import cxefarm
    os.environ["CXEFARM"] = "1"
    return cxefarm.run(games, say=say, prio=PRIO, per=int(os.environ.get("EVENTFORK_PER", 12)), cpus=int(os.environ.get("EVENTFORK_CPUS", 8)))


def check0(a, donor, opp):
    base, oso, flip, flipbot, _nul = libs(a, donor, opp)
    mapdir = opt(a, "--mapdir", MAPDIR)
    n = int(opt(a, "--check0"))
    maps = random.Random(int(opt(a, "--seed", "1"))).sample(sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a")), n)
    out = opt(a, "--out") or os.path.join(cxebuild.ROOT, "eventfork", f"check0_{time.strftime('%m%d%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    games = []
    for i, m in enumerate(maps):
        seat = "AB"[i % 2]
        mp = os.path.join(mapdir, m)
        ab = lambda us: (us, oso) if seat == "A" else (oso, us)  # noqa: E731
        A, B = ab(base)
        games.append(dict(id=4 * i, a=A, b=B, map=mp, libs=[flip], args=["--fork-at", "0", "--alt-team", seat, "--alt", f"@SO:{flip}@"],
                          files={"g.alt0.repl26a": f"{out}/f0_{i}.repl26a"}))
        A2, B2 = ab(flip)
        games.append(dict(id=4 * i + 1, a=A2, b=B2, map=mp, files={"g.repl26a": f"{out}/sflip_{i}.repl26a"}))
        games.append(dict(id=4 * i + 2, a=A, b=B, map=mp, libs=[base], args=["--fork-at", "150", "--alt-team", seat, "--alt", f"@SO:{base}@"],
                          files={"g.alt0.repl26a": f"{out}/n150_{i}.repl26a", "g.repl26a": f"{out}/n150p_{i}.repl26a"}))
        games.append(dict(id=4 * i + 3, a=A, b=B, map=mp, files={"g.repl26a": f"{out}/sbase_{i}.repl26a"}))
    t0 = time.time()
    got = farm(games, print)
    sha = lambda p: hashlib.sha1(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None  # noqa: E731
    f0 = sum(1 for i in range(n) if sha(f"{out}/f0_{i}.repl26a") and sha(f"{out}/f0_{i}.repl26a") == sha(f"{out}/sflip_{i}.repl26a"))
    n1 = sum(1 for i in range(n) if sha(f"{out}/n150_{i}.repl26a") and sha(f"{out}/n150_{i}.repl26a") == sha(f"{out}/sbase_{i}.repl26a"))
    p1 = sum(1 for i in range(n) if sha(f"{out}/n150p_{i}.repl26a") and sha(f"{out}/n150p_{i}.repl26a") == sha(f"{out}/sbase_{i}.repl26a"))
    fd = sum(1 for i in range(n) if sha(f"{out}/sflip_{i}.repl26a") and sha(f"{out}/sflip_{i}.repl26a") != sha(f"{out}/sbase_{i}.repl26a"))
    print(f"eventfork check0 {donor} / {flipbot} v {opp}: {got} of {len(games)} games back in {time.time() - t0:.0f} s")
    print(f"  fork at 0 (alt flip) == straight flip game: {f0}/{n}\n  identity fork at 150 == straight base game: {n1}/{n}"
          f"\n  parent of that fork == straight base game: {p1}/{n}\n  (flip game differs from base game on {fd}/{n} maps)\n  files: {out}")
    return 0 if f0 == n1 == p1 == n else 1


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    donor, opp = a[0], a[1]
    if "--check0" in a:
        sys.exit(check0(a, donor, opp))
    src = opt(a, "--fire-from")
    if not src:
        sys.exit(__doc__)
    fires = fire_from_dg(src, opt(a, "--tag")) if os.path.isdir(src) else fire_from_tsv(src)
    if os.path.isdir(src) and not opt(a, "--tag"):
        sys.exit("eventfork: a dgkit dir needs --tag T")
    mapdir = opt(a, "--mapdir", MAPDIR)
    listed = {}
    if opt(a, "--maplist"):
        for ln in open(opt(a, "--maplist")):
            p = ln.strip().split()[-1] if ln.strip() else ""
            if p:
                listed[os.path.basename(p)[:-7] if p.endswith(".map26a") else os.path.basename(p)] = p
    paths = {}
    for f in fires:
        if f["map"] not in paths:
            paths[f["map"]] = map_path(f["map"], mapdir, listed)
    miss = sorted(m for m, p in paths.items() if not p)
    if miss:
        print(f"eventfork: {len(miss)} map(s) not found, their firings skipped: {' '.join(miss[:8])}")
    fires = [f for f in fires if paths.get(f["map"]) and f["seat"] in ("A", "B")]
    classify(fires, opt(a, "--class"), paths)
    seed = int(opt(a, "--seed", "1"))
    chosen, avail = choose(fires, a, random.Random(seed))
    ks = sorted(int(x) for x in opt(a, "--k", "30,100").split(","))
    K = ks[-1]
    half = halves([f["map"] for c in chosen.values() for f in c], seed)
    forks = [dict(f, cls=c) for c in sorted(chosen) for f in chosen[c]]
    print(f"eventfork: {len(fires)} firings in {len(avail)} class(es); forking {len(forks)}: "
          + ", ".join(f"{c} {len(chosen[c])}/{avail[c]}" for c in sorted(chosen)))
    if "--dry" in a:
        return
    base, oso, flip, flipbot, nul = libs(a, donor, opp)
    NULLREAL[0] = nul is not None
    nul = nul or base
    out = opt(a, "--out") or os.path.join(cxebuild.ROOT, "eventfork", f"{donor}_{time.strftime('%m%d%H%M%S')}")
    os.makedirs(os.path.join(out, "dec"), exist_ok=True)
    games = []
    for i, f in enumerate(forks):
        A, B = (base, oso) if f["seat"] == "A" else (oso, base)
        dd = os.path.join(out, "dec", f"f{i}")
        games.append(dict(id=i, a=A, b=B, map=paths[f["map"]], libs=sorted({flip, base, nul}), decode=["g", "g.alt0", "g.alt1"],
                          args=["--fork-at", str(f["round"]), "--fork-k", str(K), "--alt-team", f["seat"], "--alt", f"@SO:{flip}@", "--alt", f"@SO:{nul}@"],
                          files={"g.dec.json": f"{dd}.base.json", "g.alt0.dec.json": f"{dd}.flip.json", "g.alt1.dec.json": f"{dd}.null.json"}))
    with open(os.path.join(out, "manifest.txt"), "w") as mf:
        for g in games:
            mf.write(f"{g['a']} {g['b']} {g['map']} f{g['id']} " + " ".join(x.replace("@SO:", "").rstrip("@") for x in g["args"]) + "\n")
    t0 = time.time()
    got = farm(games, print)
    wall = time.time() - t0
    rows, res = [], collections.defaultdict(lambda: collections.defaultdict(list))
    nofork = 0
    for i, f in enumerate(forks):
        dd = os.path.join(out, "dec", f"f{i}")
        try:
            d = {b: json.load(open(f"{dd}.{b}.json")) for b in ("base", "flip", "null")}
        except (OSError, ValueError):
            nofork += 1
            continue
        R, us = f["round"], f["seat"]
        ch = changed_after(d["flip"], d["base"], R)
        nch = changed_after(d["null"], d["base"], R)
        vals = []
        for k in ks:
            vb, vf, vn = (v_at(d[b], R + k - 1, us) for b in ("base", "flip", "null"))
            if None in (vb, vf, vn):
                vals.append(None)
                continue
            vals.append((vf - vb, vn - vb))
            res[f["cls"]][(k, "F")].append(vf - vb)
            res[f["cls"]][(k, "N")].append(vn - vb)
            res[f["cls"]][(k, "F" + half[f["map"]])].append(vf - vb)
        res[f["cls"]]["chg"].append(ch)
        res[f["cls"]]["nchg"].append(nch)
        last = d["base"]["rounds"][-1][0] if d["base"]["rounds"] else -1
        rows.append("\t".join([f["map"], us, str(R), f["cls"], half[f["map"]], str(int(ch)), str(int(nch)), str(last)]
                              + [f"{x[0]:.1f}\t{x[1]:.1f}" if x else "\t" for x in vals]))
        if "--keep" not in a:
            for b in ("base", "flip", "null"):
                os.remove(f"{dd}.{b}.json")
    open(os.path.join(out, "forks.tsv"), "w").write("map\tseat\tround\tclass\thalf\tflip_changed\tnull_changed\tbase_last_round\t"
                                                     + "\t".join(f"dF{k}\tdN{k}" for k in ks) + "\n" + "\n".join(rows) + "\n")
    rep = [f"eventfork {flipbot} (flip of {donor}) v {opp}: {len(forks)} forks chosen, {len(rows)} read ({nofork} no fork / lost), "
           f"{wall:.0f} s on the pilots (prio {PRIO}, {got} of {len(games)} games back)",
           f"V = tributed + carried gems + .35 earned gold; dF = V(us-them) flip - base, dN = null - base, at round R+k-1. Halves split by map (seed {seed}).",
           (f"DROP RULES (pre-stated, per class at k={K}): null bias |mean dN| > {NULL_MAX:g} V (null = --null-flips control), or spread sd(dF) > {SPREAD_MAX:g} V per fork -> DROP."
            if NULLREAL[0] else f"DROP RULE (pre-stated, per class at k={K}): spread sd(dF) > {SPREAD_MAX:g} V per fork -> DROP. Null = identity (replays the parent "
            f"exactly: a plumbing check that cannot fail, not a control; give --null-flips for a fuel-matched control)."),
           "STATE: " + (f"--state {opt(sys.argv[1:], '--state')} set in both arms." if opt(sys.argv[1:], "--state") else
                        "none given: flag-gated memory the flip would have built since round 0 is ABSENT at the fork (see the docstring).")]
    for c in sorted(res):
        r = res[c]
        chg = r["chg"]
        rep.append(f"\n[{c}]  forks {len(chg)}; play changed after R: flip {sum(chg)}/{len(chg)}, null {sum(r['nchg'])}/{len(chg)}")
        for k in ks:
            rep.append(f"  k={k:3d}  flip  {fmt(stats(r[(k, 'F')]))}")
            rep.append(f"         half A {fmt(stats(r[(k, 'FA')]))}")
            rep.append(f"         half B {fmt(stats(r[(k, 'FB')]))}")
            rep.append(f"         null  {fmt(stats(r[(k, 'N')]))}")
        _, nm, _, _ = stats(r[(K, "N")])
        _, _, _, sd = stats(r[(K, "F")])
        drop = [x for x, bad in ((f"null bias {nm:+.1f}", NULLREAL[0] and abs(nm) > NULL_MAX), (f"spread {sd:.0f}", sd > SPREAD_MAX)) if bad]
        rep.append(f"  verdict: {'DROP (' + ', '.join(drop) + ')' if drop else 'usable (drop rules pass)'}")
    open(os.path.join(out, "report.txt"), "w").write("\n".join(rep) + "\n")
    print("\n".join(rep) + f"\nfiles: {out}/report.txt, {out}/forks.tsv")


if __name__ == "__main__":
    main()
