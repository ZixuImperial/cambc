#!/usr/bin/env python3
"""stylepanel: the FRESH-MAP leg and the PLAYSTYLE PANEL leg on N newly generated maps. Tool builder, 1 Nov (owner: "local
testing must use newly randomly generated maps of different kinds, and play against different playstyles of bots, not just
our previous bot").

usage: python3 -I tools/lab/stylepanel.py CAND LIVE TAG [--n 300] [--panel b1,b2,..] [--par 4] [--read-only] [--keep-maps]
  1. maps: tools/lab/stratmaps.py /data/USER/st/panel/TAG --n N (new os.urandom seeds; stratified by family, team size, area,
     spawn distance, altars, terrain, economy; seeds and recipes in TAG/otf.json). The .map26a files are removed at the end
     (--keep-maps keeps them); otf.json stays.
  2. legs (condab with OTF_DIR=the maps and an empty SET, both seats of every map; at most --par at a time):
     fp<TAG> CAND vs LIVE; pc<TAG><k> CAND vs panel bot k; pl<TAG><k> LIVE vs panel bot k.
  3. read (each leg's per-map lines in its condab summary BQ/NAME.condor.txt), summary /data/USER/st/bq/sp<TAG>.txt:
     FRESH  CAND vs LIVE map-pair score (both seats of a map: 1 / 0.5 / 0), overall with a 95% CI, and per kind (every level of
            every label). FAIL when the overall CI upper < 0.5. SECOND READ (owner, 2 Nov: this test fires falsely on about 1 read in 6): a kind with
            >= 10 maps at z <= -KIND_Z (2.5) no longer fails by itself. It starts one more fresh set of the same size on new maps (fp<TAG>r, panel/<TAG>r), and
            the overall bars then read both sets pooled. A kind blocks only if it is negative again: second-set point < 0.5 and pooled z <= -KIND_Z. A kind
            flagged only on the second set blocks only at pooled z <= -KIND_Z with both sets under 0.5. No third set. A second set that cannot finish reads
            INCONCLUSIVE, not PASS. Every flag and its outcome goes to BQ/fresh_second_reads.jsonl.
     PANEL  per panel bot b: D_b = CAND's score vs b minus LIVE's score vs b, paired by map (each side's both-seat score on
            the map), with a 95% CI over maps; pooled D = per map the mean over bots, CI over maps. FAIL when the pooled CI
            upper < 0, or a bot's D has z <= -BOT_Z (2.5, ~10 bots).
  The fresh leg's per-game records (deaths, fuel ...) go to TAG/fp_games.jsonl (condab OTF_GAMES).
  --fresh-only plays only the FRESH leg (gate.py --no-style); the PANEL line says SKIPPED.
  --class 'heavy_ge:>=0.5' (or SP_CLASS; 10 Nov, Planner): every fresh set is drawn with stratmaps --class (tools/lab/mapclass.py), so FRESH
  reads class maps only (also the panel legs, on their own maps: no shared panel set). Every drawn set is tagged with --class-tag's classes
  (default heavy_ge; SP_CLASS_TAG=none: off); the FRESH CLASS line under FRESH bins the scores: a --class read prints its class row, a plain read
  class >= 0.5 / off-class < 0.2 / middle. shipcheck appends it to the fresh row (after ' | ').
  --parent PID stops every leg when PID is gone (shipcheck passes its own pid); SIGTERM stops them too.
  SP_KEEP=DIR keeps every leg's replays (replay only) in DIR/<leg name>/ with a set.json for readmany (inforead --keep-replays).
  --panel-add NAME[,NAME] (or SP_PANEL_ADD) adds OPT-IN spars (OPTIONAL, e.g. nova_spar_fastsiege) to the default or --panel list.
  --read-only re-reads finished legs (no maps, no games). Missing panel bots (bots/NAME absent) are skipped and listed.
Default panel: the aggressive dash-opener (nova_spar_opener), heavy, nochase2, fastbank, the Prism-focused spar (prismhunt),
the recall-spinner and top-Prism spars when built (spinner, topprism), and three distinct styles from sparcal_1101
(willow358, tavi, anc_dl3)."""
import argparse
import collections
import glob
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
BQ = "/data/USER/st/bq"
PANEL_DIR = "/data/USER/st/panel"
EMPTY = BQ + "/subsets/empty.txt"
PANEL = ["nova_spar_opener", "nova_spar_heavy", "nova_spar_nochase2", "nova_spar_fastbank", "nova_spar_prismhunt",
         "nova_spar_spinner", "nova_spar_topprism", "nova_spar_willow358", "nova_spar_tavi", "nova_spar_anc_dl3",
         # 1 Nov (Builder: losses to all-dash teams such as NEETCoders could not be reproduced locally): opponent-STYLE spars,
         # v394 copies with a spar-only draft (draft.cpp SPAR_ALLDASH / SPAR_SUSTAIN, no Prism-first, no draft swap)
         "nova_spar_alldash", "nova_spar_sustain",
         # 2 Nov: reproduces the live income gap (b413); of the unused spars, most losses no panel spar finds (3 of 104 maps, r <= 0.29)
         "nova_spar_ring",
         # 2 Nov: b802's draft-only hunter (trunk5l, SPH_BITS=1; not a model of any team): correlation with the panel <= 0.17, 8 both-seat-loss maps no other spar finds
         "nova_spar_hunter2",
         # 2 Nov: b809's forced Vesper / no Prism draft on v404 source: lowest score of the panel on 200 unused maps, max r 0.22 with any spar; not a model of live teams
         "nova_spar_vesper",
         # 2 Nov: b814's hound spars on v406 source, tuned on live chase and kill rates; on 150 new maps v406 scores .577 / .660, deaths 9.73 / 8.99 (panel max 4.90), r .16 / .15 with the panel
         "nova_spar_hd126", "nova_spar_hd318", "nova_spar_neet",
         # 4 Nov: b1164's centre-holding spar (takes .589 of mid body-turns v live's .411; v497 beats it .720): no-harm v centre-control styles
         "nova_spar_centre",
         # 5 Nov (Econ, board.md LOB): forced lineups of the teams that beat us live on gem-poor 5-pick no-monolith maps, on v508
         # code; live scores .63 v them on that class (v hd126 .85-1.00): a live loss class no other spar sees. Panel checks only
         "nova_ft_lobl1", "nova_ft_lobl2"]
PANEL_FULL = PANEL  # the 21-bot panel up to 5 Nov
# Panel gaps (owner 8 Nov: a no-harm check; the spawn-pressure band is NOT met): /data/USER/st/b1682/calibration.md. Owner: the shipcheck row reads as before.
# 5 Nov (owner: "reduce the sparring bots; no need if the strategy is not that different ... should decrease shipping time"): one spar per distinct
# style. Single-spar flags over all reads were spread 1-2 per spar across 13 spars (chance), never a recurring catch. Restore: SP_PANEL_FULL=1.
INFO_SPARS = []  # 12 Nov: information-only panel spars (SP_PANEL_INFO), filled in main
PANEL = PANEL_FULL if os.environ.get("SP_PANEL_FULL") else ["nova_spar_aggro", "nova_spar_sbg", "nova_spar_fish"]  # owner 8 Nov (spec_panel3_1108): these three replace the deleted spars. Before: owner 6 Nov ~22:50Z: prune the playstyle bots (was 7: + hd126, sustain, centre, prismhunt)
# OPT-IN spars: never in PANEL or PANEL_FULL; a run adds them with --panel-add NAME[,NAME] (or SP_PANEL_ADD=NAME[,NAME]),
# or names them in --panel. 6 Nov (sp1): nova_spar_fastsiege = v552 whose crew commits to the map's pack early (FSG_ON,
# econ.cpp fsg_pack; reports/build_sp1_fastsiege.md): reads siege/race decisions on one-pack maps (00stampede class).
OPTIONAL = ["nova_spar_fastsiege"]
KIND_Z = float(os.environ.get("SP_KIND_Z", "2.5"))
SECOND_LOG = BQ + "/fresh_second_reads.jsonl"
BOT_Z = float(os.environ.get("SP_BOT_Z", "2.5"))
LABELS = ("fam", "team", "area", "spawn", "altar", "terrain", "econ", "pool")  # pool: weird / std (stratmaps, 1 Nov)
# 10 Nov (Planner: a class read in one command): --class COND (or SP_CLASS) draws every fresh set of this run through stratmaps --class
# (tools/lab/mapclass.py), so the FRESH rows read class maps only; --class-tag NAME[,..] (default SP_CLASS_TAG or heavy_ge; 'none' = off)
# writes each map's class values into otf.json after the draw (~15 ms a map). The summary's FRESH CLASS line bins the fresh scores by them.
CLS_ARGS = []  # extra stratmaps args (--class ...), set in main
CLS_TAG = []  # class names tagged into every drawn otf.json
CLS_COND = [None]


def strat_say(r):
    """The stratmaps line worth logging: its first line, or with --class its 'class COND: k of N maps' summary."""
    out = (r.stdout + r.stderr).strip().split("\n")
    if CLS_COND[0]:
        return next((x for x in reversed(out) if x.startswith("stratmaps: class ") and " maps from " in x), out[0])
    return out[0]


CLS_LATE = [x for x in os.environ.get("SP_CLASS_LATE", "heavy_ge2,monoreach,grc1,dom,tavi_bg,gold_share,als_share,onealt,small,team4,psa_s1,voc_rich,own_gold,holex,holexb,bushy,siege_map,midgem_share,lowpay,zgs").split(",") if x and x != "none"]
# 11 Nov (owner: "sometimes we have to separate strategies, as one general strategy will not reach the top band"): every fresh read's
# FRESH CLASS line bins its scores by these map classes too (class >= .5 / off-class < .2 / middle), tagged at summary time (after the games,
# so the draw is not slowed), so a candidate that loses pooled but wins a class shows it. SP_CLASS_LATE=none: off.


LATE_THREADS = []


def late_tag(d):
    """start the late class tags of d in a background thread (~60 s for 600 maps, run while the games play); late_join() waits for them"""
    if not CLS_LATE or CLS_COND[0]:
        return
    import threading

    def run():  # 11 Nov (load 58 with 9 checks): lowest CPU priority, and at most SP_CLASS_LATE_N maps tagged (the bins are information)
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (OSError, AttributeError):
            pass
        lim = int(os.environ.get("SP_CLASS_LATE_N", 1200))
        try:  # 12 Nov (owner: "fast iterations"; the late tags cost ~1.9 CPU-min a check on the main machine): 400 maps while its load > 40
            if os.getloadavg()[0] > float(os.environ.get("SP_CLASS_LATE_BUSY", 40)):
                lim = min(lim, int(os.environ.get("SP_CLASS_LATE_N_BUSY", 400)))
        except OSError:
            pass
        tag_maps(d, [x for x in CLS_LATE if x not in CLS_TAG], limit=lim)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    LATE_THREADS.append(t)


def late_join(timeout=0):
    for t in LATE_THREADS:
        t.join(timeout)


def tag_maps(d, names=None, limit=None):
    """Add "class": {NAME: value} for CLS_TAG (or names) to every map of d/otf.json that lacks one (never fails the run: a bad map is skipped)."""
    names = list(names) if names is not None else list(CLS_TAG)
    if not names:
        return
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mapclass
        p = f"{d}/otf.json"
        meta = json.load(open(p))
        k = 0
        pre = {}
        want = [f"{d}/{m['name']}.map26a" for j, m in enumerate(meta["maps"]) if (limit is None or j < limit)
                and not all(n in m.get("class", {}) for n in names)]
        if len(want) >= int(os.environ.get("SP_TAG_PILOTS_MIN", 50)) and os.environ.get("SP_TAG_PILOTS", "1") != "0":
            try:  # 12 Nov ~22:3xZ (owner "iterate faster"; local CPU is the cap): classify on the pilots (stratmaps._cls_on_pilots), local fallback
                import stratmaps
                pre = stratmaps._cls_on_pilots(want, names) or {}
            except Exception:  # noqa: BLE001
                pre = {}
        for j, m in enumerate(meta["maps"]):
            if limit is not None and j >= limit:
                break
            if all(n in m.get("class", {}) for n in names):
                continue
            try:
                src_ = f"{d}/{m['name']}.map26a"
                v_ = pre.get(src_)
                m.setdefault("class", {}).update(v_ if isinstance(v_, dict) else mapclass.values(src_, names))
                k += 1
            except Exception:  # noqa: BLE001  (an unreadable map stays untagged)
                pass
        if k:
            json.dump(meta, open(p + ".part", "w"))
            os.replace(p + ".part", p)
    except Exception as e:  # noqa: BLE001  (tagging is information only)
        say(f"class tag skipped for {d}: {str(e)[:80]}")


CLASS_TSV = BQ + "/classbins.tsv"  # 11 Nov (Planner): one row per read x class x bin, for screening failed reads by a pre-registered class


def class_tsv(tag, cand, live, fs, cv):
    """append tag cand live class bin n point lo hi time rows (bins: class >= .5 / off < .2 / middle) to bq/classbins.tsv; never fails a read"""
    try:
        rows = []
        for nm in sorted({k for mp in fs for k in cv.get(mp, {})}):
            vs = {mp: cv.get(mp, {}).get(nm) for mp in fs}
            for lbl, xs in (("class", [fs[mp] for mp, v in vs.items() if v is not None and v >= 0.5]),
                            ("off", [fs[mp] for mp, v in vs.items() if v is not None and v < 0.2]),
                            ("middle", [fs[mp] for mp, v in vs.items() if v is not None and 0.2 <= v < 0.5])):
                if xs:
                    m, se, n = ci(xs)
                    rows.append(f"{tag}\t{cand}\t{live}\t{nm}\t{lbl}\t{n}\t{m:.4f}\t{m - 1.96 * se:.4f}\t{m + 1.96 * se:.4f}\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        if rows:
            new = not os.path.exists(CLASS_TSV)
            with open(CLASS_TSV, "a") as f:
                if new:
                    f.write("tag\tcand\tlive\tclass\tbin\tn\tpoint\tlo\thi\ttime\n")
                f.writelines(rows)
    except Exception:  # noqa: BLE001
        pass


def class_line(fs, cv):
    """FRESH CLASS line from the fresh scores {map: x} and class values {map: {NAME: v}}; None when no map carries a value.
    With --class: the class row only (plus a count of maps outside it, which a class draw never has); else per tagged class
    three bins: >= 0.5 (class), < 0.2 (off-class), the middle, and maps with no value."""
    if not fs or not any(cv.get(mp) for mp in fs):
        return None

    def row(lbl, v):
        m, se, n = ci(v)
        return f"{lbl}: n {n}" + ("" if n == 0 else f", {m:.3f}" if n < 2 else f", {m:.3f} [{m - 1.96 * se:.3f}, {m + 1.96 * se:.3f}]")
    parts = []
    if CLS_COND[0]:
        import mapclass
        conds = mapclass.parse(CLS_COND[0])
        inn = [x for mp, x in fs.items() if mapclass.passes(cv.get(mp, {}), conds)]
        parts.append(row(f"class {CLS_COND[0].replace(':', '')}", inn))
        if len(inn) < len(fs):
            parts.append(f"outside the class: n {len(fs) - len(inn)}")
    else:
        for nm in sorted({k for mp in fs for k in cv.get(mp, {})}):
            vs = {mp: cv.get(mp, {}).get(nm) for mp in fs}
            parts += [row(f"class {nm}>=0.5", [fs[mp] for mp, v in vs.items() if v is not None and v >= 0.5]),
                      row(f"off-class {nm}<0.2", [fs[mp] for mp, v in vs.items() if v is not None and v < 0.2]),
                      *([row("middle", mid)] if (mid := [fs[mp] for mp, v in vs.items() if v is not None and 0.2 <= v < 0.5]) else [])]
            k = sum(v is None for v in vs.values())
            if k:
                parts.append(f"no value: n {k}")
    return "FRESH CLASS: " + "; ".join(parts)


def say(msg):
    print(f"[stylepanel {time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def leg(name, a, b, mdir, dump=None, games=None):
    env = dict(os.environ, OTF_DIR=mdir, CONDAB_PRIO=os.environ.get("SP_PRIO", "10"))
    # 2 Nov (gate 7981 sat 82 min on two legs): a leg with no job back for this long stops, and the read uses the maps it has. The fresh leg decides ships, so it gets longer
    env["CONDAB_STALL"] = str(int(os.environ.get("SP_STALL", 900)) * (2 if dump else 1))
    if dump:  # the fresh leg's per-game records (deaths ...) for shipcheck's death guard
        env["OTF_GAMES"] = dump
    elif games:  # 12 Nov (Coordinator / VV, b2283 draft read): panel legs record per-game results too (record only: no stall or early-stop change)
        env["OTF_GAMES"] = games
    for k in ("CONFIRM", "BIG", "KEEP", "STOP", "STOP_REF", "OTF_DOM", "OTF_RULE", "OTF_GEMCLU", "CONDAB_TIMEBOX",
              "CONDAB_TIMEBOX_EXT", "CONDAB_HI_FAIL", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND", "CONDAB_STOPFILE", "OTF_KEEP",
              "OTF_ROUNDS"):
        env.pop(k, None)  # a shipcheck parent's per-leg settings: the panel plays every game of every leg (and never a capped game)
    if dump and os.environ.get("SP_FRESH_EARLY"):  # 12 Nov (owner: make the queue faster; fix-lane early stop): the FRESH leg only stops at
        # condab's interim looks once it can no longer reach its bar (score + Z * se < BAR, >= MIN map pairs back): SP_FRESH_EARLY=BAR,Z,MIN
        env["STOP"] = "1"
        env["CONDAB_HI_FAIL"] = os.environ["SP_FRESH_EARLY"]
    if os.environ.get("SP_KEEP"):  # 3 Nov (inforead --keep-replays): each leg's replays in SP_KEEP/<leg>, a readmany source
        env["OTF_KEEP"] = os.path.join(os.environ["SP_KEEP"], name)
    cmd = ["sh", "tools/lab/condab.sh", a, b, name, EMPTY]
    if name.startswith("pls"):  # a shared base leg (--panel-shared): one check plays it, the rest wait on its lock and reuse it
        cmd = [sys.executable, "-I", os.path.abspath(__file__), "--pl-run", name, a, b, mdir]
    with open(f"{BQ}/{name}.stylepanel.log", "a" if name.startswith("pls") else "w") as lg:
        return subprocess.Popen(cmd, cwd=REPO, env=env, stdout=lg, stderr=subprocess.STDOUT)


def pl_run(name, a, b, mdir):
    """--pl-run: a shared base leg (LIVE v a spar on the per-live panel set): under its lock, play it only when its summary holds
    under 90% of the set's maps (another check may have played it meanwhile)."""
    import fcntl
    lk = open(f"{mdir}/.{name}.lock", "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    ms = {m["name"] for m in json.load(open(f"{mdir}/otf.json"))["maps"]}
    n = len(ms)
    if len(set(map_score(name, a)) & ms) >= 0.9 * n:  # 11 Nov: only maps of THIS set count (an overwritten summary held another set's maps)
        print(f"stylepanel: shared leg {name} already complete ({n} maps): reused")
        return 0
    return subprocess.run(["sh", "tools/lab/condab.sh", a, b, name, EMPTY], cwd=REPO).returncode


def shared_set(live, n):
    """The panel's per-live map set (owner 7 Nov ~15:40Z: the panel's base side uses one fresh set per live version, shared by the
    candidates tested on that live; a new set at every ship): PANEL_DIR/shared_<live>_<n>, drawn once (stratmaps --take) under a lock."""
    import fcntl
    d = f"{PANEL_DIR}/shared_{live}_{n}"
    os.makedirs(PANEL_DIR, exist_ok=True)
    with open(f"{PANEL_DIR}/.shared_{live}_{n}.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.exists(f"{d}/otf.json"):
            r = subprocess.run(["python3", "-I", "tools/lab/stratmaps.py", d, "--n", str(n), "--take", "--who", f"stylepanel-shared:{live}"],
                               cwd=REPO, capture_output=True, text=True)
            say((r.stdout + r.stderr).strip().split("\n")[0])
            if r.returncode != 0:
                return None
            tag_maps(d)
    return d


SF_ON = "/data/USER/st/bq/shared_fresh"
SF_ROOT = "/data/USER/st/sharedfresh"
SF_BLK = 1000


def shared_fresh_slice(mdir, n, tag, live):
    """13 Nov (owner, typed to the Builder: "can they not just share maps and regenerate when we have the next ship?" and "or on retests"):
    while bq/shared_fresh exists, the FIRST read of every candidate tested against one live (look 1 'TAG'/'TAGff' and its sequential
    extensions 'TAGq<look>x<i>') plays the same per-live fresh set: SF_ROOT/<live>/blk_K (SF_BLK maps each, default mix, stratmaps --take,
    made on first use, never reused across lives). Look 1 takes maps [0, n); each extension chunk takes the next slice (cursor per check
    tag). Retests never share: a CONFIRM (SP_FRESH_NEW=1), near-miss 'TAGx', second sets and class/changed reads draw new maps as before.
    -> True when mdir was filled from the shared set."""
    import fcntl
    # 13 Nov 22:2xZ (owner via the Builder: "only generate maps for when we need it for the rare changes. Just stick with the same map set
    # for now"): while bq/shared_fresh_pin names a version, every non-class fresh read (look 1, extensions, confirms, near-miss/second
    # sets) plays that version's shared set; reads past look 1 take the check's next unused slice (cursor per check number)
    try:
        pin = open(os.path.join(BQ, "shared_fresh_pin")).readline().split()[0]
    except (OSError, IndexError):
        pin = ""
    m = re.fullmatch(r"(\d+)(ff|q\d+x\d+)?", tag or "")
    if pin and not m:
        m = re.fullmatch(r"(\d+)([A-Za-z0-9_]+)", tag or "")
    if not os.path.exists(SF_ON) or not m or (os.environ.get("SP_FRESH_NEW") == "1" and not pin) or CLS_ARGS:
        return False
    base, kind = m.group(1), m.group(2) or ""
    if pin and os.environ.get("SP_FRESH_NEW") == "1" and not kind.startswith("q"):
        kind = "q" + kind  # a confirm on the pinned set: next unused slice, not maps [0, n)
    if pin and kind and kind != "ff" and not kind.startswith("q"):
        kind = "q" + kind
    try:  # keyed on the LIVE version (bq/live.txt), not the leg's base: a TRUNK-mode check's base is its own private trunk
        live = pin or open(os.path.join(BQ, "live.txt")).readline().split()[0]
    except (OSError, IndexError):
        return False
    d = os.path.join(SF_ROOT, re.sub(r"[^A-Za-z0-9_.-]", "_", live))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if kind.startswith("q"):
            cp = os.path.join(d, f"cur_{base}")
            try:
                start = int(open(cp).read().strip())
            except (OSError, ValueError):
                start = int(os.environ.get("SF_LOOK1", "1000"))
            open(cp, "w").write(str(start + n))
        else:
            start = 0
        need = start + n
        maps = []
        k = 0
        while len(maps) < need:
            bd = os.path.join(d, f"blk_{k:03d}")
            if not os.path.exists(os.path.join(bd, "otf.json")):
                r = subprocess.run(["python3", "-I", "tools/lab/stratmaps.py", bd, "--n", str(SF_BLK), "--take", "--who", f"sharedfresh:{live}"],
                                   cwd=REPO, capture_output=True, text=True)
                if r.returncode != 0 or not os.path.exists(os.path.join(bd, "otf.json")):
                    say(f"shared fresh: block {k} of {live} failed ({(r.stderr or r.stdout).strip()[-160:]}); drawing new maps instead")
                    return False
            mm = sorted(json.load(open(os.path.join(bd, "otf.json")))["maps"], key=lambda x: x["name"])
            maps += [(bd, x) for x in mm]
            k += 1
    sl = maps[start:need]
    os.makedirs(mdir, exist_ok=True)
    for bd, x in sl:
        dst = os.path.join(mdir, x["name"] + ".map26a")
        if not os.path.exists(dst):
            os.link(os.path.join(bd, x["name"] + ".map26a"), dst)
    json.dump(dict(maps=[x for _, x in sl], log=[f"shared fresh set of {live}: maps {start}..{need - 1}"], tag=f"sharedfresh:{live}",
                   made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(os.path.join(mdir, "otf.json.part"), "w"))
    os.replace(os.path.join(mdir, "otf.json.part"), os.path.join(mdir, "otf.json"))
    say(f"shared fresh (owner 13 Nov): {len(sl)} maps {start}..{need - 1} of {live}'s shared set")
    return True


def classbank_slice(mdir, n, tag):
    """13 Nov (Builder/b2365, OCF-P 'prism_fielded': the class depends on our draft, so no map-file class can draw it): while SP_CLASSBANK names
    a bank dir (maps + otf.json, filled by the line's own screener on FRESH maps), every fresh draw of this check (look 1, extensions,
    confirms) takes the next n NEVER-USED maps of that bank, in otf order. Use is recorded in BANK/used.txt under a lock, so no map is read
    twice by any check. -> True when mdir was filled; False when the bank is short (the check then has no fresh maps: INCONCLUSIVE)."""
    import fcntl
    bank = os.environ.get("SP_CLASSBANK", "").strip()
    if not bank or not os.path.exists(os.path.join(bank, "otf.json")):
        return False
    with open(os.path.join(bank, ".lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            used = {ln.strip() for ln in open(os.path.join(bank, "used.txt"))}
        except OSError:
            used = set()
        maps = [m for m in json.load(open(os.path.join(bank, "otf.json")))["maps"]
                if m["name"] not in used and os.path.exists(os.path.join(bank, m["name"] + ".map26a"))]
        if len(maps) < n:
            say(f"class bank {bank}: {len(maps)} unused maps, {n} needed: short")
            return False
        sl = maps[:n]
        with open(os.path.join(bank, "used.txt"), "a") as f:
            f.writelines(f"{m['name']}\n" for m in sl)
    os.makedirs(mdir, exist_ok=True)
    for m in sl:
        dst = os.path.join(mdir, m["name"] + ".map26a")
        if not os.path.exists(dst):
            os.link(os.path.join(bank, m["name"] + ".map26a"), dst)
    json.dump(dict(maps=sl, log=[f"class bank {bank}: {len(sl)} never-used maps for {tag}"], tag=f"classbank:{os.path.basename(bank)}",
                   made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(os.path.join(mdir, "otf.json.part"), "w"))
    os.replace(os.path.join(mdir, "otf.json.part"), os.path.join(mdir, "otf.json"))
    say(f"class bank (13 Nov): {len(sl)} never-used maps of {os.path.basename(bank)} for {tag}")
    return True


def pls_name(live, p, n=600):
    """the shared base leg's name: the live bot's number and a stable code for the spar"""
    import zlib
    m = re.match(r"nova_b(\d+)", live)
    # 10 Nov 21:5xZ (Builder: vsp1 lost a .5122 read): two hand-submitted lives from one agent (nova_b1831_bfBv707 = v708,
    # nova_b1831_bf5v710 = v711) shared the number 1831, condab refused the reused NAME and every panel leg returned nothing.
    # The live's full name now goes into the code as well.
    base = f"{m.group(1)}x{zlib.crc32(live.encode()) % 1000}" if m else str(zlib.crc32(live.encode()) % 100000)
    # 11 Nov: a shared set of another size got the same name and overwrote the 600-map leg (fix checks drew 3,300-map panels): n in the name
    return f"pls{base}_{zlib.crc32(p.encode()) % 100000}" + (f"n{n}" if n and n != 600 else "")


WORD = {"won both": 1.0, "split": 0.5, "lost both": 0.0}


_REMOTE = [0.0, False, ""]


def games_remote():
    """True while condab legs play on Condor (>= 4 pilots alive; cxe and cxecondor batches both go there then), re-checked every 30 s."""
    if time.time() - _REMOTE[0] > 30:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import pilotd
            n = len(pilotd.alive_pilots())
            _REMOTE[1], _REMOTE[2] = n >= 4, f"{n} pilots alive"
        except Exception as e:  # noqa: BLE001
            _REMOTE[1], _REMOTE[2] = False, f"pilot check failed: {e!r}"[:160]
        _REMOTE[0] = time.time()
    return _REMOTE[1]


def load_par():
    """Concurrent condab legs (capped further by --par). Games on Condor (4 Nov, iterspeed report: legs ran 2 at a time at load 88-130
    all evening although the games played remotely, ~8 h of serialised reads): 8, or 4 above load 300. Games on HOST: 8 below
    load 40, 4 below 60, else 2."""
    la = os.getloadavg()[0]
    n = (8 if la < 32 else 4) if games_remote() else (4 if la < 24 else 2)  # owner 4 Nov ~21:55Z: CPU crashed VS Code
    if n != _LP[0]:  # logged on change: why a read runs fewer legs at once
        _LP[0] = n
        print(f"[stylepanel {time.strftime('%H:%M:%S')}] legs at once: {n} (load {la:.0f}, {_REMOTE[2]})", flush=True)
    return n


_LP = [None]


def map_score(name, a):
    """{map: a's both-seat score (1 / 0.5 / 0)} from condab NAME's summary: OTF games are never archived or indexed, so the
    summary's per-map lines ("  fm_... : A won both|split|lost both | seed ...") are their only record."""
    out = {}
    try:
        txt = open(f"{BQ}/{name}.condor.txt").read()
    except OSError:
        return out
    for m in re.finditer(r"^  (fm_\w+) .*?: (\S+) (won both|split|lost both) \|", txt, re.M):
        if m.group(2) == a:
            out[m.group(1)] = WORD[m.group(3)]
    return out


def short_legs(a, mdir, legs):
    """Legs whose summary holds under 90% of their maps (panel legs: --panel-n of them when set)."""
    n = len(json.load(open(f"{mdir}/otf.json"))["maps"])
    out = []
    for nm, x, _ in legs:
        if a.fresh_first and not os.path.exists(f"{BQ}/{nm}.condor.txt"):
            continue  # a fresh FAIL plays no panel: not lost, never started
        want = n if nm == f"fp{a.tag}" or not a.panel_n else min(n, a.panel_n)
        if len(map_score(nm, x)) < 0.9 * want:
            out.append(nm)
    return out


def src_hash(bot):
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    return abindex.bot_hash(bot)


def adopt_fresh(a, mdir, want_n):
    """--reuse-fresh (1 Nov, Builder speed item 2): a finished fresh read of the SAME two sources (gate.py's fresh leg marks its
    complete read REUSABLE with both source hashes and keeps its maps) is adopted instead of playing a new draw: its maps,
    otf.json, per-game records and condab summary move here, so only the panel legs play (on the same maps). One use: the claim
    renames REUSABLE -> REUSED_BY_<tag> (atomic), so no second check adopts it. -> the source tag, or None."""
    hc, hl = src_hash(a.cand), src_hash(a.live)
    def _mt(r):  # another check may claim (rename) a REUSABLE between the glob and here
        try:
            return os.path.getmtime(r)
        except OSError:
            return -1.0
    names = [r for r in sorted(glob.glob(f"{PANEL_DIR}/*/REUSABLE"), key=_mt, reverse=True) if _mt(r) >= 0]
    for r in names:
        src = os.path.dirname(r)
        stag = os.path.basename(src)
        try:
            h = json.load(open(f"{src}/hashes.json"))
            meta = json.load(open(f"{src}/otf.json"))
        except (OSError, ValueError):
            continue
        import abindex  # the engine too (4 Nov finals patch): a read played on 2.0.0 (no 'cli' stamp) is never adopted on 3.0.0
        if (h.get("cand"), h.get("live"), h.get("hc"), h.get("hl")) != (a.cand, a.live, hc, hl) or len(meta["maps"]) < 0.95 * want_n \
                or h.get("cli", "4.0.0") != abindex.cli_version() or meta.get("class_filter") != (a.cls or None):  # a class read adopts only a read of the same class
            continue
        if not os.path.exists(f"{BQ}/fp{stag}.condor.txt"):
            continue
        try:
            os.rename(r, f"{src}/REUSED_BY_{a.tag}")  # the claim
        except OSError:
            continue
        os.makedirs(mdir, exist_ok=True)
        for m in meta["maps"]:
            f = f"{src}/{m['name']}.map26a"
            if os.path.exists(f):
                os.replace(f, f"{mdir}/{m['name']}.map26a")
        for f in ("fp_games.jsonl", "hashes.json"):
            if os.path.exists(f"{src}/{f}"):
                open(f"{mdir}/{f}", "w").write(open(f"{src}/{f}").read())
        meta["reused_from"] = stag
        json.dump(meta, open(f"{mdir}/otf.json", "w"))
        open(f"{BQ}/fp{a.tag}.condor.txt", "w").write(f"# reused from fp{stag} (stylepanel --reuse-fresh, same source hashes)\n"
                                                    + open(f"{BQ}/fp{stag}.condor.txt").read())
        return stag
    return None


def adopt_second(a, stag):
    """A gate's second read moves with its first: the same pair needs no third set."""
    src = f"{PANEL_DIR}/{stag}_r"
    if os.path.exists(f"{src}/otf.json") and os.path.exists(f"{BQ}/fp{stag}_r.condor.txt"):
        os.makedirs(f"{PANEL_DIR}/{a.tag}_r", exist_ok=True)
        open(f"{PANEL_DIR}/{a.tag}_r/otf.json", "w").write(open(f"{src}/otf.json").read())
        open(f"{BQ}/fp{a.tag}_r.condor.txt", "w").write(f"# reused from fp{stag}_r\n" + open(f"{BQ}/fp{stag}_r.condor.txt").read())


def adopt_panel(a, stag, have, nmaps):
    """After adopt_fresh: the gate's panel legs on those same maps, for spars of the same source, need no replay: their summaries
    are the only record of these games (OTF maps are never indexed). A leg with under 95% of the maps plays. -> leg names done."""
    try:
        src = json.load(open(f"{PANEL_DIR}/{stag}/panel.json"))
    except (OSError, ValueError):
        return set()
    done = set()
    for i, p in enumerate(have):
        e = src.get(p)
        if not e or e.get("hash") != src_hash(p):
            continue
        for pre, bot in (("pc", a.cand), ("pl", a.live)):
            name = f"{pre}{stag}_{e['i']}"
            if len(map_score(name, bot)) >= 0.95 * nmaps:
                open(f"{BQ}/{pre}{a.tag}_{i}.condor.txt", "w").write(f"# reused from {name} (stylepanel --reuse-fresh, same sources and maps)\n"
                                                                    + open(f"{BQ}/{name}.condor.txt").read())
                done.add(f"{pre}{a.tag}_{i}")
    return done


def ci(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else float("nan")), float("nan"), n
    m = sum(v) / n
    se = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1) / n)
    return m, se, n


def kind_groups(fs, lab):
    """{(label, level): [scores]} of one set of maps."""
    g = collections.defaultdict(list)
    for dim in LABELS:
        for mp, x in fs.items():
            if dim in lab.get(mp, {}):
                g[(dim, lab[mp][dim])].append(x)
    return g


def kind_stat(v):
    m, se, n = ci(v)
    if n and not (se and se > 0):  # every map the same: a kind lost on all of them used to read z 0 and never flag (b935)
        return m, se, n, (-99.0 if m < 0.5 else 99.0 if m > 0.5 else 0.0)
    return m, se, n, ((m - 0.5) / se if se and se > 0 else 0.0)


# 12 Nov (Builder, owner-approved third reads cleared TSX/GNW/NTG1's kind flags): SP_KIND_CLEAR = 'dim=level,...' kinds already cleared for
# this candidate's line (bq/kindflag_cleared.tsv, set by shipcheck): they neither flag nor block; every other kind is read as before
KIND_CLEAR = {x.strip() for x in os.environ.get("SP_KIND_CLEAR", "").split(",") if x.strip()}


def first_flags(fs, lab, kind_z):
    return sorted(k for k, v in kind_groups(fs, lab).items() if kind_stat(v)[2] >= 10 and kind_stat(v)[3] <= -kind_z
                  and f"{k[0]}={k[1]}" not in KIND_CLEAR)


def second_outcomes(fs1, fs2, lab, kind_z):
    """The second-read rule per kind -> [dict(kind, n1, m1, z1, n2, m2, z2, np, mp, zp, flag, blocks)] for each kind flagged on either set."""
    g1, g2 = kind_groups(fs1, lab), kind_groups(fs2, lab)
    out = []
    for k in sorted(set(g1) | set(g2)):
        if f"{k[0]}={k[1]}" in KIND_CLEAR:
            continue
        m1, _, n1, z1 = kind_stat(g1.get(k, []))
        m2, _, n2, z2 = kind_stat(g2.get(k, []))
        f1, f2 = n1 >= 10 and z1 <= -kind_z, n2 >= 10 and z2 <= -kind_z
        if not (f1 or f2):
            continue
        mp, _, np_, zp = kind_stat(g1.get(k, []) + g2.get(k, []))
        low = zp <= -kind_z
        blocks = (n2 > 0 and m2 < 0.5 and low) if f1 else (n1 > 0 and m1 < 0.5 and m2 < 0.5 and low)
        out.append(dict(kind=f"{k[0]}={k[1]}", n1=n1, m1=m1, z1=z1, n2=n2, m2=m2, z2=z2, np=np_, mp=mp, zp=zp, flag="first" if f1 else "second", blocks=blocks))
    return out


def fresh_block(fs1, fs2, lab, kind_z, fresh_min, second_state):
    """The FRESH lines. fs2: the second set's scores or None. second_state: "" (none wanted), "done", or why it is missing. -> (verdict, lines, record)."""
    pooled = dict(fs1, **(fs2 or {}))
    m, se, n = ci(list(pooled.values()))
    hi = m + 1.96 * se if n > 1 else float("nan")
    low_pt = fresh_min is not None and m < fresh_min
    flags = first_flags(fs1, lab, kind_z)
    out = second_outcomes(fs1, fs2, lab, kind_z) if second_state == "done" else []
    blocked = [o["kind"] for o in out if o["blocks"]]
    by = {o["kind"]: o for o in out}
    rows = []
    for k, v in sorted(kind_groups(pooled, lab).items()):
        km, kse, kn, z = kind_stat(v)
        name = f"{k[0]}={k[1]}"
        o = by.get(name)
        mark = ""
        if o:
            mark = (f"  << first {o['m1']:.3f} n{o['n1']} z {o['z1']:+.1f}, second {o['m2']:.3f} n{o['n2']} z {o['z2']:+.1f}: "
                    + ("significantly negative again" if o["blocks"] else "not confirmed"))
        elif k in flags:
            mark = "  << flagged, second read not finished"
        rows.append(f"  {k[0]:8s} {k[1]:11s} n {kn:3d}  {km:.3f} [{km - 1.96 * kse:.3f}, {km + 1.96 * kse:.3f}]  z {z:+.1f}" + mark)
    if n < 20:
        fv = "INCONCLUSIVE"
    elif hi < 0.5 or low_pt or blocked:
        fv = "FAIL"
    elif flags and second_state != "done":
        fv = "INCONCLUSIVE"  # a flag needs its second read: without one it neither fails nor passes
    else:
        fv = "PASS"
    reads = ""
    if fs2:
        m1, se1, n1 = ci(list(fs1.values()))
        m2, se2, n2 = ci(list(fs2.values()))
        reads = f" (pooled; first {m1:.3f} [{m1 - 1.96 * se1:.3f}, {m1 + 1.96 * se1:.3f}] n{n1}; second {m2:.3f} [{m2 - 1.96 * se2:.3f}, {m2 + 1.96 * se2:.3f}] n{n2})"
    if flags and second_state != "done" and fv == "INCONCLUSIVE":
        reads += f" (second read {second_state or 'not started'} for " + ", ".join(f"{d}={lv}" for d, lv in flags) + ")"
    line = (f"FRESH: {fv}  CAND vs LIVE {m:.4f} [{m - 1.96 * se:.3f}, {hi:.3f}] over {n} maps{reads}; "
            f"bar: CI upper >= 0.5 and no kind negative on a second read (z <= -{kind_z:g})" + (f" and score >= {fresh_min:g}" if fresh_min is not None else "")
            + (f"; negative kinds: {', '.join(blocked)}" if blocked else ""))
    return fv, [line, *rows, ""], dict(verdict=fv, n=n, m=round(m, 4), hi=round(hi, 4), second=second_state, flags=[f"{d}={lv}" for d, lv in flags],
                                       kinds=[{k: (round(v, 3) if isinstance(v, float) else v) for k, v in o.items()} for o in out])


def changed_build(a, mdir, tag, avoid=()):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import changedprobe
    return changedprobe.build(a.cand, a.live, mdir, a.changed, tag, max_probe=int(os.environ.get("SP_CHANGED_MAX", 40000)), wall=int(os.environ.get("SP_CHANGED_WALL", 10800)),
                              wfams=os.environ.get("SP_CHANGED_WFAMS") or None, avoid=avoid, base_has=a.base_has)


def agent_slot(a):
    """10 Nov (owner: more parallel ship tests; Builder: one agent ran 8 local stylepanels at ~1.5 GB each, 10 GB of HOST): a stylepanel
    that is NOT a shipcheck leg (no --parent) waits until fewer than SP_AGENT_MAX (2) such stylepanels of the same agent (bNNNN in its bot
    names) run. Shipcheck legs never wait. SP_AGENT_MAX=0: no cap."""
    if getattr(a, "parent", None) or "--parent" in sys.argv:
        return
    cap = int(os.environ.get("SP_AGENT_MAX", "2"))
    m = re.search(r"_(b\d{4})", f"{a.cand} {a.live}")
    if cap <= 0 or not m:
        return
    who, me, t0, said = m.group(1), os.getpid(), time.time(), 0.0
    while True:
        n = 0
        for p in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                pid = int(p.split("/")[2])
                if pid >= me:  # only earlier starters count, so two that start together never both wait
                    continue
                c = open(p).read().split("\0")
            except (OSError, ValueError):
                continue
            if any(x.endswith("stylepanel.py") for x in c) and "--parent" not in c and any(f"_{who}_" in x or x.endswith(f"_{who}") for x in c):
                n += 1
        if n < cap:
            return
        if time.time() - said > 300:
            say(f"waiting: {n} stylepanels of {who} already run locally (SP_AGENT_MAX {cap}; ~1.5 GB each on HOST)")
            said = time.time()
        if time.time() - t0 > int(os.environ.get("SP_AGENT_WAIT", 7200)):
            sys.exit(f"stylepanel: {who} still has {n} local stylepanels after {int(time.time() - t0)} s; nothing played")
        time.sleep(20)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == "--pl-run":
        return pl_run(*sys.argv[2:6])
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("live")
    ap.add_argument("tag")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--panel")
    ap.add_argument("--panel-add", default=os.environ.get("SP_PANEL_ADD", ""), help="comma list of extra panel bots (e.g. the OPTIONAL spars) after the default or --panel list")
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--read-only", action="store_true")
    ap.add_argument("--keep-maps", action="store_true")
    ap.add_argument("--fresh-only", action="store_true")
    ap.add_argument("--fresh-min", type=float, default=None, help="FRESH also FAILs below this pooled score (shipcheck FRESH DECIDES: 0.50)")
    ap.add_argument("--reuse-fresh", default=None, help="'auto': adopt a REUSABLE fresh read of the same two sources (gate.py)")
    ap.add_argument("--fresh-first", action="store_true", help="the panel plays only after the fresh read: a FAIL there plays no panel (gate.py; a panel leg is 1,190 games)")
    ap.add_argument("--panel-n", type=int, default=0, help="panel legs play only the first this many of the fresh maps (2 Nov: fresh 1,200, panel 600; a leg is 2 games a map)")
    ap.add_argument("--parent", type=int, help="stop every leg when this process (the calling shipcheck) is gone")
    ap.add_argument("--changed", type=int, default=0, help="N: play only N new maps where the games of a rare flip differ from BASE's (tools/lab/changedprobe.py: full games, both seats, "
                    "identical replays dropped); the CHANGED block gives the changed share, unchanged count, targeted share and implied whole-pool effect. SP_CHANGED_MAX, SP_CHANGED_WALL, SP_CHANGED_WFAMS")
    ap.add_argument("--base-has", default=os.environ.get("SP_BASE_HAS") or None, help="with --draft-changed or --changed: draw from tools/lab/draftstock.py's map stock and probe only maps whose stored BASE lineup / labels "
                    "pass this filter (e.g. ryth, ryth,prism+team=T4/T5); a probe also plays ~300 maps outside it and is INCONCLUSIVE when coverage is under .95. Env SP_BASE_HAS (shipcheck's marker BASEHAS)")
    ap.add_argument("--draft-changed", type=int, default=0, help="N: play only N new maps where CAND's champion picks differ from LIVE's, "
                    "N/2 weird and N/2 std (tools/lab/draftprobe.py; 1-round probes first); the DRAFT block gives the firing share and implied whole-pool effect")
    ap.add_argument("--panel-shared", default=os.environ.get("SP_PANEL_SHARED", ""), help="LIVEBOT: the panel plays on one map set per live "
                    "version, and its base side is LIVEBOT's games there, played once and reused by every check on that live (owner 7 Nov). "
                    "Not with --changed / --draft-changed (their panel stays on their own maps), nor when a reused gate read brought its panel")
    ap.add_argument("--resume", action="store_true", help="play only legs that returned under 90%% of their maps, on the same maps (inforead resume)")
    ap.add_argument("--class", dest="cls", default=os.environ.get("SP_CLASS") or None, help="NAME:OPvalue (e.g. heavy_ge:>=0.5; tools/lab/mapclass.py; "
                    "env SP_CLASS): every fresh set this run draws holds only maps of that class (stratmaps --class), so the FRESH rows mean class maps; "
                    "no shared panel set; a reused gate read must have the same class. Not with --changed / --draft-changed (their probes draw their own maps)")
    ap.add_argument("--class-tag", default=os.environ.get("SP_CLASS_TAG", "heavy_ge"), help="comma list of classes whose values go into each drawn "
                    "map's otf.json entry (default SP_CLASS_TAG or heavy_ge; 'none' = off); the FRESH CLASS line bins the fresh scores by them")
    a = ap.parse_args()
    if a.panel and a.fresh_only:  # 13 Nov (b2401: --panel FOE --fresh-only played no panel leg, "panel 0 bots"): an explicit --panel wins
        print("stylepanel: --fresh-only ignored because --panel was given (the panel legs play)", flush=True)
        a.fresh_only = False
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mapclass
    CLS_TAG[:] = [x for x in (a.class_tag or "").split(",") if x and x != "none" and x in mapclass.CLASSES]
    if a.cls:
        mapclass.parse(a.cls)  # exits on a bad condition before anything plays
        CLS_COND[0] = a.cls
        CLS_ARGS[:] = ["--class", a.cls] + (["--class-tag", ",".join(CLS_TAG)] if CLS_TAG else [])
    if os.environ.get("SP_WFAMS"):  # 11 Nov: a family-only fresh draw (shipcheck's w_manygrp fuel row): stratmaps --wfams FAMS --weird 1
        CLS_ARGS[:] = CLS_ARGS + ["--wfams", os.environ["SP_WFAMS"], "--weird", "1"]
    agent_slot(a)
    mdir = f"{PANEL_DIR}/{a.tag}"
    panel = [] if a.fresh_only else (a.panel.split(",") if a.panel else list(PANEL))
    if not a.fresh_only:
        panel += [p for p in a.panel_add.split(",") if p and p not in panel]
        # 12 Nov ~20:4xZ (owner via the Coordinator: nova_spar_prism "yes, add it" on the condition "PVF shows Prism-in beating live"; PVF read
        # D = -.040, so INFORMATION ONLY for now): SP_PANEL_INFO spars play every panel and print a row marked [info], but stay OUT of the
        # pooled panel bar, the negative-bot flags and the legs-returned count. It becomes a blocking row only after a Prism-in line passes.
        INFO_SPARS[:] = [p for p in os.environ.get("SP_PANEL_INFO", "nova_spar_prism").split(",") if p and p not in panel]
        panel += INFO_SPARS
    have = [p for p in panel if os.path.isdir(f"{REPO}/bots/{p}/src")]
    skipped = [p for p in panel if p not in have]
    if not have and not a.panel and not a.fresh_only:  # every default opponent is gone (owner 8 Nov): FRESH only, PANEL reads SKIPPED
        a.fresh_only = True
    shared = a.panel_shared if a.panel_shared and not a.fresh_only and not a.changed and not a.draft_changed and have and not a.cls else ""  # --class: the panel's own legs on the class maps
    if shared and a.reuse_fresh and not a.read_only and not os.path.exists(f"{mdir}/otf.json"):
        try:  # a gate read that will be adopted brings its own panel legs on its own maps: keep that cheaper path
            if any(os.path.exists(f"{PANEL_DIR}/{os.path.basename(os.path.dirname(r))}/panel.json")
                   for r in glob.glob(f"{PANEL_DIR}/*/REUSABLE") if json.load(open(os.path.join(os.path.dirname(r), "hashes.json"))).get("hc") == src_hash(a.cand)):
                shared = ""
        except (OSError, ValueError):
            pass
    plname = (lambda i, p: pls_name(shared, p, a.panel_n or a.n)) if shared else (lambda i, p: f"pl{a.tag}_{i}")
    plbot = shared or a.live
    legs = [(f"fp{a.tag}", a.cand, a.live)]
    for i, p in enumerate(have):
        legs += [(f"pc{a.tag}_{i}", a.cand, p), (plname(i, p), plbot, p)]
    legs_all = list(legs)
    t0 = time.time()
    reused = None
    if a.reuse_fresh and not a.changed and not a.read_only and not os.path.exists(f"{mdir}/otf.json"):  # --changed: a plain read's maps would fill the probe and dilute the read it exists for
        reused = adopt_fresh(a, mdir, a.n)
        if reused:
            adopt_second(a, reused)
            done = set() if shared else adopt_panel(a, reused, have, len(json.load(open(f"{mdir}/otf.json"))["maps"]))  # shared: the panel plays on the per-live set
            legs = [x for x in legs if x[0] != f"fp{a.tag}" and x[0] not in done]
            say(f"fresh leg reused from {reused} (same source hashes), and {len(done)} panel legs: {len(legs)} legs play")

    if a.resume and os.path.exists(f"{mdir}/otf.json"):
        short = set(short_legs(a, mdir, legs_all))
        legs = [x for x in legs if x[0] in short]
        say(f"resume: {len(legs)} of {len(legs_all)} legs short: {', '.join(x[0] for x in legs) or 'none'}")
        if f"fp{a.tag}" in short and os.path.exists(f"{mdir}/fp_games.jsonl"):  # its games are appended again
            os.remove(f"{mdir}/fp_games.jsonl")
    mdir2, fp2, second_failed, record, logged = f"{PANEL_DIR}/{a.tag}_r", f"fp{a.tag}_r", [], {}, []

    def log_flags():
        if logged or not record.get("flags") and not record.get("kinds"):
            return
        logged.append(1)
        with open(SECOND_LOG, "a") as f:
            f.write(json.dumps(dict(record, time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tag=a.tag, cand=a.cand, live=a.live,
                                    hc=src_hash(a.cand), hl=src_hash(a.live))) + "\n")

    def summarize(note=""):
        """Read every leg that has a summary and write BQ/sp<TAG>.txt; note marks a PARTIAL read (1 Nov: a stopped or timed-out
        panel wrote nothing, and shipcheck read 'no result'). Legs never finished read as empty (n 0)."""
        meta = json.load(open(f"{mdir}/otf.json"))
        lab = {m["name"]: m.get("labels", {}) for m in meta["maps"]}
        L = [f"# stylepanel {a.tag}: {a.cand} vs live {a.live}, {len(meta['maps'])} new maps ({meta.get('tag')}, {meta.get('made')}"
             + (f"; fresh read reused from {meta['reused_from']}" if meta.get("reused_from") else "") + "), "
             f"panel {len(have)} bots, wall {(time.time() - t0) / 60:.0f} min" + (f" | {note}" if note else ""), ""]
        # FRESH
        fs = map_score(f"fp{a.tag}", a.cand)
        if len(fs) < 0.95 * max(1, len(meta["maps"])):  # 3 Nov (b935): the first set had no completeness check; the same 95% rule as the second's
            L.append(f"first set incomplete: {len(fs)} of {len(meta['maps'])} maps returned; the fresh read counts none of them")
            fs = {}
        fs2, state, labs = None, "", dict(lab)
        if os.path.exists(f"{mdir2}/otf.json"):
            meta2 = json.load(open(f"{mdir2}/otf.json"))
            labs.update({m["name"]: m.get("labels", {}) for m in meta2["maps"]})
            fs2 = map_score(f"fp{a.tag}_r", a.cand)
            state = "done" if len(fs2) >= 0.95 * max(1, len(meta2["maps"])) else "not finished"
            if state != "done":
                fs2 = None  # the partial set counts for nothing: the row is INCONCLUSIVE
        elif second_failed:
            state = second_failed[0]
        fv, lines, rec = fresh_block(fs, fs2, labs, KIND_Z, a.fresh_min, state)
        if CLS_LATE and not CLS_COND[0] and not note:  # 11 Nov: read whatever the background thread tagged so far; never wait
            meta = json.load(open(f"{mdir}/otf.json"))
            if fs2:
                meta2 = json.load(open(f"{mdir2}/otf.json"))
        cv = {m["name"]: m["class"] for m in meta["maps"] if m.get("class")}
        if fs2:
            cv.update({m["name"]: m["class"] for m in meta2["maps"] if m.get("class")})
        cl = class_line(dict(fs, **(fs2 or {})), cv)
        if not note:
            class_tsv(a.tag, a.cand, a.live, dict(fs, **(fs2 or {})), cv)
        if cl:
            lines = [lines[0], cl, *lines[1:]]
        L += lines
        record.clear()
        record.update(rec)
        # PANEL
        per_map = collections.defaultdict(list)
        prow, pbad = [], []
        nread = 0
        for i, p in enumerate(have):
            sc = map_score(f"pc{a.tag}_{i}", a.cand)
            sl = map_score(plname(i, p), plbot)
            common = sorted(set(sc) & set(sl))
            d = [sc[x] - sl[x] for x in common]
            dm, dse, dn = ci(d)
            if p in INFO_SPARS:  # information only: printed, never pooled or flagged
                cs = sum(sc[x] for x in common) / max(1, len(common))
                ls = sum(sl[x] for x in common) / max(1, len(common))
                z = dm / dse if dse and dse > 0 else 0.0
                prow.append(f"  {p:22s} n {dn:3d}  CAND {cs:.3f}  LIVE {ls:.3f}  D {dm:+.3f} [{dm - 1.96 * dse:+.3f}, {dm + 1.96 * dse:+.3f}]  z {z:+.1f}"
                            "  [info: not in the panel bar]")
                continue
            for x in common:
                per_map[x].append(sc[x] - sl[x])
            nread += 1 if dn > 0 else 0  # 2 Nov (b849): a refused leg read as a bot of the panel, and the panel could PASS without it
            z = dm / dse if dse and dse > 0 else 0.0
            flag = dn >= 10 and z <= -BOT_Z
            pbad += [p] if flag else []
            cs = sum(sc[x] for x in common) / max(1, len(common))
            ls = sum(sl[x] for x in common) / max(1, len(common))
            prow.append(f"  {p:22s} n {dn:3d}  CAND {cs:.3f}  LIVE {ls:.3f}  D {dm:+.3f} [{dm - 1.96 * dse:+.3f}, {dm + 1.96 * dse:+.3f}]  z {z:+.1f}"
                        + ("  << significantly negative" if flag else ""))
        pd = [sum(v) / len(v) for v in per_map.values()]
        pm, pse, pn = ci(pd)
        phi = pm + 1.96 * pse if pn > 1 else float("nan")
        have_bar = [p for p in have if p not in INFO_SPARS]
        pv = "SKIPPED" if a.fresh_only else "INCONCLUSIVE" if pn < 20 or not have_bar or nread < len(have_bar) else ("FAIL" if phi < 0 or pbad else "PASS")
        L += [f"PANEL: {pv}  pooled D {pm:+.3f} [{pm - 1.96 * pse:+.3f}, {phi:+.3f}] over {pn} maps x {nread} bots" + (f" ({len(have_bar) - nread} of {len(have_bar)} legs returned nothing)" if nread < len(have_bar) else "") + "; "
              f"bar: pooled CI upper >= 0 and no bot z <= -{BOT_Z:g}" + (f"; negative bots: {', '.join(pbad)}" if pbad else ""),
              *prow] + ([f"  skipped (not built): {', '.join(skipped)}"] if skipped else []) + [""]
        if os.path.exists(f"{mdir}/changed.json"):  # 7 Nov (owner): a rare change, read only where it changes the game
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import changedprobe
            cs = changedprobe.summary(json.load(open(f"{mdir}/changed.json")), meta)
            L += ["CHANGED-MAP READ: only maps where the two seats' games differ (every other map is the base mirror game and reads exactly .500)"]
            L += ["  " + x for x in changedprobe.report(cs)]
            fm = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) ", "\n".join(L), re.M)
            if fm and cs["kept_score"] is not None and abs(float(fm.group(1)) - cs["kept_score"]) > 0.0015:
                L.append(f"  WARNING: the replayed read {fm.group(1)} is not the probe's {cs['kept_score']:.3f} on the same maps: the games should be identical")
            if pn and not cs["targeted"]["probed"]:
                L.append(f"  rough whole-pool third-party D = share x D = {cs['share'] * pm:+.4f} [{cs['share'] * (pm - 1.96 * pse):+.4f}, {cs['share'] * phi:+.4f}] "
                         "(not exact: the maps were picked by CAND v BASE; against another bot the change can fire on other maps too)")
            L.append("")
        if os.path.exists(f"{mdir}/probe.json"):  # 4 Nov (owner): a draft-changed read
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import draftprobe
            ds = draftprobe.summary(json.load(open(f"{mdir}/probe.json")), meta)
            ps = ds["pool_share"]
            L += ["DRAFT-CHANGED READ: only maps where CAND's picks differ from LIVE's in a seat (unchanged maps play identical games)"]
            L += ["  " + x for x in draftprobe.report(ds)]
            fm = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\]", "\n".join(L), re.M)
            if fm:
                v = [float(x) - 0.5 for x in fm.groups()]
                L.append(f"  implied whole-pool h2h effect = firing share x (changed-map score - .5) = {ps * v[0]:+.4f} [{ps * v[1]:+.4f}, {ps * v[2]:+.4f}]"
                         f" (score {fm.group(1)}, share {100 * ps:.1f}%; the share's own error not included)")
            if pn:
                L.append(f"  implied whole-pool third-party D = share x D = {ps * pm:+.4f} [{ps * (pm - 1.96 * pse):+.4f}, {ps * phi:+.4f}]")
            L.append("")
        L.append(f"maps: {mdir}/otf.json (seeds, recipes, labels); legs: fp{a.tag}, pc{a.tag}_K / "
                 + (f"{pls_name(shared, 'SPAR')[:-6]}_* ({shared} on the shared per-live set {PANEL_DIR}/shared_{shared}_*)" if shared else f"pl{a.tag}_K") + f" in {BQ}")
        txt = "\n".join(L) + "\n"
        open(f"{BQ}/sp{a.tag}.txt.part", "w").write(txt)
        os.replace(f"{BQ}/sp{a.tag}.txt.part", f"{BQ}/sp{a.tag}.txt")
        return fv
        print(txt)
    if not a.read_only:
        os.makedirs(PANEL_DIR, exist_ok=True)
        if not os.path.exists(EMPTY):
            open(EMPTY, "w").close()
        if a.changed and not (json.load(open(f"{mdir}/changed.json")).get("done") if os.path.exists(f"{mdir}/changed.json") else False):
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import changedprobe
            say(f"changed probe: up to {a.changed} maps where the games differ")
            cs = changed_build(a, mdir, a.tag)
            say(changedprobe.report(cs)[0])
            if cs.get("inconclusive"):  # 8 Nov: a stock filter that misses changed maps must not read a narrower population
                say(f"CHANGED: INCONCLUSIVE ({cs['inconclusive']})")
                sys.exit(2)
            if os.environ.get("CP_RAREBANK") and not cs.get("not_rare") and json.load(open(f"{mdir}/changed.json")).get("bank_short") and cs["kept"] < a.changed:
                # 11 Nov (owner: rare reads on banked maps): the bank ran out before N changed maps: keep the probe, back to waiting (shipcheck: BANKWAIT)
                import rarebank
                k, pr, shr = rarebank.save_resume(mdir, a.tag, a.cand, a.live)
                say(f"RARE BANK SHORT: {k} of {a.changed} changed maps after {pr} bank maps (changed share {100 * shr:.1f}%); probe saved for a resume")
                sys.exit(4)
            if not cs["kept"] or cs.get("not_rare"):
                sys.exit("changed probe: " + (cs.get("stopped") or "no changed maps (nothing to play)"))
        if a.draft_changed and not (json.load(open(f"{mdir}/probe.json")).get("done") if os.path.exists(f"{mdir}/probe.json") else False):
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import draftprobe
            say(f"draft probe: up to {a.draft_changed} maps where the picks differ")
            ds = draftprobe.build(a.cand, a.live, mdir, a.draft_changed, a.tag, max_probe=int(os.environ.get("SP_DRAFT_MAX", 40000)), wall=int(os.environ.get("SP_DRAFT_WALL", 14400)), base_has=a.base_has)
            say(draftprobe.report(ds)[0])
            if ds.get("inconclusive"):  # 7 Nov (Builder): a too-rare draft change reads INCONCLUSIVE, not a 40k-map hunt
                say(f"DRAFT: INCONCLUSIVE ({ds['inconclusive']})")
                sys.exit(2)
            if not ds["kept"]:
                sys.exit("draft probe: no changed maps (nothing to play)")
        if os.environ.get("SP_CLASSBANK") and not os.path.exists(f"{mdir}/otf.json") and not a.draft_changed and not a.changed:
            if not classbank_slice(mdir, a.n, a.tag):
                sys.exit(f"class bank short for {a.tag}: no fresh maps drawn (SP_CLASSBANK={os.environ.get('SP_CLASSBANK')})")
            tag_maps(mdir)
        if not os.path.exists(f"{mdir}/otf.json") and not a.draft_changed and not a.changed and shared_fresh_slice(mdir, a.n, a.tag, a.live):
            tag_maps(mdir)
        if not os.path.exists(f"{mdir}/otf.json"):
            say(f"generating {a.n} maps into {mdir}")
            # 1 Nov (owner: faster iterations): unseen pre-generated sets from tools/lab/freshpool.py (single use), else generated here
            r = subprocess.run(["python3", "-I", "tools/lab/stratmaps.py", mdir, "--n", str(a.n), "--take", "--who", f"stylepanel:{a.tag}", *CLS_ARGS],
                               cwd=REPO, capture_output=True, text=True)
            say(strat_say(r))
            if r.returncode != 0:
                sys.exit(f"stratmaps failed: {r.stderr[-400:]}")
            tag_maps(mdir)
        late_tag(mdir)
        if a.keep_maps:
            json.dump({p: dict(i=i, hash=src_hash(p)) for i, p in enumerate(have)}, open(f"{mdir}/panel.json", "w"))
        pdir = mdir
        if shared:
            pdir = shared_set(shared, a.panel_n or a.n)
            if pdir is None:
                sys.exit("stylepanel: the shared panel set could not be drawn")
            say(f"panel on the shared set {pdir}: base side {shared}, played once per live version")
        elif a.panel_n and have:  # a dir of its own, as condab reads every map of an OTF dir
            meta = json.load(open(f"{mdir}/otf.json"))
            if len(meta["maps"]) > a.panel_n:
                pdir = f"{mdir}/panelmaps"
                os.makedirs(pdir, exist_ok=True)
                for m in meta["maps"][:a.panel_n]:
                    if not os.path.exists(f"{pdir}/{m['name']}.map26a"):
                        os.link(f"{mdir}/{m['name']}.map26a", f"{pdir}/{m['name']}.map26a")
                json.dump(dict(meta, maps=meta["maps"][:a.panel_n]), open(f"{pdir}/otf.json", "w"))
        todo, run = list(legs), []

        def stop_all(why):  # 1 Nov: a stopped shipcheck left its panel's legs playing for a cancelled check
            say(f"stopping: {why}")
            for _, q in run:
                if q.poll() is None:
                    q.terminate()  # condab removes its own Condor cluster on SIGTERM
            for _, q in run:
                try:
                    q.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    q.kill()
            try:
                summarize(f"PARTIAL ({why}; {len(legs) - len(todo) - len(run)} of {len(legs)} legs finished)")
                log_flags()
            except Exception as e:  # noqa: BLE001  (the partial read must not hide the stop)
                say(f"partial summary failed: {e}")
            sys.exit(143)
        # 13 Nov (TB; Builder/Coordinator read 14021's 'PARTIAL (SIGTERM ...)' as a killed check): when the parent shipcheck stopped this panel because
        # another row already FAILED (its CONDAB_STOPFILE exists), say so: the check's verdict is that row's, not a harness kill
        def _term_why():
            sf = os.environ.get("CONDAB_STOPFILE", "")
            return "stopped by its shipcheck: another row FAILED first (verdict stands)" if sf and os.path.exists(sf) else "SIGTERM"
        signal.signal(signal.SIGTERM, lambda *_: stop_all(_term_why()))

        def start_second():
            """A kind flagged on a first read that passes its other bars: one more set of the same size, on new maps, ahead of the panel legs still to start."""
            if os.path.exists(f"{mdir2}/otf.json"):
                return
            fs = map_score(f"fp{a.tag}", a.cand)
            lab = {m["name"]: m.get("labels", {}) for m in json.load(open(f"{mdir}/otf.json"))["maps"]}
            flags = first_flags(fs, lab, KIND_Z)
            mm, se, n = ci(list(fs.values()))
            if not flags or n < 20 or mm + 1.96 * se < 0.5 or (a.fresh_min is not None and mm < a.fresh_min):
                return
            say(f"kinds flagged on the first read: {', '.join(f'{d}={lv}' for d, lv in flags)}: second read of {a.n} new maps")
            if a.changed:  # the second set is changed maps too, never the first set's
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import changedprobe
                cs = changed_build(a, mdir2, f"{a.tag}r", avoid=(mdir,))
                say("second set: " + changedprobe.report(cs)[0])
                r = subprocess.CompletedProcess([], 0 if cs["kept"] and not cs.get("inconclusive") else 1)
            elif a.draft_changed:  # the second set is draft-changed maps too (draftprobe), else it reads unchanged games
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import draftprobe
                ds = draftprobe.build(a.cand, a.live, mdir2, a.draft_changed, f"{a.tag}r", max_probe=int(os.environ.get("SP_DRAFT_MAX", 40000)), wall=int(os.environ.get("SP_DRAFT_WALL", 14400)), avoid=[mdir], base_has=a.base_has)  # never the first read's probe or maps (5 Nov, 1430)
                say("second set: " + draftprobe.report(ds)[0])
                r = subprocess.CompletedProcess([], 0 if ds["kept"] and not ds.get("inconclusive") else 1)
            else:
                r = subprocess.run(["python3", "-I", "tools/lab/stratmaps.py", mdir2, "--n", str(a.n), "--take", "--who", f"stylepanel:{a.tag}_r", *CLS_ARGS],
                                   cwd=REPO, capture_output=True, text=True)
                say(strat_say(r))
                if r.returncode == 0:
                    tag_maps(mdir2)
                    late_tag(mdir2)
            if r.returncode != 0:
                second_failed.append("failed: no maps")
                return
            second_ready.append((fp2, a.cand, a.live))

        # 4 Nov (iterspeed report): the second set's maps (stratmaps --take, or a draft probe for hours) are made in a thread; the leg
        # loop keeps launching and reaping legs meanwhile (it froze), and queues the second fresh leg first when its maps are ready
        import threading
        second_ready, second_thr = [], []

        def second_async():
            if not second_thr:
                second_thr.append(threading.Thread(target=start_second, daemon=True))
                second_thr[0].start()

        def second_pending():
            return bool(second_thr) and second_thr[0].is_alive()

        if reused:
            second_async()
        while todo or run or second_pending() or second_ready:
            while second_ready:
                todo.insert(0, second_ready.pop())
            if a.parent and not os.path.exists(f"/proc/{a.parent}"):
                stop_all(f"parent {a.parent} is gone")
            if a.fresh_first and todo and not second_pending() and not any(nm in (f"fp{a.tag}", fp2) for nm, _ in run) and todo[0][0] not in (f"fp{a.tag}", fp2):
                fresh_read = summarize()  # the fresh read, with its second set if it had one, is complete
                a.fresh_first = False
                if fresh_read == "FAIL":
                    say(f"fresh FAIL: {len(todo)} panel legs not played")
                    todo.clear()
                    continue
            while todo and len(run) < min(a.par, load_par()) and not (a.fresh_first and todo[0][0] not in (f"fp{a.tag}", fp2)):  # 1 Nov: fewer legs at once when the machine is loaded
                nm, x, y = todo.pop(0)
                run.append((nm, leg(nm, x, y, mdir2 if nm == fp2 else mdir if nm == f"fp{a.tag}" else pdir, f"{mdir}/fp_games.jsonl" if nm in (f"fp{a.tag}", fp2) else None,
                                games=None if nm in (f"fp{a.tag}", fp2) else f"{pdir}/{nm}_games.jsonl")))
                say(f"leg {nm}: {x} vs {y}")
            time.sleep(15)
            for nm, p in list(run):
                if p.poll() is not None:
                    run.remove((nm, p))
                    say(f"leg {nm} done (rc {p.returncode})")
                    if nm == f"fp{a.tag}":
                        second_async()
        if pdir != mdir and not shared:
            shutil.rmtree(pdir, ignore_errors=True)
        short = short_legs(a, mdir, legs_all)
        if short:  # 3 Nov (irb1030): the maps stay until the read is whole, so a resume can finish it; otf.json can rebuild them too
            say(f"PARTIAL: {', '.join(short)} returned under 90% of their maps: maps kept in {mdir} for a resume")
            open(f"{mdir}/INCOMPLETE", "w").write("\n".join(short) + "\n")
        elif not a.keep_maps:
            if os.path.exists(f"{mdir}/INCOMPLETE"):
                os.remove(f"{mdir}/INCOMPLETE")
            late_join(0)  # 11 Nov: never wait on the class tags (they held finished checks for minutes); untagged maps just have no bin
            try:  # 11 Nov (owner): maps of a finished common read that fit a waiting rare line go to its bank first (hard links; bq/rarebank_ON)
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import rarebank
                rarebank.hook_dir(mdir)
                if os.path.isdir(mdir2):
                    rarebank.hook_dir(mdir2)
            except Exception:  # noqa: BLE001  never break a read
                pass
            for f in os.listdir(mdir):
                if f.endswith(".map26a"):
                    os.remove(os.path.join(mdir, f))
        if os.path.isdir(mdir2):  # no panel leg ever plays on the second set
            for f in os.listdir(mdir2):
                if f.endswith(".map26a"):
                    os.remove(os.path.join(mdir2, f))
    fv = summarize()
    if not a.read_only:
        log_flags()
    if a.keep_maps and fv in ("PASS", "FAIL") and not os.path.exists(f"{mdir}/REUSED_BY_{a.tag}"):
        import abindex
        json.dump(dict(cand=a.cand, live=a.live, hc=src_hash(a.cand), hl=src_hash(a.live), cli=abindex.cli_version()), open(f"{mdir}/hashes.json", "w"))
        open(f"{mdir}/REUSABLE", "w").close()  # a complete fresh read: shipcheck's stylepanel --reuse-fresh auto may adopt it
    return 0


if __name__ == "__main__":
    sys.exit(main())
