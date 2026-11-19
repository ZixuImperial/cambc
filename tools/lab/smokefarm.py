#!/usr/bin/env python3
"""smokefarm: a fast smoke test of many candidates at once v live, on the Condor pilots (sf1, 6 Nov; owner: "batch test games to speed
up the process for multiple bugs"; Builder: "why should 100 games take ~5 min").

usage: python3 -I tools/lab/smokefarm.py screen CAND [CAND ...] [--maps 50] [--weird 0.5] [--vs BOT] [--tag T] [--keep] [--json OUT]
       python3 -I tools/lab/smokefarm.py factorial BASE "F1=a" "F2=b G2=c" ... [--design hadamard|full|foldover] [same options]
  CAND   a bot under bots/, or BASE+"F=V G=W" (a data-only flip of BASE, made with flip.sh as a scratch copy nova_sf_<tag>_<k>;
         commas work as separators too). Each flip arm's cxe .so is built by cxebuild.build_bot: flip.sh's own predicted wasm is
         translated (w2c) and only its data part is compiled (the OBJ cache holds the 8 code parts): ~2.2 s an arm, measured 6 Nov,
         so flip arms never rebuild code and no .so patching is needed.
  factorial  each PART is one flip string; the runs are BASE + the parts that are on in each row of the design; per part the main
         effect (mean of the on-runs minus mean of the off-runs, paired by map, 95% CI over maps) on score, capped fuel and deaths.
         hadamard (default): Sylvester H(n) columns 1,2,4,3,5,6,7,... (n = 2 for 1 part, 4 for 2, 8 for 3-7, 16 for 8-15): a 2^(k-p)
         resolution-III design (3 parts in 8 runs = the full 2^3; 7 parts in 8 runs saturated: each main effect is aliased with
         two-part interactions). full: 2^k. foldover: flagscreen.design (resolution IV). Row 0 (every part off) is BASE itself.
         Parts that set one flag are OR'ed in a run (bits of one flag: RI_BITS=1 and RI_BITS=2 on together = RI_BITS=3).
Games: ONE fresh map set for everything (stratmaps.py --take --who smokefarm: never saved, half genweird; --maps N, --weird W), at the
  real 100k fuel budget, on the pilots (tools/cxe/pilotcxe.py; cxe = byte-identical to the CLI). Per map: live v live once (shared by
  every candidate) and every candidate v live in both seats, all in ONE pilot batch. Candidates with the same .so play once.
Table (one row per candidate, run dir /data/zw4424/st/smoke/<tag>/: table.txt, games.jsonl, maps.txt, rows.json):
  score    map-pair score v live [95% CI] (per map: both seats, draw = 1/2) and the maps whose games differ from live v live
           (replay hashes; an inert flip reads 0)
  faults   the candidate side's bot faults (live v live's own in the header)
  fuel     capped fuel cut-offs v live as in shipcheck.py fuel_paired: each side's exhaustions per game capped at 5 (SMOKE_FUEL_CAP), the
           candidate side v the live side of the same games, paired by map: ratio CAND/LIVE and z
  deaths   the candidate's champion deaths per game v live's in the shared live v live games on the same maps (paired by map, z)
  DISASTER score < .40, or fuel ratio > 1.5x (and +5 capped and paired z >= 2, SMOKE_FZ), or faults > 0, or deaths >= +0.3/g at z >= 2 (env SMOKE_SCORE, SMOKE_FUELX,
           SMOKE_DEATHS, SMOKE_DZ). The exit code is 0 when the table was made (3 when any row is a DISASTER), 1 when it could not be made.
Rare change (7 Nov, owner): screen CAND --changed N [--max-probe 40000] [--wfams w_a,w_b]: one flip of --vs. Instead of --maps, tools/lab/changedprobe.py draws fresh maps until N of them
  have different games in the two seats (identical replays read exactly .500 and are dropped); the table is on those maps, and below it the changed share, unchanged count, targeted share
  and implied whole-pool effect. 2 games a map to find them: at a 2% change N = 100 is about 10,000 games.
Staged screen (7 Nov): a screen of >= 2 x SMOKE_STAGE (300) maps plays 300 maps at a time; after each stage an arm stops when it is a
  DISASTER, inert (no game changed), or its score's upper bound (mean + 1.96 se, SMOKE_STAGE_Z) is under .5025 (SMOKE_STAGE_PT; simulation 7 Nov: <= 4.9% of real +.5% arms stop early); the
  rest play on to the full --maps. Its row then reads on the maps it played (n), and the table lists who stopped and why. Arms that
  look good cost the same; a losing arm costs about a quarter. SMOKE_STAGE=0 plays one batch as before. factorial never stages.
Other options: --keep keeps replays (g/<n>.repl26a; deaths.py / replay.py read them) and the scratch flips; without it both go at the end
  (rmdata.sh). --json OUT writes the rows as JSON (armq's smoke hook reads it). --mapdir DIR plays the maps already in DIR (no new set).
  The pilots only (never a local cxe batch: RULE OFFLOAD); if the pilots cannot play the batch the run stops with exit 1.
       python3 -I tools/lab/smokefarm.py identity BASE+"F=V" ... [--maps 10]   each flip's patched .so v its cxebuild-built .so, both
         v live in both seats: replay, statistics and per-turn fuel byte-identical (6 Nov: 60/60 pairs on 3 flips, one with 2 flags)
       python3 -I tools/lab/smokefarm.py clean TAG     remove a killed run's scratch flips
.so of a flip arm (SMOKE_SO=patch, default): flip.sh's predicted wasm differs from the trunk wasm in flag-table bytes only, and w2c writes
  data segments verbatim, so the trunk's cached .so is copied with those bytes replaced (found by +-12 bytes of context, exactly once):
  ~0.2 s an arm, no w2c, no clang, no build slot (a cxebuild build of a flip is ~2.3 s alone, but waited 39-127 s for build slots under
  load on 6 Nov). The patched and the built .so differ only in the build-id note and the data part's file name in .strtab. Any arm the
  patch cannot place is built by cxebuild as before. SMOKE_SO=build builds every arm.
Speed (6 Nov, 50 maps, cxe games on the pilots, 8 games an item = one game per item cpu, SMOKE_PER): 3 flips 350 games 62 s wall; 8 flips
  850 games 103 s (maps 0, builds 4, games 99, read 0; 20 pilots alive); the games are the pilots' queue (shared), not this machine.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
SMOKE_X = (" " + os.environ["SMOKEFARM_ARGS"]) if os.environ.get("SMOKEFARM_ARGS") else ""  # b1370: extra cxe args for screen games, e.g. --fuel 1000000000 (the header's "100k fuel" then does not apply)

REPO = "/homes/zw4424/cambc"
LAB = os.path.join(REPO, "tools/lab")
CXE = os.path.join(REPO, "tools/cxe")
Q = "/data/zw4424/st/bq"
ROOT = "/data/zw4424/st/smoke"
sys.path.insert(0, LAB)
sys.path.insert(0, CXE)

FUEL_CAP = int(os.environ.get("SMOKE_FUEL_CAP", "5"))
BAR_SCORE = float(os.environ.get("SMOKE_SCORE", "0.40"))
BAR_FUELX = float(os.environ.get("SMOKE_FUELX", "1.5"))
BAR_DEATHS = float(os.environ.get("SMOKE_DEATHS", "0.3"))
BAR_DZ = float(os.environ.get("SMOKE_DZ", "2.0"))
BAR_FZ = float(os.environ.get("SMOKE_FZ", "2.0"))
# staged screen (7 Nov, owner: "speed them up"; 2,100 pilot items queued on 13 daytime pilots, screens of 4 arms x 2,000 maps):
# a screen of >= 2 x SMOKE_STAGE maps plays SMOKE_STAGE maps at a time and stops an arm after a stage when it is a DISASTER, inert
# (no game changed), or its score's upper bound (mean + SMOKE_STAGE_Z se) is under SMOKE_STAGE_PT. SMOKE_STAGE=0: one batch as before.
STAGE = int(os.environ.get("SMOKE_STAGE", "300"))  # 7 Nov: 500 -> 300, z 2.58 -> 1.96, pt .50 -> .5025 (simulated on 1,767 real arms: early stops of +.5% arms <= 4.9%, losing arms ~450 maps fewer at 2,000)
STAGE_Z = float(os.environ.get("SMOKE_STAGE_Z", "1.96"))
STAGE_PT = float(os.environ.get("SMOKE_STAGE_PT", "0.5025"))  # the score line only; DISASTER (fuel, deaths, faults) keeps its own rules
T0 = time.time()
LOG = []


def say(s):
    line = f"{time.strftime('%H:%M:%S', time.gmtime())} {s}"
    print(line, flush=True)
    LOG.append(line)


def live():
    return open(os.path.join(Q, "live.txt")).readline().split()[1]


def parse_cand(c):
    """'BOT' -> (BOT, None); 'BASE+F=V G=W' -> (BASE, 'F=V G=W')"""
    if "+" in c:
        b, f = c.split("+", 1)
        f = " ".join(x for x in re.split(r"[\s,]+", f.strip()) if x)
        if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=-?(0[xX][0-9a-fA-F]+|\d+)", x) for x in f.split()):
            sys.exit(f"smokefarm: bad flips in {c!r} (want F=INT ...)")
        return b.strip(), f
    return c.strip(), None


def make_flip(base, flips, name):
    r = subprocess.run(["sh", os.path.join(LAB, "flip.sh"), base, name, flips], capture_output=True, text=True, cwd=REPO)
    if r.returncode:
        raise RuntimeError(f"flip.sh {base} {name} [{flips}]: {(r.stdout + r.stderr).strip()[-300:]}")
    return name


SODIR = os.path.join(ROOT, "so")
SO_MODE = os.environ.get("SMOKE_SO", "patch")  # patch: a flip arm's .so = the trunk's .so with the flip's data bytes patched; build: cxebuild


def flipinfo(bot):
    try:
        return dict(ln.split("=", 1) for ln in open(os.path.join(REPO, "bots", bot, "FLIP")).read().splitlines() if "=" in ln)
    except OSError:
        return {}


def patch_so(bot):
    """A flip arm's cxe library without translating or compiling: w2c writes each wasm data segment verbatim as a uint8 array
    (w2c.py: 'static const uint8_t dataN[] = {...}'), so the trunk's .so holds every flag table byte for byte. Each run of bytes the
    flip changed in the wasm (flip.sh's predicted wasm v the trunk wasm it patched) is found in the trunk's .so by its context (+-12
    bytes, exactly once) and replaced. -> the patched .so path, or None (the caller builds as usual)."""
    import cxebuild
    fi = flipinfo(bot)
    tw = f"/data/zw4424/trunkproj/wasm/{fi.get('TRUNK')}-{fi.get('TRUNK_HASH')}.wasm"
    aw = fi.get("WASM", "")
    if not (os.path.exists(tw) and os.path.exists(aw)) or cxebuild.flip_wasm(os.path.join(REPO, "bots", bot)) != aw:
        return None
    a, b = open(tw, "rb").read(), open(aw, "rb").read()
    if len(a) != len(b):
        return None
    out = os.path.join(SODIR, hashlib.sha256(b).hexdigest()[:16] + ".so")
    if os.path.exists(out):
        return out
    base_so = cxebuild.build_bot(fi["TRUNK"], wasm=tw)  # cached by the wasm's hash: the trunk (or live) library already built
    so = bytearray(open(base_so, "rb").read())
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if not diff:
        return base_so
    C = 12
    runs, s = [], diff[0]
    for p, q in zip(diff, diff[1:] + [None]):
        if q is None or q - p > 2 * C:  # contexts never overlap (6 Nov: two flags of one table, 14 bytes apart, fell back to a build)
            runs.append((s, p + 1))
            s = q
    orig, put = bytes(so), []
    for i, j in runs:  # every context is found in the unpatched library first
        ctx, new = a[max(0, i - C):j + C], b[max(0, i - C):j + C]
        at = orig.find(ctx)
        if at < 0 or orig.find(ctx, at + 1) >= 0:
            return None
        put.append((at, new))
    for at, new in put:
        so[at:at + len(new)] = new
    os.makedirs(SODIR, exist_ok=True)
    for f in os.listdir(SODIR):  # patched libraries are 2 s to remake: 2 days, as cxebuild's object cache
        try:
            if time.time() - os.path.getmtime(os.path.join(SODIR, f)) > 2 * 86400:
                os.remove(os.path.join(SODIR, f))
        except OSError:
            pass
    tmp = f"{out}.{os.getpid()}.tmp"
    open(tmp, "wb").write(so)
    os.chmod(tmp, 0o755)
    os.replace(tmp, out)
    return out


def build_all(specs, tag):
    """specs: [(label, base, flips|None)] -> {label: (bot, so)}; flips go to scratch copies made by flip.sh, in parallel."""
    import cxebuild
    made = []

    def one(k_spec):
        k, (label, base, flips) = k_spec
        if not os.path.isdir(os.path.join(REPO, "bots", base, "src")):
            raise RuntimeError(f"no bot {base}")
        bot, t = base, time.time()
        if flips:
            bot = make_flip(base, flips, f"nova_sf_{tag}_{k}")
            made.append(bot)
        tf = time.time() - t
        so = patch_so(bot) if flips and SO_MODE == "patch" else None
        how = "patched" if so else "built"
        so = so or cxebuild.build_bot(bot)
        say(f"  {label[:60]}: flip {tf:.1f} s, .so {how} {time.time() - t - tf:.1f} s")
        return label, bot, so
    out, errs = {}, []
    with ThreadPoolExecutor(int(os.environ.get("SMOKE_BUILD_PAR", "8"))) as ex:
        for fut in [ex.submit(one, ks) for ks in enumerate(specs, 1)]:
            try:
                label, bot, so = fut.result()
                out[label] = (bot, so)
            except (Exception, SystemExit) as e:  # noqa: BLE001  a broken arm is reported, the others still play
                errs.append(str(e)[-300:])
    return out, errs, made


def mapset(run, n, weird, mapdir):
    if mapdir:
        ms = sorted(os.path.join(mapdir, f) for f in os.listdir(mapdir) if f.endswith(".map26a"))
        return ms[:n] if n else ms
    d = os.path.join(run, "maps")
    r = subprocess.run([sys.executable, "-I", os.path.join(LAB, "stratmaps.py"), d, "--n", str(n), "--take", "--who", "smokefarm",
                        "--weird", str(weird), "--light"], capture_output=True, text=True)
    ms = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".map26a")) if os.path.isdir(d) else []
    if not ms:
        sys.exit(f"smokefarm: no maps ({(r.stdout + r.stderr).strip()[-300:]})")
    return ms


def side(d, team):
    """deaths, capped/raw fuel exhaustions and faults of one team in a cxe statistics JSON (ablsum.py side_metrics' fields)"""
    deaths = sum(int(float(c["metrics"].get("deaths", 0))) for c in d["champions"] if c["team"] == team)
    fuel = sum(len(e["entries"]) for e in d["events"] if e["kind"] == "fuelExhausted" and e["owner"].get("team") == team)
    faults = int(d.get("diagnostics", {}).get("botFaults", {}).get(team, 0))
    return dict(deaths=deaths, fuel=fuel, faults=faults)


def read_game(out):
    try:
        d = json.load(open(out + ".json"))
    except (OSError, ValueError):
        return None
    oc = d["match"].get("outcome")
    h = None
    try:
        h = hashlib.sha1(open(out + ".repl26a", "rb").read()).hexdigest()[:16]
    except OSError:
        pass
    gm = {x.get("team"): int(x.get("submittedGems", 0)) for x in d.get("teams", [])}  # margin study (tools/lab/margin.py, 7 Nov)
    return dict(win="A" if oc == "teamA" else ("B" if oc == "teamB" else "D"), rounds=int(d["match"].get("roundsCompleted", 0)),
                sa=side(d, "teamA"), sb=side(d, "teamB"), h=h, ga=gm.get("teamA", 0), gb=gm.get("teamB", 0))


def mean_se(xs):
    n = len(xs)
    if not n:
        return 0.0, 0.0
    mu = sum(xs) / n
    return mu, (math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1) / n) if n > 1 else 0.0)


def play(run, maps, sos, lv_so, keep):
    """sos: {label: so}. Plays live v live once per map and every distinct so v live in both seats, ONE pilot batch.
    -> (per[label][map] = dict(score, fc, fl, dc, faults, games, changed), lvl[map] = game, n_missing) or None when the pilots fail."""
    import pilotcxe
    g = os.path.join(run, "g")
    os.makedirs(g, exist_ok=True)
    uniq = list(dict.fromkeys(s for s in sos.values() if s != lv_so))
    games, idx = [], {}
    for mi, mp in enumerate(maps):
        idx[("L", mi)] = len(games)
        games.append((lv_so, lv_so, mp, f"{g}/{len(games)}", "--statistics @STATS@" + SMOKE_X))
        for s in uniq:
            for seat in "AB":
                idx[(s, mi, seat)] = len(games)
                a, b = (s, lv_so) if seat == "A" else (lv_so, s)
                games.append((a, b, mp, f"{g}/{len(games)}", "--statistics @STATS@" + SMOKE_X))
    os.environ.setdefault("PILOTCXE_PRIO", "9")  # a screen: behind ship legs and reads (6 Nov)
    os.environ.setdefault("PILOTCXE_PER", os.environ.get("SMOKE_PER", "8"))  # one game per item cpu, one wave: 850 games back in 95 s on 20 pilots (20 an item: 650 in 137 s)
    say(f"games: {len(games)} ({len(maps)} maps: live v live once + {len(uniq)} distinct candidate(s) x 2 seats) on the pilots")
    t = time.time()
    if not pilotcxe.run(games, say=lambda m: say(m)):
        say("the pilots did not play the batch (pilotd down, or games missing): no table")
        return None
    say(f"games back in {time.time() - t:.0f} s")
    res = [read_game(x[3]) for x in games]
    with open(os.path.join(run, "games.jsonl"), "w") as f:
        for x, r in zip(games, res):
            f.write(json.dumps(dict(a=x[0], b=x[1], map=os.path.basename(x[2]), out=x[3], r=r)) + "\n")
    miss = sum(r is None for r in res)
    lvl = {mi: res[idx[("L", mi)]] for mi in range(len(maps))}
    per = {}
    for label, s in sos.items():
        pm = {}
        for mi in range(len(maps)):
            if s == lv_so:
                ga = gb = lvl[mi]
                if ga is None:
                    continue
                # live itself as a candidate (same .so): its games are the live v live game, by definition 1/2 and no change
                f2 = min(ga["sa"]["fuel"], FUEL_CAP) + min(ga["sb"]["fuel"], FUEL_CAP)
                dl = (ga["sa"]["deaths"] + ga["sb"]["deaths"]) / 2
                pm[mi] = dict(score=0.5, fc=f2, fl=f2, dc=dl, dl=dl, faults=ga["sa"]["faults"] + ga["sb"]["faults"], changed=0)
                continue
            ga, gb, gl = res[idx[(s, mi, "A")]], res[idx[(s, mi, "B")]], lvl[mi]
            if ga is None or gb is None or gl is None:
                continue
            sc = ({"A": 1, "B": 0, "D": 0.5}[ga["win"]] + {"B": 1, "A": 0, "D": 0.5}[gb["win"]]) / 2
            pm[mi] = dict(score=sc,
                          fc=min(ga["sa"]["fuel"], FUEL_CAP) + min(gb["sb"]["fuel"], FUEL_CAP),   # candidate side, 2 games
                          fl=min(ga["sb"]["fuel"], FUEL_CAP) + min(gb["sa"]["fuel"], FUEL_CAP),   # live side of the same games
                          fraw=ga["sa"]["fuel"] + gb["sb"]["fuel"], lraw=ga["sb"]["fuel"] + gb["sa"]["fuel"],
                          dc=(ga["sa"]["deaths"] + gb["sb"]["deaths"]) / 2,                       # candidate deaths / game
                          dl=(gl["sa"]["deaths"] + gl["sb"]["deaths"]) / 2,                       # live's deaths / game, live v live
                          faults=ga["sa"]["faults"] + gb["sb"]["faults"],
                          changed=int(ga["h"] != gl["h"] or gb["h"] != gl["h"]))
        per[label] = pm
    if not keep:  # games.jsonl holds what was read; the per-game files and the (never saved) maps go
        shutil.rmtree(g, ignore_errors=True)
        shutil.rmtree(os.path.join(run, "maps"), ignore_errors=True)
    return per, lvl, miss


def play_staged(run, maps, sos, lv_so, keep):
    """play() in stages of STAGE maps; arms that read clearly worse than the bar, inert or DISASTER stop after a stage.
    -> (per, lvl, n_missing, stops {label: (maps read, why)}) or None when the pilots fail the first stage"""
    chunks = [maps[i:i + STAGE] for i in range(0, len(maps), STAGE)]
    if len(chunks) > 1 and len(chunks[-1]) < STAGE // 2:
        last = chunks.pop()  # 8 Nov (b1661): `chunks[-2] += chunks.pop()` assigned to the NEW -2: one 300-map chunk lost, the last played twice
        chunks[-1] = chunks[-1] + last
    per, lvl, miss, stops, active, off = {lb: {} for lb in sos}, {}, 0, {}, dict(sos), 0
    with open(os.path.join(run, "games.jsonl"), "w") as gj:
        for k, ch in enumerate(chunks):
            sub = os.path.join(run, f"stage{k}")
            os.makedirs(sub, exist_ok=True)
            say(f"stage {k + 1}/{len(chunks)}: {len(ch)} maps, {sum(1 for s in active.values() if s != lv_so)} arm(s) playing")
            got = play(sub, ch, active, lv_so, keep)
            if got is None:
                if k == 0:
                    return None
                say(f"stage {k + 1}: the pilots did not play it; the table is on the {off} maps of the earlier stages")
                break
            p, l, m = got
            miss += m
            for lb, pm in p.items():
                per[lb].update({off + mi: v for mi, v in pm.items()})
            lvl.update({off + mi: g for mi, g in l.items()})
            off += len(ch)
            try:
                gj.write(open(os.path.join(sub, "games.jsonl")).read())
            except OSError:
                pass
            if k == len(chunks) - 1:
                break
            for lb in list(active):
                if active[lb] == lv_so:
                    continue
                r = row(lb, per[lb], None)
                if not r["n"]:
                    continue
                up = r["score"] + STAGE_Z * (r["hi"] - r["score"]) / 1.96
                why = (r["why"] if r["disaster"] else "inert: no game changed" if not r["changed"]
                       else f"score {r['score']:.4f}, upper bound {up:.4f} < {STAGE_PT:g}" if up < STAGE_PT else "")
                if why:
                    stops[lb] = (r["n"], why)
                    del active[lb]
                    say(f"stopped {lb} after {r['n']} maps: {why}")
            if not any(s != lv_so for s in active.values()):
                say("every arm stopped: no further stage")
                break
    if not keep:
        shutil.rmtree(os.path.join(run, "maps"), ignore_errors=True)
    return per, lvl, miss, stops


def row(label, pm, bot):
    ms = sorted(pm)
    n = len(ms)
    if not n:
        return dict(label=label, bot=bot, n=0, disaster=True, why="no games")
    mu, se = mean_se([pm[m]["score"] for m in ms])
    fc, fl = sum(pm[m]["fc"] for m in ms), sum(pm[m]["fl"] for m in ms)
    fd_mu, fd_se = mean_se([pm[m]["fc"] - pm[m]["fl"] for m in ms])
    dd = [pm[m]["dc"] - pm[m].get("dl", pm[m]["dc"]) for m in ms]
    d_mu, d_se = mean_se(dd)
    r = dict(label=label, bot=bot, n=n, score=mu, lo=mu - 1.96 * se, hi=mu + 1.96 * se, changed=sum(pm[m]["changed"] for m in ms),
             faults=sum(pm[m]["faults"] for m in ms), fuel_c=fc, fuel_l=fl, fuel_ratio=fc / max(1, fl),
             fuel_z=(fd_mu / fd_se) if fd_se > 0 else 0.0, deaths_c=sum(pm[m]["dc"] for m in ms) / n,
             deaths_l=sum(pm[m].get("dl", pm[m]["dc"]) for m in ms) / n, deaths_d=d_mu, deaths_z=(d_mu / d_se) if d_se > 0 else 0.0)
    why = []
    if r["score"] < BAR_SCORE:
        why.append(f"score {r['score']:.3f} < {BAR_SCORE:g}")
    if r["fuel_ratio"] > BAR_FUELX and fc - fl >= 5 and r["fuel_z"] >= BAR_FZ:
        why.append(f"fuel {r['fuel_ratio']:.2f}x > {BAR_FUELX:g}x")
    if r["faults"] > 0:
        why.append(f"{r['faults']} faults")
    if r["deaths_d"] >= BAR_DEATHS and r["deaths_z"] >= BAR_DZ:
        why.append(f"deaths {r['deaths_d']:+.2f}/g z {r['deaths_z']:+.1f}")
    r["disaster"], r["why"] = bool(why), "; ".join(why)
    return r


def fmt(r):
    if not r["n"]:
        return f"  {r['label'][:46]:46s} no games  DISASTER ({r['why']})"
    return (f"  {r['label'][:46]:46s} {r['n']:3d} {r['score']:.3f} [{r['lo']:.3f}, {r['hi']:.3f}] {r['changed']:3d}  {r['faults']:3d}  "
            f"{r['fuel_c']:4d} v {r['fuel_l']:4d} {r['fuel_ratio']:5.2f}x z{r['fuel_z']:+5.1f}  "
            f"{r['deaths_c']:.2f} v {r['deaths_l']:.2f} {r['deaths_d']:+.2f} z{r['deaths_z']:+5.1f}  "
            + (f"DISASTER ({r['why']})" if r["disaster"] else "ok"))


HEAD = (f"  {'candidate':46s} {'n':>3s} {'score [95% CI]':21s} {'chg':>3s}  {'flt':>3s}  {'cap5 fuel C v L ratio z':27s} "
        f"{'deaths/g C v L  d  z':24s}  verdict")


def args_common(a):
    def opt(k, d):
        if k in a:
            i = a.index(k)
            v = a[i + 1]
            del a[i:i + 2]
            return v
        return d
    o = dict(maps=int(opt("--maps", 50)), weird=float(opt("--weird", 0.5)), vs=opt("--vs", None), tag=opt("--tag", None),
             json=opt("--json", None), mapdir=opt("--mapdir", None), design=opt("--design", "hadamard"), changed=int(opt("--changed", 0)), max_probe=int(opt("--max-probe", 40000)),
             wfams=opt("--wfams", None))
    o["keep"] = "--keep" in a
    while "--keep" in a:
        a.remove("--keep")
    o["vs"] = o["vs"] or live()
    o["tag"] = o["tag"] or time.strftime("%m%d%H%M%S", time.gmtime())
    if not re.fullmatch(r"[a-z0-9]+", o["tag"]):
        sys.exit("smokefarm: --tag must be [a-z0-9]+")
    return o


def cleanup(made, run, keep):
    if keep or not made:
        return
    lst = os.path.join(run, "rm.txt")
    paths = []
    for b in made:
        link = os.path.join(REPO, "bots", b)
        real = os.path.realpath(link)
        paths += [real, link] if os.path.islink(link) else [real]
        paths += [p for p in (os.path.join("/data/zw4424/trunkproj/wasm", f) for f in os.listdir("/data/zw4424/trunkproj/wasm")
                              if f.startswith(b + "-")) if os.path.isfile(p)]
    open(lst, "w").write("\n".join(paths) + "\n")
    r = subprocess.run(["sh", os.path.join(LAB, "rmdata.sh"), lst], capture_output=True, text=True)
    say(f"scratch removed ({len(made)} flip copies)" if r.returncode == 0 else f"scratch NOT removed: {(r.stdout + r.stderr)[-200:]}")


def run_set(specs, o, title, staged=False):
    """specs [(label, base, flips|None)] -> (rows, per, run) ; the shared pipeline of screen and factorial."""
    run = os.path.join(ROOT, o["tag"])
    if os.path.exists(run):
        sys.exit(f"smokefarm: {run} exists (pick another --tag)")
    os.makedirs(run)
    say(f"{title}: {len(specs)} candidate(s) v {o['vs']}, run dir {run}")
    import readslots  # 7 Nov: at most bq/bigread_max big reads (> 600 maps, or a changed probe) at once across agents; the rest wait in order
    run_set.slot = readslots.acquire(o["tag"], o["changed"] or o["maps"], f"smokefarm {title}", say, changed=bool(o["changed"]))
    import cxebuild
    t = time.time()
    chg = []
    if o["changed"]:
        import changedprobe
        built, errs, made = build_all(specs, o["tag"])
        tb = time.time() - t
        if not built:
            sys.exit(f"smokefarm: build failed: {errs}")
        cdir = os.path.join(run, "changed")
        cs = changedprobe.build(next(iter(built.values()))[0], o["vs"], cdir, o["changed"], o["tag"], max_probe=o["max_probe"], wfams=o["wfams"], log=say)
        chg = changedprobe.report(cs)
        print("\n".join(chg), flush=True)
        maps = mapset(run, 0, 0, cdir) if cs["kept"] and not cs.get("not_rare") else []
        tm = time.time() - t
        if not maps:
            cleanup(made, run, o["keep"])
            return None, None, run
    else:
      with ThreadPoolExecutor(2) as ex:  # the map set and the builds at once
        fm = ex.submit(mapset, run, o["maps"], o["weird"], o["mapdir"])
        fb = ex.submit(build_all, specs, o["tag"])
        tm = None
        maps = fm.result()
        tm = time.time() - t
        built, errs, made = fb.result()
        tb = time.time() - t
    lv_so = cxebuild.build_bot(o["vs"])
    say(f"maps: {len(maps)} in {tm:.0f} s; builds: {len(built)} of {len(specs)} in {tb:.0f} s (from the start, parallel to the maps)")
    for e in errs:
        say(f"BUILD FAILED: {e}")
    open(os.path.join(run, "maps.txt"), "w").write("\n".join(maps) + "\n")
    t = time.time()
    sos = {lb: so for lb, (_, so) in built.items()}
    stops = {}
    if staged and STAGE > 0 and len(maps) >= 2 * STAGE:
        got = play_staged(run, maps, sos, lv_so, o["keep"])
        if got is not None:
            got, stops = got[:3], got[3]
    else:
        got = play(run, maps, sos, lv_so, o["keep"])
    tg = time.time() - t
    if got is None:
        cleanup(made, run, o["keep"])
        return None, None, run
    per, lvl, miss = got
    t = time.time()
    rows = [row(lb, per[lb], built[lb][0]) for lb, _, _ in specs if lb in built]
    rows += [dict(label=lb, bot=None, n=0, disaster=True, why="build failed") for lb, _, _ in specs if lb not in built]
    lf = sum(g["sa"]["faults"] + g["sb"]["faults"] for g in lvl.values() if g)
    lfu = sum(min(g["sa"]["fuel"], FUEL_CAP) + min(g["sb"]["fuel"], FUEL_CAP) for g in lvl.values() if g)
    tr = time.time() - t
    split = f"wall {time.time() - T0:.0f} s: maps {tm:.0f} s | builds {tb:.0f} s (parallel to maps) | games {tg:.0f} s | read {tr:.1f} s"
    hdr = [f"# smokefarm {title} {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: v {o['vs']}, {len(maps)} fresh maps x 2 seats, "
           f"{('fuel args:' + SMOKE_X) if '--fuel' in SMOKE_X else '100k fuel'}, cxe on the pilots; {miss} games missing",
           f"# live v live (shared, {len(lvl)} games): faults {lf}, cap{FUEL_CAP} fuel {lfu} (both sides)",
           f"# DISASTER: score < {BAR_SCORE:g}, fuel > {BAR_FUELX:g}x (+5, z >= {BAR_FZ:g}), faults > 0, deaths >= +{BAR_DEATHS:g}/g at z >= {BAR_DZ:g}",
           f"# {split}", HEAD]
    for r in rows:
        if r["label"] in stops:
            r["stopped"] = stops[r["label"]][1]
    stp = ([f"# staged ({STAGE} maps a stage; stop: DISASTER, inert, or upper bound mean + {STAGE_Z:g} se < {STAGE_PT:g}; SMOKE_STAGE=0 turns it off):"]
           + [f"#   {lb[:46]} stopped after {n} maps: {w}" for lb, (n, w) in stops.items()] if stops else [])
    txt = "\n".join(hdr + [fmt(r) for r in rows] + stp + chg)
    open(os.path.join(run, "table.txt"), "w").write(txt + "\n")
    json.dump(rows, open(os.path.join(run, "rows.json"), "w"), indent=1)
    if o["json"]:
        json.dump(dict(rows=rows, run=run, split=split), open(o["json"], "w"), indent=1)
    print(txt, flush=True)
    cleanup(made, run, o["keep"])
    return rows, per, run


def screen(a):
    o = args_common(a)
    if not a:
        sys.exit(__doc__)
    if o["changed"] and len(a) > 1:
        sys.exit("smokefarm: --changed reads one candidate (each has its own changed maps)")
    specs = []
    for c in a:
        b, f = parse_cand(c)
        specs.append((c, b, f))
    rows, _, run = run_set(specs, o, "screen", staged=True)
    if rows is None:
        return 1
    return 3 if any(r["disaster"] for r in rows) else 0


def sylvester(n):
    """H(n)[i][j] parity: row i, column j -> popcount(i & j) odd"""
    return [[bin(i & j).count("1") & 1 for j in range(n)] for i in range(n)]


def design_rows(k, kind, tag):
    """0/1 rows (1 = part on); row 0 = every part off (BASE)."""
    if kind == "full":
        return [[(r >> i) & 1 for i in range(k)] for r in range(2 ** k)]
    if kind == "foldover":
        import flagscreen
        rs = flagscreen.design(k, tag)
        off = [0] * k
        return [off] + [r for r in rs if r != off]
    if kind != "hadamard":
        sys.exit(f"smokefarm: --design {kind}? (hadamard|full|foldover)")
    n = 2 if k <= 1 else 4 if k <= 2 else 8 if k <= 7 else 16
    if k > 15:
        sys.exit("smokefarm: at most 15 parts")
    pw = [1 << i for i in range(4) if (1 << i) < n]
    cols = pw + [j for j in range(1, n) if j not in pw]  # main factors first: 3 parts in 8 runs = the full 2^3
    H = sylvester(n)
    return [[H[i][c] for c in cols[:k]] for i in range(n)]


def merge_parts(ps):
    """Parts that are on -> one flip string; two parts setting one flag (RI_BITS=1, RI_BITS=2: bits of one flag) are OR'ed."""
    v = {}
    for p in ps:
        for kv in re.split(r"[\s,]+", p.strip()):
            k, x = kv.split("=")
            v[k] = (v[k] | int(x, 0)) if k in v else int(x, 0)
    return " ".join(f"{k}={x}" for k, x in v.items())


def factorial(a):
    o = args_common(a)
    if len(a) < 2:
        sys.exit(__doc__)
    base, parts = a[0], a[1:]
    for p in parts:
        parse_cand(base + "+" + p)
    k = len(parts)
    D = design_rows(k, o["design"], o["tag"])
    specs, labels = [], []
    for r in D:
        fl = merge_parts([p for p, on in zip(parts, r) if on])
        lb = f"r{''.join(map(str, r))}"
        labels.append(lb)
        specs.append((lb, base, fl or None))
    say(f"factorial: {k} part(s), {len(D)} runs ({o['design']}); runs: " + "; ".join(f"{lb}=[{s[2] or 'BASE'}]" for lb, s in zip(labels, specs)))
    rows, per, run = run_set(specs, o, f"factorial {base}")
    if rows is None:
        return 1
    L = [f"# main effects ({o['design']}, {len(D)} runs; resolution III when k > log2(runs): a main effect is aliased with two-part "
         "interactions): mean(on) - mean(off), paired by map [95% CI over maps]",
         f"  {'part':28s} {'score':24s} {'cap5 fuel / map (2 games)':30s} {'deaths / game':24s}"]
    ok = [lb for lb in labels if lb in per]
    common = set.intersection(*[set(per[lb]) for lb in ok]) if ok else set()
    effs = []
    for j, p in enumerate(parts):
        on = [lb for lb, r in zip(labels, D) if r[j] and lb in per]
        off = [lb for lb, r in zip(labels, D) if not r[j] and lb in per]
        e = {}
        for met in ("score", "fc", "dc"):
            xs = [sum(per[lb][m][met] for lb in on) / len(on) - sum(per[lb][m][met] for lb in off) / len(off)
                  for m in sorted(common)] if on and off else []
            mu, se = mean_se(xs)
            e[met] = (mu, mu - 1.96 * se, mu + 1.96 * se)
        effs.append(dict(part=p, **{k_: list(v) for k_, v in e.items()}))
        L.append(f"  {p[:28]:28s} " + "  ".join(f"{e[m][0]:+.3f} [{e[m][1]:+.3f}, {e[m][2]:+.3f}]".ljust(28) for m in ("score", "fc", "dc")))
    txt = "\n".join(L)
    with open(os.path.join(run, "table.txt"), "a") as f:
        f.write(txt + "\n")
    json.dump(effs, open(os.path.join(run, "effects.json"), "w"), indent=1)
    print(txt, flush=True)
    return 3 if any(r["disaster"] for r in rows) else 0


def identity(a):
    """identity CAND ... [--maps 10]: each flip's patched .so v its cxebuild-built .so, both v live on the same maps in both seats
    (one pilot batch): every replay and statistics file must be byte-identical. The proof behind SMOKE_SO=patch."""
    import cxebuild
    import pilotcxe
    o = args_common(a)
    run = os.path.join(ROOT, o["tag"])
    os.makedirs(run)
    maps = mapset(run, o["maps"], o["weird"], o["mapdir"])
    lv = cxebuild.build_bot(o["vs"])
    games, pairs, made = [], [], []
    for k, c in enumerate(a, 1):
        b, f = parse_cand(c)
        bot = make_flip(b, f, f"nova_sf_{o['tag']}_{k}")
        made.append(bot)
        ps, bs = patch_so(bot), cxebuild.build_bot(bot)
        if not ps:
            say(f"{c}: no patched .so (context not unique or no FLIP wasm)")
            continue
        say(f"{c}: patched {ps} v built {bs} (.so bytes differ only in build-id and the data part's file name: "
            f"{sum(x != y for x, y in zip(open(ps, 'rb').read(), open(bs, 'rb').read()))} bytes)")
        for mp in maps:
            for seat in "AB":
                for so in (ps, bs):
                    games.append(((so, lv) if seat == "A" else (lv, so)) + (mp, f"{run}/g{len(games)}", "--statistics @STATS@ --fuel-log"))
                pairs.append((c, len(games) - 2, len(games) - 1))
    if not games or not pilotcxe.run(games, say=say):
        say("identity: no games")
        return 1
    rd = lambda p: open(p, "rb").read() if os.path.exists(p) else None  # noqa: E731
    bad = {}
    for c, i, j in pairs:
        for ext in (".repl26a", ".json", ".fuel.tsv"):
            x, y = rd(games[i][3] + ext), rd(games[j][3] + ext)
            if x is None or x != y:
                bad[c] = bad.get(c, 0) + 1
    for c in dict.fromkeys(p[0] for p in pairs):
        n = sum(p[0] == c for p in pairs)
        say(f"IDENTITY {c}: {n} game pairs, {n - min(n, bad.get(c, 0))} byte-identical (replay, statistics, per-turn fuel)"
            + ("" if c not in bad else f"; {bad[c]} file(s) DIFFER"))
    for g in games:
        for ext in (".repl26a", ".json", ".fuel.tsv"):
            try:
                os.remove(g[3] + ext)
            except OSError:
                pass
    cleanup(made, run, o["keep"])
    return 1 if bad else 0


def clean(a):
    """clean TAG: remove a run's scratch flips (nova_sf_TAG_*: armq's smoke hook calls it after a killed run) and its replays."""
    if len(a) != 1 or not re.fullmatch(r"[a-z0-9]+", a[0]):
        sys.exit("usage: smokefarm.py clean TAG")
    made = [b for b in os.listdir(os.path.join(REPO, "bots")) if b.startswith(f"nova_sf_{a[0]}_")]
    run = os.path.join(ROOT, a[0])
    os.makedirs(run, exist_ok=True)
    cleanup(made, run, False)
    g = os.path.join(run, "g")
    if os.path.isdir(g):
        for f in os.listdir(g):
            if f.endswith(".repl26a"):
                os.remove(os.path.join(g, f))
    return 0


def main():
    import signal  # 7 Nov: a kill (SIGTERM) now runs the finally blocks, so cxefarm cancels its queued items and the scratch flips go
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    a = sys.argv[1:]
    cmds = {"screen": screen, "factorial": factorial, "identity": identity, "clean": clean}
    if not a or a[0] in ("-h", "--help") or a[0] not in cmds:
        sys.exit(__doc__)
    os.nice(10)
    return cmds[a[0]](a[1:])


if __name__ == "__main__":
    sys.exit(main())
