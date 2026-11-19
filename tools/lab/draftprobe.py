#!/usr/bin/env python3
"""draftprobe: the new maps where CAND's champion picks differ from BASE's. Tool builder, 4 Nov (owner via the Builder: a draft change
plays identical games wherever both bots draft the same, so those maps only dilute the read; play full games only where the picks differ).

usage: python3 -I tools/lab/draftprobe.py CAND BASE OUTDIR --n N [--batch 300] [--max-probe 40000] [--wall 14400] [--tag T]
  Takes new maps from the fresh pool (stratmaps --take: unsaved, half pathological) a batch at a time and plays CAND v BASE on both seats
  of every map, each game stopped after round 1 (the draft is over by then; condab OTF_ROUNDS=1). Picks are simultaneous and blind
  (GameRules :45-86: enemy picks unused), so one game a seat gives CAND's lineup in that seat and BASE's in the other. A map is CHANGED
  when CAND's lineup differs from BASE's in either seat. The KEPT changed maps are stratified (owner 4 Nov): N/2 weird and N/2 std
  (otf label pool), since a draft change may fire more on one kind; a half's extra changed maps are skipped, and once one half is full
  a batch takes two pool sets and probes only the short half's maps (4 Nov, tool builder 2: generating that half here at --light
  waited up to 30 min while the load was high). Up to DP_PAR batches (default 3) run at once; new ones start only while a half is
  still short after the changed maps the batches in flight should bring at the observed firing share. Stops when both halves are full, or at
  --max-probe maps (default 40,000) or --wall seconds (default 4 h), whichever first (owner 4 Nov: keep generating to a limit, then read
  what was found). RARITY CAP (7 Nov, Builder): after DP_RARE_N (5,000) probed maps with a firing share under DP_RARE_SHARE (3%) the
  probe stops and the read is INCONCLUSIVE (st['inconclusive']; stylepanel exits 2). Probe batches skip the local CLI spot-check
  (DP_SPOT=1 restores it): each one-round batch otherwise started CLI games here, and an 88-batch probe filled /var with their logs.
  REUSE (4 Nov, b1107): probe.json records draft_key(CAND), a fingerprint of the draft-path source only. A new probe with the same key
  and BASE adopts the newest finished probe's per-map lineups after re-probing a sample of its maps (all its changed maps up to 60,
  100 maps in all) and finding every lineup equal; then it tops up with new maps. BASE matches by name or by draft_key (7 Nov, Builder: mct2 passed after 77 min, live moved on an unrelated
  flip, and its re-read probed 40,000 maps again: a new base with the same draft path drafts the same lineups, and the sample above is still re-probed with the new pair). DP_REUSE_FROM=PANELTAG (inforead --probe-from) names a
  donor of another key (same draft, other source text), still verified. DP_REUSE=0 turns reuse off.
  OUTDIR gets otf.json (only the changed maps, labels and seeds kept: stylepanel / condab OTF reads it as is), their .map26a files, and
  probe.json: probed maps (both seats read), changed maps, firing share, and per map the four lineups and labels; the summary gives
  the firing share per half and per family. Probe maps stay in OUTDIR/probe/bK (probe reuse re-plays them); the 1-round replays are
  removed once their lineups are read (5 Nov, owner: bloat; DP_KEEP_REPLAYS=1 keeps them; tools/lab/probeprune.py clears old ones).
  STOCK (8 Nov, tool builder; owner: DXS took 19,757-35,635 probes for 669-1,089 changed maps): --stock draws from tools/lab/draftstock.py's map stock instead of the fresh pool, --base-has F (implies --stock) probes only the maps
  passing a draft-time filter on the stored BASE lineup / labels (e.g. ryth: 'Ryth in BASE's lineup' covers every DXS change). Halves stay N/2 weird, N/2 std. A map the probe keeps is consumed; unchanged, surplus and unread
  maps go back (a 1-round probe is not a read). Every filtered probe also probes ~DS_OUT_N (300) maps OUTSIDE the filter; coverage under .95 stops the probe INCONCLUSIVE, as does a stored lineup that differs from the BASE lineup measured here on over 2% of
  maps, and whole-pool shares are the inside share x the filter's share of the stock plus the outside part. No probe reuse in stock mode.
Used by: inforead.py CAND BASE --draft-changed N, stylepanel.py ... --draft-changed N. As a module: build(cand, base, outdir, n, tag).
Caveat: a pick missed through fuel is random (rules :8-10), so a probe can mark a map changed by chance; the draft turn's 10M fuel
makes this rare. Valid only for changes that act through the draft (or kit-specific play): a change that also alters common play
changes games on unchanged-draft maps too, and this read would miss that part."""
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
BQ = "/data/zw4424/st/bq"
PANEL = "/data/zw4424/st/panel"
sys.path.insert(0, REPO + "/tools/lab")


def say(msg, log=None):
    line = f"{time.strftime('%H:%M:%SZ', time.gmtime())} draftprobe: {msg}"
    print(line, flush=True)
    if log:
        with open(log, "a") as f:
            f.write(line + "\n")


def lineups(leg_dir):
    """-> {map: {'cA', 'bB'} or {'bA', 'cB'}: sorted kit names} from a kept 1-round CAND v BASE leg."""
    import replay as R
    out = {}
    try:
        games = json.load(open(f"{leg_dir}/set.json"))["games"]
    except (OSError, ValueError, KeyError):
        return out
    for g in games:
        try:
            r = R.load(os.path.join(leg_dir, g["replay"]), "A")
            team = {0: set(), 1: set()}
            for c, b in r.bodies.items():
                team[r.team_of[c]].add("cassi_issac" if b["name"] in ("cassi", "issac") else b["name"])
        except BaseException:  # noqa: BLE001  a broken replay: that seat is unread and the map is not probed
            continue
        a, b = sorted(team[0]), sorted(team[1])
        m = out.setdefault(g["map"], {})
        if g["seat"] == "a":  # CAND on side A
            m["cA"], m["bB"] = a, b
        else:
            m["bA"], m["cB"] = a, b
    return out


DRAFT_FILES = ("draft.cpp", "draft.h", "prismdraft.cpp", "mapfeat.cpp", "mapfeat.h", "fitfeat.cpp", "fitfeat.h", "mapinfo.cpp", "mapinfo.h",
               "plan.cpp", "plan.h", "planner.cpp", "planner.h", "zone.cpp", "zone.h", "strat.cpp", "strat.h", "dv3table.h", "prism.h")
DEF = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\b")
TAB = re.compile(r"^\s*inline\s+(?:const\s+volatile|constexpr(?:\s+const)?)\s+int\s+([A-Za-z_]\w*_TAB)\s*\[")


def draft_key(bot):
    """The draft's source fingerprint: the text of the draft-path files (DRAFT_FILES) plus every #define / flag table line, in any file,
    whose name they use (directly or through a table they use). Play code elsewhere (brain, combat, econ, common.h ...) and other flags'
    values don't enter, so arms that share a draft change and differ in kit play share a key. The gap is a draft-path call into code
    outside these files: build() re-probes a sample of the donor's maps (all its changed maps up to 60) before it adopts any lineup."""
    src = f"{REPO}/bots/{bot}/src"
    files = sorted(f for f in os.listdir(src) if f.endswith((".cpp", ".cc", ".h")))
    text = {f: open(f"{src}/{f}", errors="replace").read().splitlines() for f in files}
    used = set()
    cc = {x[:-4] + ".cc" for x in DRAFT_FILES if x.endswith(".cpp")}  # 8 Nov: the refactored layout's .cc twins of the .cpp draft files (mapfeat.cc, mapinfo.cc, planner.cc were outside the key)
    draft_files = set(DRAFT_FILES) | cc | {x for x in files if x.startswith(("draft_", "plan_", "contest_zone", "strategy", "champ_prism.h"))}
    for f in draft_files:
        for ln in text.get(f, []):
            if not (DEF.match(ln) or TAB.match(ln)):
                used.update(re.findall(r"[A-Za-z_]\w*", ln))
    for f in files:  # a draft-relevant table makes the defines it lists relevant
        for ln in text[f]:
            m = TAB.match(ln)
            if m and m.group(1) in used:
                used.update(re.findall(r"[A-Za-z_]\w*", ln))
    h = hashlib.sha1()
    for f in files:
        for ln in text[f]:
            m = DEF.match(ln) or TAB.match(ln)
            if f in draft_files and not m:
                h.update(f"{f}: {ln}\n".encode())
            elif m and m.group(1) in used:
                h.update(f"{m.group(1)}: {ln.split('//')[0].strip()}\n".encode())
    return h.hexdigest()[:16]


def probe_dir(cand, base, bdir, leg, log=None):
    """CAND v BASE, both seats of every map in BDIR (otf.json), 1 round, replays kept -> lineups()."""
    empty = f"{BQ}/subsets/empty.txt"
    if not os.path.exists(empty):
        open(empty, "w").close()
    env = dict(os.environ, OTF_DIR=bdir, OTF_KEEP=f"{bdir}/rep", OTF_ROUNDS="1", CONDAB_PRIO="12")
    if os.environ.get("DP_SPOT") != "1":  # 7 Nov (Builder: b1505's probe ran 88 batches, each with local CLI spot-check games, and /var filled
        env["CXE_SPOT"], env["CXE_SPOT_MIN"] = "0", "0"  # with their process starts): 1-round draft games stay on the pilots; DP_SPOT=1 keeps the check
    for x in ("KEEP", "SET", "SUBSET", "CONFIRM", "BIG", "STOP", "OTF_GAMES", "CONDAB_STOPFILE", "CONDAB_TIMEBOX", "CONDAB_HI_FAIL"):
        env.pop(x, None)
    with open(f"{BQ}/{leg}.draftprobe.log", "w") as lg:
        subprocess.run(["nice", "-n", "10", "sh", "tools/lab/condab.sh", cand, base, leg, empty], cwd=REPO, env=env, stdout=lg,
                       stderr=subprocess.STDOUT)
    got = lineups(f"{bdir}/rep")
    # 5 Nov (owner: cut the bloat): the 1-round replays are read once, here; the lineups go to probe.json. 82 probes had kept
    # 774k of them (20 GB). DP_KEEP_REPLAYS=1 keeps them.
    if os.environ.get("DP_KEEP_REPLAYS") != "1":
        for f in glob.glob(f"{bdir}/rep/rep/*.repl26a"):  # condab's OTF_KEEP writes DIR/rep/ (7 Nov: this read rep/*.repl26a, matched nothing, and 500k replays built up)
            try:
                os.remove(f)
            except OSError:
                pass
    return got


def map_index(d):
    """name -> (map dict, .map26a path) over a probe dir's batches."""
    out = {}
    for b in glob.glob(f"{d}/probe/b*/otf.json"):
        try:
            for m in json.load(open(b))["maps"]:
                p = os.path.join(os.path.dirname(b), m["name"] + ".map26a")
                if os.path.exists(p):
                    out[m["name"]] = (m, p)
        except (OSError, ValueError, KeyError):
            pass
    return out


def same_draft(a, b):
    """two bases that draft alike: the same bot, or the same draft-path source"""
    try:
        return a == b or draft_key(a) == draft_key(b)
    except (OSError, TypeError):  # a retired bot: unknown, so no
        return False


def find_donor(base, key, outdir, avoid=()):
    """The newest finished probe of the same draft key and BASE with its maps still on disk -> (dir, probe state) or None.
    AVOID: dirs never used (a second read must not adopt its first read's probe: 5 Nov, shipcheck 1430)."""
    best = None
    skip = {os.path.abspath(outdir)} | {os.path.abspath(x) for x in avoid}
    for pj in glob.glob(f"{PANEL}/*/probe.json"):
        d = os.path.dirname(pj)
        if os.path.abspath(d) in skip:
            continue
        try:
            st = json.load(open(pj))
        except (OSError, ValueError):
            continue
        if st.get("stock"):  # a stock probe's maps are the filter's, and went back to the stock: never a donor
            continue
        if st.get("key") == key and st.get("done") and st.get("probed") and (best is None or os.path.getmtime(pj) > best[0]) and same_draft(st.get("base"), base):
            best = (os.path.getmtime(pj), d, st)
    return best[1:] if best else None


def adopt(cand, base, outdir, tag, donor, log=None):
    """Re-probe up to 100 of the donor's maps (its changed maps first, up to 60) with CAND; every lineup equal -> the donor's per-map
    lineups (dict name -> record), else None."""
    d, dst = donor
    idx = map_index(d)
    have = [x for x in dst["maps"] if x in idx]
    ch = [x for x in have if dst["maps"][x]["changed"]][:60]
    un = [x for x in have if not dst["maps"][x]["changed"]][:100 - len(ch)]
    if len(ch) + len(un) < 20:
        return None
    vdir = f"{outdir}/probe/verify"
    os.makedirs(vdir, exist_ok=True)
    for x in ch + un:
        if not os.path.exists(f"{vdir}/{x}.map26a"):
            shutil.copyfile(idx[x][1], f"{vdir}/{x}.map26a")
    json.dump(dict(maps=[idx[x][0] for x in ch + un]), open(f"{vdir}/otf.json", "w"))
    say(f"reuse: donor {d} (same draft key, or DP_REUSE_FROM): verifying on {len(ch)} changed + {len(un)} unchanged of its maps", log)
    lu = probe_dir(cand, base, vdir, f"dp{tag}v", log)
    bad = [x for x in ch + un if lu.get(x) != {k: dst["maps"][x][k] for k in ("cA", "bA", "cB", "bB")}]
    if bad:
        say(f"reuse refused: {len(bad)} of {len(ch) + len(un)} verify maps differ (e.g. {bad[0]})", log)
        return None
    return {x: (dst["maps"][x], idx[x]) for x in have}


def build(cand, base, outdir, n, tag, batch=300, max_probe=40000, log=None, rare=0.0, wall=14400, avoid=(), stock=False, base_has=None):
    """build_once; a stock probe stopped by the rare-firing cap is played again from the fresh pool. 8 Nov (10000): a second read of a change finds the stock's changed maps already consumed
    (single-use), which reads as 'too rare'. The pool has new maps; a change that really is rare stops there too."""
    if not stock and not base_has and os.environ.get("DP_STOCK_DEFAULT", "1") == "1":  # 8 Nov (v634 dxs: 38,329 pool maps probed in 44 min, the games 1 min): the stock when it is full
        try:
            import draftstock as DS0
            stock = len(DS0.ready_names()) >= int(os.environ.get("DP_STOCK_MIN", 20000))
        except Exception:  # noqa: BLE001
            stock = False
    s = build_once(cand, base, outdir, n, tag, batch, max_probe, log, rare, wall, avoid, stock, base_has)
    if not ((stock or base_has) and (s.get("too_rare") or s.get("stopped") or s.get("kept", n) < n)):
        return s
    say(f"stock probe stopped on the rare-firing cap ({s.get('inconclusive')}): probing new pool maps instead", log)
    for f in ("probe.json", "otf.json"):
        if os.path.exists(os.path.join(outdir, f)):
            os.remove(os.path.join(outdir, f))
    shutil.rmtree(os.path.join(outdir, "probe"), ignore_errors=True)
    return build_once(cand, base, outdir, n, tag, batch, max_probe, log, rare, wall, avoid, False, None)


def build_once(cand, base, outdir, n, tag, batch=300, max_probe=40000, log=None, rare=0.0, wall=14400, avoid=(), stock=False, base_has=None):
    """Fill OUTDIR with the first n changed maps (otf.json + maps) and probe.json -> the probe summary dict. RARE > 0 (LANE=draft): stop
    after >= 600 probed maps when the firing share is under RARE (st['too_rare']; off by default: owner 4 Nov, keep generating to the limit).
    Limits (owner 4 Nov): MAX_PROBE maps (default 40,000) or WALL seconds of this call (default 4 h), whichever first; then the read uses
    what was found (st['stopped']). STOCK / BASE_HAS: draw from draftstock.py (see the module note)."""
    # AVOID (5 Nov, shipcheck 1430: the second read adopted the first read's own probe, so both reads were the same 1,200 maps):
    # dirs whose probe is never adopted and whose maps are never taken (a second read passes its first read's dir)
    avoid_names = set()
    for d in avoid:
        try:
            avoid_names |= {m["name"] for m in json.load(open(f"{d}/otf.json"))["maps"]}
        except (OSError, ValueError, KeyError):
            pass
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    pj = f"{outdir}/probe.json"
    key = draft_key(cand)
    st = json.load(open(pj)) if os.path.exists(pj) else dict(cand=cand, base=base, key=key, probed=0, changed=0, unread=0, batches=0, maps={})
    meta = json.load(open(f"{outdir}/otf.json")) if os.path.exists(f"{outdir}/otf.json") else None
    quota = {"weird": n - n // 2, "std": n // 2}
    stockm = bool(stock or base_has)
    DS = flt = lkey = None
    if stockm:
        import draftstock as DS  # noqa: N813
        flt = DS.parse_filter(base_has)
        DS.check_kits(flt)
        if not st.get("stock"):
            lkey, note = DS.key_for(base)
            st["stock"] = dict(filter=flt[2], key=lkey, note=note, frac=DS.frac(lkey, flt), root=DS.ROOT, mismatch=0)
            if note:
                say(f"stock: {note}", log)
        lkey = st["stock"]["key"]
        stored = (DS.load_lineups(lkey) or {}).get("maps", {})
        say(f"stock: filter {flt[2] or '(none)'} passes {100 * st['stock']['frac']['mean']:.1f}% of the stock (weird {100 * st['stock']['frac']['weird']:.1f}%, std "
            f"{100 * st['stock']['frac']['std']:.1f}%), lineups key {lkey}", log)
    kept = lambda: {h: sum(1 for m in (meta or {}).get("maps", []) if half(m) == h) for h in quota}

    def take(m, path):
        nonlocal meta
        if meta is None:
            meta = dict(maps=[], draft_probe=dict(cand=cand, base=base))
        if kept()[half(m)] < quota[half(m)] and m["name"] not in {x["name"] for x in meta["maps"]} and m["name"] not in avoid_names:
            shutil.copyfile(path, f"{outdir}/{m['name']}.map26a")
            meta["maps"].append(m)
            return 1
        return 0

    def save():
        if meta is not None:
            json.dump(meta, open(f"{outdir}/otf.json.part", "w"))
            os.replace(f"{outdir}/otf.json.part", f"{outdir}/otf.json")
        json.dump(st, open(pj, "w"))

    if not stockm and not st["probed"] and not st.get("reused_from") and os.environ.get("DP_REUSE", "1") == "1":  # 4 Nov (Builder, b1107): arms sharing a draft change
        rf = os.environ.get("DP_REUSE_FROM")  # inforead --probe-from TAG: a named donor (another key, e.g. same draft, other text), still verified
        dn = find_donor(base, key, outdir, avoid)
        if rf:
            try:
                ds_ = json.load(open(f"{PANEL}/{rf}/probe.json"))
                dn = (f"{PANEL}/{rf}", ds_) if ds_.get("base") == base else None
                if not dn:
                    say(f"reuse: {rf} probed against {ds_.get('base')}, not {base}: not used", log)
            except (OSError, ValueError):
                say(f"reuse: no {PANEL}/{rf}/probe.json", log)
        got = adopt(cand, base, outdir, tag, dn, log) if dn else None
        if got:
            for x, (rec, (m, path)) in got.items():
                st["maps"][x] = rec
                st["probed"] += 1
                st["changed"] += rec["changed"]
                if rec["changed"]:
                    take(m, path)
            st["reused_from"] = dn[0]
            st["unread"] += dn[1].get("unread", 0)
            save()
            kh = kept()
            say(f"reuse: adopted {st['probed']} probed maps from {dn[0]} ({st['changed']} changed); weird {kh['weird']}/{quota['weird']}, "
                f"std {kh['std']}/{quota['std']}", log)
    # 4 Nov (tool builder 2; Builder: rare drafts and a lagging half made probes wait 60+ min): up to DP_PAR batches run at once
    # (a batch is ~600 one-round games, almost all Condor round-trip time; the lineup read is ~1 s), and a half-only batch takes
    # pool sets and probes only the short half's maps instead of generating that half here (--light waited up to 30 min on load).
    # 8 Nov: stock batches draw nothing (no pool wait) and scale on the pilots: 10 x 150-map batches took 102 s (DP_PAR 3), 53 s (6), 30 s (12). Default 6 in stock mode; pool mode keeps 3 (a long probe drains the pool)
    par = max(1, int(os.environ.get("DP_PAR", 12 if stockm else 3)))  # 8 Nov: 12 in stock mode (30 s v 53 s at 6 for 10 batches)
    done_b = set(st.get("done_b", range(st["batches"])))
    nxt = st.get("next_batch", st["batches"])
    redo = [k for k in range(nxt) if k not in done_b and os.path.exists(f"{outdir}/probe/b{k}/otf.json")]  # drawn, not read
    inflight, stop = {}, None
    seen = set(st["maps"]) | set((st.get("outside") or {}).get("maps", {}))  # this probe's maps, returned to the stock batch by batch: never drawn twice

    def settle(k, names):
        """stock: a read batch's kept maps are consumed, the rest go back (idempotent: a resume repeats it)."""
        if stockm:
            DS.settle(f"{outdir}/probe/b{k}", names, {m["name"] for m in (meta or {}).get("maps", [])}, f"draftprobe:{tag}")

    if stockm:  # a resume: batches read before the stop that the stop left unsettled
        for k in sorted(done_b):
            try:
                settle(k, [m["name"] for m in json.load(open(f"{outdir}/probe/b{k}/otf.json"))["maps"]])
            except (OSError, ValueError, KeyError):
                pass

    def pool_share():
        """the observed changed share as a share of the pool: inside x the filter's fraction (outside maps: unknown here, ~0 by the safety row)"""
        s = st["changed"] / st["probed"] if st["probed"] else 0.0
        return s * st["stock"]["frac"]["mean"] if stockm and flt[2] else s

    def run_outside():
        """The safety row: ~DS_OUT_N maps outside the filter, CAND v BASE. They go back whatever they show; they are not read."""
        bdir, leg = f"{outdir}/probe/out", f"dp{tag}out"
        os.makedirs(bdir, exist_ok=True)
        if not os.path.exists(f"{bdir}/otf.json"):
            DS.draw(bdir, lkey, flt, DS.OUT_N - DS.OUT_N // 2, DS.OUT_N // 2, f"draftprobe:{tag}:outside", outside=True)
        bm = json.load(open(f"{bdir}/otf.json"))
        say(f"outside sample: {len(bm['maps'])} maps outside the filter {flt[2]} ({leg})", log)
        return -1, bm, probe_dir(cand, base, bdir, leg, log) if bm["maps"] else {}

    def coverage_check(final=False):
        """-> an INCONCLUSIVE reason once the safety row says the filter misses changed maps (stop now rather than read a narrower population), else None."""
        if not (stockm and flt[2]) or not (st.get("outside") or {}).get("done"):
            return None
        if not final and st["probed"] < int(os.environ.get("DP_COV_MIN", 100)):
            return None
        c = DS.coverage(st)
        ok, why = DS.safety_verdict(c)
        return None if ok else why

    def mismatch_check():
        """stored BASE lineups that differ from the ones measured here: a stale key or a key that missed the draft path. -> reason or None."""
        if not stockm:
            return None
        mm = st["stock"].get("mismatch", 0)
        if mm >= 3 and mm / max(1, st["probed"]) > DS.MISMATCH_BAR:
            return f"stored BASE lineups differ from the measured ones on {mm} of {st['probed']} maps: stale lineups for this BASE (draftstock.py lineups --bot {base})"
        return None

    def rate(h):  # observed firing share of a half (prior 0.10 before 100 maps)
        ms = [m for m in st["maps"].values() if half(m) == h]
        return sum(m["changed"] for m in ms) / len(ms) if len(ms) >= 100 else 0.10

    def short_now():
        """Halves still short after the changed maps the batches in flight should bring."""
        exp = {h: sum(rate(h) * c.get(h, 0) for _, c in inflight.values()) for h in quota}
        return [h for h in quota if kept()[h] + exp[h] < quota[h]]

    def run_batch(k, short, nn):
        bdir, leg = f"{outdir}/probe/b{k}", f"dp{tag}{k}"
        os.makedirs(bdir, exist_ok=True)
        if stockm and not os.path.exists(f"{bdir}/otf.json"):  # stock: nn maps of the short halves' maps, all passing the filter
            nw, ns = nn - nn // 2, nn // 2
            if len(short) == 1:
                nw, ns = (nn, 0) if short[0] == "weird" else (0, nn)
            DS.draw(bdir, lkey, flt, nw, ns, f"draftprobe:{tag}", exclude=seen)
        elif not os.path.exists(f"{bdir}/otf.json"):
            say(f"batch {k}: drawing {nn} maps ({'pool mix' if len(short) == 2 else short[0] + ' only, from pool sets'})", log)
            r = subprocess.run([sys.executable, "-I", "tools/lab/stratmaps.py", bdir, "--n", str(nn), "--take", "--who", f"draftprobe:{tag}"],
                               cwd=REPO, capture_output=True, text=True)
            if r.returncode:
                return k, None, f"stratmaps rc {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}"
            if len(short) == 1:
                bm = json.load(open(f"{bdir}/otf.json"))
                shutil.copyfile(f"{bdir}/otf.json", f"{bdir}/otf_all.json")  # the full draw; the other half's maps stay on disk, unplayed
                bm = dict(bm, maps=[m for m in bm["maps"] if half(m) == short[0]], half_only=short[0])
                json.dump(bm, open(f"{bdir}/otf.json.part", "w"))
                os.replace(f"{bdir}/otf.json.part", f"{bdir}/otf.json")
        bm = json.load(open(f"{bdir}/otf.json"))
        if bm.get("stock") and not bm["maps"]:
            return k, None, f"stock empty: no {'/'.join(short)} maps left that pass {flt[2] or '(no filter)'} (of ready, {bm['stock']['avail']}; {bm['stock']['nolu']} without a lineup)"
        say(f"batch {k}: {len(bm['maps'])} maps{' (' + bm['half_only'] + ' only)' if bm.get('half_only') else ''}, CAND v BASE both seats, 1 round ({leg})", log)
        return k, bm, probe_dir(cand, base, bdir, leg, log)

    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    with ThreadPoolExecutor(par + 1) as ex:
        if stockm and flt[2] and not (st.get("outside") or {}).get("done"):
            inflight[ex.submit(run_outside)] = (-1, {})
        while True:
            while not stop and sum(1 for v in inflight.values() if v[0] >= 0) < par:
                if st["probed"] + st["unread"] + sum(sum(c.values()) for _, c in inflight.values()) >= max_probe or time.time() - t0 > wall:
                    if not inflight and any(kept()[h] < quota[h] for h in quota):
                        st["stopped"] = f"{'map limit ' + str(max_probe) if st['probed'] + st['unread'] >= max_probe else 'wall limit ' + str(wall // 60) + ' min'}"
                        say(f"limit reached ({st['stopped']}): reading on {len(meta['maps']) if meta else 0} changed maps", log)
                        stop = "limit"
                    break
                short = short_now()
                if not short:
                    break
                if redo:
                    k = redo.pop(0)
                else:
                    k, nxt = nxt, nxt + 1
                    st["next_batch"] = nxt
                nn = batch
                if len(short) == 1 and not stockm:  # half-only: two pool sets give ~one batch of the short half; one set when ~half a batch is enough
                    h = short[0]
                    nn = batch if (quota[h] - kept()[h]) / max(rate(h), 0.01) <= batch / 3 else 2 * batch
                exp = {h: nn / 2 for h in quota} if len(short) == 2 else {short[0]: nn if stockm else nn / 2}
                inflight[ex.submit(run_batch, k, short, nn)] = (k, exp)
            if not inflight:
                break
            fin, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for f in fin:
                inflight.pop(f)
                k, bm, lu = f.result()
                if bm is None:
                    say(lu, log)
                    if stockm and str(lu).startswith("stock empty"):
                        st["stopped"] = lu
                        stop = stop or "stock"
                    stop = stop or "stratmaps"
                    continue
                if k == -1:  # the safety row: back to the stock, read or not
                    o = dict(done=True, drawn=len(bm["maps"]), probed=0, changed=0, unread=0, maps={})
                    for m in bm["maps"]:
                        L = lu.get(m["name"], {})
                        if len(L) < 4:
                            o["unread"] += 1
                            continue
                        ch = L["cA"] != L["bA"] or L["cB"] != L["bB"]
                        o["probed"] += 1
                        o["changed"] += ch
                        o["maps"][m["name"]] = dict(L, changed=ch, labels=m.get("labels", {}))
                    st["outside"] = o
                    seen |= set(o["maps"])
                    bd = f"{outdir}/probe/out"
                    DS.settle(bd, [m["name"] for m in bm["maps"]], (), f"draftprobe:{tag}:outside")
                    say(f"outside sample: {o['changed']} of {o['probed']} maps OUTSIDE the filter changed ({o['unread']} unread)", log)
                    save()
                    why = coverage_check()
                    if why and not stop:
                        st["inconclusive"] = why
                        say(f"INCONCLUSIVE: {why}", log)
                        stop = "coverage"
                    continue
                if meta is None:
                    meta = dict({kk: v for kk, v in bm.items() if kk not in ("maps", "half_only", "stock")}, maps=[], draft_probe=dict(cand=cand, base=base))
                got = 0
                for m in bm["maps"]:
                    if m["name"] in st["maps"]:
                        continue
                    L = lu.get(m["name"], {})
                    if len(L) < 4:
                        st["unread"] += 1
                        continue
                    st["probed"] += 1
                    ch = L["cA"] != L["bA"] or L["cB"] != L["bB"]
                    st["maps"][m["name"]] = dict(L, changed=ch, labels=m.get("labels", {}))
                    if stockm:
                        seen.add(m["name"])
                        sl = stored.get(m["name"])
                        if sl and (sl["bA"] != L["bA"] or sl["bB"] != L["bB"]):
                            st["stock"]["mismatch"] = st["stock"].get("mismatch", 0) + 1
                            st["stock"].setdefault("mismatch_eg", []).append(m["name"])
                    if ch:
                        st["changed"] += 1
                        got += take(m, f"{outdir}/probe/b{k}/{m['name']}.map26a")
                done_b.add(k)
                st["done_b"] = sorted(done_b)
                st["batches"] = len(done_b)
                save()
                settle(k, [m["name"] for m in bm["maps"]])
                why = (coverage_check() or mismatch_check()) if not stop else None
                if why:
                    st["inconclusive"] = why
                    say(f"INCONCLUSIVE: {why}", log)
                    stop = "coverage"
                kh = kept()
                say(f"batch {k}: {got} changed maps kept; weird {kh['weird']}/{quota['weird']}, std {kh['std']}/{quota['std']}; {st['changed']} of {st['probed']} probed changed "
                    f"({st['unread']} unread; {len(inflight)} batches in flight)", log)
                if len(lu) == 0:
                    say("batch read no replays: stopping (see the condab log)", log)
                    stop = stop or "noreplays"
            # 12 Nov (owner via the Coordinator, CLAUDE.md §2 'No arbitrary Step 0 bars': a change that fires at all gets its read): the 3% rarity
            # cap is OFF by default; the probe runs to the owner's 40,000-map / 4 h cap and decides on what it found. DP_RARE_N=5000 restores it
            rn, rs = int(os.environ.get("DP_RARE_N", 0)), float(os.environ.get("DP_RARE_SHARE", 0.03))
            if rn and not stop and st["probed"] >= rn and pool_share() < rs:  # 7 Nov (Builder): no 40k-map hunts for a rare draft change
                sh = pool_share()
                st["too_rare"] = dict(share=sh, reach=int(sh * max_probe), cap=max_probe, bar=rs)
                st["inconclusive"] = f"firing {100 * sh:.2f}% < {100 * rs:g}% after {st['probed']} maps"
                say(f"INCONCLUSIVE: {st['inconclusive']} (DP_RARE_N / DP_RARE_SHARE); stopping the probe", log)
                stop = "rare"
            if rare and not stop and st["probed"] >= 600 and pool_share() < rare:
                sh = pool_share()
                st["too_rare"] = dict(share=sh, reach=int(sh * max_probe), cap=max_probe, bar=rare)
                say(f"TOO RARE: firing {100 * sh:.2f}% < {100 * rare:g}% after {st['probed']} maps: about {int(sh * max_probe)} changed maps at the "
                    f"{max_probe}-map cap; stopping", log)
                stop = "rare"
    if stockm and flt[2]:  # the row at the end too: a probe finishing under DP_COV_MIN inside maps, or an outside sample read last
        why = st.get("inconclusive") or coverage_check(final=True) or mismatch_check()
        if why and not st.get("inconclusive"):
            st["inconclusive"] = why
            say(f"INCONCLUSIVE: {why}", log)
    if stockm and st.get("inconclusive") and meta and meta["maps"]:  # no read will happen: the changed maps found go back too (1-round only), their copies leave OUTDIR
        DS.settle(outdir, [m["name"] for m in meta["maps"]], (), f"draftprobe:{tag}:inconclusive")
        say(f"inconclusive: {len(meta['maps'])} changed maps returned to the stock", log)
        meta["maps"] = []
        save()
    if stockm:  # whatever a stopped probe drew and did not read goes back
        for b in glob.glob(f"{outdir}/probe/b*/otf.json"):
            try:
                DS.settle(os.path.dirname(b), [m["name"] for m in json.load(open(b))["maps"]], {m["name"] for m in (meta or {}).get("maps", [])}, f"draftprobe:{tag}:end")
            except (OSError, ValueError, KeyError):
                pass
    if meta and meta["maps"]:  # weird and std alternate, so a first-K slice (stylepanel --panel-n) keeps the 50/50 mix
        w, d = [m for m in meta["maps"] if half(m) == "weird"], [m for m in meta["maps"] if half(m) == "std"]
        meta["maps"] = [m for pair in zip(w, d) for m in pair] + w[len(d):] + d[len(w):]
    st["done"] = True  # both halves full, or out of probes: a resume skips the probe
    save()
    return summary(st, meta)


def half(m):
    return "weird" if (m.get("labels") or {}).get("pool") == "weird" else "std"


def share(c, p):
    sh = c / p if p else 0.0
    se = math.sqrt(sh * (1 - sh) / p) if p else 0.0
    return dict(probed=p, changed=c, share=sh, lo=max(0.0, sh - 1.96 * se), hi=min(1.0, sh + 1.96 * se))


def summary(st, meta=None):
    """Firing share overall, per half (weird/std) and per family; kept maps per half. The whole-pool share is the halves' mean (the
    fresh pool is half weird), not the probed mix, which the short-half batches skew."""
    ms = st["maps"].values()
    out = dict(share(st["changed"], st["probed"]), unread=st["unread"], kept=len(meta["maps"]) if meta else 0, reused_from=st.get("reused_from"),
               stopped=st.get("stopped"),
               too_rare=st.get("too_rare"), inconclusive=st.get("inconclusive"))
    for h in ("weird", "std"):
        hs = [m for m in ms if half(m) == h]
        out[h] = dict(share(sum(m["changed"] for m in hs), len(hs)), kept=sum(1 for m in (meta or {}).get("maps", []) if half(m) == h))
    out["pool_share"] = (out["weird"]["share"] + out["std"]["share"]) / 2
    if st.get("stock") and st["stock"].get("frac"):  # a filtered probe's shares are inside the filter: scale them to the pool, with the outside sample's part
        import draftstock as DS  # noqa: N813
        fr = st["stock"]["frac"]
        out["stock"] = dict(st["stock"], inside_share=out["pool_share"])
        if st["stock"].get("filter"):
            out["pool_share"] = (fr["weird"] * out["weird"]["share"] + fr["std"] * out["std"]["share"]) / 2
            c = DS.coverage(st)
            out["safety"] = dict(c, ok=DS.safety_verdict(c)[0], unread=(st.get("outside") or {}).get("unread"))
            if (st.get("outside") or {}).get("probed"):
                out["pool_share"] += (1 - fr["mean"]) * st["outside"]["changed"] / st["outside"]["probed"]
    fams = {}
    for m in ms:
        f = fams.setdefault((m.get("labels") or {}).get("fam", "?"), [0, 0])
        f[0] += m["changed"]
        f[1] += 1
    out["fams"] = {f: dict(changed=c, probed=p) for f, (c, p) in sorted(fams.items(), key=lambda x: -x[1][0] / max(1, x[1][1]))}
    return out


def report(s):
    """Lines for a result file."""
    L = [f"draft probe: {s['changed']} of {s['probed']} probed maps changed ({100 * s['share']:.1f}%), {s['unread']} unread; "
         f"whole-pool firing share (halves' mean) {100 * s['pool_share']:.1f}%"]
    if s.get("stopped"):
        L.append(f"  probing stopped at the {s['stopped']}: the read uses the {s['kept']} changed maps found (target not reached)")
    if s.get("reused_from"):
        L.append(f"  probe reused from {s['reused_from']} (same draft, verified on a re-probed sample), then topped up")
    if s.get("stock"):
        k = s["stock"]
        L.append(f"  STOCK draw, filter {k.get('filter') or '(none)'}: {100 * k['frac']['mean']:.1f}% of the stock (weird {100 * k['frac']['weird']:.1f}%, std {100 * k['frac']['std']:.1f}%); lineups key {k['key']}"
                 + (f" ({k['note']})" if k.get("note") else "") + f"; {k.get('mismatch', 0)} stored lineups differ from the measured ones")
    if s.get("safety"):
        c = s["safety"]
        cov = f"{c['cov']:.3f}" if c["cov"] is not None else "n/a (nothing fired)"
        L.append(f"  SAFETY ROW (outside the filter): {c['out_changed']} of {c['out_probed']} changed ({100 * (c['outside'] or 0):.1f}%), inside {100 * c['inside']:.1f}%, coverage estimate {cov} (bar {__import__('draftstock').COV_BAR:.2f})")
    if s.get("inconclusive"):
        L.append(f"  !!! INCONCLUSIVE: {s['inconclusive']}")
    if s.get("too_rare"):
        t = s["too_rare"]
        L.append(f"  TOO RARE for the draft lane: firing {100 * t['share']:.2f}% < {100 * t['bar']:g}%: about {t['reach']} changed maps at the {t['cap']}-map cap")
    for h in ("weird", "std"):
        x = s[h]
        L.append(f"  {h:5s} {x['changed']:5d} of {x['probed']:5d} changed {100 * x['share']:5.1f}% [{100 * x['lo']:.1f}, {100 * x['hi']:.1f}], kept {x['kept']}")
    fl = [f"{f} {v['changed']}/{v['probed']}" for f, v in s["fams"].items() if v["changed"]]
    L.append("  families that fired (changed/probed): " + (", ".join(fl) if fl else "none"))
    return L


def main():
    a = sys.argv[1:]
    if len(a) < 3 or "--n" not in a:
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    s = build(a[0], a[1], os.path.abspath(a[2]), int(opt("--n", 0)), opt("--tag", time.strftime("%d%H%M%S", time.gmtime())),
              batch=int(opt("--batch", 300)), max_probe=int(opt("--max-probe", 40000)), wall=int(opt("--wall", 14400)),
              stock="--stock" in a, base_has=opt("--base-has", None))
    print("\n".join(report(s)))
    print(json.dumps(s))


if __name__ == "__main__":
    main()
