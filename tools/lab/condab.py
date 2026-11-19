#!/usr/bin/env python3
"""Condor fan-out of a bot A/B: the games of abl.sh + sprt.py + heldout.sh, played on the DoC Condor pool.

usage: sh tools/lab/condab.sh CAND BASE NAME [SET]          (from /homes/USER/cambc; blocks until done)
  CAND, BASE: bots under bots/ (current source). NAME: a plain run name ([A-Za-z0-9._+-]).
  SET: all (default) = pool + fresh + heldout; pool = abl.sh's default list (89 maps); fresh = sprt.py's decision maps
       (gen_s_001..400 with every tenth map a gen_c/gen_p map, as sprt.py orders them); heldout = gen_01..45
       (heldout.sh) + /data/USER/st/fl/fb2/heldout.txt (gen_ux 17 + gen_u 40); or a file with one map per line.
  Both seats on every map. A game the index already has (tools/lab/abindex.py: any abl.sh, sprt.py, heldout.sh run or an
  earlier condab batch between the same two source versions) is reused, not replayed. CONDAB_FORCE=1 replays them anyway
  (a determinism check: Index.conflicts counts any game whose two copies disagree).
  Results land as an abl.sh-format run /data/USER/abl/cq_NAME_K (manifest.txt, games.jsonl, cli.txt), so abstat.py
  pools them with the local games and sprt.py reuses them. Summary: /data/USER/st/bq/NAME.condor.txt (abstat.py's
  per-family map-pair scores with 95% CIs on the SET's maps, bot faults and fuel exhaustions per side, games played vs
  reused, wall time).
  Condor batch: /homes/USER/condor-runs/cq_NAME_K (moved to /data/USER/condor_runs_archive when collected), one job
  per 24 games, 12 at a time, runner tools/lab/condab_node.sh. Bots and maps are synced into condor-work/proj400 as
  tools/lab/tourney.py does (same lock). KEEP=1 (or --keep) also keeps every game's replay and statistics in the run dir
  (cq_NAME_K/rep/ID.repl26a, st/ID.json: the layout of KEEP=1 abl.sh and restat.py --keep, read by replay.py and
  econrace.py; about 0.1 MB + 1.1 MB per game, on /data only). With KEEP=1 a cached game counts as reused only if some
  run on this machine kept its replay; a game cached without one is played again on Condor (deterministic: the same
  game, now with its replay). The summary lists the run dirs that hold the SET's replays, for
  `econrace.py jackpot --pair CAND BASE RUNDIR...`. CONDAB_TIMEOUT (s, default 7200) bounds the wait; if 90% of the jobs are done
  and the rest make no progress for 10 min, the stragglers are removed and their games are left for a re-run.
INTERIM looks at 50, 60, 70, 75, 80 and 90% of the jobs: the paired map score so far (complete map pairs only, 95% CI as
  abstat.py), maps done per family, and DECIDED FAIL / PASS for the bar ALL < 0.48 = fail, ALL > 0.53 = pass, by either
  (a) the deterministic bound: no outcome of the unplayed map pairs can move the final pooled score across the bar, or
  (b) the projected final score: cached pairs + the unplayed pairs' mean estimated from the returned ones, with a
      finite-population standard error and an O'Brien-Fleming boundary z = 2.6 / sqrt(t), t = share of the unplayed
      pairs returned (z 3.68 at 50%, 3.00 at 75%, 2.74 at 90%; at least 30 returned pairs). Checked offline on 236
      finished condab batches (tools: /data/USER/tooler/condab_sim.py): decides early in about 30% of runs, never
      against the full run's verdict in 12,272 simulated return orders; 0.4-0.6% wrong decisions when the final score
      sits right at a bar.
  Jobs hold a family-balanced pseudo-random set of maps (fixed hash order, both seats of a map in the same job), so the
  first jobs back are not one family; caching is by bot source and map hash, so the order changes nothing there.
  STOP=1 (or CONDAB_STOP=1): once DECIDED, condor_rm this batch's own cluster (the id recorded at submit) and summarise
  what returned; the summary says "stopped early at N% (decided FAIL/PASS)". The unplayed games are left for a re-run.
STOP_REF=RUNDIR (a run name under /data/USER/abl, e.g. cq_nd130_1, or a path): FAIL-only early stop on the paired
  difference D = CAND's map-pair score - the reference bot's score in RUNDIR against the same opponent (BASE), per map, on
  the maps both have complete, exactly as pair_d.py pairs them (its scores(), fam() and boot() are loaded from
  /data/USER/st/b86dg/py/pair_d.py, never copied). Each look adds a "paired D" line; once the boundary-corrected upper
  bound of the projected final D is below 0 (deterministic: even all unplayed maps won by CAND on both seats keep D < 0;
  or projected D + z * finite-population se < 0 with z = 2.6 / sqrt(t), t = share of the batch's maps that the reference
  also has returned, at least 30), the batch's own cluster is removed. No early PASS. The summary ends with pair_d's
  per-family D lines.
OTF (on by default; OTF=0 turns it off; owner 29 Oct: "add 5 unseen maps generated on the fly and never saved, so we do
  not overfit", "a spread of pathological and normal"): each batch also plays both seats on 5 maps generated for it from
  os.urandom seeds: 3 normal genmaps.py maps, one each of size S, M and L (other recipe columns random), and 2
  pathological maps of two different types (genbig.py's gen_p recipes, the generator behind genpatho). Every map passes
  genmaps' validate(), the decode check of build_and_check(), mapcheck.py's audit and genmaps.strict_checks(); a failing
  map gets a new seed (40 per recipe; normal: up to 3 recipes of the same size; patho: then another unused pathology
  type, logged as a fallback); a slot that still fails is dropped and logged. The maps live in
  /data/USER/otf_tmp/<NAME_tag> and, for the Condor jobs, as copies in the batch dir's otf/ (the jobs' own input, not
  proj400/maps); every file is deleted (exact list, never a glob) when the summary is written, on an early stop and on
  errors. Their games are never in games.jsonl, the index, abstat or sprt; the summary keeps the results and each map's
  seed and recipe (`condab.py --otf-regen SEED 'RECIPE' OUT.map26a` rebuilds one). OTF_DIR=DIR uses the maps of
  `condab.py --otf-gen [DIR]` instead (scr.sh: the same 5 maps for both legs), and never deletes them
  (`condab.py --otf-clean DIR` does). With STOP_REF the reference bot plays them against BASE too, for a paired D.
  The interim looks ignore them.
OTF_DOM=K (default 0): K more on-the-fly maps per batch from tools/lab/gendom.py's dominant-structure recipes ('single'
  kind, fresh os.urandom seeds), rejection-sampled until the b151 trigger holds: /data/USER/st/bq/dg151/py/dctrig.py's
  trig() (loaded, never copied; DC_MODE=x: the largest non-monolith group holds >= 35% of the non-monolith camp gems and
  >= 3x the next non-monolith group) plus >= 30 gems in that group. At most OTF_DOM_TRIES (150) attempts per map, a new
  recipe every 10; a slot that never triggers is dropped and its failure counts are logged. Same never-saved handling,
  OTF_DIR sharing and reference games; reported on their own "otf dom K" line, outside ALL and outside the 5-map lines.
OTF_RULE=path/module.py:func OTF_RULE_K=K (default K 5): K more on-the-fly maps on which func(path) is true. func gets the path
  of a freshly built .map26a and returns a bool or (bool, info dict). The module is loaded like pair_d.py: its imports,
  functions, classes and UPPERCASE constants only, so its command line never runs. Recipes are drawn from the normal
  (genmaps), pathological (genbig gen_p) and gendom mix, a new recipe every 5 seeds, with fresh os.urandom seeds, until func
  holds: at most OTF_RULE_TRIES (300) draws per map, misses counted and logged. Same never-saved handling, OTF_DIR sharing and
  reference games; reported as "otf rule NAME K" with its own paired D. OTF_GEMCLU=K is OTF_RULE for b168's GEM_TILT_CLU
  rule (/data/USER/tooler/rules/gemclu.py:gemclu: >= 4 walkable pure gem-cluster groups <= 25 gems and >= 2 walkable
  gold-only groups <= 60 gold; ~6% of fresh maps). OTF_DOM is unchanged.
  A rule module may define RECIPES (a list of gendom-style recipe dicts, built by its own functions): every draw then
  takes its recipe from that list, built with gendom.generate, instead of the normal / patho / gendom mix (for rules the
  mix almost never meets, e.g. /data/USER/tooler/rules/neartotal.py: 0 hits in 1,800 mixed draws, 29 Oct).
OTF_GAMES=FILE (1 Nov): append every OTF game's record (a, b, map, win, sa, sb with deaths, fuel ...) to FILE as JSON lines
  (10 Nov: + lu {a,b: kit per body}, cs {a,b: [kills, deaths, earnedGold, tributed] per body}, fk [round, killer label, kit,
  victim label, kit] when the stats carry kill events (CLI games; cxe has totals only); labels = replay.py's 1..6 / KLNPRS)
  (OTF games are never archived or indexed; shipcheck's death guard reads them).
CONFIRM=N (the swarm's confirm leg, a final check before a ship): `CONFIRM=100 sh tools/lab/condab.sh CAND BASE cfNNN`
  plays CAND vs BASE, both seats, on N maps generated for this batch only, with the OTF machinery: 3:2 normal :
  pathological (normal sizes cycling S/M/L, pathology types as even as possible, never the same type twice in a row of
  five), fresh os.urandom seeds, the same checks and capped regeneration. No SET maps, no OTF extras, no reference games,
  no early stop (STOP / STOP_REF are ignored). Never saved and never indexed, like the OTF maps; NAME.condor.txt holds
  "confirm N maps: ..." in abstat's ALL-line format, normal and patho sub-lines, a verdict, faults and fuel, and every
  map's seed and recipe.
SPEED (owner 29 Oct ~19:40, "our iterations are too slow"):
  - condab_node.sh caches each bot's build per Condor node (35 s of every job before; ~1 s now on a warm node).
  - Job size adapts to the pool: about 2 jobs per unclaimed >= 12-cpu slot (condor_status at submit), between 12 games a
    job (the floor: one game per core of the job's 12, so a job's fixed cost stays small next to its games) and 48;
    CONDAB_PER_JOB=N fixes it. Whole maps per job and the family-balanced order as before; at most CONDAB_CAP (400) jobs.
  - STOP=1 stops early on a FAIL only; STOP=2 (or STOP_PASS=1) also on a PASS: h2h when the projected final ALL's
    corrected lower bound is > 0.5; with STOP_REF when the projected paired D's corrected lower bound is > 0. Same OBF z.
    With STOP_REF the decision is the paired D's alone.
  - CONDAB_TIMEBOX=S: after S seconds (from the start), one last look decides on what has returned with the same rule
    (FAIL or PASS; else INCONCLUSIVE, never a pass), this batch's cluster is removed and the summary says
    "timebox at M min, N% of jobs: decided X".
  - CONDAB_HI_FAIL="BAR,Z,MIN" (shipcheck's SC_LH_EARLY, 30 Oct): one more FAIL rule at each interim look (acted on with
    STOP=1/2 like the others, and at the timebox look): once >= MIN complete map pairs are back, FAIL when their plain
    map-pair score + Z * se < BAR (se = the returned pairs' sd / sqrt(n), no finite-population term). Off when unset.
  - CONDAB_STOPFILE=PATH (shipcheck, 30 Oct): when PATH exists, the batch removes its own cluster at its next poll (every
    10-20 s; also a CONFIRM batch) and summarises what returned, "stopped early at N% of jobs (decided STOPPED ...)".
    shipcheck writes it once the live h2h leg has FAILED, so its other Condor legs stop too. Off when unset.
CONDAB_PILOT (default 1; 0 = always a normal Condor cluster), 30 Oct: when >= 1 pilot of tools/lab/pilotd.py is alive,
  the batch's parts go into the pilot queue (/homes/USER/condor-runs/pilotq) at the batch's priority instead of a new
  cluster (no queue wait); parts of 12-24 games. STOP / stop file / timebox / straggler rule cancel the batch's items (queued
  deleted, running killed); a killed condab cancels them too. No pilot alive for CONDAB_PILOT_FALLBACK s (300): the unfinished
  parts go to a normal cluster (run_fb). Every batch touches the pool's demand file, so pilotd keeps pilots while we work.
  Set runs (h2h, not CONFIRM) also print "  changed  X of Y maps" under the map pairs: maps whose two seats' games differ
  (CONFIRM's definition; 0 = CAND plays exactly like BASE on every map with both seats).
"""
import collections
import ast
import fcntl
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = "/homes/USER/cambc"
PROJ = "/homes/USER/condor-work/proj400"
OLD_RUNS = "/homes/USER/condor-runs"


def stall_tick(st, bids, queued, claimed, now):
    """Advance a pilot batch's stall clock and return its age in s. st = {"ref": start time, "seen": claimed names seen}.
    queued / claimed: names in pilotq/queue and pilotq/claimed (pilotd.parse: field 2 is the batch id). A new claim of one of
    this batch's items restarts the clock; while none is claimed and some are still queued the batch waits on the pool, and the
    clock holds at 0. Nothing claimed and nothing queued: the clock runs (nothing left that could come back)."""
    import pilotd as _pl
    bids = set(bids)
    mine = lambda names: {n for n in names if (_pl.parse(n) or (0, 0, ""))[2] in bids}
    c, qd = mine(claimed), mine(queued)
    if c - st["seen"]:
        st["seen"] |= c
        st["ref"] = now
    if not c and qd:
        st["ref"] = now
    return now - st["ref"]


def scratch(env, path):
    """2 Nov (home at 52k files, cleanup blocked): new job files and bot copies go to the shared scratch; only regenerable files, since
    results and summaries stay on /data. Falls back to the home when it cannot be written. Set the env var to "" to turn it off."""
    p = os.environ.get(env, path)
    if not p:
        return ""
    try:
        os.makedirs(p, exist_ok=True)
        return p if os.access(p, os.W_OK) else ""
    except OSError:
        return ""


RUNS = scratch("CONDAB_RUNS", OLD_RUNS) or OLD_RUNS  # 2 Nov (owner: no bitbucket): the home again, at about one file per job (parts.txt, botpacks)
BOTP = OLD_RUNS + "/botpacks"  # one .tgz per bot, read by condab_node.sh; untouched for BOTP_AGE: gone, and the next sync makes it again
OTFP_AGE = int(os.environ.get("CONDAB_OTFP_AGE", 2 * 3600))  # 9 Nov 17:30Z: 3 h -> 2 h (home at 9.9 of 10 GB; oldest queued item ~2 h)
_OTFP_AGE_OLD = 3 * 3600  # an otfpack is touched on every reuse; untouched this long: gone (9 Nov)
BOTP_AGE = 3 * 3600  # 4 Nov: 48 h held 1,629 packs (980 MB) and filled the home size quota; 9 Nov 17:30Z: 12 h -> 3 h (home at 9.9 of 10 GB)
ARCHIVE = "/data/USER/condor_runs_archive"
ABL = "/data/USER/abl"
BQ = "/data/USER/st/bq"
WORK_MAPS = "/data/USER/work301/maps"        # where abindex hashes maps (and tourney.py copies them from)
ABL_MAPS = "/data/USER/work301_4.0.0/maps"   # abl.sh's workspace for cambc 4.0.0 (its default list)
FRESH = "/data/USER/genmaps_s/maplist.txt"
ODD = ["/data/USER/genmaps_c/maplist.txt", "/data/USER/genmaps_p/maplist.txt"]
HELDOUT = ["/data/USER/genmaps/maplist.txt", "/data/USER/st/fl/fb2/heldout.txt"]
NODE = os.path.join(REPO, "tools/lab/condab_node.sh")
PER_JOB, PAR = int(os.environ.get("CONDAB_PER_JOB", 24)), 12
CAP = int(os.environ.get("CONDAB_CAP", 400))  # our own queued-job cap (condor_selfservice.md), not a pool limit: the
# schedd allows 100,000 jobs per owner and 500 running; sweepd.py runs at 600 (Builder 30 Oct)
ENGINE_FILE = "/data/USER/st/bq/condab_engine"  # 'cxe': every condab batch (shipcheck legs too) plays on cxe; absent = Condor
LOOKS = (0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9)  # interim looks, as shares of the batch's jobs
FAIL_BAR, PASS_BAR = 0.48, 0.53               # pooled map-pair score: clear fail below, clear pass above
OBF_C, MIN_STAT = 2.6, 30                      # O'Brien-Fleming z = OBF_C / sqrt(t); returned pairs before rule (b)
OBF_C_DFAIL = 2.4  # paired-D FAIL side only (29 Oct sims, looks from 40%: 2.4 = the loosest with 0 wrong FAILs vs cq_nd130_1 in
# 5,351 batches and 6 in 12,720 vs random references, all at final D ~ 0; 2.2 gave 1 and 8, 2.0 2 and 16). PASS keeps OBF_C.
PAIR_D = "/data/USER/st/b86dg/py/pair_d.py"  # the Builder's paired-D definition (STOP_REF)
OTF_TMP = "/data/USER/otf_tmp"               # on-the-fly maps: one dir per batch, deleted with its maps
OTF_SEEDS, OTF_RECIPES = 40, 3                 # attempts per recipe; recipes per normal slot
OTF_PATHO_SEEDS = 12                           # attempts per pathology type before the next type (an islands seed takes ~8 s)
DCTRIG = "/data/USER/st/bq/dg151/py/dctrig.py"  # the b151 DOM_COMMIT trigger (OTF_DOM)
OTF_DOM_TRIES, DOM_MIN_GEMS = 150, 30          # attempts per OTF_DOM map; gems the dominant group needs at least
OTF_RULE_TRIES = 300                           # draws per OTF_RULE map
GEMCLU_RULE = "/data/USER/tooler/rules/gemclu.py:gemclu"
_RULE = {}                                     # the loaded OTF_RULE (set before the worker pool forks)
CLEAN_FILES, CLEAN_DIRS = [], []
PILOT_ACTIVE = []  # pilot batch ids this process queued and has not finished: cancelled at exit (a kill too)
EXTENDED = []                                  # CONDAB_TIMEBOX_EXT used (seconds), once per batch               # exact paths this process created and removes at exit
TREASURE_IDS = {19, 21, 23}
import condorroute  # noqa: E402  (5 Nov HOST: no local schedd -> the HOST route)
CONDOR_ENV = condorroute.env(dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", "")))
_cc = CONDOR_ENV.get("KRB5CCNAME", "")  # 30 Oct 20:25: a daemon's inherited Kerberos cache can be gone (its session renewed into a
if _cc and not os.path.exists(_cc[5:] if _cc.startswith("FILE:") else _cc):  # new file): then every condor_q / submit fails
    _ccs = sorted(glob.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
    if _ccs:
        CONDOR_ENV["KRB5CCNAME"] = "FILE:" + _ccs[-1]
        os.environ["KRB5CCNAME"] = "FILE:" + _ccs[-1]


# ---------------------------------------------------------------- node side: one game's statistics -> one line
def pair_deaths(d, team):
    """9 Nov (owner: a linked C&I pair death counts once, GR :381/:442): {'pair': n} = the side's Cassi+Issac joint deaths (the duo always dies
    together, so n = min of the two bodies' deaths), when every champion carries its design ('name': 'Unknown champion (N)', the platform's
    and, from 9 Nov, cxe's form; 3 = Cassi, 4 = Issac). {} when a record has no designs (older games): the pair count is then unknown."""
    import re as _re
    dd = {}
    for c in d["champions"]:
        if c["team"] != team:
            continue
        nm = str(c.get("name", ""))
        mm = _re.search(r"\((\d+)\)", nm)
        k = int(mm.group(1)) if mm else {"cassi": 3, "issac": 4}.get(nm.strip().lower(), -1 if nm.strip() else None)  # the local CLI names them ("Ryth")
        if k is None:
            return {}
        dd[k] = dd.get(k, 0) + int(float(c["metrics"].get("deaths", 0)))
    return {"pair": min(dd[3], dd[4]) if 3 in dd and 4 in dd else 0, "bodies": len([c for c in d["champions"] if c["team"] == team])}


def side_metrics(d, team):
    """Per-side metrics exactly as tools/lab/ablsum.py computes them for abl.sh's games.jsonl."""
    m = collections.Counter()
    for c in d["champions"]:
        if c["team"] != team:
            continue
        met = c["metrics"]
        for k in ("kills", "deaths", "earnedGold", "collectedGems"):
            m[k] += int(float(met.get(k, 0)))
        for i in c["items"]:
            mm = re.search(r"\((\d+)\)", i["item"])
            n = i["item"].lower()
            if (int(mm.group(1)) in TREASURE_IDS) if mm else ("treasure" in n and "emblem" in n):
                m["treasure"] += int(i["quantity"])
    for e in d["events"]:
        if e["owner"].get("team") != team:
            continue
        if e["kind"] == "wardPlacement":
            m["wards"] += len(e["entries"])
        elif e["kind"] == "fuelExhausted":
            m["fuel"] += len(e["entries"])
        elif e["kind"] == "fuelExhaustedAfterActions":  # 13 Nov (PCQ): cxe, marker bots only: cut-offs AFTER the turn's actions (subset of fuel)
            m["fuel_after"] += len(e["entries"])
    m["gems"] = next((int(t["submittedGems"]) for t in d["teams"] if t["team"] == team), 0)
    m.update(pair_deaths(d, team))
    m["faults"] = int(d.get("diagnostics", {}).get("botFaults", {}).get(team, 0))
    m["draftrand"] = int(d.get("diagnostics", {}).get("draftRandomPicks", {}).get(team, 0))  # 10 Nov: draft turns cut before a pick (cxe)
    return dict(m)


# 10 Nov (Coordinator, Prism post-mortem: kit-specific reads): per-body lineup and stats, both sides, in a compact form.
KITS = ("ryth", "vesper", "vendetta", "cassi", "issac", "stellar", "prism", "marcella", "willow", "ren", "varg", "tavi", "heart")  # champion_type
BODY_LABEL = ("123456", "KLNPRS")  # replay.py's labels: team A 1..6, team B LABEL_B, in champion id order


def kit_of(name):
    """'Unknown champion (6)' (cxe, platform) / 'Prism', 'Heart of Ruin' (CLI) / 'heart_of_ruin' (rdec) -> 'prism', 'heart'."""
    n = str(name or "").strip()
    mm = re.search(r"\((\d+)\)\s*$", n)
    if n.startswith("Unknown") and mm:
        k = int(mm.group(1))
        return KITS[k] if 0 <= k < len(KITS) else f"?{k}"
    return n.lower().replace("_", " ").split(" ")[0] if n else "?"


def champ_summary(d):
    """{'lu': {'a': [kit per body], 'b': [...]}, 'cs': {'a': [[kills, deaths, earnedGold, tributed gems] per body], 'b': [...]},
    'fk': [round, killer label, killer kit, victim label, victim kit]} from one game's statistics JSON. Body order = champion id
    order within the side = replay.py's labels (A 1..6, B K L N P R S). 'fk' (first champion kill) only when the statistics carry
    kill events (the CLI's) or a cxe 'firstKill' {round, killer, victim} (10 Nov), and is absent when nobody killed anyone."""
    side, lab = {}, {}
    lu, cs = {"a": [], "b": []}, {"a": [], "b": []}
    for c in sorted(d["champions"], key=lambda c: int(c["id"])):
        s = "a" if c["team"] == "teamA" else "b"
        met = c.get("metrics", {})
        lab[int(c["id"])] = (BODY_LABEL[s == "b"][len(lu[s])] if len(lu[s]) < 6 else str(len(lu[s]))), kit_of(c.get("name"))
        lu[s].append(kit_of(c.get("name")))
        cs[s].append([int(float(met.get(k, 0))) for k in ("kills", "deaths", "earnedGold", "submittedGems")])
        side[int(c["id"])] = s
    out = {"lu": lu, "cs": cs}
    best = None
    for e in d.get("events", ()):
        if e.get("kind") != "kill" or (e.get("owner") or {}).get("kind", "champion") != "champion":
            continue
        for x in e.get("entries", ()):
            t, ts = x.get("target") or {}, x.get("timestamp") or {}
            if t.get("kind", "champion") != "champion" or "id" not in t or "id" not in e["owner"]:
                continue
            key = (int(ts.get("round", 1 << 30)), int(ts.get("ordinal", 0)))
            if best is None or key < best[0]:
                best = (key, int(e["owner"]["id"]), int(t["id"]))
    fk = d.get("firstKill")  # 10 Nov: cxe writes the first champion kill itself ({round, killer, victim} champion ids)
    if best is None and isinstance(fk, dict) and "killer" in fk and "victim" in fk:
        best = ((int(fk.get("round", 0)), 0), int(fk["killer"]), int(fk["victim"]))
    if best and best[1] in lab and best[2] in lab:
        out["fk"] = [best[0][0], *lab[best[1]], *lab[best[2]]]
    return out


def champ_fields(d):
    try:
        return champ_summary(d)
    except Exception:  # noqa: BLE001 - never lose a game's result over the extra fields
        return {}


def stat_record(gid, a, b, mp, path):
    """One game's CQ record from its statistics JSON (also used by the cxe backend, tools/cxe/cxecondab.py)."""
    try:
        d = json.load(open(path))
        oc = d["match"].get("outcome")
        return dict(id=gid, a=a, b=b, map=mp, ok=True, win="A" if oc == "teamA" else ("B" if oc == "teamB" else "?"),
                    rounds=int(d["match"].get("roundsCompleted", 0)), sa=side_metrics(d, "teamA"), sb=side_metrics(d, "teamB"),
                    cx=champ_fields(d))
    except Exception as e:  # noqa: BLE001
        return dict(id=gid, a=a, b=b, map=mp, ok=False, err=str(e)[:120])


def node_stat(gid, a, b, mp, path):
    try:
        d = json.load(open(path))
        oc = d["match"].get("outcome")
        g = dict(id=gid, a=a, b=b, map=mp, ok=True, win="A" if oc == "teamA" else ("B" if oc == "teamB" else "?"),
                 rounds=int(d["match"].get("roundsCompleted", 0)), sa=side_metrics(d, "teamA"), sb=side_metrics(d, "teamB"),
                 cx=champ_fields(d))
    except Exception as e:  # noqa: BLE001
        g = dict(id=gid, a=a, b=b, map=mp, ok=False, err=str(e)[:120])
        jd = os.path.dirname(os.path.dirname(path))  # the job dir: condab_node.sh writes buildfail_<bot> there (1 Nov)
        if not os.path.exists(os.path.join(jd, "maps", mp + ".map26a")):  # 1 Nov: the map never reached the job
            g["err"] = f"MAP_MISSING {mp}"
        for bot in (a, b) if not g["err"].startswith("MAP_MISSING") else ():
            bf = os.path.join(jd, "buildfail_" + bot)
            if os.path.exists(bf):
                g["err"] = f"BUILD FAILED {bot}: {open(bf, errors='replace').read().strip()[:160]}"
                break
    print("CQ " + json.dumps(g, separators=(",", ":")))
    return 0 if g["ok"] else 1


# ---------------------------------------------------------------- maps
def read(f):
    return [ln.strip() for ln in open(f) if ln.strip()] if os.path.exists(f) else []


def pool_maps():
    """abl.sh's default list: every non-generated map plus gen_c_*, an S2-NN map byte-identical to a 02* map left out."""
    names = sorted(f[:-7] for f in os.listdir(ABL_MAPS) if f.endswith(".map26a") and (not f.startswith("gen_") or f.startswith("gen_c_")))
    pub = {open(os.path.join(ABL_MAPS, n + ".map26a"), "rb").read() for n in names if n.startswith("02")}
    return [n for n in names if not (n.startswith("S2-") and open(os.path.join(ABL_MAPS, n + ".map26a"), "rb").read() in pub)]


def fresh_maps():
    """sprt.py's decision maps in its order: nine gen_s maps, then one gen_c/gen_p map not in the pool."""
    pool = {f[:-7] for f in os.listdir(WORK_MAPS) if f.endswith(".map26a") and (not f.startswith("gen_") or f.startswith("gen_c_"))}
    fresh, odd = read(FRESH), [m for f in ODD for m in read(f) if m not in pool]
    order = []
    while fresh:
        order += fresh[:9]
        fresh = fresh[9:]
        if odd:
            order.append(odd.pop(0))
    return order


def balanced_order(maps):
    """Maps in a fixed pseudo-random order that interleaves the families in proportion (each job gets a fair mix)."""
    fam = collections.defaultdict(list)
    for m in maps:
        fam[abindex.map_set(m)].append(m)
    keyed = []
    for ms in fam.values():
        ms.sort(key=lambda m: hashlib.sha1(("condab:" + m).encode()).hexdigest())
        keyed += [((i + 0.5) / len(ms), hashlib.sha1(("condab2:" + m).encode()).hexdigest(), m) for i, m in enumerate(ms)]
    return [m for _, _, m in sorted(keyed)]


def set_maps(spec):
    if spec == "pool":
        ms = pool_maps()
    elif spec == "fresh":
        ms = fresh_maps()
    elif spec == "heldout":
        ms = [m for f in HELDOUT for m in read(f)]
    elif spec == "all" and os.environ.get("BIGSET") in ("ladderw_nh", "big2"):  # owner 3 Nov: held-out and sprt decision maps stay out of BIG
        ms = pool_maps()
    elif spec == "all":
        ms = pool_maps() + fresh_maps() + [m for f in HELDOUT for m in read(f)]
    elif os.path.isfile(spec):
        ms = read(spec)
    else:
        sys.exit(f"SET must be all, pool, fresh, heldout or a map-list file: {spec}")
    seen, out = set(), []
    for m in ms:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


# ---------------------------------------------------------------- Condor
def sh_out(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, env=CONDOR_ENV).stdout


def src_hash(d):
    import srchash  # 3 Nov: no spawn, byte-identical to the shell form (every exec on this machine costs /var/log/syslog ~2 KB)
    return srchash.src_hash(d)


QUOTA_TRICKLE = int(os.environ.get("CONDAB_QUOTA_TRICKLE", "60"))
QUOTA_TOKEN = "/data/USER/st/bq/preflight_token"
PREFLIGHT_HOLD = "/data/USER/st/bq/preflight_hold"  # touched while a batch waits on the home guard (healthwatch alarms on it)


def _quota_token():
    """True for at most one batch per QUOTA_TRICKLE s across all condab processes."""
    import fcntl
    try:
        with open(QUOTA_TOKEN, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            if time.time() - os.path.getmtime(QUOTA_TOKEN) < QUOTA_TRICKLE and os.path.getsize(QUOTA_TOKEN) > 0:
                return False
            if os.path.getsize(QUOTA_TOKEN) == 0:
                f.write("x\n")
                f.flush()
            os.utime(QUOTA_TOKEN)
            return True
    except OSError:  # the token is a brake only: a broken file must not stop the pipeline
        return True


def _preflight_why(n_jobs):
    """Why a batch can't start now (None: it can): home quota full, or CAP (400) Condor jobs of ours with no pilot alive."""
    import homequota  # 1 Nov ~22:40: the HOME server's line; quota -s also lists other users' mounted servers (HOST: erne)
    hq = homequota.home_quota() or {}
    files, mb = hq.get("files", 0), hq.get("mb", 0)
    # 5 Nov HOST: a hard stop at 57k deadlocked 84 batches (nothing finished, so nothing freed). Now a band: over 58k / 10 GB one
    # batch starts per QUOTA_TRICKLE s (a finished batch archives its ~28 files), so the pipeline slows instead of stopping; over
    # 59k / 10.8 GB (soft quota 60k / hard 61k) none start. quotaguard frees idle run dirs and healthwatch raises an ALARM meanwhile.
    # 12 Nov (TB; real quota 11,719 MB soft / 12,696 hard; the live Claude transcripts, not batches, fill home): MB band 11,000 / 11,400
    mb_slow, mb_stop = int(os.environ.get("CONDAB_HOME_MB_SLOW", "11000")), int(os.environ.get("CONDAB_HOME_MB_STOP", "11400"))
    if files > 59000 or mb > mb_stop:
        return f"home quota too full for a batch ({files} files, {mb:.0f} MB; limits 59,000 / {mb_stop:,})"
    if (files > 58000 or mb > mb_slow) and not _quota_token():
        return f"home quota high, one batch per {QUOTA_TRICKLE} s ({files} files, {mb:.0f} MB; band from 58,000 / {mb_slow:,})"
    # 31 Oct 02:30 (Builder: two shipchecks' reference top-ups were refused here while 26 pilots idled; 400+ idle cqbatch
    # jobs held the count): a batch that goes to live pilots adds no Condor job, so the cap does not apply to it
    if os.environ.get("CONDAB_PILOT", "1") not in ("", "0"):
        try:
            import pilotd
            if pilotd.alive_pilots():
                return None
        except Exception:  # noqa: BLE001  pool unreadable: the cap applies as before
            pass
        # 4 Nov: with no pilot alive a cxecondor batch plays on local cxe (play()), adding no Condor job either
        eng = os.environ.get("CONDAB_ENGINE") or (open(ENGINE_FILE).read().strip() if os.path.exists(ENGINE_FILE) else "")
        if eng in ("cxe", "cxecondor") and os.environ.get("CONDAB_STARVED_LOCAL", "1") != "0":
            return None
    tot = sh_out(["condor_q", "-totals"]).strip().split("\n")
    m = re.search(r"(\d+) jobs;", tot[-1] if tot else "")
    if m and int(m.group(1)) + n_jobs > CAP:
        return f"Condor already has {m.group(1)} of our jobs; adding {n_jobs} would pass {CAP}"
    return None


PF_WAIT = [0.0]  # 10 Nov (Builder: ppg1s/prc1s INCONCLUSIVE): seconds this process waited in preflight; a timebox does not count them


def preflight(n_jobs):
    """condor-work/reports/condor_selfservice.md: home guard (_preflight_why), under CAP (400) jobs of ours queued. A batch that
    can't start WAITS (re-checked every 30 s, up to CONDAB_PREFLIGHT_WAIT 3600 s) instead of exiting (4 Nov, b1155: legs came back
    EMPTY when the cap was hit; a resume then worked)."""
    t0, last = time.time(), 0.0
    while True:
        why = _preflight_why(n_jobs)
        if not why:
            PF_WAIT[0] += time.time() - t0
            return
        if "home quota too full" in why:  # the hard stop only: the trickle band above is a designed slowdown, logged below, not a stall to alarm on (6 Nov)
            try:
                with open(PREFLIGHT_HOLD, "a"):
                    os.utime(PREFLIGHT_HOLD)
            except OSError:
                pass
        if time.time() - t0 > float(os.environ.get("CONDAB_PREFLIGHT_WAIT", "3600")):
            sys.exit(f"{why}: waited {(time.time() - t0) / 60:.0f} min")
        if time.time() - last > 300:
            print(f"{time.strftime('%H:%M:%S')} preflight: {why}: waiting", flush=True)
            last = time.time()
            if "home quota" in why:
                try:
                    with open("/data/USER/st/bq/home_gate.log", "a") as f:
                        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} condab pid {os.getpid()}: {why}\n")
                except OSError:
                    pass
        time.sleep(30)


class _NoIndex:
    """The index of a batch with no saved maps: nothing to reuse, nothing to summarise."""
    games = {}
    conflicts = []

    def _add(self, *a):
        pass

    def pairs(self, *a):
        return {}


def pack_hash(b):
    """The source hash a bot's pack was made from, or None."""
    import tarfile  # 3 Nov: in-process, no tar spawn per bot per leg (/var/log/syslog)
    try:
        with tarfile.open(os.path.join(BOTP, b + ".tgz"), "r:gz") as t:
            return t.extractfile("./.srchash").read().decode().strip()
    except (OSError, KeyError, AttributeError, EOFError, tarfile.TarError):
        return None


def pack_bot(b, h):
    """bots/b as one file for the nodes (58 files and 1.4 MB as a copy): written whole, then renamed."""
    os.makedirs(BOTP, exist_ok=True)
    tmp = os.path.join(BOTP, f".{b}.{os.getpid()}.tmp")
    src = os.path.join(REPO, "bots", b)
    hf = tmp + ".hash"
    os.makedirs(hf)
    open(os.path.join(hf, ".srchash"), "w").write(h + "\n")
    try:
        subprocess.run(["tar", "-czf", tmp, "--exclude", ".cambc", "--exclude", "build", "-C", src + "/", ".", "-C", hf, "./.srchash"], check=True)
        os.replace(tmp, os.path.join(BOTP, b + ".tgz"))
    finally:
        shutil.rmtree(hf, ignore_errors=True)
        if os.path.exists(tmp):
            os.remove(tmp)


SYNC_WAIT = [0.0]  # s the last sync() waited for .sync.lock (the pre-game timing line)


def sync(bots, hashes, maps):
    """Bots and maps into the shared Condor project. 10 Nov ~20:40Z (owner: "make full use of our available compute"): 1,454 legs an
    hour each waited ~120 s for this lock while their own sync took ~4 s, because the lock also covered pack pruning, a read of every
    queued pilot item and the map copies. Now the lock covers only packing a bot whose pack is stale; map copies are atomic
    (tmp + rename) and need none; pruning runs at most every SYNC_HK_S (600) s, outside the lock."""
    t0 = time.time()
    need = [b for b in bots if pack_hash(b) != hashes[b]]
    for b in bots:
        if b not in need:
            try:
                os.utime(os.path.join(BOTP, b + ".tgz"))  # in use: the age rule keeps it
            except OSError:
                need.append(b)
    SYNC_WAIT[0] = 0.0
    if need:
        with open(os.path.join(PROJ, ".sync.lock"), "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            SYNC_WAIT[0] = time.time() - t0
            for b in need:
                if pack_hash(b) == hashes[b]:  # another leg packed it while we waited
                    continue
                if src_hash(os.path.join(REPO, "bots", b)) != hashes[b]:
                    sys.exit(f"bots/{b} does not hash to {hashes[b]}")
                pack_bot(b, hashes[b])
                if pack_hash(b) != hashes[b]:
                    sys.exit(f"the pack of {b} does not hash to {hashes[b]}")
    stamp = os.path.join(PROJ, ".sync.hk")
    try:
        due = time.time() - os.path.getmtime(stamp) > int(os.environ.get("SYNC_HK_S", "600"))
    except OSError:
        due = True
    if due:
        try:
            open(stamp, "a").close()
            os.utime(stamp)
        except OSError:
            pass
        for f in os.listdir(BOTP) if os.path.isdir(BOTP) else ():
            p = os.path.join(BOTP, f)
            try:
                if f.endswith(".tgz") and time.time() - os.path.getmtime(p) > BOTP_AGE:
                    os.remove(p)
            except OSError:
                pass
        od = OLD_RUNS + "/otfpacks"  # 9 Nov: the on-the-fly map packs were "kept 3 h from last use" but nothing removed them (862 MB, home guard hit)
        # 9 Nov 18:20Z: draft probes make one pack a batch (617 MB in 45 min put the home over 10 GB and throttled every condab to 1 batch/min):
        # a pack no queued or claimed pilot item names goes after OTFP_IDLE (20 min); a named one still waits OTFP_AGE
        try:
            refd = set()
            for sub in ("queue", "claimed"):
                qd = os.path.join(OLD_RUNS, "pilotq", sub)
                for it in os.listdir(qd):
                    try:
                        refd.update(re.findall(r"otfpacks/([0-9a-f]{16})", open(os.path.join(qd, it)).read()))
                    except OSError:
                        pass
        except OSError:
            refd = None
        for f in os.listdir(od) if os.path.isdir(od) else ():
            p = os.path.join(od, f)
            try:
                age = time.time() - os.path.getmtime(p)
                idle = refd is not None and f[:16] not in refd and age > int(os.environ.get("CONDAB_OTFP_IDLE", 1200))
                named = refd is not None and f[:16] in refd  # 10 Nov (Econ: a pack deleted under 2.5 h-queued items -> MAP_MISSING, 0 games)
                if f.endswith(".tar") and not named and (age > OTFP_AGE or idle):
                    os.remove(p)
            except OSError:
                pass
    try:  # ladderw.py's packed maps (BIGSET=ladderw) reach the nodes as packs too (31 Oct)
        import ladderw
        lw = ladderw.packed()
    except Exception:  # noqa: BLE001
        lw = {}
    def sync_map(m):
        src, dst = os.path.join(WORK_MAPS, m + ".map26a"), os.path.join(PROJ, "maps", m + ".map26a")
        if not os.path.exists(dst) or open(dst, "rb").read() != open(src, "rb").read():
            tmp = f"{dst}.tmp{os.getpid()}"  # 10 Nov: atomic, so map copies need no lock
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        else:  # 1 Nov: mark it in use, so quotaguard's QG_MAP_AGE keeps it between this sync and the job lists
            os.utime(dst)  # (an identical old copy read as unused and was removed before submit: kgb746sf1b lost 98 games)
    # bank maps reach the nodes as packs (condor-work/mapbank), never as files on the home
    loose = [m for m in maps if not (m.startswith(("gen_bk_", "gen_bh_", "gen_bk2_", "gen_bh2_")) or m in lw)]
    if any(re.match(r"lw[0-9]_\d+$", m) for m in loose):  # 10 Nov (home at 54.9k files): killgate's lwN_ pool maps go as packs
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "poolpack.py")], check=False)
        try:
            lw = ladderw.packed()
        except Exception:  # noqa: BLE001
            pass
        loose = [m for m in maps if not (m.startswith(("gen_bk_", "gen_bh_", "gen_bk2_", "gen_bh2_")) or m in lw)]
    # 8 Nov (owner: speed up testing): the same byte compare and copy of every map, on threads. One at a time over NFS it took 35 s for
    # the 6,679 loose maps of a full-pool leg, under this exclusive lock, so every other leg of a shipcheck waited behind it (0.5 s on 32)
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max(1, int(os.environ.get("CONDAB_SYNC_THREADS", "32")))) as ex:
        list(ex.map(sync_map, loose))




def cluster_of(run):
    try:
        m = re.search(r"\((\d+)\.\d+\.\d+\)", open(os.path.join(run, "batch.log")).read())
        return m.group(1) if m else None
    except OSError:
        return None


def collect(run):
    """{game index: CQ record} of the jobs that returned, and their BUILD_FAIL and MAP_MISSING lines."""
    got, bfail = {}, set()
    for f in sorted(glob.glob(os.path.join(run, "job_*.out")) + glob.glob(os.path.join(run + "_fb", "job_*.out"))
                    + glob.glob(os.path.join(run + "_pl", "job_*.out"))):  # _pl: jobs moved back to the pilots (REHOME)
        for line in open(f, errors="replace"):
            i = line.find("CQ {")
            if i >= 0:
                try:
                    g = json.loads(line[i + 3:])
                    got[int(g["id"])] = g
                except (ValueError, KeyError):
                    pass
            elif "BUILD_FAIL" in line or "MAP_MISSING" in line:
                bfail.add(line.strip()[:120])
    return got, bfail


def job_size(n_games):
    """Games per job: CONDAB_PER_JOB, else ~4 jobs per unclaimed >= PAR-cpu slot, 4..48 games a job (4 = both seats of 2
    maps), and never more jobs than leave our queue under 380. Measured 29 Oct: a 358-game leg took 1.55 min in 92 jobs of 4
    and 1.85 min in 15 of 12; queue latency and the per-job build (~35 s: every job gets a fresh /tmp, so it re-downloads
    the toolchain and rebuilds) set the time, not the games."""
    if os.environ.get("CONDAB_PER_JOB"):
        return int(os.environ["CONDAB_PER_JOB"])
    idle = len([x for x in sh_out(["condor_status", "-constraint", f'State == "Unclaimed" && Cpus >= {PAR}', "-af", "Name"])
                .splitlines() if x.strip()])
    tot = sh_out(["condor_q", "-totals"]).strip().split("\n")
    m = re.search(r"(\d+) jobs;", tot[-1] if tot else "")
    room = max(10, CAP - 20 - (int(m.group(1)) if m else 0))
    mq = re.search(r"(\d+) idle", next((x for x in tot if x.startswith("Total for USER")), ""))
    free = idle - (int(mq.group(1)) if mq else 0)  # (29 Oct 20:50: 107 of our jobs idle in the queue: small jobs only add builds)
    if free <= 0:
        return max(PER_JOB, math.ceil(n_games / room))
    jobs = min(max(4 * free, math.ceil(n_games / 48)), math.ceil(n_games / 4), room)
    return max(4, min(48, math.ceil(n_games / max(1, jobs))))


BUILD_CACHE = "/homes/USER/condor-work/buildcache"  # condab_node.sh's shared build cache (one tar per bot source + stamp)


def prebuild(bots, say):
    """Build every bot that has no shared-cache tar once HERE, by running condab_node.sh on a 1-game list (same paths as on
    the nodes: /tmp/USER-cqws-STAMP), which publishes the tar: then every node unpacks it instead of building (30 Oct: 8
    pilots that start a batch together all built the same new bot, 12-18 s each). Best effort: a failure or timeout leaves
    the nodes to build as before. CONDAB_PREBUILD=0 skips it.
    THROTTLED (30 Oct 18:20): a variant farm's many condab processes all prebuilt at once (load ~110 on 16 cores, 99 builds
    hit the 300 s timeout and left their compilers running, ubaudit builds died). Now: one prebuild per bot version at a
    time (a per-bot lock: a second asker skips it), at most PREBUILD_PAR (2) prebuilds on this machine (slot locks; none free
    within 30 s: skip), none when the 1-min load is above 2 x nproc, and a timeout kills the whole process group."""
    if os.environ.get("CONDAB_PREBUILD", "1") == "0":
        return
    if os.getloadavg()[0] > 2 * (os.cpu_count() or 16):
        return say(f"prebuild: skipped, load {os.getloadavg()[0]:.0f} (the nodes build)")
    # 5 Nov (/var full from process starts): reuse the stamp for 60 s (same value; saves 5 processes per condab start)
    sf = os.path.join(BQ, ".condab_stamp")
    try:
        stamp = open(sf).read().strip() if time.time() - os.path.getmtime(sf) < 60 else ""
    except OSError:
        stamp = ""
    if not stamp:
        stamp = subprocess.run(f'ls -ld --time-style=+%s "{PROJ}/cambc.toml" "{PROJ}/sdk" "{PROJ}/cmake" 2>/dev/null | '
                               "awk '{print $6, $7}' | cksum | cut -d' ' -f1", shell=True, capture_output=True, text=True).stdout.strip()
        try:
            with open(sf + ".tmp", "w") as fh:
                fh.write(stamp)
            os.replace(sf + ".tmp", sf)
        except OSError:
            pass
    keys = {b: f"{b}-{src_hash(os.path.join(REPO, 'bots', b))}-{stamp}" for b in bots}
    need = [b for b in bots if not os.path.exists(os.path.join(BUILD_CACHE, keys[b] + ".tar"))]
    if not need:
        return
    m0 = next((f[:-7] for f in sorted(os.listdir(os.path.join(PROJ, "maps"))) if f.endswith(".map26a")), None)
    if not m0:
        return
    lockd = os.path.join(BQ, ".prebuild")
    os.makedirs(lockd, exist_ok=True)
    held = []

    def grab(path):
        fh = open(path, "a")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(fh)
            return True
        except OSError:
            fh.close()
            return False
    try:
        mine = [b for b in need if grab(os.path.join(lockd, keys[b] + ".lock"))]  # another process builds the rest
        if not mine:
            return say(f"prebuild: {', '.join(need)} already being prebuilt elsewhere (the nodes unpack it when ready)")
        slot, t_end = False, time.time() + 30
        while not slot and time.time() < t_end:
            slot = any(grab(os.path.join(lockd, f"slot{k}.lock")) for k in range(int(os.environ.get("PREBUILD_PAR", 2))))
            if not slot:
                time.sleep(3)
        if not slot:
            return say("prebuild: no free prebuild slot within 30 s (the nodes build)")
        os.makedirs(OTF_TMP, exist_ok=True)
        lst = os.path.join(OTF_TMP, f"prebuild_{os.getpid()}.txt")
        open(lst, "w").write("\n".join(f"{i} {b} {b} {m0}" for i, b in enumerate(mine)) + "\n")
        t0 = time.time()
        p = subprocess.Popen(["nice", "-n", "10", "sh", os.path.join(REPO, "tools/lab/condab_node.sh"), lst, str(len(mine))],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=OTF_TMP, start_new_session=True)
        try:
            out, _ = p.communicate(timeout=300)
            built = re.findall(r"## (?:built|cached) (\S+-[0-9a-f]{12})", out)
            say(f"prebuild here (shared build cache for the nodes): {', '.join(built) or 'nothing built'} in {time.time() - t0:.0f} s")
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGTERM)  # the whole group: no orphaned compilers
            except OSError:
                pass
            p.wait()
            say("prebuild: timeout after 300 s, its build stopped (the nodes build)")
        finally:
            try:
                os.remove(lst)
            except OSError:
                pass
    finally:
        for fh in held:
            fh.close()


def play(out, games, timeout, say, keep=False, look=None, stop=False, order=None, xmaps=None, per_job=None, timebox=None):
    """games: [(a, b, map)], a map's games next to each other -> ({index: CQ record}, stopped (pct, decision) or None).
    One Condor batch in out/, blocks until it returns. look(got) -> (interim line, decision or None) at each look.
    order: the games' indices in job order (default: as listed); a game's id stays its index + 1. xmaps: a dir of extra
    maps the jobs read instead of the shared project (OTF)."""
    os.makedirs(out, exist_ok=True)
    engine = os.environ.get("CONDAB_ENGINE") or (open(ENGINE_FILE).read().strip() if os.path.exists(ENGINE_FILE) else "")
    if engine == "cxe" and not keep:
        # 4 Nov (Builder, owner priority iteration speed): play on HOST with cxe (verified game-identical to the CLI),
        # with a CLI spot-check; any guard failing sends the batch to Condor below, as before
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cxe"))
            import cxecondab
            res = cxecondab.play(out, games, say, look, stop, (xmaps + "") if xmaps else None, PROJ, LOOKS, stat_record)
            if res == "condor":  # local cxe busy: the same games with cxe on Condor nodes (below)
                engine = "cxecondor"
            elif res is not None:
                return res
        except (Exception, SystemExit) as e:  # cxebuild exits on a failed build  # noqa: BLE001  never let the fast path break a batch
            say(f"!! cxe backend failed ({str(e)[:160]}): Condor as usual")
    if engine == "cxecondor" and not keep and os.environ.get("CONDAB_STARVED_LOCAL", "1") != "0":
        # 4 Nov (Builder: 82 of 137 slots owner-held, 0 pilots alive, shipcheck legs crawling): with no pilot alive, play on HOST's
        # cxe slots instead (same CLI spot-check; any failure falls through to Condor as before)
        try:
            import pilotd as _pl
            starved = not _pl.alive_pilots()
        except Exception:  # noqa: BLE001
            starved = False
        if starved:
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cxe"))
                import cxecondab
                say("no Condor pilot alive: this batch plays on local cxe (CLI spot-checked)")
                res = cxecondab.play(out, games, say, look, stop, (xmaps + "") if xmaps else None, PROJ, LOOKS, stat_record, force=True)
                if res not in (None, "condor"):
                    return res
            except (Exception, SystemExit) as e:  # cxebuild exits on a failed build  # noqa: BLE001
                say(f"!! local cxe failed ({str(e)[:160]}): Condor as usual")
    cxe_rt, spot_pre = None, None
    if engine == "cxecondor":
        # 4 Nov (Builder: Condor is the bottleneck): the same Condor/pilot jobs, but each node plays with cxe (staged on
        # /homes with its own runtime) instead of building and running the CLI; CLI spot-check at the end, a mismatch re-plays
        # the batch on the CLI
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cxe"))
            import cxecondab
            if os.path.exists(cxecondab.STATUS) and open(cxecondab.STATUS).read().startswith("FAIL"):
                raise RuntimeError("the regular cxe check is FAIL")
            t_stage = time.time()
            # 10 Nov ~23:35Z (TB 6ad907: vmd25's leg sat 21.5 min in this stage, then its timebox fired 1 s after submit): the stage gets
            # CONDAB_STAGE_TIMEOUT (900 s), run in a thread; a slower stage falls back to CLI jobs. Stage time never counts toward the timebox.
            import threading as _th
            _res = {}

            def _stage():
                try:
                    _res["rt"] = cxecondab.stage_condor(sorted({g[0] for g in games} | {g[1] for g in games}), say)
                except BaseException as _e:  # noqa: BLE001
                    _res["err"] = _e
            _t = _th.Thread(target=_stage, daemon=True)
            _t.start()
            _t.join(float(os.environ.get("CONDAB_STAGE_TIMEOUT", 900)))
            PF_WAIT[0] += time.time() - t_stage
            if _t.is_alive():
                raise RuntimeError(f"cxe stage still running after {time.time() - t_stage:.0f} s (CONDAB_STAGE_TIMEOUT)")
            if "err" in _res:
                raise _res["err"]
            cxe_rt = _res.get("rt")
            say(f"pre-game: cxe stage (libraries for the nodes) {time.time() - t_stage:.1f} s")
            # the CLI spot-check plays alongside the batch (its sample is drawn up front), not after it
            _xd = cxecondab.unpack(xmaps) if xmaps else None
            spot_pre = cxecondab.spot_start(out, games, cxecondab.map_paths(games, _xd, PROJ),
                                            sorted({g[0] for g in games} | {g[1] for g in games}), 8)
            say(f"pre-game: map paths + spot-check start {time.time() - t_stage:.1f} s since the stage began")
        except (Exception, SystemExit) as e:  # cxebuild exits on a failed build  # noqa: BLE001
            say(f"!! cxe on Condor unavailable ({str(e)[:160]}): CLI jobs as usual")
            cxe_rt = None
    if not cxe_rt:
        prebuild(sorted({g[0] for g in games} | {g[1] for g in games}), say)
    pl, alive = None, []
    if os.environ.get("CONDAB_PILOT", "1") not in ("", "0"):  # the pilot pool (tools/lab/pilotd.py), when pilots run
        for _try in range(4):  # 11 Nov (dgxa 12338): one ESTALE on the NFS pilot queue sent 326 jobs to a direct submit that never ran (14 min, INCONCLUSIVE)
            try:
                import pilotd as pl
                pl.demand()
                alive = pl.alive_pilots()
                break
            except Exception as e:  # never let the pool break a batch: the normal submit still works
                if _try < 3 and isinstance(e, OSError):
                    say(f"!! pilot pool: {e}: retry {_try + 1} of 3 in 5 s")
                    time.sleep(5)
                    continue
                say(f"!! pilot pool unavailable ({e}): normal Condor submit")
                pl, alive = None, []
    use_pilot = bool(pl and len(alive) >= 1) and not os.environ.get("CONDAB_FORCE_DIRECT")  # FORCE_DIRECT: tests (REHOME)
    if use_pilot and not os.environ.get("CONDAB_PER_JOB"):
        # 1 Nov ~19:40 (Builder: 116 slots, 48 claimed, 65 idle: latency-bound): items of 16-48 games sized for the pool's
        # ceiling (CONDAB_PILOT_TARGET, default 100 = the running pilotd PILOT_MAX), not for the pilots alive at submit time (1-2 alive made
        # 17 items of ~96 from 1,600 games, so pilots that started later found nothing to take). Per-item cost stays small:
        # a pilot keeps its node's build workspace and wasm compile cache ("## cached"), so an item adds ~2-5 s.
        # 2 Nov: 48 games always. A pilot plays one item at a time, so 16-game items capped an 80-core machine at 16 games at once (pilots set PAR from the slot); also a third of the queue files.
        per_job = 48
    seq = [(j, games[j]) for j in (order if order is not None else range(len(games)))]
    per_job = per_job or PER_JOB
    groups, cur = [], []  # job parts: whole maps (both seats in the same job), up to per_job games
    for k, (j, g) in enumerate(seq):
        if cur and cur[-1][1][2] != g[2] and len(cur) + sum(1 for _, x in seq[k:k + 4] if x[2] == g[2]) > per_job:
            groups.append(cur)
            cur = []
        cur.append((j, g))
    if cur:
        groups.append(cur)
    parts = []  # one file for the run, not one per job (home inodes): condab_node.sh takes PARTSFILE:INDEX
    pf = os.path.join(out, "parts.txt")
    with open(pf, "w") as f:
        for i, grp in enumerate(groups):
            f.write(f"#part {i}\n" + "".join(f"{j + 1} {a} {b} {m}\n" for j, (a, b, m) in grp))
            parts.append(f"{pf}:{i}")
    if cxe_rt:  # condab_node.sh plays the parts with cxe when this file is next to the parts file
        rt, sos = cxe_rt
        open(pf + ".cxe", "w").write(f"rt {rt}\n" + "".join(f"bot {b} {so}\n" for b, so in sos.items()))
    kd = os.path.join(out, "keep")
    if keep:
        os.makedirs(kd)
        if os.environ.get("OTF_KEEP"):  # 3 Nov: condab_node.sh keeps the on-the-fly games' replays too (replay only)
            open(os.path.join(kd, ".otf"), "w").close()
        if os.environ.get("OTF_ROUNDS", "").isdigit():  # and caps those games at this many rounds (saved-map games never)
            open(os.path.join(kd, ".rounds"), "w").write(os.environ["OTF_ROUNDS"] + "\n")
    tail = f" {kd if keep else '-'} {xmaps}" if xmaps else (f" {kd}" if keep else "")
    open(os.path.join(out, "jobs.cmds"), "w").write("".join(f"sh {NODE} {p} {PAR}{tail}\n" for p in parts))
    run = os.path.join(out, "run")
    prio = os.environ.get("CONDAB_PRIO") or os.environ.get("READ_PRIO") or ("10" if os.environ.get("CONFIRM", "0") not in ("", "0") else
                                             "-5" if os.environ.get("KEEP") == "1" else "0")
    targs = ([kd if keep else "-", xmaps] if xmaps else ([kd] if keep else []))

    def submit(cmds, rdir):
        r = subprocess.run(["sh", os.path.join(REPO, "tools/condor/cbatch.sh"), cmds, rdir,
                            "1", "1", str(PAR), "10000"], capture_output=True, text=True, env=dict(CONDOR_ENV, CBATCH_PRIO=prio))
        if r.returncode != 0:
            sys.exit(f"cbatch.sh failed, nothing queued: {(r.stdout + r.stderr)[-300:]}")
        for _ in range(10):
            if cluster_of(rdir):
                break
            time.sleep(3)
        else:
            sys.exit(f"no Condor job log after the submit ({rdir}/batch.log)")
        return cluster_of(rdir)

    cl, bid, fb, fb_cl = None, None, None, None  # Condor cluster | pilot batch (+ its fallback cluster and parts)
    if use_pilot:
        bid = pl.enqueue(run, [(i, [p, PAR] + targs) for i, p in enumerate(parts)], prio)
        PILOT_ACTIVE.append(bid)
        open(os.path.join(out, "cluster.txt"), "w").write(f"pilot:{bid}\n")
        say(f"Pilot batch {bid}: {len(games)} games in {len(parts)} items, priority {prio}, {len(alive)} pilots alive -> {out}")
    else:
        cl = submit(os.path.join(out, "jobs.cmds"), run)
        open(os.path.join(out, "cluster.txt"), "w").write(f"{cl}\n")  # STOP and the straggler rule remove only this cluster
        say(f"Condor cluster {cl}: {len(games)} games in {len(parts)} jobs -> {out}")

    rebids, last_rehome = [], [time.time()]  # REHOME: pilot batches (run_pl) of jobs moved off a Condor cluster
    heal_st, last_heal = {}, time.time()
    rehomed = set()  # parts rehome() moved to the pilot queue: the only ones the rehomed heal below may queue again
    stall = int(os.environ.get("CONDAB_STALL", 0) or 0)  # s with no job back: stop and report what came back (stylepanel's legs; timeboxes do this for the others)

    stall_st = {"ref": time.time(), "seen": set()}  # 10 Nov: stall clock for pilot batches (stall_tick)

    def stall_age():
        """Seconds the stall clock has run. Pilot batches (10 Nov, b1834: legs removed after 45 min merely queued behind other work):
        the clock runs only while an item of this batch is claimed by a pilot, counted from the last claim or finish; a batch whose
        remaining items are all still queued is waiting on the pool, not stalled. A Condor cluster (or the fallback): since the last job back."""
        if not bid or fb:
            return time.time() - since
        return stall_tick(stall_st, [bid] + rebids, pl.ls(pl.q("queue")), pl.ls(pl.q("claimed")), time.time())

    def remove():
        """condor_rm this batch's own cluster; a pilot batch: cancel its items (queued deleted, running killed)."""
        for b in ([bid] if bid else []) + rebids:
            pl.cancel(b)
            if b in PILOT_ACTIVE:
                PILOT_ACTIVE.remove(b)
        for c in (cl, fb_cl):
            if c:
                subprocess.run(["condor_rm", c], capture_output=True, text=True, env=CONDOR_ENV)

    def finished():
        if not bid:
            n = sum(1 for f in glob.glob(os.path.join(run, "job_*.out")) if "## end" in open(f, errors="replace").read())
            return n + (len(pl.done_parts(run + "_pl")) if rebids else 0)
        d = pl.done_parts(run) | (pl.done_parts(run + "_pl") if rebids else set())
        for f in glob.glob(os.path.join(run + "_fb", "job_chunk_*.out")) if fb else []:
            if "## end" in open(f, errors="replace").read():
                d.add(fb[int(re.search(r"job_chunk_(\d+)\.out", f).group(1))])
        return len(d & set(range(len(parts))))

    def rehome():
        """31 Oct 12:40 (Builder: lh518 went to a direct cluster of 220 jobs while no pilot was alive; its own demand then
        brought 4 pilots back, which sat idle beside 218 idle jobs on a day pool of ~8 slots): when pilots are alive, the
        cluster's jobs that have NOT started move to the pilot queue. Only idle jobs are removed (constraint JobStatus == 1),
        and only a part whose job is gone and wrote no output is re-queued, so nothing runs twice."""
        target = fb_cl or cl
        if not (pl and target) or os.environ.get("CONDAB_REHOME", "1") in ("", "0") or not pl.alive_pilots():
            return
        rows = [ln.split() for ln in sh_out(["condor_q", target, "-af", "ProcId", "JobStatus"]).splitlines() if ln.strip()]
        idle = [int(r[0]) for r in rows if len(r) >= 2 and r[0].isdigit() and r[1] == "1"]
        if not idle:
            return
        subprocess.run(["condor_rm", "-constraint", f"ClusterId == {target} && JobStatus == 1"], capture_output=True,
                       text=True, env=CONDOR_ENV)
        time.sleep(3)
        still = {int(ln.split()[0]) for ln in sh_out(["condor_q", target, "-af", "ProcId"]).splitlines()
                 if ln.strip() and ln.split()[0].isdigit()}
        rdir = run + "_fb" if fb_cl else run
        moved = [k for k in idle if k not in still and not os.path.exists(os.path.join(rdir, f"job_chunk_{k:04d}.out"))]
        idx = [fb[k] for k in moved if k < len(fb)] if fb_cl else [k for k in moved if k < len(parts)]
        if not idx:
            return
        rehomed.update(idx)
        b2 = pl.enqueue(run + "_pl", [(i, [parts[i], PAR] + targs) for i in idx], prio)
        rebids.append(b2)
        PILOT_ACTIVE.append(b2)
        say(f"PILOTS BACK: {len(idx)} jobs of cluster {target} had not started: moved to the pilot queue as {b2} "
            f"({len(pl.alive_pilots())} pilots alive)")

    what = f"pilot batch {bid}" if bid else f"cluster {cl}"
    no_pilot_since, last_alive_check = None, 0
    end, last, since, polls = time.time() + timeout, -1, time.time(), 0
    looked, stopped = set(), None
    while True:
        fin = finished()
        if bid and not fb and fin < len(parts) and time.time() - last_alive_check > 60:
            last_alive_check = time.time()  # every pilot gone (evicted, pilotd stopped): the rest goes the normal way
            if pl.alive_pilots():
                no_pilot_since = None
            elif no_pilot_since is None:
                no_pilot_since = time.time()
            elif time.time() - no_pilot_since > int(os.environ.get("CONDAB_PILOT_FALLBACK", 300)):
                done = pl.done_parts(run)
                fb = [i for i in range(len(parts)) if i not in done]
                pl.cancel(bid)
                open(os.path.join(out, "jobs_fb.cmds"), "w").write("".join(f"sh {NODE} {parts[i]} {PAR}{tail}\n" for i in fb))
                fb_cl = submit(os.path.join(out, "jobs_fb.cmds"), run + "_fb")
                what = f"pilot batch {bid} + fallback cluster {fb_cl}"
                say(f"!! no pilot alive for {time.time() - no_pilot_since:.0f} s: {len(fb)} unfinished parts submitted as "
                    f"Condor cluster {fb_cl}")
        if (cl or fb_cl) and fin < len(parts) and time.time() - last_rehome[0] > 60:
            last_rehome[0] = time.time()
            try:
                rehome()
            except Exception as e:  # noqa: BLE001  the cluster keeps running either way
                say(f"!! rehome to the pilots failed ({str(e)[:120]}): the Condor jobs stay")
        if bid and not fb and fin < len(parts) and time.time() - last_heal > 60:
            last_heal = time.time()
            try:
                nb, nl = pl.heal([bid] + rebids, run, [(i, [p, PAR] + targs) for i, p in enumerate(parts)], prio, heal_st)
                if nb:
                    rebids.append(nb)
                    PILOT_ACTIVE.append(nb)
                    say(f"!! pilot batch {bid}: nothing queued or running with {nl} parts unfinished: queued them again ({nb})")
            except Exception as e:  # noqa: BLE001  the batch keeps running either way
                say(f"!! heal failed ({str(e)[:120]})")
        if rehomed and fin < len(parts) and time.time() - last_heal > 60:  # 2 Nov (shipcheck 1071): a rehomed part lost in a /vol/bitbucket blip had no heal; the run sat 10 min on the straggler rule, 24 games short
            last_heal = time.time()
            try:
                nb, nl = pl.heal(list(rebids), run + "_pl", [(i, [parts[i], PAR] + targs) for i in sorted(rehomed)], prio, heal_st)
                if nb:
                    rebids.append(nb)
                    PILOT_ACTIVE.append(nb)
                    say(f"!! rehomed parts: nothing queued or running with {nl} parts unfinished: queued them again ({nb})")
            except Exception as e:  # noqa: BLE001  the batch keeps running either way
                say(f"!! heal failed ({str(e)[:120]})")
        sfile = os.environ.get("CONDAB_STOPFILE")
        if sfile and os.path.exists(sfile) and fin < len(parts):  # the caller's stop (shipcheck: the live h2h FAILED)
            remove()
            stopped = (int(round(100 * fin / len(parts))), f"STOPPED by {os.path.basename(sfile)}")
            say(f"STOP: {sfile} exists: removed this batch's {what} ({len(parts) - fin} jobs unfinished)")
            time.sleep(5)
            break
        due = [f for f in LOOKS if f not in looked and fin >= math.ceil(f * len(parts))]
        if look and due and fin < len(parts):
            looked.update(due)
            lines, dec, _ = look(collect(run)[0])
            for line in ([lines] if isinstance(lines, str) else lines):
                say(f"INTERIM {int(round(100 * due[-1]))}% of jobs ({fin}/{len(parts)}): {line}")
            if dec and stop:
                remove()
                stopped = (int(round(100 * fin / len(parts))), dec)
                say(f"STOP: decided {dec}: removed this batch's {what} ({len(parts) - fin} jobs unfinished)")
                time.sleep(5)
                break
        if fin >= len(parts):
            break
        ext = float(os.environ.get("CONDAB_TIMEBOX_EXT", 0) or 0)
        frac = float(os.environ.get("CONDAB_EXT_FRAC", 0.7) or 0.7)  # shipcheck: 0.5 (Builder 30 Oct, daytime capacity)
        if timebox and time.time() > timebox + PF_WAIT[0] and ext > 0 and not EXTENDED and fin >= frac * len(parts):
            EXTENDED.append(ext)  # once: most jobs are back, the rest will be soon (owner 29 Oct: let iteration continue)
            timebox += ext
            say(f"TIMEBOX: {fin}/{len(parts)} jobs back (>= {frac:.0%}): extended by {ext / 60:.0f} min")
        if timebox and time.time() > timebox + PF_WAIT[0]:
            pct = int(round(100 * fin / len(parts)))
            dec = None
            if look:
                lines, _, dec = look(collect(run)[0])
                for line in ([lines] if isinstance(lines, str) else lines):
                    say(f"TIMEBOX {pct}% of jobs ({fin}/{len(parts)}): {line}")
            remove()
            stopped = (pct, dec or "INCONCLUSIVE", "timebox")
            say(f"TIMEBOX: {dec or 'INCONCLUSIVE'}: removed this batch's {what} ({len(parts) - fin} jobs unfinished)")
            time.sleep(5)
            break
        if fin != last:
            if last >= 0:
                say(f"  {fin}/{len(parts)} jobs done")
            last, since = fin, time.time()
            stall_st["ref"] = since  # a job back restarts the stall clock
        elif (fin >= 0.9 * len(parts) and time.time() - since > 600) or (time.time() > end and not (time.time() < end + 2 * timeout and heal_st.get("empty", 1) == 0)) \
                or (stall and stall_age() > stall):  # 10 Nov: pilot batches count only claimed time (stall_tick); 2 Nov's 3 x stall queue cap is gone
            remove()
            say(f"!! removed {what} with {len(parts) - fin} of {len(parts)} jobs unfinished: a re-run plays their games")
            time.sleep(5)
            break
        polls += 1
        if polls % 30 == 0 and (fb_cl or cl):  # held jobs never finish (26 Oct: the home over quota): release them
            held = [x for x in sh_out(["condor_q", fb_cl or cl, "-hold", "-af", "HoldReason"]).splitlines() if x.strip()]
            if held:
                say(f"!! {len(held)} jobs held ({held[0][:120]}): releasing")
                subprocess.run(["condor_release", fb_cl or cl], capture_output=True, text=True, env=CONDOR_ENV)
        # jobs return in bursts: look often enough to catch 50%; 8 Nov: the last 10% of the jobs every CONDAB_POLL_TAIL (5) s, the end of a batch waited up to 20 s for nothing
        time.sleep(10 if look and len(looked) < len(LOOKS) else float(os.environ.get("CONDAB_POLL_TAIL", "5")) if fin >= 0.9 * len(parts) else 20)
    if bid in PILOT_ACTIVE:
        PILOT_ACTIVE.remove(bid)
    got, bfail = collect(run)
    for b in sorted(bfail)[:5]:
        say(f"!! {b}")
    if cxe_rt and got:
        try:
            xdir = cxecondab.unpack(xmaps) if xmaps else None
            paths = cxecondab.map_paths(games, xdir, PROJ)
            ok, note = cxecondab.spot_check(out, games, got, paths, sorted({g[0] for g in games} | {g[1] for g in games}),
                                            stat_record, 8, f"engine cxe on Condor: {len(got)} games", pre=spot_pre)
        except (Exception, SystemExit) as e:  # cxebuild exits on a failed build  # noqa: BLE001
            if isinstance(e, SystemExit) and e.code == 143:  # 7 Nov: our own SIGTERM (a stopped read), not a cxe fault: stop, never re-play on the CLI
                raise
            ok, note = False, f"!! cxe spot-check could not run ({str(e)[:120]})"
        say(note)
        if not ok:
            say("!! re-playing this batch with the CLI on Condor")
            os.environ["CONDAB_ENGINE"] = "condor"
            try:
                return play(out + "_cli", games, timeout, say, keep, look, stop, order, xmaps, per_job, timebox)
            finally:
                os.environ.pop("CONDAB_ENGINE", None)
                # 5 Nov: only the parent was archived, so 301 finished _cli dirs held 9k home files and the home guard stopped 84 batches
                if os.path.isdir(out + "_cli"):
                    archive(out + "_cli")
    return got, stopped


def interim_rule(cand, base, maps, todo, cached):
    """look(got) for play(): cached = {(a, b, map): win} of the SET's games that are not replayed."""
    todo_maps = {m for _, _, m in todo}
    known = {}
    for m in maps:
        if m not in todo_maps and (cand, base, m) in cached and (base, cand, m) in cached:
            known[m] = ((cached[(cand, base, m)] == "A") + (cached[(base, cand, m)] == "B")) / 2
    N, Nt = len(maps), len(todo_maps)
    fam_tot = collections.Counter(abindex.map_set(m) for m in maps)
    hf = os.environ.get("CONDAB_HI_FAIL")  # "BAR,Z,MIN": FAIL when the returned pairs' score + Z se < BAR (docstring)
    hf = tuple(float(x) for x in hf.split(",")) if hf else None

    def look(got):
        res = {k: v for k, v in cached.items() if k[2] in todo_maps}
        for g in got.values():
            if g.get("ok") and g.get("win") in ("A", "B"):
                res[(g["a"], g["b"], g["map"])] = g["win"]
        ret = {m: ((res[(cand, base, m)] == "A") + (res[(base, cand, m)] == "B")) / 2 for m in todo_maps
               if (cand, base, m) in res and (base, cand, m) in res}
        sc = list(known.values()) + list(ret.values())
        n, nr = len(sc), len(ret)
        if n < 2:
            return f"{n} complete map pairs", None
        mean = sum(sc) / n
        se = math.sqrt(sum((x - mean) ** 2 for x in sc) / (n - 1) / n)
        fam = collections.Counter(abindex.map_set(m) for m in list(known) + list(ret))
        fams = " ".join(f"{f} {fam[f]}/{fam_tot[f]}" for f in sorted(fam_tot, key=lambda f: -fam_tot[f]))
        Sk, Sr = sum(known.values()), sum(ret.values())
        lo, hi = (Sk + Sr) / N, (Sk + Sr + Nt - nr) / N
        dec = how = None
        if hi < FAIL_BAR:
            dec, how = "FAIL", "deterministic"
        elif lo > 0.5:
            dec, how = "PASS", "deterministic"
        proj_s = ""
        if nr >= 2:
            mr = Sr / nr
            sr2 = sum((x - mr) ** 2 for x in ret.values()) / (nr - 1)
            proj = (Sk + Nt * mr) / N
            sef = (Nt / N) * math.sqrt(max(0.0, 1 - nr / Nt) * sr2 / nr)
            z = OBF_C / math.sqrt(nr / Nt)
            proj_s = f"projected final {proj:.3f} +-{z * sef:.3f} (OBF z {z:.2f}, finite-population se)"
            if dec is None and nr >= MIN_STAT:
                if proj + z * sef < FAIL_BAR:
                    dec, how = "FAIL", "projected"
                elif proj - z * sef > 0.5:
                    dec, how = "PASS", "projected"
        if dec is None and hf and n >= hf[2] and mean + hf[1] * se < hf[0]:
            dec, how = "FAIL", f"CI upper {mean + hf[1] * se:.3f} < {hf[0]:g} at z {hf[1]:g}, n {n} >= {hf[2]:.0f}"
        line = (f"{n}/{N} map pairs: score {mean:.3f} [{max(0, mean - 1.96 * se):.3f}, {min(1, mean + 1.96 * se):.3f}] (plain 95% CI); "
                f"{proj_s}; final range [{lo:.3f}, {hi:.3f}]; {fams}; "
                + (f"DECIDED {dec} ({how})" if dec else f"not decided (FAIL: upper < {FAIL_BAR}; PASS: lower > 0.5)"))
        return line, dec
    return look


OUTS = []  # this process's run dirs: archived at exit, also after a stop


def archive(out):
    try:
        os.makedirs(ARCHIVE, exist_ok=True)
        subprocess.run(["rsync", "-a", "--remove-source-files", out, ARCHIVE + "/"], check=True, capture_output=True)
        subprocess.run(["find", out, "-depth", "-type", "d", "-empty", "-delete"], capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"!! could not move {out} to {ARCHIVE}: {e}")


def kept_replays(hashes):
    """{(hash A, hash B, map name): run dir} of every game whose replay a run on this machine kept (RUN/rep/ID.repl26a)."""
    want = set(hashes.values())
    mp = abindex.maps()
    out = {}
    for d in sorted(glob.glob(os.path.join(ABL, "*", "rep"))):
        rd = os.path.dirname(d)
        man, gj = os.path.join(rd, "manifest.txt"), os.path.join(rd, "games.jsonl")
        if not (os.path.exists(man) and os.path.exists(gj)):
            continue
        t = os.path.getmtime(gj)
        try:  # only games of this engine (abindex.py's rule for local runs)
            cv = open(os.path.join(rd, "cli.txt")).read().strip()
        except OSError:
            cv = ""
        if cv != "cambc " + abindex.cli_version() or t < os.path.getmtime(abindex.CLI):
            continue
        ok = set()
        for line in open(gj):
            try:
                g = json.loads(line)
                if g.get("ok") and g.get("win") in ("A", "B"):
                    ok.add(str(g["id"]))
            except ValueError:
                pass
        for i, line in enumerate(open(man), 1):
            f = line.split()
            if len(f) < 3 or str(i) not in ok or not os.path.exists(os.path.join(d, f"{i}.repl26a")):
                continue
            ha, hb, m = f[0].rsplit("-", 1)[-1], f[1].rsplit("-", 1)[-1], os.path.basename(f[2])[:-7]
            if ha in want and hb in want and m in mp and mp[m][2] <= t:
                out.setdefault((ha, hb, m), rd)
    return out


def _untar(tf, dest):
    """9 Nov (/var: root's syslog logs every process we start, ~156 a second at 10:55Z, and `tar xzf` + gzip per kept game were the top
    source): unpack in-process, no fork. True on success."""
    import tarfile
    try:
        with tarfile.open(tf) as t:
            t.extractall(dest, filter="data")
        return True
    except (OSError, tarfile.TarError, ValueError):
        return False


def unpack_keep(out, rd):
    """The jobs' keep_*.tgz into rd/rep and rd/st (the run's own game ids); returns how many replays landed."""
    n = 0
    for tf in sorted(glob.glob(os.path.join(out, "keep", "keep_*.tgz"))):
        if _untar(tf, rd):
            os.remove(tf)  # the batch's copy (home, inode quota); the replays now live in rd
    if os.path.isdir(os.path.join(rd, "rep")):
        n = len(os.listdir(os.path.join(rd, "rep")))
    return n


def unpack_otf_keep(out, okd, name, games, ntodo, got, otf, cand, base, rd=None):
    """OTF_KEEP=DIR (3 Nov, inforead --keep-replays): the jobs' keep tarballs -> DIR/rep/<batch>_<J>.repl26a for the on-the-fly games
    (the node keeps their replay only) and DIR/set.json, a readmany trunkset source (per game: replay, map, a, b, us = the bot of
    interest (CAND, else the side that is not BASE), opp, seat = us's side, win, rounds, leg, family, labels, capped = OTF_ROUNDS).
    Saved-map games' replays and statistics go to rd (KEEP=1) or are dropped. -> how many on-the-fly replays landed."""
    import shutil
    import tempfile
    # 9 Nov (cxefarm stalled: home 55k files, 1,800 per batch in keep/x): unpack into a scratch dir on /data, beside okd, not the batch's home dir
    sdir = "/data/USER/tmp"
    os.makedirs(sdir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f"okeep_{os.path.basename(out.rstrip('/'))}_", dir=sdir)
    for tf in sorted(glob.glob(os.path.join(out, "keep", "keep_*.tgz"))):
        if _untar(tf, tmp):
            os.remove(tf)
    os.makedirs(os.path.join(okd, "rep"), exist_ok=True)
    meta = {om["name"]: om for om in (otf or {}).get("maps", [])}
    cap = int(os.environ["OTF_ROUNDS"]) if os.environ.get("OTF_ROUNDS", "").isdigit() else 0
    tag, new = os.path.basename(out), []
    for p in sorted(glob.glob(os.path.join(tmp, "rep", "*.repl26a"))):
        j = int(os.path.basename(p)[:-8])
        if j > ntodo and j <= len(games):
            a, b, m = games[j - 1]
            g = got.get(j) or {}
            if not cap and not (g.get("ok") and g.get("win") in ("A", "B")):
                continue  # a capped game has no result (and no statistics): its replay is the whole point
            us = cand if cand in (a, b) else (a if b == base else b)
            fn = f"{tag}_{j}.repl26a"
            shutil.move(p, os.path.join(okd, "rep", fn))
            om = meta.get(m, {})
            new.append(dict(replay=f"rep/{fn}", map=m, a=a, b=b, us=us, opp=b if us == a else a, seat="a" if us == a else "b",
                            win=g.get("win") if not cap else None, rounds=g.get("rounds", 0) if not cap else cap, leg=name, family=om.get("family"), labels=om.get("labels", {}),
                            capped=cap))
        elif rd and j <= ntodo:
            for sub, ext in (("rep", ".repl26a"), ("st", ".json")):
                q = os.path.join(tmp, sub, f"{j}{ext}")
                if os.path.exists(q):
                    os.makedirs(os.path.join(rd, sub), exist_ok=True)
                    shutil.move(q, os.path.join(rd, sub, f"{j}{ext}"))
    shutil.rmtree(tmp, ignore_errors=True)
    sj = os.path.join(okd, "set.json")
    old = json.load(open(sj)) if os.path.exists(sj) else dict(games=[])
    old.update(leg=name, cand=cand, base=base)
    old["games"] += new
    json.dump(old, open(sj + ".part", "w"))
    os.replace(sj + ".part", sj)
    return len(new)


def write_run(rd, games, got, hashes):
    """An abl.sh-format run dir that abindex.py reads: manifest line k names game k's bot cache dirs and map."""
    os.makedirs(rd)
    open(os.path.join(rd, "cli.txt"), "w").write(f"cambc {abindex.cli_version()}\n")
    open(os.path.join(rd, "bots.txt"), "w").write("".join(f"{b} {h} condor\n" for b, h in hashes.items()))
    with open(os.path.join(rd, "manifest.txt"), "w") as mf, open(os.path.join(rd, "games.list"), "w") as gl, \
            open(os.path.join(rd, "games.jsonl"), "w") as gj:
        for j, (a, b, m) in enumerate(games, 1):
            mf.write(f"/data/USER/ablcache2_4.0.0/{a}-{hashes[a]} /data/USER/ablcache2_4.0.0/{b}-{hashes[b]} "
                     f"/data/USER/ablproj_4.0.0/maps/{m}.map26a {rd}/rep/{j}.repl26a --statistics {rd}/st/{j}.json --json\n")
            gl.write(f"{j} {a} {b} {m}\n")
            g = got.get(j) or dict(ok=False)
            if g.get("ok") and (g.get("a"), g.get("b"), g.get("map")) != (a, b, m):  # 3 Nov (b935): a game reported for another pairing is not this one
                print(f"!! game {j}: the job reported {g.get('a')} v {g.get('b')} on {g.get('map')}, the batch wanted {a} v {b} on {m}: dropped")
                g = dict(ok=False)
            g = dict(g, id=str(j), a=a, b=b, map=m)
            gj.write(json.dumps(g) + "\n")


# ---------------------------------------------------------------- STOP_REF: paired D against a reference run
def pair_d():
    """pair_d.py's imports and functions (scores, fam, boot) without running its command line."""
    tree = ast.parse(open(PAIR_D).read(), PAIR_D)
    tree.body = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    ns = {"__name__": "pair_d"}
    exec(compile(tree, PAIR_D, "exec"), ns)
    return ns


def ref_run(spec, opp):
    """STOP_REF -> (run dir, its name relative to ABL as pair_d.scores() takes it, the reference bot). A comma list of runs
    (the reference's games split over several runs) is merged, each game once, into /data/USER/st/bq/.ref_<hash>."""
    if "," in spec:
        parts = [ref_run(x, opp) for x in spec.split(",") if x]
        if len({p[2] for p in parts}) != 1:
            sys.exit(f"STOP_REF {spec}: the runs have different reference bots ({', '.join(sorted({p[2] for p in parts}))})")
        md = os.path.join(BQ, ".ref_" + hashlib.sha1(spec.encode()).hexdigest()[:10])
        os.makedirs(md, exist_ok=True)
        seen, lines = set(), []
        for rd_, _, rb in parts:
            for ln in open(os.path.join(rd_, "games.jsonl")):
                try:
                    g = json.loads(ln)
                except ValueError:
                    continue
                k = (g.get("a"), g.get("b"), g.get("map"))
                if g.get("ok") and k not in seen and {k[0], k[1]} == {rb, opp}:
                    seen.add(k)
                    lines.append(dict(g, id=str(len(lines) + 1)))
        open(os.path.join(md, "games.jsonl"), "w").write("".join(json.dumps(g) + "\n" for g in lines))
        open(os.path.join(md, "games.list"), "w").write("".join(f"{g['id']} {g['a']} {g['b']} {g['map']}\n" for g in lines))
        shutil.copyfile(os.path.join(parts[0][0], "bots.txt"), os.path.join(md, "bots.txt"))
        return md, os.path.relpath(md, ABL), parts[0][2]
    rd = os.path.join(ABL, spec) if os.path.isdir(os.path.join(ABL, spec)) else os.path.abspath(spec)
    if not os.path.exists(os.path.join(rd, "games.jsonl")):
        sys.exit(f"STOP_REF {spec}: no games.jsonl in {rd}")
    bots = set()
    for line in open(os.path.join(rd, "games.list")):
        p = line.split()
        if len(p) >= 4:
            bots.update(p[1:3])
    if opp not in bots or len(bots - {opp}) != 1:
        sys.exit(f"STOP_REF {spec}: its games are {' vs '.join(sorted(bots))}, not one reference bot against {opp}")
    return rd, os.path.relpath(rd, ABL), (bots - {opp}).pop()


def d_rule(d_known, d_ret, hi_unret, n_todo):
    """FAIL-only rule on the projected final paired D. d_known: D of maps not replayed (cached); d_ret: D of the batch's
    returned maps; hi_unret: the largest D each unreturned batch map can still reach (1 - reference score);
    n_todo: the batch's maps that the reference has. -> (projected D, its upper bound or None, z, max D, decision, how)"""
    nk, nr = len(d_known), len(d_ret)
    Nc = nk + n_todo
    Sk, Sr = sum(d_known), sum(d_ret)
    dmax = (Sk + Sr + sum(hi_unret)) / max(1, Nc)
    if dmax < 0:
        return (Sk + Sr) / max(1, nk + nr), None, None, dmax, "FAIL", "deterministic"
    dmin = (Sk + Sr - sum(1 - h for h in hi_unret)) / max(1, Nc)  # every unplayed map lost on both seats
    if dmin > 0:
        return (Sk + Sr) / max(1, nk + nr), None, None, dmax, "PASS", "deterministic"
    if nr < 2 or n_todo == 0:
        return (Sk + Sr) / max(1, nk + nr), None, None, dmax, None, None
    mr = Sr / nr
    s2 = sum((x - mr) ** 2 for x in d_ret) / (nr - 1)
    proj = (Sk + n_todo * mr) / Nc
    se = (n_todo / Nc) * math.sqrt(max(0.0, 1 - nr / n_todo) * s2 / nr)
    z = OBF_C / math.sqrt(min(1.0, nr / n_todo))
    zf = OBF_C_DFAIL / math.sqrt(min(1.0, nr / n_todo))
    up = proj + zf * se
    if nr >= MIN_STAT and up < 0:
        return proj, up, zf, dmax, "FAIL", "projected"
    if nr >= MIN_STAT and proj - z * se > 0:
        return proj, up, z, dmax, "PASS", "projected"
    return proj, up, z, dmax, None, None


def d_look(name, cand, base, maps, todo, cached, ref):
    """look for STOP_REF: the candidate's map scores by pair_d.scores() on a games.jsonl of what returned so far."""
    rd, rel, rbot = ref
    pd = pair_d()
    b = pd["scores"](rel, rbot)
    tmp = os.path.join(BQ, f".{name}.dlook")
    os.makedirs(tmp, exist_ok=True)
    todo_maps = {m for _, _, m in todo}
    set_maps_ = set(maps)

    def look(got):
        recs = [dict(a=a, b=bb, map=m, ok=True, win=w) for (a, bb, m), w in cached.items()]
        recs += [g for g in got.values() if g.get("ok") and g.get("win") in ("A", "B")]
        with open(os.path.join(tmp, "games.jsonl"), "w") as f:
            f.write("".join(json.dumps(dict(a=g["a"], b=g["b"], map=g["map"], ok=True, win=g["win"])) + "\n" for g in recs))
        c = {m: v for m, v in pd["scores"](os.path.relpath(tmp, ABL), cand).items() if m in set_maps_}
        common = sorted(set(c) & set(b))
        d_known = [c[m] - b[m] for m in common if m not in todo_maps]
        d_ret = [c[m] - b[m] for m in common if m in todo_maps]
        n_todo = sum(1 for m in todo_maps if m in b)
        hi_unret = [1 - b[m] for m in todo_maps if m in b and m not in c]
        mu, lo, hi = pd["boot"](d_known + d_ret)
        proj, up, z, dmax, dec, how = d_rule(d_known, d_ret, hi_unret, n_todo)
        line = (f"paired D vs {os.path.basename(rd)} ({rbot}): n {len(common)}/{len(set_maps_ & set(b))} maps  D {mu:+.3f} "
                f"[{lo:+.3f}, {hi:+.3f}] (pair_d bootstrap); projected final D {proj:+.3f}"
                + (f", upper bound {up:+.3f} (FAIL z {z:.2f}, finite-population se)" if up is not None else "")
                + f"; max final D {dmax:+.3f}; " + (f"DECIDED {dec} ({how})" if dec else "not decided"))
        return line, dec
    return look


def d_final(cand, base, maps, ix, hashes, ref, name):
    """pair_d's per-family D lines over every game the index has on the SET's maps."""
    rd, rel, rbot = ref
    pd = pair_d()
    tmp = os.path.join(BQ, f".{name}.dlook")
    os.makedirs(tmp, exist_ok=True)
    nm, inv = abindex.map_names(), {h: b for b, h in hashes.items()}
    with open(os.path.join(tmp, "games.jsonl"), "w") as f:
        for (ha, hb, mh), g in ix.games.items():
            if nm.get(mh) in set(maps) and ha in inv and hb in inv:
                f.write(json.dumps(dict(a=inv[ha], b=inv[hb], map=nm[mh], ok=True, win=g["win"])) + "\n")
    c = pd["scores"](os.path.relpath(tmp, ABL), cand)
    b = pd["scores"](rel, rbot)
    groups = collections.defaultdict(list)
    for m in sorted(set(c) & set(b)):
        groups["ALL"].append(c[m] - b[m])
        groups[pd["fam"](m)].append(c[m] - b[m])
    out = [f"paired D vs {os.path.basename(rd)} ({rbot}), pair_d.py per map, bootstrap 95% CI:"]
    for k in ["ALL", "pool", "fresh", "heldout", "dom"]:
        if k in groups:
            mu, lo, hi = pd["boot"](groups[k])
            out.append("  %-12s n %3d  D %+.3f [%+.3f, %+.3f]  maps changed %d" % (k, len(groups[k]), mu, lo, hi,
                                                                               sum(1 for d in groups[k] if d != 0)))
    return out


# ---------------------------------------------------------------- OTF: maps generated for one batch, never saved
def pack_xmaps(xm, maps):
    """The batch's on-the-fly maps as ONE file on the shared home. condab_node.sh unpacks it once per node and marks the maps, so KEEP never saves their
    replays, as before. 2 Nov: one .tar.gz per set of maps, shared by all a panel's legs (35 x 20 MB per shipcheck had taken the home over its limit), kept 3 h from last use. -> its path, less the .tar."""
    import hashlib
    import tarfile
    h = hashlib.sha1()
    for name, src in sorted(maps):  # 3 Nov (b935): by content, not name and size: two sets reusing a name could share a pack
        h.update(name.encode() + b"\0" + open(src, "rb").read())
    d = OLD_RUNS + "/otfpacks"
    os.makedirs(d, exist_ok=True)
    x = os.path.join(d, h.hexdigest()[:16])
    if os.path.exists(x + ".tar"):
        os.utime(x + ".tar")
        return x
    tmp = f"{x}.{os.getpid()}.tmp"
    CLEAN_FILES.append(tmp)
    with tarfile.open(tmp, "w:gz", compresslevel=1) as tf:
        for name, src in maps:
            tf.add(os.path.realpath(src), name + ".map26a")  # 8 Nov: never a symlink into /data (dangles on nodes)
    os.replace(tmp, x + ".tar")
    for f in os.listdir(d):
        try:
            if time.time() - os.path.getmtime(os.path.join(d, f)) > 3 * 3600:
                os.remove(os.path.join(d, f))
        except OSError:
            pass
    return x


def otf_clean():
    """Remove exactly the files and (then empty) dirs this process registered; nothing else, never a glob."""
    for f in list(CLEAN_FILES):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
        CLEAN_FILES.remove(f)
    for d in sorted(set(CLEAN_DIRS), key=len, reverse=True):
        try:
            os.rmdir(d)
        except OSError:
            pass
    CLEAN_DIRS.clear()


def dctrig(map_dir):
    """dctrig.py's imports, functions and SHARE / RATIO / MAPS without its report; MAPS -> [map_dir]."""
    tree = ast.parse(open(DCTRIG).read(), DCTRIG)
    keep = []
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            keep.append(n)
        elif isinstance(n, ast.Assign):
            names = {x.id for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
            if names and names <= {"SHARE", "RATIO", "MAPS"}:
                keep.append(n)
    tree.body = keep
    ns = {"__name__": "dctrig"}
    exec(compile(tree, DCTRIG, "exec"), ns)
    ns["MAPS"] = [map_dir]
    return ns


def _otf_build(G, mapcheck, mapfeat, rec, seed, work, name, gen=None, extra=None):
    """One map from (recipe, seed) into work/name.map26a after every check -> (map path, features) or (None, why).
    gen: the generator (default genmaps.generate); extra(map path) -> None or why, a last check on the built map."""
    import contextlib
    import io
    try:
        m = (gen or G.generate)(rec, seed)
        ok, info = G.validate(m, rec)
    except Exception as e:  # noqa: BLE001  (the generators raise RuntimeError, AssertionError, IndexError ...)
        return None, f"generate: {str(e)[:80]}"
    if not ok:
        return None, f"validate: {str(info)[:80]}"
    sp, mp = os.path.join(work, name + ".json"), os.path.join(work, name + ".map26a")
    for f in (sp, mp):
        CLEAN_FILES.append(f)
    try:
        json.dump(G.spec_of(m), open(sp, "w"))
        d = G.build_and_check(m, sp, mp)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            good = mapcheck.audit([work])
        w = G.strict_checks(mapcheck._Mirror(d), rec, d) if rec.get("kind") in ("normal", "long", "split") else None
        if not good or w:
            raise RuntimeError(f"audit: {(buf.getvalue().strip() or w)[:80]}")
        f = mapfeat.analyse(d, name)
        why = extra(mp) if extra else None
        if why:
            raise RuntimeError(why)
    except Exception as e:  # noqa: BLE001
        for x in (sp, mp):
            if os.path.exists(x):
                os.remove(x)
        return None, str(e)[:100]
    os.remove(sp)
    return mp, f


def load_rule(spec):
    """'path.py:func' -> (name, func): the module's imports, functions, classes and UPPERCASE constants only."""
    path, fn = spec.rsplit(":", 1)
    tree = ast.parse(open(path).read(), path)
    keep = []
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            keep.append(n)
        elif isinstance(n, ast.Assign):
            names = {x.id for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
            if names and all(x.isupper() for x in names):
                keep.append(n)
    tree.body = keep
    ns = {"__name__": "otf_rule_" + fn}
    exec(compile(tree, path, "exec"), ns)
    if not callable(ns.get(fn)):
        raise ValueError(f"OTF_RULE {spec}: no function {fn}")
    if ns.get("RECIPES"):
        ns[fn].otf_recipes = list(ns["RECIPES"])  # the rule's own recipe pool (see OTF_RULE in the docstring)
    return fn, ns[fn]


def _rule_job(a):
    """One OTF_RULE slot in a worker process: rejection-sample recipes x seeds until the rule holds."""
    i, work, name = a
    import gendom
    import genmaps as G
    import mapcheck
    import mapfeat
    os.makedirs(work, exist_ok=True)
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    why, info = collections.Counter(), {}

    def check(mp):
        r = _RULE["func"](mp)
        ok, inf = (r if isinstance(r, tuple) else (r, {}))
        info[mp] = inf
        return None if ok else "rule miss"
    for a_ in range(OTF_RULE_TRIES):
        if a_ % 5 == 0:
            own = getattr(_RULE["func"], "otf_recipes", None)
            fam = "dom" if own else rng.choice(["normal", "patho", "dom"])
            rec = (dict({k: rng.choice(v) for k, v in G.SCHED.items()}, kind="normal") if fam == "normal"
                   else dict(rng.choice(_RULE["patho"] if fam == "patho" else (own or _RULE["dom"]))))
            rec["checks"] = 2
        seed = int.from_bytes(os.urandom(6), "big")
        mp, f = _otf_build(G, mapcheck, mapfeat, rec, seed, work, name, gen=gendom.generate, extra=check)
        if mp:
            return dict(i=i, ok=True, rec=rec, seed=seed, mp=mp, f=f, att=a_ + 1, why=dict(why), info=info.get(mp, {}),
                        src=fam)
        why[f.split(" (")[0].split(":")[0]] += 1
    return dict(i=i, ok=False, why=dict(why))


def _slot_job(a):
    """One normal / patho slot in a worker process -> dict (the map is left in its own work dir for the parent)."""
    i, fam, size, kinds, work, name, pool = a
    import genmaps as G
    import mapcheck
    import mapfeat
    os.makedirs(work, exist_ok=True)
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    tried = []
    for r in range(OTF_RECIPES if fam == "normal" else len(kinds)):
        if fam == "normal":
            rec = dict({k: rng.choice(v) for k, v in G.SCHED.items()}, kind="normal", size=size, checks=2)
        else:
            rec = dict(rng.choice([x for x in pool if x["kind"] == kinds[r]]), checks=2)
        n = OTF_SEEDS if fam == "normal" else OTF_PATHO_SEEDS
        for a_ in range(n):
            seed = int.from_bytes(os.urandom(6), "big")
            mp, f = _otf_build(G, mapcheck, mapfeat, rec, seed, work, name)
            if mp:
                return dict(i=i, ok=True, rec=rec, seed=seed, mp=mp, f=f, att=sum(1 for _ in tried) * n + a_ + 1, tried=tried)
        tried.append(rec["kind"] if fam == "patho" else f"recipe {r + 1}")
    return dict(i=i, ok=False, tried=tried)


def _any_job(a):
    return _rule_job(a[1]) if a[0] == "rule" else _slot_job(a[1])


def _otf_worker_init():
    """OTF pool workers die on SIGTERM (30 Oct 23:50: forked workers inherited main()'s SIGTERM -> sys.exit handler, so
    Pool.terminate() made them exit through Python's shutdown, which blocked on a pool lock: join() hung, and the CONFIRM
    legs of 408g and 418l printed nothing until their timebox)."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _otf_take(mp, dst, i, log):
    """Move a worker's finished map into the batch dir -> True, or log and drop the slot when the file is gone (30 Oct
    hxe1: FileNotFoundError at this move killed a CONFIRM=650 run; a rerun worked). The note says whether the slot's
    work dir went too (a clean-up) or only the file."""
    try:
        os.replace(mp, dst)
        return True
    except FileNotFoundError:
        w = os.path.dirname(mp)
        log.append(f"!! otf slot {i}: the worker's map {os.path.basename(mp)} is gone "
                   f"({'its work dir too' if not os.path.isdir(w) else 'work dir still there'}): dropped")
        return False


def otf_generate(d, say=print, own=False, n_normal=3, n_patho=2, n_dom=None, n_rule=None):
    """Generate the batch's maps into d; writes d/otf.json. own: register every file made (and d) for removal at exit."""
    import genbig
    import genmaps as G
    import mapcheck
    import mapfeat
    if own and not os.path.isdir(d):
        CLEAN_DIRS.append(d)
    os.makedirs(d, exist_ok=True)
    work = os.path.join(d, "work")
    os.makedirs(work, exist_ok=True)
    CLEAN_DIRS.append(work)
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    tag = os.urandom(3).hex()
    sizes = [("S", "M", "L")[j % 3] for j in range(n_normal)]  # one each for 3; an even spread for more
    rng.shuffle(sizes)
    used = collections.Counter()  # pathology types so far: each slot takes a least-used one (5 slots: all distinct)
    pool = genbig.patho_recipes(100)  # gen_p's recipe draws (random columns + the type's fixes), 20 of each type
    n_dom = int(os.environ.get("OTF_DOM", "0") or 0) if n_dom is None else n_dom
    rule_spec = os.environ.get("OTF_RULE") or (GEMCLU_RULE if os.environ.get("OTF_GEMCLU") else "")
    if n_rule is None:
        n_rule = int(os.environ.get("OTF_RULE_K") or os.environ.get("OTF_GEMCLU") or 5) if rule_spec else 0
    rname = None
    if n_rule:
        import gendom
        rname, _RULE["func"] = load_rule(rule_spec)
        _RULE["patho"], _RULE["dom"] = pool, gendom.recipes(200)
    slots = ([("normal", sz) for sz in sizes] + [("patho", None)] * n_patho + [("dom", None)] * n_dom
             + [("rule", None)] * n_rule)
    maps, log = [], []
    if n_dom:
        import gendom  # (it points genmaps.generate at its own, which is the same for recipes without a 'dom' structure)
        os.environ["DC_MODE"] = "x"  # dctrig: monoliths out of both the share and the ratio
        tr = dctrig(work)
        singles = [x for x in gendom.recipes(200) if x.get("dom", {}).get("kind") == "single"]
        trig_info = {}

        def trigger(mp):
            r = tr["trig"](os.path.basename(mp)[:-7])
            trig_info[mp] = r
            if not r or not r["fire"] or r.get("gems", 0) < DOM_MIN_GEMS:
                return (f"trigger miss (share {r['share']:.2f}, ratio {r['ratio']:.1f}, gems {r.get('gems', 0)})"
                        if r else "trigger unread")
            return None
        log.append(f"otf dom trigger: dctrig.py trig() DC_MODE=x, share >= {tr['SHARE']}, ratio >= {tr['RATIO']}, "
                   f"gems >= {DOM_MIN_GEMS}")
    # normal and patho slots in parallel (a slow pathology type no longer holds up the batch); every path a worker may
    # write is registered first, so an error or a kill still removes it
    order = list(G.PATHO)
    rng.shuffle(order)
    jobs, pj = [], 0
    for i, (fam, size) in enumerate(slots, 1):
        if fam == "dom":
            continue
        w = os.path.join(work, f"w{i}")
        if fam == "rule":
            CLEAN_DIRS.append(w)
            CLEAN_FILES.extend(os.path.join(w, f"otf_{tag}_{i}{x}") for x in (".json", ".map26a"))
            jobs.append(("rule", (i, w, f"otf_{tag}_{i}")))
            continue
        CLEAN_DIRS.append(w)
        CLEAN_FILES.extend(os.path.join(w, f"otf_{tag}_{i}{x}") for x in (".json", ".map26a"))
        kinds = None
        if fam == "patho":
            first = order[pj % len(order)]
            pj += 1
            kinds = [first] + rng.sample([k for k in G.PATHO if k != first], len(G.PATHO) - 1)
        jobs.append(("slot", (i, fam, size, kinds, w, f"otf_{tag}_{i}", pool)))
    pre = {}
    if jobs:  # a total budget: a map build that never returns (mkmap has no timeout) must not hang the batch (30 Oct cf56)
        import multiprocessing
        budget = float(os.environ.get("OTF_GEN_BUDGET", 240))
        end = time.time() + budget
        mpool = multiprocessing.get_context("fork").Pool(min(8, len(jobs)), initializer=_otf_worker_init)
        try:
            it = mpool.imap_unordered(_any_job, jobs)
            for _ in jobs:
                try:
                    res = it.next(timeout=max(1, end - time.time()))
                except multiprocessing.TimeoutError:
                    break
                pre[res["i"]] = res
        finally:
            mpool.terminate()
            for w in list(getattr(mpool, "_pool", [])):  # a worker that survived terminate() must not hang join()
                try:
                    if w.is_alive():
                        w.kill()
                except (OSError, ValueError, AttributeError):
                    pass
            mpool.join()
        for j in jobs:
            i = j[1][0]
            if i not in pre:
                pre[i] = dict(i=i, ok=False, tried=[f"generation not done within OTF_GEN_BUDGET {budget:.0f} s"],
                              why={"timeout": 1})
    for i, (fam, size) in enumerate(slots, 1):
        name = f"otf_{tag}_{i}"
        got, tried = None, []
        if fam == "rule":
            res = pre[i]
            why = ", ".join(f"{k} {v}" for k, v in sorted(res["why"].items(), key=lambda kv: -kv[1]))
            if not res["ok"]:
                log.append(f"!! otf slot {i} (rule {rname}): no map met the rule in {OTF_RULE_TRIES} draws ({why}): dropped")
                continue
            rec, seed, mp, f = res["rec"], res["seed"], res["mp"], res["f"]
            dst = os.path.join(d, name + ".map26a")
            if own:
                CLEAN_FILES.append(dst)
            if not _otf_take(mp, dst, i, log):
                continue
            log.append(f"otf slot {i} (rule {rname}): {res['att']} draws ({why or 'first draw'}); rule info {res['info']}")
            maps.append(dict(name=name, family="rule", kind=f"rule_{rname}/{res['src']}/{rec['kind']}", size=rec.get("size"),
                             seed=seed, recipe=rec, W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"),
                             s2s=f.get("s2s"), attempts=res["att"], rule=dict(name=rname, **res["info"])))
            continue
        if fam != "dom":
            res = pre[i]
            tried = res["tried"]
            if not res["ok"]:
                log.append(f"!! otf slot {i} ({fam} {size or ''}): no valid map after {', '.join(tried)}: dropped")
                continue
            rec, seed, mp, f, att = res["rec"], res["seed"], res["mp"], res["f"], res["att"]
            dst = os.path.join(d, name + ".map26a")
            if own:
                CLEAN_FILES.append(dst)
            if not _otf_take(mp, dst, i, log):
                continue
            if tried:
                log.append(f"otf slot {i}: {', '.join(tried)} gave no valid map in {OTF_SEEDS if fam == 'normal' else OTF_PATHO_SEEDS} "
                           f"seeds each: fell back to {rec['kind']}")
            maps.append(dict(name=name, family=fam, kind=rec["kind"], size=rec.get("size"), seed=seed, recipe=rec,
                             W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"), s2s=f.get("s2s"), attempts=att))
            continue
        if fam == "dom":
            why = collections.Counter()
            for a in range(OTF_DOM_TRIES):
                if a % 10 == 0:
                    rec = dict(rng.choice(singles), checks=2)
                seed = int.from_bytes(os.urandom(6), "big")
                mp, f = _otf_build(G, mapcheck, mapfeat, rec, seed, work, name, gen=gendom.generate, extra=trigger)
                if mp:
                    tinfo = trig_info.get(mp) or {}
                    got = (rec, seed, mp, f, a + 1)
                    break
                why[f.split(" (")[0].split(":")[0]] += 1
            if not got:
                log.append(f"!! otf slot {i} (dom): no map met the trigger in {OTF_DOM_TRIES} attempts "
                           f"({', '.join(f'{k} {v}' for k, v in why.most_common())}): dropped")
                continue
            rec, seed, mp, f, att = got
            dst = os.path.join(d, name + ".map26a")
            if own:
                CLEAN_FILES.append(dst)
            if not _otf_take(mp, dst, i, log):
                continue
            CLEAN_FILES.remove(mp)
            log.append(f"otf slot {i} (dom): {att} attempts" + (f" ({', '.join(f'{k} {v}' for k, v in why.most_common())})"
                                                               if why else ""))
            maps.append(dict(name=name, family="dom", kind=f"dom_{rec['dom']['kind']}", size=rec.get("size"), seed=seed,
                             recipe=rec, W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"), s2s=f.get("s2s"),
                             attempts=att, trigger=dict(share=round(tinfo.get("share", 0), 3),
                                                        ratio=round(tinfo.get("ratio", 0), 2), gems=tinfo.get("gems"))))
            continue
        for r in range(OTF_RECIPES if fam == "normal" else len(G.PATHO)):
            if fam == "normal":
                rec = dict({k: rng.choice(v) for k, v in G.SCHED.items()}, kind="normal", size=size, checks=2)
            else:
                left = [k for k in G.PATHO if k not in tried]
                if not left:
                    break
                kind = min(left, key=lambda k: (used[k], rng.random()))
                rec = dict(rng.choice([x for x in pool if x["kind"] == kind]), checks=2)
            for a in range(OTF_SEEDS):
                seed = int.from_bytes(os.urandom(6), "big")
                mp, f = _otf_build(G, mapcheck, mapfeat, rec, seed, work, name)
                if mp:
                    got = (rec, seed, mp, f, len(tried) * OTF_SEEDS + a + 1)
                    break
            if got:
                break
            tried.append(rec["kind"] if fam == "patho" else f"recipe {r + 1}")
        if not got:
            log.append(f"!! otf slot {i} ({fam} {size or ''}): no valid map after {', '.join(tried)}: dropped")
            continue
        rec, seed, mp, f, att = got
        if fam == "patho":
            used[rec["kind"]] += 1
        dst = os.path.join(d, name + ".map26a")
        if own:
            CLEAN_FILES.append(dst)
        os.replace(mp, dst)
        CLEAN_FILES.remove(mp)
        if tried:
            log.append(f"otf slot {i}: {', '.join(tried)} gave no valid map in {OTF_SEEDS} seeds each: fell back to "
                       f"{rec['kind']}")
        maps.append(dict(name=name, family=fam, kind=rec["kind"], size=rec.get("size"), seed=seed, recipe=rec,
                         W=f.get("W"), H=f.get("H"), T=f.get("T"), gems=f.get("gems"), s2s=f.get("s2s"), attempts=att))
    for sub in sorted(os.listdir(work)):
        try:
            os.rmdir(os.path.join(work, sub))  # the slots' (now empty) work dirs
        except OSError:
            pass
    os.rmdir(work) if not os.listdir(work) else None
    if own:
        CLEAN_FILES.append(os.path.join(d, "otf.json"))
    json.dump(dict(tag=tag, maps=maps, log=log, rule=rname, files=[m["name"] + ".map26a" for m in maps]),
              open(os.path.join(d, "otf.json"), "w"), indent=1)
    for line in log:
        say(line)
    return dict(dir=d, tag=tag, maps=maps, log=log, rule=rname)


def otf_own(d):
    """Register the files of an OTF dir this process created (otf.json's exact list) for removal at exit."""
    info = json.load(open(os.path.join(d, "otf.json")))
    CLEAN_FILES.extend(os.path.join(d, f) for f in info["files"])
    CLEAN_FILES.append(os.path.join(d, "otf.json"))
    CLEAN_DIRS.append(d)


def otf_cli(a):
    """--otf-gen [DIR] (prints DIR) | --otf-clean DIR | --otf-regen SEED RECIPE_JSON OUT.map26a"""
    if a[0] == "--otf-gen":
        d = a[1] if len(a) > 1 else os.path.join(OTF_TMP, "scr_" + os.urandom(4).hex())
        if os.path.exists(os.path.join(d, "otf.json")):
            sys.exit(f"{d} already holds OTF maps")
        try:
            otf_generate(d, say=lambda x: print(x, file=sys.stderr), own=True)
        except BaseException:
            otf_clean()  # a failed generation leaves nothing behind
            raise
        CLEAN_FILES.clear()  # success: the caller (scr.sh) owns the maps and removes them with --otf-clean
        CLEAN_DIRS.clear()
        print(d)
    elif a[0] == "--otf-clean":
        if os.path.exists(os.path.join(a[1], "otf.json")):
            otf_own(a[1])
            otf_clean()
    elif a[0] == "--otf-regen-many":
        # 11 Nov (Coordinator, /var: root's syslog logs ~1.9 KB per process start; inforead's resume ran a python + node per map): one
        # process rebuilds a list of maps (FILE: 'SEED<TAB>RECIPE_JSON<TAB>OUT' lines), reusing one node mkmap server; a failed map is skipped
        ok = 0
        for ln in open(a[1]):
            p = ln.rstrip("\n").split("\t")
            if len(p) != 3:
                continue
            try:
                otf_cli(["--otf-regen", p[0], p[1], p[2]])
                ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"{p[2]}: FAILED {str(e)[:160]}")
        print(f"otf-regen-many: {ok} maps rebuilt")
    elif a[0] == "--otf-regen":
        # 9 Nov 19:10Z: no slot here. A cap added at 18:00 used the same lock folder as inforead's own regen cap (cxe/regenslots, 6 slots, held
        # by the inforead parent around each regen): parents held the slots their children waited for and every resume deadlocked for 67 min.
        # inforead's cap already bounds the regens machine-wide.
        import genmaps as G
        rec, out = json.loads(a[2]), a[3]
        if rec.get("weird") or rec.get("nf"):  # stratmaps' genweird and genfam maps: their own builders, as stratmaps built them
            import genfam
            import genweird
            fam, mod = (rec.pop("weird"), genweird) if rec.get("weird") else (rec.pop("nf"), genfam)
            d, name = os.path.split(os.path.abspath(out))
            mod.build_one(fam, name[:-7], int(a[1]), rec, d)
            if os.path.exists(out[:-7] + ".json"):  # w_dashaltar and w_dashgolem build through _otf_build, which leaves none
                os.remove(out[:-7] + ".json")
            print(f"{out}: {fam}")
            return
        if rec.get("dom"):
            import gendom  # noqa: F401  (its generate adds the dominant structure)
        m = G.generate(rec, int(a[1]))
        sp = out[:-7] + ".spec.json"
        json.dump(G.spec_of(m), open(sp, "w"))
        G.build_and_check(m, sp, out)
        os.remove(sp)
        print(f"{out}: {m.W}x{m.H} T{m.T} ({rec.get('kind')})")


# ---------------------------------------------------------------- CONFIRM: a fresh-map leg, never saved
def confirm(cand, base, name, n, hashes, say, t0):
    """CONFIRM=N: N on-the-fly maps (3:2 normal : patho), CAND vs BASE both seats; results only in NAME.condor.txt."""
    import abstat
    n_norm = round(n * 3 / 5)
    od = os.path.join(OTF_TMP, f"{name}_{os.urandom(4).hex()}")
    otf = otf_generate(od, say, own=True, n_normal=n_norm, n_patho=n - n_norm, n_dom=0, n_rule=0)
    fam = {m["name"]: m["family"] for m in otf["maps"]}
    say(f"CONFIRM: {len(otf['maps'])} of {n} maps generated in {od} ({sum(v == 'normal' for v in fam.values())} normal, "
        f"{sum(v == 'patho' for v in fam.values())} patho; deleted at the end)")
    ms = list(fam)
    random.Random(int.from_bytes(os.urandom(8), "big")).shuffle(ms)  # every job a mix of kinds and sizes
    games = [g for m in ms for g in ((cand, base, m), (base, cand, m))]
    pj = job_size(len(games))
    preflight((len(games) + pj - 1) // pj)
    sync([cand, base], hashes, [])
    k = 1
    while any(os.path.exists(os.path.join(d, f"cq_{name}_{k}")) for d in (RUNS, OLD_RUNS, ARCHIVE, ABL)):
        k += 1
    out = os.path.join(RUNS, f"cq_{name}_{k}")
    os.makedirs(out)
    OUTS.append(out)
    xm = pack_xmaps(os.path.join(out, "otf"), [(m, os.path.join(od, m + ".map26a")) for m in ms])
    tb = t0 + float(os.environ["CONDAB_TIMEBOX"]) if os.environ.get("CONDAB_TIMEBOX") else None
    got, stopped = play(out, games, int(os.environ.get("CONDAB_TIMEOUT", 7200)), say, False, None, False, xmaps=xm,
                        per_job=pj, timebox=tb)
    otf_clean()
    archive(out)
    res = {(g["a"], g["b"], g["map"]): g for g in got.values() if g.get("ok") and g.get("win") in ("A", "B")}
    rows, side = [], {cand: collections.Counter(), base: collections.Counter()}
    for g in res.values():
        for b, sd in ((g["a"], g["sa"]), (g["b"], g["sb"])):
            side[b]["faults"] += int(sd.get("faults", 0))
            side[b]["fault_games"] += int(sd.get("faults", 0)) > 0
            side[b]["fuel"] += int(sd.get("fuel", 0))
            side[b]["fuel_games"] += int(sd.get("fuel", 0)) > 0
    word, per = {1.0: "won both", 0.5: "split", 0.0: "lost both"}, {}
    changed = 0  # maps whose two seats' games differ: identical games on a map = CAND plays exactly like BASE there
    for m in fam:
        g1, g2 = res.get((cand, base, m)), res.get((base, cand, m))
        if g1 and g2:
            changed += (g1["win"], g1.get("rounds"), g1["sa"], g1["sb"]) != (g2["win"], g2.get("rounds"), g2["sa"], g2["sb"])
            sc = ((g1["win"] == "A") + (g2["win"] == "B")) / 2
            per[m] = sc
            rows.append((m, fam[m], sc, g1["sa"].get("gems", 0) + g2["sb"].get("gems", 0),
                         g1["sb"].get("gems", 0) + g2["sa"].get("gems", 0)))
    wall = time.time() - t0
    L = [f"# condab {name}: {cand}@{hashes[cand]} vs {base}@{hashes[base]}, CONFIRM {n} on-the-fly maps (never saved), "
         f"{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
         f"games: {len(res)} of {len(games)} played on Condor ({len(otf['maps'])} maps generated); wall {wall / 60:.1f} min"
         + (f"; timebox at {stopped[0]}% of jobs: the rest not played" if stopped else ""), "",
         f"confirm maps (fresh os.urandom seeds, 3:2 normal : patho; not in any pool, index, abstat or sprt):"]
    tot = abstat.summarize(rows)
    if tot:
        L.append(f"  {'confirm':8s}{abstat.line(tot)}")
        for f in ("normal", "patho"):
            st = abstat.summarize([r for r in rows if r[1] == f])
            if st:
                L.append(f"  {f:8s}{abstat.line(st)}")
        L.append(f"  verdict: {abstat.verdict(tot, cand, base)}")
        L.append(f"  changed  {changed} of {len(rows)} maps (the two seats' games differ; 0 = CAND plays exactly like BASE "
                 f"on every map)")
    else:
        L.append("  no complete map pairs")
    L += ["", "bot faults / fuel exhaustions per side:"]
    for b in (cand, base):
        x = side[b]
        L.append(f"  {b:24s} faults {x['faults']} (in {x['fault_games']} games)  fuel exhaustions {x['fuel']} (in {x['fuel_games']} games)")
    L += ["", "maps (rebuild one to debug: python3 -I tools/lab/condab.py --otf-regen SEED 'RECIPE' OUT.map26a):"]
    for om in otf["maps"]:
        L.append(f"  {om.get('name', '?')} {om.get('family', '?')}/{om.get('kind', '?')} size {om.get('size', '?')} {om.get('W', '?')}x{om.get('H', '?')} T{om.get('T', '?')} gems "
                 f"{om.get('gems', '?')}: {cand} {word.get(per.get(om.get('name')), 'not returned')} | seed {om.get('seed', '?')} recipe "
                 f"{json.dumps(om.get('recipe', {}), separators=(',', ':'))}")
    L += [f"  {x}" for x in otf.get("log", [])]
    txt = "\n".join(L) + "\n"
    open(os.path.join(BQ, name + ".condor.txt"), "w").write(txt)
    print(txt)


# ---------------------------------------------------------------- main
import abindex  # noqa: E402


def main():
    a = sys.argv[1:]
    if a[:1] == ["--stat"]:
        sys.exit(node_stat(*a[1:6]))
    ok_ = os.environ.get("OTF_KEEP", "")
    if ok_ and not os.path.isabs(ok_):  # 12 Nov (Builder: b2240's OTF_KEEP=1 wrote replays into the repo as ./1): "1"/"yes"/"true" means the
        #      default keep dir under /data; any other relative path is refused (cwd is often the repo, whose home has an inode quota)
        if ok_.lower() in ("1", "yes", "true", "on"):
            os.environ["OTF_KEEP"] = f"/data/USER/st/otfkeep/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{os.getpid()}"
            os.makedirs(os.environ["OTF_KEEP"], exist_ok=True)
            print(f"condab: OTF_KEEP={ok_} -> {os.environ['OTF_KEEP']}", file=sys.stderr)
        else:
            sys.exit(f"condab: OTF_KEEP must be an absolute directory (got {ok_!r}); OTF_KEEP=1 keeps in /data/USER/st/otfkeep/")
    keep = os.environ.get("KEEP") == "1" or "--keep" in a
    a = [x for x in a if x != "--keep"]
    if len(a) < 3 or a[0].startswith("-"):
        print(__doc__)
        sys.exit(1)
    cand, base, name = a[0], a[1], a[2]
    # 10 Nov (Tool Builder: `SET=heldout condab.sh ...` ran ALL sets, 13,388 games): the set is the 4th argument; SET from the environment now
    # counts too when no argument names one (callers that mean otherwise already drop SET from the env they pass)
    spec = a[3] if len(a) > 3 else (os.environ.get("SET") or "all")
    if not re.fullmatch(r"[A-Za-z0-9_+-][A-Za-z0-9._+-]*", name):
        sys.exit(f"NAME must be a plain run name ([A-Za-z0-9._+-], no leading '.'): {name}")
    try:
        os.nice(10)
    except OSError:
        pass
    t0 = time.time()
    os.makedirs(BQ, exist_ok=True)
    logf = open(os.path.join(BQ, name + ".condor.log"), "a")

    def say(s):
        s = f"{time.strftime('%T')} {s}"
        print(s, flush=True)
        logf.write(s + "\n")
        logf.flush()
    hashes = {}
    for b in (cand, base):
        if not os.path.isdir(os.path.join(REPO, "bots", b, "src")):
            sys.exit(f"no bots/{b}/src")
        hashes[b] = abindex.bot_hash(b)
    if hashes[cand] == hashes[base] and not (cand == base and os.environ.get("OTF_ONE_SEAT") == "1"):  # OTF_ONE_SEAT: draftstock's one-game BOT v BOT draft read (8 Nov)
        sys.exit(f"{cand} and {base} have the same source ({hashes[cand]})")
    hc, hb = hashes[cand], hashes[base]
    if os.environ.get("CONDAB_NAME_REUSE") != "1":  # a NAME belongs to one bot pair (29 Oct: four bots ran as nd185)
        used = set()
        for bt in glob.glob(os.path.join(ABL, f"cq_{name}_*", "bots.txt")):
            used.add(" vs ".join(x.split()[0] for x in open(bt) if x.strip()))
        hm = re.match(r"# condab \S+: (\S+?)@(\S+) vs (\S+?)@(\S+),", (open(os.path.join(BQ, name + ".condor.txt")).readline()
                                                           if os.path.exists(os.path.join(BQ, name + ".condor.txt")) else ""))
        if hm:
            used.add(f"{hm.group(1)} vs {hm.group(3)}")
        other = [u for u in used if u != f"{cand} vs {base}"]
        # 9 Nov (Deep: wglb / wglbi INCONCLUSIVE twice): shipcheck's trunk-code gate tag is a SOURCE-hash tag (tc + cand hash + live hash), so
        # two trunks with the same code at flag 0 share it; the second was refused here as "used by" the first and its fresh leg read nan.
        # Same source hashes as the NAME's last run = the same pair of programs: not a clash.
        _same = lambda x, y: bool(x and y) and (x.startswith(y) or y.startswith(x))  # noqa: E731
        if other and hm and _same(hm.group(2), hc) and _same(hm.group(4), hb):
            other = []
        if other:
            sys.exit(f"condab: NAME {name} was used by {other[0]}; pick a new NAME (CONDAB_NAME_REUSE=1 overrides)")
    if os.environ.get("CONFIRM", "0") not in ("", "0"):
        return confirm(cand, base, name, int(os.environ["CONFIRM"]), hashes, say, t0)
    maps = set_maps(spec)
    big = int(os.environ.get("BIG", "0") or 0)
    if big:  # BIG=N (30 Oct): + the first N maps of the frozen decision bank (tools/lab/mapbank.py), cached like the pool
        import mapbank
        bk = "bk" if os.environ.get("BANK", "2") == "1" else "bk2"  # BANK=1: bank v1 (comparisons only); default v2 (ladder-matched)
        if os.environ.get("BIGSET", "") == "big2":  # 11 Nov: BIG2 (tools/lab/big2.py): new, deduped, current-ladder bands; packed like ladderw
            import big2
            import ladderw
            bank, lab = big2.bank_list(big), "BIG2 (BIGSET=big2)"
            pk = ladderw.packed()
            unpacked = [m for m in bank if m not in pk]
            if unpacked:
                sys.exit(f"BIGSET=big2: {len(unpacked)} maps are not packed: run python3 -I tools/lab/big2.py pack")
        elif os.environ.get("BIGSET", "") in ("ladderw", "ladderw_nh"):  # 31 Oct: the ladder-weighted set (tools/lab/ladderw.py), not the default
            import ladderw
            bank, lab = ladderw.bank_list(big), f"ladder-weighted (BIGSET={os.environ.get('BIGSET')})"
            pk = ladderw.packed()
            unpacked = [m for m in bank if not m.startswith(ladderw.BANKPFX) and m not in pk]
            if unpacked:
                sys.exit(f"BIGSET=ladderw: {len(unpacked)} maps are not packed: run python3 -I tools/lab/ladderw.py pack")
        else:
            bank, lab = mapbank.bank_list(bk, big), f"frozen bank maps (gen_{bk}_*)"
        have = set(maps)
        maps = maps + [m for m in bank if m not in have]
        say(f"BIG={big}: + {len(bank)} {lab}{'' if len(bank) >= big else ' (the set has no more)'}")
        if not (os.environ.get("STOP") or os.environ.get("CONDAB_STOP")):  # losers stay cheap: early FAIL only
            os.environ["STOP"] = "1"
            os.environ.setdefault("CONDAB_HI_FAIL", "0.5,2.58,300")
            say("BIG: STOP=1 with CONDAB_HI_FAIL 0.5,2.58,300 (FAIL once >= 300 pairs have score + 2.58 se < 0.5)")
    mp = abindex.maps()
    miss = [m for m in maps if m not in mp]
    if miss:
        say(f"!! {len(miss)} maps not in {WORK_MAPS} are skipped: {' '.join(miss[:8])}")
    maps = [m for m in maps if m in mp]
    mlist = os.path.join(BQ, name + ".maps")
    open(mlist, "w").write("".join(m + "\n" for m in maps))
    say(f"{cand}@{hc} vs {base}@{hb}, SET {spec}: {len(maps)} maps, {2 * len(maps)} games")
    force = os.environ.get("CONDAB_FORCE") == "1"
    kept = kept_replays(hashes) if keep else {}
    # 4 Nov: an on-the-fly-only batch (panel legs: 0 saved maps) needs nothing from the index (2.8 s a leg); its games are never indexed
    ix = abindex.Index({hc, hb}) if maps else _NoIndex()
    todo, reused = [], 0
    for m in maps:
        for x, y in ((cand, base), (base, cand)):
            if keep and (hashes[x], hashes[y], m) not in kept:
                todo.append((x, y, m))
            elif not force and (hashes[x], hashes[y], mp[m][0]) in ix.games:
                reused += 1
            else:
                todo.append((x, y, m))
    say(f"{reused} games reused from the index{' (with kept replays)' if keep else ''}, {len(todo)} to play")
    rank = {m: i for i, m in enumerate(balanced_order(sorted({m for _, _, m in todo})))}
    first = set(read(os.environ["CONDAB_FIRST"])) if os.environ.get("CONDAB_FIRST") else set()  # e.g. trigger maps
    todo.sort(key=lambda g: (g[2] not in first, rank[g[2]], g[0] != cand))  # CONDAB_FIRST maps first, then family-balanced
    tset = set(todo)
    cached = {}
    for m in maps:
        for x, y in ((cand, base), (base, cand)):
            g = ix.games.get((hashes[x], hashes[y], mp[m][0]))
            if g and (x, y, m) not in tset:
                cached[(x, y, m)] = g["win"]
    stop_v = os.environ.get("STOP") or os.environ.get("CONDAB_STOP") or "0"
    stop = stop_v in ("1", "2")
    stop_pass = stop_v == "2" or os.environ.get("STOP_PASS") == "1"
    timebox = t0 + float(os.environ["CONDAB_TIMEBOX"]) if os.environ.get("CONDAB_TIMEBOX") else None
    ref = ref_run(os.environ["STOP_REF"], base) if os.environ.get("STOP_REF") else None
    rh = {}
    if ref:
        say(f"STOP_REF: paired D vs {ref[0]} ({ref[2]} against {base}); FAIL-only early stop")
        try:
            rh = {p[0]: p[1] for p in (ln.split() for ln in open(os.path.join(ref[0], "bots.txt"))) if len(p) > 1}
        except OSError:
            rh = {}
        if rh.get(base, hashes[base]) != hashes[base]:
            say(f"!! STOP_REF: {base} played {ref[0]} as source {rh[base]}, now {hashes[base]}: D compares different opponents")
    otf, otf_games, rb, rbh = None, [], None, None
    if os.environ.get("OTF", "1") != "0":
        od = os.environ.get("OTF_DIR")
        try:
            if od and os.path.exists(os.path.join(od, "otf.json")):
                otf = dict(json.load(open(os.path.join(od, "otf.json"))), dir=od)
                say(f"OTF: {len(otf['maps'])} maps from OTF_DIR {od} (left for its owner to delete)")
            else:
                own = not od
                od = od or os.path.join(OTF_TMP, f"{name}_{os.urandom(4).hex()}")
                otf = otf_generate(od, say, own=own)
                say(f"OTF: {len(otf['maps'])} maps generated in {od}{' (deleted at the end)' if own else ''}")
        except Exception as e:  # noqa: BLE001  (the A/B must not die with the generator)
            say(f"!! OTF: map generation failed ({str(e)[:160]}): this batch runs without on-the-fly maps")
            otf_clean()
            otf = None
    if otf and ref and ref[2] != cand:
        rbh = abindex.bot_hash(ref[2])
        if rbh:
            rb = ref[2]
            if rh.get(rb, rbh) != rbh:
                say(f"!! OTF: {rb} is source {rbh} now, {rh[rb]} in {ref[0]}: its OTF games are of the current source")
        else:
            say(f"!! OTF: no bots/{ref[2]}/src: the reference does not play the OTF maps (no OTF paired D)")
    for om in (otf or {}).get("maps", []):
        # OTF_ONE_SEAT=1 (8 Nov, draftstock lineups): one game a map; a BOT v BOT draft game gives both seats' lineups, the other seat is the same game with the sides swapped
        otf_games += [(cand, base, om["name"])] if os.environ.get("OTF_ONE_SEAT") == "1" else [(cand, base, om["name"]), (base, cand, om["name"])]
        if rb:
            otf_games += [(rb, base, om["name"]), (base, rb, om["name"])]
    played = failed = 0
    stopped, interim = None, []
    otf_res = {}
    if todo or otf_games:
        pj = job_size(len(todo) + len(otf_games))
        njobs = (len(todo) + len(otf_games) + pj - 1) // pj
        t_pre = time.time()
        preflight(njobs)
        t_sync = time.time()
        sync([cand, base] + ([rb] if rb else []), dict(hashes, **({rb: rbh} if rb else {})), sorted({m for _, _, m in todo}))
        say(f"pre-game: preflight {t_sync - t_pre:.1f} s, sync {time.time() - t_sync:.1f} s (lock wait {SYNC_WAIT[0]:.1f} s), {len({m for _, _, m in todo})} maps")
        k = 1
        while os.path.exists(os.path.join(OLD_RUNS, f"cq_{name}_{k}")) or os.path.exists(os.path.join(RUNS, f"cq_{name}_{k}")) or os.path.exists(os.path.join(ARCHIVE, f"cq_{name}_{k}")) \
                or os.path.exists(os.path.join(ABL, f"cq_{name}_{k}")):
            k += 1
        out = os.path.join(RUNS, f"cq_{name}_{k}")
        OUTS.append(out)
        look = interim_rule(cand, base, maps, todo, cached)
        dlook = d_look(name, cand, base, maps, todo, cached, ref) if ref else None

        def look_log(got):
            """-> (lines, decision that stops the batch now, decision for a timebox)"""
            line, dec = look(got)
            interim.append(line)
            if not dlook:
                act = dec if (dec == "FAIL" and stop) or (dec == "PASS" and stop_pass) else None
                return line, act, dec
            dline, ddec = dlook(got)
            interim.append(dline)
            lab = ddec and f"{ddec} (paired D {'<' if ddec == 'FAIL' else '>'} 0 vs {os.path.basename(ref[0])})"
            return [line, dline], (lab if ddec == "FAIL" or (ddec == "PASS" and stop_pass) else None), lab
        games = todo + otf_games
        grp = []  # whole maps as index lists; one OTF map at the head of each of the first jobs
        for j, g in enumerate(games):
            if grp and games[grp[-1][-1]][2] == g[2] and (grp[-1][-1] < len(todo)) == (j < len(todo)):
                grp[-1].append(j)
            else:
                grp.append([j])
        ngr, ogr = [x for x in grp if x[0] < len(todo)], [x for x in grp if x[0] >= len(todo)]
        per = max(1, pj // 2 - 1)
        order = []
        for gi, x in enumerate(ngr):
            if gi % per == 0 and gi // per < len(ogr):
                order += ogr[gi // per]
            order += x
        order += [j for x in ogr[(len(ngr) + per - 1) // per:] for j in x]
        xm = None
        if otf_games:
            os.makedirs(out)
            xm = pack_xmaps(os.path.join(out, "otf"), [(om["name"], os.path.join(otf["dir"], om["name"] + ".map26a")) for om in otf["maps"]])
        if os.environ.get("OTF_ROUNDS", "").isdigit() and otf_games:
            say(f"!! OTF_ROUNDS {os.environ['OTF_ROUNDS']}: the on-the-fly games stop at that round, so their scores are not game results")
        # 10 Nov (draftprobe, HOST /var): OTF_ROUNDS reaches the nodes through the keep dir's .rounds only; with no saved-map games,
        # a keep dir without .otf caps the on-the-fly games and keeps nothing, so a round-capped leg needs no OTF_KEEP (OTF_LINEUPS reads it)
        capkeep = bool(os.environ.get("OTF_ROUNDS", "").isdigit() and otf_games and not todo)
        got, stopped = play(out, games, int(os.environ.get("CONDAB_TIMEOUT", 7200)), say, keep or bool(os.environ.get("OTF_KEEP") and otf_games) or capkeep,
                            look_log if todo else None, stop or stop_pass or bool(ref), order=order, xmaps=xm,
                            per_job=pj, timebox=timebox)
        otf_clean()  # the OTF maps (this batch's copies, and its own generated maps) are gone before anything else
        otf_res = {(g["a"], g["b"], g["map"]): g["win"] for j, g in got.items()
                   if j > len(todo) and g.get("ok") and g.get("win") in ("A", "B")}
        if os.environ.get("OTF_GAMES"):  # 1 Nov (shipcheck death guard): OTF games are never archived; append their records
            with open(os.environ["OTF_GAMES"], "a") as fo:
                for j, g in sorted(got.items()):
                    if j > len(todo) and g.get("ok") and g.get("win") in ("A", "B"):
                        fo.write(json.dumps(dict(run=name, a=g["a"], b=g["b"], map=g["map"], win=g["win"],
                                                 sa=g.get("sa", {}), sb=g.get("sb", {}), **g.get("cx", {}))) + "\n")
        if os.environ.get("OTF_LINEUPS"):  # 10 Nov (draftprobe): every returned OTF game's lineup, decided or not (a round-capped game
            with open(os.environ["OTF_LINEUPS"], "a") as fo:  # is a draw at the cap), so a draft probe needs no replay decode
                for j, g in sorted(got.items()):
                    if j > len(todo) and g.get("ok") and (g.get("cx") or {}).get("lu"):
                        fo.write(json.dumps(dict(run=name, j=j, a=g["a"], b=g["b"], map=g["map"], win=g.get("win"), lu=g["cx"]["lu"])) + "\n")
        got_otf = {j: g for j, g in got.items() if j > len(todo)}  # OTF_KEEP's metadata (3 Nov)
        got = {j: g for j, g in got.items() if j <= len(todo)}
        if any(src_hash(os.path.join(REPO, "bots", b)) != hashes[b] for b in (cand, base)):
            say("!! a bot's source changed during the batch: its results are recorded under the hash it was synced with")
        rd = os.path.join(ABL, f"cq_{name}_{k}")
        if todo:
            write_run(rd, todo, got, hashes)
        if os.environ.get("OTF_KEEP") and otf_games:
            nko = unpack_otf_keep(out, os.environ["OTF_KEEP"], name, games, len(todo), got_otf, otf, cand, base, rd if keep and todo else None)
            say(f"OTF_KEEP: {nko} of {len(otf_games)} on-the-fly replays kept in {os.environ['OTF_KEEP']} (set.json: a readmany source)")
        if keep and todo:
            nk = unpack_keep(out, rd)
            say(f"{nk} replays kept in {rd}/rep ({sum(os.path.getsize(p) for p in glob.glob(os.path.join(rd, '*', '*.*'))) / max(1, nk) / 1e6:.2f} MB per game with st/)")
        played = sum(1 for g in got.values() if g.get("ok") and g.get("win") in ("A", "B"))
        failed = len(todo) - played
        say(f"{played} games returned, {failed} {'not played (stopped early)' if stopped else 'missing or failed'}"
            + (f" -> {rd}" if todo else "") + (f"; OTF {len(otf_res)} of {len(otf_games)} games returned" if otf_games else ""))
        archive(out)
    # ---- summary over the SET's maps (every game the index has, local and Condor). The index loaded at the start plus this
    # batch's games, not a reload: under load ~290 (29 Oct) one Index load took 5 min, and the summary's two (+ abstat's own)
    # outlasted shipcheck's timebox, so a fully cached re-run ended with no summary at all.
    if todo:
        for j, (a_, b_, m_) in enumerate(todo, 1):
            g = got.get(j)
            if g and g.get("ok") and g.get("win") in ("A", "B") and m_ in mp:
                ix._add((hashes[a_], hashes[b_], mp[m_][0]),
                        dict(win=g["win"], rounds=g.get("rounds", 0), sa=g["sa"], sb=g["sb"], src=f"abl:cq_{name}_{k}"))
    side = {cand: collections.Counter(), base: collections.Counter()}
    n_games = 0
    names_ok = set(maps)
    _mnames = abindex.map_names()  # hoisted (30 Oct): rebuilding it per game made BIG summaries take 20+ min
    for (ha, hbb, mh), g in ix.games.items():
        mn = _mnames.get(mh)
        if mn not in names_ok:
            continue
        n_games += 1
        for h, s in ((ha, g["sa"]), (hbb, g["sb"])):
            b = cand if h == hc else base
            side[b]["faults"] += int(s.get("faults", 0))
            side[b]["fault_games"] += int(s.get("faults", 0)) > 0
            side[b]["fuel"] += int(s.get("fuel", 0))
            side[b]["fuel_games"] += int(s.get("fuel", 0)) > 0
    import abstat
    import contextlib
    import io
    buf = io.StringIO()  # abstat.py CAND BASE --maps MLIST, in-process on this index (its main(), minus the reload)
    with contextlib.redirect_stdout(buf):
        arows, ahalf = abindex.map_pairs(ix, hc, hb)
        arows = [r for r in arows if r[0] in set(maps)]
        if ix.conflicts:
            print(f"!! {len(ix.conflicts)} games disagree between sources (determinism failure): {ix.conflicts[:3]}")
        abstat.report(arows, f"{cand}@{hc}", f"{base}@{hb}", ahalf)
        if hc != hb:  # CONFIRM's "changed" count, on the set's maps (shipcheck's fix-lane change size reads it)
            nch = sum(1 for r in arows if (lambda g1, g2: g1 and g2 and (g1["win"], g1.get("rounds"), g1["sa"], g1["sb"])
                                           != (g2["win"], g2.get("rounds"), g2["sa"], g2["sb"]))(
                ix.games.get((hc, hb, mp[r[0]][0])), ix.games.get((hb, hc, mp[r[0]][0]))))
            print(f"  changed  {nch} of {len(arows)} maps (the two seats' games differ; 0 = CAND plays exactly like BASE "
                  f"on every map)")
    ab = buf.getvalue()
    # pooled held-out: gen_01..45 + gen_u 40 + gen_ux 17, one unit per map (both seats), abstat's statistics
    import abstat
    held = {m for f in HELDOUT for m in read(f)}
    hrows = [r for r in abindex.map_pairs(ix, hc, hb)[0] if r[0] in held]
    hst = abstat.summarize(hrows)
    held_line = (f"held-out pooled (gen_NN + gen_u + gen_ux: {len(hrows)} of {len(held)} maps): {abstat.line(hst).split(' maps: ', 1)[1]}" if hst
                 else f"held-out pooled: no complete map pairs on the {len(held)} held-out maps")
    # sprt.py on its decision maps: only when the index already has both seats of every one (no local games)
    dec = fresh_maps()
    dec = [m for m in dec if m in mp]
    have = {r[0] for r in abindex.map_pairs(ix, hc, hb)[0]}
    lack = [m for m in dec if m not in have]
    if lack:
        sprt_line = f"sprt: not run, {len(lack)} of {len(dec)} decision maps lack a complete pair (SET all or fresh plays them)"
    else:
        r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/sprt.py"), cand, base, name],
                           capture_output=True, text=True)
        sl = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("SPRT RESULT")]
        new_b = [ln for ln in r.stdout.splitlines() if re.search(r"## batch \d+:", ln)]
        sprt_line = (sl[-1] if sl else f"sprt: no SPRT RESULT line (exit {r.returncode}): {(r.stdout + r.stderr)[-200:]}") + \
            (f" (!! sprt played {len(new_b)} local batches)" if new_b else "")
        say(sprt_line)
    keep_line = ""
    if keep:
        kept = kept_replays(hashes)
        dirs = sorted({kept[(hashes[x], hashes[y], m)] for m in maps for x, y in ((cand, base), (base, cand))
                       if (hashes[x], hashes[y], m) in kept})
        nk = sum(1 for m in maps for x, y in ((cand, base), (base, cand)) if (hashes[x], hashes[y], m) in kept)
        keep_line = (f"replays: {nk} of {2 * len(maps)} games kept, in {' '.join(dirs)}\n"
                     f"  python3 -I tools/lab/econrace.py jackpot --pair {cand} {base} {' '.join(dirs)}\n")
    wall = time.time() - t0
    L = [f"# condab {name}: {cand}@{hc} vs {base}@{hb}, SET {spec} ({len(maps)} maps), {time.strftime('%Y-%m-%d %H:%M:%S')}",
         "", f"games: {played} played on Condor now, {reused} reused from the index"
         + (f", {failed} {'not played' if stopped else 'missing/failed'} (re-run to retry)" if failed else "")
         + (f"; plus {len(otf_res)} of {len(otf_games)} on-the-fly map games returned (read by stylepanel; not in the set counts below)"
            if otf_games else "") + f"; wall {wall / 60:.1f} min",
         *([f"timebox extended by {EXTENDED[0] / 60:.0f} min (>= {float(os.environ.get('CONDAB_EXT_FRAC', 0.7) or 0.7):.0%} of jobs back at the timebox)"] if EXTENDED else []),
         *([(f"timebox at {float(os.environ['CONDAB_TIMEBOX']) / 60:.0f} min, {stopped[0]}% of jobs: decided {stopped[1]}"
              if len(stopped) > 2 else f"stopped early at {stopped[0]}% of jobs (decided {stopped[1]})")] if stopped else []),
         f"index: {n_games} games on these maps; {len(ix.conflicts)} determinism conflicts", "",
         "map pairs (tools/lab/abstat.py --maps, every source pooled):", ab.rstrip(), "", held_line, "",
         *((otf_summary(otf, otf_res, cand, base, rb, os.path.basename(ref[0]) if ref else None) + [""]) if otf else []),
         sprt_line, "", keep_line,
         *([f"interim looks (bars ALL < {FAIL_BAR} fail, > {PASS_BAR} pass; DECIDED = deterministic bound, or projected "
            f"final +- O'Brien-Fleming z {OBF_C}/sqrt(t) x finite-population se, >= {MIN_STAT} returned pairs):"]
           + ([f"  paired D lines (STOP_REF): FAIL-only, when even the boundary-corrected upper bound of the projected "
                f"final D is below 0 (same z and minimum)"] if ref else [])
           + [f"  {x}" for x in interim] + [""] if interim else []),
         *((d_final(cand, base, maps, ix, hashes, ref, name) + [""]) if ref else []),
         "bot faults / fuel exhaustions per side (all games on these maps):"]
    for b in (cand, base):
        s = side[b]
        L.append(f"  {b:24s} faults {s['faults']} (in {s['fault_games']} games)  fuel exhaustions {s['fuel']} (in {s['fuel_games']} games)")
    txt = "\n".join(L) + "\n"
    open(os.path.join(BQ, name + ".condor.txt"), "w").write(txt)
    print(txt)


def otf_summary(otf, res, cand, base, rb, ref_name):
    """The OTF block of NAME.condor.txt: totals, normal / patho sub-lines, the warning, the paired D, one line per map."""
    def sc(x, m):
        a, b = res.get((x, base, m)), res.get((base, x, m))
        return None if a is None or b is None else ((a == "A") + (b == "B")) / 2
    allrows = [(om, sc(cand, om["name"]), sc(rb, om["name"]) if rb else None) for om in otf["maps"]]
    rows = [r for r in allrows if r[0]["family"] not in ("dom", "rule")]
    rrows = [r for r in allrows if r[0]["family"] == "rule"]
    drows = [r for r in allrows if r[0]["family"] == "dom"]

    def fam_line(label, rs):
        ss = [s for _, s, _ in rs if s is not None]
        miss = f" ({len(rs) - len(ss)} not returned)" if len(ss) < len(rs) else ""
        if not ss:
            return f"{label}: no results{miss}"
        w, l = ss.count(1.0), ss.count(0.0)
        return f"{label}: won both {w}, split {len(ss) - w - l}, lost both {l} | score {sum(ss) / len(ss):.3f}{miss}"
    L = [fam_line(f"otf {len(rows)} maps", rows) + "  (generated for this batch from fresh seeds, never saved; "
         "not in ALL or any family above)"]
    for fam in ("normal", "patho"):
        rs = [r for r in rows if r[0]["family"] == fam]
        L.append("  " + fam_line(f"otf {fam} {len(rs)}", rs))
    lost = sum(1 for _, s, _ in rows if s == 0.0)
    if lost >= 3:
        L.append(f"OTF WARNING: {cand} lost both seats on {lost} of the {len(rows)} on-the-fly maps")
    if rb:
        ds = [(om["family"], s - r) for om, s, r in rows if s is not None and r is not None]
        part = "; ".join(f"{f} n {len([d for ff, d in ds if ff == f])} D {sum(d for ff, d in ds if ff == f) / max(1, len([d for ff, d in ds if ff == f])):+.3f}"
                         for f in ("normal", "patho"))
        L.append(f"otf paired D vs {ref_name} ({rb}): n {len(ds)}  D {sum(d for _, d in ds) / max(1, len(ds)):+.3f}  ({part})")
    if drows:
        L.append(fam_line(f"otf dom {len(drows)}", drows) + "  (OTF_DOM: dominant-group maps, outside ALL and the lines above)")
        if rb:
            dd = [s - r for _, s, r in drows if s is not None and r is not None]
            L.append(f"otf dom paired D vs {ref_name} ({rb}): n {len(dd)}  D {sum(dd) / max(1, len(dd)):+.3f}")
    if rrows:
        rn = otf.get("rule") or "rule"
        L.append(fam_line(f"otf rule {rn} {len(rrows)}", rrows) + "  (OTF_RULE: maps where the rule holds, outside ALL and the lines above)")
        if rb:
            dd = [s - r for _, s, r in rrows if s is not None and r is not None]
            L.append(f"otf rule {rn} paired D vs {ref_name} ({rb}): n {len(dd)}  D {sum(dd) / max(1, len(dd)):+.3f}")
    word = {1.0: "won both", 0.5: "split", 0.0: "lost both", None: "not returned"}
    for om, s, r in allrows:
        L.append(f"  {om.get('name', '?')} {om.get('family', '?')}/{om.get('kind', '?')} size {om.get('size', '?')} {om.get('W', '?')}x{om.get('H', '?')} T{om.get('T', '?')} gems "
                 f"{om.get('gems', '?')}: {cand} {word.get(s, s)}" + (f", {rb} {word.get(r, r)}" if rb else "")
                 + (f" | trigger share {om['trigger']['share']} ratio {om['trigger']['ratio']} gems {om['trigger']['gems']}"
                    if om.get("trigger") else "")
                 + (f" | rule {json.dumps(om['rule'], separators=(',', ':'))}" if om.get("rule") else "")
                 + f" | seed {om.get('seed', '?')} recipe {json.dumps(om.get('recipe', {}), separators=(',', ':'))}")  # 13 Nov (TB): imported class banks (b2365 OCF-M) carry only name/family/labels
    L += [f"  {x}" for x in otf.get("log", [])]
    L.append("  rebuild one (to debug): python3 -I tools/lab/condab.py --otf-regen SEED 'RECIPE' OUT.map26a")
    return L


if __name__ == "__main__":
    if sys.argv[1:2] and sys.argv[1].startswith("--otf-"):
        otf_cli(sys.argv[1:])
        sys.exit(0)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # a kill still runs the clean-up below
    try:
        main()
    finally:
        for _b in list(PILOT_ACTIVE):  # a stopped or killed condab leaves no queued pilot work behind
            try:
                import pilotd
                pilotd.cancel(_b)
            except Exception:
                pass
        otf_clean()
        for _o in list(OUTS):  # 3 Nov: a stopped leg (shipcheck's stop file, a gate's SIGTERM) left its run dir on the home: 175 of 322
            if os.path.isdir(_o) and _o.startswith(OLD_RUNS + "/"):
                archive(_o)
