#!/usr/bin/env python3
"""puppetmany: `puppet.py --diag` over many real games at once, on the Condor pilots (Tool builder, 11 Nov; Path Finding's ASK 2:
firing counts of our decision sites in REAL games v the top teams, not v our own copy).

usage: python3 -I tools/lab/puppetmany.py --diag DIAG --out DIR [--version v717[,v718]] [--foe Mite,SBG,Fish] [--games ID,ID | --games-file F] [--lane top3|side|all | --games-tsv F]
                                           [--limit N] [--prio 9] [--wave 60] [--build-chunk 8] [--per 6] [--summary-only] [--keep-fuel]
  --diag     the identity diag copy: NAME (every selected version; only sensible with one version) or v717=NAME,v718=NAME2 (one per version).
             A diag copy of the bot that played: `NEWBOT_UNBAKED=1 sh tools/lab/newbot.sh BOT nova_dg_X`, tools/lab/dglog.h in src/, DGP(tag, a, b, c, d)
             lines (integers; DGP makes no counted host call). Records only: any behaviour change shows as an early divergence.
  --version  versions to take games of (default: every version --diag names). Games come from /data/zw4424/st/climb_top3/games.tsv
             (--lane top3, the default), the side lanes' /data/zw4424/st/climb_side*/games.tsv (--lane side), both (--lane all), or any
             climb-format list (--games-tsv FILE, repeatable, globs; 11 Nov). A side-lane game whose replay is not on disk is refused (missing replay).
             --games/--games-file
             (match ids, full) restrict them. --foe: Mite, SBG (stellar best girl), Fish (Intercontinental Fish); names or substrings.
  --out      results; re-running the same command resumes (games with DIR/g/ID/result.json are skipped; a phase whose files exist is skipped).
  --summary-only  only rebuild DIR/records.tsv and DIR/summary.txt from the per-game results.

Per game, exactly what `puppet.py GAME --diag DIAG` does (same table(), write_bot(), map rebuild, compare()), without its CLI game:
  1. the puppet of the foe (one bot per game) and the rebuilt map. The bot is the version ACTIVE when the match was created (puppet.timed_version: checked
     on the first and last game of each version; a disagreement makes every game of that version look itself up).
  2. builds: the version's bot and its diag copy once each (cxebuild); the puppets' wasm on pilots, --build-chunk puppets in one pilot build item
     (mergecheck_node.sh builds a list), then cxebuild translates each wasm (w2c here, clang parts via pilotcc; the code parts hit the object cache, so a
     puppet after the first costs its data part).
  3. REC game: the unchanged bot v the puppet with CXE_FUEL_REC, on the pilots (cxefarm, priority --prio <= 9). fuel.rec comes back.
  4. PLAY game: the diag copy v the puppet with CXE_FUEL_PLAY (the fuel.rec staged on /homes, removed after), CXE_STDOUT=1, CXE_PROBE.
  5. gather: the first round each game differs from the real one (ours and foe, both games), fuel-play mismatches, the records
     (DIR/g/ID/diag_records.txt, the same lines puppet.py writes) and DIR/g/ID/result.json.
  Waves of --wave games go through 3-5 together (bounds the /homes staging).
Outputs:
  DIR/records.tsv   game foe map seat version tag round champion a b c d  (only rounds before the game's cut)
  DIR/coverage.tsv  one row per game: game foe map seat version bot real_last cut covered_rounds diag_ours diag_foe rec_ours rec_foe mismatches
                    first_mismatch_round mismatches_before_cut records_kept records_dropped status
  DIR/summary.txt   per foe: games puppeted, games refused (why), covered rounds; per tag: firings, games with >= 1, per covered game and per 1,000
                    covered rounds with 90% ranges.
Cut (exclusion): the first round any of the four comparisons differs (ours or foe, REC or PLAY game); records of that round and later are dropped,
  and a game covers rounds 1 .. cut-1 (all of it when nothing differs). Rates are only over covered rounds and covered games.
90% range: a bootstrap over games (2,000 resamples, seed 1): each resample draws the foe's games with replacement and recomputes firings/games and
  1000*firings/covered rounds (a ratio over the same resampled games). Games, not rounds, are the independent unit.
Refused games: a foe with two bodies of one champion type (puppet.py can't tell them apart), a missing replay, a bot no longer in bots/, a failed
  build or game; listed with the reason in coverage.tsv (status) and summary.txt.
Validation 11 Nov (5 v717 games, /data/zw4424/st/pmv): all 5 played; v puppet.py GAME --diag one by one, game 01a1c843 identical (never
  diverged, 0 mismatches, records byte-identical); the other 4 reference runs were still going (ref.log; compare DIR/g/ID/diag_records.txt).
Cost (5 games): one pilot build item for 5 puppets (30 s), translation 31 s (a pilotcc item per puppet: code parts differ per puppet),
  REC 34 s + PLAY 18 s (1 item each), gather ~5 s; the version bot + diag copy build once (~12 min when pilotcc finds no pilot)."""
import argparse
import collections
import concurrent.futures
import glob
import json
import os
import random
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import zipfile

REPO = "/homes/zw4424/cambc"
LAB = REPO + "/tools/lab"
sys.path.insert(0, LAB)
sys.path.insert(0, REPO + "/tools/cxe")
import puppet as P  # noqa: E402
import replay as R  # noqa: E402

GAMES = "/data/zw4424/st/climb_top3/games.tsv"
LANES = {"top3": [GAMES], "side": sorted(glob.glob("/data/zw4424/st/climb_side*/games.tsv"))}  # 11 Nov (Path Finding: side-lane losses)
LANES["all"] = LANES["top3"] + LANES["side"]
PLAT = "/data/zw4424/plat"
HSTAGE = "/homes/zw4424/condor-runs/stage"
FOES = {"mite": "Mite", "sbg": "stellar best girl", "fish": "Intercontinental Fish"}
SHORT = {"Mite": "Mite", "stellar best girl": "SBG", "Intercontinental Fish": "Fish"}
_lock = threading.Lock()


def say(msg):
    with _lock:
        print(f"puppetmany: {msg}", flush=True)


def gid_of(mid):
    return mid.replace("-", "")


# ---------- selection ----------
def select(a, diag_of):
    want_v = set(a.version.split(",")) if a.version else set(diag_of)
    foes = None
    if a.foe:
        foes = []
        for f in a.foe.split(","):
            f = f.strip().lower()
            foes.append(FOES.get(f, f))
    ids = None
    if a.games:
        ids = set(a.games.split(","))
    if a.games_file:
        ids = (ids or set()) | {ln.split()[0] for ln in open(a.games_file) if ln.strip() and not ln.startswith("#")}
    seen, out = set(), []
    files = [f for x in (a.games_tsv or []) for f in sorted(glob.glob(x))] or LANES[a.lane]
    lines = []
    for f in files:
        try:
            lines += open(f).read().splitlines()
        except OSError as e:
            say(f"games list {f} unreadable: {e}")
    for ln in lines:
        p = ln.rstrip("\n").split("\t")
        if len(p) < 7:
            continue
        v, foe, mid, mp, seat, res = p[0], p[1], p[3], p[4], p[5], p[6]
        if v not in want_v or mid in seen or (ids is not None and mid not in ids):
            continue
        import teamalias  # 12 Nov: 'prism best fih' (SBG renamed) matches the SBG filter
        if foes and not any(f.lower() in teamalias.canonical(foe).lower() for f in foes):
            continue
        seen.add(mid)
        out.append(dict(id=mid, version=v, foe=foe, map=mp, seat=seat.upper(), result=res))
    if a.limit:
        out = out[:a.limit]
    return out


def replay_path(g, d):
    """the real replay: plat/top3_vNNN/x_ID/replay.repl26a, else any set's copy, else extracted from a zip into d/game.repl26a"""
    for p in [f"{PLAT}/top3_{g['version']}/x_{g['id']}/replay.repl26a"] + sorted(glob.glob(f"{PLAT}/*/x_{g['id']}/replay.repl26a")):
        if os.path.exists(p):
            return p
    if os.path.exists(f"{d}/game.repl26a"):
        return f"{d}/game.repl26a"
    for zp in [f"{PLAT}/top3_{g['version']}/{g['id']}.zip"] + sorted(glob.glob(f"{PLAT}/*/{g['id']}.zip")):
        if os.path.exists(zp) and zipfile.is_zipfile(zp):
            with zipfile.ZipFile(zp) as z:
                nm = next((n for n in z.namelist() if n.endswith(".repl26a")), None)
                if nm:
                    open(f"{d}/game.repl26a.tmp", "wb").write(z.read(nm))
                    os.replace(f"{d}/game.repl26a.tmp", f"{d}/game.repl26a")
                    return f"{d}/game.repl26a"
    return None


def bots_for(games, diag_of):
    """{id: (bot, diag)} by the version active at match creation (puppet.timed_version on the first and last game of each version)."""
    byv = collections.defaultdict(list)
    for g in games:
        byv[g["version"]].append(g)
    out = {}
    for v, gs in byv.items():
        ends = {gs[0]["id"], gs[-1]["id"]}
        tv = {m: P.timed_version(m) for m in ends}
        per_game = any(t and t != v for t in tv.values())
        if per_game:
            say(f"{v}: the platform says {sorted(set(tv.values()) - {None})} was active for some games: looking every game up")
        for g in gs:
            t = (P.timed_version(g["id"]) if per_game else None) or v
            bot = P.bot_of(t)
            dg = diag_of.get(t)
            out[g["id"]] = (t, bot, dg)
    return out


# ---------- per-game preparation (local, small) ----------
def prepare(g, d, ver, bot, dg):
    """puppet bot + map, as puppet.main does. -> None, or a refusal reason"""
    if os.path.exists(f"{d}/prep.json"):
        x = json.load(open(f"{d}/prep.json"))
        return x.get("refused")
    os.makedirs(d, exist_ok=True)
    gid = gid_of(g["id"])
    refused = None
    try:
        if not dg:
            refused = f"no diag copy for {ver} (give --diag {ver}=NAME)"
        elif not bot or not os.path.isdir(f"{REPO}/bots/{bot}/src"):
            refused = f"bot of {ver} ({bot}) is not in bots/"
        else:
            path = replay_path(g, d)
            if not path:
                refused = "no replay on disk"
            else:
                real = R.load(path, g["seat"])
                foe = 1 if g["seat"] == "A" else 0
                try:
                    names, rows, skipped = P.table(real, foe)
                except SystemExit as e:
                    refused = str(e).replace("puppet: ", "")
                if not refused:
                    P.write_bot(f"{d}/nova_pup_{gid}", names, real.d["draft"][foe], rows)
                    mp = f"{d}/{gid}.map26a"
                    import subprocess
                    r = subprocess.run(["nice", "-n", "10", "python3", "-I", P.REPL2MAP, path, mp], capture_output=True, text=True)
                    if r.returncode:
                        refused = f"map rebuild failed: {(r.stdout + r.stderr).strip()[-150:]}"
    except Exception as e:  # noqa: BLE001
        refused = f"prepare failed: {type(e).__name__}: {str(e)[:150]}"
    json.dump(dict(id=g["id"], version=ver, bot=bot, diag=dg, refused=refused,
                   path=None if refused else replay_path(g, d)), open(f"{d}/prep.json", "w"))
    return refused


# ---------- builds ----------
def pilot_build_many(dirs, prio, chunk, wait):
    """release wasm of each puppet dir (name = basename) on the pilots, CHUNK per item. -> {dir: wasm path}"""
    import mergecheck as M
    import pilotd as pl
    M.setup_ws()
    got = {}
    if not dirs:
        return got
    try:
        if not pl.alive_pilots():
            pl.demand()
    except Exception:  # noqa: BLE001
        pass
    chunks = [dirs[i:i + chunk] for i in range(0, len(dirs), chunk)]
    stages = []
    for k, ch in enumerate(chunks):
        pd = f"{HSTAGE}/pmb_{os.getpid()}_{time.time_ns()}_{k}"
        os.makedirs(pd)
        with tarfile.open(f"{pd}/in.tgz", "w:gz") as tf:
            for x in ("cambc.toml", "sdk", "cmake"):
                tf.add(os.path.join(M.WS, x), arcname="proj/" + x)
            for dd in ch:
                tf.add(f"{dd}/src", arcname=f"proj/bots/{os.path.basename(dd)}/src")
        names = " ".join(os.path.basename(dd) for dd in ch)
        open(f"{pd}/job.sh", "w").write(f"cp {pd}/in.tgz . && sh {LAB}/mergecheck_node.sh in.tgz out.tgz ${{1:-4}} {names} && "
                                        f"cp out.tgz {pd}/.out.tmp && mv {pd}/.out.tmp {pd}/out.tgz\n")
        bid = pl.enqueue(pd, [(0, [f"run:{pd}/job.sh", 4])], prio)
        stages.append((pd, ch, bid))
    say(f"building {len(dirs)} puppets as {len(chunks)} pilot items ({chunk} an item, priority {prio})")
    t0, left = time.time(), list(range(len(stages)))
    try:
        while left and time.time() - t0 < wait:
            for k in list(left):
                pd, ch, bid = stages[k]
                pl.poke(pd)
                if not os.path.exists(f"{pd}/out.tgz"):
                    continue
                with tarfile.open(f"{pd}/out.tgz") as tf:
                    mem = {os.path.basename(m.name): m for m in tf.getmembers()}
                    for dd in ch:
                        nm = os.path.basename(dd)
                        if f"{nm}.wasm" in mem:
                            w = f"{dd}/pilot.wasm"
                            open(w + ".tmp", "wb").write(tf.extractfile(mem[f"{nm}.wasm"]).read())
                            os.replace(w + ".tmp", w)
                            got[dd] = w
                        elif f"{nm}.log" in mem:
                            open(f"{dd}/build.log", "wb").write(tf.extractfile(mem[f"{nm}.log"]).read())
                left.remove(k)
            time.sleep(3)
    finally:
        for pd, ch, bid in stages:
            if os.path.isdir(pd) and not os.path.exists(f"{pd}/out.tgz"):
                pl.cancel(bid)
            shutil.rmtree(pd, ignore_errors=True)
    say(f"puppet wasm: {len(got)} of {len(dirs)} built in {time.time() - t0:.0f} s")
    return got


def build_so(dirwasm):
    import cxebuild
    d, w = dirwasm
    try:
        so = cxebuild.build_bot(d, wasm=w)
        open(f"{d}/so.path", "w").write(so + "\n")
        return d, so
    except (SystemExit, Exception) as e:  # noqa: BLE001
        open(f"{d}/build.log", "a").write(f"translate: {e}\n")
        return d, None


# ---------- games ----------
def farm(games, prio, per, label):
    import cxefarm
    os.environ["CXEFARM"] = "1"
    t0 = time.time()
    n = cxefarm.run(games, say=lambda m: say(f"{label}: {m}"), per=per, cpus=per, prio=prio)
    say(f"{label}: {n} of {len(games)} games back in {time.time() - t0:.0f} s")
    return n


def rec_games(todo, prio, per):
    gs = []
    for k, (d, us, so_bot, so_pup, mp) in enumerate(todo):
        a, b = (so_bot, so_pup) if us == "A" else (so_pup, so_bot)
        for f in (f"{d}/diagbase.repl26a", f"{d}/fuel.rec", f"{d}/diagbase.err"):
            if os.path.exists(f):
                os.remove(f)
        gs.append(dict(id=k, a=a, b=b, map=mp, env={"CXE_FUEL_REC": "@D@/fuel.rec"},
                       files={"g.repl26a": f"{d}/diagbase.repl26a", "fuel.rec": f"{d}/fuel.rec", "stdout": f"{d}/diagbase.err"}))
    if gs:
        farm(gs, prio, per, "REC")


def play_games(todo, prio, per):
    sd = f"{HSTAGE}/pmf_{os.getpid()}_{time.time_ns()}"
    os.makedirs(sd)
    gs = []
    try:
        for k, (d, us, so_dg, so_pup, mp) in enumerate(todo):
            fr = f"{sd}/{k}.rec"
            shutil.copyfile(f"{d}/fuel.rec", fr)
            a, b = (so_dg, so_pup) if us == "A" else (so_pup, so_dg)
            for f in glob.glob(f"{d}/diag.*") + [f"{d}/diag_probe.tsv"]:
                if os.path.exists(f):
                    os.remove(f)
            gs.append(dict(id=k, a=a, b=b, map=mp, env={"CXE_FUEL_PLAY": fr, "CXE_STDOUT": "1", "CXE_PROBE": "@D@/probe.tsv"},
                           files={"g.repl26a": f"{d}/diag.repl26a", "probe.tsv": f"{d}/diag_probe.tsv", "stdout": f"{d}/diag.err",
                                  "g.team-a.stdout": f"{d}/diag.team-a.stdout", "g.team-b.stdout": f"{d}/diag.team-b.stdout"}))
        if gs:
            farm(gs, prio, per, "PLAY")
    finally:
        shutil.rmtree(sd, ignore_errors=True)


# ---------- gather ----------
def gather(job):
    """the same comparisons and records as puppet.diag(); writes result.json and diag_records.txt"""
    d, g, prep, keep_fuel = job
    us = g["seat"]
    ours = 0 if us == "A" else 1
    res = dict(id=g["id"], foe=g["foe"], map=g["map"], seat=us, version=prep["version"], bot=prep["bot"], diag=prep["diag"], status="ok")
    try:
        real = R.load(prep["path"], us)
        res["real_last"] = real.last_round
        fb, _ = P.compare(real, R.load(f"{d}/diagbase.repl26a", us))
        first, last = P.compare(real, R.load(f"{d}/diag.repl26a", us))
    except Exception as e:  # noqa: BLE001
        res["status"] = f"gather failed: {type(e).__name__}: {str(e)[:120]}"
        json.dump(res, open(f"{d}/result.json", "w"))
        return res
    pre = f"{d}/diag.team-{us.lower()}.stdout"
    lines = [ln for ln in open(pre, errors="replace") if ln.startswith("DG ")] if os.path.exists(pre) else []
    probe = []
    if os.path.exists(f"{d}/diag_probe.tsv"):
        for ln in open(f"{d}/diag_probe.tsv"):
            v = ln.split()
            if len(v) == 8 and v[1] == str(ours):
                probe.append(f"DP {v[3]} {v[0]} {v[2]} {v[4]} {v[5]} {v[6]} {v[7]}\n")
    open(f"{d}/diag_records.txt", "w").write("".join(probe + lines))
    err = open(f"{d}/diag.err", errors="replace").read().splitlines() if os.path.exists(f"{d}/diag.err") else []
    res["fuel_summary"] = next((ln[5:] for ln in err if ln.startswith("cxe: fuel-play:")), "fuel-play: no summary")
    mism = [ln[5:] for ln in err if ln.startswith("cxe: fuel-play mismatch")]
    mr = [int(m.group(1)) for m in (re.search(r" r(\d+) ", x) for x in mism) if m]
    res.update(diag_ours=first.get(ours, (None,))[0], diag_foe=first.get(1 - ours, (None,))[0], compared_through=last,
               rec_ours=fb.get(ours, (None,))[0], rec_foe=fb.get(1 - ours, (None,))[0], mismatches=len(mism),
               first_mismatch=mism[0] if mism else None, first_mismatch_round=min(mr) if mr else None)
    cuts = [x for x in (res["diag_ours"], res["diag_foe"], res["rec_ours"], res["rec_foe"]) if x]
    res["cut"] = min(cuts) if cuts else None
    res["covered_rounds"] = (res["cut"] - 1) if res["cut"] else real.last_round
    res["mismatches_before_cut"] = sum(1 for r in mr if res["cut"] is None or r < res["cut"])
    recs, dropped = [], 0
    for ln in probe + lines:
        v = ln.split()
        if v[0] == "DP":
            tag, rnd, champ, vals = f"DP{v[1]}", int(v[2]), v[3], v[4:8]
        else:
            tag, rnd, champ, vals = f"DG{v[1]}", int(v[2]), "-", v[3:7]
        if res["cut"] is not None and rnd >= res["cut"]:
            dropped += 1
            continue
        recs.append([tag, rnd, champ] + vals)
    res["records_kept"], res["records_dropped"] = len(recs), dropped
    json.dump(recs, open(f"{d}/records.json", "w"))
    json.dump(res, open(f"{d}/result.json.tmp", "w"))
    os.replace(f"{d}/result.json.tmp", f"{d}/result.json")
    if not keep_fuel:
        for f in (f"{d}/fuel.rec",):
            if os.path.exists(f):
                os.remove(f)
    return res


# ---------- summary ----------
def boot(per_game, B=2000, seed=1):
    """per_game: [(firings, covered_rounds)] -> (per game, lo, hi, per 1000 rounds, lo, hi) with 90% bootstrap ranges over games"""
    n = len(per_game)
    if not n:
        return (0,) * 6
    f = sum(x for x, _ in per_game)
    rr = sum(r for _, r in per_game) or 1
    rng = random.Random(seed)
    pg, pr = [], []
    for _ in range(B):
        s = [per_game[rng.randrange(n)] for _ in range(n)]
        sf, sr = sum(x for x, _ in s), sum(r for _, r in s) or 1
        pg.append(sf / n)
        pr.append(1000 * sf / sr)
    pg.sort()
    pr.sort()
    lo, hi = int(0.05 * B), int(0.95 * B) - 1
    return f / n, pg[lo], pg[hi], 1000 * f / rr, pr[lo], pr[hi]


def summarise(out, games):
    rows, cov, results = [], [], []
    for g in games:
        d = f"{out}/g/{gid_of(g['id'])}"
        prep = json.load(open(f"{d}/prep.json")) if os.path.exists(f"{d}/prep.json") else {}
        if os.path.exists(f"{d}/result.json"):
            r = json.load(open(f"{d}/result.json"))
        else:
            r = dict(id=g["id"], foe=g["foe"], map=g["map"], seat=g["seat"], version=prep.get("version", g["version"]), bot=prep.get("bot"),
                     status=("refused: " + prep["refused"]) if prep.get("refused") else (open(f"{d}/status").read().strip() if os.path.exists(f"{d}/status") else "not done"))
        results.append(r)
        cov.append([r["id"], SHORT.get(r["foe"], r["foe"]), r["map"], r["seat"], r.get("version"), r.get("bot")] +
                   [r.get(k) for k in ("real_last", "cut", "covered_rounds", "diag_ours", "diag_foe", "rec_ours", "rec_foe", "mismatches",
                                       "first_mismatch_round", "mismatches_before_cut", "records_kept", "records_dropped")] + [r["status"]])
        if r["status"] == "ok":
            for x in json.load(open(f"{d}/records.json")):
                rows.append([r["id"], SHORT.get(r["foe"], r["foe"]), r["map"], r["seat"], r["version"]] + x)
    with open(f"{out}/records.tsv", "w") as f:
        f.write("game\tfoe\tmap\tseat\tversion\ttag\tround\tchampion\ta\tb\tc\td\n")
        f.writelines("\t".join(map(str, x)) + "\n" for x in rows)
    with open(f"{out}/coverage.tsv", "w") as f:
        f.write("game\tfoe\tmap\tseat\tversion\tbot\treal_last\tcut\tcovered_rounds\tdiag_ours\tdiag_foe\trec_ours\trec_foe\tmismatches\t"
                "first_mismatch_round\tmismatches_before_cut\trecords_kept\trecords_dropped\tstatus\n")
        f.writelines("\t".join("-" if v is None else str(v) for v in x) + "\n" for x in cov)
    tags = sorted({x[5] for x in rows})
    cnt = collections.Counter((x[0], x[5]) for x in rows)
    L = [f"puppetmany summary {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}: {len(games)} games selected. Rates over covered rounds only "
         "(rounds before each game's first divergence); 90% ranges: bootstrap over games (2,000, seed 1)."]
    for foe in sorted({SHORT.get(r["foe"], r["foe"]) for r in results}):
        rs = [r for r in results if SHORT.get(r["foe"], r["foe"]) == foe]
        ok = [r for r in rs if r["status"] == "ok"]
        why = collections.Counter(re.sub(r"\(\[.*?\]\)|\[.*?\]", "", r["status"]).strip()[:90] for r in rs if r["status"] != "ok")
        cr = sum(r["covered_rounds"] for r in ok)
        full = sum(r["real_last"] for r in ok)
        cuts = sorted(r["covered_rounds"] for r in ok)
        L.append("")
        L.append(f"== {foe}: {len(ok)} of {len(rs)} games puppeted; covered rounds {cr} of {full} played ({100 * cr / max(1, full):.0f}%), "
                 f"median covered per game {cuts[len(cuts) // 2] if cuts else 0}; never diverged {sum(1 for r in ok if r['cut'] is None)}; "
                 f"games with fuel-play mismatches before the cut {sum(1 for r in ok if r.get('mismatches_before_cut'))}")
        for w, n in why.most_common():
            L.append(f"   not puppeted: {n} x {w}")
        if not ok:
            continue
        L.append(f"   {'tag':<8} {'firings':>7} {'games>=1':>9} {'per game [90%]':>24} {'per 1000 rounds [90%]':>28}")
        for t in tags:
            pg = [(cnt[(r["id"], t)], r["covered_rounds"]) for r in ok]
            a, alo, ahi, b, blo, bhi = boot(pg)
            L.append(f"   {t:<8} {sum(x for x, _ in pg):>7} {sum(1 for x, _ in pg if x):>5}/{len(ok):<3} {a:>8.2f} [{alo:.2f}, {ahi:.2f}]{'':>3} "
                     f"{b:>9.2f} [{blo:.2f}, {bhi:.2f}]")
    open(f"{out}/summary.txt", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(usage=__doc__.replace("%", "%%"))  # 11 Nov: a literal % in the docstring broke --help
    ap.add_argument("--diag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version")
    ap.add_argument("--foe")
    ap.add_argument("--games")
    ap.add_argument("--games-file")
    ap.add_argument("--lane", choices=sorted(LANES), default="top3", help="which climb games.tsv lists to take games from")
    ap.add_argument("--games-tsv", action="append", help="a games.tsv (climb format, globs ok); repeatable; overrides --lane")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--prio", type=int, default=min(9, int(os.environ.get("READ_PRIO") or 9)))
    ap.add_argument("--wave", type=int, default=60)
    ap.add_argument("--build-chunk", type=int, default=8)
    ap.add_argument("--per", type=int, default=6, help="games per pilot item")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--keep-fuel", action="store_true")
    a = ap.parse_args()
    a.prio = min(a.prio, 9)
    diag_of = {}
    for x in a.diag.split(","):
        if "=" in x:
            v, n = x.split("=", 1)
            diag_of[v.strip()] = n.strip()
        else:
            diag_of[None] = x.strip()
    if None in diag_of:
        if not a.version:
            sys.exit("puppetmany: a bare --diag NAME needs --version")
        for v in a.version.split(","):
            diag_of.setdefault(v, diag_of[None])
        diag_of.pop(None)
    out = os.path.abspath(a.out)
    os.makedirs(f"{out}/g", exist_ok=True)
    games = select(a, diag_of)
    if not games:
        sys.exit("puppetmany: no games selected")
    json.dump(dict(argv=sys.argv, t=time.time()), open(f"{out}/run.json", "w"))
    if a.summary_only:
        summarise(out, games)
        return 0
    T0 = time.time()
    todo = [g for g in games if not os.path.exists(f"{out}/g/{gid_of(g['id'])}/result.json")]
    say(f"{len(games)} games selected, {len(games) - len(todo)} done before, {len(todo)} to play; out {out}")
    if not todo:
        summarise(out, games)
        return 0
    need = [g for g in todo if not os.path.exists(f"{out}/g/{gid_of(g['id'])}/prep.json")]
    bmap = bots_for(need, diag_of) if need else {}
    for g in todo:
        d = f"{out}/g/{gid_of(g['id'])}"
        if g["id"] in bmap:
            ver, bot, dg = bmap[g["id"]]
        else:
            x = json.load(open(f"{d}/prep.json"))
            ver, bot, dg = x["version"], x["bot"], x["diag"]
        rf = prepare(g, d, ver, bot, dg)
        if rf:
            say(f"{g['id']} ({SHORT.get(g['foe'], g['foe'])}, {g['map']}): refused: {rf}")
    live = [g for g in todo if not json.load(open(f"{out}/g/{gid_of(g['id'])}/prep.json")).get("refused")]
    T1 = time.time()
    # builds: version bots and diag copies once each
    import cxebuild
    preps = {g["id"]: json.load(open(f"{out}/g/{gid_of(g['id'])}/prep.json")) for g in live}
    sos = {}
    for n in sorted({p["bot"] for p in preps.values()} | {p["diag"] for p in preps.values()}):
        say(f"building {n}")
        try:
            sos[n] = cxebuild.build_bot(n)
        except (SystemExit, Exception) as e:  # noqa: BLE001
            say(f"{n}: build failed: {e}")
    pdirs = {g["id"]: f"{out}/g/{gid_of(g['id'])}/nova_pup_{gid_of(g['id'])}" for g in live}
    nob = [pdirs[i] for i in pdirs if not os.path.exists(f"{pdirs[i]}/so.path") and not os.path.exists(f"{pdirs[i]}/pilot.wasm")]
    pilot_build_many(nob, a.prio, a.build_chunk, wait=int(os.environ.get("PUPPETMANY_BUILD_WAIT", 2400)))
    tr = [(pdirs[i], f"{pdirs[i]}/pilot.wasm") for i in pdirs if not os.path.exists(f"{pdirs[i]}/so.path") and os.path.exists(f"{pdirs[i]}/pilot.wasm")]
    if tr:
        t = time.time()
        with concurrent.futures.ThreadPoolExecutor(int(os.environ.get("PUPPETMANY_TRANSLATE", 3))) as ex:
            n_ok = sum(1 for _, so in ex.map(build_so, tr) if so)
        say(f"translated {n_ok} of {len(tr)} puppets in {time.time() - t:.0f} s")
    T2 = time.time()
    ready = []
    for g in live:
        d = f"{out}/g/{gid_of(g['id'])}"
        p = preps[g["id"]]
        sp = f"{pdirs[g['id']]}/so.path"
        why = None
        if p["bot"] not in sos or p["diag"] not in sos:
            why = "failed: bot or diag build"
        elif not os.path.exists(sp):
            why = "failed: puppet build" + (f" ({open(pdirs[g['id']] + '/build.log', errors='replace').read()[-120:].strip()})" if os.path.exists(pdirs[g['id']] + "/build.log") else "")
        if why:
            open(f"{d}/status", "w").write(why + "\n")
            continue
        ready.append((g, d, p, open(sp).read().strip(), f"{d}/{gid_of(g['id'])}.map26a"))
    nwave = 0
    for w in range(0, len(ready), a.wave):
        wave = ready[w:w + a.wave]
        nwave += 1
        rt = [(d, g["seat"], sos[p["bot"]], so, mp) for g, d, p, so, mp in wave
              if not (os.path.exists(f"{d}/fuel.rec") and os.path.exists(f"{d}/diagbase.repl26a"))]
        say(f"wave {nwave}: {len(wave)} games ({len(rt)} REC to play)")
        rec_games(rt, a.prio, a.per)
        pt = [(d, g["seat"], sos[p["diag"]], so, mp) for g, d, p, so, mp in wave
              if os.path.exists(f"{d}/fuel.rec") and os.path.exists(f"{d}/diagbase.repl26a") and not os.path.exists(f"{d}/diag.repl26a")]
        play_games(pt, a.prio, a.per)
        jobs = []
        for g, d, p, so, mp in wave:
            if os.path.exists(f"{d}/diag.repl26a") and os.path.exists(f"{d}/diagbase.repl26a"):
                jobs.append((d, g, p, a.keep_fuel))
            else:
                open(f"{d}/status", "w").write("failed: " + ("REC game did not come back" if not os.path.exists(f"{d}/diagbase.repl26a") else "PLAY game did not come back") + "\n")
        with concurrent.futures.ProcessPoolExecutor(int(os.environ.get("PUPPETMANY_GATHER", 3))) as ex:
            for r in ex.map(gather, jobs):
                say(f"{r['id']} {SHORT.get(r['foe'], r['foe'])} {r['map']}: {r['status']}; cut {r.get('cut')}, covered {r.get('covered_rounds')}/"
                    f"{r.get('real_last')}, mismatches {r.get('mismatches')}, records {r.get('records_kept')} kept {r.get('records_dropped')} dropped")
    T3 = time.time()
    say(f"timing: prepare {T1 - T0:.0f} s, builds {T2 - T1:.0f} s, games+gather {T3 - T2:.0f} s ({len(ready)} games, {nwave} waves); total {T3 - T0:.0f} s")
    summarise(out, games)
    return 0


if __name__ == "__main__":
    sys.exit(main())
