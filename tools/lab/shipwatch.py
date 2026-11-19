#!/usr/bin/env python3
"""shipwatch: start tools/lab/shipcheck.sh for a candidate as soon as it carries a SHIPCHECK marker. Tool builder, 29 Oct.

usage: nohup nice -n 10 python3 -I tools/lab/shipwatch.py > /data/USER/st/bq/shipwatch.out 2>&1 &   (the Builder starts it)
       WATCH_DRY=1 python3 -I tools/lab/shipwatch.py [--once]   (tests: shipcheck runs with DRY=1, nothing is submitted)
Every 30 s it scans bots/nova_b*/SHIPCHECK. A marker is acted on only when
  - bots/NAME is a newbot.sh copy: a real dir with src/ (or, for older bots, a symlink to /data/USER/st/new/bots/NAME);
  - the marker parses: KEY=VALUE lines, TAG required ([A-Za-z0-9_]+), optional LANE (behaviour|fix|param), SUBJECT (a git-style commit subject for the submit note), TRIGGER (an
    existing map-list file), MECH (prose: the commit body; never run), MECHCMD (shipcheck's mechanism
    command, run without a shell after a PASS with TRIGGER), SUBSET (a number), REUSE_LX (a condab run name, passed
    as SC_REUSE_LX: LANE=param's extension, e.g. from sweepd.py), BIG (0..4000, passed as SC_LH_BIG: the live h2h also plays
    that many frozen bank maps); '#' comments and blank lines are ignored;
  - this marker content has not been run for NAME before (state /data/USER/st/bq/shipwatch_state.json), and no shipcheck
    for NAME is running (per-candidate flock /data/USER/st/bq/.shipwatch_NAME.lock, held by the shipcheck it starts).
GUARDS (29 Oct 21:24: newbot.sh copied live b185's own marker into four new bots, which then ran TAG 185 shipchecks):
  - TAG must belong to the bot: nova_b184r_x takes TAG 184r..., 184... (the digits of its number, then [a-z0-9_]*);
  - the marker must be newer than the copy (the bot dir's birth time, else its ctime): an inherited marker is older;
  - a TAG is used by one bot only (registry state["_tags"], seeded from shipwatch.log's start lines).
UB PREBUILD (30 Oct, iteration-speed): a marker that has to wait (capacity) starts `ubaudit.sh --build-only CAND LIVE` at once,
  once per marker content (state "_ubpre"; log Q/ubpre_NAME.log), so the instrumented debug build overlaps the wait.
AUTO-REBASE (owner: "iterate as fast as possible"): a marker on a bot built on the PREVIOUS live (shipcheck's base check
  fails because live moved, but the bot carries the previous live's own change) is rebased: relqueue.merge3 (git merge-file -p
  per changed file) of the bot onto the current live into a NEW newbot-style copy NAME_r<livever>
  (/data/USER/st/new/bots + bots/ link), accepted only with no conflicts and relqueue.same_change empty (the bot's diff vs
  its old base = the copy's diff vs the new live, file by file, line for line). The copy gets a fresh marker, TAG + "r<ver>",
  and is gated on the next scan. SHIPCHECK files never take part in the merge. 31 Oct: also after a gate that PASSED but
  was REFUSED for base at submit (live moved mid-check): the same rebase, then the full gate on the new base. Conflicts and mismatches are logged and
  skipped; the original bot is only read.
  CONFIRM MODE (owner 9 Nov ~17:20Z): the copy made after a PASS REFUSED for base carries CONFIRM_FROM=<the passing TAG>, CONFIRM_N=1:
  shipcheck then reads only 1,200 fresh maps v the new live (point >= .50, CI upper >= .50; faults, capped fuel, death guard). A confirm
  refused again (or a waiting confirm marker rebased before its start) keeps CONFIRM_FROM with CONFIRM_N + 1, at most CONFIRM_MAX (2), then
  both keys are dropped and the full check runs. A merge conflict is skipped as before.
CAPACITY (owner 29 Oct: "only run jobs that will finish in time"): at most MAX_RUNNING (4) shipchecks at once (one runs while
  its per-candidate lock is held); none starts while our Condor jobs (idle + running) exceed QUEUE_MAX (300). Waiting markers
  queue by PRIO=N (marker key, default 0, higher first); none starts either while this machine's 1-min load average exceeds
  LOAD_MAX (6 x nproc), except that a start is always allowed while fewer than 2 shipchecks run (the valve). Markers, then marker age; each position change is logged.
SELF-HEAL (owner 29 Oct: "detect if jobs start bottlenecking without our input and fix it"): when >= 2 of the last 6
  shipchecks that ended since the last change ended INCONCLUSIVE with a leg that had "no result", MAX_RUNNING drops to 2 for
  one hour, then comes back; each change is logged. PID file /data/USER/st/bq/shipwatch.pid (SHIPWATCH_PID overrides).
  `python3 -I tools/lab/shipwatch.py --reset-heal` clears it at once (the running watcher reads it on its next scan).
Each trigger, skip and parse failure is logged to /data/USER/st/bq/shipwatch.log; the shipcheck's own output goes to
/data/USER/st/bq/shipwatch_NAME_TAG.out. To re-run a candidate, change its marker (e.g. a new TAG).
"""
import difflib
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shipstack  # noqa: E402

REPO = os.environ.get("SHIPWATCH_REPO", "/homes/USER/cambc")  # (tests: a fake repo)
NEWB = "/data/USER/st/new/bots"
Q = os.environ.get("SHIPWATCH_Q", "/data/USER/st/bq")  # (tests: a fake dir)
STATE = os.path.join(Q, "shipwatch_state.json")
LOG = os.path.join(Q, "shipwatch.log")
DRY = os.environ.get("WATCH_DRY") == "1"
MAX_RUNNING = int(os.environ.get("MAX_RUNNING", 4))
_BASE_OK = {}  # 13 Nov: cached passing base checks (see the scan loop)


def _live_ver():
    """live.txt's first token as an int (v911 -> 911), else None"""
    try:
        t = open("/data/USER/st/bq/live.txt").readline().split()[0]
        return int(t.lstrip("v"))
    except (OSError, IndexError, ValueError):
        return None


def _stale_base(kv):
    """True when the marker's BASE is nova_base_vNNN with NNN below live.txt's version (13 Nov pre-check)"""
    b_ = str(kv.get("BASE", "")).strip()
    if not b_ and kv.get("TRUNK"):  # markers carry TRUNK; the trunk dir's BASE file names the live it was built on (BASE=nova_base_vNNN)
        try:
            b_ = open(os.path.join(REPO, "bots", kv["TRUNK"].strip(), "BASE")).read().split("BASE=", 1)[1].split()[0]
        except (OSError, IndexError):
            b_ = ""
    m_ = re.match(r"nova_base_v(\d+)$", b_)
    lv_ = _live_ver()
    return bool(m_ and lv_ and int(m_.group(1)) < lv_)
MAX_RUNNING_FILE = "/data/USER/st/bq/max_running"  # 6 Nov (Builder): read every scan, so the limit changes without a restart and survives one


_PILOTS = [0.0, None]


def pilot_cap():
    """12 Nov (owner: 'make the shipcheck queue faster', option 'scale checks to pilots'): with ~19 pilots, 8 checks at once each ran slow
    and a quarter timed out (INCONCLUSIVE capacity). Cap = alive pilots / SW_PILOTS_PER_CHECK (1.5; 12 Nov 15:4xZ TB: a pilot plays ~450 items/h, ~47 games each in ~4 s, so 3.5 per check starved slots while pilots idled between legs), between SW_PILOT_CAP_MIN (4; owner 12 Nov ~13:5xZ: keep the parallel count, cut tests per check instead) and the
    max_running file's value; pilotd's count is read at most once a minute. SW_PILOT_SCALE=0 turns it off. None when unknown."""
    if os.environ.get("SW_PILOT_SCALE", "1") == "0":
        return None
    if time.time() - _PILOTS[0] > 60:
        try:
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
            import pilotd
            _PILOTS[1] = len(pilotd.alive_pilots())
        except Exception:  # noqa: BLE001
            _PILOTS[1] = None
        _PILOTS[0] = time.time()
    n = _PILOTS[1]
    if not n:
        return None
    return max(int(os.environ.get("SW_PILOT_CAP_MIN", "4")), int(n / float(os.environ.get("SW_PILOTS_PER_CHECK", "1.5"))))


def max_default():
    try:
        v = int(open(MAX_RUNNING_FILE).read().split()[0])
        # 9 Nov 21:40Z: the cap was 12, so the owner's 16 fell back to MAX_RUNNING (4) for ~20 min. Values above the cap are now clamped to it,
        # never dropped to the default
        v = max(1, min(v, int(os.environ.get("SW_MAX_CAP", "32"))))
    except (OSError, ValueError, IndexError):
        v = MAX_RUNNING
    pc = pilot_cap()
    return min(v, pc) if pc else v
QUEUE_MAX = int(os.environ.get("QUEUE_MAX", 300))
LOAD_MAX = float(os.environ.get("LOAD_MAX", 2 * (os.cpu_count() or 16)))  # local 1-min load average (29 Oct: ~320 on 16 cores)
# 4 Nov (iteration speed): while games play on Condor (>= 4 pilots alive; cxe and cxecondor go there) a shipcheck's local cost is small
# (staging, a 2% spot-check on the CLI runner, no index for panel legs), so the gate rises to LOAD_MAX_REMOTE
LOAD_MAX_REMOTE = float(os.environ.get("LOAD_MAX_REMOTE", 48))


def load_max():
    # 10 Nov (owner: "allow the load to go up and make sure to keep the load safe"): limits from loadlim (bq/load_limits, read each scan;
    # env LOAD_MAX / LOAD_MAX_REMOTE still win); loadguard.py keeps VS Code safe with CPU weights and pauses deferrable units
    try:
        import loadlim
        lm, lr = loadlim.get("load_max"), loadlim.get("load_max_remote")
    except Exception:  # noqa: BLE001
        lm, lr = LOAD_MAX, LOAD_MAX_REMOTE
    try:
        import pilotd
        if len(pilotd.alive_pilots()) >= 4:
            return max(lm, lr)
    except Exception:  # noqa: BLE001
        pass
    return lm
VALVE = 2  # below this many running shipchecks a start is always allowed, whatever the load (a stuck reader must not block)
PIDFILE = os.environ.get("SHIPWATCH_PID", os.path.join(Q, "shipwatch.pid"))
LOW_MAX, LOW_FOR = 2, 3600
CONFIRM_MAX = int(os.environ.get("SW_CONFIRM_MAX", 2))  # owner 9 Nov: a stale PASS gets at most this many CONFIRM reads (live moves), then the full check
FUNNEL_LOAD = float(os.environ.get("SW_FUNNEL_LOAD", "90"))  # 12 Nov ~22:3xZ: funnel lines start below this load (others: LOAD_MAX)
FUNNEL_EXTRA = int(os.environ.get("SW_FUNNEL_EXTRA", "5"))  # 12 Nov ~21:2xZ (owner via the Planner): dedicated funnel slots past MAX_RUNNING
CONFIRM_EXTRA = int(os.environ.get("SW_CONFIRM_EXTRA", 2))  # 12 Nov owner: confirm reads start past MAX_RUNNING by this many


def log(s):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z {'[dry] ' if DRY else ''}{s}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


# SUBJECT (owner 30 Oct: "make the notes on the submission like git commit messages"): the platform note and the
# submissions log entry start with it, e.g. "fix(econ): DOM crew wait ignores unseen mates".
SUBJECT_RE = r"(fix|feat|perf|tune|revert|refactor|bundle)(\([a-z0-9_,-]+\))?!?: [ -~]{4,60}"


def parse(path):
    kv = {}
    for raw in open(path, errors="replace"):
        x = raw.strip()
        if not x or x.startswith("#"):
            continue
        if "=" not in x:
            raise ValueError(f"not KEY=VALUE: {x[:60]!r}")
        k, v = (y.strip() for y in x.split("=", 1))
        if k not in ("TAG", "LANE", "TRIGGER", "MECH", "MECHCMD", "SUBSET", "PRIO", "REUSE_LX", "BIG", "BIGSET", "SUBJECT", "NULLSW",
                     "DONORS", "LIVEVALS", "TRUNK", "STACK_ON", "BUGBAR", "Q1BAR", "PARAMBAR", "SEQ_SPAR", "FUELX", "RARE", "RAREFAMS", "BASEHAS", "SHADOW", "REVISES",
                     "CONFIRM_FROM", "CONFIRM_N", "CLASS", "WFAMS", "IDENT_OK", "IDENTSHIP"):
            raise ValueError(f"unknown key {k!r}")
        kv[k] = v
    if not re.fullmatch(r"[A-Za-z0-9_]+", kv.get("TAG", "")):
        raise ValueError("TAG missing or not [A-Za-z0-9_]+")
    if kv.get("LANE", "behaviour") not in ("behaviour", "fix", "param", "draft", "ctrunk"):  # ctrunk: owner 6 Nov, the Builder's correctness batches
        raise ValueError(f"LANE must be behaviour, fix, param, draft or ctrunk: {kv['LANE']!r}")
    if "REUSE_LX" in kv and not re.fullmatch(r"[A-Za-z0-9_]+", kv["REUSE_LX"]):
        raise ValueError("REUSE_LX must be a condab run name ([A-Za-z0-9_]+)")
    if "NULLSW" in kv and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", kv["NULLSW"]):  # 31 Oct: the fix's switch name
        raise ValueError(f"NULLSW must be a C identifier (the fix's #define), not {kv['NULLSW']!r}")
    if "BIGSET" in kv and kv["BIGSET"] not in ("ladderw", "ladderw_nh", "bank2", "big2"):  # 31 Oct: BIGSET=ladderw (tools/lab/ladderw.py); 11 Nov big2
        raise ValueError(f"BIGSET must be ladderw, ladderw_nh, big2 or bank2, not {kv['BIGSET']!r}")
    if "BIG" in kv and not (kv["BIG"].isdigit() and 0 <= int(kv["BIG"]) <= 4000):
        raise ValueError("BIG must be an integer 0..4000 (frozen bank maps added to the live h2h)")
    if "TRIGGER" in kv and not os.path.isfile(kv["TRIGGER"]):
        raise ValueError(f"TRIGGER file missing: {kv['TRIGGER']}")
    if "PRIO" in kv and not re.fullmatch(r"-?\d+", kv["PRIO"]):
        raise ValueError("PRIO must be an integer")
    if "SUBSET" in kv and not kv["SUBSET"].isdigit():
        raise ValueError("SUBSET must be a number")
    if "DONORS" in kv and not re.fullmatch(r"[A-Za-z0-9_]+(:[A-Za-z0-9_]+)?(,[A-Za-z0-9_]+(:[A-Za-z0-9_]+)?)*", kv["DONORS"]):
        raise ValueError("DONORS must be BOT[:BASE],BOT[:BASE],... (shipcheck's mergecheck --donor list)")
    if "LIVEVALS" in kv and not re.fullmatch(r"(\s*[A-Za-z_][A-Za-z0-9_]*=-?\d+)*\s*", kv["LIVEVALS"]):
        raise ValueError("LIVEVALS must be 'FLAG=INT FLAG=INT ...' (flip.sh syntax: the flips that make the trunk play like live)")
    if "PARAMBAR" in kv and (kv["PARAMBAR"] != "1" or kv.get("LANE") != "behaviour"):
        raise ValueError("PARAMBAR must be 1, with LANE=behaviour")
    if "SEQ_SPAR" in kv and (kv["SEQ_SPAR"] != "1" or kv.get("LANE", "behaviour") != "behaviour"):  # 3 Nov, owner via Builder: MH only
        raise ValueError("SEQ_SPAR must be 1, with LANE=behaviour")
    if "FUELX" in kv and not (re.fullmatch(r"\d+(\.\d+)?", kv["FUELX"]) and 1.0 < float(kv["FUELX"]) <= 3.0):  # owner 6 Nov ("Fuel later")
        raise ValueError("FUELX must be a number in (1, 3]: the capped-fuel ratio the fuel row accepts (fuel debt)")
    if "RARE" in kv and not (re.fullmatch(r"\d+", kv["RARE"]) and 50 <= int(kv["RARE"]) <= 1200 and kv.get("LANE") == "fix"):  # owner 7 Nov: rare changes, read where they change the game
        raise ValueError("RARE must be 50-1200 changed maps, with LANE=fix")
    if "SHADOW" in kv and not ("RARE" in kv and re.fullmatch(r"[A-Z][A-Z0-9_]*=-?\d+( [A-Z][A-Z0-9_]*=-?\d+)*", kv["SHADOW"])):
        raise ValueError("SHADOW must be FLAG=V [FLAG=V ...] (the donor's compute-only flips), with RARE")  # CI Analyser 10 Nov (spec_akx_1110 A4)
    if "RAREFAMS" in kv and not ("RARE" in kv and re.fullmatch(r"w_[a-z0-9_]+(,w_[a-z0-9_]+)*", kv["RAREFAMS"])):
        raise ValueError("RAREFAMS must be w_a,w_b, with RARE")
    if "BASEHAS" in kv and not (("RARE" in kv or kv.get("LANE") == "draft") and re.fullmatch(r"[A-Za-z0-9_,=/+<>.!-]+", kv["BASEHAS"])):
        raise ValueError("BASEHAS must be a draftstock filter (e.g. ryth or ryth,prism+team=T4/T5), with RARE or LANE=draft")
    if "CLASS" in kv:  # 10 Nov (Planner): class read; shipcheck's fresh / stylepanel legs draw only these maps (SP_CLASS)
        import mapclass
        try:
            mapclass.parse(kv["CLASS"])
        except SystemExit as e:
            raise ValueError(f"CLASS: {e}")
    if "BUGBAR" in kv and (kv["BUGBAR"] != "1" or kv.get("LANE") != "fix"):
        raise ValueError("BUGBAR must be 1, with LANE=fix")
    if "Q1BAR" in kv and (kv["Q1BAR"] != "1" or kv.get("LANE") != "fix"):
        raise ValueError("Q1BAR must be 1, with LANE=fix")
    if "STACK_ON" in kv and not re.fullmatch(r"nova_b[A-Za-z0-9_]+", kv["STACK_ON"]):
        raise ValueError("STACK_ON must be the bundle this one carries (shipstack.py)")
    if "TRUNK" in kv and not re.fullmatch(r"[A-Za-z0-9_]+", kv["TRUNK"]):
        raise ValueError("TRUNK must be a bot name (the trunk the candidate flips)")
    if "SUBJECT" in kv and not re.fullmatch(SUBJECT_RE, kv["SUBJECT"]):
        raise ValueError("SUBJECT must be a commit subject: type(area): summary, type in fix/feat/perf/tune/revert/refactor/bundle, "
                         "area optional, summary 4-60 printable ASCII chars")
    return kv


def live_chain():
    """[(version, bot)] from CLAUDE.md's live line: live first, then its parent, grandparent, ..."""
    t = open(os.path.join(REPO, "CLAUDE.md")).read()
    m = re.search(r"The live bot: \*\*bots/(\S+) = v(\d+)\*\*", t)
    if not m:  # 4 Nov: CLAUDE.md's live line changed form; live.txt ("vNNN BOT UTC parent=PREV", newest first) holds the chain
        try:
            ch = []
            for line in open(os.path.join(Q if not os.environ.get("SHIPWATCH_Q") else "/data/USER/st/bq", "live.txt")):
                x = line.split()
                if len(x) >= 2 and re.fullmatch(r"v\d+", x[0]) and (not ch or ch[-1][1] != x[1]):
                    ch.append((x[0][1:], x[1]))
                if len(ch) >= 6:
                    break
            return ch
        except OSError:
            return []
    ch = [(m.group(2), m.group(1))] + re.findall(r"v(\d+) = bots/([A-Za-z0-9_.+-]+)", t[m.end():m.end() + 1500])
    try:  # shipcheck's machine-kept live.txt is ahead of CLAUDE.md right after a submit ("vNNN BOT UTC parent=PREV")
        x = open(os.path.join(Q if not os.environ.get("SHIPWATCH_Q") else "/data/USER/st/bq", "live.txt")).readline().split()
        par = next((y[7:] for y in x if y.startswith("parent=")), None)
        if int(x[0].lstrip("v")) > int(ch[0][0]) and par == ch[0][1]:
            ch = [(x[0].lstrip("v"), x[1])] + ch
    except (OSError, IndexError, ValueError):
        pass
    return ch


QUEUE_MD = "/homes/USER/condor-work/reports/builder_queue.md"


def submitted():
    """{version: bot} of submitted versions (builder_queue.md's "- vNNN <date>: BOT (shipcheck ...)" lines, not DRY)."""
    out = {}
    try:
        for line in open(QUEUE_MD, errors="replace"):
            m = re.match(r"^- v(\d+) [^:]*\d\d:\d\d:\d\d[^:]*: (nova_\S+)", line)
            if m and "DRY" not in line:
                out[int(m.group(1))] = m.group(2)
    except OSError:
        pass
    return out


def lost_change(orig, base, live, ch, sc):
    """A submitted version between live's parent and live that is not in live's ancestry, whose added lines (vs base) live
    lacks but orig carries -> (version, bot, sample) or None. (29 Oct 23:25: v286 was built on v284 and dropped v285's
    NT_GEMROOM; a candidate built on v285 would bring it back unseen through a rebase onto v286.)"""
    anc = {b for _, b in ch}
    lo, hi = int(ch[1][0]), int(ch[0][0])
    O, B, LV = sc.src_files(orig), sc.src_files(base), sc.src_files(live)
    for v, sb in sorted(submitted().items()):
        if not lo < v < hi or sb in anc or not os.path.isdir(os.path.join(REPO, "bots", sb, "src")):
            continue
        S, lost = sc.src_files(sb), []
        for fn, sl in S.items():
            have = set(x.strip() for x in LV.get(fn, []))
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, B.get(fn, []), sl, autojunk=False).get_opcodes():
                if op in ("insert", "replace"):
                    lost += [(fn, x.strip()) for x in sl[j1:j2] if x.strip() and x.strip() not in have]
        if not lost:
            continue
        carried = [x for x in lost if x[1] in set(y.strip() for y in O.get(x[0], []))]
        if len(carried) >= max(1, 0.8 * len(lost)):
            d = next((re.match(r"#\s*define\s+(\w+)", x[1]).group(1) for x in carried if re.match(r"#\s*define\s+\w+", x[1])), None)
            return v, sb, d or carried[0][1][:50]
    return None


def live_check(state):
    """Every 2 min: live.txt vs the platform's live (shipcheck.platform_listing, read-only via platlock). Platform newer:
    if its note names an existing bot, live.txt is corrected atomically under the submit lock (parent = the previous live,
    marked inferred); else "LIVE MISMATCH" holds new starts until live.txt is fixed. A failed call never blocks."""
    now = time.time()
    if now - state.get("_livechk_at", 0) < 120:
        return state.get("_live_hold")
    state["_livechk_at"] = now
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import shipcheck as sc
    lf = os.path.join(Q, "live.txt")
    try:
        x = open(lf).read().split()
        lv, lbot = int(x[0].lstrip("v")), x[1]
    except (OSError, IndexError, ValueError):
        state["_live_hold"] = None
        return None
    pv, notes = sc.platform_listing()
    # 11 Nov (TB: the Builder's hand-submit v785 was never written to live.txt; this check compared live.txt with the platform's ACTIVE
    # version (still 784 while 785 compiled), did not hold, and xde1 auto-shipped on v784 as v786 without the hand-submitted fix): compare
    # with the NEWEST submitted version
    if pv is not None and notes:
        pv = max([pv] + list(notes))
    if pv is None:  # 12 Nov (TB): 4104f8f9 lost this line, so every SUCCESSFUL call logged 'failed' and returned unchecked (guard off since ~00:00Z)
        log("live check: the platform call failed; not holding (live.txt stays the reference)")
        state["_live_hold"] = None
        return None
    if pv <= lv:
        if state.get("_live_hold"):
            log(f"live check: live.txt v{lv} agrees with the platform again: starts resume")
        state["_live_hold"] = None
        return None
    nm = re.search(r"(nova_[A-Za-z0-9_.+-]+)", notes.get(pv, ""))
    if nm and os.path.isdir(os.path.join(REPO, "bots", nm.group(1), "src")):
        with open(sc.SUBMIT_LOCK, "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            sc.prepend_live(f"v{pv} {nm.group(1)} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} parent={lbot} inferred", lf)
        log(f"LIVE MISMATCH: live.txt v{lv}, platform v{pv}: corrected live.txt to v{pv} {nm.group(1)} (the platform note "
            f"names it; parent {lbot} inferred)")
        state["_live_hold"] = None
        return None
    hold = f"LIVE MISMATCH: live.txt v{lv}, platform v{pv}"
    if state.get("_live_hold") != hold:
        log(f"{hold}: holding new shipcheck starts until live.txt is corrected (the platform note does not name a bot here)")
    state["_live_hold"] = hold
    return hold


def lost_files(rq, cand, base, live, merged, files):
    """Split relqueue.same_change's files: a file whose merged copy equals live's is fine when everything the candidate
    changed in it (vs base) is already in live (its added lines present, its removed lines absent), e.g. b254 built on the
    unsubmitted b251 rollback that live v294 also carries (29 Oct). Otherwise the candidate's change was lost.
    -> (lost files, other differing files)"""
    c, b, l, m = rq.tree(cand), rq.tree(base), rq.tree(live), rq.tree(merged)
    lost, other = [], []
    for f in files:
        if m.get(f) != l.get(f):
            other.append(f)
            continue
        rm, ad = rq.change(b.get(f), c.get(f))
        have = set((l.get(f) or b"").decode(errors="replace").splitlines())
        if not (all(x in have for x in ad) and all(x not in have for x in rm if x.strip())):
            lost.append(f)
    return lost, other


def drop_live_marker(out):
    """A merged copy starts as a cp -rL of live: live's own SHIPCHECK must never come along (29 Oct: b254_r294 got TAG=252)."""
    p = os.path.join(out, "SHIPCHECK")
    if os.path.lexists(p):
        os.remove(p)


def rebase(name, kv, confirm_from=None):
    """-> (new bot name or None, why). confirm_from=TAG (owner 9 Nov): the copy's marker gets CONFIRM_FROM=TAG, CONFIRM_N=1, so shipcheck runs
    CONFIRM MODE (1,200 fresh maps v live) instead of the full check. A marker that already has CONFIRM_FROM (live moved again: before its start or
    during its confirm read) keeps it with CONFIRM_N + 1, at most CONFIRM_MAX (2); past that both keys are dropped and the copy gets the full check."""
    sys.path.insert(0, os.path.join(REPO, "tools/lab"))
    import relqueue as rq
    import shipcheck as sc
    ch = live_chain()
    if len(ch) < 3:
        return None, "no live chain in CLAUDE.md"
    (ver, live) = ch[0]
    # 12 Nov (owd1qs/nrf1qrs/hsk33s: three PASSes built on v796 dropped when v797 and v798 shipped during their checks): the base may be up to
    # SW_REBASE_BACK (4) live versions back, not only the previous one; the 3-way merge then runs from that base onto live.
    tried = []
    for i in range(1, min(len(ch) - 1, 1 + int(os.environ.get("SW_REBASE_BACK", 4)))):
        parent, gparent = ch[i][1], ch[i + 1][1]
        k, t = sc.live_own(name, parent, gparent)
        if t and k >= 0.95 * t:
            break
        # 12 Nov (TB: v825 shipped and all 40 waiting markers read v824 27/30 and were skipped): armq builds lines on the BAKED base
        # nova_base_vNNN, where a shipped flag's table and test are folded into plain code; read the baked pair too, and merge from it
        bp, bg = f"nova_base_v{ch[i][0]}", f"nova_base_v{ch[i + 1][0]}"
        if all(os.path.isdir(os.path.join(REPO, "bots", b, "src")) for b in (bp, bg)):
            k2, t2 = sc.live_own(name, bp, bg)
            if t2 and k2 >= 0.95 * t2:
                parent = bp
                break
            tried.append(f"v{ch[i][0]} {k}/{t} (baked {k2}/{t2})")
            continue
        tried.append(f"v{ch[i][0]} {k}/{t}")
    else:
        return None, f"not built on live {live} nor on the {len(tried)} live version(s) before it ({', '.join(tried)} of their own lines)"
    lc = lost_change(name, parent, live, ch, sc)
    if lc:
        return None, (f"needs manual merge: {name} carries v{lc[0]}'s {lc[2]} ({lc[1]}) which live v{ver} {live} lacks")
    new = f"{name}_r{ver}"
    out = os.path.join(NEWB, new)
    if os.path.lexists(os.path.join(REPO, "bots", new)) or os.path.lexists(out):
        return None, f"{new} exists already"
    orig = rq.tree
    rq.tree = lambda b: {f: v for f, v in orig(b).items() if os.path.basename(f) != "SHIPCHECK"}  # markers never merge
    try:
        b = lambda n: os.path.join(REPO, "bots", n)  # noqa: E731
        bad = rq.merge3(b(name), b(parent), b(live), out)
        if os.path.isdir(out):
            drop_live_marker(out)
        if bad:
            return None, f"merge onto {live} has conflicts: {'; '.join(bad)[:200]}"
        diff = rq.same_change(b(name), b(parent), b(live), out)
        lost, other = lost_files(rq, b(name), b(parent), b(live), out, diff) if diff else ([], [])
        if lost:
            return None, f"candidate change lost in {', '.join(lost)[:200]} (copy {out} left, not linked)"
        if other:
            return None, f"merged copy {out} changes differently from {name} in {', '.join(other)[:200]} (copy left, not linked)"
    except RuntimeError as e:
        return None, f"merge failed: {str(e)[:200]}"
    finally:
        rq.tree = orig
    subprocess.run(["chmod", "-R", "u+w", out])
    out = shutil.move(out, os.path.join(REPO, "bots", new))  # owner 1 Nov: a real dir, not a link
    tag = kv["TAG"] + f"r{ver}"
    kv2, cf = {k: v for k, v in kv.items() if k not in ("CONFIRM_FROM", "CONFIRM_N")}, ""
    if confirm_from:
        kv2.update(CONFIRM_FROM=confirm_from, CONFIRM_N="1")
    elif kv.get("CONFIRM_FROM"):
        n = (int(kv["CONFIRM_N"]) if kv.get("CONFIRM_N", "").isdigit() else 1) + 1
        if n <= CONFIRM_MAX:
            kv2.update(CONFIRM_FROM=kv["CONFIRM_FROM"], CONFIRM_N=str(n))
        else:
            cf = f"# CONFIRM_FROM={kv['CONFIRM_FROM']} dropped: live moved {n} times since that full PASS (cap {CONFIRM_MAX}): full check\n"
    if kv2.get("CONFIRM_FROM"):
        cf = f"# owner 9 Nov: CONFIRM MODE, stale PASS from TAG {kv2['CONFIRM_FROM']}, live move {kv2['CONFIRM_N']} of at most {CONFIRM_MAX}\n"
    open(os.path.join(out, "SHIPCHECK"), "w").write(
        f"# auto-rebased by shipwatch from {name} (built on {parent}) onto v{ver} {live}\n{cf}TAG={tag}\n"
        + "".join(f"{key}={kv2[key]}\n" for key in kv2 if key != "TAG"))  # every key but TAG (PRIO was lost, 29 Oct)
    return new, (f"rebased onto v{ver} {live} as {new}, TAG {tag} (clean merge, same change)"
                 + (f"; CONFIRM MODE from TAG {kv2['CONFIRM_FROM']} (move {kv2['CONFIRM_N']})" if kv2.get("CONFIRM_FROM") else "; full check" if cf else ""))


def born(path):
    """The dir's birth time (statx), else its src/'s ctime. Not the dir's own ctime: NFS has no birth time, and writing SHIPCHECK
    into the dir bumps that ctime, so 22 of 60 fresh markers read "older than the copy" (2 Nov, bundle 34 refused twice)."""
    try:
        w = int(subprocess.run(["stat", "-c", "%W", path], capture_output=True, text=True).stdout.strip() or 0)
    except ValueError:
        w = 0
    return w if w > 0 else os.stat(os.path.join(path, "src")).st_ctime


def seed_tags(state):
    tags = state.setdefault("_tags", {})
    if not tags and os.path.exists(LOG):
        for line in open(LOG, errors="replace"):
            m = re.search(r"\] ?start (\S+): shipcheck TAG=(\S+)|Z start (\S+): shipcheck TAG=(\S+)", line)
            if m and "[dry]" not in line:
                bot, tag = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                tags.setdefault(tag, bot)
    return tags


def running(state):
    """Shipchecks running now: started ones whose per-candidate lock is held."""
    n = 0
    for name, st in state.items():
        if name.startswith("_") or not isinstance(st, dict) or st.get("status") != "started":
            continue
        if os.path.exists(os.path.join(Q, f"seqext_{name}")):  # a sequential read's extension (shipcheck seq_extend): hours of new maps at low priority, no slot
            continue
        with open(os.path.join(Q, f".shipwatch_{name}.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
            except BlockingIOError:
                n += 1
    return n


START_BURST = int(os.environ.get("SW_START_BURST", 4))  # starts a scan while the load is under SW_START_LOAD
START_GAP = float(os.environ.get("SW_START_GAP", 15))  # 10 Nov: staggered starts (owner); 45 -> 15 at ~23:58Z (spot games left HOST)
START_LOAD = float(os.environ.get("SW_START_LOAD", 52))  # 12 Nov ~17:0xZ tried 58, reverted at once: cpu psi 73% (local CPU is the ceiling); ~16:4xZ back to 52 (load 76, cpu psi 52% at cap 30); 12 Nov ~16:3xZ (owner: "start testing more as we have more pilots", 192 pilots): 52 -> 60. 10 Nov 23:15Z: 44 -> 52 (TB 6ad907: the stagger held ship checks behind others' load)
START_VALVE = int(os.environ.get("SW_START_VALVE", 8))
FIX_MAX_FILE = os.path.join(Q, "fix_max")  # 9 Nov 18:15Z (owner): "limit the amount of bug fix shipchecks they can reserve as we want behaviour changes more"


def fix_max():
    """At most this many fix-lane (bug fix) shipchecks at once while any non-fix line waits (bq/fix_max, default 4).
    12 Nov (owner via the Builder: "limit slots of fixes"): bq/fix_max = 'half' means ceil(the running cap / 2), the cap being the
    pilot-scaled max_default(), so fixes hold at most half the slots while behaviour / draft lines wait."""
    try:
        v = open(FIX_MAX_FILE).read().split()[0]
        if v == "half":
            return max(1, -(-max_default() // 2))
        return max(0, int(v))
    except (OSError, ValueError, IndexError):
        return 4


def running_fix(state):
    """Running shipchecks whose marker is LANE=fix (the bug-fix lane)."""
    n = 0
    for name, st in state.items():
        if name.startswith("_") or not isinstance(st, dict) or st.get("status") != "started":
            continue
        with open(os.path.join(Q, f".shipwatch_{name}.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                continue
            except BlockingIOError:
                pass
        try:
            if parse(os.path.join(REPO, "bots", name, "SHIPCHECK")).get("LANE", "behaviour") == "fix":
                n += 1
        except (OSError, ValueError):
            pass
    return n


def rare_max():
    """11 Nov ~02:25Z (owner: "limit amount of rare reads if affecting load and speed of iteration"): at most bq/rare_max (default 6) RARE
    shipchecks run at once; more wait as markers (none is stopped). Behaviour, fix and draft lines start ahead of them."""
    try:
        return max(0, int(open(os.path.join(Q, "rare_max")).read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 6


def running_rare(state):
    """Running shipchecks whose marker has RARE= (the rare lane)."""
    n = 0
    for name, st in state.items():
        if name.startswith("_") or not isinstance(st, dict) or st.get("status") != "started":
            continue
        with open(os.path.join(Q, f".shipwatch_{name}.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                continue
            except BlockingIOError:
                pass
        try:
            if parse(os.path.join(REPO, "bots", name, "SHIPCHECK")).get("RARE"):
                n += 1
        except (OSError, ValueError):
            pass
    return n


def nonfix_waiting(ready):
    """A behaviour / draft / rare line waits: a ready marker, or a line in armq's queue, whose lane is not fix."""
    if any(r["kv"].get("LANE", "behaviour") != "fix" for r in ready):
        return True
    try:
        for ln in open(os.path.join(Q, "armq.txt")):
            if ln.strip() and json.loads(ln).get("lane", "behaviour") != "fix":
                return True
    except (OSError, ValueError):
        pass
    return False


def our_queue():
    """Our Condor jobs idle + running, or None if condor_q fails."""
    if os.environ.get("FAKE_QUEUE"):  # tests
        return int(os.environ["FAKE_QUEUE"])
    # 31 Oct 02:30 (Builder): agents' cqbatch jobs (batch cqb_*) and remote UB audits (ub_*) are not ship-leg load: they
    # held our count over 300 while pilots idled. Count our idle + running jobs without them.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import condorroute  # 7 Nov: with no schedd here this returned None, which turned QUEUE_MAX off
        out = subprocess.run(["condor_q", "-af", "JobBatchName", "JobStatus"], capture_output=True, text=True, timeout=60, env=condorroute.env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    n = 0
    for ln in out.stdout.splitlines():
        f = ln.split()
        if len(f) >= 2 and f[1] in ("1", "2") and not f[0].startswith(("cqb_", "ub_")):
            n += 1
    return n


def ended(state):
    """Record every shipcheck that finished since the last scan (its lock is free): its OVERALL and whether a leg had no
    result. Its state entry keeps the marker hash, so the marker is not run again."""
    rec = state.setdefault("_ended", [])
    for name, st in list(state.items()):
        if name.startswith("_") or not isinstance(st, dict) or st.get("status") != "started":
            continue
        with open(os.path.join(Q, f".shipwatch_{name}.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
            except BlockingIOError:
                continue
        try:
            txt = open(st.get("out", ""), errors="replace").read()
        except OSError:
            txt = ""
        m = re.search(r"OVERALL: (\w+)", txt)
        overall = m.group(1) if m else ("REFUSED" if "REFUSED" in txt else "ENDED")
        if "STACK VOID" in txt:
            overall = "VOID"  # its base did not ship: says nothing about capacity, so no self-heal
        # 10 Nov 21:20Z: a trunk-code gate that ran out of time (its kill gate extends up to 9 stages near .50) is not a capacity problem:
        # it cut MAX_RUNNING 22 -> 2 (afb2, bgf2). Only no-result lines other than the trunk-code row count.
        _nr = [ln for ln in txt.splitlines() if re.search(r"no result\s", ln) and "trunk code vs live" not in ln]
        nores = (overall == "INCONCLUSIVE" and bool(_nr)
                 and "INCONCLUSIVE CAUSE: harness" not in txt  # a name/reference/base refusal is not a capacity problem
                 and not re.search(r"INCONCLUSIVE CAUSE: (too rare|not rare)", txt))  # 9 Nov: nor a too-rare / not-rare change (drcdxi 10309)
        try:  # 8 Nov: legs starved by the HOME guard (condab touches preflight_hold while it waits) are not a capacity problem: the
            # 09:38 home spike cut MAX_RUNNING 6 -> 2 for an hour after it had already cleared
            if nores and time.time() - os.path.getmtime("/data/USER/st/bq/preflight_hold") < 1800:
                nores = False
                log(f"self-heal: {name}'s no-result leg came while condab waited on the home guard: not counted")
        except OSError:
            pass
        rec.append(dict(name=name, tag=st.get("tag"), overall=overall, noresult=nores, at=time.time()))
        st["status"] = f"ended: {overall}" + (" (a leg had no result)" if nores else "")
        # 12 Nov ~20:5xZ (owner: "if there is a rare change can you tell us what percentage of maps"): a rare read's changed-map share
        rshare = ""
        mr = re.search(r"\((\d+) of (\d+) pool maps changed", txt)
        mn = re.search(r"not a rare change: (\d+)% of maps changed", txt)
        mb = re.search(r"rare changed maps\s+\S+ \[[^\]]*\] n (\d+)/(\d+)", txt)
        if mr and int(mr.group(2)) > 0:  # 12 Nov ~23:5xZ: a banked read reads n maps; the pool share is the probe's (nef2as read 420 bank maps, pool 48/1,494)
            rshare = (f" [rare: read {mb.group(1)} changed maps; pool {int(mr.group(1)):,} of {int(mr.group(2)):,} changed = "
                      f"{100 * int(mr.group(1)) / int(mr.group(2)):.1f}%]" if mb else
                      f" [rare: {int(mr.group(1)):,} of {int(mr.group(2)):,} maps changed = {100 * int(mr.group(1)) / int(mr.group(2)):.1f}%]")
        elif mn:
            rshare = f" [rare probe: {mn.group(1)}% of maps changed: not rare]"
        elif mb:
            rshare = f" [rare: read on {mb.group(1)} banked class maps]"
        log(f"ended {name}: {overall}" + (" (a leg had no result)" if nores else "") + rshare)
        if overall == "PASS" and "REFUSED: rebase onto live first" in txt:
            # 31 Oct (Builder; 564s and others): the gate PASSED but another candidate shipped mid-check, so the submit was
            # REFUSED for base. Rebase as before a start (rebase(): clean merge-file onto the new live, same change, else
            # skipped) into NAME_r<ver> with a fresh marker; the next scan runs the FULL gate on the new base. No submit here.
            try:
                kv = parse(os.path.join(REPO, "bots", name, "SHIPCHECK"))
                # owner 9 Nov ~17:20Z: a full PASS refused for base gets a short CONFIRM read on the new live (CONFIRM_FROM=its TAG); a confirm read
                # refused again keeps its CONFIRM_FROM with CONFIRM_N + 1 (rebase(): at most CONFIRM_MAX, then the full check)
                new, why2 = rebase(name, kv, None if kv.get("CONFIRM_FROM") else kv["TAG"])
            except Exception as e:  # noqa: BLE001
                kv, new, why2 = {}, None, f"rebase not tried ({str(e)[:120]})"
            log(f"{'REBASE' if new else 'skip'} {name}: gate PASSED but REFUSED for base (live moved mid-check); {why2}")
            if new and not DRY and kv.get("TAG"):
                state.setdefault("_tags", {})[kv["TAG"] + "r" + new.rsplit("_r", 1)[-1]] = new
            st["status"] += f"; rebased -> {new}" if new else f"; rebase skipped: {why2[:120]}"
    del rec[:-30]


def max_running(state):
    """MAX_RUNNING, or LOW_MAX for an hour after >= 2 of the last 6 endings (since the last change) had a leg with no result."""
    now, until = time.time(), state.get("_low_until", 0)
    if until and now >= until:
        log(f"self-heal: MAX_RUNNING back to {max_default()} (the hour at {LOW_MAX} is over)")
        state["_low_until"], state["_low_since"] = 0, now
        until = 0
    if not until:
        last = [e for e in state.get("_ended", []) if e["at"] > state.get("_low_since", 0)][-6:]
        # 11 Nov (eap2r2r + its re-arm eap2r2ri cut MAX_RUNNING 8 -> 2 for an hour): a line and its re-arms count once (by slug root)
        import re as _re
        root = lambda nm: _re.sub(r"[iurs]+$", "", nm.split("_", 2)[-1]) if nm.count("_") >= 2 else nm  # noqa: E731
        bad = len({root(e["name"]) for e in last if e["noresult"]})
        if bad >= 2:
            state["_low_until"], state["_low_since"] = now + LOW_FOR, now
            log(f"self-heal: {bad} of the last {len(last)} shipchecks ended INCONCLUSIVE with a leg that had no result "
                f"({', '.join(e['name'] for e in last if e['noresult'])}): MAX_RUNNING {max_default()} -> {LOW_MAX} for 1 h")
            return LOW_MAX
        return max_default()
    return min(LOW_MAX, max_default())


def launch(r, state, tags):
    name, kv, h = r["name"], r["kv"], r["h"]
    lk = open(os.path.join(Q, f".shipwatch_{name}.lock"), "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"wait {name}: a shipcheck for it is still running")
        lk.close()
        return False
    out = os.path.join(Q, f"shipwatch_{name}_{kv['TAG']}.out")
    env = dict(os.environ, **{k: v for k, v in kv.items() if k in ("TRIGGER", "MECH", "MECHCMD", "SUBSET", "LANE", "SUBJECT", "BIGSET", "NULLSW",
                                                             "DONORS", "LIVEVALS", "TRUNK", "STACK_ON", "BUGBAR", "Q1BAR", "PARAMBAR", "SEQ_SPAR", "FUELX", "RARE", "RAREFAMS", "BASEHAS", "SHADOW", "REVISES",
                                                             "CONFIRM_FROM", "CONFIRM_N", "CLASS", "WFAMS", "IDENT_OK", "IDENTSHIP")})
    env.update(r.get("env") or {})  # 11 Nov: a rare read on its bank (rarebank.gate: CP_RAREBANK, SP_CHANGED_TARGETED_ONLY)
    if "REUSE_LX" in kv:
        env["SC_REUSE_LX"] = kv["REUSE_LX"]
    if "BIG" in kv:
        env["SC_LH_BIG"] = kv["BIG"]  # shipcheck: the live h2h also plays the first BIG frozen bank maps (mapbank.py)
    if DRY:
        env["DRY"] = "1"
    else:
        env.pop("DRY", None)
    args = ["sh", os.path.join(REPO, "tools/lab/shipcheck.sh"), name, kv["TAG"]]
    # 9 Nov 17:16Z: ten shipchecks shared shipwatch's unit and its 8 GB cap, and the OOM killer took a draft probe (wglds 10190). Each
    # shipcheck now runs in its own scope with its own cap (owner 9 Nov heavy-job rule: MemoryMax=8G); a scope execs in place, so the
    # lock fd below is still inherited. SW_SC_MEM sets the cap; SW_SC_SCOPE=0 runs it in shipwatch's own unit as before.
    if os.environ.get("SW_SC_SCOPE", "1") != "0" and shutil.which("systemd-run"):
        unit = re.sub(r"[^A-Za-z0-9_.-]", "_", f"nova-sc-{kv['TAG']}-{int(time.time())}")
        args = ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={unit}", "-p", f"MemoryMax={os.environ.get('SW_SC_MEM', '8G')}",
                "--"] + args
    # the child inherits the lock fd and holds it until shipcheck exits: one shipcheck per candidate
    subprocess.Popen(args, cwd=REPO, env=env, stdout=open(out, "w"), stderr=subprocess.STDOUT, pass_fds=(lk.fileno(),),
                     start_new_session=True)
    lk.close()
    log(f"start {name}: shipcheck TAG={kv['TAG']} LANE={kv.get('LANE', 'behaviour')} PRIO={r['prio']}"
        + (f" TRIGGER={kv['TRIGGER']}" if "TRIGGER" in kv else "") + (" MECH" if "MECH" in kv else "")
        + (f" REUSE_LX={kv['REUSE_LX']}" if "REUSE_LX" in kv else "") + (f" BIG={kv['BIG']}" if "BIG" in kv else "")
        + (f" CONFIRM_FROM={kv['CONFIRM_FROM']} (move {kv.get('CONFIRM_N', '1')})" if "CONFIRM_FROM" in kv else "")
        + f"{' (DRY=1)' if DRY else ''}; output {out}")
    state[name] = dict(marker=h, status="started", tag=kv["TAG"], at=time.time(), out=out)
    state.get("_queue", {}).pop(name, None)
    if not DRY:
        tags[kv["TAG"]] = name
    return True


def ub_prebuild(r, state):
    """A WAITING marker: start ubaudit's instrumented build of CAND (and live) now, once per marker content, so the ~7.5 min
    debug build is done when its shipcheck starts (30 Oct, iteration-speed). Same cache and build locks as the audit itself."""
    if state.setdefault("_ubpre", {}).get(r["name"]) == r["h"]:
        return
    try:  # 10 Nov ~23:20Z (owner: "do anything to make it go faster"; Builder): the ~7.5 min local debug build only while the machine has
        # room; above SW_UBPRE_LOAD (40) it is retried on a later scan (the shipcheck builds it itself if it starts first)
        if os.getloadavg()[0] > float(os.environ.get("SW_UBPRE_LOAD", 40)):
            return
    except OSError:
        pass
    state["_ubpre"][r["name"]] = r["h"]
    try:
        live = open(os.path.join(Q, "live.txt")).read().split()[1]
    except (OSError, IndexError):
        live = None
    out = os.path.join(Q, f"ubpre_{r['name']}.log")
    args = ["nice", "-n", "10", "sh", os.path.join(REPO, "tools/lab/ubaudit.sh"), "--build-only", r["name"]] + ([live] if live else [])
    if DRY:
        log(f"[dry] ubaudit prebuild {r['name']}: {' '.join(args[3:])}")
        return
    subprocess.Popen(args, cwd=REPO, stdout=open(out, "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    log(f"ubaudit prebuild {r['name']} (waiting marker): instrumented build started, log {out}")


def scan(state):
    tags = seed_tags(state)
    ended(state)
    maxr = max_running(state)  # every scan, so a restore is logged even with nothing waiting
    hold = live_check(state)   # every scan (at most one platform call per 2 min)
    ready = []
    for marker in sorted(glob.glob(os.path.join(REPO, "bots", "nova_b*", "SHIPCHECK"))):
        name = os.path.basename(os.path.dirname(marker))
        link = os.path.join(REPO, "bots", name)
        try:  # 9 Nov 16:02Z: `armq.py drop-armed` renamed a marker between the glob and this read; shipwatch died (FileNotFoundError) for 14 min
            h = hashlib.sha1(open(marker, "rb").read()).hexdigest()[:12]
            mt = os.path.getmtime(marker)
        except OSError:
            continue  # the marker vanished mid-scan (dropped or renamed): nothing to do
        if state.get(name, {}).get("marker") == h:
            continue  # this marker was handled (run or skipped) already
        if not ((not os.path.islink(link) or os.path.realpath(link) == os.path.join(NEWB, name))
                and os.path.isdir(os.path.join(link, "src"))):
            log(f"skip {name}: not a newbot.sh copy (bots/{name} -> {os.path.realpath(link)})")
            state[name] = dict(marker=h, status="skipped: not a newbot copy", at=time.time())
            continue
        try:
            kv = parse(marker)
        except FileNotFoundError:
            continue  # dropped between the read above and here: not 'handled', so a restored marker is still seen
        except (ValueError, OSError) as e:
            log(f"skip {name}: marker does not parse ({e})")
            state[name] = dict(marker=h, status=f"skipped: {e}", at=time.time())
            continue
        num = re.match(r"nova_b(\d+)([a-z]*)", name)
        if not num or not re.fullmatch(rf"{num.group(1)}[a-z0-9_]*", kv["TAG"]):
            log(f"REFUSE {name}: TAG={kv['TAG']} does not belong to this bot (its number {num.group(0)[6:] if num else '?'}); "
                f"an inherited marker? write a new SHIPCHECK")
            state[name] = dict(marker=h, status="refused: TAG not the bot's", at=time.time())
            continue
        real = os.path.realpath(link)
        if mt + 1 < born(real):  # 1 s: timestamps come from different clocks; an inherited marker is far older
            log(f"REFUSE {name}: SHIPCHECK ({time.strftime('%H:%M:%S', time.gmtime(mt))}Z) is older than "
                f"the copy ({time.strftime('%H:%M:%S', time.gmtime(born(real)))}Z): inherited from the source bot; write a new one")
            state[name] = dict(marker=h, status="refused: marker older than the copy", at=time.time())
            continue
        if tags.get(kv["TAG"], name) != name:
            log(f"REFUSE {name}: TAG={kv['TAG']} was used by {tags[kv['TAG']]}; pick a new TAG")
            state[name] = dict(marker=h, status=f"refused: TAG used by {tags[kv['TAG']]}", at=time.time())
            continue
        if "STACK_ON" in kv:
            if not shipstack.enabled(Q):
                log(f"REFUSE {name}: STACK_ON={kv['STACK_ON']} but stacking is off ({shipstack.SWITCH} is not in {Q})")
                state[name] = dict(marker=h, status="refused: stacking is off", at=time.time())
                continue
            if not str(state.get(kv["STACK_ON"], {}).get("status", "")).startswith(("started", "ended")):
                continue  # A has not started: B has nothing to carry yet, the next scan looks again
        try:
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
            import shipcheck as sc
            live, _, parent = sc.live_bot()
            # 13 Nov 19:4xZ (TB: 37 waiting lines, each scan re-ran base_check for every one and a scan took minutes, so starts lagged):
            # a PASSING base check is cached per (line, marker hash, live) for the life of this process; a failing one is not
            _bk = (name, h, live)
            # 13 Nov 20:5xZ (TB, Coordinator approved: after a ship every queued line re-ran base_check, ~8 s each, ~13 min with no starts):
            # a marker whose BASE=nova_base_vNNN is older than live.txt's version was armed on an older live: it fails base_check anyway,
            # so it goes straight to the not-built-on-live path (rebase); markers without such a BASE still take the full base_check
            if _bk not in _BASE_OK and _stale_base(kv):
                _BASE_OK[_bk] = (False, f"BASE {kv.get('BASE')} is older than live {_live_ver()} (pre-check, no base_check)")
            if _bk in _BASE_OK:
                ok, why = _BASE_OK[_bk]
                if not ok:  # 19:5xZ (TB: ~15 knb* lines failing base_check at ~8 s each held every scan for minutes, 0 starts): a failed
                    continue  # line was already skipped/re-queued once on this live; skip it silently, no second base check or rebase
            else:
                os.environ["REVISES"] = kv.get("REVISES", "")  # 10 Nov: the marker's deliberate revisions of live lines (cis5) count here too
                try:
                    ok, why = sc.base_check(name, live, parent)
                finally:
                    os.environ.pop("REVISES", None)
                _BASE_OK[_bk] = (bool(ok), why)
        except Exception as e:  # noqa: BLE001
            ok, why = True, f"base check not run here ({e}); shipcheck checks it"
        if not ok:
            new, why2 = rebase(name, kv)
            log(f"{'REBASE' if new else 'skip'} {name}: not built on live {live} ({why[:120]}); {why2}")
            if new and not DRY:
                tags[kv["TAG"] + "r" + new.rsplit("_r", 1)[-1]] = new  # register the rebased TAG at once
            state[name] = dict(marker=h, status=f"rebased -> {new}" if new else f"skipped: {why2[:120]}", at=time.time())
            continue
        pr_, fam_ = int(kv.get("PRIO", 0)), False
        try:  # 12 Nov ~20:5xZ (owner via the Coordinator: carries and funneling are the top item; funnel-family checks get slot priority):
            # bq/prio_family.txt, one 'REGEX  # owner: ...' a line, matched on the line's name, FLIPS and SUBJECT -> PRIO at least 5
            for ln_ in open(os.path.join(Q, "prio_family.txt")):
                rx_ = ln_.split("#")[0].strip()
                if rx_ and re.search(rx_, " ".join((name, kv.get("FLIPS", ""), kv.get("SUBJECT", ""))), re.I):
                    pr_, fam_ = max(pr_, 5), True
                    break
        except (OSError, re.error):
            pass
        try:  # 13 Nov ~19:1xZ (owner, typed to the Builder: "prioritise the prism upgrades"): bq/prio_first.txt -> PRIO at least 9, dedicated slots
            _k = 0  # 19:4xZ (owner via Planner: broad high-odds lines right after Prism): the Nth regex line gives PRIO 9 - N (Prism 9, next 8)
            for ln_ in open(os.path.join(Q, "prio_first.txt")):
                rx_ = ln_.split("#")[0].strip()
                if not rx_:
                    continue
                if re.search(rx_, " ".join((name, kv.get("FLIPS", ""), kv.get("SUBJECT", ""))), re.I):
                    pr_, fam_ = max(pr_, 9 - _k), True
                    break
                _k += 1
        except (OSError, re.error):
            pass
        ready.append(dict(name=name, kv=kv, h=h, prio=pr_, age=mt, funnel=fam_))
    if not ready:
        state.pop("_queue", None)
        return
    # 9 Nov 22:05Z (Builder: pra2f, the top behaviour line, must re-read at the front when stale): confirm re-reads (CONFIRM_FROM) start first.
    # 10 Nov ~17:15Z (owner: "we have a lot more bug fixes than behavioural changes, so increase the share they get so we can at least ship bug
    # fixes"): bug fixes (fix lane) now start BEFORE behaviour lines (was behaviour first, 9 Nov); bq/fix_max raised 6 -> 16. Oldest first within each.
    # 10 Nov ~20:00Z (owner via Builder: "sort it based on results first"): within those rules, prior evidence first (tools/lab/evid.py z;
    # none: z 0 on the fix lane, last on the others), then oldest.
    try:
        import evid as _ev
        _ed = _ev.load()
        for r in ready:
            z = _ev.get(r["name"], _ed)
            r["evid"] = z if z is not None else (0.0 if r["kv"].get("LANE", "behaviour") == "fix" else -99.0)
    except Exception:  # noqa: BLE001  the order must never stop the queue
        for r in ready:
            r["evid"] = 0.0
    # 10 Nov ~20:50Z (owner via Builder: "move the rare changes to the end as the maps would be better to generate when we have more condor
    # compute"): a RARE= line starts after every non-rare line whatever its evidence; live-bug fixes (slug dkh*) are exempt.
    def _rare_last(r):
        return bool(r["kv"].get("RARE")) and "dkh" not in r["name"]
    # 10 Nov ~21:30Z (owner: "batch bug fixes so you have more space for behavioural changes"): behaviour lines start BEFORE fix lines again
    # (was fix first since 17:15Z); fix lines also hold at most bq/fix_max slots (6) while others wait.
    # 13 Nov 19:5xZ (Builder, until the 22:35Z behaviour close: behaviour arms can't run after it, fix/fuel lines can until 23:10Z): after PRIO,
    # behaviour / draft / rare lines start before plain fix-lane lines (bq/fix_last; rm it to restore the old order)
    _fl = os.path.exists(os.path.join(Q, "fix_last"))
    def _plain_fix(r):
        return _fl and r["kv"].get("LANE", "behaviour") == "fix" and not r["kv"].get("RARE")
    ready.sort(key=lambda r: (-r["prio"], _plain_fix(r), _rare_last(r) and not _fl, "CONFIRM_FROM" not in r["kv"], r["kv"].get("LANE", "behaviour") == "fix", -r.get("evid", 0.0), r["age"]))
    run, q = running(state), our_queue()
    load = float(os.environ["FAKE_LOAD"]) if os.environ.get("FAKE_LOAD") else os.getloadavg()[0]  # (FAKE_LOAD: tests)
    started, lmax = 0, load_max()
    nfix, fmax, nonfix = running_fix(state), fix_max(), nonfix_waiting(ready)
    nrare, rmax = running_rare(state), rare_max()
    try:  # 13 Nov 22:2xZ (owner: "do not resume ideas if we cannot test them in time"): bq/no_starts -> no new shipcheck starts at all
        nostart = open("/data/USER/st/bq/no_starts").readline().strip() or "bq/no_starts"
    except OSError:
        nostart = ""
    for pos, r in enumerate(ready, 1):
        n = run + started
        isfix = r["kv"].get("LANE", "behaviour") == "fix"
        # 12 Nov (owner: "if something passes a ship check it should get a smaller test suite when retesting"): a CONFIRM copy (1,200 maps)
        # starts past MAX_RUNNING by up to SW_CONFIRM_EXTRA (2) slots and is not held by fix_max, so a stale PASS does not wait a full check.
        conf = CONFIRM_EXTRA if r["kv"].get("CONFIRM_FROM") else 0
        # 12 Nov ~21:2xZ (OWNER via the Planner, cc the Coordinator: "if testing [is the bottleneck] ... give a special slot for this
        # process"): a funnel-family line (bq/prio_family.txt) gets DEDICATED slots: SW_FUNNEL_EXTRA (2) past MAX_RUNNING, and no wait on
        # fix_max, rare_max or the start stagger. The hard load guard (LOAD_MAX), QUEUE_MAX, holds and bank gates still apply; bars unchanged.
        fun = bool(r.get("funnel"))
        if fun:
            conf = max(conf, FUNNEL_EXTRA)
        bankwhy = None
        if r["kv"].get("RARE"):  # 13 Nov (TB): every rare line goes through rarebank.gate (it applies armq's w_any default when RAREFAMS is missing). 11 Nov (owner ~02:4xZ): a rare line waits, with no slot and no CPU, until its bank
            try:                                             # of family maps from the common reads is big enough (tools/lab/rarebank.py; bq/rarebank_ON)
                sys.path.insert(0, os.path.join(REPO, "tools/lab"))
                import rarebank
                ok_b, bankwhy, r["env"] = rarebank.gate(r["name"], r["kv"])
                bankwhy = None if ok_b else bankwhy
            except Exception as e:  # noqa: BLE001  the bank must never stop the queue: the line runs as before
                log(f"!! rarebank gate {r['name']}: {type(e).__name__}: {e}")
                r["env"], bankwhy = {}, None
        why = (f"no new starts ({nostart})" if nostart and not r["kv"].get("CONFIRM_FROM") else
               hold if hold else
               bankwhy if bankwhy else
               f"{nfix} bug-fix shipchecks running (fix_max {fmax}; owner 9 Nov: behaviour changes first) while behaviour lines wait"
               if isfix and nonfix and nfix >= fmax and not conf and not fun else
               f"{nrare} rare shipchecks running (bq/rare_max {rmax}; owner 11 Nov: rare reads must not slow iteration)"
               if r["kv"].get("RARE") and nrare >= rmax and not fun else
               f"our Condor jobs {q} > QUEUE_MAX {QUEUE_MAX}" if q is not None and q > QUEUE_MAX else
               f"local load {load:.0f} > LOAD_MAX {lmax:.0f} with {n} running" if load > lmax and n >= VALVE and not fun else
               # 12 Nov ~22:3xZ (owner via the Planner: funnel tests "never wait"): a funnel line starts up to SW_FUNNEL_LOAD (90), a hard ceiling
               f"local load {load:.0f} > SW_FUNNEL_LOAD {FUNNEL_LOAD:.0f} (funnel line)" if fun and load > FUNNEL_LOAD else
               f"{n} shipchecks running (MAX_RUNNING {maxr}{f' + {conf} for confirms' if conf else ''})" if n >= maxr + conf else
               # 10 Nov ~23:00Z (owner: "lighten the main machine ... stagger pre-ship checks"): one new start per SW_START_GAP s (45),
               # none while the 1-min load is over SW_START_LOAD (44); a start's local setup (builds, map draws, spot-checks) is the burst
               f"staggered: last start {time.time() - state.get('_last_start', 0):.0f} s ago (< SW_START_GAP {START_GAP})"
               if time.time() - state.get("_last_start", 0) < START_GAP and (load > START_LOAD or started >= START_BURST) and not fun else  # 11 Nov ~00:10Z (TB 6ad907): below the load line up to SW_START_BURST (4) starts a scan, no gap
               f"staggered: local load {load:.0f} > SW_START_LOAD {START_LOAD:.0f}" if load > START_LOAD and n >= START_VALVE and not fun else None)
        if why is None:
            ok = launch(r, state, tags)
            if ok:
                state["_last_start"] = time.time()
            started += ok
            nfix += bool(ok and isfix)
            nrare += bool(ok and r["kv"].get("RARE"))
            continue
        if not bankwhy:  # a line waiting on its bank may wait hours: no ubaudit build for it now
            ub_prebuild(r, state)
        key = f"{pos}|{why}" if not bankwhy else f"{pos}|rare bank|{int(time.time() // 1800)}"  # a bank count changes often: logged once per 30 min
        if state.setdefault("_queue", {}).get(r["name"]) != key:
            log(f"queue {r['name']}: position {pos - started} of {len(ready) - started} waiting (PRIO {r['prio']}): {why}")
            state["_queue"][r["name"]] = key


def reset_heal(who="--reset-heal"):
    """Clear the self-heal (MAX_RUNNING back to the default on the running watcher's next scan); logged."""
    with open(STATE + ".lock", "a") as sl:
        fcntl.flock(sl, fcntl.LOCK_EX)
        try:
            state = json.load(open(STATE))
        except (OSError, ValueError):
            state = {}
        was = state.get("_low_until", 0)
        state["_low_until"], state["_low_since"] = 0, time.time()
        json.dump(state, open(STATE + ".new", "w"), indent=1)
        os.replace(STATE + ".new", STATE)
    log(f"self-heal: RESET ({who}); it had MAX_RUNNING {LOW_MAX} until "
        f"{time.strftime('%H:%M:%S', time.gmtime(was)) + 'Z' if was else 'nothing (it was not active)'}; "
        f"MAX_RUNNING {MAX_RUNNING} from the next scan")


FIXBATCH = [None, 0.0]  # [the running tick's Popen, its start time]


def fixbatch_tick():
    """Owner 9 Nov ~21:35Z ("yes batch bug fixes"): every 60 s a separate `fixbatch.py --tick` (its own process: a slow armq preflight or a bug
    there never holds up a scan; edits to fixbatch.py apply at the next tick). It releases batched fix-lane PASSes as one bundle and falls back
    to the single fixes; bq/fixbatch_OFF turns batching off (see fixbatch.py). Not in WATCH_DRY."""
    p, t = FIXBATCH
    if p is not None and p.poll() is None:
        return
    if DRY or time.time() - t < 60 or not os.path.exists(os.path.join(REPO, "tools/lab/fixbatch.py")):
        return
    try:
        FIXBATCH[0] = subprocess.Popen([sys.executable, "-I", os.path.join(REPO, "tools/lab/fixbatch.py"), "--tick"], cwd=REPO,
                                       stdout=open(os.path.join(Q, "fixbatch.out"), "a"), stderr=subprocess.STDOUT, start_new_session=True)
        FIXBATCH[1] = time.time()
    except OSError as e:
        log(f"!! fixbatch tick not started: {e}")


RAREBANK = [None, 0.0]  # [the running tick's Popen, its start time]


def rarebank_tick():
    """11 Nov (owner: "store maps you find in common reads that fit one of the rare reads"): every RAREBANK_TICK (120) s a separate nice'd
    `rarebank.py tick` banks fitting maps of the common fresh sets for waiting rare lines (only while bq/rarebank_ON exists). Not in WATCH_DRY."""
    p, t = RAREBANK
    if p is not None and p.poll() is None:
        return
    if DRY or time.time() - t < int(os.environ.get("RAREBANK_TICK", 120)) or not os.path.exists(os.path.join(Q, "rarebank_ON")):
        return
    try:
        RAREBANK[0] = subprocess.Popen(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/rarebank.py"), "tick"], cwd=REPO,
                                       stdout=open(os.path.join(Q, "rarebank.out"), "a"), stderr=subprocess.STDOUT, start_new_session=True)
        RAREBANK[1] = time.time()
    except OSError as e:
        log(f"!! rarebank tick not started: {e}")


def main():
    if "--reset-heal" in sys.argv:
        return reset_heal()
    once = "--once" in sys.argv
    log(f"shipwatch up (pid {os.getpid()}, {'once' if once else 'every 30 s'}, MAX_RUNNING {max_default()} ({MAX_RUNNING_FILE} if set), QUEUE_MAX {QUEUE_MAX})")
    if not once:
        open(PIDFILE + ".new", "w").write(f"{os.getpid()}\n")
        os.replace(PIDFILE + ".new", PIDFILE)
    while True:
        with open(STATE + ".lock", "a") as sl:
            fcntl.flock(sl, fcntl.LOCK_EX)
            try:
                state = json.load(open(STATE))
            except (OSError, ValueError):
                state = {}
            try:
                scan(state)
            except OSError as e:  # 9 Nov: a file another tool renamed or removed mid-scan must cost one scan, not the daemon
                log(f"!! scan: {type(e).__name__}: {e} (a file changed under the scan); retrying in 30 s")
            json.dump(state, open(STATE + ".new", "w"), indent=1)
            os.replace(STATE + ".new", STATE)
        fixbatch_tick()
        rarebank_tick()
        if once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
