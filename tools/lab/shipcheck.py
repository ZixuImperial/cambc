#!/usr/bin/env python3
"""shipcheck: the owner's FAST GATE in one command, then (on PASS) the submit. Tool builder, 29 Oct.

usage: sh tools/lab/shipcheck.sh CAND TAG [LANE=fix|param] [TRIGGER=list]   (from /homes/USER/cambc; env as below)
  DRY=1        do everything except the platform submit and unrsets.sh; the queue line goes to
               /data/USER/st/bq/shipcheck_dry.log, never to builder_queue.md. Every test runs with DRY=1.
  LIVE=NAME    the live bot (default: CLAUDE.md's "The live bot: **bots/NAME = vNNN**" line); BASE_ND=RUN its nochase2 run
               (default cq_ndNNN_1 from LIVE's nova_bNNN_ name). SUBSET (300), SET (all): passed to scr.sh.
  CONFIRM_FROM=TAG [CONFIRM_N=k]  CONFIRM MODE (owner 9 Nov; shipwatch sets it on a copy rebased after a PASS refused for base): after
               the base, merge and TAG checks, only one read v live (confirm_plan: 1,200 new maps, point >= .50 (bug bar line BUGBAR_PT) and
               CI upper >= .50; RARE / draft lane: half the lane's changed-map read, point > .50, CI upper >= .50), with bot faults, capped
               fuel and the death guard on those games; then the usual submit. reread_requeue carries it to armq (armq front --confirm-from).
0. Base check (rule 1, before anything runs and again inside the submit lock): CAND must carry LIVE's own change. LIVE's
   added lines relative to its parent (the previous live version: CLAUDE.md's "vNNN = bots/PARENT" after the live bot, or
   LIVE_PARENT=) must be >= 95% present in CAND (line-matched per file). On 29 Oct: v278 itself 312/312, the five newest
   candidates built on v277 0/312. Otherwise "rebase onto live first". Without a known parent the strict rule applies: every
   difference from LIVE is an added line, a changed #define value, or a replaced line naming a switch that CAND adds.
1. Legs, started at once:
   - nochase2 paired D: `H2H=0 SUBSET=300 STOP=2 CONDAB_TIMEBOX=720 SMOKE=0 sh /data/USER/st/bq/scr.sh CAND TAG` (BASE=LIVE,
     BASE_ND): a fresh family-balanced random subset, both seats, paired with BASE_ND on the same maps; early FAIL / PASS
     by condab's OBF rule; at 12 min the last look decides or says INCONCLUSIVE; OTF maps added. No local smoke: ubaudit builds and fault-checks CAND.
   - CONFIRM=100 vs LIVE (condab, timebox 12 min).
   - ubaudit CAND LIVE (local, nice, its own lock); TRIGGER=list adds a SEED=2 audit and a KEEP=1 condab run on the list
     (OTF=0, priority -5), started only AFTER the gate and only on a PASS (capacity rule). MECHCMD="cmd args" (with TRIGGER):
     when that KEEP run is back, MECHCMD runs (shlex-split, no shell) with {KEEPDIR} {CAND} {BASE} {TRIGGER}; MECH is prose
     (the commit body) and never runs (31 Oct)
     replaced by shell-quoted values; its last 20 lines go into a "mechanism" section. Informational, never a gate; if it
     is not done by the timebox the section says "mechanism: pending, log X".
   Condor job count: ~2 jobs per idle slot per leg, at most 26 + 17 jobs here, far under 400.
   - live h2h (30 Oct, owner "speed this up"; Builder: since the 30 Oct bisect h2h vs live is the decisive signal, nochase2
     misjudged RC by ~0.02): `OTF=0 condab.sh CAND LIVE lhTAG all`, the full 636-map pool, both seats, Condor priority 10,
     the nochase2 leg's timebox (TIMEBOX, + NC_EXT once when >= 70% of jobs are back). Fewer than LH_MIN (500) complete map
     pairs back: INCONCLUSIVE. SC_LIVEH2H=0 turns the leg off and restores the pre-30-Oct bars below.
     POWER EXTENSION (30 Oct, owner: fewer rejected candidates, same quality): on the behaviour lane, when the 636-map read
     has point >= 0.505 and LOS >= 85% but CI lower < 0.50, CAND vs LIVE plays LX_N (600) more maps generated on the fly
     (`CONFIRM=600 condab.sh CAND LIVE lxTAG`: fresh seeds, both seats, never saved; the pool has no unused maps), started
     as soon as the 636 read is in; its timebox ends LX_EXTRA (600) s after the live h2h's. Job size is set so the batch
     fits under the 400-job cap (it waits for room, up to 6 min before its deadline). The table shows both reads: "live h2h"
     (verdict EXT: the extension decides) and "live h2h+ext", the pooled map-pair score (abstat's estimator on the summed
     won-both / split / lost-both counts) judged on CI lower >= 0.50 (z LX_Z, default 2.2: Builder 30 Oct, the drift lesson); fewer than LX_MIN (300)
     extension maps back: INCONCLUSIVE. Simulated (normal approx., se 0.0138 at 636 maps): a true +0.000 candidate passes
     2.5% -> 3.6% of the time (LX_Z 2.2: 3.1%), +0.010 10.9% -> 18.1%, +0.020 31% -> 50%, -0.005 1.0% -> 1.3%.
   LANE=param (30 Oct, Builder: hyperparameter changes get a lighter bar, faster iteration): only the live h2h (636 pool)
     and an extension of PM_LX_N (650) fresh maps (`CONFIRM=650 condab.sh CAND LIVE lxTAG`), both started at once, plus
     the anchor h2h; no nochase2, CONFIRM or trigger legs. Verdict row "live h2h+ext": the pooled map pairs need
     n >= PM_N (1200), point >= PM_POINT (0.5025; owner 11 Nov, was 0.505) and LOS >= PM_LOS (90%). ubaudit is skipped when tools/lab/paramdiff.py
     finds the diff vs live param-only (numeric literals / #define values only; not when a changed number is inside [...],
     on a for line, or a changed #define sizes an array or bounds a loop); otherwise it runs as usual. Faults count every
     leg; fuel = CAND vs LIVE on the live h2h + extension games (same bar). SC_REUSE_LX=NAME (marker key REUSE_LX, e.g.
     from sweepd.py) uses an existing CONFIRM summary NAME.condor.txt instead of playing the extension, when its header
     names exactly CAND and LIVE with today's source hashes and it has >= LX_MIN maps (the live h2h itself comes from the
     index: a rerun on the same sources costs no games). Selection note: a sweep that picks the best of k variants on this
     bar ships a true-zero change far more often than one check does (sweepd.py's docstring has the numbers).
1b. SC_FIX_NONC=1 (default; 0 = the legs above; owner 30 Oct ~12:20 "iterate fast": 3 of 4 checks INCONCLUSIVE for
   capacity, the live h2h back and the nochase2 leg not): on LANE=fix with the live h2h on, no nochase2 leg (nor its
   reference top-up, OTF maps, trigger D, post-ship complement leg) and no CONFIRM leg. Why: the live h2h decides since
   the 30 Oct bisect; nochase2 misjudged RC by ~0.02; per-map nochase2 strength predicts nothing live (cambc-9e, r 0.02).
   The change-size guard reads the live h2h: maps changed = maps whose two seats' games differ (condab's set summary
   "changed X of Y maps"; older summaries: counted from the index), in three bands (Builder 30 Oct: FREE_CHIP changed 95%
   of maps on the fix lane, a behaviour change in disguise): <= 15% changed: the fix bar (point >= FIX_BIG_LH 0.50, CI upper >= 0.5; BUGBAR_PT 0.495 under BUGBAR=1 on every band, owner 7 Nov: "Everything should be >= .5 and with bugs go to .495");
   15-50%: live h2h point >= the same bar; > 50%: the behaviour-lane bar (CI lower >= 0.5, with the power extension
   when its conditions hold). Rollbacks (MECH "rollback ...") keep the fix bar. The "fix-lane change size" row shows the
   band; the live h2h row carries its bar. Fuel = CAND vs LIVE on the live h2h games. TRIGGER=list: a small
   "trigger h2h" leg (CAND vs LIVE on the installed trigger maps, OTF=0): VACUOUS when 0 maps changed, else CI upper
   >= 0.5 (n >= 10); ubaudit SEED=2 and the after-PASS KEEP / MECH as before. Kept: live h2h, anchor, ubaudit, faults.
   Re-verdicts (--verdict): 306q INCONCLUSIVE (nc leg not back) -> PASS (1% changed, lh 0.498); 304h FAIL on nc D
   -0.024 -> 78% changed, behaviour bar: lh 0.513 [0.493, 0.532] LOS 90% -> the extension decides.
1c. SC_LH_EARLY=1 (default; 0 = off), every lane: the live h2h leg runs with STOP=1 and CONDAB_HI_FAIL=BAR,Z,MIN:
   at each condab interim look (50/60/70/75/80/90% of jobs) and at its timebox look, once >= LH_EARLY_MIN (300)
   complete map pairs are back, FAIL when score + LH_EARLY_Z (2.5) * se < BAR (se = sd / sqrt(n)); BAR = 0.49 on
   LANE=fix (its point bar), 0.50 otherwise. STOP=1 also turns on condab's own FAIL rule (projected final + O'Brien-
   Fleming z * finite-population se < 0.48, or the deterministic bound). condab removes only its own cluster. The row
   reads "EARLY FAIL: why" and FAILs at any n. Then (any lane, also on a full-pool FAIL row) shipcheck writes
   Q/sc_RTAG.stop (CONDAB_STOPFILE): every other condab leg of this check removes its own cluster within ~20 s, the nc leg
   is not started if the stop came first, ubaudit is not waited for; the verdict is FAIL at once.
   Maths (iid map pairs, 40,000 simulated 636-map runs per row, looks as above; split = share of 0.5 map pairs, 304h
   0.745, near-identity fixes ~0.95+): P(early FAIL) for a true 0.500 candidate, CI rule alone / with condab's OBF rule:
     fix lane (BAR 0.49): split 0.50 0.33% / 1.54%, split 0.75 0.13% / 0.36%, split 0.90 0.02% / 0.02%
       (one look: Phi(-2.5 - 0.01 / se), se 0.020 / 0.0145 at n 300 -> 0.13% / 0.07%);
     behaviour (BAR 0.50): 1.4-1.6% at 0.500 (the full read fails those 64-88% of the time anyway), 0.02-0.28% at 0.510.
   In 0 of the simulated early FAILs (any lane, true 0.454-0.52) would the full 636 read have passed (fix: point >= 0.49
   and CI upper >= 0.5; behaviour: CI lower >= 0.5 or the 0.505 extension point): the rule only saves games.
   True 0.454 (recent candidates): early FAIL 83-98%, after 53-73% of the live h2h's games (split 0.5-0.75).
   Games per shipcheck (Condor; lh 1272 = 636 x 2, anchor 600 = the 300-map subset x 2, CONFIRM 200, nochase2 ~620 =
   600 + OTF, its reference top-up 0-600: 600 right after a ship, 3 of 3 checks on 30 Oct; T = trigger maps):
     LANE=fix        before ~2700-3300 (+2T)  ->  after 1872 (+2T; +1200 extension when > 50% changed and it
                     triggers); a clear loser (0.454) ~1150-1350
     LANE=behaviour  before ~2700-3300 (+1200 extension when it triggers) -> same for passers; a clear loser ~1500-2100
     LANE=param      before 2522 (1272 + 650 + 600)  ->  same for passers; a clear loser ~1400-1650
   (losers: the other legs stop when the live h2h does, at roughly the same share of their games.)
   shipcheck.py --verdict CAND TAG [LANE=..] [LIVE=..] re-prints a finished check's table under the current switches.
   LOAD-AWARE TIMEBOX (30 Oct, Builder: daytime capacity made 3 of 4 checks INCONCLUSIVE): at the start TIMEBOX becomes
     SHIPCHECK_TIMEBOX x sqrt((our idle + running Condor jobs) / running), within [base, SC_TB_MAX 2700 s] (17 running /
     221 idle: 45 min; a quiet pool: 12 min); SC_TB_SCALE=0 keeps the base. Every condab leg (CONFIRM and the anchor too) may
     extend once by NC_EXT at >= SC_EXT_FRAC (0.5) of its jobs back (condab CONDAB_EXT_FRAC, default 0.7 elsewhere).
   SC_LH_BIG=N (30 Oct, iteration-speed): the live h2h leg runs `BIG=N condab.sh CAND LIVE lhTAG all`, the 636 pool + the
     first N maps of the frozen bank (tools/lab/mapbank.py: generated like CONFIRM's maps, but kept, so reruns are free);
     LH_MIN becomes 79% of the maps. Its power extension (30 Oct 18:40; it used to be off, so a triggering read ended
     INCONCLUSIVE): the same h2h on the pool + all SC_BANK_MAX (4000) bank maps (`BIG=4000 condab.sh CAND LIVE lxTAG all`; the
     first N come from the index), judged ALONE (it holds the first read's maps) on CI lower >= 0.5 at z LX_Z, within
     LX_EXTRA_BIG (900) s after the live h2h's deadline. When even 636 + 4000 maps could not lift the observed point to that
     bound (projected point - LX_Z x sd / sqrt(4636) < 0.5; e.g. 0.508 -> 0.4997), it is not run: FAIL (power). Power at z 1.96 (per-map sd 0.256): true +1% passes 16% at 636
     maps, 52% with N=2000, 76% with N=4000; +2%: 50% / 98% / 100%; a true 0 always 2.5%.
2. Verdict table against condor-work/reports/subagent_primer.md's FAST GATE:
   With the live h2h leg (default), it decides: behaviour lane: live h2h CI lower >= 0.50, nochase2 D not significantly < 0
   (CI upper >= 0, no early FAIL), CONFIRM non-inferior (CI upper >= 0.5), the anchor row, ubaudit, faults (live h2h's
   games too), fuel; VACUOUS as before. LANE=fix: live h2h point >= FIX_BIG_LH (BUGBAR_PT under BUGBAR=1) AND CI upper >= 0.50, plus the fix-lane rows below.
   Without it (SC_LIVEH2H=0):
   behaviour lane: nochase2 D >= 0 (decided early or on the full subset), CONFIRM > 0.5, 0 new UB sites, 0 CAND faults
   (both legs), CAND fuel exhaustions not up vs LIVE (FUEL rule below); CONFIRM with 0 maps
   changed (every game identical to BASE's: a targeted change that never fires there) is a neutral PASS; once the nochase2 row
   PASSES, CONFIRM only has to be non-inferior (CI upper >= 0.5); otherwise > 0.5, no OTF WARNING.
   Both lanes: the cumulative anchor (anchor.txt): CAND vs ANCHOR h2h on the same subset (OTF=0), FAIL when its CI upper
   < 0.5 (rollback MECH markers: shown, not blocking); every 3rd ship since the anchor starts a full-pool live-vs-anchor h2h
   (CI upper < 0.5: ROLLBACK-FLAG to shipwatch.log + health.log; CI lower >= 0.5: the anchor moves to live).
   LANE=fix (bug-fix lane, "not significantly worse"; when CONFIRM changed > 15% of its maps the nc D point estimate must be
   >= 0 too, unless MECH starts with "rollback"): nochase2 D's 95% bootstrap CI upper bound >= 0 and no early FAIL
   (STOP_REF fail-only), CONFIRM's 95% CI upper bound >= 0.5; the other rows as above.
   nochase2 past the timebox: when >= 70% of its jobs are back at 12 min, condab extends once by NC_EXT s (480) before it
   decides (CONDAB_TIMEBOX_EXT); the D row shows "timebox +8 min".
   ubaudit past the timebox: when every other leg has PASSED, shipcheck waits for it up to UBAUDIT_WAIT s (1200) more and
   decides then (the table shows the wait); otherwise it stops ubaudit at the timebox. A stopped audit is INCONCLUSIVE.
   Overall: any FAIL -> FAIL; else any INCONCLUSIVE -> INCONCLUSIVE (never a pass); else PASS.
3. On PASS: autoship.py must not be armed; a machine-wide flock (/data/USER/plat/.shipcheck_submit.lock) so two passes
   never submit at once; rule 1 again inside it (live may have moved); submit via platlock.sh with an 80-char note; the
   version parsed from the CLI output; unrsets.sh VERSION TAG under nohup/nice (log /data/USER/st/bq/unrsets_TAG.log);
   one line appended to builder_queue.md under a lock (write the new file, then mv); prints "SUBMITTED vNNN" and the
   CLAUDE.md live line to put in (the Builder edits CLAUDE.md). No per-night cap. Rollback stays manual.
4. POST-SHIP COMPLEMENT LEG (after a real SUBMITTED; simulated in DRY): in the background under nice 10, nochase2 on the
   complement maps (all 636 minus the gate's subset, recorded at gate time in /data/USER/st/bq/postship/TAG.subset), with
   STOP=0 and OTF=0 (a measurement, not a gate), then the BASE on the same maps: since v300 the reference holds the subset only
   (index_ref), so complement n was 0 and "full pool" meant the subset until 2 Nov. Both legs run at CONDAB_PRIO POSTSHIP_PRIO
   (default -50, behind every gate); a failed leg is logged and the read goes on, labelled partial, with the games there are.
   Then pair_d's scores/boot against the base's games on all maps:
   complement D [CI] and the combined full-pool D [CI] (subset + complement games, paired per map), and "ROLLBACK-FLAG" when
   combined D < -2 SE. One line to shipwatch.log and to /data/USER/st/bq/postship.log; nothing is rolled back
   automatically. POSTSHIP_MAX=N (tests only) plays the first N complement maps.
   shipcheck.py --submit-only CAND TAG runs only step 3 (with a table saying PASS) for testing the lock with DRY=1; in DRY
   mode a simulated submit records CAND as the dry "live" for 30 min (/data/USER/st/bq/shipcheck_dry.live) so a second
   dry pass sees live move.
"""
import collections
import textwrap
import difflib
import fcntl
import json
import math
import os
import re
import glob
import shlex
import shutil
import signal
import hashlib
import subprocess
import sys
import threading
import time

REPO = "/homes/USER/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
import shipstack  # noqa: E402
Q = "/data/USER/st/bq"
CLI = "/data/USER/cambc500/bin/cambc500"
SUBMIT_LOCK = "/data/USER/plat/.shipcheck_submit.lock"
QUEUE = "/homes/USER/condor-work/reports/builder_queue.md"
DRYLOG = os.path.join(Q, "shipcheck_dry.log")
DRYLIVE = os.environ.get("DRY_LIVE_FILE", os.path.join(Q, "shipcheck_dry.live"))
# The machine-kept live version (29 Oct 23:25: v286 was built on v284 and passed because CLAUDE.md still said v284 three
# minutes after v285 went up): "vNNN BOT UTC parent=PREVBOT", written atomically inside the submit lock after a submit.
LIVEFILE = os.environ.get("SHIPCHECK_LIVEFILE", os.path.join(Q, "live.txt"))
# CUMULATIVE ANCHOR (30 Oct: v290-v297 each passed at D ~ 0, but v297 vs v289 read 0.461 [0.436, 0.487] and the rating
# fell 2074 -> 2022): "<bot> <version> <UTC> <why>". Moves only by the 3-ship full-pool check below, or by hand.
ANCHOR = os.environ.get("SHIPCHECK_ANCHOR", os.path.join(Q, "anchor.txt"))
PUBPOOL = os.path.join(Q, "subsets", "published_pool.txt")  # the anchor's map set in behaviour checks (pubpool.py)
HEALTH = os.path.join(Q, "health.log")


# The nochase2 rows and legs apply only while that bot exists (owner 8 Nov: spars deleted); restoring the folder restores them.
HAVE_ND = os.path.isdir(os.path.join(REPO, "bots", "nova_spar_nochase2", "src"))


def anchor():
    """(anchor bot, its version) or (None, None); None too when the anchor's folder is gone."""
    try:
        x = open(ANCHOR).read().split()
        return (x[0], int(x[1])) if os.path.isdir(os.path.join(REPO, "bots", x[0], "src")) else (None, None)
    except (OSError, IndexError, ValueError):
        return None, None
TIMEBOX = int(os.environ.get("SHIPCHECK_TIMEBOX", 720))
TB_SCALE, TB_MAX = os.environ.get("SC_TB_SCALE", "1") == "1", int(os.environ.get("SC_TB_MAX", 2700))  # load-aware timebox
EXT_FRAC = os.environ.get("SC_EXT_FRAC", "0.5")  # condab extends a leg's timebox once at >= this share of jobs back
LIVEH2H = os.environ.get("SC_LIVEH2H", "1") == "1"  # the full-pool CAND vs LIVE leg (docstring 1., "live h2h")
PANEL = os.environ.get("SC_PANEL", "1") == "1"  # owner 1 Nov: FRESH-MAP and PLAYSTYLE PANEL legs (tools/lab/stylepanel.py)
PANEL_N = int(os.environ.get("SC_PANEL_N", "300"))  # new maps per check (stratmaps.py, os.urandom seeds)
PANEL_PAR = int(os.environ.get("SC_PANEL_PAR", "8"))  # condab legs at a time inside the panel
SECOND_WAIT = int(os.environ.get("SC_SECOND_WAIT", "1500"))  # s more for a fresh leg's second read (stylepanel's SECOND READ); not finished = INCONCLUSIVE
PANEL_WAIT = int(os.environ.get("SC_PANEL_WAIT", "2700"))  # its own wait (s): 21 legs outlast the 12-min timebox
LH_BIG = int(os.environ.get("SC_LH_BIG", "0") or 0)  # BIG=N: the live h2h also plays N frozen bank maps (mapbank.py); 0 = off
BANK_MAX = int(os.environ.get("SC_BANK_MAX", 2000 if os.environ.get("BIGSET") in ("ladderw", "ladderw_nh", "big2") else 3910 if os.environ.get("BANK", "2") != "1" else 4000))  # decision-bank maps (v2 3910, v1 4000, BIGSET=ladderw 2000): a BIG extension plays them all
LX_EXTRA_BIG = int(os.environ.get("LX_EXTRA_BIG", 900))  # the BIG extension's own time after the live h2h's deadline
LH_MIN = int(os.environ.get("LH_MIN", 500 if not LH_BIG else int(0.79 * ((105 if os.environ.get("BIGSET") in ("ladderw_nh", "big2") else 636) + LH_BIG))))  # nh: pool only  # complete map pairs needed
LX_N, LX_MIN = int(os.environ.get("LX_N", 600)), int(os.environ.get("LX_MIN", 300))  # power extension maps / needed
LX_EXTRA, LX_Z = int(os.environ.get("LX_EXTRA", 600)), float(os.environ.get("LX_Z", 2.2))  # Builder 30 Oct: 2.2 (drift)
PM_N, PM_POINT, PM_LOS = (int(os.environ.get("PM_N", 1200)), float(os.environ.get("PM_POINT", 0.5025)),
                          float(os.environ.get("PM_LOS", 0.90)))  # LANE=param bars (Builder 30 Oct)
PM_LX_N = int(os.environ.get("PM_LX_N", 650))  # LANE=param extension maps: 636 + 650 clears PM_N after a few failed games
CAP = int(os.environ.get("CONDAB_CAP", 400))  # our Condor job cap (condab.py preflight)
NC_EXT = int(os.environ.get("NC_EXT", 480))  # the nochase2 leg may extend its timebox once by this when >= 70% of jobs are back  # 12 min (owner: sub-15-minute iterations)
DRY = os.environ.get("DRY") == "1"
FIX_NONC = os.environ.get("SC_FIX_NONC", "1") == "1"  # LANE=fix: no nochase2 / CONFIRM legs; live h2h decides (docstring 1b.)
LH_EARLY = os.environ.get("SC_LH_EARLY", "1") == "1"  # live h2h early FAIL + stop the other Condor legs (docstring 1c.)
LH_EARLY_Z, LH_EARLY_MIN = float(os.environ.get("LH_EARLY_Z", 2.5)), int(os.environ.get("LH_EARLY_MIN", 300))
FIX_BIG_LH = float(os.environ.get("FIX_BIG_LH", 0.50))  # SC_FIX_NONC: > 15% of maps changed -> live h2h point bar


def nonc(lane):
    """SC_FIX_NONC applies: the fix lane with the live h2h leg on."""
    return lane in ("fix", "draft") and (LIVEH2H or bool(RARE)) and FIX_NONC  # RARE plays no live h2h (owner 7 Nov)


DRAFT_N = int(os.environ.get("SC_DRAFT_N", "1200"))  # LANE=draft (owner 4 Nov via the Builder): changed maps the read plays, half weird
DRAFT_BIG = 0.50  # BIG no-harm point (owner 7 Nov: every point bar >= .50): unchanged-draft maps play identical games, so the changed BIG maps decide it
# 12 Nov ~23:5xZ (owner via the Coordinator, CLAUDE.md §5): the draft lane's BIG row is NO-HARM like behaviour/fix: point >= .495 and CI upper
# >= .50 (g5eg .4994 [.497, .502] had failed the old point >= .50). SC_DRAFT_BIG_NOHARM=0 restores the point >= .50 form.
DRAFT_BIG_NH = os.environ.get("SC_DRAFT_BIG_NOHARM", "1") != "0"
DRAFT_BIG_NH_PT = float(os.environ.get("SC_DRAFT_BIG_NH_PT", "0.495"))
EARLY_NOHARM = 0.495  # the early stop's CI-upper line, not a point bar: "CI upper rows stay" (owner 7 Nov via the Builder)
DRAFT_LOS = 0.95  # the changed-map read: point > .50 with LOS >= this
RARE = {}  # marker RARE=N, fix lane (owner 7 Nov via the Builder): no BIG; generated unseen maps where the change shows, and that read decides. Bars from RARE_BAR, which the Builder writes; no file, no read
RARE_BAR = os.environ.get("SC_RARE_BAR", "/data/USER/st/bq/rarebar.txt")  # SC_RARE_BAR: DRY tests only. One line: point P los L min M (e.g. point 0.50 los 0.95 min 400); a 'big' field is ignored
DRAFT_MIN = 50  # owner 4 Nov: decide on what the probe found (40,000 maps or 4 h); under this many changed maps no CI means anything
# CONFIRM MODE (owner 9 Nov ~17:20Z): marker CONFIRM_FROM=TAG (shipwatch writes it on a rebased copy): this candidate PASSED its full check (TAG) v the
# previous live, its submit was REFUSED because another candidate shipped mid-check, and its change merged cleanly onto the new live. Instead of the
# full sequential check: one leg v live (confirm_plan, by lane: 1,200 new per-run maps via stylepanel --fresh-only, never saved, half pathological,
# point >= .50 (BUGBAR_PT on a bug bar line), CI upper >= .50; RARE / draft: half the lane's changed-map read, point > .50, CI upper >= .50), plus the bot-fault
# row, capped fuel (cap5, change v fuel ratio) and the death guard on those games; then the usual submit (base check inside the lock). CONFIRM_N (marker)
# counts the live moves since the full read (at most CONFIRM_MAX 2). Markers get it from shipwatch's rebase or from reread_requeue -> armq -> fastship.
CONFIRM = {}  # {"from": TAG of the full PASS, "tag": this check's run tag}: set in main when CONFIRM_FROM is set
BIG2_MAPS = int(os.environ.get("SC_BIG2_MAPS", "1200"))  # the second fresh set for BIG no-harm stays 1,200 (owner 11 Nov rule)
CONFIRM_MAPS = int(os.environ.get("SC_CONFIRM_MAPS", "300"))  # 12 Nov ~22:4xZ owner "test it on less stuff ... make sure it is good": 600 -> 300;  # 12 Nov ~17:3xZ owner: "if an update passes test it on a smaller subset if it becomes stale": fix/bug-bar confirm 1,200 -> 600 (behaviour: bq/confirm_maps_beh 3,300 -> 1,200)
CONFIRM_WAIT = int(os.environ.get("SC_CONFIRM_WAIT", "5400"))  # s the fresh leg may take (+ the probe wall on changed-map lanes); not done = INCONCLUSIVE
CONFIRM_MAX = 2  # owner 9 Nov: at most this many confirm reads per full PASS (live moves), then the full check (shipwatch SW_CONFIRM_MAX, armq the same)


def early_bar(lane):
    """SC_LH_EARLY's bar: the CI upper (z LH_EARLY_Z) of the returned map pairs must stay >= this (docstring 1c.)."""
    return 0.49 if lane == "fix" else EARLY_NOHARM if lane == "draft" or fresh_decides(lane) else 0.50  # behaviour, POOLED DECIDES (3 Nov): stop only a BIG that cannot reach no-harm


def load_timebox(base):
    """(timebox, note): base x sqrt((our idle + running jobs) / running), within [base, TB_MAX] (Builder 30 Oct: daytime, other
    users hold ~208 of 284 slots; 3 of 4 shipchecks ended INCONCLUSIVE for capacity with 17 running / 221 idle)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import condorroute  # 7 Nov: with no schedd here condor_q failed and every check took the base timebox
        out = subprocess.run(["condor_q", "-totals"], capture_output=True, text=True, env=condorroute.env(), timeout=60).stdout
        m = re.search(r"Total for USER: \d+ jobs;.*?(\d+) idle, (\d+) running", out)
        idle, run = int(m.group(1)), int(m.group(2))
    except (OSError, subprocess.SubprocessError, AttributeError):
        return base, "condor_q unreadable: base timebox"
    tb = int(min(TB_MAX, max(base, base * math.sqrt((idle + run) / max(1, run)))))
    # 12 Nov (rgl2 12696 INCONCLUSIVE capacity: with 8 checks on ~30 pilots the ship-leg queue held 1,394 items, oldest 31 min, and the
    # Condor job counts above stay flat with pilots): a leg also waits for the pilot queue ahead of it to drain, so the timebox is at least
    # base + queued ship items / the pilots' recent claim rate, up to SC_TB_QMAX (4500 s)
    try:
        pq = "/homes/USER/condor-runs/pilotq"
        ahead = sum(1 for x in os.listdir(f"{pq}/queue") if x[:3].isdigit() and int(x[:3]) <= 488)
        now = time.time()
        done10 = sum(1 for x in os.scandir(f"{pq}/done") if now - x.stat().st_mtime < 600)
        # 12 Nov ~06:0xZ (sqp1s 12748: done/ held < 30 recent items at its start, so no drain was added and it timed out at 26.8 min with
        # a PASSING fresh row): below 30 recent items, use SC_TB_QRATE items/min (16, tonight's measured claim rate) instead of skipping
        rate = done10 / 600.0 if done10 >= 30 else float(os.environ.get("SC_TB_QRATE", 16)) / 60.0
        if ahead > 0:
            drain = ahead / rate
            tq = int(min(int(os.environ.get("SC_TB_QMAX", 4500)), base + drain))
            if tq > tb:
                return tq, f"our jobs {run} running / {idle} idle; pilot queue {ahead} ship items at {rate * 60:.0f}/min: +{drain / 60:.0f} min drain"
    except OSError:
        pass
    return tb, f"our jobs {run} running / {idle} idle"


def home_hold_s(t_from, cap=2400):
    """10 Nov (Builder: ppg1s/prc1s/pfl30 INCONCLUSIVE 'capacity'): seconds since t_from in which condab legs sat in the home-quota
    slowdown (one batch per 60 s; every leg waited ~300 s per stage, a kill gate's 4 stages ran past the timebox). condab writes a
    bq/home_gate.log line every 300 s while it waits; each 300 s bucket with one counts once. Capped at cap s."""
    try:
        lines = open("/data/USER/st/bq/home_gate.log").read().splitlines()[-3000:]
    except OSError:
        return 0
    b = set()
    for ln in lines:
        if "condab pid" not in ln or "home quota" not in ln:
            continue
        try:
            t = time.mktime(time.strptime(ln[:20], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except ValueError:
            continue
        if t >= t_from:
            b.add(int(t // 300))
    return min(cap, 300 * len(b))


def say(s):
    print(f"{time.strftime('%H:%M:%S')} {s}", flush=True)


# ---------------------------------------------------------------- rule 1: CAND = LIVE + switch-gated changes
def prepend_live(line, path=None):
    """Write LINE as the first line of live.txt, keeping the older versions' lines below it (31 Oct, Builder: the submit
    step overwrote the file, losing v336 and earlier). Atomic (.new + rename); the caller holds the submit lock."""
    path = path or LIVEFILE
    ver = line.split()[0]
    try:
        old = [ln for ln in open(path).read().splitlines() if ln.strip() and ln.split()[0] != ver]
    except OSError:
        old = []
    with open(path + ".new", "w") as f:
        f.write("\n".join([line] + old) + "\n")
    os.replace(path + ".new", path)


def live_bot():
    """-> (live bot, version or None, its parent bot or None)"""
    if os.environ.get("LIVE"):
        return os.environ["LIVE"], None, os.environ.get("LIVE_PARENT")
    if DRY and os.path.exists(DRYLIVE) and time.time() - os.path.getmtime(DRYLIVE) < 1800:
        x = open(DRYLIVE).read().split()
        return x[0], "dry", x[1] if len(x) > 1 else None
    t = open(os.path.join(REPO, "CLAUDE.md")).read()
    m = re.search(r"The live bot: \*\*bots/(\S+) = v(\d+)\*\*", t)
    pm = re.search(r"v\d+ = bots/([A-Za-z0-9_.+-]+)", t[m.end():m.end() + 600]) if m else None
    cl = (m.group(1), m.group(2), pm.group(1) if pm else None) if m else None
    lf = None
    try:
        x = open(LIVEFILE).readline().split()  # the newest line first; older versions below it (31 Oct: history kept)
        lf = (x[1], x[0].lstrip("v"), next((y[7:] for y in x if y.startswith("parent=")), None))
    except (OSError, IndexError):
        pass
    if not lf and not cl:
        sys.exit("shipcheck: no live.txt and no live line in CLAUDE.md (pass LIVE=nova_...)")
    if lf and cl and lf[:2] != cl[:2]:
        new = lf if int(lf[1]) >= int(cl[1]) else cl
        say(f"!! live.txt says v{lf[1]} {lf[0]}, CLAUDE.md says v{cl[1]} {cl[0]}: using the newer, v{new[1]} {new[0]}")
        return new
    return lf or cl


def platform_listing():
    """(live version, {version: note}) from the read-only `submissions list` via platlock.sh, or (None, {}) on failure.
    shipcheck's submit notes start "TAG BOT ...", so a version's note names its bot."""
    if os.environ.get("SHIPCHECK_FAKE_PLATFORM_LIVE"):  # tests
        return int(os.environ["SHIPCHECK_FAKE_PLATFORM_LIVE"]), {}
    try:
        if os.environ.get("SHIPCHECK_FAKE_LISTING"):  # tests: a saved `submissions list` output
            out, rc = open(os.environ["SHIPCHECK_FAKE_LISTING"]).read(), 0
        else:
            r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/platlock.sh"), CLI, "submissions", "list"],
                               capture_output=True, text=True, timeout=300, cwd=REPO)
            out, rc = r.stdout, r.returncode
        m = re.search(r"Live:\s*v?(\d+)", out)
        if m:
            notes = {int(x.group(1)): x.group(2) for x in re.finditer(r"^v(\d+)\s+\S+\s+\S+\s+\S+\s+(.*)$", out, re.M)}
            return int(m.group(1)), notes
        say(f"!! platform live check: no 'Live:' line (exit {rc}): relying on live.txt")
    except (OSError, subprocess.TimeoutExpired) as e:
        say(f"!! platform live check failed ({e}): relying on live.txt")
    return None, {}


def platform_live():
    """The platform's NEWEST submitted version (its active one, or a newer upload still compiling), or None when the call fails.
    11 Nov (TB): this returned the active version only; the Builder's hand-submit v785 was still compiling (active 784), so the pre-submit
    guard ("a submit this tool did not record") passed and xde1 went up as v786 on v784, without v785's fix."""
    pv, notes = platform_listing()
    return max([pv] + list(notes)) if pv is not None and notes else pv


def src_files(bot):
    root = os.path.join(REPO, "bots", bot, "src")
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = [x.rstrip() for x in open(p, errors="replace").read().split("\n")]
    return out


DEF = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\b")


TABDEF = re.compile(r"^\s*inline\s+(const\s+volatile|constexpr(?:\s+const)?)\s+int\s+([A-Za-z_]\w*_TAB)\s*\[")


def _decl_key(line):
    """('d', NAME) for a #define, ('t', NAME, volatile|constexpr) for a flag-table declaration, else None. The kind is part of the key:
    a bake (volatile -> constexpr) is code the candidate must carry (4 Nov: v488's trunk read as built on the v489 bake)."""
    m = DEF.match(line)
    if m:
        return ("d", m.group(1))
    m = TABDEF.match(line)
    return ("t", m.group(2), "constexpr" if m.group(1).startswith("constexpr") else "volatile") if m else None


def live_own_missing(cand, live, parent):
    """[(file, line text)] of LIVE's own added lines vs PARENT that CAND lacks (live_own's rule, listed)."""
    L, P, C = src_files(live), src_files(parent), src_files(cand)
    out = []
    for fn, ll in L.items():
        added = set()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, P.get(fn, []), ll, autojunk=False).get_opcodes():
            if op in ("insert", "replace"):
                added |= {j for j in range(j1, j2) if ll[j].strip()}
        if added:
            cl = C.get(fn, [])
            keep = set()
            for b in difflib.SequenceMatcher(None, ll, cl, autojunk=False).get_matching_blocks():
                keep |= set(range(b.a, b.a + b.size))
            ckeys = {k for x in cl for k in [_decl_key(x)] if k}
            keep |= _edited_on_top(ll, cl, P.get(fn, []))
            out += [(fn, ll[j]) for j in sorted(added - keep) if _decl_key(ll[j]) not in ckeys]
    return out


def revises_waived(missing):
    """10 Nov (Builder: a fix of a line v682 itself shipped, CIS bit 2, must change live's own lines): marker REVISES='FILE:TEXT[;FILE:TEXT]'
    names live lines a candidate changes on purpose; a missing line is waived when its file matches and TEXT is a substring of it.
    -> (not waived, waived)"""
    ws = [w.split(":", 1) for w in os.environ.get("REVISES", "").split(";") if ":" in w]
    keep, gone = [], []
    for fn, ln in missing:
        (gone if any(fn == f.strip() and t.strip() and t.strip() in ln for f, t in ws) else keep).append((fn, ln))
    return keep, gone


def _edited_on_top(ll, cl, pl):
    """10 Nov (Builder: cia3/vxbA, v682-base donors that edit a line v682 shipped, were skipped as 'not built on live'): live lines j that CAND
    replaced with a line that is neither live's nor any parent line, i.e. an edit ON TOP of live's change (the idea's own change of that line).
    A replacement equal to a parent line is a revert (FIGHT_R = 6 -> 8) and a deleted line is lost: neither counts. -> set of j"""
    ps = {x.strip() for x in pl}
    out = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ll, cl, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        rep = [x.strip() for x in cl[j1:j2] if x.strip()]
        if not rep or any(x in ps for x in rep):
            continue
        rtok = set(_TOK.findall(" ".join(_code_part(x) for x in rep)))
        for i in range(i1, i2):  # every token of live's line is still there: the candidate added to it (FIGHT_R = 6 -> 8 drops '6')
            if set(_TOK.findall(_code_part(ll[i]))) <= rtok:
                out.add(i)
    return out


_TOK = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?f?")


def _code_part(x):
    """a source line without its // comment (comments may be reworded by the edit)"""
    i = x.find("//")
    return x if i < 0 else x[:i]


def live_own(cand, live, parent):
    """(LIVE's own added lines vs PARENT that CAND keeps, all of them). A LIVE '#define X ...' or 'X_TAB' declaration counts as kept
    when CAND declares the same X in that file at any value: flags_carried checks the values (4 Nov: a bundle flipping live's
    TDS_BITS 1 -> 3 read 12/13 and shipwatch skipped it as 'not built on live')."""
    L, P, C = src_files(live), src_files(parent), src_files(cand)
    tot = kept = 0
    for fn, ll in L.items():
        added = set()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, P.get(fn, []), ll, autojunk=False).get_opcodes():
            if op in ("insert", "replace"):
                added |= {j for j in range(j1, j2) if ll[j].strip()}
        if added:
            cl = C.get(fn, [])
            keep = set()
            for b in difflib.SequenceMatcher(None, ll, cl, autojunk=False).get_matching_blocks():
                keep |= set(range(b.a, b.a + b.size))
            ckeys = {k for x in cl for k in [_decl_key(x)] if k}
            keep |= {j for j in added - keep if _decl_key(ll[j]) in ckeys}
            keep |= _edited_on_top(ll, cl, P.get(fn, []))
            tot, kept = tot + len(added), kept + len(added & keep)
    return kept, tot


_FLAGVALS = {}


def flag_values(bot):
    """{flag: value} of a bot's flag tables, runtime (const volatile) AND baked (constexpr), read with flip.py's parser, or None.
    3 Nov: a bake (fuels2) turns tables constexpr at live's values; reading only the volatile ones called them 'missing' and armq rebuilt in a loop."""
    if bot not in _FLAGVALS:
        try:
            import flip as F
            src = os.path.join(REPO, "bots", bot, "src")
            files = F.load(src)
            defs = F.defines(files)
            keep = F.TAB_RE
            F.TAB_RE = re.compile(r"inline\s+(?:const\s+volatile|constexpr\s+(?:const\s+)?)\s*int\s+(\w+)\s*\[([^\]]*)\]\s*=\s*\{(.*?)\}\s*;", re.S)
            try:
                tabs = F.tables(files, defs)
            finally:
                F.TAB_RE = keep
            out = {}
            for t in tabs:
                for n in {n for ns in t["names"][1:] for n in ns}:
                    v = str(defs[n][0][1]).strip() if n in defs and defs[n] else ""
                    if re.fullmatch(r"-?\d+", v):
                        out[n] = v
            _FLAGVALS[bot] = out
        except Exception:  # noqa: BLE001  unreadable: the caller treats None as 'cannot tell'
            _FLAGVALS[bot] = None
    return _FLAGVALS[bot]


def flags_carried(cand, live, parent):
    """(ok, why): every flag whose value LIVE changed from PARENT (or a new table LIVE sets non-zero) has LIVE's value in CAND, except CAND's
    own flips. 3 Nov: v466 (pyw1, read in parallel v v464) shipped without v465's RC9_BITS=1: the line rule below lets one #define line through
    its 5% slack when the trunk carries many new lines."""
    lv, pv, cv = flag_values(live), flag_values(parent), flag_values(cand)
    if lv is None or pv is None or cv is None:
        return True, "flag values unreadable"
    fi = flip_info(cand) or {}
    own = set(shipstack.parse_flips(fi.get("FLIPS", "")))
    miss = [f"{k}={v} (cand {cv.get(k, 'absent')})" for k, v in sorted(lv.items())
            if k not in own and cv.get(k) != v and (k in pv and pv[k] != v or k not in pv and v != "0")]
    return not miss, ("live's flag values missing: " + ", ".join(miss)) if miss else "live's flag values carried"


def diffbase_of(live):
    """7 Nov (diff model): the baked base tools/lab/shipbake.py recorded for LIVE after its identity check (bq/diffbase.txt), else None"""
    try:
        a = open(os.path.join(Q, "diffbase.txt")).readline().split()
    except OSError:
        return None
    return a[1] if len(a) > 1 and a[0] == live and a[1] != live and os.path.isdir(os.path.join(REPO, "bots", a[1], "src")) else None


def brace_hits(cand, ref):
    """8 Nov (b1554 ESC, b1573's check): lines CAND inserted right after an unbraced if/else of REF (they steal its body); waived ones left out"""
    try:
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import bracecheck
        return [h for h in bracecheck.hits(cand, ref) if not h[5]]
    except Exception:  # noqa: BLE001  the check must never block on its own failure
        return []


def brace_why(hb):
    return ("bracecheck: " + "; ".join(f"{f}:{ln} '{new[:50]}' after unbraced '{ctl[:50]}'" for f, ln, ctl, new, _b, _w in hb[:3])
            + " (brace the block, or waive in bq/bracecheck_waive.txt)")


def deletions_on_current_base(cand, live, b, parent):
    """10 Nov (Builder: fbb10, a play-identical bundle that DELETES dead code, the contest module, SUP guards and 54 unread tables, read
    'missing 163'): a missing own line of the baked base B is a deliberate deletion when CAND's trunk was merged onto B itself
    (trunk_registry.md: '... nova_base_vNNN + ...' with NNN = live's version) and the line sits in a pure deletion of CAND v B, not an
    edit. A trunk merged onto an older base never had those lines: it stays refused. -> (ok, why)"""
    if not parent or not os.path.isdir(os.path.join(REPO, "bots", parent, "src")):
        return False, ""
    tr = (flip_info(cand) or {}).get("TRUNK", "")
    tv = trunk_base_version(tr) if tr else None
    try:
        lv = next(int(x.split()[0].lstrip("v")) for x in open("/data/USER/st/bq/live.txt") if x.split()[1:2] == [live])
    except (OSError, StopIteration, ValueError):
        return False, ""
    if tv is None or tv != lv or b != f"nova_base_v{lv}":
        return False, ""
    miss = live_own_missing(cand, b, parent)
    if not miss:
        return False, ""
    B, C = src_files(b), src_files(cand)
    deleted = {}
    for fn in {f for f, _ in miss}:
        bl, cl = B.get(fn, []), C.get(fn)
        if cl is None:  # the whole file is gone (a deleted module)
            deleted[fn] = {x.strip() for x in bl}
            continue
        dl = set()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, bl, cl, autojunk=False).get_opcodes():
            if op == "delete":
                dl |= {bl[i].strip() for i in range(i1, i2)}
        deleted[fn] = dl
    rest = [(f, x) for f, x in miss if x.strip() not in deleted.get(f, set())]
    if rest:
        return False, ""
    return True, (f"{len(miss)} of {b}'s own lines deleted on purpose: {cand}'s trunk {tr} was merged onto {b} itself "
                  f"(trunk_registry.md) and every missing line is in a pure deletion")


def base_check(cand, live, parent=None):
    """(ok, why): CAND is built on LIVE (carries LIVE's own change: its lines AND its flag values), else the strict switch-diff rule.
    Diff model: a CAND built on LIVE's baked base (shipbake: LIVE with its shipped flag baked, identity-checked v LIVE) passes on that base."""
    ok, why = base_check_lines(cand, live, parent, need_switch=False)
    if not ok and diffbase_of(live):
        b = diffbase_of(live)
        # 9 Nov (Rule Checker: v649 cgm2b, built on v647's base, shipped over v648 and dropped BB13): with no parent this fallback was the
        # 80%-of-all-lines rule, which a candidate one version stale passes. It now needs the baked base's own lines (v the parent) too.
        ok2, why2 = base_check_lines(cand, b, parent if parent and os.path.isdir(os.path.join(REPO, "bots", parent, "src")) else None,
                                     need_switch=False)
        if not ok2:
            dok, dwhy = deletions_on_current_base(cand, live, b, parent)
            if dok:
                ok2, why2 = True, dwhy
        if not ok2:  # 12 Nov (Builder, lpr4b skip loop): the only lines missing v the baked base are baked flag tables the candidate turns
            #          back into runtime tables (constexpr -> const volatile, same initializer): a variant of a shipped flag, built on that base
            try:
                miss = live_own_missing(cand, b, parent if parent and os.path.isdir(os.path.join(REPO, "bots", parent, "src")) else None)
            except Exception:  # noqa: BLE001
                miss = []
            if miss and len(miss) <= 4:
                C = src_files(cand)
                back = []
                for fn, ln in miss:
                    mm = UNBAKE_RE.match(ln.split("//", 1)[0].strip())
                    hit = next((x for x in C.get(fn, []) if mm and "volatile" in x and UNBAKE_RE.match(x.split("//", 1)[0].strip())
                                and UNBAKE_RE.match(x.split("//", 1)[0].strip()).group(1) == mm.group(1)), None)
                    back.append(hit or "")
                if all(back) and unbake_only([ln for _, ln in miss], back):
                    ok2, why2 = True, f"built on {b}; its only missing lines are baked tables it turns back into runtime tables ({', '.join(UNBAKE_RE.match(ln.split('//', 1)[0].strip()).group(1) for _, ln in miss)})"
        if ok2:
            hb = brace_hits(cand, b)
            if hb:
                return False, brace_why(hb)
            return True, f"built on {b}, the baked base of {live} (bq/diffbase.txt): {why2}"
    if ok:
        hb = brace_hits(cand, live)
        if hb:
            return False, brace_why(hb)
    if ok and parent and os.path.isdir(os.path.join(REPO, "bots", parent, "src")):
        fok, fwhy = flags_carried(cand, live, parent)
        if not fok:
            return False, fwhy
    return ok, why


CALL_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")
CTL_WORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch"}


def flag_first_wrapper(gone, added, c, l, newre):
    """8 Nov (Builder, b1674 GDA: an inline flag test reshaped game_deny_slow, 1.8% of maps changed at flag 0; a noinline wrapper 0.0%): a replaced call is behind a
    switch when the new callee is a short function added in a feat_*.h/.cpp whose body reads a new switch BEFORE the call it replaces. -> the wrapper's name, or None."""
    if not newre:
        return None
    noattr = lambda x: re.sub(r"__attribute__\s*\(\(.*?\)\)", "", x)  # noqa: E731
    was = {m for x in gone for m in CALL_RE.findall(x)} - CTL_WORDS
    now = {m for x in added for m in CALL_RE.findall(x)} - CTL_WORDS
    removed, fresh = was - now, now - was
    if not removed or not fresh:
        return None
    for name in sorted(fresh):
        defre = re.compile(r"^[^=;()]*\b" + re.escape(name) + r"\s*\([^;]*$")  # a definition's head: a type before the name, no ';' on the line
        q = next((m.group(1) for x in added for m in [re.search(r"(\w+)::" + re.escape(name) + r"\s*\(", x)] if m), None)  # gda::walk must be in feat_gda.*
        for fn, lines in c.items():
            if not any(k.endswith(".cc") for k in c) and (not os.path.basename(fn).startswith("feat_") or (q and q not in os.path.basename(fn))):  # new layout: any module
                continue
            for i, x in enumerate(lines):
                if x.lstrip().startswith("//") or not defre.match(noattr(x)) or x in l.get(fn, []):  # new in this file (another feature may own a walk() too)
                    continue
                body, depth, opened = [], 0, False
                for y in lines[i:i + 16]:
                    body.append(y)
                    depth += y.count("{") - y.count("}")
                    opened = opened or "{" in y
                    if opened and depth <= 0:
                        break
                else:
                    continue  # no end within 16 lines: not a thin wrapper
                text = "\n".join(body[1:] if "{" not in body[0] else [body[0].split("{", 1)[1]] + body[1:])
                flag = newre.search(text)
                if flag and all(re.search(r"\b" + re.escape(r) + r"\s*\(", text[flag.end():]) for r in removed):
                    return name
    return None


CONFLICT_RE = re.compile(r"^(?:<{7}|>{7})(?: |$)|^={7}$", re.M)


def conflict_markers(bot):
    """'file:line, ...' of git merge-file conflict markers (<<<<<<< / ======= / >>>>>>> at a line start) in BOT's src/, else ''."""
    src = os.path.join(bot, "src") if os.path.isdir(bot) else os.path.join(REPO, "bots", bot, "src")
    hits = []
    for f in sorted(glob.glob(os.path.join(src, "*"))):
        if os.path.isfile(f) and f.endswith((".h", ".cc", ".cpp", ".c", ".hpp")):
            try:
                txt = open(f, errors="replace").read()
            except OSError:
                continue
            for m in CONFLICT_RE.finditer(txt):
                hits.append(f"{os.path.basename(f)}:{txt.count(chr(10), 0, m.start()) + 1}")
                if len(hits) >= 4:
                    return ", ".join(hits)
    return ", ".join(hits)


UNBAKE_RE = re.compile(r"^\s*inline\s+(?:constexpr(?:\s+const)?|const\s+volatile)\s+int\s+([A-Za-z_]\w*_TAB)\s*(\[\d*\]\s*=\s*\{[^}]*\})")


def unbake_only(gone, added):
    """True when the change only turns baked flag tables back into flippable ones: each removed line is `inline constexpr int X_TAB[n] = {...}`
    and the added lines are the same tables as `inline const volatile int X_TAB[n] = {...}` with the same initializer (comments ignored).
    The values stay as live's, so flag 0 plays identically (prearm ident proves it); the line's flips then patch the data (12 Nov, TB: DTZ
    arm B, a value-only DTM_PP change on a table live had baked)."""
    strip = lambda x: x.split("//", 1)[0].strip()  # noqa: E731
    g = [strip(x) for x in gone if strip(x)]
    a = [strip(x) for x in added if strip(x)]
    if not g or len(g) != len(a):
        return False
    for x, y in zip(g, a):
        mx, my = UNBAKE_RE.match(x), UNBAKE_RE.match(y)
        if not (mx and my and "constexpr" in x and "volatile" in y and mx.group(1) == my.group(1)
                and re.sub(r"\s+", "", mx.group(2)) == re.sub(r"\s+", "", my.group(2))):
            return False
    return True


def base_check_lines(cand, live, parent=None, need_switch=True):
    """(ok, why): CAND is built on LIVE (carries LIVE's own change), else the strict switch-diff rule.
    need_switch=False (owner 8 Nov: 'remove the switch rule for the ships, it wasted fuel; we only need it for firing and identity'): the ship path. Without a parent
    to compare, CAND only has to hold most of LIVE's lines. prearm and newfeat still ask for the switch: flag 0 is how they prove identity and count firing."""
    cm = conflict_markers(cand)
    if cm:  # 9 Nov (Builder: b1762's v658 rebase left git merge-file markers in econ_flags.h and this check passed it)
        return False, f"{cand} holds unresolved merge conflict markers: {cm}"
    if parent and os.path.isdir(os.path.join(REPO, "bots", parent, "src")):
        k, t = live_own(cand, live, parent)
        if t:
            # 10 Nov (Rule Checker): 95% let a candidate on v680's base pass as 'built on v681' at 36/37, the missing line being v681's
            # whole change (FIGHT_R = 6): a PASS would have shipped and reverted the owner's ship. Every own line of live is needed now
            # (SC_LIVE_OWN_SLACK lines may be missing); a refused candidate takes shipwatch's rebase path, which merges the line in.
            slack = int(os.environ.get("SC_LIVE_OWN_SLACK", "0"))
            if k < t - slack and os.environ.get("REVISES", "").strip():
                keep, gone = revises_waived(live_own_missing(cand, live, parent))
                if len(keep) <= slack:
                    return True, (f"{k}/{t} of {live}'s own lines (vs {parent}) present in {cand}; {len(gone)} revised on purpose (REVISES): "
                                  + "; ".join(f"{f}: {x.strip()[:60]}" for f, x in gone))[:400]
                return False, (f"{k}/{t} of {live}'s own lines (vs {parent}) present in {cand}: missing {len(keep)} not named in REVISES, e.g. "
                               + "; ".join(f"{f}: {x.strip()[:70]}" for f, x in keep[:3]))
            if k < t - slack:
                miss = live_own_missing(cand, live, parent)
                return False, (f"{k}/{t} of {live}'s own lines (vs {parent}) present in {cand}: missing {t - k}, live's change not carried, e.g. "
                               + "; ".join(f"{f}: {x.strip()[:70]}" for f, x in miss[:3]) + " (a deliberate revision: armq add --revises-live 'FILE:TEXT')")
            return True, f"{k}/{t} of {live}'s own lines (vs {parent}) present in {cand}"
    c, l = src_files(cand), src_files(live)
    if not c or not l:
        return False, f"no sources for {cand if not c else live}"
    if not need_switch:
        have = collections.Counter(x.strip() for f in c.values() for x in f if x.strip())
        want = collections.Counter(x.strip() for f in l.values() for x in f if x.strip())
        k, t = sum((have & want).values()), sum(want.values())
        return k >= 0.80 * t, f"{k}/{t} of {live}'s lines present in {cand} (no switch needed to ship)"
    ldefs = {m.group(1) for f in l.values() for x in f for m in [DEF.match(x)] if m}
    new = {m.group(1) for f in c.values() for x in f for m in [DEF.match(x)] if m} - ldefs
    newre = re.compile(r"\b(" + "|".join(map(re.escape, sorted(new))) + r")\b") if new else None
    bad = []
    for fn in sorted(set(l) - set(c)):
        bad.append(f"{fn}: live file missing")
    for fn in sorted(set(l) & set(c)):
        a, b = l[fn], c[fn]
        if a == b:
            continue
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op in ("equal", "insert"):
                continue
            gone = [x for x in a[i1:i2] if x.strip()]
            if not gone:
                continue
            if op == "replace":
                added = b[j1:j2]
                if newre and any(newre.search(x) for x in added):
                    continue
                cdefs = {DEF.match(x).group(1) for x in added if DEF.match(x)}
                if all(DEF.match(x) and DEF.match(x).group(1) in cdefs for x in gone):
                    continue  # a changed #define value
                if flag_first_wrapper(gone, added, c, l, newre):
                    continue  # the call now goes through a flag-first wrapper (the flag test is read before the old call)
                if unbake_only(gone, added):
                    continue  # 12 Nov (TB; Builder b2185 DTZ): X_TAB constexpr -> const volatile, same initializer: identical at flag 0, flippable again
            bad.append(f"{fn}:{i1 + 1}: {len(gone)} live line(s) {'deleted' if op == 'delete' else 'changed'} without a new "
                       f"switch: {gone[0].strip()[:60]!r}")
    if bad:
        return False, "; ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")
    return True, f"new switches: {', '.join(sorted(new)) or 'none'}"


# ---------------------------------------------------------------- legs
def launch(name, cmd, env, log):
    say(f"leg {name}: {cmd} (log {log})")
    return subprocess.Popen(cmd, shell=True, cwd=REPO, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT,
                            start_new_session=True)


def read(p):
    try:
        return open(p, errors="replace").read()
    except OSError:
        return ""


def name_owners(name):
    """Bot pairs that already own a condab run NAME (condab's own rule: abl run dirs' bots.txt + the summary header)."""
    used = set()
    for bt in glob.glob(f"/data/USER/abl/cq_{name}_*/bots.txt"):
        used.add(" vs ".join(x.split()[0] for x in open(bt) if x.strip()))
    hm = re.match(r"# condab \S+: (\S+?)@\S+ vs (\S+?)@", read(os.path.join(Q, name + ".condor.txt")).split("\n")[0])
    if hm:
        used.add(f"{hm.group(1)} vs {hm.group(2)}")
    return used


def run_tag(tag, cand, live, prefixes=None, suffix=None):
    """TAG while nd/cf/kp/ps+TAG are free or owned by this check's own pairs, else TAG_<cand source hash 6>; with prefixes=("",)
    a single name for the pair (cand, live), suffixed by suffix when taken."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    if prefixes == ("",):
        ok = lambda n: name_owners(n) <= {f"{cand} vs {live}"}  # noqa: E731
        return tag if ok(tag) else f"{tag}{suffix or abindex.bot_hash(cand)[:6]}"
    opp = "nova_spar_nochase2"
    pairs = (("nd", cand, opp), ("cf", cand, live), ("kp", cand, live), ("ps", cand, opp), ("lh", cand, live), ("lx", cand, live))
    free = lambda t: all(name_owners(f"{p}{t}") <= {f"{a} vs {b}"} for p, a, b in pairs)  # noqa: E731
    if free(tag):
        return tag
    t2 = f"{tag}_{(abindex.bot_hash(cand) or 'x' * 6)[:6]}"
    return t2 if free(t2) else f"{t2}{os.urandom(2).hex()}"


def ref_runs(live):
    """Every abl run of LIVE vs nochase2 (comma list for STOP_REF / BASE_ND)."""
    nnn = re.match(r"nova_b(\d+)", live)
    runs = []
    for d in sorted(glob.glob(f"/data/USER/abl/cq_nd{nnn.group(1) if nnn else 'x'}*_*")):
        try:
            bots = {x.split()[0] for x in open(os.path.join(d, "bots.txt")) if x.strip()}
        except OSError:
            continue
        if bots == {live, "nova_spar_nochase2"} and os.path.exists(os.path.join(d, "games.jsonl")):
            runs.append(os.path.basename(d))
    return ",".join(runs)


def index_ref(live, maps, rtag):
    """A run-format dir (games.jsonl, games.list, bots.txt) of LIVE vs nochase2 games on MAPS from the index (every source:
    abl runs, earlier checks' legs, top-ups that were all cache hits) -> its path, for BASE_ND / STOP_REF."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    opp = "nova_spar_nochase2"
    hl, ho = abindex.bot_hash(live), abindex.bot_hash(opp)
    ix, nm, inv = abindex.Index({hl, ho}), abindex.map_names(), {hl: live, ho: opp}
    d = os.path.join(Q, "refs", f"{live}_{rtag}")
    os.makedirs(d, exist_ok=True)
    rows = [(inv[ha], inv[hb], nm[mh], g) for (ha, hb, mh), g in ix.games.items()
            if ha in inv and hb in inv and ha != hb and nm.get(mh) in set(maps)]
    with open(os.path.join(d, "games.jsonl"), "w") as gj, open(os.path.join(d, "games.list"), "w") as gl:
        for i, (a, b, m, g) in enumerate(rows, 1):
            gj.write(json.dumps(dict(id=str(i), a=a, b=b, map=m, ok=True, win=g["win"], rounds=g.get("rounds", 0),
                                     sa=g.get("sa", {}), sb=g.get("sb", {}))) + "\n")
            gl.write(f"{i} {a} {b} {m}\n")
    open(os.path.join(d, "bots.txt"), "w").write(f"{live} {hl} index\n{opp} {ho} index\n")
    return d


def ref_maps(bnd, live):
    """Maps on which the reference runs hold both of LIVE's seats against nochase2 (pair_d.scores on the merged runs)."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import condab
    try:
        ref = condab.ref_run(bnd, "nova_spar_nochase2")
    except SystemExit:
        return set()
    return set(condab.pair_d()["scores"](ref[1], ref[2]))


HARNESS = re.compile(r"condab: NAME \S+ was used by|have the same source|STOP_REF \S+: (no games|its games)|rebase onto live|"
                     r"no bots/\S+/src|no nochase2 run of|patch_pos\.py failed|Traceback \(most recent call last\)|"
                     r"(?:^|\n)Killed(?:\n|$)|MemoryError|oom-kill|stratmaps: class \S+: \d+ of \d+ maps from \d+ tried .{0,60}SHORT by \d+")  # 12 Nov (TB, osq1s 13306): a class draw short of its tries cap is a harness shortfall, not capacity  # 9 Nov (Deep: wglds 10190): a leg the kernel OOM-killed is a harness fault, re-armed, not capacity


def inconclusive_cause(rows, tag, rtag):
    """"harness (...)" when a no-result leg was refused by the harness (name, source, reference, base), else "capacity"."""
    logs = {"nochase2 paired D": [f"nd{rtag}.log", f"sc_{tag}_scr.log", f"sc_{tag}_ref.log"], "CONFIRM": [f"sc_{tag}_cf.log"],
            "trigger D": [f"sc_{tag}_tr.log"], "trigger h2h": [f"sc_{tag}_th.log"], "live h2h": [f"sc_{tag}_lh.log"], "live h2h+ext": [f"sc_{tag}_lx.log"],
            "ubaudit": [f"sc_{tag}_ub.log"], "fresh maps": [f"sc_{tag}_sp.log"], "playstyle panel": [f"sc_{tag}_sp.log"],
            "draft changed maps": [f"sc_{tag}_sp.log"], "confirm fresh": [f"sc_{tag}_sp.log"], "confirm changed maps": [f"sc_{tag}_sp.log"]}
    # 12 Nov ~22:0xZ (TB: eqr3cs 13760, a confirm of a line that had shipped as live, read 'capacity' and re-armed: its leg's condab refusal
    # "... have the same source" is in fp<tag>.condor.log, which no row looked at): the fresh / panel / confirm rows also read their condab logs
    for k_ in ("fresh maps", "playstyle panel", "confirm fresh", "confirm changed maps", "draft changed maps"):
        logs[k_] = logs[k_] + [f"fp{tag}.condor.log", f"fp{rtag}.condor.log"]  # 8 Nov (2781): a patch_pos anchor miss read as 'capacity'; 10002: a stylepanel crash too
    why = []
    for r in rows:  # 9 Nov (Deep: wglb 10175 / wglbi 10180 parked as 'capacity'): the trunk-code row's own gate keeps its logs under its gate tag
        g = re.search(r"gate (tc[0-9a-f]+)", r[1]) if r[0] == "trunk code vs live" and r[3] == "INCONCLUSIVE" else None
        if g:
            for lg in (f"fp{g.group(1)}.stylepanel.log", f"../gate/{g.group(1)}/sp.log", f"../gate/{g.group(1)}/kg.log"):
                m = HARNESS.search(read(os.path.join(Q, lg)))
                if m:
                    why.append(f"{r[0]}: {m.group(0)[:60]}")
                    break
            else:
                if "nan [nan, nan]" in r[1]:  # a leg that returned no games at all is a harness fault, not a capacity shortfall
                    why.append(f"{r[0]}: a leg of gate {g.group(1)} returned no games")
    for r in rows:
        if r[3] == "INCONCLUSIVE" and r[0] in logs:
            for lg in logs[r[0]]:
                m = HARNESS.search(read(os.path.join(Q, lg)))
                if m:
                    why.append(f"{r[0]}: {m.group(0)[:60]}")
                    break
    for r in rows:  # 9 Nov 20:05Z (Builder: drcdxi 10309 'capacity' cut MAX_RUNNING to 2): a draft probe stopped by its rarity cap is a rare change
        if r[0] == "draft changed maps" and r[3] == "INCONCLUSIVE":
            m = re.search(r"firing ([0-9.]+)% < ([0-9.]+)% after (\d+) maps", r[1] + " " + read(os.path.join(Q, f"sc_{tag}_sp.log")))
            if m:
                return f"too rare (draft probe: firing {m.group(1)}% < {m.group(2)}% after {m.group(3)} maps: re-read on the rare lane)"
    dz = re.search(r"draft probe: 0 of (\d+) probed maps changed", read(os.path.join(Q, f"sc_{tag}_sp.log")))
    if dz:  # 12 Nov (TB, pzl1s 13211: 0 of 40,031 probed maps changed, re-armed as capacity): a draft change that fires 0 times changes no game (owner: stays closed)
        return f"too rare (never changes play: draft probe 0 of {dz.group(1)} probed maps changed; count where the draft clause fires before another read)"
    nv = re.search(r"never changes play: 0 of (\d+) targeted maps changed", read(os.path.join(Q, f"sc_{tag}_sp.log")))
    if nv:  # 11 Nov (Builder, rgp1vs): no re-arm; the line needs a firing count where its clause changes play
        return f"too rare (never changes play: 0 of {nv.group(1)} targeted maps changed; count where the clause fires before another read)"
    for r in rows:  # 8 Nov (Builder): a common change on the rare lane goes to the behaviour lane (a stricter bar), not a rare re-read
        m = re.search(r"not a rare change: (\d+)% of maps changed", r[1]) if r[0] == "rare changed maps" and r[3] == "INCONCLUSIVE" else None
        if m:
            return f"not rare ({m.group(1)}% of maps changed: re-read on the behaviour lane)"
    if not why:  # 8 Nov (vsr4 2675: 3 of 6285 pool maps changed): a rare read that would need >10x the maps it probed is not short of
        # capacity, it can't reach its bar at all; re-arming only repeats it. The Builder routes it (pending_reads.txt)
        for r in rows:
            m = re.search(r"n (\d+)/\d+ .*?\((\d+) of (\d+) pool maps changed", r[1]) if r[0] == "rare changed maps" and r[3] == "INCONCLUSIVE" else None
            if m:
                n, c, pr = int(m.group(1)), int(m.group(2)), int(m.group(3))
                need = RARE.get("min", 400) * pr / max(c, 1)
                # 10 Nov (TB 6ad907, tws1b 11708: 0 of 598 pool maps but 9 of 300 targeted w_checker_big changed): with targeted families, judge
                # on the targeted share too; a change that shows on its target class is reachable there (SP_CHANGED_TARGETED_ONLY=1 draws only those)
                tm = re.search(r"targeted families: (\d+) of (\d+) changed", read(os.path.join(Q, f"sc_{tag}_sp.log")))
                if tm and int(tm.group(1)) > 0:
                    tneed = RARE.get("min", 400) * int(tm.group(2)) / int(tm.group(1))
                    if tneed <= int(os.environ.get("SC_RARE_TARGET_MAX", 30000)):
                        continue  # not too rare on its targeted class: capacity (re-armed with SP_CHANGED_TARGETED_ONLY=1)
                if n < RARE.get("min", 400) and need > 10 * pr:
                    return (f"too rare ({c} of {pr} pool maps changed, {100 * c / max(pr, 1):.2f}%: ~{need:,.0f} maps to probe for "
                            f"{RARE.get('min', 400):g} changed; the rare bar can't be reached)")
    return f"harness ({'; '.join(why)})" if why else "capacity"


def trigger_subset(tag, trigger, n, seed=None):
    """All trigger maps of the 636 pool + a fresh family-stratified random fill to n -> (file, trigger maps in, not in).
    seed (7 Nov, SC_REF_LIVE): the fill is drawn from this seed (one per live version), so every check against one live shares the
    subset and live's nochase2 reference on it is played once; trigger maps are still added per check."""
    import random
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    import condab
    allm = condab.set_maps("all")
    trig = [x.strip() for x in open(trigger) if x.strip()] if trigger else []
    inst = abindex.maps()
    tin = [m for m in trig if m in inst]          # every installed trigger map, in the 636 pool or not (b204: 2 of 16 were)
    tout = [m for m in trig if m not in inst]
    rest = [m for m in allm if m not in set(tin)]
    need = max(0, n - len(tin))
    rng = random.Random(seed) if seed else random.Random(int.from_bytes(os.urandom(8), "big"))
    fam = collections.defaultdict(list)
    for m in rest:
        fam[abindex.map_set(m)].append(m)
    quota = {f: need * len(ms) / max(1, len(rest)) for f, ms in fam.items()}
    take = {f: int(q) for f, q in quota.items()}
    for f in sorted(quota, key=lambda f: -(quota[f] - take[f]))[:need - sum(take.values())]:
        take[f] += 1
    fill = [m for f, ms in fam.items() for m in rng.sample(ms, min(take[f], len(ms)))]
    os.makedirs(os.path.join(Q, "subsets"), exist_ok=True)
    sf = os.path.join(Q, "subsets", f"sub_{tag}.txt")
    open(sf, "w").write("".join(m + "\n" for m in tin + fill))
    open(os.path.join(Q, "subsets", f"trig_{tag}.txt"), "w").write("".join(m + "\n" for m in tin))
    return sf, tin, tout


def trigger_d(cand, live, tmaps):
    """pair_d D of CAND vs LIVE against nochase2 on exactly the trigger maps (both from the index: the trigger-ref leg plays
    live there, since most trigger maps lie outside the 636 pool and live's nd runs) -> (n, D, lo, hi, maps changed)."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    import condab
    opp = "nova_spar_nochase2"
    pd = condab.pair_d()
    nm = abindex.map_names()

    def scores(bot):
        h, ho = abindex.bot_hash(bot), abindex.bot_hash(opp)
        ix, inv = abindex.Index({h, ho}), {h: bot, ho: opp}
        tmp = os.path.join(Q, f".trig_{bot}")
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, "games.jsonl"), "w") as f:
            for (ha, hb, mh), g in ix.games.items():
                if nm.get(mh) in set(tmaps) and ha in inv and hb in inv:
                    f.write(json.dumps(dict(a=inv[ha], b=inv[hb], map=nm[mh], ok=True, win=g["win"])) + "\n")
        return pd["scores"](os.path.relpath(tmp, "/data/USER/abl"), bot)
    c, b = scores(cand), scores(live)
    ds = [c[m] - b[m] for m in tmaps if m in c and m in b]
    if not ds:
        return 0, 0.0, 0.0, 0.0, 0
    mu, lo, hi = pd["boot"](ds) if len(ds) > 1 else (ds[0], ds[0], ds[0])
    return len(ds), mu, lo, hi, sum(1 for d in ds if d != 0)


FUEL_CAP = int(os.environ.get("SC_FUEL_CAP", "5"))  # exhaustions counted per side per game, at most this many
FUEL_Z = float(os.environ.get("SC_FUEL_Z", "1.645"))  # FAIL needs CAND - LIVE > max(5% of LIVE, FUEL_Z x paired SE, 5); one-sided 5% (Builder 1 Nov: "did fuel go up")


def panel_recs(tag, cand, live):
    """[(map, CAND stats, LIVE stats)] from stylepanel's fp_games.jsonl: the fresh leg's CAND v LIVE games."""
    out = []
    for ln in read(f"/data/USER/st/panel/{tag}/fp_games.jsonl").splitlines():
        try:
            g = json.loads(ln)
        except ValueError:
            continue
        if {g["a"], g["b"]} == {cand, live}:
            out.append((g["map"], *((g["sa"], g["sb"]) if g["a"] == cand else (g["sb"], g["sa"]))))
    return out


def fuel_paired(cand, base):
    """FUEL rule (1 Nov, Builder; fuelbuild_1101.md: a behaviour-neutral recompile reads 1.06-1.08x vs LIVE when one seat on a
    spike map falls into a chain of 30-100 exhaustions, so the raw 1.05x bar sat at 0.2-1 SE): every CAND vs BASE game on
    record (abindex, both seats: the legs of this check and any earlier run of the same two sources), each side's count per
    game capped at FUEL_CAP, the difference paired by map (SE over maps). None without games or with equal sources."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    hc, hb = abindex.bot_hash(cand), abindex.bot_hash(base)
    if not hc or not hb or hc == hb:
        return None
    per = collections.defaultdict(lambda: [0, 0, 0, 0])  # map -> [cand capped, base capped, cand raw, base raw]
    AFTER = [0, 0]
    if RARE.get("tag") or CONFIRM.get("tag"):  # no BIG: the read's own games, which the index doesn't hold (CONFIRM MODE: the confirm read's)
        recs = panel_recs(RARE.get("tag") or CONFIRM["tag"], cand, base)
    else:
        recs = [(mh, *((g["sa"], g["sb"]) if ha == hc else (g["sb"], g["sa"]))) for (ha, hbb, mh), g in abindex.Index({hc, hb}).games.items() if {ha, hbb} == {hc, hb}]
    for mh, sc, sb in recs:
        # 13 Nov (PCQ, owner via the Coordinator): cut-offs AFTER the turn's actions (cxe 'fuelExhaustedAfterActions', marker bots only, 0 for every
        # other bot) are information, so cap5 counts the cut-offs before the actions; the after-action count rides along as ra/rab.
        ac, ab = int(sc.get("fuel_after", 0)), int(sb.get("fuel_after", 0))
        AFTER[0] += ac; AFTER[1] += ab
        fc, fb = int(sc.get("fuel", 0)) - ac, int(sb.get("fuel", 0)) - ab
        p = per[mh]
        p[0] += min(fc, FUEL_CAP); p[1] += min(fb, FUEL_CAP); p[2] += fc; p[3] += fb
    if not per:
        return None
    d = [p[0] - p[1] for p in per.values()]
    mu = sum(d) / len(d)
    se = math.sqrt(len(d) * sum((x - mu) ** 2 for x in d) / max(1, len(d) - 1))
    c, b = sum(p[0] for p in per.values()), sum(p[1] for p in per.values())
    return dict(c=c, b=b, rc=sum(p[2] for p in per.values()), rb=sum(p[3] for p in per.values()), se=se, maps=len(d), ra=AFTER[0], rab=AFTER[1],
                z=(c - b) / se if se > 0 else 0.0, fail=c - b > max(0.05 * b, FUEL_Z * se, 5))


FUELX_CUM = float(os.environ.get("SC_FUELX_CUM", "2.0"))
FUELRATIO = os.environ.get("SC_FUEL_RATIO", os.path.join(Q, "fuelratio.txt"))  # owner 7 Nov: one line 'pct_per_point 10'. No file: no ratio row, today's fuel bar
FUELBANK = os.environ.get("SC_FUEL_BANK", os.path.join(Q, "fuelbank.tsv"))
FUELBANK_COLS = ("t", "tag", "cand", "base", "version", "lane", "donor", "flips", "point", "n", "cap5", "heavy", "subject")
FUEL_FIRST = {}  # the fuel row as table() made it: fuel_ratio runs twice, the second time on the final read


def fuel_pct():
    w = read(FUELRATIO).split()
    return float(w[1]) if len(w) >= 2 and w[0] == "pct_per_point" else 0.0


def fuel_allowed(base, se, point):
    """The excess a read's gain buys: max(5% of base, FUEL_Z SE, 5, pct_per_point per point above .50), in the figure's own units."""
    return max(0.05 * base, FUEL_Z * se, 5, base * fuel_pct() / 100 * max(0.0, (point - 0.5) * 100))


def deciding_read(rows):
    """(point, n, row name) of the read that decides: rare, pooled, near-miss, live h2h (+ ext), gate's BIG. (None, 0, '') without one."""
    for name in ("confirm fresh", "confirm changed maps", "rare changed maps", "pooled BIG + fresh", "live h2h (near-miss ext)", "live h2h+ext", "live h2h", "BIG (killgate)"):
        r = next((x for x in rows if x[0] == name), None)
        m = re.search(r"([\d.]+) \[[\d.]+, [\d.]+\](?: n (\d+))?", r[1]) if r else None
        if m:
            return float(m.group(1)), int(m.group(2) or 0), name
    return None, 0, ""


def heavy_go(cand, live, tag):
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    try:
        import heavyfuel
        FUEL_FIRST["h"] = heavyfuel.read(cand, live, f"/data/USER/st/heavy/{tag}", say=say)
    except Exception as e:  # noqa: BLE001  (a tool failure is INCONCLUSIVE, never a FAIL)
        say(f"!! heavy-turn read failed: {type(e).__name__}: {e}")
        FUEL_FIRST["h"] = None


def heavy_read(cand, live, tag):
    """tools/lab/heavyfuel.py once per check, the figure or None. main() starts it beside the other legs: 30 s on idle pilots, 10 min on busy ones (7 Nov)."""
    t = FUEL_FIRST.get("t")
    if t:
        t.join(timeout=3600)
    if "h" not in FUEL_FIRST:
        heavy_go(cand, live, tag)
    return FUEL_FIRST.get("h")


def draft_rand_row(cand, live):
    """10 Nov (Builder; owner 9 Nov: the draft never runs out of fuel): games where a draft turn ended with no pick (cxe stats
    draftRandomPicks, condab's 'draftrand'), CAND v LIVE on the same games as the capped-fuel row. FAIL when CAND has more such games
    than LIVE. Records from before the field (no 'draftrand') are left out; none at all -> INCONCLUSIVE, which does not block."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    hc, hb = abindex.bot_hash(cand), abindex.bot_hash(live)
    if not hc or not hb:
        return None
    if RARE.get("tag") or CONFIRM.get("tag"):
        recs = panel_recs(RARE.get("tag") or CONFIRM["tag"], cand, live)
    elif hc == hb:
        return None
    else:
        recs = [(mh, *((g["sa"], g["sb"]) if ha == hc else (g["sb"], g["sa"]))) for (ha, hbb, mh), g in abindex.Index({hc, hb}).games.items() if {ha, hbb} == {hc, hb}]
    known = [(sc, sb) for _, sc, sb in recs if "draftrand" in sc and "draftrand" in sb]
    c = sum(1 for sc, _ in known if int(sc["draftrand"]) > 0)
    b = sum(1 for _, sb in known if int(sb["draftrand"]) > 0)
    val = f"CAND {c} v LIVE {b} games with a draft turn cut before its pick ({len(known)} games with the field)"
    if not known:
        return ("draft random picks", "no game records carry draftrand yet (cxe stats from 10 Nov ~06:00Z)", "CAND <= LIVE", "INFO")
    return ("draft random picks", val, "CAND <= LIVE (owner 9 Nov: the draft never runs out of fuel)", "FAIL" if c > b else "PASS")


def fuel_ratio(rows, cand, live, tag):
    """CHANGE V FUEL RATIO (owner 7 Nov), every lane, on while FUELRATIO holds a value. Fuel only matters on turns near the budget, so both figures are heavy-turn ones, never mean
    fuel: cap5 (turns that ran out, FUEL_CAP per side per game) and heavy (turns at >= heavyfuel.NEAR of their budget, which cap5 cannot see). Each may exceed the base by fuel_allowed().
    A fuel row that only fails today's bar passes when both are inside; the row is shown either way.
    Rule (a), owner 9 Nov: fuel is judged on cut-offs. The heavy-turn figure fails a line only when cap5 is also above the base (its heavy turns cost extra cuts);
    with cap5 at or below the base it is reported as information."""
    rows = [r for r in rows if r[0] != "draft random picks"]
    try:
        dr = draft_rand_row(cand, live)
    except Exception as e:  # noqa: BLE001  the row must never break a check
        dr = ("draft random picks", f"not read ({e!r})"[:120], "CAND <= LIVE", "INFO")
    if dr:
        k = next((j for j, r in enumerate(rows) if r[0] == "bot faults (CAND)"), len(rows) - 1)
        rows.insert(k + 1, dr)
    i = next((k for k, r in enumerate(rows) if r[0] == "fuel exhaustions"), None)
    rows = [r for r in rows if r[0] != "change v fuel ratio"]
    if i is None or fuel_pct() <= 0:
        return rows, _verdict(rows)
    i = next(k for k, r in enumerate(rows) if r[0] == "fuel exhaustions")
    rows[i] = FUEL_FIRST.setdefault("row", rows[i])
    f, (pt, _, name) = fuel_paired(cand, live), deciding_read(rows)
    bar = f"max(5%, {FUEL_Z:g} SE, {fuel_pct():g}%/point): cap{FUEL_CAP}; heavy turns too when cap{FUEL_CAP} is up (rule (a))"
    if f is None or pt is None or rows[i][3] == "INCONCLUSIVE":
        rows.append(("change v fuel ratio", "no paired fuel record or no deciding read", bar, "INCONCLUSIVE"))
        return rows, _verdict(rows)
    h = heavy_read(cand, live, tag)
    if h is None:
        rows.append(("change v fuel ratio", "no heavy-turn read", bar, "INCONCLUSIVE"))
        return rows, _verdict(rows)
    ph = pt
    if name in ("rare changed maps", "confirm changed maps"):  # cap5 is read on the changed maps, heavy on a pool draw: its gain is the changed share of the read's
        m = re.search(r"changed ([\d.]+)% of pool maps", next((r[1] for r in rows if r[0] == ("rare implied effect" if name == "rare changed maps" else name)), ""))
        ph = 0.5 + (pt - 0.5) * float(m.group(1)) / 100 if m else 0.5
    ac, ah = fuel_allowed(f["b"], f["se"], pt), fuel_allowed(h["b"], h["se"], ph)
    h_ok = h["c"] - h["b"] <= ah
    h_info = not h_ok and f["c"] - f["b"] <= 0  # rule (a), owner 9 Nov: heavy turns that cause no extra cut-offs do not fail
    ok = f["c"] - f["b"] <= ac and (h_ok or h_info)
    val = (f"gain {100 * (pt - 0.5):+.2f} pt ({name}): cap{FUEL_CAP} {f['c'] - f['b']:+d} of {f['b']} (allowed {ac:.0f}); heavy turns {h['c'] - h['b']:+d} of {h['b']} (allowed {ah:.0f}, "
           f"p99 turn {h['p99c']}% v {h['p99b']}% of budget, {h['maps']} maps)"
           + ("; heavy over its allowance with no extra cuts: information only (rule (a), owner 9 Nov)" if h_info else "")
           + (f"; heavy turns are pre-action fuel (v2 marker); whole turn incl. intentional post-action spending {h['wc']} v {h['wb']}: information"
              if h.get("wc") is not None and (h.get("wc"), h.get("wb")) != (h["c"], h["b"]) else ""))
    if rows[i][3] == "FAIL" and ok:
        rows[i] = (rows[i][0], rows[i][1], rows[i][2] + "; change v fuel ratio decides", "PASS")
    rows.append(("change v fuel ratio", val, bar, "PASS" if ok else "FAIL"))
    return rows, _verdict(rows)


def bank_fields(cand):
    """(donor, flips, subject) of a line, for the banks."""
    fi = flip_info(cand) or {}
    donor = os.environ.get("DONORS", "-").split(",")[0] or "-"
    tr = os.environ.get("TRUNK", "")
    if donor == "-" and tr:  # 9 Nov (b1750): an armq private trunk carries the idea's code, not live: the donor is on armq's arming line for that trunk
        try:
            for ln in open(os.path.join(Q, "armq.log"), errors="replace"):
                if tr in ln:
                    mm = re.search(r"arming: (\S+:\S+) ", ln)
                    if mm:
                        donor = mm.group(1)
        except OSError:
            pass
    return donor, fi.get("FLIPS", "").strip(), os.environ.get("SUBJECT", "")[:80]


def fuel_bank(rows, overall, cand, live, tag, lane):
    """A line that fails only on fuel (owner 7 Nov) is not closed: one row in FUELBANK. `armq.py fuelbank` lists them and re-arms one."""
    bad = {r[0] for r in rows if r[3] == "FAIL"}
    if overall != "FAIL" or "fuel exhaustions" not in bad or bad - {"fuel exhaustions", "change v fuel ratio"}:
        return
    pt, n, _ = deciding_read(rows)
    donor, flips, subject = bank_fields(cand)
    ver = (open(os.path.join(Q, "live.txt")).readline().split() or ["?"])[0]
    f = fuel_paired(cand, live) or {}
    h = FUEL_FIRST.get("h") or {}
    row = dict(t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tag=tag, cand=cand, base=live, version=ver, lane=lane, donor=donor, flips=flips, point=pt, n=n,
               cap5=f"{f.get('c')}v{f.get('b')}", heavy=f"{h.get('c')}v{h.get('b')}" if h else "-", subject=subject.replace("\t", " "))
    if DRY:
        return say(f"DRY: would add to {FUELBANK}: {row}")
    new = not os.path.exists(FUELBANK)
    with open(FUELBANK, "a") as o:
        o.write(("\t".join(FUELBANK_COLS) + "\n" if new else "") + "\t".join(str(row[c]) for c in FUELBANK_COLS) + "\n")
    say(f"fuel change bank: {cand} (point {pt}, cap5 {row['cap5']})")


def auto_bank(rows, overall, cand, live, tag, lane):
    """FAILED-POSITIVE BANK, automatic (owner 7 Nov): a behaviour or parameter line that ends FAIL or VACUOUS with its deciding point > .50 goes in, with base, read and cause.
    A fuel-only failure goes to fuel_bank instead; a line whose flips are already active in the bank stays as it is."""
    if overall not in ("FAIL", "VACUOUS") or CTRUNK[0] or not (lane in ("behaviour", "param", "fix", "draft") or os.environ.get("PARAMBAR") == "1"):
        return  # 7 Nov (owner: "still keep features that show positives"): fix and draft lines bank too (a fix that reads up but misses = POWER)
    bad = [r[0] for r in rows if r[3] in ("FAIL", "VACUOUS")]
    pt, n, _ = deciding_read(rows)
    if pt is None or pt <= 0.5 or not bad or not set(bad) - {"fuel exhaustions", "change v fuel ratio"}:
        return
    donor, flips, subject = bank_fields(cand)
    txt = " ".join(bad) + " " + " ".join(str(r[1]) for r in rows if r[3] in ("FAIL", "VACUOUS"))
    cause = ("sequential-stop" if "pooled BIG + fresh" in bad and seq_bar() else "kind-gate" if re.search(r"\bkinds?\b", txt) else "trunk-code" if "trunk code vs live" in bad
             else "fuel" if "fuel exhaustions" in bad else "power" if lane == "fix" else "other")
    ver = (open(os.path.join(Q, "live.txt")).readline().split() or ["?"])[0]
    eid = re.sub(r"^nova_b\d+_", "", cand)
    cmd = [sys.executable, "-I", os.path.join(REPO, "tools/lab/flagscreen.py"), "bank", "add", eid, "--bot", cand, "--donor", donor, "--point", f"{pt:.4f}", "--n", str(n), "--base", ver,
           "--fail", ",".join(bad)[:120], "--cause", cause, "--lane", "param" if os.environ.get("PARAMBAR") == "1" else lane, "--note", f"auto, shipcheck {tag}: {subject}"[:120]]
    if DRY:
        return say(f"DRY: would bank: {' '.join(cmd[3:])}")
    try:
        bk = json.load(open("/data/USER/st/fs/bank.json"))
    except (OSError, ValueError):
        bk = {}
    want = sorted(flips.replace(",", " ").split())
    same = next((e["id"] for e in bk.values() if e.get("state") == "active" and flips and sorted(f"{k}={v}" for k, v in e.get("flips", {}).items()) == want), None)
    if same:
        return say(f"failed-positive bank: {eid} already active as {same}")
    if eid in bk:
        cmd[5] = f"{eid}_{tag}"
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    say(f"failed-positive bank: {(p.stdout + p.stderr).strip()[:160]}")
FUEL_ANCHOR = os.path.join(Q, "fuel_anchor.txt")  # the bot the fuel debt is counted from (v562 nova_b1679_bh65clar on 6 Nov)


def fuel_cumulative(cand, ratio):
    """-> (capped-exhaustion ratio of CAND v the anchor, how). Direct when the index holds CAND v anchor games; else the product of the
    fuel-debt ratios of the ledger's bots that went live since the anchor, times this ratio (ships under the plain bar add ~1.0)."""
    try:
        anchor = open(FUEL_ANCHOR).read().split()[0]
    except (OSError, IndexError):
        anchor = "nova_b1679_bh65clar"
    d = fuel_paired(cand, anchor)
    if d and d["maps"] >= 200:
        return d["c"] / max(1, d["b"]), f"direct v {anchor}, {d['maps']} maps"
    try:
        live_names = [ln.split()[1] for ln in open(os.path.join(Q, "live.txt")) if len(ln.split()) > 1]
    except OSError:
        live_names = []
    since = set(live_names[:live_names.index(anchor)]) if anchor in live_names else set(live_names)
    prod, n = 1.0, 0
    try:
        for ln in open(os.path.join(Q, "fuel_debt.txt")):
            m = re.search(r"Z (\S+) v \S+: cap\d+ \d+ v \d+ \(([\d.]+)x", ln)
            if m and m.group(1) in since:
                prod *= float(m.group(2))
                n += 1
    except OSError:
        pass
    return prod * ratio, f"product of {n} live fuel-debt ship(s) since {anchor} x this {ratio:.2f}"


def fuel_row(cand, live, raw_c, raw_b, legs, have_any):
    """The fuel exhaustions row: the FUEL rule on capped, map-paired counts; raw counts and (NULLSW) CAND vs NULL as info."""
    f = fuel_paired(cand, live)
    bar = f"cap{FUEL_CAP}: diff <= max(5%, {FUEL_Z:g} SE)"
    if f is None:  # no record in the index: the old raw rule
        ok = not (raw_c > 1.05 * raw_b and raw_c - raw_b >= 5)
        return ("fuel exhaustions", f"CAND {raw_c} vs LIVE {raw_b} ({legs}; raw, no paired record)", "not (> 1.05x and +5)",
                "INCONCLUSIVE" if not have_any else ("PASS" if ok else "FAIL"))
    val = ((f"[pre-action cut-offs; after-action {f['ra']} v {f['rab']}: information (PCQ)] " if f.get('ra') or f.get('rab') else "")
           + f"cap{FUEL_CAP} {f['c']} vs {f['b']} ({f['c'] / max(1, f['b']):.2f}x, z {f['z']:+.1f}, {f['maps']} maps); "
           f"raw {raw_c} vs {raw_b} ({legs}{'; all cut-offs, after-action included' if f.get('ra') or f.get('rab') else ''})")
    nb = NULL_RUN.get("bot")
    fn = fuel_paired(cand, nb) if nb else None
    if fn:
        val += f"; vs NULL cap{FUEL_CAP} {fn['c']} vs {fn['b']} (z {fn['z']:+.1f})"
    fx = float(os.environ.get("FUELX", "0") or 0)  # owner 6 Nov ("Fuel later"): marker FUELX=X: a capped ratio <= X passes as fuel debt
    if have_any and f["fail"] and fx > 1.0:
        ratio = f["c"] / max(1, f["b"])
        cum, how = fuel_cumulative(cand, ratio)  # Builder 6 Nov: per-ship 1.5x compounds; the chain v the anchor may not pass 2.0x
        if ratio <= fx and cum > FUELX_CUM:
            return ("fuel exhaustions", val + f"; cumulative v anchor {cum:.2f}x ({how})", bar + f"; FUELX {fx:g}, cumulative <= {FUELX_CUM:g}",
                    "FAIL")
        if ratio <= fx:
            try:
                with open(os.path.join(Q, "fuel_debt.txt"), "a") as fd:
                    fd.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} v {live}: cap{FUEL_CAP} {f['c']} v {f['b']} "
                             f"({ratio:.2f}x, FUELX {fx:g}); raw {raw_c} v {raw_b}; cumulative v anchor {cum:.2f}x ({how})\n")
            except OSError:
                pass
            return ("fuel exhaustions", val + f"; cumulative v anchor {cum:.2f}x", bar + f"; FUELX {fx:g}: cap ratio <= {fx:g} (fuel debt), "
                    f"cumulative <= {FUELX_CUM:g}", "PASS")
    return ("fuel exhaustions", val, bar, "INCONCLUSIVE" if not have_any else ("FAIL" if f["fail"] else "PASS"))


MAPLINE = re.compile(r"^\s+(?:ALL|confirm)\s+(\d+) maps: won both (\d+), split (\d+), lost both (\d+) \| score ([\d.]+) "
                     r"\[([\d.]+), ([\d.]+)\] LOS (\d+)%", re.M)


def map_read(txt):
    """condab's ALL / confirm line -> dict(n, w, d, l, score, lo, hi, los), or None."""
    m = MAPLINE.search(txt)
    if not m:
        return None
    n, w, d, l = (int(m.group(i)) for i in range(1, 5))
    return dict(n=n, w=w, d=d, l=l, score=float(m.group(5)), lo=float(m.group(6)), hi=float(m.group(7)),
                los=int(m.group(8)) / 100)


def fresh_decides(lane):
    """FRESH DECIDES (Builder 1 Nov, after bundle 23: a BIG-selected flip read 0.509 on BIG and 0.482 on unsaved maps): TRUNK-mode
    behaviour-lane bundles are decided by the per-run fresh leg (SC_FRESH_N maps, pooled >= SC_FRESH_MIN with CI upper >= 0.50);
    the live h2h (BIG) only needs LOS >= 90%, and the power extension is off."""
    return os.environ.get("SC_FRESH_DECIDES") == "1" and lane == "behaviour"


FRESH_N = int(os.environ.get("SC_FRESH_N", "600"))  # = 2 pooled per-run sets of 300
FRESH_N_DECIDES = int(os.environ.get("SC_FRESH_N_B", "3300" if os.environ.get("SC_FRESH_LED", "1") != "0" else "1200"))  # 11 Nov FRESH-LED: look 1 is 3,300 fresh maps, drawn at the first read so a pass is not one extension round slower  # 2 Nov (owner: "just do more testing"): where fresh decides, 4 sets; the panel stays on the first 600
FRESH_MIN = os.environ.get("SC_FRESH_MIN", "0.50")  # owner 7 Nov: every point bar >= .50; fresh_min() is .495 under BUGBAR


def lx_trigger(r, lane):
    """The power extension's trigger on the 636-map live h2h read (off when the fresh leg decides)."""
    if os.environ.get("SC_FRESH_DECIDES") == "1":
        return False
    return (lane not in ("fix", "fixmid") and r is not None and r["n"] >= LH_MIN and r["score"] >= 0.505 and r["los"] >= 0.85
            and r["lo"] < 0.5)


def big_plan(r1):
    """SC_LH_BIG extension plan on a triggering read r1: ('ext', maps) = rerun the h2h on the 636 pool + all BANK_MAX bank maps
    (the first LH_BIG come from the index); ('power', projected lower bound) = even then the observed point could not reach
    CI lower >= 0.5 at z LX_Z: a FAIL, not worth the games (30 Oct, CT_HARD 0.508 [0.499, 0.517] went INCONCLUSIVE twice)."""
    n_max = 636 + BANK_MAX
    if LH_BIG >= BANK_MAX:
        return "power", r1["lo"]
    sd = (r1["hi"] - r1["lo"]) / (2 * 1.96) * r1["n"] ** 0.5
    plo = r1["score"] - LX_Z * sd / n_max ** 0.5
    return ("ext", n_max) if plo >= 0.5 else ("power", plo)


def pooled(a, b, z=1.96):
    """abstat.summarize's map-pair score and normal CI on the summed won-both / split / lost-both counts of a and b."""
    n, w, d, l = (a[k] + b[k] for k in ("n", "w", "d", "l"))
    mean = (w + 0.5 * d) / n
    var = (w * (1 - mean) ** 2 + d * (0.5 - mean) ** 2 + l * mean ** 2) / (n - 1)
    se = (var / n) ** 0.5
    los = 0.5 * (1 + math.erf((w - l) / math.sqrt(2 * (w + l)))) if w + l else 0.5  # abstat's LOS
    return dict(n=n, score=mean, lo=max(0.0, mean - z * se), hi=min(1.0, mean + z * se), los=los)


def reuse_lx(name, cand, live, rtag):
    """SC_REUSE_LX=NAME: copy Q/NAME.condor.txt to lx{rtag}.condor.txt when it is a CONFIRM run of exactly CAND vs LIVE
    with their current source hashes and >= LX_MIN maps. -> None on success, else why not."""
    import abindex
    p = os.path.join(Q, f"{name}.condor.txt")
    txt = read(p)
    m = re.match(r"# condab \S+: (\S+?)@(\w+) vs (\S+?)@(\w+), CONFIRM", txt)
    if not m:
        return f"{p}: no CONFIRM summary"
    want = (cand, abindex.bot_hash(cand), live, abindex.bot_hash(live))
    if m.groups() != want:
        return f"{name} is {m.group(1)}@{m.group(2)} vs {m.group(3)}@{m.group(4)}, not {want[0]}@{want[1]} vs {want[2]}@{want[3]}"
    r = map_read(txt)
    if not r or r["n"] < LX_MIN:
        return f"{name} has {r['n'] if r else 0} maps (< {LX_MIN})"
    shutil.copyfile(p, os.path.join(Q, f"lx{rtag}.condor.txt"))
    return None


def lh_early(txt):
    """SC_LH_EARLY: the live h2h summary's early / timebox FAIL decision (condab's STOP=1 rules incl. CONDAB_HI_FAIL) ->
    'why' or None."""
    if not LH_EARLY:
        return None
    m = re.search(r"^(stopped early at \d+% of jobs \(decided FAIL\)|timebox at .*: decided FAIL)$", txt, re.M)
    if not m:
        return None
    how = re.findall(r"DECIDED FAIL \(([^)]*)\)", txt)
    return m.group(1) + (f"; {how[-1]}" if how else "")


_CHANGED = {}


NULLSW = os.environ.get("NULLSW", "").strip()  # SHIPCHECK key NULLSW=NAME (31 Oct): fix-lane change size vs a switch-off copy
NULL_WAIT = int(os.environ.get("SC_NULL_WAIT", 600))  # s the change-size read waits for the CAND vs NULL leg
NULL_RUN = {}  # {"name": nl run name, "bot": null copy, "lc": cached (changed, maps, source)}


def make_null(cand, rtag):
    """NULLSW=NAME (31 Oct, Builder; cambc-34's null test b542v2: the SAME source with its switch off differed from live v351
    in 24/32 games through recompilation alone (ward/cast fuel timing), switch on vs off in 9/32; so "% maps changed vs live"
    mostly measured recompilation, and fixes 530f, 534, 553, 536r fell to the behaviour bar on it). A copy of CAND (newbot.sh)
    whose one `#define NAME <v>` line reads 0: the fix-lane change size is then CAND vs NULL, the switch's own effect.
    -> (null bot name or None, note). Reused when bots/NAME exists for the same CAND source and switch (.nullof)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", NULLSW):
        return None, f"NULLSW {NULLSW!r} is not a C identifier"
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    nb = "nova_null_" + re.sub(r"[^A-Za-z0-9_]", "", rtag)
    d = os.path.join(REPO, "bots", nb)
    mark = f"{cand} {abindex.bot_hash(cand)} {NULLSW}\n"
    if os.path.exists(d):
        try:
            if open(os.path.join(d, ".nullof")).read() == mark:
                return nb, f"bots/{nb} reused (same CAND source, {NULLSW} = 0)"
        except OSError:
            pass
        return None, f"bots/{nb} exists and is not this CAND's null copy: change size stays vs live"
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/newbot.sh"), cand, nb], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isdir(os.path.join(d, "src")):
        return None, f"newbot.sh failed: {(r.stdout + r.stderr).strip()[-160:]}"
    real = os.path.realpath(d)
    if subprocess.run(["find", real, "-type", "l"], capture_output=True, text=True).stdout.strip():
        return None, f"bots/{nb} holds symlinks: not patched"
    pat = re.compile(rf"^([ \t]*#[ \t]*define[ \t]+{NULLSW}[ \t]+)(\S+)(.*)$", re.M)
    hits = []
    for f in sorted(glob.glob(os.path.join(real, "src", "*.h")) + glob.glob(os.path.join(real, "src", "*.hpp"))
                    + glob.glob(os.path.join(real, "src", "*.cpp")) + glob.glob(os.path.join(real, "src", "*.cc"))):
        hits += [(f, m) for m in pat.finditer(open(f, errors="replace").read())]
    if len(hits) != 1 or hits[0][1].group(2) == "0":
        why = (f"#define {NULLSW} occurs {len(hits)} times" if len(hits) != 1 else f"{NULLSW} is already 0 in {cand}")
        shutil.rmtree(real, ignore_errors=True)  # our own copy, made a moment ago
        os.remove(d)
        return None, why + ": change size stays vs live"
    f, m = hits[0]
    txt = open(f).read()
    open(f, "w").write(txt[:m.start()] + m.group(1) + "0" + m.group(3) + txt[m.end():])
    open(os.path.join(real, ".nullof"), "w").write(mark)
    return nb, f"bots/{nb}: {os.path.basename(f)} #define {NULLSW} {m.group(2)} -> 0"


def null_changed():
    """(changed, maps, source) from the CAND vs NULL leg's summary, waiting up to NULL_WAIT once; None without it."""
    if not NULL_RUN.get("name"):
        return None
    if NULL_RUN.get("lc") is not None or NULL_RUN.get("gave_up"):
        return NULL_RUN.get("lc")
    t0 = time.time()
    while True:
        m = re.search(r"^\s+changed\s+(\d+) of (\d+) maps", read(os.path.join(Q, f"{NULL_RUN['name']}.condor.txt")), re.M)
        if m and int(m.group(2)) > 0:
            NULL_RUN["lc"] = (int(m.group(1)), int(m.group(2)), f"vs NULL {NULL_RUN['bot']} ({NULLSW}=0)")
            return NULL_RUN["lc"]
        if time.time() - t0 > NULL_WAIT:
            NULL_RUN["gave_up"] = True
            say(f"!! the CAND vs NULL leg {NULL_RUN['name']} gave no maps-changed count within {NULL_WAIT} s: change size vs live")
            return None
        time.sleep(15)


def lh_changed(lh, cand, live):
    """Maps changed in the live h2h (the two seats' games differ, CONFIRM's definition) -> (changed, maps, source) or None.
    condab's set summary prints it ("changed X of Y maps", since 30 Oct); older summaries: counted from the index."""
    m = re.search(r"^\s+changed\s+(\d+) of (\d+) maps", lh, re.M)
    if m:
        return int(m.group(1)), int(m.group(2)), "summary"
    if not map_read(lh):
        return None
    if (cand, live) not in _CHANGED:
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import abindex
        import condab
        hc, hl = abindex.bot_hash(cand), abindex.bot_hash(live)
        ix, mp = abindex.Index({hc, hl}), abindex.maps()
        ch = n = 0
        for mname in condab.set_maps("all"):
            if mname not in mp:
                continue
            g1, g2 = ix.games.get((hc, hl, mp[mname][0])), ix.games.get((hl, hc, mp[mname][0]))
            if g1 and g2:
                n += 1
                ch += (g1["win"], g1.get("rounds"), g1["sa"], g1["sb"]) != (g2["win"], g2.get("rounds"), g2["sa"], g2["sb"])
        _CHANGED[(cand, live)] = (ch, n, "index")
    return _CHANGED[(cand, live)]


FIX_FRESH = os.environ.get("SC_FIX_FRESH", "1") == "1"
BUGBAR_PT = 0.50  # 9 Nov ~17:55Z, owner (asked directly): "Make sure the h2h >= 0.5" -> "Yes, .50 for all": bug-bar lines need point >= .50 too (was .495)
BUGBAR_LO = 0.4975  # 9 Nov ~22:40Z, owner (asked directly: 'CI lower >= .4975'): a bug-bar line's deciding read also needs CI lower >= this (95% sure the
# fix costs at most a quarter point; asked because near-.50 passes could be luck)
# 11 Nov ~23:3xZ, owner (asked directly): "Reduce the bug bar head to head so that the bug fixes succeed, but only if slightly below 0.5
# to the point it could just be variance": a bug-bar line's live h2h row passes at point >= BUGBAR_H2H_PT with CI upper >= .50 (not
# significantly below .50), with no CI-lower harm bound. SC_BUGBAR_H2H_VAR=0 restores the old row (point .50 / CI lower .4975).
BUGBAR_H2H_VAR = os.environ.get("SC_BUGBAR_H2H_VAR", "1") == "1"
BUGBAR_H2H_PT = float(os.environ.get("SC_BUGBAR_H2H_PT", "0.50"))  # owner 12 Nov ~12:3xZ: "Combat fixes could also be odd, make bug bar above 0.5": .4975 -> .50  # owner 12 Nov (directly): "be careful of bug fixes that seem negative increase the bug bar threshold slightly": .495 -> .4975
TRUNK_PT = 0.495  # the trunk-code row (flag-0 shared code v live) keeps its own .495 no-harm bar (CLAUDE.md section 5 'Trunk code')
_BUGBAR_PT_OLD = 0.495  # marker BUGBAR=1, LANE=fix, set only by the Builder for verified bug fixes or play-identical changes (2 Nov; owner 7 Nov: every band): live h2h point >= this, not FIX_BIG_LH, and the > 50% band's fresh floor. Every other row stays.
FIX_FRESH_HIT = []  # set when a fix check (TRUNK or direct) changed > 50% of maps and the fresh leg decides (eff_lane)
FIX_MID_HIT = []  # holds the share while the latest eff_lane read is at <= 50% changed; the fresh leg does not decide there


def bugbar_on():
    return os.environ.get("BUGBAR") == "1" and bool(FIX_FRESH_HIT or FIX_MID_HIT)


def fix_pt():
    """The fix lane's live h2h point bar, every change-size band."""
    return BUGBAR_PT if bugbar_on() else FIX_BIG_LH


# 12 Nov ~02:3xZ, owner (relayed by the Coordinator, his words "Q2 make it .4975"): a verified bug fix's (--bugbar) FRESH row passes at
# point >= .4975 with CI upper >= .50; every other bug-bar row unchanged. SC_BUGBAR_FRESH_PT=0.50 restores.
BUGBAR_FRESH_PT = float(os.environ.get("SC_BUGBAR_FRESH_PT", "0.5001"))  # owner 12 Nov ~12:3xZ: bug bar ABOVE .50 (strictly: point > .50)  # owner 12 Nov (directly, ~12:2xZ): bug bar raised slightly, .4975 -> .50 (fresh decides and the bug-bar confirm)


def fix_lean():
    """12 Nov owner: fix checks play BIG2-only h2h and no panel while ideas are waiting; strict (full pool + panel) when the armq queue is
    empty ("if you run out of ideas revert to being more strict"). bq/fix_strict forces strict, SC_FIX_LEAN=0/1 overrides."""
    ov = os.environ.get("SC_FIX_LEAN", "")
    if ov in ("0", "1"):
        return ov == "1"
    if os.path.exists(os.path.join(Q, "fix_strict")):
        return False
    try:
        r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "armq.py"), "list"],
                           capture_output=True, text=True, timeout=120)
        # 12 Nov (Coordinator, default agreed with the Builder): SPSA / parameter lines (--parambar) are not ideas for this switch
        if sum(1 for ln in r.stdout.splitlines() if ln.startswith("{") and '"parambar": true' not in ln) > 0:
            return True
        # 12 Nov ~05:4xZ (4 of 8 fix checks ran STRICT, ~16k-game h2h, while 6 armed lines sat in shipwatch's start queue: armq is empty once a
        # line is armed): armed markers not yet started (bots/nova_b*/SHIPCHECK with no shipwatch_*_TAG.out) are waiting ideas too
        # waiting = a marker shipwatch has not handled yet (its state has no entry with this marker's hash; skipped / started ones do)
        import hashlib
        try:
            stw = json.load(open(os.path.join(Q, "shipwatch_state.json")))
        except (OSError, ValueError):
            stw = {}
        for mk in glob.glob(os.path.join(REPO, "bots", "nova_b*", "SHIPCHECK")):
            try:
                raw = open(mk, "rb").read()
            except OSError:
                continue
            nm = os.path.basename(os.path.dirname(mk))
            if b"PARAMBAR=1" in raw or stw.get(nm, {}).get("marker") == hashlib.sha1(raw).hexdigest()[:12]:
                continue
            return True
        return False
    except Exception:  # noqa: BLE001
        return False  # unknown queue: strict


Q1BAR_FRESH_PT = float(os.environ.get("SC_Q1BAR_FRESH_PT", "0.495"))  # owner Q1 (12 Nov): play-identical fuel cuts with a REAL fuel effect


def fresh_min():
    """The fresh floor where the fresh leg decides a fix check. Q1BAR=1 (owner 12 Nov, Q1 "depends on the effect on fuel"; the Builder
    marks only cuts whose capped cut-offs fall, z <= -2 on a burning family): no-harm, point >= .495 with CI upper >= .50."""
    if os.environ.get("Q1BAR") == "1":
        return f"{Q1BAR_FRESH_PT:g}"
    if os.environ.get("BUGBAR") == "1":
        return f"{BUGBAR_FRESH_PT:g}"
    return f"{BUGBAR_PT:g}" if bugbar_on() else FRESH_MIN


def eff_lane(lh, lane, cand, live):
    """SC_FIX_NONC's change-size bands (docstring 1b.) -> (the lane whose live h2h bar applies, (changed, maps, source) or
    None): <= 15% of maps changed "fix", 15-50% "fixmid" (point >= FIX_BIG_LH), > 50% "behaviour" (CI lower >= 0.5 with
    the power extension). Rollbacks (MECH "rollback ...") stay "fix"; other lanes are returned unchanged."""
    FIX_MID_HIT.clear()
    if not nonc(lane):
        return lane, None
    lc = null_changed() or lh_changed(lh, cand, live)  # NULLSW: the switch's own change size, else vs live
    if lane == "draft":  # no change-size bands: BIG no-harm, the changed-map read decides
        return "draft", lc
    if os.environ.get("MECH", "").strip().lower().startswith("rollback") or not lc or lc[1] == 0:
        return "fix", lc
    sh = lc[0] / lc[1]
    if sh > 0.50 and FIX_FRESH and PANEL:  # 4 Nov (Failure management): direct fix arms too; TRUNK-only judged BUGBAR bakes 1180/1348 on CI lower >= 0.5
        # 1 Nov ~20:20 (Builder: fuel reshuffle drives most changes of a data flip; bundles 27/30 were hand-submitted on this
        # rule): a TRUNK-mode fix check with > 50% changed gets the 15-50% live h2h bar (point >= FIX_BIG_LH) and the fresh leg
        # (FRESH_N unsaved maps or an adopted gate.py read) must pass FRESH DECIDES' bar (pooled >= FRESH_MIN, CI upper >= 0.5,
        # no kind z <= -2.5) -- as TRUNK-mode behaviour checks already are. SC_FIX_FRESH=0: the old behaviour bar.
        if not FIX_FRESH_HIT:
            FIX_FRESH_HIT.append(sh)
        return "fixmid", lc
    if sh <= 0.50:
        FIX_MID_HIT.append(sh)
    return ("behaviour" if sh > 0.50 else "fixmid" if sh > 0.15 else "fix"), lc


def lh_row(lh, lane, cand, live):
    """The live h2h row -> (value, bar, verdict, 636-map read or None, ext). verdict EXT: the extension row decides."""
    lm = re.search(r"^\s+ALL\s+(\d+) maps: .*?score ([\d.]+) \[([\d.]+), ([\d.]+)\]", lh, re.M)
    eb = early_bar(lane)
    lane = eff_lane(lh, lane, cand, live)[0] if lm and not lh_early(lh) else lane
    fband = "> 50%" if FIX_FRESH_HIT else "15-50%" if lane == "fixmid" else "<= 15%"
    lbar = ((f"BUG BAR point >= {BUGBAR_H2H_PT:g}, CI upper >= 0.5 (within variance of .50, owner 11 Nov) ({fband} changed)" if bugbar_on() and BUGBAR_H2H_VAR else
             f"{'BUG BAR ' if bugbar_on() else ''}point >= {fix_pt():g}, CI upper >= 0.5{f', CI lower >= {BUGBAR_LO:g}' if bugbar_on() else ''} ({fband} changed)") if lane in ("fix", "fixmid")
            else (f"point >= {DRAFT_BIG_NH_PT:g}, CI upper >= 0.5 (draft lane: BIG no-harm, owner 12 Nov)" if DRAFT_BIG_NH else f"point >= {DRAFT_BIG} (draft lane: BIG no-harm)")
            if lane == "draft" else "pooled row decides" if lane == "param" else "CI lower >= 0.5")
    if LH_EARLY:
        lbar += f"; early: CI(z {LH_EARLY_Z:g}) upper >= {eb:.3g}"
    if not lm:
        return "no result", lbar, "INCONCLUSIVE", None, False
    n, s, lo, hi = int(lm.group(1)), float(lm.group(2)), float(lm.group(3)), float(lm.group(4))
    mr = map_read(lh)
    if mr and mr["n"]:  # owner 7 Nov via the Builder: the bar reads the unrounded point; condab's line rounds to 3 dp, so a .4998 passed as .500
        s = (mr["w"] + 0.5 * mr["d"]) / mr["n"]
    tb = re.search(r"^(timebox at .*)$", lh, re.M)
    early = lh_early(lh)
    if early:
        v = "FAIL"
    elif n < LH_MIN:
        v = "INCONCLUSIVE"
    elif lane == "draft":
        v = ("PASS" if s >= DRAFT_BIG_NH_PT and hi >= 0.5 else "FAIL") if DRAFT_BIG_NH else ("PASS" if s >= DRAFT_BIG else "FAIL")
    elif lane in ("fix", "fixmid") and fix_fresh_led():  # owner 11 Nov (asked directly): fix lane fresh-led; BIG is no-harm and keeps the bug bar's harm bound
        bbv = os.environ.get("BUGBAR") == "1" and BUGBAR_H2H_VAR
        # 12 Nov ~18:0xZ (TB: ntg1rs PASSED its bug bar with BIG .4967): the owner's 12 Nov bug bar is BIG point >= .50 (SC_BUGBAR_H2H_PT), CI
        # upper >= .50; this fresh-led branch still used the plain fix lane's no-harm .495 for bug-bar lines
        bpt = BUGBAR_H2H_PT if os.environ.get("BUGBAR") == "1" else BIG_NH_PT
        lbar = f"BIG {'BUG BAR' if os.environ.get('BUGBAR') == '1' else 'no-harm'}: point >= {bpt:g}, CI upper >= 0.5" + ((" (owner 12 Nov bug bar)" if bbv else f", CI lower >= {BUGBAR_LO:g} (bug bar harm bound)") if os.environ.get("BUGBAR") == "1" else "") + " (FRESH-LED fix)"
        v = "PASS" if s >= bpt and hi >= 0.5 and (os.environ.get("BUGBAR") != "1" or bbv or lo >= BUGBAR_LO) else "FAIL"
    elif lane in ("fix", "fixmid"):
        if bugbar_on() and BUGBAR_H2H_VAR:  # owner 11 Nov: a bug fix's h2h within variance of .50 passes
            v = "PASS" if s >= BUGBAR_H2H_PT and hi >= 0.5 else "FAIL"
        else:
            v = "PASS" if s >= fix_pt() and hi >= 0.5 and (not bugbar_on() or lo >= BUGBAR_LO) else "FAIL"
    else:
        v = "PASS" if lo >= 0.5 else "FAIL"
    fu = re.search(rf"^\s+{re.escape(cand)}\s+faults \d+ .*?fuel exhaustions (\d+)", lh, re.M)
    fl_ = re.search(rf"^\s+{re.escape(live)}\s+faults \d+ .*?fuel exhaustions (\d+)", lh, re.M)
    r1 = map_read(lh)
    if fresh_decides(lane) and not early and n >= LH_MIN:  # owner 3 Nov (b935): BIG is a true no-harm row; the pooled row decides
        lbar = f"BIG point >= {POOL_NOHARM} (no-harm; POOLED DECIDES)"
        v = "PASS" if s >= POOL_NOHARM else "FAIL"
        if FRESH_LED:  # owner 11 Nov: fresh decides; BIG not significantly negative
            lbar = f"BIG point >= {BIG_NH_PT} and CI upper >= .50 (no-harm; FRESH-LED)"
            v = "PASS" if s >= BIG_NH_PT and hi >= 0.5 else "FAIL"
    ext = not early and (lx_trigger(r1, lane) or (lane == "param" and r1 is not None))
    val = (f"{s:.4f} [{lo:.3f}, {hi:.3f}] n {n}/{636 + LH_BIG}" + (f" LOS {r1['los'] * 100:.0f}%" if r1 else "")
           + (f", fuel {fu.group(1)}-{fl_.group(1)}" if fu and fl_ else "")
           + (f" (EARLY FAIL: {early[:90]})" if early else f" ({tb.group(1)[:30]})" if tb else ""))
    return val, lbar, ("EXT" if ext else v), r1, ext


def panel_games(tag, cand, live):
    """(CAND faults, CAND raw fuel, LIVE raw fuel, games) of the fresh leg."""
    r = panel_recs(tag, cand, live)
    return sum(int(c.get("faults", 0)) for _, c, _ in r), sum(int(c.get("fuel", 0)) for _, c, _ in r), sum(int(b.get("fuel", 0)) for _, _, b in r), len(r)


def table(cand, live, tag, lane, ub_rc, ub_txt, ub_wait=None, trig=None):
    nd, cf = read(os.path.join(Q, f"nd{tag}.condor.txt")), read(os.path.join(Q, f"cf{tag}.condor.txt"))
    smk = read(f"/data/USER/abl/smk_{tag}/summary.txt")
    rows = []
    # nochase2 paired D
    m = re.search(r"^\s+ALL\s+n\s+(\d+)\s+D ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\]", nd, re.M)
    stopd = re.search(r"^(stopped early at .*|timebox at .*)$", nd, re.M)
    if not HAVE_ND:
        pass
    elif not m:
        rows.append(("nochase2 paired D", "no result", ">= 0", "INCONCLUSIVE"))
    else:
        n, d, lo, hi = int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        st = stopd.group(1) if stopd else "full subset"
        ex = re.search(r"^timebox extended by (\d+) min", nd, re.M)
        if ex:
            st = f"timebox +{ex.group(1)} min; " + st
        if "INCONCLUSIVE" in st:
            v = "INCONCLUSIVE"
        elif "decided FAIL" in st:
            v = "FAIL"
        elif lane == "fix" or LIVEH2H:  # with the live h2h deciding, nochase2 only has to be not significantly < 0
            v = "PASS" if hi >= 0 else "FAIL"
        elif "decided PASS" in st:
            v = "PASS"
        else:
            v = "PASS" if d >= 0 else "FAIL"
        if n < 100 and "decided" not in st:
            v = "INCONCLUSIVE"  # the reference covers too few of the subset's maps (BASE_ND); not when the leg's own sequential rule
            # stopped it with a decision (3 Nov: 1256 decided PASS at 80% of jobs, n 86 of a 105-map subset, and was voided as 'capacity')
        mc = re.search(r"^\s+ALL\s+n\s+\d+\s+D .*?maps changed (\d+)", nd, re.M)
        if v == "PASS" and mc and int(mc.group(1)) == 0 and not trig and lane != "fix":
            v, st = "VACUOUS", "VACUOUS (no change anywhere); " + st  # zero evidence: never a ship (LANE=fix: identity is the goal)
        rows.append(("nochase2 paired D", f"{d:+.3f} [{lo:+.3f}, {hi:+.3f}] n {n} ({st[:60]})",
                     "CI upper >= 0" if lane == "fix" or LIVEH2H else ">= 0", v))
    # CONFIRM
    m = re.search(r"^\s+confirm\s+(\d+) maps: .*?score ([\d.]+) \[([\d.]+), ([\d.]+)\]", cf, re.M)
    if not m:
        rows.append(("CONFIRM", "no result", "> 0.5", "INCONCLUSIVE"))
    else:
        n, s, lo, hi = int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        ch = re.search(r"^\s+changed\s+(\d+) of (\d+) maps", cf, re.M)
        chs = f", maps changed {ch.group(1)}" if ch else ""
        if "timebox" in cf and n < 60:
            v = "INCONCLUSIVE"
        elif ch and int(ch.group(1)) == 0:
            v, chs = "PASS", f"; neutral: no change on {ch.group(2)} maps, the trigger leg decides"
        elif lane == "fix" or LIVEH2H:
            v = "PASS" if hi >= 0.5 else "FAIL"
        elif rows and rows[0][0] == "nochase2 paired D" and rows[0][3] == "PASS":
            # CONFIRM is self-play vs live: once nochase2 passed, ask only "not significantly worse" (owner-authorised, 29 Oct;
            # b206: nc +0.010 decided PASS, CONFIRM 0.485 [0.468, 0.502] on 16 changed maps)
            v, chs = ("PASS" if hi >= 0.5 else "FAIL"), chs + "; non-inferior (nc decided PASS)"
        else:
            v = "PASS" if s > 0.5 else "FAIL"
        bar = "CI upper >= 0.5" if lane == "fix" or LIVEH2H or "non-inferior" in chs else "> 0.5"
        rows.append(("CONFIRM", f"{s:.3f} [{lo:.3f}, {hi:.3f}] n {n}{chs}", bar, v))
    # cumulative anchor: CAND vs ANCHOR h2h on the same subset, both lanes; rollbacks see it but are not blocked
    an_bot = os.environ.get("SC_ANCHOR")
    if an_bot:
        an = read(os.path.join(Q, f"an{os.environ.get('SC_ANTAG', tag)}.condor.txt"))
        am = re.search(r"^\s+ALL\s+(\d+) maps: .*?score ([\d.]+) \[([\d.]+), ([\d.]+)\]", an, re.M)
        rb = os.environ.get("MECH", "").strip().lower().startswith("rollback")
        if os.environ.get("SC_ANCHOR_SAME") == "1":
            rows.append((f"anchor h2h", f"n/a: the candidate is the anchor {an_bot}'s source", "CI upper >= 0.5", "PASS"))
        elif not am:
            rows.append((f"anchor h2h", f"no result (vs {an_bot})", "CI upper >= 0.5", "PASS" if rb else "INCONCLUSIVE"))
        else:
            n, sc_, lo, hi = int(am.group(1)), float(am.group(2)), float(am.group(3)), float(am.group(4))
            v = "PASS" if hi >= 0.5 or rb else "FAIL"
            rows.append((f"anchor h2h", f"vs {an_bot}: {sc_:.3f} [{lo:.3f}, {hi:.3f}] n {n}"
                         + ("; rollback: shown, not blocking" if rb and hi < 0.5 else ""), "CI upper >= 0.5", v))
    # fix lane, big change: the nc point estimate too (29 Oct: v292 shipped on LANE=fix with nc D -0.040 and 87/100 CONFIRM
    # maps changed). Rollbacks (MECH "rollback ...") are exempt: they undo a change by design.
    lh = read(os.path.join(Q, f"lh{tag}.condor.txt")) if LIVEH2H else ""
    lx = read(os.path.join(Q, f"lx{tag}.condor.txt")) if LIVEH2H else ""
    # fuel / fault counts: a BIG extension already holds the live h2h's games. Not the param lane: its extension is the
    # PM_LX_N fresh CONFIRM maps, other games than the live h2h (31 Oct, b438 agent: 438x dropped the h2h's fuel)
    lhc = "" if LH_BIG and lane != "param" and map_read(lx) else lh
    if nonc(lane):  # SC_FIX_NONC: the change size from the live h2h's maps picks its bar (docstring 1b.)
        if map_read(lh) and not lh_early(lh):
            el, lc = eff_lane(lh, lane, cand, live)
            if lc is None:
                rows.append(("fix-lane change size", "no live h2h maps-changed count", "band", "INCONCLUSIVE"))
            else:
                pb = f"lh point >= {fix_pt():g}{' (bug bar)' if bugbar_on() else ''}"
                band = {"fix": f"<= 15%: {pb}", "fixmid": f"15-50%: {pb}",
                        "behaviour": "> 50%: behaviour bar (lh CI lower >= 0.5 / ext)",
                        "draft": (f"draft lane: BIG no-harm (point >= {DRAFT_BIG_NH_PT:g}, CI upper >= .50); the changed-map read decides" if DRAFT_BIG_NH else f"draft lane: BIG point >= {DRAFT_BIG}; the changed-map read decides")}[el]
                if FIX_FRESH_HIT:
                    band = f"> 50%: {pb} + fresh >= {fresh_min()}"
                rb = os.environ.get("MECH", "").strip().lower().startswith("rollback")
                src = lc[2] if lc[2].startswith("vs NULL") else f"live h2h, {lc[2]}"
                rows.append(("fix-lane change size", f"{100 * lc[0] / max(1, lc[1]):.0f}% of {lc[1]} maps changed ({src}) -> "
                             f"{'rollback: fix bar' if rb else band}", "bar in the lh row", "PASS"))
    elif lane == "fix":
        chm = re.search(r"^\s+changed\s+(\d+) of (\d+) maps", cf, re.M)
        dm = re.search(r"^\s+ALL\s+n\s+\d+\s+D ([+-][\d.]+)", nd, re.M)
        if chm and int(chm.group(2)) > 0 and int(chm.group(1)) > 0.15 * int(chm.group(2)):
            share = 100 * int(chm.group(1)) / int(chm.group(2))
            if os.environ.get("MECH", "").strip().lower().startswith("rollback"):
                rows.append(("fix-lane change size", f"{share:.0f}% maps changed: exempt (rollback)", "nc D point >= 0", "PASS"))
            elif dm:
                dp = float(dm.group(1))
                rows.append(("fix-lane change size", f"{share:.0f}% maps changed -> nc D point >= 0 required: {dp:+.3f}",
                             "nc D point >= 0", "PASS" if dp >= 0 else "FAIL"))
            else:
                rows.append(("fix-lane change size", f"{share:.0f}% maps changed; no nc D", "nc D point >= 0", "INCONCLUSIVE"))
    # UB
    k = re.search(r"NEW UB SITES: (\d+)", ub_txt)
    if ub_txt.startswith("ubaudit skipped:"):
        rows.append(("ubaudit", ub_txt[17:75], "0 new, pass", "PASS"))
    else:
        rows.append(("ubaudit", f"new sites {k.group(1) if k else '?'} (exit {ub_rc}"
                     + (f"; waited {ub_wait / 60:.1f} min past the timebox" if ub_wait is not None else "") + ")",
                     "0 new, pass", "PASS" if ub_rc == 0 else ("FAIL" if ub_rc == 1 else "INCONCLUSIVE")))
    # faults and fuel
    fl = collections.Counter()

    def side(txt, bot, key):
        mm = re.search(rf"^\s+{re.escape(bot)}\s+faults (\d+) .*?fuel exhaustions (\d+)", txt, re.M)
        if mm:
            fl[(key, bot, "faults")] += int(mm.group(1))
            fl[(key, bot, "fuel")] += int(mm.group(2))
            return True
        return False
    have = [side(nd, cand, "nd"), side(cf, cand, "cf"), side(cf, live, "cf"), side(lhc, cand, "lh") or bool(lhc != lh and map_read(lh)), side(lx, cand, "lx")]
    sm = re.search(r"fuel exhaustions (\d+)-(\d+) \(total\)\s+bot faults (\d+)-(\d+)", smk)
    if sm:
        fl[("smk", cand, "fuel")], fl[("smk", live, "fuel")] = int(sm.group(1)), int(sm.group(2))
        fl[("smk", cand, "faults")] = int(sm.group(3))
    faults = sum(v for (k_, b, w), v in fl.items() if b == cand and w == "faults")
    rows.append(("bot faults (CAND)", f"{faults} (smoke {'yes' if sm else 'off'}, nd {'yes' if have[0] else 'missing'}, "
                 f"cf {'yes' if have[1] else 'missing'}"
                 + (f", lh {'yes' if have[3] else 'missing'}" if LIVEH2H else "") + ")", "0",
                 "INCONCLUSIVE" if not (sm or any(have)) else ("PASS" if faults == 0 else "FAIL")))
    fc = fl[("cf", cand, "fuel")] + fl[("smk", cand, "fuel")]
    fb = fl[("cf", live, "fuel")] + fl[("smk", live, "fuel")]
    rows.append(fuel_row(cand, live, fc, fb, "CONFIRM + smoke", bool(sm or have[1])))  # FUEL rule (1 Nov): capped, map-paired
    if trig and trig.get("h2h"):  # SC_FIX_NONC + TRIGGER: CAND vs LIVE on exactly the trigger maps (docstring 1b.)
        th = read(os.path.join(Q, f"th{tag}.condor.txt"))
        r_, ch_ = map_read(th), re.search(r"^\s+changed\s+(\d+) of (\d+) maps", th, re.M)
        if not r_:
            rows.insert(1, ("trigger h2h", "no result", "CI upper >= 0.5, changed > 0", "INCONCLUSIVE"))
        else:
            tv = ("VACUOUS" if ch_ and int(ch_.group(1)) == 0 else "INCONCLUSIVE" if r_["n"] < 10 else
                  "PASS" if r_["hi"] >= 0.5 else "FAIL")
            rows.insert(1, ("trigger h2h", f"{'VACUOUS: ' if tv == 'VACUOUS' else ''}{r_['score']:.3f} [{r_['lo']:.3f}, "
                            f"{r_['hi']:.3f}] n {r_['n']}/{len(trig['maps'])}, maps changed "
                            f"{ch_.group(1) if ch_ else '?'}", "CI upper >= 0.5, changed > 0", tv))
    if trig and "res" in trig:  # targeted change: its own row on exactly the trigger maps (b204 passed with none in its random subset)
        tn, td, tlo, thi, tch = trig["res"]
        if tn < 10:
            tv, tval = "INCONCLUSIVE", (f"too few trigger maps paired (n {tn} of {len(trig['maps'])})" if have[0] else
                                        f"not read: CAND's nochase2 leg did not run (n {tn} of {len(trig['maps'])}; "
                                        f"it needs CAND vs nochase2 on the trigger maps)")
        elif tch == 0:
            tv, tval = "VACUOUS", f"VACUOUS: 0 of {tn} trigger maps changed"
        else:
            tv = ("PASS" if thi >= 0 else "FAIL") if lane == "fix" else ("PASS" if td >= 0 else "FAIL")
            tval = f"{td:+.3f} [{tlo:+.3f}, {thi:+.3f}] n {tn}, maps changed {tch}"
        rows.insert(1, ("trigger D", tval, "CI upper >= 0" if lane == "fix" else ">= 0, n >= 10", tv))
    if LIVEH2H:  # the decisive leg, first row
        val, lbar, v1, r1, ext = lh_row(lh, lane, cand, live)
        rows.insert(0, ("live h2h", val, lbar, v1))
        if r1 is not None:
            if ext:  # the power extension decides (docstring 1.)
                r2 = map_read(lx)
                # BIG extension: the same h2h on the pool + the whole bank, judged alone (it holds the first read's maps).
                # Never the param lane (31 Oct, 438x): lx_watch does not run there, its extension is PM_LX_N fresh maps,
                # pooled with the live h2h below (the BIG read judged alone sat at n 650 < 79% of 4546: INCONCLUSIVE)
                if LH_BIG and lane != "param":
                    plan = big_plan(r1)
                    xbar = f"CI lower >= 0.5 (z {LX_Z:g}), pool + {BANK_MAX} bank"
                    why = re.search(r"^lx: (.*)$", read(os.path.join(Q, f"lx{tag}.note")), re.M)
                    if plan[0] == "power":
                        rows.insert(1, ("live h2h+ext", f"not run: at {636 + BANK_MAX} maps the projected CI lower is {plan[1]:.3f}"
                                        " < 0.5 (power: more maps cannot pass it)", xbar, "FAIL"))
                    elif not r2:
                        rows.insert(1, ("live h2h+ext", "no result" + (f" ({why.group(1)[:44]})" if why else ""), xbar,
                                        "INCONCLUSIVE"))
                    else:
                        pp = pooled(r2, dict(n=0, w=0, d=0, l=0), LX_Z)
                        xv = "INCONCLUSIVE" if r2["n"] < 0.79 * (636 + BANK_MAX) else ("PASS" if pp["lo"] >= 0.5 else "FAIL")
                        rows.insert(1, ("live h2h+ext", f"{pp['score']:.3f} [{pp['lo']:.3f}, {pp['hi']:.3f}] n {pp['n']} (pool + whole bank)",
                                        xbar, xv))
                else:
                    xbar = (f"n>={PM_N} pt>={PM_POINT:g} LOS>={PM_LOS * 100:.0f}%" if lane == "param"
                            else f"pooled CI lower >= 0.5 (z {LX_Z:g})")
                    nx = PM_LX_N if lane == "param" else LX_N
                    why = re.search(r"^lx: (.*)$", read(os.path.join(Q, f"lx{tag}.note")), re.M)
                    if not r2:
                        rows.insert(1, ("live h2h+ext", "no result" + (f" ({why.group(1)[:44]})" if why else ""), xbar,
                                        "INCONCLUSIVE"))
                    else:
                        pp = pooled(r1, r2, LX_Z)
                        if lane == "param":
                            xv = ("INCONCLUSIVE" if pp["n"] < PM_N else
                                  "PASS" if pp["score"] >= PM_POINT and pp["los"] >= PM_LOS else "FAIL")
                        else:
                            xv = "INCONCLUSIVE" if r2["n"] < LX_MIN else ("PASS" if pp["lo"] >= 0.5 else "FAIL")
                        rows.insert(1, ("live h2h+ext", f"{pp['score']:.3f} [{pp['lo']:.3f}, {pp['hi']:.3f}] n {pp['n']} "
                                        + (f"LOS {pp['los'] * 100:.0f}% " if lane == "param" else "")
                                        + f"(ext {r2['score']:.3f} n {r2['n']}/{nx})", xbar, xv))
    if RARE:  # no live h2h: faults and the raw fuel count come from the read's own games
        pf, pc, pb_, pn = panel_games(tag, cand, live)
        rows = [r for r in rows if r[0] not in ("nochase2 paired D", "CONFIRM", "fuel exhaustions", "trigger D", "bot faults (CAND)")]
        rows.append(("bot faults (CAND)", f"{pf} ({pn} games of the changed-map read)", "0", "INCONCLUSIVE" if not pn else "FAIL" if pf else "PASS"))
        rows.append(fuel_row(cand, live, pc, pb_, "changed-map read", bool(pn)))
    elif lane == "param" or nonc(lane):  # only the live h2h (+ ext) and the anchor ran: drop the other legs' rows, fuel from lh + lx
        rows = [r if r[0] != "bot faults (CAND)" else
                (r[0], f"{faults} (live h2h {'yes' if have[3] else 'missing'}, ext {'yes' if have[4] else 'missing'})", r[2],
                 "INCONCLUSIVE" if not (have[3] or have[4]) else r[3])
                for r in rows if r[0] not in ("nochase2 paired D", "CONFIRM", "fuel exhaustions", "trigger D")]
        side(lhc, live, "lh")
        side(lx, live, "lx")
        fc = fl[("lh", cand, "fuel")] + fl[("lx", cand, "fuel")]
        fb = fl[("lh", live, "fuel")] + fl[("lx", live, "fuel")]
        rows.append(fuel_row(cand, live, fc, fb, "live h2h + ext", bool(have[3] or have[4])))  # FUEL rule (1 Nov)
    w = re.search(r"^OTF WARNING.*$", nd, re.M)
    if lane != "param" and not nonc(lane) and HAVE_ND:  # 8 Nov (DRY 9911): the row reads the nochase2 leg; with that bot gone it was INCONCLUSIVE on every behaviour-lane check
        rows.append(("OTF maps", w.group(0)[:70] if w else ("no warning" if nd else "no result"), "no OTF WARNING",
                     "FAIL" if w else ("PASS" if nd else "INCONCLUSIVE")))
    dr = death_row(cand, live, tag)
    if dr:
        rows.append(dr)
    rows += panel_rows(tag)
    rows += trunk_code_rows()
    if FIX_FRESH_HIT or (lane in ("fix", "fixmid") and fix_fresh_led()):  # the fresh leg decides a > 50%-changed fix check (eff_lane); owner 11 Nov: every fix check (FRESH-LED)
        fr = next((r for r in rows if r[0] == "fresh maps"), None)
        m = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", fr[1]) if fr else None
        a = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\] n (\d+)", next((r[1] for r in rows if r[0] == "live h2h"), ""))
        if SAMEPLAY and m and a and fr[3] != "INCONCLUSIVE":
            (p1, l1, h1, n1), (p2, l2, h2, n2) = [(float(x.group(1)), float(x.group(2)), float(x.group(3)), int(x.group(4))) for x in (a, m)]
            pt = (n1 * p1 + n2 * p2) / (n1 + n2)
            se = math.sqrt((n1 * (h1 - l1) / 3.92) ** 2 + (n2 * (h2 - l2) / 3.92) ** 2) / (n1 + n2)
            rows.append(("trunk code pooled", f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n1 + n2} (BIG {n1} + fresh {n2}; {identity_row(SAMEPLAY[0])[1][:40]})",
                         f"pt>={TRUNK_PT:g}, up>=0.50 (no-harm)", "PASS" if pt >= TRUNK_PT and pt + 1.96 * se >= 0.5 else "FAIL"))
        elif not fr or not m or fr[3] == "INCONCLUSIVE":
            rows.append(("fresh decides (fix)", "no complete fresh read", f">= {fresh_min()}, up >= 0.5", "INCONCLUSIVE"))
        else:
            ok = fr[3] == "PASS" and float(m.group(1)) >= float(fresh_min()) and float(m.group(3)) >= 0.5
            rows.append(("fresh decides (fix)", f"{m.group(1)} [{m.group(2)}, {m.group(3)}] over {m.group(4)} maps "
                         + (f"({100 * FIX_FRESH_HIT[0]:.0f}% changed)" if FIX_FRESH_HIT else "(FRESH-LED fix)")
                         # 12 Nov (Builder, 12698 tsxk11qs: point and CI met the bar, the row said FAIL with no reason): name the fresh row's own FAIL
                         + (f"; fresh row {fr[3]}" + (f": negative kinds {kn.group(1)[:80]} (kind flag, z <= -2.5 on a second read)" if (kn := re.search(r"NEG ([^|]*)", fr[1] if len(fr) > 1 else "")) else "")
                            if fr[3] != "PASS" else ""),
                         f">= {fresh_min()}, up >= 0.5, fresh row PASS (no kind flag)", "PASS" if ok else "FAIL"))
    if lane == "draft":
        rows += rare_rows(tag) if RARE else draft_rows(tag)
    vs = [r[3] for r in rows]
    vs = [x for x in vs if x != "EXT"]  # the 636 read handed the decision to the live h2h+ext row
    overall = ("FAIL" if "FAIL" in vs else "VACUOUS" if "VACUOUS" in vs else
               "INCONCLUSIVE" if "INCONCLUSIVE" in vs else "PASS")  # VACUOUS never submits
    return rows, overall


TRUNK_WASM = "/data/USER/trunkproj/wasm"  # the trunk agent's cached release builds: <bot>-<source hash>.wasm
WSEC = "/data/USER/rswproj/wsec.py"


def flip_info(cand):
    """bots/CAND/FLIP (written by tools/lab/flip.sh) as a dict, or None for an ordinary candidate."""
    try:
        return dict(ln.rstrip("\n").split("=", 1) for ln in open(os.path.join(REPO, "bots", cand, "FLIP")) if "=" in ln)
    except OSError:
        return None


def trunk_check(cand, livevals=""):
    """TRUNK mode (1 Nov): CAND is a data-byte flip of a trunk. -> (ok, why, base). The trunk's source must still hash to
    FLIP's TRUNK_HASH; wsec.py must print the code section IDENTICAL between the trunk's cached wasm and CAND's predicted
    wasm, with exactly DATA_BYTES data bytes different. The base is the trunk at live values: the trunk itself when LIVEVALS
    is empty, else a flip.sh copy with LIVEVALS (made once, named <trunk>_live<hash6>)."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    f = flip_info(cand)
    if not f or not f.get("TRUNK"):
        return False, f"no bots/{cand}/FLIP with TRUNK= (make flip candidates with tools/lab/flip.sh)", None
    trunk, th = f["TRUNK"], f.get("TRUNK_HASH", "")
    h = abindex.bot_hash(trunk)
    if h != th:
        return False, f"trunk {trunk} is source {h}, FLIP says {th}: re-flip on the current trunk", None
    tw, cw = os.path.join(TRUNK_WASM, f"{trunk}-{th}.wasm"), f.get("WASM", "")
    if not (os.path.exists(tw) and os.path.exists(cw)):
        fl = f.get("FLIPS", "")  # the wasm cache is per machine: a flip made elsewhere has none here (2 Nov, back on HOST)
        return False, (f"missing wasm ({tw if not os.path.exists(tw) else cw}); rebuild it on this machine and arm the new copy: "
                       f"FLIP_BUILD=1 sh tools/lab/flip.sh {trunk} NEW_NAME '{fl}'"), None
    r = subprocess.run([sys.executable, "-I", WSEC, tw, cw], capture_output=True, text=True)
    code = re.search(r"^code\s+\d+\s+\d+\s+(\S+)", r.stdout, re.M)
    nd = re.search(r"(\d+) bytes differ", r.stdout)
    if not code or code.group(1) != "IDENTICAL":
        return False, f"wsec: code section {code.group(1) if code else 'unread'} vs the trunk (not a data-only flip)", None
    if f.get("DATA_BYTES") and nd and int(nd.group(1)) != int(f["DATA_BYTES"]):
        return False, f"wsec: {nd.group(1)} data bytes differ, FLIP says {f['DATA_BYTES']}", None
    base = trunk
    if livevals.strip():
        base = f"{trunk}_live{hashlib.md5(livevals.encode()).hexdigest()[:6]}"  # 2 Nov: hash() differs per process, so every check made new copies
        if not os.path.isdir(os.path.join(REPO, "bots", base)):
            r2 = subprocess.run(["sh", os.path.join(REPO, "tools/lab/flip.sh"), trunk, base, livevals], cwd=REPO,
                                capture_output=True, text=True)
            if r2.returncode != 0:
                return False, f"flip.sh {trunk} {base} LIVEVALS failed: {(r2.stdout + r2.stderr)[-200:]}", None
    return True, (f"flip of {trunk}@{th} ({f.get('FLIPS', '?')}; wsec code IDENTICAL, {nd.group(1) if nd else '?'} data bytes); "
                  f"base = {base}" + (f" (LIVEVALS {livevals})" if livevals.strip() else " (trunk = live values)")), base


DEATH_GATE = os.environ.get("SC_DEATH_GATE", "1") == "1"  # Builder 1 Nov: the death guard blocks (0 = information only)
DEATH_Z = float(os.environ.get("SC_DEATH_Z", "2.5"))


def death_row(cand, live, tag):
    """Death guard (folded in 1 Nov; Combat's guard.py headline): CAND minus LIVE champion deaths per game, map-paired, on
    every CAND vs LIVE game on record (abindex: BIG and the other legs) and on this check's fresh maps (stylepanel's
    fp_games.jsonl). FAIL when the BIG z >= DEATH_Z (CAND dies more) and the fresh difference has the same sign.
    9 Nov (owner): the guard reads PAIR-ADJUSTED deaths, a linked Cassi+Issac death counted once (GR :381/:442; the records' 'pair' count,
    tools/lab/condab.py pair_deaths). Raw deaths are shown beside it. A set with any record lacking 'pair' (games from before the 9 Nov
    stats) is judged raw and says so; deaths per body per game are shown as information."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    hc, hl = abindex.bot_hash(cand), abindex.bot_hash(live)
    if not hc or not hl or hc == hl:
        return None

    def paired(recs):
        per = collections.defaultdict(lambda: [0, 0, 0])
        for m, dc, dl in recs:
            p = per[m]
            p[0] += dc; p[1] += dl; p[2] += 1
        if len(per) < 2:
            return None
        d = [(p[0] - p[1]) / p[2] for p in per.values()]
        mu = sum(d) / len(d)
        se = math.sqrt(sum((x - mu) ** 2 for x in d) / (len(d) - 1) / len(d))
        g = sum(p[2] for p in per.values())
        return dict(c=sum(p[0] for p in per.values()) / g, l=sum(p[1] for p in per.values()) / g, d=mu,
                    z=mu / se if se > 0 else 0.0, maps=len(d))
    big = []
    for (ha, hb, mh), g in abindex.Index({hc, hl}).games.items():
        if {ha, hb} == {hc, hl}:
            sc, sl = (g["sa"], g["sb"]) if ha == hc else (g["sb"], g["sa"])
            big.append((mh, int(sc.get("deaths", 0)), int(sl.get("deaths", 0)), sc.get("pair"), sl.get("pair"), sc.get("bodies"), sl.get("bodies")))
    fr = []
    try:
        for ln in open(f"/data/USER/st/panel/{tag}/fp_games.jsonl"):
            g = json.loads(ln)
            if {g["a"], g["b"]} == {cand, live}:
                sc, sl = (g["sa"], g["sb"]) if g["a"] == cand else (g["sb"], g["sa"])
                fr.append((g["map"], int(sc.get("deaths", 0)), int(sl.get("deaths", 0)), sc.get("pair"), sl.get("pair"), sc.get("bodies"), sl.get("bodies")))
    except OSError:
        pass
    def adj(recs):  # pair-adjusted, or None when any record has no pair count
        if not recs or any(r[3] is None or r[4] is None for r in recs):
            return None
        return [(r[0], r[1] - int(r[3]), r[2] - int(r[4])) for r in recs]

    def per_body(recs):
        rb = [r for r in recs if r[5] and r[6]]
        return (sum(r[1] / r[5] for r in rb) / len(rb), sum(r[2] / r[6] for r in rb) / len(rb)) if rb else None
    big_a, fr_a = adj(big), adj(fr)
    one = bool(RARE or CONFIRM.get("tag"))  # RARE / CONFIRM MODE: no BIG, the check's own read alone
    pair_on = (big_a is not None or one) and (not fr or fr_a is not None)
    raw_B, raw_F = paired([r[:3] for r in big]), paired([r[:3] for r in fr])
    B, F = ((paired(big_a) if big_a else None), (paired(fr_a) if fr_a else None)) if pair_on else (raw_B, raw_F)
    if one:  # no BIG: the changed-map read (RARE) or the confirm read (CONFIRM MODE) alone
        B, raw_B = F, raw_F
    if not B:
        return ("death guard", "no CAND vs LIVE games on record", f"BIG z < {DEATH_Z:g} or fresh <= 0", "INCONCLUSIVE")
    flag = B["z"] >= DEATH_Z and (F is None or F["d"] > 0)
    val = (("pair-adjusted (C&I pair death once): " if pair_on else "RAW (some records have no pair count; pair-adjusted unavailable): ")
           + f"{'read' if one else 'BIG'} {B['c']:.2f} vs {B['l']:.2f}/g ({B['d']:+.2f}, z {B['z']:+.1f}, {B['maps']} maps); "
           + (f"fresh {F['c']:.2f} vs {F['l']:.2f} ({F['d']:+.2f}, z {F['z']:+.1f}, {F['maps']} maps)" if F else "fresh: no records"))
    if pair_on and raw_B:
        val += (f"; raw {'read' if one else 'BIG'} {raw_B['c']:.2f} vs {raw_B['l']:.2f} ({raw_B['d']:+.2f}, z {raw_B['z']:+.1f})"
                + (f", raw fresh {raw_F['d']:+.2f} (z {raw_F['z']:+.1f})" if raw_F else ""))
    pb = per_body(fr if one else big)
    if pb:
        val += f"; per body {pb[0]:.3f} vs {pb[1]:.3f}/g (information)"
    if one:  # 12 Nov (RC: SC12866 jkc3s failed this row on its ONE 420-map changed read used as both arms): CLAUDE.md §5's death guard needs two
        # independent sets of the same sign, each read at 700+ maps; the rare / confirm read is one set, so the row is information there
        return ("death guard", val + f" | ONE set ({B['maps']} maps): information only (§5 needs two sets of 700+ maps)",
                f"information (one set); two-set rule: not (BIG z >= {DEATH_Z:g} and fresh > 0)", "PASS")
    return ("death guard", val, f"not (BIG z >= {DEATH_Z:g} and fresh > 0)",
            ("FAIL" if DEATH_GATE else "PASS") if flag else "PASS")


def second_read_started(tag):
    return os.path.exists(f"/data/USER/st/panel/{tag}_r/otf.json") or os.path.exists(f"/data/USER/st/panel/{tag}r/otf.json")  # _r from 3 Nov


def draft_rows(tag):
    """LANE=draft (owner 4 Nov via the Builder): the read on the maps where CAND's picks differ from live's (stylepanel --draft-changed,
    DRAFT_N maps, half weird): point > .50 with LOS >= DRAFT_LOS; the panel row (third-party D CI upper >= 0), the fresh row's kinds rule, fuel
    and deaths stay as usual; the implied whole-pool effect is shown, not judged."""
    txt = read(os.path.join(Q, f"sp{tag}.txt"))
    fm = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    pr = re.search(r"draft probe: (\d+) of (\d+) probed maps changed .*?whole-pool firing share \(halves' mean\) ([\d.]+)%", txt)
    kept = sum(int(x) for x in re.findall(r"^    (?:weird|std)\s.*kept (\d+)$", txt, re.M))
    bar = f"point > 0.50, LOS >= {DRAFT_LOS:.0%}, >= 95% of kept maps (>= {DRAFT_MIN})"
    if not fm or not pr:
        return [("draft changed maps", "no draft-changed read", bar, "INCONCLUSIVE")]
    p, lo, hi, n = float(fm.group(1)), float(fm.group(2)), float(fm.group(3)), int(fm.group(4))
    se = max((hi - lo) / 3.92, 1e-9)
    los = 0.5 * (1 + math.erf((p - 0.5) / se / math.sqrt(2)))
    v = ("INCONCLUSIVE" if kept < DRAFT_MIN or n < 0.95 * kept else "PASS" if p > 0.5 and los >= DRAFT_LOS else "FAIL")
    rows = [("draft changed maps", f"{p:.3f} [{lo:.3f}, {hi:.3f}] n {n}/{kept} LOS {100 * los:.0f}% ({pr.group(1)} of {pr.group(2)} probed changed)", bar, v)]
    im = re.search(r"implied whole-pool h2h effect = .*? = ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\]", txt)
    imd = re.search(r"implied whole-pool third-party D = share x D = ([+-][\d.]+)", txt)
    rows.append(("draft implied effect", f"firing {pr.group(3)}% of pool maps: h2h {im.group(1) if im else '?'} [{im.group(2) if im else '?'}, "
                 f"{im.group(3) if im else '?'}], third-party D {imd.group(1) if imd else '?'}", "shown, not judged", "PASS"))
    return rows


def rare_rows(tag):
    """Marker RARE=N: the read on the maps where CAND's games differ (stylepanel --changed; every other map is the base mirror game, exactly .500). The bar is RARE_BAR's; the implied
    whole-pool effect is shown, not judged."""
    txt = read(os.path.join(Q, f"sp{tag}.txt"))
    fm = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    pr = re.search(r"changed probe: (\d+) of (\d+) pool maps changed \(([\d.]+)% .*?(\d+) unchanged dropped.*?(\d+) kept", txt)
    bar = f"point > {RARE['point']:g}, LOS >= {RARE['los']:.0%}, >= {RARE['min']:g} maps read, >= 95% of kept"
    if not fm or not pr:
        nr = re.search(r"not a rare change: (\d+)% of maps changed", read(os.path.join(Q, f"sc_{tag}_sp.log")) + txt)
        if nr:  # 8 Nov (Builder): the probe's verdict, not 'no read': a common change is re-read on the behaviour lane
            return [("rare changed maps", f"not a rare change: {nr.group(1)}% of maps changed: the behaviour lane reads it", bar, "INCONCLUSIVE")]
        return [("rare changed maps", "no changed-map read", bar, "INCONCLUSIVE")]
    p, lo, hi, n, kept = float(fm.group(1)), float(fm.group(2)), float(fm.group(3)), int(fm.group(4)), int(pr.group(5))
    se = max((hi - lo) / 3.92, 1e-9)
    los = 0.5 * (1 + math.erf((p - 0.5) / se / math.sqrt(2)))
    v = "INCONCLUSIVE" if n < RARE["min"] or n < 0.95 * kept else "PASS" if p > RARE["point"] and los >= RARE["los"] else "FAIL"
    rows = [("rare changed maps", f"{p:.3f} [{lo:.3f}, {hi:.3f}] n {n}/{kept} LOS {100 * los:.0f}% ({pr.group(1)} of {pr.group(2)} pool maps changed, {pr.group(4)} unchanged dropped)", bar, v)]
    im = re.search(r"implied whole-pool h2h effect = share x \(score - \.5\) = ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\]", txt)
    rows.append(("rare implied effect", f"changed {pr.group(3)}% of pool maps: h2h {im.group(1) if im else '?'} [{im.group(2) if im else '?'}, {im.group(3) if im else '?'}]", "shown, not judged", "PASS"))
    return rows


def panel_rows(tag):
    """The FRESH-MAP and PLAYSTYLE PANEL rows from stylepanel.py's sp<tag>.txt; none for a check that never launched it."""
    txt = read(os.path.join(Q, f"sp{tag}.txt"))
    if not txt and not os.path.exists(os.path.join(Q, f"sc_{tag}_sp.log")):
        return []
    out = []
    fb = f"DECIDES: >={FRESH_MIN}, up>=0.5" if os.environ.get("SC_FRESH_DECIDES") == "1" else "CI up>=0.5, kinds 2 reads"
    for key, name, bar in (("FRESH", "fresh maps", fb), ("PANEL", "playstyle panel", "pooled up>=0, bots")):
        m = re.search(rf"^{key}: (\w+)\s+(.*)$", txt, re.M)
        if not m:
            out.append((name, "no result (stylepanel did not finish)", bar, "INCONCLUSIVE"))
            continue
        if m.group(1) == "SKIPPED":
            continue
        val = m.group(2).split("; bar:")[0]
        pt = re.search(r"\| (PARTIAL \(.*?legs finished\))", txt)
        if pt:  # stylepanel was stopped (timebox / lh FAIL): the row reads the legs that finished
            val += f" ({pt.group(1)[:60]})"
        neg = re.search(r"; negative (?:kinds|bots): (.*)$", m.group(2))
        cl = re.search(r"^FRESH CLASS: (.*)$", txt, re.M) if key == "FRESH" else None  # 10 Nov: class bins (stylepanel; note only, after the parsed numbers)
        out.append((name, val + (f"; NEG {neg.group(1)}" if neg else "") + (f" | {cl.group(1)}" if cl else ""), bar, m.group(1)))
    return out


SAMEPLAY = []  # the trunk, when CAND is that trunk itself (no data bytes), BUGBAR=1 and its registry line holds the null identity: the > 50% band's no-harm is the trunk-code row


def identity_row(base):
    """The trunk's flag-0 null identity at unlimited fuel, from its registry line: an exact copy of live (REBUILT) or 'identity N/N'."""
    t = re.sub(r"_live[0-9a-f]+$", "", base)
    line = next((x for x in reversed(open("/homes/USER/condor-work/reports/trunk_registry.md", errors="ignore").read().splitlines())
                 if x.startswith(f"- {t} ")), "")
    m = re.search(r"identity (\d+)/(\d+)", line)
    if " REBUILT " in line:
        return ("null identity", f"{t} is an exact copy of live (REBUILT)", "20/20 at unlimited fuel", "PASS")
    if m:
        return ("null identity", f"{t}: identity {m.group(1)}/{m.group(2)} (registry)", "20/20 at unlimited fuel",
                "PASS" if m.group(1) == m.group(2) and int(m.group(2)) >= 20 else "FAIL")
    return ("null identity", f"{t}: no identity in its registry line", "20/20 at unlimited fuel", "FAIL")


def set_sameplay(cand):
    """Same-play code armed as a no-flip trunk (rf4a 7 Nov): CLAUDE.md's trunk-code row judges it, pooled BIG + fresh, not 600 fresh maps alone (se .010: a true null reads under .495 31% of the time)."""
    fi = flip_info(cand) or {}
    if fi.get("TRUNK") and fi.get("DATA_BYTES") == "0" and os.environ.get("BUGBAR") == "1" and identity_row(fi["TRUNK"])[3] == "PASS":
        SAMEPLAY[:] = [fi["TRUNK"]]


TRUNK_CODE = {}  # a flip on a trunk with code live lacks: the read of that code, once per (trunk at live values, live)


def hash_of(bot):
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import abindex
    return abindex.bot_hash(bot)


def trunk_read(cand, base, live):
    """TRUNK mode legs (2 Nov, shipcheck 1030: a no-flip bundle played itself and read nothing, and a flip carried the trunk's code to
    live with no capped-fuel read of it, since every leg plays the trunk at live values and identity is unlimited fuel only).
    CAND = BASE's source: its legs play the real live bot. Else they play BASE, which measures the flip, and if BASE's source is not
    live's, a gate of BASE vs live judges the trunk's code: BIG, fresh, capped fuel, deaths, fix lane. -> (what, TRUNK_CODE fields)."""
    hc, hb, hl = hash_of(cand), hash_of(base), hash_of(live)
    if hc == hb:
        return f"no flips: every leg plays the real live bot {live}", {}
    # 9 Nov 23:05Z (Builder: fb7/fb8/ktb64 trunk-code rows failed on fuel at flag 0; gate base673tc: the baked base ALONE has 1.16x live's cap5
    # cut-offs while playing identically at unlimited fuel): a trunk built on live's baked base (nova_base_vNNN, the diff model) is judged
    # against THAT base, so the row measures the trunk's own code, not the bake. The row keeps its name.
    ref = live
    try:
        tv = trunk_base_version(base)
        lv = next((ln.split()[0] for ln in open("/data/USER/st/bq/live.txt") if ln.split()[1:2] == [live]), "")
        rb = f"nova_base_v{tv}" if tv is not None else ""
        if rb and lv == f"v{tv}" and os.path.isdir(os.path.join(REPO, "bots", rb, "src")):
            ref = rb
        mb = re.fullmatch(r"nova_base_v(\d+)", base)
        if mb and lv == f"v{mb.group(1)}":  # 11 Nov (Builder: jns6r's tc row FAILed 'null identity' on nova_base_v717 itself): a flip-only line's
            ref = base                      # trunk IS live's baked base, so it carries no code live lacks: no trunk-code row
    except (OSError, IndexError, ValueError):
        ref = live
    if ref != live:
        hl, live = hash_of(ref), ref
    if hb == hl or os.environ.get("SC_TRUNK_CODE", "1") == "0":
        return f"every leg plays {base}" + ("" if hb == hl else " (SC_TRUNK_CODE=0: trunk code not read)"), {}
    import abindex
    gt = f"tc{hb[:8]}{hl[:8]}" + ("" if abindex.cli_version() == "4.0.0" else "c" + abindex.cli_version().replace(".", ""))  # engine in the tag (finals patch)
    vf = f"/data/USER/st/gate/{gt}/verdict.txt"
    m = re.search(r"OVERALL: (\w+)", read(vf))
    cached = m.group(1) if m and m.group(1) in ("PASS", "FAIL") else ""
    if cached == "FAIL" and tc_judge(read(vf))[0] == "PASS":  # 11 Nov: a fuel-only FAIL of the flag-0 trunk is not a trunk-code FAIL (score bar)
        cached = "PASS"
    py = f"nice -n 10 python3 -I {os.path.join(REPO, 'tools/lab/gate.py')} {base} {live} --lane fix --no-style --no-a --keep-fresh --trunk-code --tag {gt}"
    # one gate per pair: a second check on this trunk waits on the lock, then finds the verdict
    cmd = f"flock {shlex.quote(os.path.join(Q, '.tc_' + gt + '.lock'))} sh -c {shlex.quote(f'grep -qE ' + chr(34) + 'OVERALL: (PASS|FAIL)' + chr(34) + f' {vf} 2>/dev/null || {py}')}"
    return (f"every leg plays {base} (the flip); trunk code vs {live}: " + (f"gate {gt} {cached}, cached" if cached else f"gate {gt}"),
            dict(base=base, live=live, tag=gt, file=vf, cmd=cmd, verdict=cached))


def tc_judge(txt):
    """-> (verdict, note) of a trunk-code gate's verdict.txt. 11 Nov (Builder, ffs24r 12383): CLAUDE.md section 5's trunk-code bar is the SCORE
    (pooled BIG + fresh >= .495, CI upper >= .50); the flag-0 trunk's fuel rows judge code that never ships as flag 0 (a pass ships the flag on,
    and the bake folds it), so a gate that FAILs on fuel rows only, with its pooled row PASS, is a PASS here (fuel shown as information)."""
    m = re.search(r"OVERALL: (\w+)", txt)
    v = m.group(1) if m else "INCONCLUSIVE"
    if v != "FAIL":
        return v, ""
    bad = [" ".join(ln.split()[:2]) for ln in txt.splitlines() if re.search(r"\bFAIL\s*$", ln) and not ln.strip().startswith("OVERALL")]
    if bad and all(re.match(r"(fuel exhaustions|change v)", x) for x in bad) and re.search(r"^\s*pooled BIG\+fresh .*PASS\s*$", txt, re.M):
        return "PASS", "; fuel rows FAIL on the flag-0 trunk: information (score bar only, CLAUDE.md section 5)"
    return v, ""


def trunk_code_rows():
    """The 'trunk code vs live' row; none when the trunk has no code live lacks. FAIL or no read blocks the submit."""
    if not TRUNK_CODE:
        return []
    txt = read(TRUNK_CODE["file"])
    m = re.search(r"OVERALL: (\w+)", txt)
    v = m.group(1) if m else "INCONCLUSIVE"
    bits = [ln.strip()[:46] for ln in txt.splitlines() if re.match(r"\s*(BIG|fresh maps|fuel exh)", ln)]
    v, note = tc_judge(txt)
    if False:  # 11 Nov (Builder, ffs24r 12383): CLAUDE.md section 5's trunk-code bar is the SCORE (pooled BIG + fresh >= .495, CI upper >= .50); the
        # flag-0 trunk's fuel rows judge code that never ships as flag 0 (a pass ships the flag on, the bake folds it). Fuel rows: information.
        bad = [ln.split()[0] + (" " + ln.split()[1] if len(ln.split()) > 1 else "") for ln in txt.splitlines()
               if re.search(r"\bFAIL\s*$", ln) and not ln.strip().startswith("OVERALL")]
        fuelonly = bad and all(re.match(r"(fuel exhaustions|change v)", x) for x in bad)
        if fuelonly and re.search(r"^\s*pooled BIG\+fresh .*PASS\s*$", txt, re.M):
            v, note = "PASS", "; fuel rows FAIL on the flag-0 trunk: information (score bar only, CLAUDE.md section 5)"
    return [("trunk code vs live", ("; ".join(bits) or "no result (gate did not finish)")[:150] + f" (gate {TRUNK_CODE['tag']})" + note, "gate fix lane (score)", v)]


MANYGRP_N = int(os.environ.get("SC_MANYGRP_N", "80"))  # 0 = off


def big2_line(rtag, cand):
    """11 Nov (owner: the fix lane keeps pool + BIG2 as its BIG row; a BIG2-only line as information): the live h2h's score on the BIG2 maps
    (b2_*) alone, both seats paired, from the leg's games.jsonl. Never a row."""
    import glob as _g
    try:
        g = {}
        for f in _g.glob(f"/data/USER/abl/cq_lh{rtag}_*/games.jsonl"):
            for ln in open(f):
                r = json.loads(ln)
                if not r.get("ok") or not str(r.get("map", "")).startswith("b2_"):
                    continue
                seat = "A" if r["a"] == cand else "B"
                g.setdefault(r["map"], {})[seat] = 1.0 if r["win"] == seat else 0.0
        s = [(v["A"] + v["B"]) / 2 for v in g.values() if len(v) == 2]
        if len(s) < 30:
            return ""
        n = len(s)
        m = sum(s) / n
        se = math.sqrt(sum((x - m) ** 2 for x in s) / (n - 1) / n)
        return f"\n  BIG2 only (information; the BIG row reads pool + BIG2): {m:.4f} [{m - 1.96 * se:.4f}, {m + 1.96 * se:.4f}] n {n} maps"
    except (OSError, ValueError, KeyError):
        return ""


def manygrp_line(rtag, cand, live):
    """11 Nov (Builder/RC X306; owner decides blocking): capped fuel cut-offs on SC_MANYGRP_N new w_manygrp maps (65-130 groups, ladder-shaped;
    the pool and BIG top out at 64), CAND v LIVE, the main row's cap rule. INFORMATION: printed after the verdict, never a row, until the
    owner makes it blocking (then SC_MANYGRP_BLOCK=1 and a row; not built yet)."""
    if MANYGRP_N <= 0 or RARE:  # 13 Nov (TB): the leg never runs on rare reads (launch skips them), so no 'no games back' line there
        return ""
    rec = panel_recs(f"{rtag}mg", cand, live)
    if not rec:
        return f"\n  many-group fuel (w_manygrp, information): no games back (log sc_*_mg.log)"
    per, aft = {}, [0, 0]
    for m, c, b in rec:
        # 13 Nov (owner, typed to Shared Mem: "differentiate between intentional and unintentional fuel faults"): as cap5, only cut-offs
        # BEFORE the turn's actions count; after-action cut-offs (a marker bot spending leftover fuel on purpose) print as information
        x = per.setdefault(m, [0, 0])
        x[0] += min(max(0, int(c.get("fuel", 0)) - int(c.get("fuel_after", 0))), FUEL_CAP)
        x[1] += min(max(0, int(b.get("fuel", 0)) - int(b.get("fuel_after", 0))), FUEL_CAP)
        aft[0] += int(c.get("fuel_after", 0))
        aft[1] += int(b.get("fuel_after", 0))
    cc, bb = sum(v[0] for v in per.values()), sum(v[1] for v in per.values())
    d = [v[0] - v[1] for v in per.values()]
    n = len(d)
    mu = sum(d) / n
    se = (sum((x - mu) ** 2 for x in d) / max(1, n - 1) / n) ** 0.5 * n
    over = cc - bb > max(0.05 * bb, FUEL_Z * se, 5)
    return (f"\n  many-group fuel (w_manygrp, information; owner decides blocking): cap{FUEL_CAP} CAND {cc} v LIVE {bb} "
            f"({cc / max(1, bb):.2f}x, {n} maps, {len(rec)} games; pre-action cut-offs{f'; after-action {aft[0]} v {aft[1]}: information (intentional)' if any(aft) else ''}); "
            f"the main fuel rule would {'FAIL' if over else 'pass'} it")


def ladder_panel_line(tag, lane):
    """10 Nov (Planner, from Deep's selfplay_tempo_1110: self-play inflates early fighting ~1.8x; the sbg and fish panel legs match the
    ladder's tempo, aggro runs high): for behaviour-lane checks, the sbg + fish panel D pooled, printed under the table next to the h2h.
    Information only (no row, no bar): an h2h gain the ladder-like legs don't share may be a self-play tempo gain."""
    if lane not in ("behaviour", "param", "draft"):
        return ""
    try:
        txt = open(os.path.join(Q, f"sp{tag}.txt")).read()
    except OSError:
        return ""
    got = {}
    for m in re.finditer(r"^\s+(nova_spar_(sbg|fish))\s+n (\d+).*?D ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\]", txt, re.M):
        got[m.group(2)] = (int(m.group(3)), float(m.group(4)), (float(m.group(6)) - float(m.group(5))) / (2 * 1.96))
    if not got:
        return ""
    d = sum(v[1] for v in got.values()) / len(got)
    se = sum(v[2] ** 2 for v in got.values()) ** 0.5 / len(got)
    parts = ", ".join(f"{k} {v[1]:+.3f} (n {v[0]})" for k, v in sorted(got.items()))
    return (f"\n  ladder-like panel (sbg + fish; self-play tempo check, information): D {d:+.4f} [{d - 1.96 * se:+.4f}, {d + 1.96 * se:+.4f}] ({parts})"
            + ("; h2h gain not seen on the ladder-like legs: possible self-play tempo gain" if d + 1.96 * se < 0 else ""))


def tempo_line(tag):
    """10 Nov (Planner/Deep): tempocheck.py on the CONFIRM leg's kept replays, detached after the verdict (never part of it)."""
    if not glob.glob(os.path.join(Q, "tempo", tag, "**", "*.repl26a"), recursive=True):
        return ""
    with open(os.path.join(Q, f"sc_{tag}_tempo.txt"), "w") as f:
        subprocess.Popen(["nice", "-n", "15", sys.executable, "-I", os.path.join(REPO, "tools/lab/tempocheck.py"), tag], cwd=REPO,
                         stdout=f, stderr=subprocess.DEVNULL, start_new_session=True)
    return f"\n  self-play tempo: see {os.path.join(Q, f'sc_{tag}_tempo.txt')} (tempocheck.py, after the verdict)"


def hetero_line(tag, cand, overall):
    """4 Nov (owner: which maps is a change good on?): hetero.py's 'where it helps' lead on the fresh leg, after the verdict and
    never part of it. Inline on a non-PASS (flat and failed reads are what it is for); on a PASS detached into sc_<tag>_hetero.txt
    so a ship is never delayed."""
    if not os.path.exists(f"/data/USER/st/panel/{tag}/fp_games.jsonl"):
        return ""
    if os.path.exists(os.path.join(Q, "hetero_off")):  # 13 Nov 20:1xZ (Builder: information only; local load near 90): off until midnight
        return ""
    cmd = ["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/hetero.py"), "read", tag, "--cand", cand, "--brief",
           "--perm", "500", "--min-half", "100"]
    # 4 Nov (iterspeed report): always detached; inline on a non-PASS it held the shipwatch slot 1.2-6.4 min and delayed re-arms
    with open(os.path.join(Q, f"sc_{tag}_hetero.txt"), "w") as f:
        subprocess.Popen(cmd, cwd=REPO, stdout=f, stderr=subprocess.DEVNULL, start_new_session=True)
    return f"\n  where it helps: see {os.path.join(Q, f'sc_{tag}_hetero.txt')} (hetero.py, running after the verdict)"


CTRUNK = [False]  # LANE=ctrunk (owner 6 Nov): set in main; the legs run as the fix lane


def fmt(rows, overall, cand, live, tag, lane, wall):
    # 10 Nov (Builder: since.py read rare checks as 'lane draft'): a RARE=N check runs the draft lane's legs, but it is the rare lane
    L = [f"SHIPCHECK {tag}: {cand} vs live {live}, lane {'ctrunk' if CTRUNK[0] else ('rare' if RARE else lane)}, wall {wall / 60:.1f} min"
         + ("\n  CTRUNK: h2h informational (owner 6 Nov)" if CTRUNK[0] else ""),
         f"  {'leg':20s} {'value':58s} {'bar':16s} verdict"]
    L += [f"  {a:20s} {b:58s} {c:16s} {d}" for a, b, c, d in rows]
    L.append(f"  OVERALL: {overall}")
    return "\n".join(L)


# ---------------------------------------------------------------- submit
TAGS = os.path.join(Q, "shipcheck_tags.json")  # TAG -> CAND: a TAG names one candidate's runs (29 Oct 21:24 collision)


def claim_tag(tag, cand):
    """Refuse a TAG another candidate used (its sc_/nd/cf/subset files would be overwritten); else record it."""
    with open(TAGS + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            reg = json.load(open(TAGS))
        except (OSError, ValueError):
            reg = {}
            for f in glob.glob(os.path.join(Q, "shipcheck_*.txt")):  # seed: earlier verdict tables
                m = re.match(r"SHIPCHECK (\S+): (\S+) vs", read(f))
                if m:
                    reg.setdefault(m.group(1), m.group(2))
        if reg.get(tag, cand) != cand:
            return reg[tag]
        reg[tag] = cand
        json.dump(reg, open(TAGS + ".new", "w"), indent=1)
        os.replace(TAGS + ".new", TAGS)
    return None


POSTSHIP_ND = {}  # the gate's nochase2 reference runs, for the post-ship complement leg
SUBMIT_RETRY_S = int(os.environ.get("SC_SUBMIT_RETRY_S", 30))  # before reading the listing after a failed upload
POSTSHIP_LEG_S = int(os.environ.get("POSTSHIP_LEG_S", 6 * 3600))  # a stuck post-ship leg ends here


def subject_line(lane):
    """The commit subject: the marker's SUBJECT, else "LANE: SWITCH" from the first word of MECH."""
    sub = os.environ.get("SUBJECT", "").strip()
    if sub:
        return sub
    w = re.match(r"[A-Za-z0-9_]+", os.environ.get("MECH", "").strip())
    kind = {"fix": "fix", "param": "tune"}.get(lane, "feat")
    return f"{kind}: {w.group(0) if w else 'change'}"


SUBLOG = "/homes/USER/condor-work/reports/submissions_log.md"


def affects_pct(cand, wait=0):
    """12 Nov ~22:3xZ (owner: "For each submission, write percentage of maps it changes as well"): tools/lab/affects.py's reading for this
    bot (bq/affects.tsv), waiting up to `wait` s for it; a rare read's changed share as the fallback. -> '12.5%' or ''."""
    t_end = time.time() + wait
    while True:
        try:
            rows = [ln.rstrip("\n").split("\t") for ln in open(os.path.join(Q, "affects.tsv")) if f"\t{cand}\t" in ln]
            rows = [p for p in rows if len(p) >= 6 and p[5]]
            if rows:  # 13 Nov (owner: "why does it keep saying 0% maps"): a fuel-only change (0% at unlimited fuel) shows its 100k cut-off change
                p_ = rows[-1]
                if float(p_[5]) == 0 and len(p_) >= 7 and p_[6]:
                    return f"0% maps, fuel cuts/g {p_[6]}"
                return f"{float(p_[5]):g}%"
        except OSError:
            pass
        if time.time() >= t_end:
            return ""
        time.sleep(10)


def log_submission(version, cand, live, tag, lane, text):
    """Append a git-commit-style entry (subject, metadata, body = MECH, gate rows) to the submissions log."""
    body = os.environ.get("MECH", "").strip() or "(no MECH text in the marker)"
    rows = [x.strip() for x in text.splitlines()
            if re.match(r"\s*(live h2h|anchor|ubaudit|fix-lane change size|nochase2|CONFIRM|fuel|faults|OVERALL)", x)]
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    entry = (f"\n## v{version} {subject_line(lane)}\n\n"
             f"bot `{cand}` | parent `{live}` | shipcheck {tag}, lane {lane} | {when}"
             + (f" | changes {affects_pct(cand)} of maps" if affects_pct(cand) else "") + "\n\n"
             + textwrap.fill(body, 116) + "\n\nGate:\n" + "".join(f"    {r}\n" for r in rows))
    dst = (SUBLOG + ".dry") if DRY else SUBLOG
    with open(dst + ".lock", "a") as sl:
        fcntl.flock(sl, fcntl.LOCK_EX)
        old = read(dst) or "# Submissions log (git-commit style; newest last)\n"
        open(dst + ".new", "w").write(old + entry)
        os.replace(dst + ".new", dst)


def upload(cmd):
    """One platform upload -> the version it reports, or None."""
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    out = r.stdout + r.stderr
    say(f"submit exit {r.returncode}: {out.strip()[-300:]}")
    mm = re.search(r"\bv(\d{3,4})\b", out) or re.search(r"[Vv]ersion\D{0,3}(\d{3,4})", out)
    return mm.group(1) if r.returncode == 0 and mm else None


def landed(note, ver):
    """After a failed upload: did it reach the platform anyway? -> (version or None, may we retry). The listing decides, so a lost
    response can never double-submit: an unreadable listing, or a newer version with another note, means no retry."""
    pv, notes = platform_listing()
    if pv is None or not notes:
        return None, False
    new = {v: n for v, n in notes.items() if v > int(ver)}
    mine = [v for v, n in new.items() if n.strip()[:40] == note.strip()[:40]]
    return (str(max(mine)), False) if mine else (None, not new)


def submit_once_more(cmd, note, ver):
    """The upload, retried once inside the submit lock (2 Nov: v401's upload got 'invalid response' from the platform, and a hand
    resubmit skipped the post-ship read). -> the version, or None when it has to be looked at by hand."""
    version = upload(cmd)
    if version or not str(ver).isdigit():
        return version
    time.sleep(SUBMIT_RETRY_S)
    version, retry = landed(note, ver)
    if version:
        say(f"submit: the failed upload landed anyway as v{version}: not uploading again")
        return version
    if not retry:
        say("submit: no retry: the platform listing is unreadable or shows another new version")
        return None
    say("submit: retrying once")
    version = upload(cmd)
    if version:
        return version
    time.sleep(SUBMIT_RETRY_S)
    return landed(note, ver)[0]


NC_SECOND_N, SPAR_SECOND_N = 600, 1200


def second_read(rows, overall, cand, live, tag, lane):
    """Owner 2 Nov (through the Builder), more games, not lower bounds: on the behaviour lane, when one row alone fails and it is the fixed-subset nochase2 row (600 new maps) or one
    spar at z <= -2.5 in a panel whose pooled read is fine (1,200 new maps), that opponent plays once more on new unsaved maps, both seats, CAND vs live, and the read replaces the
    failure: PASS if point >= 0 and CI upper >= 0, else the failure stands. A pooled panel failure or any other failing row plays no second set."""
    bad = [r for r in rows if r[3] == "FAIL"]
    # The fix lane only with the file spar2_fix_enabled in the queue dir: off until the owner answers (Builder 2 Nov; the owner's approval was for the behaviour lane)
    if len(bad) != 1 or (lane != "behaviour" and not (lane in ("fix", "fixmid") and os.path.exists(os.path.join(Q, "spar2_fix_enabled")))
                         and not (lane == "draft" and os.path.exists(os.path.join(Q, "spar2_draft_enabled")))):
        return rows, overall  # 7 Nov: the draft lane too, with the file spar2_draft_enabled (owner's call), its spar read on draft-changed maps
    if bad[0][0] == "nochase2 paired D":
        spar, n, rt = "nova_spar_nochase2", NC_SECOND_N, f"{tag}n"
    elif bad[0][0] == "playstyle panel":
        m = re.search(r"^PANEL: \w+\s+pooled D [+-][\d.]+ \[[+-][\d.]+, ([+-][\d.]+)\].*?negative bots: (\S+?)\s*$", read(os.path.join(Q, f"sp{tag}.txt")), re.M)
        if not m or float(m.group(1)) < 0 or "," in m.group(2):
            return rows, overall
        spar, n, rt = m.group(2), SPAR_SECOND_N, f"{tag}s"
    else:
        return rows, overall
    say(f"{bad[0][0]} failed alone ({bad[0][1][:50]}): second read vs {spar} on {n} new maps")
    dc = ["--draft-changed", str(n)] if lane == "draft" else []  # a draft change alters only the maps where the picks differ: read the spar there
    p = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, rt, "--n", str(n), *dc, "--panel", spar,
                        "--parent", str(os.getpid())], cwd=REPO, capture_output=True, text=True, env=dict(os.environ, SP_PRIO="12"), timeout=1800)
    m = re.search(r"^PANEL: \w+\s+pooled D ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\] over (\d+) maps", read(os.path.join(Q, f"sp{rt}.txt")), re.M)
    ok = bool(m) and int(m.group(4)) >= 0.9 * n and float(m.group(1)) >= 0 and float(m.group(3)) >= 0
    val = f"second read vs {spar[10:]} {m.group(1)} [{m.group(2)}, {m.group(3)}] n {m.group(4)}; first {bad[0][1][:30]}" if m else f"second read gave no result (rc {p.returncode}); first {bad[0][1][:30]}"
    third = None
    if (not ok and m and spar != "nova_spar_nochase2" and int(m.group(4)) >= 0.9 * n
            and float(m.group(1)) < 0 and float(m.group(2)) <= 0 <= float(m.group(3))):
        # owner 4 Nov ~19:00Z (CLAUDE.md section 5): the second read is within noise but below 0 -> ONE more read of n new maps v that
        # spar, then all three reads pooled (map-weighted, tools/lab/sparpool.py) decide: point >= 0 and CI upper >= 0
        import sparpool
        rt3 = f"{tag}s3"
        say(f"second read vs {spar} {m.group(1)} [{m.group(2)}, {m.group(3)}] is within noise but below 0: third read on {n} new maps, then the three pooled")
        p3 = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, rt3, "--n", str(n), *dc, "--panel", spar,
                             "--parent", str(os.getpid())], cwd=REPO, capture_output=True, text=True, env=dict(os.environ, SP_PRIO="12"), timeout=1800)
        reads = [sparpool.spar_read(spar, t) for t in (tag, rt, rt3)]
        if all(reads) and reads[2][2] >= 0.9 * n:
            d, se, pn = sparpool.pool(reads)
            ok = d >= 0 and d + 1.96 * se >= 0
            third = (d, se, pn)
            val = (f"three reads vs {spar[10:]} pooled {d:+.4f} [{d - 1.96 * se:+.4f}, {d + 1.96 * se:+.4f}] n {pn} (first {reads[0][0]:+.4f}, second {reads[1][0]:+.4f}, "
                   f"third {reads[2][0]:+.4f}); sparpool.py {spar[10:]} {tag} {rt} {rt3}")
        else:
            val += f"; third read gave no full result (rc {p3.returncode}): the second read decides"
    with open(os.path.join(Q, "fresh_second_reads.jsonl"), "a") as f:
        f.write(json.dumps(dict(kind="nochase2" if spar == "nova_spar_nochase2" else "panel_spar", spar=spar, n=n, t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tag=tag, cand=cand,
                                live=live, first=bad[0][1], second=m.groups() if m else None, third_pooled=third, passed=ok)) + "\n")
    rows = [(bad[0][0], val, ("three reads pooled" if third else "second read replaces") + ": point >= 0, CI upper >= 0", "PASS" if ok else "FAIL")
            if r is bad[0] else r for r in rows]
    res = [r[3] for r in rows]
    return rows, "FAIL" if "FAIL" in res else "VACUOUS" if "VACUOUS" in res else "INCONCLUSIVE" if "INCONCLUSIVE" in res else "PASS"


FRESH_LED = os.environ.get("SC_FRESH_LED", "1") != "0"  # owner 11 Nov ~16:0xZ ("ship based mainly on fresh"), agreed form (Builder + TB, owner chose "fresh-led, same power"):
# the behaviour lane's sequential read pools ONLY new fresh maps (looks/z bars of seqbar.txt unchanged); BIG is a no-harm row (point >= BIG_NH_PT and
# CI upper >= .50); a std-half no-harm row (std point >= BIG_NH_PT) joins the PASS. SC_FRESH_LED=0: the pooled BIG + fresh read as before.
BIG_NH_PT = 0.495
FRESH_N_FIX = int(os.environ.get("SC_FRESH_N_FIX", 3300))  # owner 11 Nov: the fix lane's fresh read decides on 3,300 maps
# 13 Nov 18:4xZ (owner, AskUserQuestion "Halve reads + cap slots", after a behaviour change ships): while bq/fix_small exists the fix lane
# reads half: fresh 3,300 -> 1,650 maps and BIG no-harm 2,000 -> 1,000 (half_noharm); same point / CI bars. rm bq/fix_small restores.
FIX_SMALL = os.path.exists("/data/USER/st/bq/fix_small")
if FIX_SMALL and not os.environ.get("SC_FRESH_N_FIX"):
    FRESH_N_FIX = FRESH_N_FIX // 2


def fix_fresh_led():
    """owner 11 Nov ~16:3xZ (asked directly; "Fresh-led, harm bound on BIG"): fix-lane checks are decided by the fresh read (>= 3,300 maps,
    point >= .50, CI upper >= .50); the BIG live h2h is no-harm (point >= .495, CI upper >= .50) and carries the bug bar's CI lower >= .4975.
    Not RARE (its changed-map read decides) and not the draft lane. SC_FIX_FRESH_LED=0: the old fix bar."""
    return FRESH_LED and not RARE and os.environ.get("SC_FIX_FRESH_LED", "1") != "0"
POOL_PT, POOL_LOS, POOL_NOHARM = 0.503, 0.90, 0.50  # owner 3 Nov ~03:20Z after audit b935 (CLAUDE.md section 5, POOLED DECIDES); no-harm .50 since 7 Nov


def pooled_row(rows, overall, lane):
    """Behaviour lane, fresh decides: BIG and the per-run fresh maps pooled into one map-weighted read (maps are independent across the two sets),
    pass at point >= POOL_PT and LOS >= POOL_LOS. The BIG row stays as no-harm (point >= POOL_NOHARM), the fresh row as >= FRESH_MIN with the kinds rule."""
    if not fresh_decides(lane):
        return rows, overall
    lr = next((r for r in rows if r[0] == "live h2h"), None)
    fr = next((r for r in rows if r[0] == "fresh maps"), None)
    a = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\] n (\d+)", lr[1]) if lr else None
    b = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", fr[1]) if fr else None
    if not a or not b:
        row = ("pooled BIG + fresh", "no read (a leg has no result)", f"pt>={POOL_PT}, LOS>={POOL_LOS:.0%}", "INCONCLUSIVE")
    else:
        (p1, lo1, hi1, n1), (p2, lo2, hi2, n2) = [(float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))) for m in (a, b)]
        s1, s2 = (hi1 - lo1) / 3.92, (hi2 - lo2) / 3.92
        if FRESH_LED:  # fresh only: BIG is the no-harm live h2h row
            n1 = 0
        pt = (n1 * p1 + n2 * p2) / (n1 + n2)
        se = math.sqrt((n1 * s1) ** 2 + (n2 * s2) ** 2) / (n1 + n2)
        los = 0.5 * (1 + math.erf((pt - 0.5) / max(se, 1e-9) / math.sqrt(2)))
        row = ("pooled BIG + fresh", f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n1 + n2} (BIG {n1} + fresh {n2}) LOS {100 * los:.0f}%",
               f"pt>={POOL_PT}, LOS>={POOL_LOS:.0%}", "PASS" if pt >= POOL_PT and los >= POOL_LOS else "FAIL")
        if seq_bar():  # verdict EXT: seq_extend (called right after param_row) decides; it never reaches the table as EXT
            v0 = seq_decide(pt, se, seq_bar()[0][1], len(seq_bar()) == 1, p2)
            if FRESH_LED and n2 < 0.95 * seq_bar()[0][0] and v0 == "PASS":  # under look 1's n: no PASS yet (the stop rule still applies)
                v0 = "EXT"
            row = ("pooled BIG + fresh", f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n1 + n2} (" + (f"FRESH-LED: fresh {n2}; BIG no-harm" if FRESH_LED else f"BIG {n1} + fresh {n2}") + f") z {(pt - 0.5) / max(se, 1e-9):+.2f}",
                   seq_bar_text(0), v0)
    rows = rows + [row]
    res = [r[3] for r in rows]
    return rows, "FAIL" if "FAIL" in res else "VACUOUS" if "VACUOUS" in res else "INCONCLUSIVE" if "INCONCLUSIVE" in res else "PASS"


# ---------------------------------------------------------------- sequential pooled read (owner 3 Nov ~18:20Z, DR dr52, b1044)
# BQ/seqbar.txt absent: today's bars exactly, nothing logged. Present (tools/lab/seqbar.example has the format):
#   looks N1 N2 N3                          the map counts of the nested looks
#   set NAME Z1 Z2 Z3 stop point P|los L    a threshold set; an earlier look stops at point <= P, or at LOS < L
#   decide NAME|none                        the set that decides the ship; none: today's bars and the near-miss still decide, the sets only shadow
#   shadow_full N                           the next N behaviour candidates play every look whatever the verdicts, detached (never holding up or changing a ship); counts down
# Every read logs each set's verdict at each look to BQ/seqbar_log.jsonl; the built-in set 'today' is the POOLED DECIDES bar.
SEQBAR = os.path.join(Q, "seqbar.txt")
SEQ_CHUNK = int(os.environ.get("SC_SEQ_CHUNK", 1200))  # an extension plays in sets of this many maps: freshpool keeps ~20 sets of 300, a 9,600-map take would never find 32
SEQ_PAR = int(os.environ.get("SC_SEQ_PAR", 3))  # chunks playing at once over ALL shipchecks (BQ/.seqchunk_K.lock)
SEQ_PRIO = os.environ.get("SC_SEQ_PRIO", "11")  # a deciding read: level with info reads' legs (11), under first reads' 12; a shadow read plays at 5 (seq_shadow_main)
SEQ_STALL = os.environ.get("SC_SEQ_STALL", "1200")  # stylepanel doubles it for a fresh leg; a merely queued leg gets 3 x that
SEQ_WAIT = int(os.environ.get("SC_SEQ_WAIT", 3 * 3600))  # one chunk, once it has a slot
SEQ_KIND_Z = float(os.environ.get("SC_SEQ_KIND_Z", 3.5))  # about 90 kinds per read: at the usual 2.5 a null candidate blocks here 19-25% of the time on 6,000-16,000 maps (simulated on real labels), at 3.5 about 1-3%
_SEQ, SEQ_ST = [], {}
SEQ_SPAR = {}  # marker SEQ_SPAR=1 (owner 3 Nov via the Builder, one-off for MH): the spar whose second read failed with 0 inside its CI, and its reads [(D, se, n)]


def seq_parse(path):
    """-> dict(looks=[n...], sets={name: ([z...], (kind, value))}, decide=name or None, shadow=N). {} for a missing file; ValueError for one that doesn't read."""
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    c = dict(looks=[], sets={}, decide=None, shadow=0)
    for ln in lines:
        f = ln.split("#")[0].split()
        if not f:
            continue
        if f[0] == "looks":
            c["looks"] = [int(x) for x in f[1:]]
        elif f[0] == "set" and len(f) >= 6 and f[-3] == "stop" and f[-2] in ("point", "los"):
            # 12 Nov (owner: "run on more maps when high possibility of hitting threshold"): the stop value may be a comma list, one per
            # non-final look (e.g. los 0.60,0.85: look 3 is played only when look 2's LOS >= 85%); one value applies to every look
            sv = [float(x) for x in f[-1].split(",")]
            c["sets"][f[1]] = ([float(x) for x in f[2:-3]], (f[-2], sv[0] if len(sv) == 1 else sv))
        elif f[0] == "decide" and len(f) == 2:
            c["decide"] = None if f[1] in ("none", "today") else f[1]
        elif f[0] == "shadow_full" and len(f) == 2:
            c["shadow"] = int(f[1])
        else:
            raise ValueError(f"bad line {ln.strip()!r}")
    if not c["looks"] or c["looks"] != sorted(set(c["looks"])) or not c["sets"]:
        raise ValueError("needs ascending looks and a set")
    if any(len(z) != len(c["looks"]) for z, _ in c["sets"].values()) or (c["decide"] and c["decide"] not in c["sets"]):
        raise ValueError("a set's z count differs from the looks, or decide names no set")
    return c


def seq_conf():
    """seqbar.txt, read once per process; a file that doesn't read counts as absent (today's bars, said once)."""
    if not _SEQ:
        try:
            _SEQ.append(seq_parse(SEQBAR))
        except (ValueError, IndexError) as e:
            say(f"!! {SEQBAR} unreadable ({e}): today's bars apply")
            _SEQ.append({})
    return _SEQ[0]


def fresh_n_decides():
    """12 Nov ~14:0xZ (TB; owner 'smaller first reads'): the first fresh draw is look 1 of seqbar.txt (1,650), not a fixed 3,300: with
    3,300 drawn up front, look 1 was judged on 3,300 maps and look 2 played none. SC_FRESH_N_B set by hand still wins."""
    if os.environ.get("SC_FRESH_N_B") or not FRESH_LED:
        return FRESH_N_DECIDES
    c = seq_conf()
    return int(c["looks"][0]) if c and c.get("looks") else FRESH_N_DECIDES


FF_PILOTS = int(os.environ.get("SC_FF_PILOTS", "25"))


def fresh_first_on(lane):
    """FRESH-FIRST (owner 12 Nov ~14:0xZ, asked directly with pilots short: "fewer tests on each set", chose 'No-harm after fresh
    passes'): a behaviour check whose fresh read decides plays look 1's fresh maps ALONE first; the BIG live h2h, the panel and the
    information legs start only when that read is not below the fresh bar. Bars unchanged. On while alive pilots < SC_FF_PILOTS (25),
    always with bq/fresh_first or SC_FRESH_FIRST=1, never with SC_FRESH_FIRST=0."""
    v = os.environ.get("SC_FRESH_FIRST", "auto")
    if v == "0" or not fresh_decides(lane) or RARE or CONFIRM.get("from") or not FRESH_LED:
        return False
    if v == "1" or os.path.exists(os.path.join(Q, "fresh_first")):
        return True
    try:
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import pilotd
        return len(pilotd.alive_pilots()) < FF_PILOTS
    except Exception:  # noqa: BLE001
        return False


PANEL_N_SC = [600]  # the panel's map count (stylepanel --panel-n); HALF NO-HARM sets 300 while pilots are short


def half_noharm(lane):
    """HALF NO-HARM (owner 12 Nov ~15:1xZ, asked directly: "For now sure, but when load recovers go back to default"): while alive pilots
    < SC_FF_PILOTS (25), a behaviour check whose fresh read decides plays its no-harm legs at half size: BIG 2,000 -> 1,000 maps
    (LH_BIG) and the panel 600 -> 300 maps a spar. Decided once per check at leg start, so a check started after the pilots recover
    plays the default sizes. The rows' bars are unchanged (they read wider CIs). SC_HALF_NOHARM=0 off, =1 always."""
    global LH_BIG, LH_MIN, PANEL_WAIT
    v = os.environ.get("SC_HALF_NOHARM", "auto")
    if v == "0" or not fresh_decides(lane) or RARE or CONFIRM.get("from") or not FRESH_LED:
        return False
    # 13 Nov 18:5xZ (owner, AskUserQuestion "Two-stage": BIG 1,000 + panel 300 for behaviour until midnight): bq/half_noharm forces it on
    if v != "1" and not (lane == "fix" and FIX_SMALL) and not os.path.exists("/data/USER/st/bq/half_noharm"):  # 13 Nov: bq/fix_small halves the fix lane's no-harm legs whatever the pilots
        try:
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
            import pilotd
            if len(pilotd.alive_pilots()) >= FF_PILOTS:
                return False
        except Exception:  # noqa: BLE001
            return False
    old = LH_BIG
    LH_BIG = max(500, LH_BIG // 2) if LH_BIG else LH_BIG
    if LH_BIG and not os.environ.get("LH_MIN"):  # the h2h completeness floor follows the smaller BIG (else a 1,000-map read is 'short')
        LH_MIN = int(0.79 * ((105 if os.environ.get("BIGSET") in ("ladderw_nh", "big2") else 636) + LH_BIG))
    PANEL_N_SC[0] = 300
    if not os.environ.get("SC_PANEL_WAIT"):  # 12 Nov (TB: pet1/pet3/pet14/cwe1is lost their fresh reads at 20-41 of 69 jobs to the 45-min wait at 13 pilots)
        PANEL_WAIT = 2 * PANEL_WAIT
    say(f"HALF NO-HARM (owner 12 Nov, pilots short): BIG {old} -> {LH_BIG} maps, panel 600 -> 300 maps a spar, panel wait {PANEL_WAIT // 60} min; default sizes once pilots recover")
    return True


def fresh_first_screen(cand, live, rtag, tag, lane, env, procs, base):
    """-> None (go on: the full check adopts the screen's fresh read via --reuse-fresh auto) or the FAIL text (the check ends here)."""
    if not fresh_first_on(lane):
        return None
    n = fresh_n_decides()
    ft = f"{rtag}ff"
    say(f"FRESH-FIRST (owner 12 Nov, pilots short): {n} fresh maps alone first (tag {ft}); below {FRESH_MIN} the check ends FAIL "
        f"(sequential look 1 stops at LOS < 50%); otherwise BIG, panel and the other legs start and reuse this read")
    p = launch("fresh-first screen (stylepanel --fresh-only --keep-maps)",
               f"nice -n 10 python3 -I tools/lab/stylepanel.py {cand} {live} {ft} --n {n} --fresh-only --keep-maps --fresh-min {FRESH_MIN} "
               f"--par {PANEL_PAR} --parent {os.getpid()}", env, os.path.join(Q, f"sc_{tag}_ff.log"))
    try:
        p.wait(timeout=PANEL_WAIT + int(os.environ.get("SC_FF_EXTRA", "3600")))
    except subprocess.TimeoutExpired:
        say(f"!! fresh-first screen not done in time: stopping it, the full check plays as usual")
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass
        p.wait()
        return None
    txt = read(os.path.join(Q, f"sp{ft}.txt"))
    q = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    if not q or int(q.group(4)) < int(0.9 * n):
        say(f"fresh-first screen: {'no result' if not q else q.group(4) + ' of ' + str(n) + ' maps'}: the full check plays as usual")
        return None
    pt, lo, hi, nn = float(q.group(1)), float(q.group(2)), float(q.group(3)), int(q.group(4))
    if pt >= float(FRESH_MIN):
        say(f"fresh-first screen: {pt:.4f} [{lo:.3f}, {hi:.3f}] n {nn} >= {FRESH_MIN}: the full check starts and adopts this read")
        return None
    for k, pr in list(procs.items()):  # legs launched before the screen (ubaudit, trigger legs)
        if pr.poll() is None:
            try:
                os.killpg(pr.pid, signal.SIGTERM)
            except OSError:
                pass
    return (f"SHIPCHECK {tag}: {cand} on {base}, lane {lane}: FRESH-FIRST screen (owner 12 Nov, pilots short)\n"
            f"  fresh maps           CAND vs LIVE {pt:.4f} [{lo:.3f}, {hi:.3f}] over {nn} maps (tag {ft}) "
            f"pt >= {FRESH_MIN} at look 1 (LOS < 50% stops)  FAIL\n"
            f"  BIG, panel, info legs  not played (fresh-first: they play only after the fresh read)\n  OVERALL: FAIL")


def seq_bar():
    """[(n, z), ...] of the deciding set, or None: today's bars decide."""
    c = seq_conf()
    return list(zip(c["looks"], c["sets"][c["decide"]][0])) if c.get("decide") else None


def seq_bar_text(k):
    c = seq_conf()
    z, stop = c["sets"][c["decide"]]
    sv = stop[1][min(k, len(stop[1]) - 1)] if isinstance(stop[1], list) else stop[1]
    stops = f", stop at pt<={sv:g}" if stop[0] == "point" else f", stop at LOS<{sv:.0%}"
    return f"{c['decide']} look {k + 1}/{len(z)}: z>={z[k]:g}, fresh>.500" + ("" if k == len(z) - 1 else stops)


def seq_los(pt, se):
    return 0.5 * (1 + math.erf((pt - 0.5) / max(se, 1e-9) / math.sqrt(2)))


def seq_decide(pt, se, z_bar, last, fresh_pt, stop=None, k=0):
    """One look. PASS: z clears the bar and the fresh maps alone are above .500 (the owner's second-set rule). FAIL: the last look missed, or an earlier look hit the binding stop
    (("point", P): point <= P; ("los", L): LOS < L; default the deciding set's). EXT otherwise, also when z clears but fresh alone doesn't: BIG-strong / fresh-weak gets more fresh maps, not a ship."""
    stop = stop or seq_conf()["sets"][seq_conf()["decide"]][1]
    if (pt - 0.5) / max(se, 1e-9) >= z_bar and fresh_pt > 0.5:
        return "PASS"
    if last:
        return "FAIL"
    sv = stop[1][min(k, len(stop[1]) - 1)] if isinstance(stop[1], list) else stop[1]  # per-look stop (seq_parse)
    return "FAIL" if (pt <= sv if stop[0] == "point" else seq_los(pt, se) < sv) else "EXT"


def seq_today(pt, se):
    """Today's pooled row at look 1 (POOLED DECIDES): PASS, NEAR (the near-miss extension's band) or FAIL."""
    los = seq_los(pt, se)
    return "FAIL" if pt < POOL_PT or los < 0.70 else "PASS" if los >= POOL_LOS else "NEAR"


def seq_pool(reads):
    """Map-weighted pooling of independent (point, se, n) reads -> (point, se, n)."""
    n = sum(r[2] for r in reads)
    return sum(r[0] * r[2] for r in reads) / n, math.sqrt(sum((r[2] * r[1]) ** 2 for r in reads)) / n, n


def seq_chunk(cand, live, tag, n, base):
    """One extension chunk, on new maps never saved, no replays: stylepanel --fresh-only under a global slot, resumed once if short. -> ({map: score}, {map: labels}), empty if under 95% returned (stylepanel's completeness rule)."""
    import stylepanel
    while True:
        for k in range(SEQ_PAR):
            slot = open(os.path.join(Q, f".seqchunk_{k}.lock"), "a")
            try:
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                slot.close()
        else:
            time.sleep(15)
            continue
        break
    env = {k: v for k, v in os.environ.items() if k != "SP_KEEP"}
    env.update(SP_KIND_Z="99", SP_PRIO=SEQ_PRIO, SP_STALL=SEQ_STALL)  # kinds never start another set here: seq_kinds reads them over all the fresh maps
    meta, got = f"/data/USER/st/panel/{tag}/otf.json", {}
    try:
        for extra in ([], ["--resume"]):
            legs = ["--panel", SEQ_SPAR["spar"]] if SEQ_SPAR else ["--fresh-only"]  # SEQ_SPAR: the failed spar re-read on this chunk's maps
            with open(os.path.join(Q, f"sc_{base}_seq.log"), "a") as lg:
                p = subprocess.Popen(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, tag, "--n", str(n),
                                      *legs, "--par", "8", "--parent", str(os.getpid()), *extra], cwd=REPO, stdout=lg, stderr=subprocess.STDOUT, env=env)
                try:
                    p.wait(timeout=SEQ_WAIT)
                except subprocess.TimeoutExpired:
                    p.terminate()  # its SIGTERM handler stops the condab leg and writes a partial read
                    p.wait()
            got = stylepanel.map_score(f"fp{tag}", cand)
            want = len(json.load(open(meta))["maps"]) if os.path.exists(meta) else n
            if len(got) >= 0.95 * want:
                break
            say(f"sequential read: chunk {tag} has {len(got)} of {want} maps" + ("" if extra else ": resuming once"))
        else:
            got = {}
    finally:
        slot.close()
    lab = {m["name"]: m.get("labels", {}) for m in json.load(open(meta))["maps"]} if got else {}
    if SEQ_SPAR and got:
        m = re.search(r"^PANEL: \w+\s+pooled D ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\] over (\d+) maps", read(os.path.join(Q, f"sp{tag}.txt")), re.M)
        if m:
            SEQ_SPAR["reads"].append((float(m.group(1)), (float(m.group(3)) - float(m.group(2))) / 3.92, int(m.group(4))))
        else:
            SEQ_SPAR["missing"] = SEQ_SPAR.get("missing", 0) + 1
    return got, lab


def seq_play(cand, live, tag, look, need):
    """need more new maps, in chunks -> ({map: score}, {map: labels}). A test replaces this function."""
    import concurrent.futures
    sizes = [SEQ_CHUNK] * (need // SEQ_CHUNK) + ([need % SEQ_CHUNK] if need % SEQ_CHUNK else [])
    got, lab = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=SEQ_PAR) as ex:
        for g, l in ex.map(lambda x: seq_chunk(cand, live, f"{tag}q{look}x{x[0]}", x[1], tag), enumerate(sizes)):
            got.update(g)
            lab.update(l)
    return got, lab


def seq_kinds(tag, cand, ext, lab):
    """The kinds rule over every fresh map once a read has extended: stylepanel's second-read rule, first read v extension sets, at SEQ_KIND_Z. -> names of kinds that block."""
    import stylepanel
    fs1, labs = {}, dict(lab)
    for t, leg in ((tag, f"fp{tag}"), (f"{tag}_r", f"fp{tag}_r")):
        fs1.update(stylepanel.map_score(leg, cand))
        try:
            labs.update({m["name"]: m.get("labels", {}) for m in json.load(open(f"/data/USER/st/panel/{t}/otf.json"))["maps"]})
        except (OSError, ValueError):
            pass
    return [o["kind"] for o in stylepanel.second_outcomes(fs1, ext, labs, SEQ_KIND_Z) if o["blocks"]]


def seq_record(st, k, big, reads):
    """One look of one read: every set's verdict here and its final one (the first look where it passed or stopped); log it. -> the printed line."""
    c = st["conf"]
    fpt = seq_pool(reads)[0]
    pt, se, n = seq_pool(reads if FRESH_LED else [big] + reads)
    z = (pt - 0.5) / max(se, 1e-9)
    here = {}
    for name, (zs, stop) in c["sets"].items():
        here[name] = seq_decide(pt, se, zs[k], k == len(zs) - 1, fpt, stop, k)
        if st["final"].get(name, "EXT") == "EXT" and here[name] != "EXT":
            st["final"][name] = dict(verdict=here[name], look=k + 1)
    if k == 0:
        here["today"] = seq_today(pt, se)
        st["final"]["today"] = dict(verdict=here["today"], look=1)
    with open(os.path.join(Q, "seqbar_log.jsonl"), "a") as f:
        f.write(json.dumps(dict(t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), cand=st["cand"], live=st["live"], tag=st["tag"], look=k + 1, n=n, point=round(pt, 5), se=round(se, 5),
                                z=round(z, 3), fresh=round(fpt, 5), others=st["others"], verdicts=here, final=st["final"], decide=c.get("decide"), full=st.get("full", False))) + "\n")
    line = f"SEQ look {k + 1} n {n} point {pt:.4f} z {z:+.2f} fresh {fpt:.4f}: " + " | ".join(f"{a} {here[a]}" for a in sorted(here))
    st["lines"].append(line)
    say(line)
    return v_of(st, here), pt, se, n, fpt


def v_of(st, here):
    return here.get(st["conf"].get("decide"), "EXT")


def seq_first(rows, cand, live, tag, lane):
    """Look 1: log every set's verdict on the pooled read. -> the read's state, or None (no seqbar.txt, not the behaviour lane's pooled read, or no read)."""
    c = seq_conf()
    if not c or not fresh_decides(lane):
        return None
    lr = next((r for r in rows if r[0] == "live h2h"), None)
    fr = next((r for r in rows if r[0] == "fresh maps"), None)
    a = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\] n (\d+)", lr[1]) if lr else None
    b = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", fr[1]) if fr else None
    if not a or not b:
        return None
    big, first = [(float(m.group(1)), (float(m.group(3)) - float(m.group(2))) / 3.92, int(m.group(4))) for m in (a, b)]
    others = _verdict([r for r in rows if r[0] != "pooled BIG + fresh"])
    st = dict(conf=c, cand=cand, live=live, tag=tag, lane=lane, big=big, first=first, others=others, final={}, lines=[], ext={}, lab={})
    seq_record(st, 0, big, [first])
    SEQ_ST[tag] = st
    return st


def seq_looks(st, start, stop_on_decide):
    """Play looks start.. (0-based) on new maps, recording each. -> (verdict of the deciding set, point, se, n, fresh, look) or None when a look came back short (RULE TIMEOUT: never a FAIL)."""
    import stylepanel
    c = st["conf"]
    v, pt, se, n, fpt, k = "EXT", 0.0, 0.0, 0, st["first"][0], start
    for k in range(start, len(c["looks"])):
        need = c["looks"][k] - ((0 if FRESH_LED else st["big"][2]) + st["first"][2] + len(st["ext"]))
        say(f"SEQUENTIAL READ look {k + 1}/{len(c['looks'])}: {need} new maps (tag {st['tag']}q{k + 1}xN)")
        got, lab = seq_play(st["cand"], st["live"], st["tag"], k + 1, need) if need > 0 else ({}, {})
        if len(got) < 0.9 * need:
            st["lines"].append(f"SEQ look {k + 1}: {len(got)} of {need} new maps returned, read stops here")
            say(st["lines"][-1])
            with open(os.path.join(Q, "seqbar_log.jsonl"), "a") as f:
                f.write(json.dumps(dict(t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), cand=st["cand"], live=st["live"], tag=st["tag"], look=k + 1, short=[len(got), need], final=st["final"])) + "\n")
            return None
        st["ext"].update(got)
        st["lab"].update(lab)
        if st["final"].get("today", {}).get("verdict") == "NEAR":  # today's near-miss: first read + one 1,200-map set
            x0 = stylepanel.map_score(f"fp{st['tag']}q{k + 1}x0", st["cand"])
            if x0:
                m0, s0, n0 = stylepanel.ci(list(x0.values()))
                p0, se0, _ = seq_pool([st["big"], st["first"], (m0, s0, n0)])
                ok = p0 >= POOL_PT and seq_los(p0, se0) >= POOL_LOS and seq_pool([st["first"], (m0, s0, n0)])[0] >= POOL_NOHARM
                st["final"]["today"] = dict(verdict="PASS" if ok else "FAIL", look=k + 1, nearmiss=True)
        m, s, nx = stylepanel.ci(list(st["ext"].values())) if st["ext"] else (0.0, 0.0, 0)
        v, pt, se, n, fpt = seq_record(st, k, st["big"], [st["first"]] + ([(m, s, nx)] if nx else []))
        if stop_on_decide and v != "EXT":
            break
    return v, pt, se, n, fpt, k


def big2_read(rows, cand, live, rtag, lane):
    """SECOND FRESH SET FOR BIG NO-HARM (owner 11 Nov ~01:10Z, CLAUDE.md §5 'Second reads'): a behaviour candidate whose fresh row reads
    >= SC_BIG2_FRESH (.52) on >= SC_BIG2_MINN (1,140) maps and whose ONLY non-PASS row (the pooled row aside) is the BIG point row FAIL gets ONE
    second independent fresh set: 1,200 new unsaved maps (stylepanel --fresh-only: stratmaps --take, half weird, never saved, so maps the
    candidate was not picked on). Point >= .50 and CI upper >= .50 replaces the BIG point row as no-harm; every other row (fuel, deaths,
    faults, panel, the pooled sequential read) is unchanged. SC_BIG2=0 turns it off. -> the new row, or None when the rule does not apply."""
    if os.environ.get("SC_BIG2", "1") == "0" or lane != "behaviour" or RARE:
        return None
    bad = [r for r in rows if r[0] != "pooled BIG + fresh" and r[3] != "PASS"]
    if len(bad) != 1 or bad[0][0] != "live h2h" or bad[0][3] != "FAIL" or "BIG point" not in bad[0][2]:
        return None
    fr = next((r for r in rows if r[0] == "fresh maps"), None)
    m = re.search(r"CAND vs LIVE ([\d.]+) \[[\d.]+, [\d.]+\] over (\d+) maps", fr[1]) if fr else None
    if not m or float(m.group(1)) < float(os.environ.get("SC_BIG2_FRESH", "0.52")) or int(m.group(2)) < int(os.environ.get("SC_BIG2_MINN", "1140")):
        return None
    t2 = f"{rtag}b2"
    say(f"SECOND FRESH SET (owner 11 Nov ~01:10Z): fresh {m.group(1)} on {m.group(2)} maps and BIG point is the only failing row: one more "
        f"independent fresh set of {BIG2_MAPS} unsaved maps (tag {t2}); point >= .50 and CI upper >= .50 replaces the BIG point row as no-harm")
    env = dict(os.environ, SP_KIND_Z="99")
    env.setdefault("SP_PRIO", "12")
    for k in ("SUBSET", "CONDAB_STOPFILE", "STOP", "SET", "BASE_ND", "BIG", "CONFIRM"):
        env.pop(k, None)
    p = launch("second fresh set (stylepanel --fresh-only)", f"nice -n 10 python3 -I tools/lab/stylepanel.py {cand} {live} {t2} --n {BIG2_MAPS} "
               f"--fresh-only --par {PANEL_PAR} --parent {os.getpid()}", env, os.path.join(Q, f"sc_{t2}_sp.log"))
    try:
        p.wait(timeout=CONFIRM_WAIT)
    except subprocess.TimeoutExpired:
        say(f"!! second fresh set not done after {CONFIRM_WAIT // 60} min: stopping it (pid {p.pid})")
        os.killpg(p.pid, signal.SIGTERM)
        p.wait()
    txt = read(os.path.join(Q, f"sp{t2}.txt"))
    q = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    bar = "pt>=.50, up>=.50 (owner 11 Nov: replaces the BIG point row as no-harm)"
    if not q:
        return ("BIG no-harm, 2nd fresh", "no result (second fresh set did not finish)", bar, "INCONCLUSIVE")
    pt, lo, hi, nn = float(q.group(1)), float(q.group(2)), float(q.group(3)), int(q.group(4))
    v = "INCONCLUSIVE" if nn < int(0.9 * BIG2_MAPS) else "PASS" if pt >= 0.5 and hi >= 0.5 else "FAIL"
    return ("BIG no-harm, 2nd fresh", f"{pt:.4f} [{lo:.3f}, {hi:.3f}] n {nn} (new unsaved maps v live, half weird; tag {t2})", bar, v)


def seq_extend(rows, overall, cand, live, tag, lane):
    """SEQUENTIAL POOLED READ with a deciding set (behaviour lane; owner 3 Nov: 'allow smaller changes as long as it is just positive; test them more so it is not a statistical anomaly').
    The first look is pooled_row's. A look that neither passes nor stops plays new maps up to the next look's n, on CAND v the same base, then decides on BIG + all fresh pooled.
    Any other row that isn't PASS ends it first: FAIL fails now, INCONCLUSIVE stays INCONCLUSIVE (the usual one re-arm). An extension short of its maps reads INCONCLUSIVE, never FAIL
    (RULE TIMEOUT). A live that moves meanwhile is handled at submit (reread_requeue), and the re-read starts again at look 1. While it extends, the check holds no shipwatch or armq slot."""
    row = next((r for r in rows if r[0] == "pooled BIG + fresh" and r[3] == "EXT"), None)
    if row is None:
        return rows, overall
    others = [r for r in rows if r is not row]

    def out(*new):
        rr = [x for r in rows for x in (new if r is row else (r,))]
        return rr, _verdict(rr)

    ov = _verdict(others)
    spr = seq_spar_start(others) if ov != "PASS" else None
    if ov != "PASS" and spr is None:
        return out((row[0], f"{row[1]}; not extended: another row is {ov}", row[2], "INCONCLUSIVE"))
    st = SEQ_ST.get(tag) or seq_first(rows, cand, live, tag, lane)
    mark = os.path.join(Q, f"seqext_{cand}")
    try:
        open(mark, "w").write(f"{os.getpid()} {tag}\n")
        res = seq_looks(st, 1, True)
    finally:
        try:
            os.remove(mark)
        except OSError:
            pass
    if res is None:
        return out((row[0], f"{st['lines'][-1]}; first look {row[1]}", row[2], "INCONCLUSIVE"))
    v, pt, se, n, fpt, k = res
    if spr is not None:
        return seq_spar_finish(rows, row, spr, st, v, pt, se, n, fpt, k)
    big_n = 0 if FRESH_LED else st["big"][2]
    val = f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n} (" + ("FRESH-LED: fresh" if FRESH_LED else f"BIG {big_n} + fresh") + f" {n - big_n}) z {(pt - 0.5) / max(se, 1e-9):+.2f}; first look {row[1]}"
    new = [(row[0], val, seq_bar_text(k), v)]
    if v == "PASS":
        new.append(("fresh alone", f"{fpt:.4f} n {n - big_n}", "> .500 (second set)", "PASS"))
        blocked = seq_kinds(tag, cand, st["ext"], st["lab"])
        new.append(("kinds, all fresh", "none negative on two reads" if not blocked else "negative on two reads: " + ", ".join(blocked), f"no kind z<=-{SEQ_KIND_Z:g} on both", "FAIL" if blocked else "PASS"))
        if FRESH_LED:
            new.append(std_half_row(tag, st))
    return out(*new)


def std_half_row(tag, st):
    """FRESH-LED (owner 11 Nov): the std (non-weird) half of all the fresh maps: point >= BIG_NH_PT (no-harm). First read from its sp file's
    'pool std' line, the extension maps from their labels."""
    m = re.search(r"^\s+pool\s+std\s+n\s+(\d+)\s+([\d.]+)", read(os.path.join(Q, f"sp{tag}.txt")), re.M)
    n0, p0 = (int(m.group(1)), float(m.group(2))) if m else (0, 0.0)
    xs = [v for mp, v in st["ext"].items() if (st["lab"].get(mp) or {}).get("pool") == "std"]
    n = n0 + len(xs)
    if n == 0:
        return ("fresh std half", "no std maps labelled", f"point >= {BIG_NH_PT}", "INCONCLUSIVE")
    pt = (n0 * p0 + sum(xs)) / n
    return ("fresh std half", f"{pt:.4f} n {n} (first read {n0} + extension {len(xs)})", f"point >= {BIG_NH_PT} (no-harm; FRESH-LED)", "PASS" if pt >= BIG_NH_PT else "FAIL")


def seq_spar_start(others):
    """Marker SEQ_SPAR=1 (owner 3 Nov via the Builder, MH only): the single-spar second read is the only other failing row and its CI includes 0 -> that row; the
    sequential read then extends anyway, the spar re-read on every extension chunk's maps. Anything else -> None (today's rule: no extension)."""
    if os.environ.get("SEQ_SPAR") != "1":
        return None
    bad = [r for r in others if r[3] != "PASS"]
    if len(bad) != 1 or bad[0][0] != "playstyle panel" or bad[0][3] != "FAIL":
        return None
    m = re.match(r"second read vs (\S+) ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\] n (\d+)", bad[0][1])
    if not m or not float(m.group(3)) <= 0 <= float(m.group(4)):
        return None
    SEQ_SPAR.update(spar="nova_spar_" + m.group(1), reads=[(float(m.group(2)), (float(m.group(4)) - float(m.group(3))) / 3.92, int(m.group(5)))])
    say(f"SEQ_SPAR: {bad[0][0]} failed alone with 0 inside its CI ({bad[0][1][:60]}): the sequential read extends; {SEQ_SPAR['spar']} plays on every chunk")
    return bad[0]


def seq_spar_finish(rows, row, spr, st, v, pt, se, n, fpt, k):
    """SEQ_SPAR's end: the deciding set's verdict, and the spar pooled over its second read and every chunk's read: point >= 0 and CI upper >= 0, else FAIL."""
    d, dse, dn = seq_pool(SEQ_SPAR["reads"])
    ok = d >= 0 and d + 1.96 * dse >= 0 and not SEQ_SPAR.get("missing")
    spar_row = ("playstyle panel", f"SEQ_SPAR {SEQ_SPAR['spar'][10:]} pooled {d:+.4f} [{d - 1.96 * dse:+.4f}, {d + 1.96 * dse:+.4f}] n {dn} over {len(SEQ_SPAR['reads'])} reads"
                + (f"; {SEQ_SPAR['missing']} chunk(s) gave no spar read" if SEQ_SPAR.get("missing") else "") + f"; first: {spr[1][:60]}",
                "SEQ_SPAR: point >= 0 and CI upper >= 0 at the last look", "PASS" if ok else "FAIL")
    big_n = 0 if FRESH_LED else st["big"][2]
    val = f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n} (" + ("FRESH-LED: fresh" if FRESH_LED else f"BIG {big_n} + fresh") + f" {n - big_n}) z {(pt - 0.5) / max(se, 1e-9):+.2f}; first look {row[1]}"
    new = [(row[0], val, seq_bar_text(k), v)]
    if v == "PASS":
        new.append(("fresh alone", f"{fpt:.4f} n {n - big_n}", "> .500 (second set)", "PASS"))
        blocked = seq_kinds(st["tag"], st["cand"], st["ext"], st["lab"])
        new.append(("kinds, all fresh", "none negative on two reads" if not blocked else "negative on two reads: " + ", ".join(blocked), f"no kind z<=-{SEQ_KIND_Z:g} on both", "FAIL" if blocked else "PASS"))
    rr = []
    for r in rows:
        if r is row:
            rr += new
        elif r is spr:
            rr.append(spar_row)
        else:
            rr.append(r)
    st["lines"].append(f"SEQ_SPAR final: {spar_row[1]} -> {spar_row[3]}")
    return rr, _verdict(rr)


def seq_shadow_take():
    """One of shadow_full's N: rewrites seqbar.txt with N - 1 under a lock. -> True if taken."""
    with open(os.path.join(Q, ".seqbar.lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            n = seq_parse(SEQBAR).get("shadow", 0)
        except (ValueError, IndexError):
            return False
        if n <= 0:
            return False
        tmp = f"{SEQBAR}.new.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(re.sub(r"^(\s*shadow_full\s+)\d+", lambda m: f"{m.group(1)}{n - 1}", read(SEQBAR), flags=re.M))
        os.replace(tmp, SEQBAR)
    return True


def seq_shadow_start(st):
    """shadow_full: the rest of the looks, in a detached process: the ship decision never waits for it, and it plays on whatever this check's verdict was."""
    if not st or not seq_shadow_take():
        return
    sf = os.path.join(Q, f"seqshadow_{st['tag']}.json")
    json.dump({k: st[k] for k in ("cand", "live", "tag", "lane", "big", "first", "others", "final")}, open(sf, "w"))
    subprocess.Popen(["nohup", "nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/shipcheck.py"), "--seqshadow", st["tag"]], cwd=REPO,
                     stdout=open(os.path.join(Q, f"seqshadow_{st['tag']}.log"), "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    say(f"shadow_full: every look of this read plays on detached (seqshadow_{st['tag']}.log; seqbar_log.jsonl)")


def seq_shadow_main(tag):
    """shipcheck.py --seqshadow TAG: play every look not yet played; verdicts go to seqbar_log.jsonl and seqshadow_TAG.txt only."""
    import stylepanel
    global SEQ_PRIO, SEQ_STALL, SEQ_WAIT
    SEQ_PRIO, SEQ_STALL, SEQ_WAIT = os.environ.get("SC_SEQ_SHADOW_PRIO", "5"), "3600", 12 * 3600  # evidence, not a ship: behind everything, and it may queue for hours
    st = json.load(open(os.path.join(Q, f"seqshadow_{tag}.json")))
    st.update(conf=seq_conf(), full=True, lines=[], ext={}, lab={}, big=tuple(st["big"]), first=tuple(st["first"]))
    played = 1
    for f in glob.glob(os.path.join(Q, f"fp{tag}q*x*.condor.txt")):  # looks a deciding set already played
        leg = os.path.basename(f)[:-len(".condor.txt")]
        st["ext"].update(stylepanel.map_score(leg, st["cand"]))
        try:
            st["lab"].update({m["name"]: m.get("labels", {}) for m in json.load(open(f"/data/USER/st/panel/{leg[2:]}/otf.json"))["maps"]})
        except (OSError, ValueError):
            pass
        played = max(played, int(re.search(rf"fp{re.escape(tag)}q(\d+)x", leg).group(1)))
    if not st["conf"]:
        sys.exit(f"{SEQBAR} missing: no shadow read")
    res = seq_looks(st, played, False)
    blocked = seq_kinds(tag, st["cand"], st["ext"], st["lab"]) if st["ext"] else []
    st["lines"].append(f"finals: {json.dumps(st['final'])}; kinds negative on two reads over all fresh: {', '.join(blocked) or 'none'}" + ("" if res else "; read stopped short"))
    open(os.path.join(Q, f"seqshadow_{tag}.txt"), "w").write(f"{st['cand']} v {st['live']} tag {tag}\n" + "\n".join(st["lines"]) + "\n")
    say(st["lines"][-1])


NEARMISS = os.path.join(Q, "nearmiss_ext")  # 1 = on (owner 3 Nov: "if a ship falls short with some confidence, do more unsaved unseen map testing")
NEARMISS_N = int(os.environ.get("SC_NEARMISS_N", 1200))


def fix_careful(rows, overall, lane):
    """13 Nov (owner: "For bugs be more careful"): a fix-lane line (bug bar, plain fix, Q1 fuel cut; NOT a RARE line, NOT an IDENT ship) that
    PASSES must also show LOS >= FIX_LOS (0.80) on its deciding fresh read ('confirm fresh', else 'pooled BIG + fresh', else 'fresh maps'), so a
    point a hair over .50 inside a wide CI no longer ships a bug fix. While bq/fix_careful exists."""
    if lane != "fix" or RARE or overall != "PASS" or not os.path.exists(os.path.join(Q, "fix_careful")):
        return rows, overall
    los_bar = float(os.environ.get("FIX_LOS", "0.80"))
    for name in ("confirm fresh", "pooled BIG + fresh", "fresh maps"):
        r = next((x for x in rows if x[0] == name), None)
        m = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\]", r[1]) if r else None
        if not m:
            continue
        pt, lo, hi = float(m.group(1)), float(m.group(2)), float(m.group(3))
        se = max(1e-9, (hi - lo) / 3.92)
        los = 0.5 * (1 + math.erf((pt - 0.5) / se / math.sqrt(2)))
        rows.append(("fix careful (LOS)", f"{name}: point {pt:.4f} [{lo:.3f}, {hi:.3f}] LOS {100 * los:.0f}%",
                     f"LOS >= {100 * los_bar:.0f}% (owner 13 Nov: 'For bugs be more careful')", "PASS" if los >= los_bar else "FAIL"))
        return rows, _verdict(rows)
    return rows, overall


def class_noharm(rows, overall, cand, live, tag):
    """13 Nov (owner, typed to the Builder: "make a generator for those types and only run on those types with no harm on the rest of the test
    set"): a CLASS rare line (RARE + SP_CLASS) that PASSED on its class maps also plays SC_CLASS_NH_N (1,000) NEW general fresh maps
    (stylepanel --fresh-only, tag TAGnh) and must show no harm there: point >= .495 and CI upper >= .50 (the BIG no-harm rule). Only while
    bq/class_noharm exists."""
    if not (RARE and os.environ.get("SP_CLASS", "").strip() and overall == "PASS" and os.path.exists(os.path.join(Q, "class_noharm"))):
        return rows, overall
    nt, n = f"{tag}nh", int(os.environ.get("SC_CLASS_NH_N", "1000"))
    say(f"CLASS NO-HARM (owner 13 Nov): {n} new general fresh maps ({nt}) after the class PASS")
    try:
        subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, nt, "--n", str(n),
                        "--fresh-only", "--par", "8", "--parent", str(os.getpid())], cwd=REPO, capture_output=True, text=True,
                       env={k: v for k, v in dict(os.environ, SP_FRESH_NEW="1").items() if k not in ("SP_CLASS", "SP_CLASS_TAG")}, timeout=5400)
    except subprocess.TimeoutExpired:
        pass
    q = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", read(os.path.join(Q, f"sp{nt}.txt")), re.M)
    bar = "point >= 0.495 and CI upper >= .50 (owner 13 Nov: no harm on the rest of the test set)"
    if not q or int(q.group(4)) < int(0.9 * n):
        rows.append(("class no-harm fresh", f"no result ({nt})", bar, "INCONCLUSIVE"))
    else:
        pt, lo, hi, nn = float(q.group(1)), float(q.group(2)), float(q.group(3)), int(q.group(4))
        rows.append(("class no-harm fresh", f"CAND vs LIVE {pt:.4f} [{lo:.3f}, {hi:.3f}] over {nn} general fresh maps ({nt})", bar,
                     "PASS" if pt >= 0.495 and hi >= 0.50 else "FAIL"))
    return rows, _verdict(rows)


def _verdict(rows):
    res = [r[3] for r in rows]
    return "FAIL" if "FAIL" in res else "VACUOUS" if "VACUOUS" in res else "INCONCLUSIVE" if "INCONCLUSIVE" in res else "PASS"


def lh_nearmiss(val, bar, lane):
    """A FAILED live h2h row the near-miss extension would take (fix lanes: point at most .005 under its 'point >= X' bar, CI upper
    >= .50, BQ/nearmiss_ext on): its other legs must not be stopped early, since the extension pools this check's fresh read."""
    a = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\]", val or "")
    pb = re.search(r"point >= ([\d.]+)", bar or "")
    return bool(lane.startswith("fix") and read(NEARMISS).strip() == "1" and a and pb
                and float(pb.group(1)) - 0.005 <= float(a.group(1)) < float(pb.group(1)) and float(a.group(3)) >= 0.5)


def nearmiss_ext(rows, overall, cand, live, tag, lane):
    """NEAR-MISS EXTENSION (owner 3 Nov via the Builder), once per shipcheck, when BQ/nearmiss_ext holds 1 and the only failing row is:
    behaviour lane: 'pooled BIG + fresh' at point >= POOL_PT with LOS in [70%, 90%); fix lanes: 'live h2h' with its point at most .005 under
    its bar and CI upper >= .50. Then one more set of NEARMISS_N new per-run maps (stratmaps via stylepanel --fresh-only, half pathological),
    CAND v the same base, and the same bar re-decides on BIG + every fresh map pooled. Logged in fresh_second_reads.jsonl (kind nearmiss_ext).
    A live that moves meanwhile is handled at submit (reread_requeue)."""
    if overall != "FAIL" or read(NEARMISS).strip() != "1" or (fresh_decides(lane) and seq_bar()):  # seqbar.txt replaces it on the behaviour lane
        return rows, overall
    bad = [r for r in rows if r[3] == "FAIL"]
    if len(bad) != 1:
        return rows, overall
    lr = next((r for r in rows if r[0] == "live h2h"), None)
    fr = next((r for r in rows if r[0] == "fresh maps"), None)
    a = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\] n (\d+)", lr[1]) if lr else None
    b = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", fr[1]) if fr else None
    if not a:
        return rows, overall
    reads = [(float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))) for m in (a, b) if m]
    if bad[0][0] == "pooled BIG + fresh" and fresh_decides(lane):
        m = re.search(r"^([\d.]+) .*LOS (\d+)%", bad[0][1])
        if not m or float(m.group(1)) < POOL_PT or not 70 <= int(m.group(2)) < 90:
            return rows, overall
        pbar = None
    elif bad[0][0] == "live h2h" and lane.startswith("fix"):
        pb = re.search(r"point >= ([\d.]+)", bad[0][2])
        if not pb or not float(pb.group(1)) - 0.005 <= reads[0][0] < float(pb.group(1)) or reads[0][2] < 0.5:
            return rows, overall
        pbar = float(pb.group(1))
    else:
        return rows, overall
    xt = f"{tag}x"
    say(f"NEAR-MISS EXTENSION: {bad[0][0]} {bad[0][1][:60]}: one more set of {NEARMISS_N} new maps ({xt})")
    try:
        subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, xt, "--n", str(NEARMISS_N),
                        "--fresh-only", "--par", "8", "--parent", str(os.getpid())], cwd=REPO, capture_output=True, text=True,
                       env=dict(os.environ, SP_KIND_Z="99", SP_FRESH_NEW="1"), timeout=3600)  # one extension only: kinds never start another set; a retest: new maps
    except subprocess.TimeoutExpired:
        pass
    m = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", read(os.path.join(Q, f"sp{xt}.txt")))
    ext = (float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))) if m and int(m.group(4)) >= 0.9 * NEARMISS_N else None
    if not ext:
        val, v = f"extension {xt} gave no full read ({m.group(4) if m else 0} of {NEARMISS_N} maps); first {bad[0][1][:50]}", "FAIL"
        pt = los = None
    else:
        allr = reads + [ext]
        n = sum(r[3] for r in allr)
        pt = sum(r[0] * r[3] for r in allr) / n
        se = math.sqrt(sum((r[3] * (r[2] - r[1]) / 3.92) ** 2 for r in allr)) / n
        los = 0.5 * (1 + math.erf((pt - 0.5) / max(se, 1e-9) / math.sqrt(2)))
        fr2 = [r for r in allr[1:]]
        fpt = sum(r[0] * r[3] for r in fr2) / sum(r[3] for r in fr2)
        if pbar is None:
            v = "PASS" if pt >= POOL_PT and los >= POOL_LOS and fpt >= POOL_NOHARM else "FAIL"
            bar = f"pt>={POOL_PT}, LOS>={POOL_LOS:.0%}, fresh pooled >= {POOL_NOHARM}"
        else:
            v = "PASS" if pt >= pbar and pt + 1.96 * se >= 0.5 else "FAIL"
            bar = f"point >= {pbar}, CI upper >= 0.5 (BIG + fresh pooled)"
        val = (f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n} LOS {100 * los:.0f}% (BIG + {sum(r[3] for r in fr2)} fresh incl. extension "
               f"{ext[0]:.3f} n {ext[3]}); first {bad[0][1][:40]}")
    with open(os.path.join(Q, "fresh_second_reads.jsonl"), "a") as f:
        f.write(json.dumps(dict(kind="nearmiss_ext", t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tag=tag, cand=cand, live=live, lane=lane,
                                first=bad[0][1], ext=ext, pooled=pt, los=los, passed=v == "PASS")) + "\n")
    rows = [(bad[0][0] + " (near-miss ext)", val, bar if ext else bad[0][2], v) if r is bad[0] else r for r in rows]
    return rows, _verdict(rows)


def bugbar_fuel_row(rows, overall, lane):
    """Owner 12 Nov (user, ~12:0xZ: "with bug fixes if they increase fuel be more strict with them as some may have worsened the bot"): a BUGBAR
    line whose capped fuel cut-offs RISE (cap5 CAND > LIVE with z >= SC_BUGBAR_FUEL_Z, 1.0) loses the bug bar's .4975 / within-variance
    allowances: its deciding read (fresh decides / confirm fresh) and its BIG live h2h, when present, need point >= .50 (CI upper >= .50 as before).
    Fuel flat or down: unchanged. SC_BUGBAR_FUEL_STRICT=0 turns the row off."""
    if os.environ.get("BUGBAR") != "1" or lane != "fix" or os.environ.get("SC_BUGBAR_FUEL_STRICT", "1") == "0":
        return rows, overall
    fu = next((r for r in rows if r[0] == "fuel exhaustions"), None)
    m = re.search(r"cap5 (\d+) vs (\d+) \(([\d.]+)x, z ([+-]?[\d.]+)", fu[1]) if fu else None
    zmin = float(os.environ.get("SC_BUGBAR_FUEL_Z", "1.0"))
    if not m or not (int(m.group(1)) > int(m.group(2)) and float(m.group(4)) >= zmin):
        return rows, overall
    bad, got = [], []
    for name in ("fresh decides (fix)", "confirm fresh", "live h2h"):
        r = next((x for x in rows if x[0] == name), None)
        pm = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\]", r[1]) if r else None
        if pm:
            got.append(f"{name} {float(pm.group(1)):.4f}")
            if float(pm.group(1)) < 0.50:
                bad.append(name)
    v = "FAIL" if bad else "PASS"
    rows = rows + [("bug bar, fuel up", f"cap5 {m.group(1)} v {m.group(2)} ({m.group(3)}x, z {m.group(4)}): " + "; ".join(got),
                    "fuel up on a bug-bar line: deciding read and BIG h2h point >= .50 (owner 12 Nov)", v)]
    res = [r[3] for r in rows]
    return rows, "FAIL" if "FAIL" in res else overall


def param_row(rows, overall, lane, final=True):
    """Marker PARAMBAR=1, behaviour or draft lane (b846's parameters; Builder 2 Nov; draft lane 12 Nov: its draft-changed maps): CLAUDE.md's parameter bar on top of every lane bar: the fresh read at n >= 1,140 of 1,200, point >= 0.5025 (owner 11 Nov, was 0.505), LOS >= 90%."""
    if os.environ.get("PARAMBAR") != "1":
        return rows, overall
    if lane == "draft":  # 12 Nov (Builder, RC C634): a draft parameter is judged on the draft-changed maps it plays
        fr = next((r for r in rows if r[0] == "draft changed maps"), None)
        m = re.search(r"^([\d.]+) \[([\d.]+), ([\d.]+)\] n (\d+)/", fr[1]) if fr else None
        what = "draft-changed"
    else:
        fr = next((r for r in rows if r[0] == "fresh maps"), None)
        m = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", fr[1]) if fr else None
        what = "fresh"
    if not m:
        v, val = "INCONCLUSIVE", f"no {what} read"
    else:
        pt, hi, n = float(m.group(1)), float(m.group(3)), int(m.group(4))
        se = max((hi - pt) / 1.96, 1e-9)
        los = 0.5 * (1 + math.erf((pt - 0.5) / se / math.sqrt(2)))
        v, val = ("PASS" if n >= 1140 and pt >= PM_POINT and los >= 0.90 else "FAIL"), f"{what} {pt:.3f} n {n} LOS {100 * los:.0f}%"  # owner 11 Nov: .5025 (was .505)
        # 13 Nov (OWNER via the Coordinator, gujl9 14566): the parameter bar's LOS row applies at the LAST look only: before the sequential looks a
        # LOS-only miss (n and point met) is EXT, so the read goes on; the row is judged again (final=True) after the looks
        if not final and v == "FAIL" and n >= 1140 and pt >= PM_POINT and lane == "behaviour":
            v, val = "EXT", val + " (LOS judged at the last look)"
    rows = [r for r in rows if r[0] != "parameter bar"] + [("parameter bar", val, f"n>=1140, pt>={PM_POINT:g}, LOS>=90%", v)]
    res = [r[3] for r in rows]
    return rows, "FAIL" if "FAIL" in res else "VACUOUS" if "VACUOUS" in res else "INCONCLUSIVE" if "INCONCLUSIVE" in res else "PASS"


def own_flip_text(cand, livevals):
    fi = flip_info(cand) or {}
    own = shipstack.own_flips(shipstack.parse_flips(fi.get("FLIPS", "")), shipstack.parse_flips(livevals))
    return " ".join(f"{k}={v}" for k, v in sorted(own.items()))


PENDING = os.path.join(Q, "pending_reads.txt")
def trunk_base_version(trunk):
    """9 Nov (v649 cgm2b shipped from a v647-based trunk over v648): the baked base a private trunk was merged onto, from trunk_registry.md
    ('- nova_ptk_X (...): nova_base_vNNN + ...'), as an int, or None when not recorded"""
    try:
        for ln in open("/homes/USER/condor-work/reports/trunk_registry.md", errors="replace"):
            if ln.startswith(f"- {trunk} "):
                m = re.search(r"\):\s*nova_base_v(\d+)\b", ln)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


LIVE_MOVED = []  # submit(): the live bot when a PASS was refused because live moved on (parallel mode re-read)
REARMS = os.path.join(Q, "inconc_rearms.jsonl")


def armed_donors(cand):
    """The donors the armed line of CAND carried (armq's armed_donors.jsonl; 5 Nov, px3) -> 'DONOR:BASE[,...]' or '-'."""
    donors = "-"
    try:
        for ln in open(os.path.join(Q, "armed_donors.jsonl")):
            d = json.loads(ln)
            if d.get("bot") == cand:
                donors = d.get("donors") or "-"
    except (OSError, ValueError):
        pass
    return donors


def reread_requeue(cand, lane, livevals, tag, old, new):
    """Parallel mode (Builder 3 Nov): a PASS read against a live that a sibling replaced before the submit is re-read ONCE against the new live,
    at the front of the arm queue; a second time goes to pending_reads.txt."""
    lane = "ctrunk" if CTRUNK[0] else "fix" if RARE else lane  # 6 Nov (Builder: a ctrunk line's re-read ran on the fix lane): keep the line's own lane
    fl = own_flip_text(cand, livevals)
    dn = armed_donors(cand)
    key = f"reread {lane} {fl}" + (f" {dn}" if dn != "-" else "")
    seen = [json.loads(x).get("key") for x in open(REARMS) if x.strip()] if os.path.exists(REARMS) else []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # 7 Nov (owner: worry less about parallel work, keep the positives): in parallel arming a PASS is overtaken whenever a sibling ships first;
    # each overtake re-reads on the new live (the diff re-applied on the new base), up to SC_REREAD_MAX (3) times, then pending_reads.txt
    if (not fl and dn == "-") or seen.count(key) >= int(os.environ.get("SC_REREAD_MAX", "3")):
        if not DRY:
            with open(PENDING, "a") as f:
                f.write(f"PENDING: {stamp} {cand} ({lane}) PASSED v {old} but {new} went live first, "
                        f"{'not a flip candidate' if (not fl and dn == '-') else 'overtaken ' + str(seen.count(key) + 1) + ' times'}; read {Q}/shipcheck_{tag}.txt; re-arm: armq.py add {dn} \"{fl}\" {lane} "
                        f"\"SUBJECT\" --front{' --bugbar' if os.environ.get('BUGBAR') == '1' and lane == 'fix' else ''}; bar: the {lane} lane's shipcheck bars\n")
        return say(f"PASS v {old}, but {new} is live: written to {PENDING}, no re-read")
    if not DRY:
        with open(REARMS, "a") as f:
            f.write(json.dumps(dict(key=key, cand=cand, tag=tag, cause=f"live moved {old} -> {new}", t=stamp)) + "\n")
    # owner 9 Nov ~17:20Z: this requeue is a PASS refused for base, so the re-armed line gets a short CONFIRM read on the new live (marker CONFIRM_FROM
    # = the full PASS's TAG, CONFIRM_N = live moves since it). A confirm read refused again carries its own CONFIRM_FROM with CONFIRM_N + 1, at most
    # CONFIRM_MAX (2); past that the plain requeue (the full check). No other requeue (stack void, INCONCLUSIVE) ever carries it.
    if CONFIRM.get("from"):
        cn = int(CONFIRM.get("n") or 1) + 1
        cf = (CONFIRM["from"], cn) if cn <= CONFIRM_MAX else None
    else:
        cf = (tag, 1)
    say(f"PASS v {old}, but {new} went live first: re-read {seen.count(key) + 1} of {os.environ.get('SC_REREAD_MAX', '3')} against it, at the front"
        + (f"; CONFIRM MODE from TAG {cf[0]} (live move {cf[1]} of at most {CONFIRM_MAX})" if cf else f"; confirm cap {CONFIRM_MAX} reached: full check"))
    return stack_requeue(cand, lane, livevals, "r", confirm=cf)


def inconclusive_requeue(cand, lane, livevals, tag, cause):
    """Owner 3 Nov (don't lose a promising candidate to a timeout): a capacity/timeout INCONCLUSIVE goes back on the arm queue ONCE, at the front;
    the second INCONCLUSIVE of the same own flips and lane goes to pending_reads.txt for the Builder. FAIL and harness causes never re-arm."""
    lane = "ctrunk" if CTRUNK[0] else lane  # 6 Nov (Builder: a ctrunk line's re-read ran on the fix lane): keep the line's own lane
    fl = own_flip_text(cand, livevals)
    dn = armed_donors(cand)  # a donor-only line (no own flips) re-arms too: its donors carry the change
    key = f"{lane} {fl}" + (f" {dn}" if dn != "-" else "")
    seen = []
    for line in open(REARMS) if os.path.exists(REARMS) else ():
        try:
            seen.append(json.loads(line).get("key"))
        except ValueError:
            pass
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # 12 Nov (owner via the Coordinator: "never dismiss an idea before testing"; a capacity shortfall never closes a line): a CAPACITY
    # INCONCLUSIVE re-arms up to SC_CAPACITY_REARMS (3) times; any other cause keeps the one re-arm. Past the limit: pending_reads (not closed)
    # 12 Nov ~14:4xZ (owner, pilots short: "make sure not to lose any as when testing load increases we will be able to try these"):
    # capacity re-arms 3 -> 12, so a starved line keeps its place on the queue through the day instead of going to pending_reads
    limit = int(os.environ.get("SC_CAPACITY_REARMS", "12")) if str(cause).startswith("capacity") else 1
    if (not fl and dn == "-") or seen.count(key) >= limit:
        why = "no own flips or donors to re-arm (not a flip candidate)" if (not fl and dn == "-") else f"INCONCLUSIVE {seen.count(key) + 1} times (re-arm limit {limit})"
        if DRY:
            return say(f"DRY: would add to {PENDING}: {cand} {why}")
        with open(PENDING, "a") as f:
            f.write(f"PENDING: {stamp} {cand} ({lane}{', bug bar' if os.environ.get('BUGBAR') == '1' else ''}) {why}, cause {cause}; "
                    f"read {Q}/shipcheck_{tag}.txt; re-arm: armq.py add {dn} \"{fl}\" {lane} \"SUBJECT\" --front"
                    f"{' --bugbar' if os.environ.get('BUGBAR') == '1' and lane == 'fix' else ''}; bar: the {lane} lane's shipcheck bars\n")
        return say(f"INCONCLUSIVE ({cause}): {why}; written to {PENDING}, no re-arm")
    if not DRY:
        with open(REARMS, "a") as f:
            f.write(json.dumps(dict(key=key, cand=cand, tag=tag, cause=cause, t=stamp)) + "\n")
    say(f"INCONCLUSIVE ({cause}): re-arming at the front (re-arm {seen.count(key) + 1} of {limit})")
    return stack_requeue(cand, lane, livevals, "i")


BUGBAR_MAXCHG = float(os.environ.get("SC_BUGBAR_MAXCHG", "0.01"))
BUGBAR_GATE_LOG = os.path.join(Q, "bugbar_gate.log")


IDENT_MAPS = int(os.environ.get("SC_IDENT_MAPS", "100"))


def ident_ship(cand, live, lane, tag):
    """IDENT SHIP (owner 12 Nov ~14:4xZ, directly to TB: "for non behaviour change fuel cuts once verified it behaves identically feel
    free to ship it without any more testing as either neutral or improvement"). A fix-lane line marked BUGBAR or Q1BAR (or IDENTSHIP=1)
    is played CAND v LIVE by cxeident on SC_IDENT_MAPS (100) new maps x 2 seats at unlimited fuel. When EVERY game is byte-identical
    and the same-work fuel is not above live's, it is a pure fuel cut: ubaudit runs (a crash check, not a game read) and the line
    submits with no played reads. Anything else (a game differs, fuel up, pilots short, ubaudit fails) -> False: the usual check runs.
    SC_IDENT_SHIP=0 turns it off. -> True when it handled the line (submitted, or held by hold_submit)."""
    if os.environ.get("SC_IDENT_SHIP", "1") == "0" or lane != "fix" or RARE:
        return False
    if not (os.environ.get("BUGBAR") == "1" or os.environ.get("Q1BAR") == "1" or os.environ.get("IDENTSHIP") == "1"):
        return False
    subj = os.environ.get("SUBJECT", "").strip().lower()
    if not (os.environ.get("Q1BAR") == "1" or os.environ.get("IDENTSHIP") == "1" or os.environ.get("IDENT_OK") == "1" or subj.startswith("perf(")):
        # 12 Nov (Builder / RC C758: ntg1rs, stc2s, xlm31s, rare bug fixes or bundles that never fired on the identity maps, read 200/200 and
        # would have shipped unread): the owner's rule is for non-behaviour FUEL CUTS; only a fuel-cut line (Q1BAR=1, a perf(...) subject,
        # or IDENT_OK/IDENTSHIP=1) takes the identity path; any other --bugbar line reads its normal bar
        return False
    t0 = time.time()
    def run(nm, seed):
        return subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/cxe/cxeident.py"), live, cand, "--maps", str(nm),
                               "--seed", str(seed)], capture_output=True, text=True, cwd=REPO,
                              env=dict(os.environ, CXEIDENT_PILOTS_ONLY="1", PILOTCXE_PRIO="20"))
    r = run(20, int(tag) % 997 + 5)  # stage 1: 40 games; a play-changing line stops here (most bug fixes), so pilots are not spent on it
    m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", r.stdout)
    if not m or m.group(1) != m.group(2):
        say(f"IDENT SHIP: stage 1 {m.group(1) + '/' + m.group(2) if m else 'not read'} identical v {live}: the usual check runs ({time.time() - t0:.0f} s)")
        return False
    r = run(IDENT_MAPS, int(tag) % 997 + 11)
    m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", r.stdout)
    f = re.search(r"fuel, same work \(unlimited\): ([\d,]+) -> ([\d,]+) per game \(([+-][\d.]+)%\)", r.stdout)
    if not m or not f:
        say(f"IDENT SHIP: identity not read (rc {r.returncode}, pilots short?): the usual check runs ({time.time() - t0:.0f} s)")
        return False
    same, ng, pct = int(m.group(1)), int(m.group(2)), float(f.group(3))
    # 12 Nov (Coordinator / RC x693b: CTP1's cut-offs rose at 100k while identity passed): INFORMATION only, logged for every candidate:
    # capped cut-offs per game at the real 100k budget (cxeident's 'real budget' line), live -> cand, and how many games changed there.
    cut = re.search(r"fuel cut-offs ([\d.]+) -> ([\d.]+) per game \(all (\d+) games; (\d+) played differently at 100k\)", r.stdout)
    cut_txt = (f"100k cut-offs/g {cut.group(1)} -> {cut.group(2)} ({cut.group(4)}/{cut.group(3)} games changed at 100k)" if cut else "100k cut-offs not read")
    try:
        with open(os.path.join(Q, "identship.log"), "a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {tag} {cand} INFO {cut_txt} (identity {same}/{ng}, same-work fuel {pct:+.2f}%)\n")
    except OSError:
        pass
    if same != ng or ng < 2 * IDENT_MAPS * 0.9:
        say(f"IDENT SHIP: {same}/{ng} games byte-identical v {live}: not a pure fuel cut, the usual check runs")
        return False
    cut_min = float(os.environ.get("SC_IDENT_CUT_MIN", "-0.05"))
    if pct > cut_min and os.environ.get("IDENTSHIP") != "1":
        # 12 Nov (RC: NTG1, a rare bug fix that never fired on the 100x2 maps, nearly shipped unread): the owner's rule is for FUEL CUTS that
        # behave identically, so the path needs a real cut (same-work fuel <= SC_IDENT_CUT_MIN, -0.05%) or an explicit IDENTSHIP=1 marker
        say(f"IDENT SHIP: identical on {ng} games but same-work fuel {pct:+.2f}% v live is not a cut (needs <= {cut_min:+.2f}%): the usual check runs")
        return False
    # 12 Nov ~19:2xZ (TB): tsx11cs/kcv7cs/dfh1c were 200/200 identical but ubaudit's Condor job sat idle ~50 min and ended rc 2 (harness),
    # so each fell back to a full played read. The audit now has SC_IDENT_UB_WAIT (1200 s); a harness rc (2, or the wait running out)
    # takes the owner's small-subset rule instead (owner 12 Nov ~19:2xZ: "with identical fuel cutting changes you can test on a very small
    # subset as obviously not negative"): SC_IDENT_SMALL_N (300) new fresh maps v live, PASS iff CI upper >= .50 (not negative).
    # A real ubaudit FAIL (rc 1: new UB sites, traps or faults) still sends the line to the usual check.
    try:
        u = subprocess.run(["sh", os.path.join(REPO, "tools/lab/ubaudit.sh"), cand, live], capture_output=True, text=True, cwd=REPO,
                           timeout=int(os.environ.get("SC_IDENT_UB_WAIT", "1200")), env=dict(os.environ, UB_REMOTE_START=os.environ.get("UB_REMOTE_START", "180")))
        urc = u.returncode
    except subprocess.TimeoutExpired:
        urc = 2
    small = None
    # 13 Nov (OWNER "Yes, gate it", via the Coordinator, on RC's proposal): a line whose games play differently at the REAL 100k budget (cxeident's
    # 'played differently at 100k' count > 0, or that count unread) does not ship on identity alone: it takes the small fallback read
    # (SC_IDENT_SMALL_N new fresh maps v live, PASS iff CI upper >= .50). Lines identical at 100k still ship on identity.
    diff100 = (int(cut.group(4)) if cut else None)
    gate100 = diff100 is None or diff100 > 0
    if urc == 1 or urc not in (0, 2):
        say(f"IDENT SHIP: ubaudit rc {urc}: the usual check runs")
        return False
    if urc == 2 or gate100:
        sn = int(os.environ.get("SC_IDENT_SMALL_N", "300"))
        st = f"{run_tag(tag, cand, live)}is"
        why_ = ("ubaudit could not run (rc 2: harness/Condor idle)" if urc == 2 else "") + (" and " if urc == 2 and gate100 else "") + \
               (f"{'the 100k count was not read' if diff100 is None else f'{diff100} games played differently at the 100k budget'} (owner 13 Nov: gate it)" if gate100 else "")
        say(f"IDENT SHIP: {why_}: small-subset read instead, {sn} new fresh maps v live, PASS iff CI upper >= .50 (tag {st})")
        sp = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), cand, live, st, "--n", str(sn),
                             "--fresh-only", "--fresh-min", "0", "--par", str(PANEL_PAR), "--parent", str(os.getpid())],
                            capture_output=True, text=True, cwd=REPO, env=os.environ.copy())
        open(os.path.join(Q, f"sc_{tag}_is.log"), "w").write((sp.stdout or "")[-20000:] + (sp.stderr or "")[-4000:])
        qq = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", read(os.path.join(Q, f"sp{st}.txt")), re.M)
        if not qq or int(qq.group(4)) < int(0.9 * sn):
            say(f"IDENT SHIP: small-subset read {'gave no result' if not qq else 'short (' + qq.group(4) + ' maps)'}: the usual check runs")
            return False
        spt, slo, shi, snn = float(qq.group(1)), float(qq.group(2)), float(qq.group(3)), int(qq.group(4))
        if shi < 0.50:
            say(f"IDENT SHIP: small-subset read {spt:.4f} [{slo:.3f}, {shi:.3f}] n {snn}: CI upper < .50 (negative): the usual check runs")
            return False
        small = (spt, slo, shi, snn, st)
    rows = [("identity v live", f"{same}/{ng} games byte-identical at unlimited fuel ({IDENT_MAPS} new maps x 2 seats)", "all identical", "PASS"),
            ("same-work fuel", f"{f.group(1)} -> {f.group(2)} per game ({pct:+.2f}%)", "<= live (neutral or a cut)", "PASS"),
            ("ubaudit", "rc 0", "rc 0", "PASS") if not small else
            ("small subset", f"CAND vs LIVE {small[0]:.4f} [{small[1]:.3f}, {small[2]:.3f}] over {small[3]} new fresh maps (tag {small[4]}; ubaudit rc {urc}"
             + (f"; {'100k count unread' if diff100 is None else f'{diff100} games differ at 100k'}" if gate100 else "") + ")",
             "CI upper >= .50 (owner 12 Nov; 100k gate owner 13 Nov)", "PASS")]
    text = fmt(rows, "PASS", cand, live, tag, lane, time.time() - t0)
    text = text.replace("\n", "\n  IDENT SHIP (owner 12 Nov): play-identical fuel cut, shipped on identity" + ("; no played reads\n" if not small else "; small-subset read only\n"), 1)
    print(text)
    open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
    with open(os.path.join(Q, "identship.log"), "a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {tag} {cand} v {live}: {same}/{ng} identical, fuel {pct:+.2f}%\n")
    tail = f" | {cand} ident {pct:+.2f}% fuel"
    submit(cand, tag, text, subject_line(lane)[:max(0, 80 - len(tail))].rstrip() + tail)
    return True


def bugbar_gate(cand, live, lane, livevals):
    """INFO ONLY since 9 Nov ~16:40Z (owner: verified bug fixes keep the bug bar when they change play). Was, owner rule 7 Nov ~21:15Z: the bug bar (BUGBAR=1) is ONLY for play-identical changes (refactors, fuel cuts, bakes,
    layouts) and fixes that fire ~0 on ordinary maps. Identity CAND v its TRUNK (flag 0; live when it has none) on SC_BUGBAR_MAPS (50) pool maps
    x 2 seats, on the pilots only. Unlimited fuel: at 100k a play-identical bake still differs in ~12% of games (the bot budgets by
    fuel_remaining), so only unlimited fuel separates play from the fuel reshuffle. Over SC_BUGBAR_MAXCHG (1%) of games changed: BUGBAR
    refused, the line requeued on the behaviour lane at the front, exit 3. Pilots short: the check is skipped and logged (fail open).
    Off: SC_BUGBAR_GATE=0."""
    if os.environ.get("BUGBAR") != "1" or lane != "fix" or os.environ.get("SC_BUGBAR_GATE") == "0":
        return
    ref = (flip_info(cand) or {}).get("TRUNK") or live
    if ref == cand or not os.path.isdir(os.path.join(REPO, "bots", ref, "src")):
        return say(f"bug-bar gate: no reference to compare {cand} with ({ref}): skipped")
    n = int(os.environ.get("SC_BUGBAR_MAPS", "50"))
    t0 = time.time()
    r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/cxe/cxeident.py"), ref, cand, "--maps", str(n), "--seed", "7"],
                       capture_output=True, text=True, cwd=REPO, env=dict(os.environ, CXEIDENT_PILOTS_ONLY="1", PILOTCXE_PRIO="20"))
    m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", r.stdout)
    rec = lambda txt: open(BUGBAR_GATE_LOG, "a").write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} v {ref}: {txt}\n")  # noqa: E731
    if r.returncode == 3 or not m:
        rec(f"not run (rc {r.returncode}): BUGBAR kept")
        return say(f"bug-bar gate: identity not run (rc {r.returncode}, pilots short?): BUGBAR kept ({time.time() - t0:.0f} s)")
    same, ng = int(m[1]), int(m[2])
    share = (ng - same) / max(1, ng)
    if share <= BUGBAR_MAXCHG:
        rec(f"{ng - same}/{ng} games changed ({share:.1%}): bug bar OK")
        return say(f"bug-bar gate: {ng - same}/{ng} games change play v {ref} at flag 0 ({share:.1%} <= {BUGBAR_MAXCHG:.0%}): bug bar OK ({time.time() - t0:.0f} s)")
    # 9 Nov ~16:40Z, owner (asked directly, "Yes, normal bug bar"; "as long as not negative it is fine"): VERIFIED bug fixes ship on the bug bar
    # even when they change play. The changed-games share is an info row; nothing is refused or requeued (was: > 1% -> behaviour lane, exit 3).
    rec(f"{ng - same}/{ng} games changed ({share:.1%}): play-changing fix, bug bar kept (owner 9 Nov)")
    say(f"bug-bar gate (info): {cand} changes play in {ng - same}/{ng} games v {ref} at flag 0 ({share:.1%}); owner 9 Nov: verified fixes keep the "
        f"bug bar when they change play ({time.time() - t0:.0f} s)")


def stack_requeue(cand, lane, livevals, suffix="u", confirm=None):
    """B's base failed: B's own flips go back on the arm queue, for whatever is live by then (armq.py). Also the one re-arm of a
    capacity INCONCLUSIVE (suffix i)."""
    lane = "ctrunk" if CTRUNK[0] else "fix" if RARE else lane  # 6 Nov (Builder: a ctrunk line's re-read ran on the fix lane): keep the line's own lane
    fl = own_flip_text(cand, livevals)
    subject = os.environ.get("SUBJECT") or f"{'fix' if lane == 'fix' else 'feat'}(trunk): {fl}"[:60]
    slug = re.sub(r"[^a-z0-9]", "", cand.split("_", 2)[-1]) + suffix
    # 5 Nov (Builder, px3 1444 -> px3i 1445): the requeue carries the donors the armed line carried (armq's armed_donors.jsonl), so a
    # donor-only change is not re-armed as live itself and armq counts its donor as needed
    donors = armed_donors(cand)
    if donors == "-" and not fl:
        return say(f"requeue of {cand}: no donors recorded and no own flips: nothing to re-arm (see {PENDING})")
    cmd = [sys.executable, "-I", os.path.join(REPO, "tools/lab/armq.py"), "front", donors, fl, lane, subject, slug]
    cmd += ["--bugbar"] if os.environ.get("BUGBAR") == "1" and lane == "fix" else []  # 3 Nov: the requeue dropped the line's bars (b971x16, b971x1)
    cmd += ["--parambar"] if os.environ.get("PARAMBAR") == "1" else []
    cmd += ["--seqspar"] if os.environ.get("SEQ_SPAR") == "1" and lane == "behaviour" else []  # 8 Nov: the marker's SEQ_SPAR key too
    cmd += ["--fuelx", os.environ["FUELX"]] if os.environ.get("FUELX") else []  # and its fuel-debt key
    not_rare = bool(RARE) and any("not a rare change" in read(f) for f in (os.path.join(Q, f"sc_{RARE.get('tag')}_sp.log"),
                                                                           os.path.join(Q, f"sp{RARE.get('tag')}.txt")))
    # 8 Nov (Builder, v622 geb1i): a re-arm keeps EVERY bar key of its marker. Dropping --rare after a 'not a rare change' probe (rdk1, 62%
    # changed) re-read geb1 (53% changed) on the plain fix bar, a lighter one, and it shipped on it. The rare read of a common change is
    # still valid (it reads the changed maps, which hold the whole effect); the note stays for the Builder.
    if not_rare:  # Builder 8 Nov: a common change leaves the rare lane for the BEHAVIOUR lane (its pooled sequential bar is stricter
        # than the plain fix bar that geb1i shipped on); every other re-arm keeps --rare
        say("the changed-map probe found a common change: re-queued on the BEHAVIOUR lane, without --rare")
        cmd[6] = "behaviour"  # [exe, -I, armq.py, front, donors, flips, LANE, ...]
        cmd = [x for x in cmd if x != "--bugbar"]
    cmd += ["--rare", str(RARE["n"])] if RARE and not not_rare else []
    cmd += ["--rare-fams", os.environ["RAREFAMS"]] if RARE and not not_rare and os.environ.get("RAREFAMS") else []
    cmd += ["--shadow", os.environ["SHADOW"]] if RARE and not not_rare and os.environ.get("SHADOW") else []
    cmd += ["--revises-live", os.environ["REVISES"]] if os.environ.get("REVISES", "").strip() else []  # the behaviour lane reads the whole effect v the trunk
    cmd += ["--base-has", os.environ["SP_BASE_HAS"]] if os.environ.get("SP_BASE_HAS") and not not_rare else []
    # 12 Nov (Builder, htr4 -> htr4i lost CLASS=htrh_share_min:>=0.75 and re-read the whole pool): a re-arm keeps the class read
    cmd += ["--class", os.environ["SP_CLASS"]] if os.environ.get("SP_CLASS", "").strip() and not not_rare else []
    cmd += ["--confirm-from", confirm[0], "--confirm-n", str(confirm[1])] if confirm else []  # reread_requeue only (owner 9 Nov: CONFIRM MODE)
    if DRY:
        return say(f"DRY: would requeue: {' '.join(cmd[2:])}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    say(f"requeue of {cand}'s own flips: rc {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}")


FIXBATCH_OFF = os.path.join(Q, "fixbatch_OFF")


def fixbatch_take(cand, tag, lane, stack, livevals, text, confirm=False, point=None):
    """Owner 9 Nov ~21:35Z (to the Builder: "yes batch bug fixes"): a plain FIX-LANE PASS (LANE=fix, with or without BUGBAR=1; not ctrunk, RARE,
    param, draft or behaviour, not a STACK_ON read, not a CONFIRM MODE read, not a fixbatch bundle itself) is not submitted: it goes to
    bq/fixbatch.tsv, and tools/lab/fixbatch.py releases the waiting fixes as ONE bundle on live (CONFIRM read, bug bar), falling back to the
    single fixes if the bundle does not ship. -> True when batched; any doubt -> False (today's submit). Off: touch bq/fixbatch_OFF."""
    # 9 Nov 22:05Z (Builder: v670 bb34sr, a fix-lane CONFIRM re-read, shipped at once and moved live under pra2f): confirm=True (called from
    # confirm_main) batches a fix-lane confirm PASS too; behaviour/draft/rare confirms never come here. A fixbatch bundle is never batched again.
    if lane != "fix" or CTRUNK[0] or RARE or stack or os.path.exists(FIXBATCH_OFF) or "(fixbatch)" in os.environ.get("SUBJECT", ""):
        return False
    if "(train)" in os.environ.get("SUBJECT", ""):  # 10 Nov: a release train's own confirm PASS submits (never batched again)
        return False
    if "(fixpre)" in os.environ.get("SUBJECT", ""):  # 10 Nov: a fixbatch.py pre-test bundle (bq/fixbundle_ON) was read once: its PASS submits
        return False
    if not confirm and (CONFIRM.get("from") or os.environ.get("CONFIRM_FROM", "").strip()):
        return False
    try:  # 10 Nov (owner: "why haven't we uploaded the passed stuff"): a fixbatch fallback single's confirm PASS submits (no bundle loop)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import fixbatch as _fb
        if _fb.is_fallback_single(cand):
            print(f"FIXBATCH: {cand} is a fallback single of a bundle that did not ship: submitted now, not batched again")
            return False
    except Exception:  # noqa: BLE001
        pass
    try:
        import fixbatch
        fl, dn = own_flip_text(cand, livevals), armed_donors(cand)
        if not fl and dn == "-":  # nothing a bundle could carry: today's submit
            return False
        h = re.search(r"live h2h(?: \([^)]*\))?\s+([\d.]+)", text)
        row = dict(bot=cand, tag=tag, donors=dn, flips=fl, lane=lane, bugbar="1" if os.environ.get("BUGBAR") == "1" else "0",
                   point=point or (h.group(1) if h else "?"), subject=subject_line(lane), fuelx=os.environ.get("FUELX", ""))
        dst = fixbatch.add_entry(row, dry=DRY)
    except Exception as e:  # noqa: BLE001  the batch never loses a PASS
        say(f"!! fix batch not used ({type(e).__name__}: {e}): submitting as before")
        return False
    print(f"BATCHED: {cand} TAG {tag} (fix lane{', bug bar' if row['bugbar'] == '1' else ''}, h2h {row['point']}; donors {dn}; flips {fl!r}) "
          f"written to {dst}{' (DRY)' if DRY else ''}: no submit now; fixbatch.py ships it in the next bundle (off: touch {FIXBATCH_OFF})")
    return True


TRAIN_ON = os.path.join(Q, "train_ON")


def train_donors(cand):
    """armed_donors(cand); a shipwatch rebase copy (NAME_r<ver>) has no armq record of its own: its source's donors."""
    dn = armed_donors(cand)
    m = re.fullmatch(r"(.+?)(_r\d+)+", cand)
    return armed_donors(m.group(1)) if dn == "-" and m else dn


def train_take(cand, tag, lane, stack, livevals, text, confirm=False, point=None):
    """RELEASE TRAIN (10 Nov, Tool Builder for the Builder; tools/lab/fixbatch.py): with bq/train_ON present, a PASS of ANY lane (fix, bug bar,
    behaviour, rare, param, draft; a full read or a CONFIRM MODE read; a check whose base live left mid-read too) is not submitted: one line of
    bq/train.tsv, and fixbatch.py ships every waiting PASS as ONE train on live (one CONFIRM read). Its own lane's PASS stands: no bar changes.
    Not taken (-> False, today's path): train_ON absent, ctrunk (armq's own train), a STACK_ON read, a train or fixbatch bundle itself, a PASS
    with no own flips and no recorded donors, any error."""
    if not os.path.exists(TRAIN_ON) or CTRUNK[0] or stack:
        return False
    subj = os.environ.get("SUBJECT", "")
    if "(train)" in subj or "(fixbatch)" in subj or "(fixpre)" in subj:  # (fixpre): a pre-test bundle's PASS submits, read once
        return False
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import fixbatch
        fl, dn = own_flip_text(cand, livevals), train_donors(cand)
        if not fl and dn == "-":
            return False
        if not point:
            pm = re.search(r"live h2h\+ext\s+([\d.]+)", text)
            rm = re.search(r"rare changed maps\s+([\d.]+)", text)
            h = re.search(r"live h2h(?: \([^)]*\))?\s+([\d.]+)", text)
            point = (pm.group(1) if lane == "param" and pm else rm.group(1) if RARE and rm else h.group(1) if h else "?")
        bb = os.environ.get("BUGBAR") == "1" and lane == "fix" and not RARE
        kind = "rare" if RARE else "param" if (lane == "param" or os.environ.get("PARAMBAR") == "1") else "bugbar" if bb else lane
        bars = {k: v for k, v in (("BUGBAR", "1" if bb else ""), ("RARE", str(RARE.get("n") or "") if RARE else ""),
                                  ("PARAMBAR", os.environ.get("PARAMBAR", "") if os.environ.get("PARAMBAR") == "1" else ""),
                                  ("RAREFAMS", os.environ.get("RAREFAMS", "") if RARE else ""), ("SHADOW", os.environ.get("SHADOW", "") if RARE else ""),
                                  ("REVISES", os.environ.get("REVISES", "").strip()), ("BASEHAS", os.environ.get("SP_BASE_HAS", "")), ("CLASS", os.environ.get("SP_CLASS", "")), ("WFAMS", os.environ.get("SP_WFAMS", "")),
                                  ("CONFIRM", "1" if confirm else "")) if v}
        row = dict(bot=cand, tag=tag, donors=dn, flips=fl, lane=kind, bugbar="1" if bb else "0", point=point, subject=subject_line(lane),
                   fuelx=os.environ.get("FUELX", ""), bars=bars)
        dst = fixbatch.train_add(row, dry=DRY)
    except Exception as e:  # noqa: BLE001  the train never loses a PASS
        say(f"!! release train not used ({type(e).__name__}: {e}): the old path")
        return False
    print(f"TRAIN: {cand} TAG {tag} ({kind}{', confirm read' if confirm else ''}, point {row['point']}; donors {dn}; flips {fl!r}) written to {dst}"
          f"{' (DRY)' if DRY else ''}: no submit now; the next release train carries it (off: rm {TRAIN_ON})")
    return True


RIDEALONG_ON = os.path.join(Q, "ridealong_ON")


def ride_hook(cand, live, rtag, tag, lane):
    """10 Nov (owner ~20:52Z, ride-along): OFF unless bq/ridealong_ON exists. When CAND carries ride-along rare bits (tools/lab/ridealong.py:
    marker RIDEALONG=, or fixbatch's bundle registry), one detached process plays each bit's TWIN leg (CAND v CAND with the bit at live's
    values) on this check's own fresh maps and updates the bit's ledger. Nothing here enters this check's rows or verdict."""
    if not os.path.exists(RIDEALONG_ON) or RARE:
        return
    try:
        import ridealong
        ridealong.twin_start(cand, live, rtag, tag, lane, log=say)
    except Exception as e:  # noqa: BLE001  never break a check
        say(f"ride-along: not started ({type(e).__name__}: {e})")


SHIP_ONLY = os.path.join(Q, "ship_only.txt")


def ship_only_wait(cand):
    """10 Nov (Builder: the v687 gate fix must ship before anything else): while bq/ship_only.txt holds a regex the candidate's name does
    not match, a PASS waits here, outside the submit lock, up to SHIP_ONLY_WAIT_S (5400 s). The file gone (or the wait over) -> on as usual;
    the submit's base check then catches a live that moved meanwhile."""
    t0, said = time.time(), False
    while os.path.exists(SHIP_ONLY) and time.time() - t0 < float(os.environ.get("SHIP_ONLY_WAIT_S", "5400")):
        try:
            pat = open(SHIP_ONLY).read().strip()
        except OSError:
            break
        if not pat or re.search(pat, cand):
            break
        if not said:
            say(f"ship hold: bq/ship_only.txt lets only /{pat}/ ship now; {cand} waits (up to {float(os.environ.get('SHIP_ONLY_WAIT_S', '5400')) / 60:.0f} min)")
            said = True
        time.sleep(30)


HOLD_FILE = "/data/USER/st/bq/hold_submit.txt"


def held(cand):
    """12 Nov (Builder: the Planner's emo5f7 has extra KILL rows to read from its fresh games before any ship): a line of
    bq/hold_submit.txt (a slug or any substring of the candidate's name; '#' comments) holds that candidate's submit: the shipcheck still
    runs and writes its verdict, a PASS is reported "PASS (held)" and nothing is uploaded; ship it by hand (tools/lab/handsubmit.py)."""
    # 13 Nov (owner via the Coordinator: "prioritise behavioural ones now as when a bug fix ships it screws all the other ships"): while
    # bq/hold_fix_lane exists, every fix-lane PASS (fix, bug bar, Q1 fuel cut, IDENT SHIP) is held like a hold_submit line and listed in
    # bq/held_fix.txt, so the Builder ships them as ONE bundle at a quiet point. rm bq/hold_fix_lane to ship fix PASSes one by one again.
    try:
        # 13 Nov ~12:5xZ (owner: "If no iteration for a while do the bug fixes etc"): the fix-lane hold applies only while a ship landed in
        # the last HOLD_FIX_IDLE_MIN (30) minutes; after a quiet spell fix-lane PASSes submit as usual
        idle_ok = True
        try:
            ts = open(os.path.join(Q, "live.txt")).readline().split()[2][:19]
            import calendar
            idle_ok = time.time() - calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%S")) < 60 * int(os.environ.get("HOLD_FIX_IDLE_MIN", "30"))
        except (OSError, IndexError, ValueError):
            pass
        if idle_ok and os.path.exists(os.path.join(Q, "hold_fix_lane")):
            kv_ = {}
            for ln in open(os.path.join(REPO, "bots", cand, "SHIPCHECK"), errors="replace"):
                if "=" in ln and not ln.lstrip().startswith("#"):
                    k_, _, v_ = ln.strip().partition("=")
                    kv_[k_.strip()] = v_.strip()
            # (a RARE=N line runs on the fix lane but changes play: it is a behaviour change, not held, unless it is a bug bar or Q1 cut)
            if kv_.get("LANE", os.environ.get("LANE", "behaviour")) == "fix" and (not kv_.get("RARE") or kv_.get("BUGBAR") or kv_.get("Q1BAR")):
                with open(os.path.join(Q, "held_fix.txt"), "a") as f_:
                    f_.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} TRUNK={kv_.get('TRUNK', '-')} DONORS={os.environ.get('DONORS', '-')}\n")
                return "fix-lane hold (bq/hold_fix_lane)"
    except OSError:
        pass
    try:
        keys = [ln.split("#")[0].strip() for ln in open(HOLD_FILE)]
    except OSError:
        return None
    return next((k for k in keys if k and k in cand), None)


def submit(cand, tag, text, summary_note):
    h = held(cand)
    if h:
        try:
            with open(os.path.join(Q, "hold_submit.log"), "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {tag} {cand}: PASS held (hold_submit.txt line {h!r})\n")
        except OSError:
            pass
        return say(f"PASS (held): {cand} matches {h!r} in {HOLD_FILE}: no submit; read the held rows, then hand-submit "
                   f"(python3 -I tools/lab/handsubmit.py vNNN {cand} \"note\")")
    ship_only_wait(cand)
    st = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/autoship.py"), "status"], capture_output=True,
                        text=True, cwd=REPO).stdout
    if not re.search(r"timer: not armed", st):
        return say(f"REFUSED: autoship looks armed ({st.splitlines()[0] if st else '?'}): disarm it first")
    os.makedirs(os.path.dirname(SUBMIT_LOCK), exist_ok=True)
    with open(SUBMIT_LOCK, "a") as lk:
        say("waiting for the submit lock" if not _try(lk) else "submit lock taken")
        fcntl.flock(lk, fcntl.LOCK_EX)
        live, ver, parent = live_bot()  # live.txt first: a submit a minute ago is already there
        if os.environ.get("STACK_ON") and live != os.environ["STACK_ON"]:
            return say(f"STACK VOID: stacked on {os.environ['STACK_ON']}, but {live} is live inside the submit lock: no submit")
        fi = flip_info(cand)
        if fi and fi.get("TRUNK"):  # TRUNK mode: a valid flip of a trunk that is itself built on live
            ok, why, tbase = trunk_check(cand, os.environ.get("LIVEVALS", ""))
            if ok:
                ok, why = base_check(tbase, live, parent)
            tv = trunk_base_version(fi["TRUNK"])
            if ok and tv is not None and ver and ver.isdigit() and tv < int(ver):
                ok, why = False, f"its trunk {fi['TRUNK']} is built on nova_base_v{tv}, older than live v{ver} (trunk_registry.md)"
        else:
            ok, why = base_check(cand, live, parent)
        if not ok:
            LIVE_MOVED.append(live)
            return say(f"REFUSED: rebase onto live first ({live} is live now: {why})")
        pv = platform_live()
        if pv is not None and ver and ver.isdigit() and pv > int(ver):
            return say(f"REFUSED: rebase onto live first (the platform's live is v{pv}, newer than v{ver} {live} in live.txt / "
                       f"CLAUDE.md: a submit this tool did not record)")
        note = summary_note[:80]
        ap_ = affects_pct(cand, wait=int(os.environ.get("SC_AFFECTS_WAIT", 120)))  # owner 12 Nov: each submission states its changed-map share
        if ap_ and "% maps" not in note:
            add_ = f" [{ap_}]" if "maps" in ap_ else f" [{ap_} maps]"
            i_ = note.find(" | nova_")  # keep the bot name at the end (hand-submit/shipwatch notes key on it)
            head_, tail_ = (note[:i_], note[i_:]) if i_ >= 0 else (note, "")
            note = (head_[:max(0, 80 - len(tail_) - len(add_))].rstrip() + add_ + tail_)[:80]
        cmd = ["sh", os.path.join(REPO, "tools/lab/platlock.sh"), CLI, "submit", "-n", note, f"bots/{cand}"]
        if DRY:
            say(f"DRY: would submit: {' '.join(cmd[:5])} {note!r} bots/{cand}  (note {len(note)} chars)")
            version = "DRY"
            time.sleep(float(os.environ.get("DRY_HOLD", "0")))  # (tests: the lock stays held for a while, as a real submit)
            open(DRYLIVE, "w").write(f"{cand} {live}\n")
        else:
            version = submit_once_more(cmd, note, ver)
            if not version:
                return say("!! no version in the submit output: check `cambc submissions list` and run unrsets.sh by hand")
            prepend_live(f"v{version} {cand} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} parent={live}")
            subprocess.run(["sh", os.path.join(REPO, "tools/lab/realbot.sh"), cand], capture_output=True)  # 2 Nov: only a shipped bot is a real folder (git can hold it)
            an_bot, an_ver = anchor()
            since = anchor_set_at()  # ships made since the anchor was set (by time: v298 re-shipped the v289 source)
            ships = sorted({v for v, t in submitted_versions().items() if t > since} | {int(version)})
            if an_bot and ships and len(ships) % 3 == 0:
                alog = os.path.join(Q, f"anchorcheck_v{version}.log")
                subprocess.Popen(f"nohup nice -n 10 python3 -I {os.path.join(REPO, 'tools/lab/shipcheck.py')} --anchorcheck "
                                 f"{cand} {version} > {alog} 2>&1 &", shell=True, cwd=REPO, start_new_session=True)
                say(f"{len(ships)} ships since the anchor {an_bot} (v{an_ver}): full-pool live-vs-anchor h2h started ({alog})")
            log = os.path.join(Q, f"unrsets_{tag}.log")
            subprocess.Popen(f"nohup nice -n 10 sh {Q}/unrsets.sh {version} {tag} > {log} 2>&1 &", shell=True, cwd=REPO)
        line = (f"- v{version} {subprocess.run(['date', '-u'], capture_output=True, text=True).stdout.strip()}: {cand} "
                f"(shipcheck {tag}{', DRY' if DRY else ''})\n" + "".join(f"    {x}\n" for x in text.splitlines()))
        dst = DRYLOG if DRY else QUEUE
        with open(dst + ".lock", "a") as ql:
            fcntl.flock(ql, fcntl.LOCK_EX)
            old = read(dst)
            open(dst + ".new", "w").write(old + ("" if old.endswith("\n") or not old else "\n") + line)
            os.replace(dst + ".new", dst)
        try:
            log_submission(version, cand, live, tag, os.environ.get("LANE", "behaviour"), text)
        except Exception as e:  # the log never blocks a submit
            say(f"submissions log not written: {e}")
        say(f"{'DRY: would append to ' + QUEUE + ' (written to ' + DRYLOG + ')' if DRY else 'appended to ' + QUEUE}")
        print(f"SUBMITTED v{version}{' (DRY: nothing was submitted)' if DRY else ''}")
        try:  # every lane: fix-lane checks have no nochase2 reference, so post-ship plays both sides itself
            start_postship(cand, tag, version, POSTSHIP_ND.get("bnd") or "", live)
            if not DRY:
                subprocess.Popen(f"nohup nice -n 10 python3 -I {os.path.join(REPO, 'tools/lab/driftledger.py')} {cand} {version} "
                                 f"> {os.path.join(Q, 'postship', f'ledger_{tag}.log')} 2>&1 &", shell=True, cwd=REPO, start_new_session=True)
        except Exception as e:  # noqa: BLE001  (a measurement never fails a ship)
            say(f"!! post-ship not started: {e}")
        print(f"CLAUDE.md live line to put in: - The live bot: **bots/{cand} = v{version}** (submitted "
              f"{time.strftime('%d %b %H:%M', time.gmtime())} UTC: v{ver or '?'} + <this change>; v{ver or '?'} = bots/{live} = ...)")


def start_postship(cand, tag, version, bnd, base=""):
    """The complement leg in the background (its own session, nice 10)."""
    if DRY and os.environ.get("SC_DRY_POSTSHIP") != "1":  # 7 Nov: a DRY read that reached PASS played 6,694 real maps
        return say("DRY: no post-ship leg (SC_DRY_POSTSHIP=1 plays it)")
    sub = os.path.join(Q, "postship", f"{tag}.subset")
    if not os.path.exists(sub):
        if bnd:
            return say(f"!! post-ship: no recorded subset {sub}: complement leg not started")
        os.makedirs(os.path.dirname(sub), exist_ok=True)
        open(sub, "w").close()
    log = os.path.join(Q, "postship", f"{tag}.log")
    cmd = (f"nohup nice -n 10 python3 -I {os.path.join(REPO, 'tools/lab/shipcheck.py')} --postship {cand} {tag} {version} "
           f"{shlex.quote(bnd)} {shlex.quote(base)} > {log} 2>&1 &")
    subprocess.Popen(cmd, shell=True, cwd=REPO, start_new_session=True)
    say(f"post-ship complement leg started in the background (log {log})")


def retire_old_postships(tag, version, say=say):
    """7 Nov (Builder, owner yes: 'if we speed up our workflow then yes'): a new live's post-ship retires every older version's
    post-ship and drift reads (shipcheck --postship, driftledger, their condab legs ps<TAG> / dl<VER>x<N>) and cancels their queued
    pilot batches: those reads can no longer change a decision and held ~1,100 of 1,755 queued items. SC_KEEP_OLD_POSTSHIP=1: keep."""
    if os.environ.get("SC_KEEP_OLD_POSTSHIP") == "1":
        return
    me = os.getpid()
    old_tags, old_vers, pids = set(), set(), []
    for p in filter(str.isdigit, os.listdir("/proc")):
        try:
            cl = open(f"/proc/{p}/cmdline").read().split("\0")
        except OSError:
            continue
        if int(p) == me or not cl or not os.path.basename(cl[0]).startswith("python") or not any(x.endswith("shipcheck.py") for x in cl[1:3]) or "--postship" not in cl:
            continue
        i = cl.index("--postship")
        t, v = (cl[i + 2], cl[i + 3]) if len(cl) > i + 3 else ("", "")
        if t and t != str(tag) and v.isdigit() and int(v) < int(version):
            old_tags.add(t)
            old_vers.add(v)
            pids.append(int(p))
    if not old_tags:
        return
    pat = re.compile(r"^(ps(" + "|".join(map(re.escape, old_tags)) + r")|dl(" + "|".join(map(re.escape, old_vers)) + r")x\d+)$")
    anc, q_ = set(), me
    while q_ > 1:  # never this process's parents (a shell whose command text names the legs must not match)
        anc.add(q_)
        try:
            q_ = int(open(f"/proc/{q_}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    for p in filter(str.isdigit, os.listdir("/proc")):
        try:
            cl = [x for x in open(f"/proc/{p}/cmdline").read().split("\0") if x]
        except OSError:
            continue
        if int(p) in anc or not cl or not os.path.basename(cl[0]).startswith("python"):
            continue
        script = next((x for x in cl[1:] if x.endswith(".py")), "")
        if (script.endswith("/condab.py") or script == "condab.py") and any(pat.match(x) for x in cl):
            pids.append(int(p))
        elif (script.endswith("/driftledger.py") or script == "driftledger.py") and cl[-1] in old_vers:
            pids.append(int(p))
    for p in pids:
        try:
            os.kill(p, 15)
        except OSError:
            pass
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import pilotd
    nq = 0
    for n in pilotd.ls(pilotd.q("queue")):
        b = (pilotd.parse(n) or (0, 0, ""))[2]
        if re.match(r"^cq-(ps(" + "|".join(map(re.escape, old_tags)) + r")|dl(" + "|".join(map(re.escape, old_vers)) + r")x\d+)-", b):
            nq += pilotd.cancel(b)[0]
    say(f"post-ship {tag} v{version}: retired older post-ship/drift reads of tags {sorted(old_tags)} (v{', v'.join(sorted(old_vers))}): "
        f"{len(pids)} process(es) stopped, {nq} queued item(s) cancelled")


def postship(cand, tag, version, bnd, base=""):
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    try:
        retire_old_postships(tag, version)
    except Exception as e:  # noqa: BLE001
        say(f"post-ship {tag}: retiring older post-ship reads failed: {e}")
    if not HAVE_ND:  # the complement leg plays nochase2 (owner 8 Nov: spars deleted)
        return say(f"post-ship {tag}: no nochase2 bot, complement leg skipped")
    import abindex
    import condab
    opp = "nova_spar_nochase2"
    allm = condab.set_maps("all")
    sub = [x.strip() for x in open(os.path.join(Q, "postship", f"{tag}.subset")) if x.strip()]
    comp = [m for m in allm if bnd == "" or m not in set(sub)]  # no reference run (fix lane): both sides play every map
    say(f"post-ship {tag} v{version}: subset {len(sub)} + complement {len(comp)} = {len(sub) + len(comp)} "
        f"(all {len(allm)}; subset maps outside all: {len(set(sub) - set(allm))})")
    play = comp[:int(os.environ["POSTSHIP_MAX"])] if os.environ.get("POSTSHIP_MAX") else comp
    cf = os.path.join(Q, "postship", f"{tag}.complement")
    open(cf, "w").write("".join(m + "\n" for m in play))
    env = {k: v for k, v in os.environ.items() if k not in ("STOP", "STOP_PASS", "STOP_REF", "CONDAB_TIMEBOX", "KEEP",
                                                             "CONFIRM", "OTF_DIR", "OTF_DOM", "OTF_RULE", "OTF_GEMCLU")}
    env.update(STOP="0", OTF="0", CONDAB_PRIO=os.environ.get("POSTSHIP_PRIO", "-50"))
    rtag = os.environ.get("SC_RTAG", tag)

    def leg(what, bot, run):
        """One condab leg. It runs after the submit, so a failure or a stuck leg is logged and the read goes on."""
        try:
            r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/condab.sh"), bot, opp, run, cf], cwd=REPO, env=env,
                               capture_output=True, text=True, timeout=POSTSHIP_LEG_S)
        except (OSError, subprocess.SubprocessError) as e:
            say(f"!! {what} leg failed: {str(e)[:160]}")
            return
        say(f"{what} leg exit {r.returncode}: {r.stdout.strip().splitlines()[-1][:160] if r.stdout.strip() else r.stderr[-200:]}")
    leg("complement", cand, f"ps{rtag}")
    ref = condab.ref_run(bnd, opp) if bnd else None
    base = ref[2] if ref else base
    if not base:
        return say("!! post-ship: no base bot: no read")
    leg("base complement", base, f"pb{rtag}")
    try:  # every game the index has of the base on all maps: the gate's subset plus the leg above
        ref = condab.ref_run(index_ref(base, allm, f"{rtag}ps"), opp)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        if not ref:
            return say(f"!! post-ship: base reference not built ({str(e)[:160]}): no read")
        say(f"!! post-ship: base reference on all maps not built ({str(e)[:160]}): the read stays on the subset")
    pd = condab.pair_d()
    b = pd["scores"](ref[1], ref[2])
    hc, ho = abindex.bot_hash(cand), abindex.bot_hash(opp)
    ix = abindex.Index({hc, ho})
    nm, inv = abindex.map_names(), {hc: cand, ho: opp}
    tmp = os.path.join(Q, "postship", f".{tag}.games")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "games.jsonl"), "w") as f:
        for (ha, hb, mh), g in ix.games.items():
            if nm.get(mh) in set(allm) and ha in inv and hb in inv:
                f.write(json.dumps(dict(a=inv[ha], b=inv[hb], map=nm[mh], ok=True, win=g["win"])) + "\n")
    c = pd["scores"](os.path.relpath(tmp, "/data/USER/abl"), cand)

    def dline(ms):
        ds = [c[m] - b[m] for m in ms if m in c and m in b]
        if len(ds) < 2:
            return ds, f"n {len(ds)}"
        mu, lo, hi = pd["boot"](ds)
        se = (sum((x - mu) ** 2 for x in ds) / (len(ds) - 1) / len(ds)) ** 0.5
        return ds, f"D {mu:+.3f} [{lo:+.3f}, {hi:+.3f}] n {len(ds)} (se {se:.3f})"
    dc, comp_s = dline(play)
    da, all_s = dline(allm)
    flag = ""
    if len(da) >= 2:
        mu = sum(da) / len(da)
        se = (sum((x - mu) ** 2 for x in da) / (len(da) - 1) / len(da)) ** 0.5
        flag = "  ROLLBACK-FLAG (combined D < -2 SE)" if mu < -2 * se else ""
    line = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z post-ship v{version} {cand} ({tag}{', DRY' if DRY else ''}): "
            f"complement {comp_s}; combined {'full pool' if len(da) >= 0.95 * len(allm) else f'PARTIAL ({len(da)} of {len(allm)} maps)'} "
            f"{all_s} vs {os.path.basename(ref[0])} ({ref[2]}){flag}")
    for dst in (os.path.join(Q, "shipwatch.log"), os.path.join(Q, "postship.log")):
        with open(dst, "a") as f:
            f.write(line + "\n")
    print(line)


def submitted_versions():
    """{version: UTC epoch} of real submits in builder_queue.md ("- vNNN Thu 29 Oct 23:52:33 UTC 2026: BOT ...", not DRY)."""
    import calendar
    out = {}
    for line in read(QUEUE).splitlines():
        m = re.match(r"^- v(\d+) (\w{3} \d+ \w{3} \d\d:\d\d:\d\d) UTC (\d{4}): nova_", line)
        if m and "DRY" not in line:
            try:
                out[int(m.group(1))] = calendar.timegm(time.strptime(f"{m.group(2)} {m.group(3)}", "%a %d %b %H:%M:%S %Y"))
            except ValueError:
                pass
    return out


def anchor_set_at():
    """UTC epoch the anchor was set (anchor.txt's third field), or 0."""
    import calendar
    try:
        return calendar.timegm(time.strptime(open(ANCHOR).read().split()[2], "%Y-%m-%dT%H:%M:%SZ"))
    except (OSError, IndexError, ValueError):
        return 0


def anchor_check(live, version):
    """Full-pool (636) h2h live vs ANCHOR, in the background after every 3rd ship. CI upper < 0.5: ROLLBACK-FLAG to
    shipwatch.log and health.log; CI lower >= 0.5 (significantly better, the strict reading): the anchor moves to live.
    Nothing is rolled back automatically."""
    an_bot, an_ver = anchor()
    if not an_bot:
        return say("anchor check: no anchor")
    env = {k: v for k, v in os.environ.items() if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONFIRM", "KEEP")}
    env.update(OTF="0")
    name = run_tag(f"al{version}", live, an_bot, prefixes=("",))
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/condab.sh"), live, an_bot, name, "all"], cwd=REPO, env=env,
                       capture_output=True, text=True)
    txt = read(os.path.join(Q, f"{name}.condor.txt"))
    m = re.search(r"^\s+ALL\s+(\d+) maps: .*?score ([\d.]+) \[([\d.]+), ([\d.]+)\]", txt, re.M)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    if not m:
        line = f"{stamp}Z anchor check v{version}: no result (condab exit {r.returncode}, {name})"
    else:
        n, sc_, lo, hi = int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        res = f"{sc_:.3f} [{lo:.3f}, {hi:.3f}] n {n}"
        if hi < 0.5:
            line = f"{stamp}Z ROLLBACK-FLAG: live v{version} {live} significantly worse than anchor {an_bot} (v{an_ver}) ({res})"
        elif lo >= 0.5:
            with open(ANCHOR + ".new", "w") as f:
                f.write(f"{live} {version} {stamp.replace(' ', 'T')}Z full-pool h2h vs {an_bot} (v{an_ver}) {res}\n")
            os.replace(ANCHOR + ".new", ANCHOR)
            line = f"{stamp}Z anchor moved: {an_bot} (v{an_ver}) -> {live} (v{version}): live significantly better ({res})"
        else:
            line = f"{stamp}Z anchor check v{version}: live {live} vs anchor {an_bot} (v{an_ver}) {res}: not different, anchor stays"
    for dst in (os.path.join(Q, "shipwatch.log"), HEALTH):
        with open(dst, "a") as f:
            f.write(line + "\n")
    print(line)


def mech_run(cand, tag, live, trigger):
    """After a gate PASS: KEEP=1 on TRIGGER (priority -5, OTF=0), then MECH on the kept dir; appended to shipcheck_TAG.txt."""
    env = {k: v for k, v in os.environ.items() if k not in ("STOP", "STOP_PASS", "STOP_REF", "CONFIRM", "OTF_DIR",
                                                             "CONDAB_TIMEBOX")}
    env.update(KEEP="1", OTF="0", CONDAB_PRIO="-5")
    kt = os.environ.get("SC_RTAG", tag)
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/condab.sh"), cand, live, f"kp{kt}", trigger], cwd=REPO, env=env,
                       capture_output=True, text=True)
    say(f"KEEP kp{tag} exit {r.returncode}")
    out = f"\nmechanism (informational, after the gate PASS): KEEP kp{tag} exit {r.returncode}"
    # 31 Oct (cambc-34): MECH used to run as a shell command, but markers carry MECH as PROSE (the commit body); 10 of 10
    # runs to date failed harmlessly (syntax error / not found), yet a prose '>' could have truncated a repo file. Now only
    # MECHCMD runs, split with shlex and WITHOUT a shell; MECH stays prose (commit body, subject, "rollback ...").
    if os.environ.get("MECHCMD"):
        kd = sorted(glob.glob(f"/data/USER/abl/cq_kp{kt}_*/rep"), key=os.path.getmtime)
        sub = {"{KEEPDIR}": os.path.dirname(kd[-1]) if kd else "", "{CAND}": cand, "{BASE}": live, "{TRIGGER}": trigger}
        try:
            argv = shlex.split(os.environ["MECHCMD"])
        except ValueError as e:
            argv = None
            out += f", MECHCMD not run (cannot split it: {e})"
        if argv:
            for k, v in sub.items():
                argv = [a.replace(k, v) for a in argv]
            say(f"mechanism: {' '.join(shlex.quote(a) for a in argv)}")
            try:
                m = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=3600)
                tail = (m.stdout + m.stderr).rstrip().splitlines()[-20:]
                out += f", MECHCMD exit {m.returncode}:\n" + "\n".join(f"  {x}" for x in tail)
                print("\n".join(tail))
            except (OSError, subprocess.TimeoutExpired) as e:
                out += f", MECHCMD failed: {e}"
    elif os.environ.get("MECH"):
        out += ", MECH is prose (no MECHCMD): no mechanism command run"
    with open(os.path.join(Q, f"shipcheck_{tag}.txt"), "a") as f:
        f.write(out + "\n")


def reverdict(cand, tag, lane, live=None):
    """--verdict CAND TAG [LANE=..] [LIVE=..]: the verdict table again from an earlier check's leg summaries (TAG = its run
    tag, e.g. 306q), under the current switches (SC_FIX_NONC, SC_LH_EARLY, ...). Prints only: no submit, no file written.
    ubaudit from sc_TAG_ub.log ("NEW UB SITES: N"); no trigger D (it needs the index walk of the trigger maps)."""
    live = live or re.search(r"vs live ([^\s,]+)", read(os.path.join(Q, f"shipcheck_{tag}.txt")) or f"vs live {live_bot()[0]}").group(1)
    set_sameplay(cand)
    an_bot, _ = anchor()
    if an_bot and os.path.exists(os.path.join(Q, f"an{tag}.condor.txt")):
        os.environ["SC_ANCHOR"], os.environ["SC_ANTAG"] = an_bot, tag
    if (flip_info(cand) or {}).get("TRUNK") and lane == "behaviour":  # a TRUNK-mode behaviour check: the fresh leg decides
        os.environ["SC_FRESH_DECIDES"] = "1"
    nh = re.match(r"# condab \S+: \S+ vs (\S+?)@", read(os.path.join(Q, f"nl{tag}.condor.txt")))
    if nh:  # the check ran a NULLSW leg: its change size and CAND vs NULL fuel, as in the original table
        NULL_RUN.update(name=f"nl{tag}", bot=nh.group(1))
    ub_txt = read(os.path.join(Q, f"sc_{tag}_ub.log"))
    k = re.search(r"NEW UB SITES: (\d+)", ub_txt)
    ub_rc = (0 if int(k.group(1)) == 0 else 1) if k else None
    rows, overall = table(cand, live, tag, lane, ub_rc, ub_txt)
    print(fmt(rows, overall, cand, live, tag, lane, 0) + f"\n  (re-verdict: SC_FIX_NONC={int(FIX_NONC)} "
          f"SC_LH_EARLY={int(LH_EARLY)} SC_LIVEH2H={int(LIVEH2H)})")
    return overall


def _try(lk):
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def confirm_plan(lane):
    """The confirm read for this line's lane (owner 9 Nov, via the Tool Builder): a near-identical change must not lose a real pass to noise.
    RARE: CHANGED maps (stylepanel --changed), half the lane's read (RARE n 420 -> 210), point > .50, CI upper >= .50. Draft lane: draft-changed maps
    (--draft-changed), half of DRAFT_N (600), point > .50, CI upper >= .50. Bug bar line (BUGBAR=1, fix): 1,200 fresh maps, point >= BUGBAR_PT (.50 since
    owner 9 Nov ~17:55Z), CI upper >= .50. Behaviour and plain fix: 1,200 fresh maps, point >= .50, CI upper >= .50. SC_CONFIRM_MAPS (tests) sets the map count of any lane."""
    ov = os.environ.get("SC_CONFIRM_MAPS")
    if RARE:
        n = int(ov) if ov else math.ceil(RARE["n"] / 2)
        return dict(kind="rare", n=n, pt=0.5, strict=True, floor=min(math.ceil(RARE["min"] / 2), int(0.9 * n)),
                    args=f"--n {n} --changed {n}", wait=CONFIRM_WAIT + int(os.environ.get("SP_CHANGED_WALL", 10800)),
                    what=f"{n} CHANGED maps v live (rare lane), PASS iff point > .50 and CI upper >= .50")
    if lane == "draft":
        n = int(ov) if ov else DRAFT_N // 2
        return dict(kind="draft", n=n, pt=0.5, strict=True, floor=min(DRAFT_MIN, int(0.9 * n)),
                    args=f"--n {n} --draft-changed {n}", wait=CONFIRM_WAIT + int(os.environ.get("SP_DRAFT_WALL", 14400)),
                    what=f"{n} draft-CHANGED maps v live (draft lane), PASS iff point > .50 and CI upper >= .50")
    # 12 Nov (Coordinator [4b38e1]: prepared, NOT enabled; the owner decides the behaviour confirm size): SC_CONFIRM_MAPS_BEH sets the behaviour
    # lane's confirm map count only; unset = CONFIRM_MAPS (1,200), today's bar. Fix / bug-bar confirms always use CONFIRM_MAPS.
    beh = os.environ.get("SC_CONFIRM_MAPS_BEH", "")
    if not beh:  # 12 Nov (Coordinator [4b38e1], owner's delegation "do what you believe": behaviour confirm at 3,300): bq/confirm_maps_beh, so it survives daemon restarts
        try:
            beh = open(os.path.join(Q, "confirm_maps_beh")).read().split()[0]
        except (OSError, IndexError):
            beh = ""
    fixn = ""
    try:  # 13 Nov (owner: "For bugs be more careful"): fix-lane confirms (bug bar, plain fix, Q1 fuel cut) read bq/confirm_maps_fix (1,200)
        fixn = open(os.path.join(Q, "confirm_maps_fix")).read().split()[0]
    except (OSError, IndexError):
        pass
    n = int(ov) if ov else (int(beh) if beh.isdigit() and lane == "behaviour" else int(fixn) if fixn.isdigit() and lane == "fix" else CONFIRM_MAPS)
    bb = os.environ.get("BUGBAR") == "1" and lane == "fix"
    # 12 Nov (owner Q2 "make it .4975", applied to the bug bar's 1,200-map confirm by the Coordinator's ruling; Builder): a bug-bar confirm
    # reads at SC_BUGBAR_FRESH_PT (.4975), a Q1BAR confirm at SC_Q1BAR_FRESH_PT (.495); CI upper >= .50 either way
    q1 = os.environ.get("Q1BAR") == "1" and lane == "fix"
    pt = BUGBAR_FRESH_PT if bb else Q1BAR_FRESH_PT if q1 else 0.5
    return dict(kind="fresh", n=n, pt=pt, strict=False, floor=int(0.9 * n), args=f"--n {n}", wait=CONFIRM_WAIT, bugbar=bb,
                what=f"{n} new maps v live{' (bug bar line)' if bb else ' (Q1 fuel-cut line)' if q1 else ''}, PASS iff point >= {pt:g} and CI upper >= .50")
    # 9 Nov ~23:25Z, owner (asked directly: "Drop lower bound on confirms"): the bug bar's CI lower >= BUGBAR_LO binds on the full read only;
    # at 1,200 maps it needed point ~.514 (fxb1z .5008, hvb56bf .5117, fxb2z .5042 failed on that row alone)


def confirm_rows(cand, live, tag, plan):
    """CONFIRM MODE rows: the confirm read on plan's bar, bot faults, capped fuel and the death guard on the same games (stylepanel's fp_games.jsonl)."""
    txt = read(os.path.join(Q, f"sp{tag}.txt"))
    m = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    name = "confirm fresh" if plan["kind"] == "fresh" else "confirm changed maps"
    bar = f"pt{'>' if plan['strict'] else '>='}{plan['pt']:g}, up>=.50, n>={plan['floor']}" + ("" if plan["kind"] == "fresh" else ", >=95% kept")
    kept, share, note = None, None, ""
    if plan["kind"] == "rare":
        pr = re.search(r"changed probe: (\d+) of (\d+) pool maps changed \(([\d.]+)% .*?(\d+) unchanged dropped.*?(\d+) kept", txt)
        if pr:
            kept, share, note = int(pr.group(5)), pr.group(3), f"{pr.group(1)} of {pr.group(2)} pool maps changed"
        nr = re.search(r"not a rare change: (\d+)% of maps changed", read(os.path.join(Q, f"sc_{CONFIRM.get('log', tag)}_sp.log")) + txt)
        if nr and not m:
            return confirm_safety(cand, live, tag, [(name, f"not a rare change: {nr.group(1)}% of maps changed", bar, "INCONCLUSIVE")])
    elif plan["kind"] == "draft":
        pr = re.search(r"draft probe: (\d+) of (\d+) probed maps changed .*?whole-pool firing share \(halves' mean\) ([\d.]+)%", txt)
        if pr:
            kept = sum(int(x) for x in re.findall(r"^    (?:weird|std)\s.*kept (\d+)$", txt, re.M))
            share, note = pr.group(3), f"{pr.group(1)} of {pr.group(2)} probed changed"
    if not m or (plan["kind"] != "fresh" and kept is None):
        return confirm_safety(cand, live, tag, [(name, "no result (stylepanel did not finish)", bar, "INCONCLUSIVE")])
    p, lo, hi, n = float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))
    short = n < plan["floor"] or (kept is not None and n < 0.95 * kept)
    ok = (p > plan["pt"] if plan["strict"] else p >= plan["pt"]) and hi >= 0.5
    val = (f"{p:.4f} [{lo:.3f}, {hi:.3f}] n {n}" + (f"/{kept}" if kept is not None else "")
           + (" (new maps v live, half pathological)" if plan["kind"] == "fresh" else f" ({note}; changed {share}% of pool maps)"))
    return confirm_safety(cand, live, tag, [(name, val, bar, "INCONCLUSIVE" if short else "PASS" if ok else "FAIL")])


def confirm_safety(cand, live, tag, rows):
    pf, pc, pb_, pn = panel_games(tag, cand, live)
    rows.append(("bot faults (CAND)", f"{pf} ({pn} games of the confirm read)", "0", "INCONCLUSIVE" if not pn else "FAIL" if pf else "PASS"))
    rows.append(fuel_row(cand, live, pc, pb_, "confirm read", bool(pn)))
    rows.append(death_row(cand, live, tag) or ("death guard", "no CAND vs LIVE games on record", f"read z < {DEATH_Z:g}", "INCONCLUSIVE"))
    return rows


def confirm_main(cand, tag, rtag, live, ver, lane, stack_vals):
    """CONFIRM MODE (owner 9 Nov; see CONFIRM above): the one confirm leg v live (confirm_plan: the lane's bar), its rows, then the usual submit path."""
    t0 = time.time()
    CONFIRM.update(tag=rtag, log=tag)
    os.environ["SP_FRESH_NEW"] = "1"  # 13 Nov (owner "or on retests"): a confirm never reads the shared per-live fresh set (stylepanel.shared_fresh_slice)
    # 12 Nov ~18:2xZ (Builder: fxp10z 'PASSED' at BIG .4960 under the fresh-led bar bug, then came back as a confirm read, which plays
    # fresh maps only): a bug-bar confirm first re-judges the ORIGINAL pass's BIG row at today's bug bar; below it, the confirm FAILs
    if os.environ.get("BUGBAR") == "1" and lane == "fix":
        orig = read(os.path.join(Q, f"shipcheck_{CONFIRM.get('from')}.txt"))
        mb = re.search(r"^  live h2h +([\d.]+) \[([\d.]+), ([\d.]+)\]", orig, re.M)
        if mb and (float(mb.group(1)) < BUGBAR_H2H_PT or float(mb.group(3)) < 0.5):
            text = (f"SHIPCHECK {tag}: {cand} v live {live}, lane {lane}: CONFIRM refused\n  original PASS {CONFIRM.get('from')}  BIG {mb.group(1)} "
                    f"[{mb.group(2)}, {mb.group(3)}] below today's bug bar (point >= {BUGBAR_H2H_PT:g}, CI upper >= .50): a full check is needed\n  OVERALL: FAIL")
            print(text)
            open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
            say("no submit: FAIL (the original pass does not meet today's bug bar)")
            return
    plan = confirm_plan(lane)
    head = (f"CONFIRM MODE (owner 9 Nov): stale PASS from TAG {CONFIRM['from']} re-read on live v{ver or '?'} {live} (live move {CONFIRM['n']} "
            f"of at most {CONFIRM_MAX} since that read): {plan['what']}; faults, capped fuel, death guard")
    say(head)
    if fuel_pct() > 0:
        FUEL_FIRST["t"] = threading.Thread(target=heavy_go, args=(cand, live, rtag), daemon=True)
        FUEL_FIRST["t"].start()
    env = dict(os.environ, SP_KIND_Z="99")  # the bar is point + CI only: no kind flags, so no second set
    env.setdefault("SP_PRIO", "12")
    for k in ("SUBSET", "CONDAB_STOPFILE", "STOP", "SET", "BASE_ND", "BIG", "CONFIRM"):
        env.pop(k, None)
    p = launch(f"confirm {plan['kind']} (stylepanel --fresh-only)", f"nice -n 10 python3 -I tools/lab/stylepanel.py {cand} {live} {rtag} {plan['args']} "
               f"--fresh-only --par {PANEL_PAR} --parent {os.getpid()}", env, os.path.join(Q, f"sc_{tag}_sp.log"))
    ride_hook(cand, live, rtag, tag, lane)
    try:
        p.wait(timeout=plan["wait"])
    except subprocess.TimeoutExpired:
        say(f"!! confirm leg not done after {plan['wait'] // 60} min: stopping it (pid {p.pid})")
        os.killpg(p.pid, signal.SIGTERM)
        p.wait()
    rows = confirm_rows(cand, live, rtag, plan)
    rows, overall = fuel_ratio(rows, cand, live, rtag)
    rows, overall = bugbar_fuel_row(rows, overall, lane)
    rows, overall = fix_careful(rows, overall, lane)
    try:  # the banks never break a check
        fuel_bank(rows, overall, cand, live, rtag, lane)
        auto_bank(rows, overall, cand, live, rtag, lane)
    except Exception as e:  # noqa: BLE001
        say(f"!! bank: {type(e).__name__}: {e}")
    L = fmt(rows, overall, cand, live, tag, lane, time.time() - t0).split("\n")
    text = "\n".join(L[:1] + ["  " + head] + L[1:])
    if overall == "INCONCLUSIVE":
        text += "\nINCONCLUSIVE CAUSE: " + inconclusive_cause(rows, tag, rtag)
    print(text)
    open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
    if overall == "PASS":
        cm = re.search(r"^([\d.]+) \[[\d.]+, [\d.]+\] n (\d+)", rows[0][1])
        tail = f" | {cand} confirm {cm.group(1) if cm else '?'} n{cm.group(2) if cm else '?'}"
        note = subject_line(lane)[:max(0, 80 - len(tail))].rstrip() + tail
        if train_take(cand, tag, lane, False, stack_vals, text, confirm=True, point=cm.group(1) if cm else None):
            return  # 10 Nov: release train on (bq/train_ON): a confirm PASS of any lane rides the next train
        if lane == "fix" and fixbatch_take(cand, tag, lane, False, stack_vals, text, confirm=True, point=cm.group(1) if cm else None):
            return  # 9 Nov 22:05Z: a fix-lane confirm PASS waits for the next fix bundle (fixbatch.py), like a plain fix PASS
        submit(cand, tag, text, note)
        if LIVE_MOVED and LIVE_MOVED[0] != live:  # as main(): a flip candidate goes back on the arm queue; shipwatch rebases a copy (confirm again, or full)
            reread_requeue(cand, lane, stack_vals, tag, live, LIVE_MOVED[0])
        return
    say(f"no submit: {overall}")
    cause = re.search(r"^INCONCLUSIVE CAUSE: (.*)$", text, re.M)
    if overall == "INCONCLUSIVE" and cause and not cause.group(1).startswith(("harness", "too rare")):
        inconclusive_requeue(cand, lane, stack_vals, tag, cause.group(1))


def main():
    a = sys.argv[1:]
    kv = dict(x.split("=", 1) for x in a if "=" in x)
    pos = [x for x in a if "=" not in x]
    if not pos[:1] or not pos[0].startswith("--"):  # 7 Nov: a running check lifts its own queued pilot legs to key 001 every minute
        def _ship_first():  # (pilotd.boost_ships; the age rule had left cq-nd2462 and cq-nd2469 behind agent screens)
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import pilotd
            while True:
                try:
                    pilotd.boost_ships()
                    pilotd.boost_top()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(60)
        import threading
        threading.Thread(target=_ship_first, daemon=True).start()
    if pos[:1] == ["--postship"]:
        return postship(*pos[1:6])
    if pos[:1] == ["--seqshadow"]:
        return seq_shadow_main(pos[1])
    if pos[:1] == ["--mech"]:
        return mech_run(*pos[1:5])
    if pos[:1] == ["--anchorcheck"]:
        return anchor_check(pos[1], pos[2])
    if pos[:1] == ["--verdict"]:
        return reverdict(pos[1], pos[2], kv.get("LANE", os.environ.get("LANE", "behaviour")), kv.get("LIVE"))
    submit_only = "--submit-only" in pos
    pos = [x for x in pos if x != "--submit-only"]
    if len(pos) < 2:
        sys.exit(__doc__)
    cand, tag = pos[0], pos[1]
    try:  # 12 Nov (Builder): kinds a line's owner-approved extra read already cleared (bq/kindflag_cleared.tsv: SLUG<TAB>dim=level,...)
        slug = cand.split("_", 2)[2] if cand.count("_") >= 2 else cand
        kc = [ln.split("#")[0].rstrip("\n").split("\t") for ln in open(os.path.join(Q, "kindflag_cleared.tsv"))]
        kinds = sorted({k for p_ in kc if len(p_) >= 2 and p_[0].strip() and slug.startswith(p_[0].strip()) for k in p_[1].split(",") if k.strip()})
        if kinds and not os.environ.get("SP_KIND_CLEAR"):
            os.environ["SP_KIND_CLEAR"] = ",".join(kinds)
            import stylepanel as _sp
            _sp.KIND_CLEAR = set(kinds)
            say(f"kind flags already cleared for this line (bq/kindflag_cleared.tsv): {', '.join(kinds)}: they neither flag nor block")
    except OSError:
        pass
    try:  # 13 Nov (Builder/b2365 OCF-P): bq/classbank_map.tsv SLUG_PREFIX<TAB>BANK_DIR: this line's fresh draws come from that screened class bank
        slug_cb = cand.split("_", 2)[2] if cand.count("_") >= 2 else cand
        for ln in open(os.path.join(Q, "classbank_map.tsv")):
            p_ = ln.split("#")[0].rstrip("\n").split("\t")
            if len(p_) >= 2 and p_[0].strip() and slug_cb.startswith(p_[0].strip()) and os.path.isdir(p_[1].strip()):
                os.environ["SP_CLASSBANK"] = p_[1].strip()
                say(f"CLASS BANK: fresh looks draw never-used maps from {p_[1].strip()} (bq/classbank_map.tsv); BIG and panel rows as usual")
                break
    except OSError:
        pass
    lane = kv.get("LANE", os.environ.get("LANE", "behaviour"))
    trigger = kv.get("TRIGGER", os.environ.get("TRIGGER"))
    if lane not in ("behaviour", "fix", "param", "draft", "ctrunk"):
        sys.exit(f"shipcheck: LANE must be behaviour, fix, param, draft or ctrunk, not {lane!r}")
    # 12 Nov (owner, 'make the shipcheck queue faster': early stop on the fix lane): the fix lane's deciding fresh leg stops early once
    # it cannot reach the lane's fresh bar (fresh_min(): .50, bug bar > .50) at z 2.5 after >= 600 map pairs. SC_FIX_EARLY=0 turns it off
    if lane == "fix" and os.environ.get("SC_FIX_EARLY", "1") == "1" and not os.environ.get("SP_FRESH_EARLY"):
        try:
            os.environ["SP_FRESH_EARLY"] = f"{float(fresh_min()):.4f},{os.environ.get('SC_FIX_EARLY_Z', '2.5')},{os.environ.get('SC_FIX_EARLY_MIN', '600')}"
        except Exception:  # noqa: BLE001
            pass
    if lane == "ctrunk":  # owner 6 Nov ("Correctness lane"): the fix lane's legs, re-decided by tools/lab/ctrunk.py; FUELX 1.5 by default
        CTRUNK[0] = True
        lane = "fix"
        os.environ.setdefault("FUELX", "1.5")
        if os.environ.get("SC_CTRUNK_FULL") != "1":  # Builder 6 Nov (owner: speed): the info-only panel and anchor are not played; BIG + one
            os.environ["SC_FIX_PANEL"] = "0"         # 600-map fresh set (pooled floor, death guard) and the gating rows stay; SC_CTRUNK_FULL=1 restores
        say("CTRUNK lane: fix-lane legs; h2h, fresh, BIG and panel informational unless pooled BIG + fresh < .48 (owner 6 Nov)"
            + ("" if os.environ.get("SC_CTRUNK_FULL") == "1" else "; panel and anchor h2h not played (SC_CTRUNK_FULL=1 plays them)"))
    rare_n = int(kv.get("RARE", os.environ.get("RARE", "0")) or 0)
    if rare_n:
        global LIVEH2H
        if lane != "fix" or CTRUNK[0]:
            sys.exit("shipcheck: RARE=N goes with LANE=fix")
        try:
            w = open(RARE_BAR).read().split()
            RARE.update({k: float(v) for k, v in zip(w[::2], w[1::2])})
            assert all(k in RARE for k in ("point", "los", "min"))
        except (OSError, ValueError, AssertionError):
            sys.exit(f"shipcheck: RARE=N: no bar in {RARE_BAR} (one line: point P los L min M; the Builder writes it)")
        RARE["n"] = max(rare_n, math.ceil(1.05 * RARE["min"]))  # a smaller read could never reach the bar's min; 5% spare for lost games
        LIVEH2H = False  # owner 7 Nov: a change that touches few maps skips the BIG ladder step
        lane = "draft"  # the draft lane's legs and rows, less the live h2h: the changed-map read decides
        os.environ.setdefault("SP_CHANGED_MAX", os.environ.get("SC_RARE_MAX", "5000000"))  # time decides, not a map count (owner 7 Nov): SP_CHANGED_WALL
        os.environ.setdefault("SP_CHANGED_WALL", os.environ.get("SC_RARE_WALL", "10800"))
        fams = kv.get("RAREFAMS", os.environ.get("RAREFAMS", ""))
        if fams:  # every second batch is drawn from these families; the pool batches keep the whole-pool share honest
            os.environ["SP_CHANGED_WFAMS"] = fams
            # 10 Nov (tws1b): families that never occur in the common pool (bq/rarefams_targeted_only.txt, e.g. w_checker_big) draw EVERY
            # batch from the family; pool batches of such a line only spend games on maps that can't change
            try:
                tonly = {x.strip() for x in open(os.path.join(Q, "rarefams_targeted_only.txt")) if x.strip() and not x.startswith("#")}
            except OSError:
                tonly = set()
            if tonly and set(fams.split(",")) <= tonly:
                os.environ["SP_CHANGED_TARGETED_ONLY"] = "1"
                say(f"RARE: {fams} never occur in the common pool: every probe batch is drawn from them (SP_CHANGED_TARGETED_ONLY)")
        os.environ.setdefault("PILOTCXE_PRIO", "12")  # a deciding read; 10 Nov 20:10Z: 11 -> 12 (hlr1s rare probe sat 89 min behind prio-11 reads)
        say(f"RARE {rare_n}: fix lane, read only on maps where the games differ; bar {RARE}")
    if lane == "draft":
        os.environ.setdefault("SP_DRAFT_MAX", os.environ.get("SC_DRAFT_MAX", "40000"))  # owner 4 Nov: probe to 40,000 maps or 4 h, then decide on what was found
    bh = kv.get("BASEHAS", os.environ.get("BASEHAS", ""))
    if bh:  # 8 Nov: draftstock filter on the probe's maps; every stylepanel below inherits it through the environment; the bars don't change
        if lane != "draft":
            sys.exit("shipcheck: BASEHAS goes with LANE=draft or RARE=N")
        os.environ["SP_BASE_HAS"] = bh
        say(f"BASEHAS {bh}: the probe draws from draftstock.py's stock, only maps passing the filter; ~300 maps outside it check coverage (INCONCLUSIVE under .95)")
    wf = kv.get("WFAMS", os.environ.get("WFAMS", "")).strip()
    if wf:  # 11 Nov (TB 06b512, Econ GRC): every stylepanel below draws only these generator families (stratmaps --wfams F --weird 1)
        os.environ["SP_WFAMS"] = wf
        say(f"WFAMS {wf}: the fresh and panel maps are drawn from these generator families only; BIG unchanged")
    cls = kv.get("CLASS", os.environ.get("CLASS", "")).strip()
    if cls:  # 10 Nov (Planner): a class read; every stylepanel below (fresh, sequential looks, near miss, confirm, panel) inherits SP_CLASS and draws
        #      only maps of that class (stratmaps --class); the BIG / live h2h legs are unchanged, so the fresh and pooled rows mean class maps
        os.environ["SP_CLASS"] = cls
        say(f"CLASS {cls}: the fresh and panel maps are class maps only (stratmaps --class); BIG unchanged; fresh rows and pooled BIG+fresh read the class")
    if lane == "param" and not LIVEH2H:
        sys.exit("shipcheck: LANE=param is decided by the live h2h: SC_LIVEH2H=0 does not apply")
    if lane == "param" and trigger:
        say("TRIGGER ignored: LANE=param has no trigger legs")
        trigger = None
    live, ver, parent = live_bot()
    start_live = live  # parallel mode: a PASS refused because live moved since here is re-read (reread_requeue)
    say(f"shipcheck {tag}: {cand} vs live {live} (v{ver or '?'}), lane {lane}{', DRY' if DRY else ''}")
    stack = kv.get("STACK_ON", os.environ.get("STACK_ON", ""))
    stack_head = lambda: live_bot()[0] if DRY else open(LIVEFILE).readline().split()[1]  # noqa: E731  (live_bot warns on every read while CLAUDE.md lags)
    stack_vals = kv.get("LIVEVALS", os.environ.get("LIVEVALS", ""))
    if stack:
        os.environ["STACK_ON"] = stack  # submit() reads it inside the lock
        if not shipstack.enabled(Q) and not DRY:  # DRY cannot submit, so it may test this with the switch off
            print(f"REFUSED: STACK_ON={stack} but stacking is off ({shipstack.SWITCH} is not in {Q})")
            sys.exit(3)
        fa, fb = flip_info(stack) or {}, flip_info(cand) or {}
        why = shipstack.check(shipstack.parse_flips(fb.get("FLIPS", "")), shipstack.parse_flips(stack_vals),
                              shipstack.parse_flips(fa.get("FLIPS", "")), fb.get("TRUNK"), fa.get("TRUNK"))
        if why:
            print(f"REFUSED: STACK_ON={stack}: {why}")
            sys.exit(3)
        if shipstack.a_state(stack, stack_head, Q) == "failed":
            print(f"STACK VOID: {stack} ended without shipping, before this check played a game")
            return stack_requeue(cand, lane, stack_vals)
        say(f"STACKED on {stack}: this read is {cand} vs {stack}'s values; no submit unless {stack} is the live head")
    global TIMEBOX
    if TB_SCALE:
        TIMEBOX, tbn = load_timebox(TIMEBOX)
        say(f"timebox {TIMEBOX / 60:.1f} min ({tbn}; base {int(os.environ.get('SHIPCHECK_TIMEBOX', 720)) / 60:.0f}, "
            f"cap {TB_MAX / 60:.0f}); every leg may extend once by {NC_EXT / 60:.0f} min at >= {float(EXT_FRAC):.0%} of jobs back")
    os.environ["CONDAB_EXT_FRAC"] = EXT_FRAC
    trunk_mode = bool(kv.get("TRUNK") or os.environ.get("TRUNK") or (flip_info(cand) or {}).get("TRUNK"))
    direct = False  # TRUNK mode with no flips: CAND has the base's source, so its legs play the real live bot
    set_sameplay(cand)
    if trunk_mode:  # TRUNK mode: the flip candidate plays the trunk at live values; that one leg replaces vs-live and vs-NULL
        lvals = kv.get("LIVEVALS", os.environ.get("LIVEVALS", ""))
        shadow = kv.get("SHADOW", os.environ.get("SHADOW", "")).strip() if RARE else ""
        if shadow:  # CI Analyser 10 Nov (spec_akx_1110 A4; vkn60 84% and vlt 90% 'changed' at .09/g firing): the base is the SHADOW twin, the
            # trunk with the donor's compute-only flips, so the rare legs read CAND v SHADOW (same work until the rule acts: changed = firing) and
            # the trunk-code row reads SHADOW v live (the cost of carrying the code, fuel included). Every SHADOW flag must be one CAND flips.
            cf = dict(x.split("=", 1) for x in ((flip_info(cand) or {}).get("FLIPS", "")).split() if "=" in x)
            sf = dict(x.split("=", 1) for x in shadow.split() if "=" in x)
            if stack or not sf or not set(sf) <= set(cf):
                print(f"REFUSED: SHADOW {shadow!r}: every shadow flag must be one of CAND's flips ({' '.join(sorted(cf)) or 'none'}), no STACK_ON")
                sys.exit(3)
            lv = dict(x.split("=", 1) for x in lvals.split() if "=" in x)
            lv.update(sf)
            lvals = " ".join(f"{k}={v}" for k, v in lv.items())
        ok, why, base = trunk_check(cand, lvals)
        if shadow:
            why += f"; SHADOW twin {shadow} (rare legs read CAND v SHADOW; the trunk-code row reads SHADOW v live)"
        if not ok:
            print(f"REFUSED: TRUNK mode: {why}")
            sys.exit(3)
        tok, twhy = base_check(base, live, parent)  # the trunk at live values: LIVEVALS supplies live's flags (2 Nov: 14/15 refused a good bundle)
        if not tok:
            print(f"REFUSED: TRUNK mode: the trunk is not built on live {live} ({twhy}); rebuild the trunk first")
            # 12 Nov (hsk33csi 12734 / ntg1s 12733 started 34 s after v802 shipped and were dropped: armq's 'live moved before its
            # shipcheck' requeue only sees markers that have not started): put the line's own flips back at the front for the new live;
            # a confirm copy keeps its CONFIRM_FROM with CONFIRM_N + 1 (cap CONFIRM_MAX), as a rebase before its start does
            try:
                cf = None
                if os.environ.get("CONFIRM_FROM"):
                    cn = int(os.environ.get("CONFIRM_N") or 1) + 1
                    cf = (os.environ["CONFIRM_FROM"], cn) if cn <= CONFIRM_MAX else None
                stack_requeue(cand, lane, lvals, "s", confirm=cf)
            except Exception as e:  # noqa: BLE001  a refusal must still exit 3
                say(f"requeue after the start refusal failed: {e!r}")
            sys.exit(3)
        tc_base = base
        if stack:  # the code row reads the trunk at the real live's values vs live: the flips it stands on are this read's base, not code live lacks
            import fastship
            lv, tv = fastship.values(live), fastship.values((flip_info(cand) or {}).get("TRUNK"))
            aok, awhy, tc_base = trunk_check(cand, " ".join(f"{k}={v}" for k, v in lv.items() if k in tv and tv[k] != v))
            if not aok:
                print(f"REFUSED: STACK_ON={stack}: {awhy}")
                sys.exit(3)
        how, tc = trunk_read(cand, tc_base, live)
        TRUNK_CODE.update(tc)
        if tc.get("verdict") == "FAIL":  # 2 Nov: legs on a trunk already failed cost 47k games for a verdict known at the start
            text = (f"SHIPCHECK {tag}: {cand} on {base}, lane {lane}: not played\n  trunk code vs live   gate {tc['tag']} already FAIL ({tc['file']})\n  OVERALL: FAIL")
            print(text)
            open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
            say("no submit: FAIL")
            return
        say(f"TRUNK mode: {why}; trunk built on live {live} ({twhy[:80]}); {how}, no NULLSW leg")
        if lane == "behaviour":
            os.environ["SC_FRESH_DECIDES"] = "1"
            say(f"FRESH DECIDES: the per-run fresh leg ({fresh_n_decides()} new maps, pooled >= {FRESH_MIN}, CI upper >= 0.50) decides; "
                f"the live h2h needs LOS >= 90%; no power extension")
        global NULLSW
        NULLSW = ""
        direct = hash_of(cand) == hash_of(base)
        if not direct:
            live = base
    ok, why = (True, "TRUNK mode (checked above)") if trunk_mode else base_check(cand, live, parent)
    # 11 Nov (Builder/Coordinator: panel D read ~-.009 on every v756 check): the shared panel leg's base side is the bot the candidate
    # is BUILT on. Candidates on the baked diff base (nova_base_vNNN) were read v the unbaked live, which plays other games at the real
    # budget (nova_base_v756 v cwsq1 on the shared set: .781/.801/.790 v .782/.812/.806, 10-13% of maps differ). SC_PANEL_LIVE=1: old way.
    _db = diffbase_of(start_live)
    _built = (twhy if trunk_mode else why) or ""
    panel_base = _db if (_db and _db in _built and os.environ.get("SC_PANEL_LIVE", "0") != "1") else start_live
    if not ok and lane == "param":  # live + numbers only is built on live, even when a number sits on live's own line
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import paramdiff
        pr = paramdiff.check(cand, live)
        if pr["ok"]:
            ok, why = True, f"{pr['reason']} vs {live} (base rule: {why[:80]})"
    if not ok:
        print(f"REFUSED: rebase onto live first ({cand} is not built on {live}: {why})")
        sys.exit(3)
    say(f"base check: {cand} is built on {live} ({why})")
    if os.environ.get("SC_AFFECTS", "1") != "0" and not submit_only:
        # 12 Nov ~20:5xZ (owner: "with updates in the message can you put percentage of maps each update affects"): a detached
        # tools/lab/affects.py run (100 new maps x 2 seats at unlimited fuel, pilots, low priority) logs 'affects NAME: X% of maps'
        # to shipwatch.log and bq/affects.tsv; information only, never waited on
        try:
            subprocess.Popen(["nice", "-n", "15", sys.executable, "-I", os.path.join(REPO, "tools/lab/affects.py"), cand, live, str(tag), cand],
                             cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
    if not kv.get("CONFIRM_FROM", os.environ.get("CONFIRM_FROM", "")).strip():  # CONFIRM MODE: no info-only legs
        bugbar_gate(cand, live, lane, stack_vals)  # info row: changed-games share of a BUGBAR line (owner 9 Nov: no refusal)
    if not stack and ident_ship(cand, live, lane, tag):  # owner 12 Nov ~14:4xZ: a verified play-identical fuel cut ships on identity
        return
    if os.environ.get("MERGECHECK") != "0" and not trunk_mode:  # merge-integrity agent (a flip is data-only: wsec checked it), 1 Nov: static merge check (~2 s) before any leg
        donors = sum((["--donor", d] for d in os.environ.get("DONORS", "").split(",") if d), [])
        mc = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/mergecheck.py"), cand, live, "--quiet",
                             "--no-build", "--no-play"] + donors, capture_output=True, text=True)
        say(mc.stdout[-2500:].rstrip() or mc.stderr[-800:])
        if mc.returncode != 0:
            print("REFUSED: mergecheck FAIL (tools/lab/mergecheck.py; MERGECHECK=0 skips)")
            sys.exit(5)
    other = claim_tag(tag, cand)
    if other:
        print(f"REFUSED: TAG {tag} was used by {other}: its runs (nd{tag}, cf{tag}, sc_{tag}_*, subsets/sub_{tag}.txt) "
              f"would be overwritten; pick a new TAG")
        sys.exit(4)
    if not submit_only:
        try:
            pass
        except Exception:  # noqa: BLE001  an info row never stops a shipcheck
            pass
    if submit_only:
        rows = [("(submit-only test)", "-", "-", "PASS")]
        if os.environ.get("POSTSHIP_SUBSET") and os.environ.get("BASE_ND"):  # tests: a fake gate subset
            os.makedirs(os.path.join(Q, "postship"), exist_ok=True)
            shutil.copyfile(os.environ["POSTSHIP_SUBSET"], os.path.join(Q, "postship", f"{tag}.subset"))
            POSTSHIP_ND["bnd"] = os.environ["BASE_ND"]
        submit(cand, tag, fmt(rows, "PASS", cand, live, tag, lane, 0), f"{tag} {cand} shipcheck submit-only test")
        return
    rtag = run_tag(tag, cand, live)  # run names that no other bot pair owns (29 Oct: nd261/nd262 held by older bots)
    if RARE:
        RARE["tag"] = rtag
    os.environ["SC_RTAG"] = rtag      # inherited by the --mech and --postship runs
    if rtag != tag:
        say(f"run names: nd{tag}/cf{tag}/kp{tag}/ps{tag} belong to another bot pair: this check's runs are nd{rtag}, cf{rtag}, ...")
    cf_from = kv.get("CONFIRM_FROM", os.environ.get("CONFIRM_FROM", "")).strip()
    if cf_from and stack:
        say(f"CONFIRM_FROM={cf_from} ignored: a STACK_ON read gets the full check")
    elif cf_from:  # CONFIRM MODE (owner 9 Nov): the base and merge checks above passed; one fresh leg v the real live decides
        CONFIRM.update({"from": cf_from, "n": kv.get("CONFIRM_N", os.environ.get("CONFIRM_N", "1"))})
        return confirm_main(cand, tag, rtag, start_live, ver, lane, stack_vals)
    opp = "nova_spar_nochase2"
    t0 = time.time()
    trig = None
    n_sub = int(os.environ.get("SUBSET", "300"))
    # SC_REF_LIVE (7 Nov, Builder for the owner's speed task; default on, SC_REF_LIVE=0 = the old per-check subset and trunk base):
    # the nochase2 reference is the REAL live bot's games on a subset drawn once per live version, so the 600 reference games are
    # played by the first check after a ship and reused (game index) by every later one. In TRUNK mode the reference was the
    # per-check trunk (36o, 36q: new hashes, 0 index hits, 600 games each); D now reads CAND v live, the bot it would replace.
    ref_live = os.environ.get("SC_REF_LIVE", "1") != "0"
    ref_bot = start_live if ref_live else live
    ref_seed = f"sub:{start_live}:{n_sub}" if ref_live else None
    if trigger:  # the nochase2 subset holds every trigger map (+ a random fill), trigger maps in the first jobs
        sf, tin, tout = trigger_subset(rtag, trigger, n_sub, seed=ref_seed)
        import condab as _cb
        npool = len(set(tin) & set(_cb.set_maps("all")))
        say(f"trigger: {len(tin)} trigger maps installed ({npool} of them in the 636 pool)"
            + (f", {len(tout)} not installed (left out): {' '.join(tout[:10])}" if tout else "")
            + f"; subset {sf} = trigger maps + a fresh random fill")
        trig = dict(maps=tin, file=os.path.join(Q, "subsets", f"trig_{rtag}.txt"), h2h=nonc(lane) or not HAVE_ND)
    else:
        sf, _, _ = trigger_subset(rtag, None, n_sub, seed=ref_seed)  # family-stratified random subset (as scr.sh's SUBSET); one per live with SC_REF_LIVE
    env = dict(os.environ, BASE=live, H2H="0", SMOKE=os.environ.get("SMOKE", "0"), SET=sf, CONDAB_TIMEBOX=str(TIMEBOX))
    env.setdefault("SP_PRIO", "12")  # 2 Nov: ahead of agents' gate legs (10, 0), which tied with or outranked this check's panel and trunk code row
    env.setdefault("KG_PRIO", "12")
    env.pop("SUBSET", None)
    env.pop("CONDAB_STOPFILE", None)
    stopf = os.path.join(Q, f"sc_{rtag}.stop")  # SC_LH_EARLY: written once the live h2h FAILED; every condab leg then stops
    if os.path.exists(stopf):
        os.remove(stopf)
    if LH_EARLY and LIVEH2H:
        env["CONDAB_STOPFILE"] = stopf
    if TRUNK_CODE:
        def tc_watch():  # the code row failed mid-check: the verdict is known, so its other legs stop
            while True:
                m = re.search(r"OVERALL: (\w+)", read(TRUNK_CODE["file"]))
                if m:
                    if m.group(1) == "FAIL" and tc_judge(read(TRUNK_CODE["file"]))[0] == "FAIL":  # 11 Nov: the score bar (fuel-only = PASS)
                        say("trunk code row FAIL: stopping this check's legs")
                        open(stopf, "w").close()
                    return
                time.sleep(20)
        threading.Thread(target=tc_watch, daemon=True).start()
    if stack:
        def stack_watch():  # A failed: B's read is void, so its legs stop now
            while True:
                st = shipstack.a_state(stack, stack_head, Q)
                if st != "running":
                    if st == "failed":
                        say(f"{stack} ended without shipping: stopping this check's legs")
                        open(stopf, "w").close()
                    return
                time.sleep(30)
        threading.Thread(target=stack_watch, daemon=True).start()
    if nonc(lane):
        say("SC_FIX_NONC: fix lane: no nochase2 / CONFIRM legs; the live h2h decides (change size from its maps)" if lane == "fix" else
            (f"RARE: no live h2h, no nochase2 / CONFIRM legs; the read on {RARE['n']} changed maps decides" if RARE else
             f"LANE=draft: no nochase2 / CONFIRM legs; BIG no-harm (point >= {DRAFT_BIG}) + the read on {DRAFT_N} draft-changed maps decide"))
    if lane in ("fix", "draft"):
        env.pop("STOP", None)
    else:
        env["STOP"] = "1" if trig else "2"  # with a trigger list no early PASS before the trigger maps are back
    if trig:
        env["CONDAB_FIRST"] = trig["file"]
    for k in ("CONFIRM", "KEEP", "CONDAB_FORCE"):
        env.pop(k, None)
    # ubaudit's instrumented build is the only local compile of a shipcheck (once per source hash, ubaudit's build lock);
    # cmake --build ran ninja at nproc + 2 jobs, ~36 clang++ per build with ~10 audits at once (load ~290 on 16 cores, 29 Oct)
    ub_env = dict(env, CMAKE_BUILD_PARALLEL_LEVEL=os.environ.get("UB_BUILD_JOBS", "4"))
    procs = {}
    if lane != "param" and not nonc(lane):
        cf_env = dict(env, CONFIRM="100", CONDAB_TIMEBOX_EXT=str(NC_EXT))
        if lane in ("behaviour", "draft") and os.environ.get("SC_TEMPO", "1") == "1":  # 10 Nov (Planner/Deep): keep the replays for tempocheck
            cf_env["OTF_KEEP"] = os.path.join(Q, "tempo", tag)
        procs["cf"] = launch("CONFIRM=100", f"nice -n 10 sh tools/lab/condab.sh {cand} {live} cf{rtag}", cf_env, os.path.join(Q, f"sc_{tag}_cf.log"))
    ub_skip = None
    if trunk_mode and not direct and os.environ.get("SC_FLIP_UB", "skip") == "skip":  # 1 Nov (Builder speed item 3): a verified data-only flip
        # (trunk_check: wsec code section IDENTICAL to the audited trunk) skips ubaudit, the slowest local leg. Residual risk: the
        # flag-on paths run under the sanitizer only if the trunk's audit set them; SC_FLIP_UB=run audits anyway. The capped
        # fuel row stays: a data flip can change fuel (bundle 24's LETHAL_BURST flip read 1.16x), and it costs no games.
        ub_skip = "ubaudit skipped: data-only flip (wsec code IDENTICAL to the trunk)"
        say(ub_skip)
    if lane == "param":  # a param-only diff vs live needs no UB audit (docstring 1., LANE=param)
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import paramdiff
        pr = paramdiff.check(cand, live)
        if pr["ok"]:
            ub_skip = f"ubaudit skipped: {pr['reason']}"
            say(ub_skip + ": " + "; ".join(f"{f}:{ln} {n[:60]}" for f, ln, _, n in pr["changes"][:4]))
        else:
            say(f"paramdiff: {pr['reason']}: ubaudit runs")
    if not ub_skip:
        procs["ub"] = launch("ubaudit", f"sh tools/lab/ubaudit.sh {cand} {live}", ub_env, os.path.join(Q, f"sc_{tag}_ub.log"))
    if trigger and trig and trig.get("h2h"):  # SC_FIX_NONC: CAND vs LIVE on the trigger maps (VACUOUS when none changed)
        procs["th"] = launch("trigger h2h (CAND vs LIVE on the trigger maps)",
                             f"nice -n 10 sh tools/lab/condab.sh {cand} {live} th{rtag} {shlex.quote(trig['file'])}",
                             {k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="10").items()
                              if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND")},
                             os.path.join(Q, f"sc_{tag}_th.log"))
    if trigger and not (trig and trig.get("h2h")):
        procs["tr"] = launch("trigger ref (live vs nochase2 on the trigger maps)",
                             f"nice -n 10 sh tools/lab/condab.sh {live} {opp} trl{live.split('_')[1]}_{rtag} "
                             f"{shlex.quote(trig['file'])}", {k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="5").items()
                                                             if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST")},
                             os.path.join(Q, f"sc_{tag}_tr.log"))
    if trigger and not ub_skip:
        procs["ub2"] = launch("ubaudit SEED=2", f"sleep 2; sh tools/lab/ubaudit.sh {cand} {live}", dict(ub_env, SEED="2"),
                              os.path.join(Q, f"sc_{tag}_ub2.log"))
    ff = fresh_first_screen(cand, live, rtag, tag, lane, env, procs, base)  # owner 12 Nov: no-harm legs only after the fresh read
    if ff:
        print(ff)
        open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(ff + "\n")
        say("no submit: FAIL")
        return
    half_noharm(lane)  # owner 12 Nov: half-size BIG and panel while pilots are short; default once they recover
    t_lh = time.time()
    FIX_LEAN = lane == "fix" and fix_lean()  # 12 Nov owner: lean fix checks while ideas wait (fix_lean)
    if lane == "fix":
        print(f"fix lane form: {'LEAN (BIG2-only h2h, no panel; ideas waiting)' if FIX_LEAN else 'STRICT (full pool + panel)'}", flush=True)
        try:  # 12 Nov (Coordinator): one line per fix check, so the first LEAN/STRICT switch can be relayed to the owner
            open(os.path.join(Q, "fix_form.log"), "a").write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} {'LEAN' if FIX_LEAN else 'STRICT'}\n")
        except OSError:
            pass
    if LIVEH2H:
        # 11 Nov (owner: "go ahead ... as long as you can reason about it"; agreed form "BIG first 2,000 point >= .495"): under FRESH-LED the
        # behaviour lane's BIG row is no-harm only, so it plays the 2,000 ladder-weighted BIG maps (BIG=2000 on an empty SET), not the ~6,150
        # killgate-pool maps besides (~12k games a check). The fix lane keeps the full set: its bug-bar harm bound (CI lower >= .4975) needs the width.
        # 12 Nov (owner "sure apply both", then "if you run out of ideas revert to being more strict"): the fix lane also plays BIG2 only and
        # skips the panel while ideas wait (fix_lean()); with the armq queue empty, or bq/fix_strict present, it plays the full pool + panel.
        lh_set = os.path.join(Q, "subsets", "empty.txt") if FRESH_LED and (lane == "behaviour" or (lane == "fix" and FIX_LEAN)) and LH_BIG and os.environ.get("SC_LH_FULL", "0") != "1" else "all"
        procs["lh"] = launch("live h2h (full pool)" if lh_set == "all" else f"live h2h (BIG {LH_BIG} only, no-harm)", f"nice -n 10 sh tools/lab/condab.sh {cand} {live} lh{rtag} {lh_set}",
                             dict({k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="10", CONDAB_TIMEBOX_EXT=str(NC_EXT)).items()
                                   if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND")},
                                  **({"STOP": "1", "CONDAB_HI_FAIL": f"{early_bar(lane)},{LH_EARLY_Z},{LH_EARLY_MIN}"}
                                     if LH_EARLY else {}), **({"BIG": str(LH_BIG)} if LH_BIG else {})),
                             os.path.join(Q, f"sc_{tag}_lh.log"))
    sp_deadline = None
    if PANEL:  # owner 1 Nov: new stratified maps + the playstyle panel (stylepanel.py writes sp<rtag>.txt)
        procs["sp"] = launch("fresh maps + playstyle panel (stylepanel.py)",
                             f"nice -n 10 python3 -I tools/lab/stylepanel.py {cand} {live} {rtag} "
                             + (f"--n {RARE['n']} --changed {RARE['n']} --panel-n 600 " if RARE else
                                f"--n {DRAFT_N} --draft-changed {DRAFT_N} --panel-n 600 " if lane == "draft" else
                                f"--n {fresh_n_decides()} --panel-n {PANEL_N_SC[0]} --fresh-min {FRESH_MIN} " if fresh_decides(lane) else
                                (f"--n {FRESH_N_FIX} --panel-n 600 " if fix_fresh_led() and lane == 'fix' else f"--n {FRESH_N} ") if (trunk_mode or nonc(lane)) and FIX_FRESH else f"--n {PANEL_N} ")  # fix (TRUNK or direct): 600 (eff_lane)
                             + f"--par {PANEL_PAR} --parent {os.getpid()} --reuse-fresh auto"  # 1 Nov: adopt a gate.py fresh read of the same sources
                             # owner 7 Nov ~15:40Z: the panel's base side is the real live bot on one map set per live version, played once
                             # and reused by every check on that live (stylepanel --panel-shared; not for RARE or draft, whose panel stays on
                             # their changed maps). SC_PANEL_SHARED=0 restores the per-check panel maps and trunk base.
                             + (f" --panel-shared {panel_base}" if not RARE and lane != "draft" and os.environ.get("SC_PANEL_SHARED", "1") != "0" else "")
                             + (" --fresh-only" if lane == "fix" and (os.environ.get("SC_FIX_PANEL", "1") == "0" or FIX_LEAN) else ""),  # owner 2 Nov: every lane plays the panel
                             env, os.path.join(Q, f"sc_{tag}_sp.log"))
        sp_deadline = time.time() + PANEL_WAIT + (int(os.environ.get("SC_DRAFT_WAIT", 16200)) if lane == "draft" else 0) + (int(os.environ.get("SC_RARE_WAIT", 10800)) if os.environ.get("RARE") else 0)  # draft: the probe first; 10 Nov: rare probes run at the back of the queue (owner), so they get up to 3 h more instead of a timebox INCONCLUSIVE (akx7g)
        ride_hook(cand, live, rtag, tag, lane)
    if fuel_pct() > 0:
        FUEL_FIRST["t"] = threading.Thread(target=heavy_go, args=(cand, live, rtag), daemon=True)
        FUEL_FIRST["t"].start()
    if MANYGRP_N > 0 and not RARE and lane in ("behaviour", "fix", "fixmid"):  # 11 Nov (Builder/RC X306: TSO1 hid on 65-130-group maps)
        procs["mg"] = launch(f"many-group fuel (information): {MANYGRP_N} new w_manygrp maps",
                             f"nice -n 10 python3 -I tools/lab/stylepanel.py {cand} {live} {rtag}mg --n {MANYGRP_N} --fresh-only --par 4 --parent {os.getpid()}",
                             dict({k: v for k, v in env.items() if k not in ("SUBSET", "CONDAB_STOPFILE", "STOP", "SET", "BASE_ND", "BIG", "SP_CLASS")},
                                  SP_WFAMS="w_manygrp", SP_KIND_Z="99", SP_PRIO="11"), os.path.join(Q, f"sc_{tag}_mg.log"))
    if TRUNK_CODE and not TRUNK_CODE.get("verdict"):
        # 13 Nov (TB, 13916 lces: the trunk-code gate's kind re-read drew 600 maps under the rare line's class lcee_any:>=1, ~1% pass, 90+ min):
        # the trunk-code row reads the pool, never the candidate's class
        procs["tc"] = launch(f"trunk code vs live ({TRUNK_CODE['base']} vs {TRUNK_CODE['live']}, gate {TRUNK_CODE['tag']})", TRUNK_CODE["cmd"],
                             {k: v for k, v in env.items() if k not in ("SP_CLASS", "SP_CLASS_TAG")},
                             os.path.join(Q, f"sc_{tag}_tc.log"))
    if LIVEH2H and nonc(lane) and NULLSW:  # NULLSW (31 Oct): the change size vs a switch-off copy, not vs live
        nb, why = make_null(cand, rtag)
        say(f"NULLSW={NULLSW}: {why}")
        if nb:
            NULL_RUN.update(name=f"nl{rtag}", bot=nb)
            procs["nl"] = launch(f"null-switch change size ({cand} vs {nb})", f"nice -n 10 sh tools/lab/condab.sh {cand} {nb} "
                                 f"nl{rtag} all", {k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="10").items()
                                                  if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND",
                                                               "BIG", "BIGSET", "CONDAB_HI_FAIL")},
                                 os.path.join(Q, f"sc_{tag}_nl.log"))
    if lane == "param":  # the extension starts with the live h2h (both always decide), unless an identical run exists
        rx = os.environ.get("SC_REUSE_LX")
        why = reuse_lx(rx, cand, live, rtag) if rx else "not asked"
        if why is None:
            say(f"extension: reusing {rx}.condor.txt as lx{rtag} (CAND and LIVE sources unchanged)")
        else:
            if rx:
                say(f"extension: not reusing {rx} ({why}): playing it")
            procs["lx"] = launch(f"live h2h extension (CONFIRM={PM_LX_N})",
                                 f"nice -n 10 sh tools/lab/condab.sh {cand} {live} lx{rtag}",
                                 {k: v for k, v in dict(env, CONFIRM=str(PM_LX_N), CONDAB_PRIO="10",
                                                        CONDAB_TIMEBOX=str(TIMEBOX + NC_EXT)).items()
                                  if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND", "KEEP",
                                               "CONDAB_TIMEBOX_EXT")}, os.path.join(Q, f"sc_{tag}_lx.log"))
    lx = {}

    def lx_watch():  # the power extension: started as soon as the 636-map read is in and triggers it
        try:
            procs["lh"].wait()
            lt = read(os.path.join(Q, f"lh{rtag}.condor.txt"))
            r1 = map_read(lt)
            if lh_early(lt) or not lx_trigger(r1, eff_lane(lt, lane, cand, live)[0]):  # fix lane > 50% changed: behaviour
                return
            note = os.path.join(Q, f"lx{rtag}.note")
            if LH_BIG:  # the BIG extension (big_plan): the pool + the whole bank, or a FAIL on power without any games
                plan = big_plan(r1)
                if plan[0] == "power":
                    open(note, "w").write(f"lx: not run: projected CI lower {plan[1]:.3f} at {636 + BANK_MAX} maps\n")
                    return say(f"BIG extension not run: at {636 + BANK_MAX} maps the projected CI lower would be {plan[1]:.3f} < 0.5")
                say(f"BIG extension: live h2h {r1['score']:.3f} [{r1['lo']:.3f}, {r1['hi']:.3f}]: the pool + all {BANK_MAX} bank maps "
                    f"(the first {LH_BIG} from the index)")
                lx["p"] = launch(f"live h2h BIG extension (BIG={BANK_MAX})", f"nice -n 10 sh tools/lab/condab.sh {cand} {live} lx{rtag} all",
                                 {k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="10", BIG=str(BANK_MAX),
                                                        CONDAB_TIMEBOX=str(max(300, LX_EXTRA_BIG - 60))).items()
                                  if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND", "KEEP", "CONFIRM",
                                               "CONDAB_TIMEBOX_EXT", "CONDAB_HI_FAIL")}, os.path.join(Q, f"sc_{tag}_lx.log"))
                return
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
            import condab as _cb
            while True:  # room under the job cap (CONDAB_CAP, 400): at most 100 jobs of >= 12 games, or wait
                tot = _cb.sh_out(["condor_q", "-totals"]).strip().split("\n")
                mq = re.search(r"(\d+) jobs;", tot[-1] if tot else "")
                room = CAP - (int(mq.group(1)) if mq else CAP) - 5
                if room >= 2 * LX_N // 48 + 1:
                    break
                if time.time() > lh_deadline + LX_EXTRA - 360:
                    open(note, "w").write(f"lx: skipped: no room under the {CAP}-job cap ({room + 5} free)\n")
                    return say(f"power extension skipped: no room under the {CAP}-job cap")
                time.sleep(30)
            per = max(12, -(-2 * LX_N // min(room, 100)))
            tb = int(lh_deadline + LX_EXTRA - 120 - time.time())
            say(f"power extension: live h2h {r1['score']:.3f} [{r1['lo']:.3f}, {r1['hi']:.3f}] LOS {r1['los'] * 100:.0f}%: "
                f"{LX_N} more maps, {per} games a job, timebox {tb / 60:.1f} min")
            lx["p"] = launch(f"live h2h power extension (CONFIRM={LX_N})", f"nice -n 10 sh tools/lab/condab.sh {cand} {live} lx{rtag}",
                             {k: v for k, v in dict(env, CONFIRM=str(LX_N), CONDAB_PRIO="10", CONDAB_PER_JOB=str(per),
                                                    CONDAB_TIMEBOX=str(max(120, tb))).items()
                              if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND", "KEEP",
                                           "CONDAB_TIMEBOX_EXT")}, os.path.join(Q, f"sc_{tag}_lx.log"))
        except Exception as e:  # noqa: BLE001  (the extension must never break the gate: no result = INCONCLUSIVE)
            say(f"!! power extension failed to start: {type(e).__name__}: {e}")

    def lh_fail_watch():  # SC_LH_EARLY: once the live h2h leg is back with a FAIL row, every other Condor leg stops
        try:
            procs["lh"].wait()
            lt = read(os.path.join(Q, f"lh{rtag}.condor.txt"))
            val, lbar, v1, _, _ = lh_row(lt, lane, cand, live)
            if v1 == "FAIL" and lh_nearmiss(val, lbar, lane):  # 4 Nov (1349): the extension pools this check's fresh leg, so it plays on
                say(f"live h2h FAILED ({val}) inside the near-miss band: no stop file, the fresh leg plays on for the extension")
            elif v1 == "FAIL":
                open(stopf, "w").write(f"live h2h FAIL: {val}\n")
                say(f"live h2h FAILED ({val}): wrote {stopf}: the other Condor legs remove their own clusters")
        except Exception as e:  # noqa: BLE001  (the watcher must never break the gate)
            say(f"!! live h2h watcher: {type(e).__name__}: {e}")

    if LH_EARLY and LIVEH2H:
        threading.Thread(target=lh_fail_watch, daemon=True).start()
    lx_thread = None
    if LIVEH2H:
        lh_deadline = t_lh + TIMEBOX + 120 + NC_EXT
    if LIVEH2H and lane != "param":  # (SC_LH_BIG: the BIG extension, big_plan)
        lx_thread = threading.Thread(target=lx_watch, daemon=True)
        lx_thread.start()
    an_bot, an_ver = anchor()
    if CTRUNK[0] and os.environ.get("SC_CTRUNK_FULL") != "1":  # Builder 6 Nov (owner: speed): ctrunk skips the info-only anchor h2h
        an_bot = None
    if an_bot and os.path.isdir(os.path.join(REPO, "bots", an_bot, "src")):
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import abindex
        os.environ["SC_ANCHOR"] = an_bot
        if abindex.bot_hash(an_bot) == abindex.bot_hash(cand):
            os.environ["SC_ANCHOR_SAME"] = "1"
        else:
            antag = run_tag(f"an{rtag}", cand, an_bot, prefixes=("",))[2:]
            os.environ["SC_ANTAG"] = antag
            # owner 7 Nov ~15:40Z (via the Builder): behaviour checks play the anchor on the published ladder pool (128 maps, both seats;
            # tools/lab/pubpool.py writes the list), not the 300-map subset: fixed maps, so a re-read of the same candidate hits the index.
            # SC_ANCHOR_SET=FILE overrides; SC_ANCHOR_POOL=0 keeps the subset.
            an_set = os.environ.get("SC_ANCHOR_SET") or (PUBPOOL if lane == "behaviour" and os.environ.get("SC_ANCHOR_POOL", "1") != "0"
                                                         and os.path.exists(PUBPOOL) else sf)
            procs["an"] = launch(f"anchor h2h vs {an_bot} (v{an_ver})", f"nice -n 10 sh tools/lab/condab.sh {cand} {an_bot} an{antag} "
                                 f"{shlex.quote(an_set)}", {k: v for k, v in dict(env, OTF="0", CONDAB_TIMEBOX_EXT=str(NC_EXT)).items()
                                                        if k not in ("STOP", "STOP_REF", "CONDAB_FIRST")},
                                 os.path.join(Q, f"sc_{tag}_an.log"))
    bnd, scr_deadline = None, 0
    if lane != "param" and not nonc(lane) and HAVE_ND:  # LANE=param, SC_FIX_NONC, or no nochase2 bot: no nochase2 leg
        # live's nochase2 reference on the subset: right after a ship it has none (v295/v296, 29-30 Oct), so play it first
        bnd = os.environ.get("BASE_ND") or ref_runs(ref_bot)
        sub = [x.strip() for x in open(sf) if x.strip()]
        # 31 Oct 02:30 (Builder: 471r331 and 455ft topped up live's reference at the same moment and both failed): one
        # top-up per live bot at a time (a lock); a check that waited re-reads what the other one played. A failed top-up
        # is retried twice, a minute apart.
        os.makedirs(os.path.join(Q, ".reflock"), exist_ok=True)
        rlk = open(os.path.join(Q, ".reflock", ref_bot + ".lock"), "a")
        try:
            fcntl.flock(rlk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            say(f"another shipcheck is topping up {ref_bot}'s nochase2 reference: waiting for it")
            fcntl.flock(rlk, fcntl.LOCK_EX)
        for attempt in range(3):
            if os.path.exists(stopf):  # the live h2h failed meanwhile: this check needs no reference
                break
            bnd = os.environ.get("BASE_ND") or ref_runs(ref_bot)
            have = (ref_maps(bnd, ref_bot) if bnd else set()) | (ref_maps(index_ref(ref_bot, sub, rtag), ref_bot)
                                                               if attempt or not bnd else set())
            miss = [m for m in sub if m not in have]
            if not (len(miss) > 0.05 * len(sub) and not os.environ.get("BASE_ND")):
                break
            nm_ref = run_tag(f"nd{ref_bot.split('_')[1][1:]}ref", ref_bot, opp, prefixes=("",), suffix=rtag)
            mf = os.path.join(Q, "subsets", f"refmiss_{rtag}.txt")
            open(mf, "w").write("".join(m + "\n" for m in miss))
            say(f"live {ref_bot} lacks nochase2 games on {len(miss)} of the subset's {len(sub)} maps: playing them first as {nm_ref}")
            r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/condab.sh"), ref_bot, opp, nm_ref, mf], cwd=REPO,
                               env={k: v for k, v in dict(env, OTF="0", CONDAB_PRIO="10").items()
                                    if k not in ("STOP", "STOP_REF", "SET", "CONDAB_FIRST", "CONDAB_TIMEBOX")},
                               stdout=open(os.path.join(Q, f"sc_{tag}_ref.log"), "a"), stderr=subprocess.STDOUT)
            say(f"reference top-up {nm_ref} exit {r.returncode}")
            if r.returncode == 0:
                break
            if attempt < 2:
                time.sleep(60)
        fcntl.flock(rlk, fcntl.LOCK_UN)
        rlk.close()
        if not os.environ.get("BASE_ND"):  # the reference = every ref_bot (live) vs nochase2 game the index has on the subset
            bnd = index_ref(ref_bot, sub, rtag)
            say(f"nochase2 reference: {len(ref_maps(bnd, ref_bot))} of the subset's {len(sub)} maps paired-ready ({bnd})")
        if not bnd and not os.path.exists(stopf):
            sys.exit(f"shipcheck: no nochase2 run of {ref_bot} and the top-up failed: pass BASE_ND=cq_nd..._1[,cq_nd..._2]")
        say(f"nochase2 reference runs: {bnd}")
        env["BASE_ND"] = bnd or ""
        t_scr = time.time()
    if bnd and os.path.exists(stopf):
        say("nochase2 leg not started: the live h2h already FAILED")
    elif bnd:
        procs["scr"] = launch("nochase2 (scr.sh)", f"sh {Q}/scr.sh {cand} {rtag}", dict(env, CONDAB_TIMEBOX_EXT=str(NC_EXT)),
                              os.path.join(Q, f"sc_{tag}_scr.log"))
        scr_deadline = t_scr + TIMEBOX + 120 + NC_EXT
    deadline = t0 + TIMEBOX + 120 + NC_EXT + (int(os.environ.get("SC_RARE_WAIT", 10800)) if os.environ.get("RARE") else 0)  # condab legs stop themselves at the timebox (+ NC_EXT once); summaries ~1 min more; rare: see sp_deadline
    def stop(k, p, why):
        say(f"!! leg {k} {why}: stopping it (its own process group, pid {p.pid})")
        os.killpg(p.pid, signal.SIGTERM)
        p.wait()
    ubk = [k for k in ("ub", "ub2") if k in procs]
    for k, p in procs.items():  # every leg but ubaudit: stopped at the timebox
        if k in ubk:
            continue
        if k == "sp":  # the panel: its own wait; stopped at once when the live h2h already FAILED
            while p.poll() is None and time.time() < sp_deadline + (SECOND_WAIT if second_read_started(rtag) else 0) and not os.path.exists(stopf):
                time.sleep(15)
            if p.poll() is None:
                stop(k, p, "stopped (live h2h FAILED)" if os.path.exists(stopf) else f"not done after SC_PANEL_WAIT {PANEL_WAIT // 60} min")
            continue
        if k == "tc":  # its gate's fresh read may need a second set too
            while p.poll() is None and time.time() < deadline + home_hold_s(t0) + int(os.environ.get("SC_TC_EXTRA", 1200)) + (SECOND_WAIT if second_read_started(TRUNK_CODE["tag"]) else 0) and not os.path.exists(stopf):  # 10 Nov: +20 min, its kill gate runs up to 9 stages
                time.sleep(15)
            if p.poll() is None and os.path.exists(stopf):  # 2 Nov: 7 min on a verdict already known. The gate plays on: its read is cached for this trunk's next check
                say("not waiting for the trunk code row: this check has failed already")
                # 11 Nov ~01:20Z (TB 6ad907: 16 orphan tc gates of ended checks kept playing ~25k games): a failed check's trunk is dead,
                # so its gate stops unless another RUNNING check names the same gate hash in its shipwatch .out (shared trunk code)
                try:
                    import glob as _g
                    h = TRUNK_CODE["tag"]
                    me_out = os.path.join(Q, f"shipwatch_{cand}_{tag}.out")
                    shared = False
                    for o in _g.glob(os.path.join(Q, "shipwatch_*.out")):
                        if o == me_out or o.endswith(f"_{tag}.out") or time.time() - os.path.getmtime(o) > 3 * 3600:
                            continue
                        b = re.sub(r"^shipwatch_|_\d+\.out$", "", os.path.basename(o))
                        lk = os.path.join(Q, f".shipwatch_{b}.lock")
                        if h in open(o, errors="replace").read(20000) and subprocess.run(["flock", "-n", lk, "true"], capture_output=True).returncode != 0:
                            shared = True
                            break
                    if not shared:
                        stop(k, p, "trunk code gate no longer needed (this check failed; no running check shares its gate)")
                except Exception as e:  # noqa: BLE001
                    say(f"trunk code gate left running ({str(e)[:100]})")
            elif p.poll() is None:
                stop(k, p, "still running at the timebox")
            continue
        dl = scr_deadline if k == "scr" else lh_deadline if k in ("lh", "lx") else deadline
        while p.poll() is None and time.time() < dl + home_hold_s(t0):  # + the home-quota slowdown the legs sat in (10 Nov)
            time.sleep(15)
        if p.poll() is None:
            stop(k, p, "still running at the timebox")
    if RARE and os.environ.get("CP_RAREBANK") and "RARE BANK SHORT" in read(os.path.join(Q, f"sc_{tag}_sp.log")):
        # 11 Nov (owner ~02:4xZ: rare reads on maps banked from the common reads): the bank ran out before N changed maps. Not INCONCLUSIVE:
        # the probe is saved (stylepanel) and the marker goes back to waiting on its bank (tools/lab/rarebank.py bank_wait)
        for k in ubk:
            if procs[k].poll() is None:
                stop(k, procs[k], "not needed: the rare read waits on its bank")
        import rarebank
        text = rarebank.bank_wait(cand, tag, live, os.path.join(Q, f"sc_{tag}_sp.log"), dry=DRY)
        print(text)
        open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
        return
    if lx_thread:  # the extension, when it started: its own +LX_EXTRA s
        lx_thread.join(timeout=max(1, lh_deadline + LX_EXTRA - 300 - time.time()))
        if "p" in lx:
            try:
                lx["p"].wait(timeout=max(1, lh_deadline + (LX_EXTRA_BIG if LH_BIG else LX_EXTRA) - time.time()))
            except subprocess.TimeoutExpired:
                stop("lx", lx["p"], "still running at its timebox")
    for k in ubk:
        try:
            procs[k].wait(timeout=1 if os.path.exists(stopf) else max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            pass
    ub_wait = None
    pending = [k for k in ubk if procs[k].poll() is None]
    if pending:  # ubaudit queues behind other audits: wait for it only when everything else already passed
        rows0, _ = table(cand, live, rtag, lane, None, "")
        others = [r for r in rows0 if r[0] != "ubaudit"]
        if all(r[3] in ("PASS", "EXT") for r in others) and not os.path.exists(stopf):
            uw = float(os.environ.get("UBAUDIT_WAIT", 1200))
            say(f"every other leg PASSED: waiting up to {uw / 60:.0f} min more for ubaudit ({', '.join(pending)})")
            t1 = time.time()
            for k in pending:
                try:
                    procs[k].wait(timeout=max(1, t1 + uw - time.time()))
                except subprocess.TimeoutExpired:
                    stop(k, procs[k], f"not done after UBAUDIT_WAIT {uw / 60:.0f} min")
            ub_wait = time.time() - t1
        else:
            for k in pending:
                stop(k, procs[k], "still running at the timebox and another leg did not pass")
    if ub_skip:
        ub_rc, ub_txt = 0, ub_skip
    else:
        ub_rc = procs["ub"].returncode
        ub_txt = read(os.path.join(Q, f"sc_{tag}_ub.log"))
    if "ub2" in procs:
        ub_txt += read(os.path.join(Q, f"sc_{tag}_ub2.log"))
        ub_rc = max(ub_rc, procs["ub2"].returncode) if ub_rc in (0, 1) else ub_rc
    if os.path.exists(sf):  # the gate's subset, kept for the complement leg
        os.makedirs(os.path.join(Q, "postship"), exist_ok=True)
        shutil.copyfile(sf, os.path.join(Q, "postship", f"{tag}.subset"))
        POSTSHIP_ND["bnd"] = bnd
    if trig and not trig.get("h2h"):
        try:
            trig["res"] = trigger_d(cand, live, trig["maps"])
        except SystemExit as e:
            say(f"!! trigger D failed: {e}")
            trig["res"] = (0, 0.0, 0.0, 0.0, 0)
    rows, overall = table(cand, live, rtag, lane, ub_rc, ub_txt, ub_wait, trig)
    rows, overall = second_read(rows, overall, cand, live, rtag, lane)
    rows, overall = pooled_row(rows, overall, lane)
    rows, overall = param_row(rows, overall, lane, final=False)
    rows, overall = bugbar_fuel_row(rows, overall, lane)
    rows, overall = fuel_ratio(rows, cand, live, rtag)  # before the sequential looks: a fuel FAIL ends them
    seq_st = seq_first(rows, cand, live, rtag, lane)  # every threshold set's look 1 verdict goes to the log, decided by them or not
    if any(r[0] == "pooled BIG + fresh" and r[3] in ("EXT", "PASS") for r in rows):  # owner 11 Nov ~01:10Z: second fresh set for BIG no-harm
        b2 = big2_read(rows, cand, live, rtag, lane)
        if b2 is not None:  # the BIG point row keeps its value; a PASS on the second set replaces its verdict (logged in the row and the bar)
            rows = [(r[0], r[1], r[2] + " -> replaced by the 2nd fresh set", "PASS") if r[0] == "live h2h" and b2[3] == "PASS" else r for r in rows]
            rows.append(b2)
            overall = _verdict(rows)
    rows, overall = seq_extend(rows, overall, cand, live, rtag, lane)
    rows, overall = param_row(rows, overall, lane, final=True)  # 13 Nov (owner): the parameter bar on the read's last look
    if not CTRUNK[0]:  # ctrunk: the h2h only informs, so no extension
        rows, overall = nearmiss_ext(rows, overall, cand, live, rtag, lane)
        rows, overall = fuel_ratio(rows, cand, live, rtag)  # again on the final point
    else:
        import ctrunk
        rows, overall = ctrunk.decide(rows)
    rows, overall = class_noharm(rows, overall, cand, live, rtag)
    rows, overall = fix_careful(rows, overall, lane)
    try:  # the banks never break a check
        fuel_bank(rows, overall, cand, live, rtag, lane)
        auto_bank(rows, overall, cand, live, rtag, lane)
    except Exception as e:  # noqa: BLE001
        say(f"!! bank: {type(e).__name__}: {e}")
    text = fmt(rows, overall, cand, live, tag, lane, time.time() - t0)
    if seq_st:
        text += "\n" + "\n".join(seq_st["lines"])
        seq_shadow_start(seq_st)
    if overall == "INCONCLUSIVE":  # for shipwatch's self-heal: only capacity-type causes count
        text += "\nINCONCLUSIVE CAUSE: " + inconclusive_cause(rows, tag, rtag)
    text += ladder_panel_line(tag, lane)
    try:
        text += manygrp_line(rtag, cand, live)
        text += big2_line(rtag, cand)
    except Exception as e:  # noqa: BLE001  information only: never breaks a check
        text += f"\n  many-group fuel (information): not read ({str(e)[:80]})"
    text += tempo_line(tag)
    text += hetero_line(tag, cand, overall)
    if trigger:  # capacity rule (primer): KEEP / MECH only after the gate, and only on a PASS
        if overall == "PASS":
            mlog = os.path.join(Q, f"sc_{tag}_mech.log")
            subprocess.Popen(f"nohup nice -n 10 python3 -I {os.path.join(REPO, 'tools/lab/shipcheck.py')} --mech {cand} {tag} "
                             f"{live} {shlex.quote(trigger)} > {mlog} 2>&1 &", shell=True, cwd=REPO, start_new_session=True)
            text += (f"\nmechanism: KEEP{' + MECHCMD' if os.environ.get('MECHCMD') else ''} started after the gate PASSED "
                     f"(KEEP priority -5), log {mlog}; appended to shipcheck_{tag}.txt when done")
        else:
            text += "\nmechanism: skipped (gate not PASS)"
    if bugbar_on():
        text += f"\nBUG BAR USED (BUGBAR=1): live h2h point bar {BUGBAR_PT}, not {FIX_BIG_LH}; every other row as usual; for verified bug fixes or play-identical changes only"
        with open(os.path.join(Q, "bugbar.log"), "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} tag {tag} {overall}\n")
    print(text)
    open(os.path.join(Q, f"shipcheck_{tag}.txt"), "w").write(text + "\n")
    if stack:
        st = (shipstack.wait(stack, stack_head, Q, int(os.environ.get("SC_STACK_WAIT", 5400))) if overall == "PASS"
              else shipstack.a_state(stack, stack_head, Q))
        act = shipstack.decide(overall, st)
        if act in ("void", "void_requeue"):
            print(f"STACK VOID: {stack} is {st}, {overall} read not used")
            return stack_requeue(cand, lane, stack_vals) if act == "void_requeue" else None
    if overall == "PASS":
        d = re.search(r"nochase2 paired D\s+([+-][\d.]+)", text)
        c = re.search(r"CONFIRM\s+([\d.]+)", text)
        h = re.search(r"live h2h(?: \([^)]*\))?\s+([\d.]+)", text)
        pm = re.search(r"live h2h\+ext\s+([\d.]+) \[[\d.]+, [\d.]+\] n (\d+) LOS (\d+)%", text)
        rm = re.search(r"rare changed maps\s+([\d.]+) \[[\d.]+, [\d.]+\] n (\d+)", text)
        if lane == "param" and pm:
            stat = f"h2h {pm.group(1)} n{pm.group(2)}"
        elif RARE and rm:
            stat = f"changed {rm.group(1)} n{rm.group(2)}"
        elif nonc(lane):
            stat = f"h2h {h.group(1) if h else '?'}"
        else:
            stat = f"h2h {h.group(1) if h else '?'} nc {d.group(1) if d else '?'} cf {c.group(1) if c else '?'}"
        # Commit-style note (owner 30 Oct): "SUBJECT | BOT STAT"; the bot name stays whole (shipwatch reads nova_* from it).
        tail = f" | {cand} {stat}"
        note = subject_line(lane)[:max(0, 80 - len(tail))].rstrip() + tail
        if train_take(cand, tag, lane, stack, stack_vals, text,  # 10 Nov: release train on (bq/train_ON): a PASS of any lane rides the next train
                      point=(pm.group(1) if lane == "param" and pm else rm.group(1) if RARE and rm else h.group(1) if h else None)):
            return
        if fixbatch_take(cand, tag, lane, stack, stack_vals, text):  # owner 9 Nov ~21:35Z: plain fix-lane PASSes ship together (fixbatch.py)
            return
        submit(cand, tag, text, note)
        if LIVE_MOVED and not stack and LIVE_MOVED[0] != start_live:
            reread_requeue(cand, lane, stack_vals, tag, start_live, LIVE_MOVED[0])
    else:
        say(f"no submit: {overall}")
        cause = re.search(r"^INCONCLUSIVE CAUSE: (.*)$", text, re.M)
        if overall == "INCONCLUSIVE" and cause and cause.group(1).startswith("too rare") and not DRY:
            with open(PENDING, "a") as f:
                f.write(f"PENDING: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {cand} ({lane}) INCONCLUSIVE {cause.group(1)}; "
                        f"read {Q}/shipcheck_{tag}.txt; not re-armed: route it (no-harm fix lane, or a trigger set where it fires)\n")
            say(f"INCONCLUSIVE ({cause.group(1)}): no re-arm; written to {PENDING}")
        elif overall == "INCONCLUSIVE" and cause and not cause.group(1).startswith("harness"):
            inconclusive_requeue(cand, lane, stack_vals, tag, cause.group(1))


if __name__ == "__main__":
    main()
