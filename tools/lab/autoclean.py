#!/usr/bin/env python3
"""autoclean: delete our regenerable leftovers, on a timer (Tool builder 2, 4 Nov; owner: 'make sure you delete our files. Use a
hook to constantly do this'). Started by .claude/hooks/autoclean_hook.py at most every AUTOCLEAN_SECS (1800) from any session,
detached, nice 19 / idle I/O. Off switch: touch /data/zw4424/st/autoclean/OFF. Log: /data/zw4424/st/autoclean/log.

usage: python3 -I tools/lab/autoclean.py [--apply]   (DRY by default: prints what it would remove)
Removes ONLY (each step skips anything a running process has open, as cwd or in its command line, and anything named in
/data/zw4424/st/bq/pending_reads.txt):
 1 readmany run dirs (/data/zw4424/readmany/runs/*) untouched for 12 h whose pid is gone: lists, staged tars, per-job
   outputs. The read's result is the --out file the caller named, elsewhere.
 2 kept replays of finished inforead reads (/data/zw4424/st/info/TAG/rep/) untouched for 36 h, when result.txt exists and the
   TAG is not named in a report, board or queue file changed in the last 36 h. cmd.json, run.log and result.txt stay.
 3 loopprof per-game files (g*.tsv, g*.out) in /data/zw4424/st/cxe/loopprof/* after 6 h; measured.json and games.txt stay.
 4 orphaned pilot stage dirs on the home (/homes/zw4424/condor-runs/stage/{rm_,lp_}*) untouched for 24 h; cf_* (cxefarm) with their process gone, idle 6 h.
 5 identity-check game caches older than 24 h: /data/zw4424/mergecheck/games/* files (keyed by base hash: old bases
   only; a later mergecheck of such a base replays them) and /data/zw4424/st/trunkmerge/*_id dirs (finished merges' identity games).
 6 tools/lab/closedprune.py, idleprune.py and probeprune.py with their own keep rules (closed bots; idle agents' run data; draft probes' 1-round replays and old-base maps).
 7 smokefarm's kept replays (/data/zw4424/st/smoke/TAG/g) idle 6 h (7 Nov: smoke wrote 14 GB/h; deterministic, so a re-run restores them), TAG not in pending_reads or a report changed in the last 36 h; games.jsonl, rows.json, table.txt stay.
 8 draft probe games of finished reads (/data/zw4424/st/panel/TAG/probe) idle 36 h, when info/TAG/result.txt exists and TAG is not in such a report; probe.json and otf.json stay.
   (A finished read's pending_reads line doesn't hold it: those lines are never removed.)
 9 estcheck's replays and row tables (/data/zw4424/st/est/runs/RUN) idle 48 h, RUN not in pending_reads or such a report; report.txt and files under 64 KB stay.
The log gets a line after each step, so a run killed by the hook's limit still leaves a trace.
Never touches: bots in use or shipped, live/baseline/best_model, gate/shipcheck outputs, reports, maps banks, caches the
engines use, other users' files."""
import glob
import os
import re
import shutil
import subprocess
import sys
import time

APPLY = "--apply" in sys.argv
NOW = time.time()
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = "/data/zw4424/st/autoclean/log"
PEND = "/data/zw4424/st/bq/pending_reads.txt"
REPORTS = ["/homes/zw4424/condor-work/reports", "/homes/zw4424/condor-work/reports/analysts"]


def busy_paths():
    out, cmds = set(), []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            out.add(os.readlink(f"/proc/{pid}/cwd"))
            for fd in os.listdir(f"/proc/{pid}/fd"):
                out.add(os.readlink(f"/proc/{pid}/fd/{fd}"))
            cmds.append(open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="ignore"))
        except OSError:
            pass
    return out, " ".join(cmds)


BUSY, CMDS = busy_paths()
PENDING = open(PEND, errors="ignore").read() if os.path.exists(PEND) else ""


def in_use(d):
    return d in CMDS or any(p == d or p.startswith(d + "/") for p in BUSY)


def newest(d):
    m = os.lstat(d).st_mtime
    for r, ds, fs in os.walk(d):
        for f in fs + ds:
            try:
                m = max(m, os.lstat(os.path.join(r, f)).st_mtime)
            except OSError:
                pass
    return m


def size(p):
    if os.path.isfile(p):
        return os.lstat(p).st_size
    return sum(os.lstat(os.path.join(r, f)).st_size for r, _, fs in os.walk(p) for f in fs if os.path.exists(os.path.join(r, f)))


tot = {"n": 0, "b": 0}
lines = []


def drop(p, why):
    # 12 Nov (TB: the keeplist was honoured by rmdata/quotaguard/idleprune/closedprune but not here; panel/12618, kept for RC C503's
    # EMO replays, would have gone by the 6 h panel rule)
    try:
        # 12 Nov ~05:3xZ: under python3 -I (3.11+: implies -P) the script dir is not on sys.path, so this import failed and every drop since
        # 674e9710 was 'skipped: keeplist unreadable' (130,700 skips, 0 removals): put tools/lab on the path first
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import keeplist
        if keeplist.is_kept(p):
            lines.append(f"kept {p} (keep_paths.txt: {keeplist.why(p)}); {why}")
            return
    except Exception:  # noqa: BLE001  an unreadable keeplist must not turn into deletions: skip the path
        lines.append(f"skipped {p}: keeplist unreadable; {why}")
        return
    q = p.rstrip("/")  # 12 Nov (Planner: a reader's input dirs went while it read them): a .inuse file < 12 h old here or above = in use
    while q and q not in ("/", "/data", "/homes"):
        f = os.path.join(q, ".inuse")
        try:
            if os.path.isfile(f) and NOW - os.path.getmtime(f) < 12 * 3600:
                lines.append(f"kept {p} (in use: {f}); {why}")
                return
        except OSError:
            pass
        q = os.path.dirname(q)
    if p.rstrip("/") in PENDING:  # 12 Nov (TB): step_readmany removed 2 run dirs pending_reads.txt names; no rule may
        lines.append(f"kept {p} (named in pending_reads.txt); {why}")
        return
    try:
        b = size(p)
    except OSError:
        return
    tot["n"] += 1
    tot["b"] += b
    lines.append(f"{'rm' if APPLY else 'would rm'} {p} ({b / 1e6:.1f} MB; {why})")
    if APPLY:
        subprocess.run(["chmod", "-R", "u+w", p], capture_output=True)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass


def step_readmany():
    for d in glob.glob("/data/zw4424/readmany/runs/*"):
        m = re.search(r"_(\d+)$", d)
        if not os.path.isdir(d) or (m and os.path.exists(f"/proc/{m.group(1)}")) or in_use(d):
            continue
        if NOW - newest(d) > 12 * 3600:
            drop(d, "readmany run dir, idle 12 h")


class _Mentions:
    """9 Nov (autoclean OOM-killed at 8 GB in 6 s): the recent notes as a set of names, streamed, instead of one string of every .md/.txt under
    st/*/ (some are 100+ MB logs and map lists). `x in m` is true when x is a whole token, or 'smoke/TAG' / a path whose last part is a token."""
    def __init__(self, toks):
        self.t = toks

    def __contains__(self, x):
        return x in self.t or x.rsplit("/", 1)[-1] in self.t


def recent_mentions():
    toks = set()
    tok = re.compile(r"[A-Za-z0-9_.-]{4,}")
    for r in REPORTS + ["/data/zw4424/st/bq"] + glob.glob("/data/zw4424/st/*/"):  # agents' own notes count (7 Nov: dr155's cite smoke/cbd1)
        for f in glob.glob(r + "/*.md") + glob.glob(r + "/*.txt"):
            try:
                st = os.stat(f)
                if NOW - st.st_mtime >= 36 * 3600 or st.st_size > 5 * 2 ** 20:
                    continue
                with open(f, errors="ignore") as fh:
                    for ln in fh:
                        for w in tok.findall(ln):
                            toks.add(w)
                            if "/" not in w and "." in w:
                                toks.update(w.split("."))
            except OSError:
                pass
    return _Mentions(toks)


def info_age():
    """9 Nov (/data 94% after the post-crash relaunch wrote 42 GB/h): kept replays of a FINISHED read stay 36 h, 12 h once /data is 90% full,
    4 h at 94% (the result.txt and rows stay; only rep/ goes, and never for a read named in pending_reads or recent mentions)."""
    st = os.statvfs("/data")
    used = 1 - st.f_bavail / max(st.f_blocks, 1)
    return 4 * 3600 if used >= 0.94 else 12 * 3600 if used >= 0.90 else 36 * 3600


def step_info():
    ment = None
    for rep in glob.glob("/data/zw4424/st/info/*/rep"):
        d = os.path.dirname(rep)
        tag = os.path.basename(d)
        if not os.path.exists(f"{d}/result.txt") or tag in PENDING or in_use(d):
            continue
        if NOW - newest(d) < info_age():
            continue
        ment = recent_mentions() if ment is None else ment
        if tag in ment:
            continue
        drop(rep, f"finished inforead's kept replays, idle {info_age() / 3600:.0f} h")


def step_loopprof():
    for d in glob.glob("/data/zw4424/st/cxe/loopprof/*"):
        if not os.path.exists(f"{d}/measured.json") or in_use(d) or NOW - os.path.getmtime(f"{d}/measured.json") < 6 * 3600:
            continue
        for f in glob.glob(f"{d}/g*.tsv") + glob.glob(f"{d}/g*.out"):
            drop(f, "loopprof per-game counters (merged into measured.json)")


def step_stage():
    for d in glob.glob("/homes/zw4424/condor-runs/stage/cf_*"):  # 7 Nov: cxefarm stage dirs its dead owner left (125 MB each on the home)
        m = re.match(r"cf_(\d+)_", os.path.basename(d))
        if m and not os.path.exists(f"/proc/{m.group(1)}") and NOW - newest(d) > 900 and not in_use(d):  # 6 h -> 1 h (7 Nov) -> 15 min (9 Nov: home over cxefarm's 54k gate stalled identity checks)
            drop(d, "cxefarm stage dir, owner gone, idle 15 min")
    for d in glob.glob("/homes/zw4424/condor-runs/stage/2026*Z_*"):  # cqbatch/pilot stage dirs, STAMP_PID: nothing else cleaned them
        m = re.match(r"\d{8}T\d{6}Z_(\d+)$", os.path.basename(d))
        if m and not os.path.exists(f"/proc/{m.group(1)}") and NOW - newest(d) > 900 and not in_use(d):
            drop(d, "stage dir, owner gone, idle 15 min")
    # 9 Nov: condab's Condor batch dirs on the home (cq_NAME_N, ~50 files each): once no process names the batch and the pilot queue holds none of
    # its items, its results are already in the index (st/bq NAME.condor.txt and the condab index); idle 30 min
    try:
        ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=30).stdout
        q = " ".join(os.listdir("/homes/zw4424/condor-runs/pilotq/queue") + os.listdir("/homes/zw4424/condor-runs/pilotq/claimed"))
    except (OSError, subprocess.SubprocessError):
        ps = q = None
    for d in glob.glob("/homes/zw4424/condor-runs/cq_*_[0-9]*") if ps is not None else []:
        m = re.match(r"cq_(.+)_\d+$", os.path.basename(d))
        if m and m.group(1) not in ps and f"cq-{m.group(1)}-" not in q and NOW - newest(d) > 1800 and not in_use(d):
            drop(d, "condab batch dir, batch finished, idle 30 min")
    for d in glob.glob("/homes/zw4424/condor-runs/stage/rm_*") + glob.glob("/homes/zw4424/condor-runs/stage/lp_*"):
        m = re.search(r"_(\d+)$", os.path.basename(d))  # 9 Nov 18:22Z: readmany stage dirs are ~55 MB of replays each; owner pid gone -> 15 min, not 24 h
        dead = bool(m) and not os.path.exists(f"/proc/{m.group(1)}")
        if not in_use(d) and NOW - newest(d) > (900 if dead else 24 * 3600):
            drop(d, "pilot stage dir, owner gone, idle 15 min" if dead else "orphaned pilot stage dir, idle 24 h")


def step_sharedpanel():
    """stylepanel's per-live panel sets (PANEL_DIR/shared_<live>_<n>, 7 Nov): a set whose live bot is no longer live, idle 6 h, goes
    (its base legs' summaries stay in st/bq as the only record of those games)."""
    try:
        live = open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    except (OSError, IndexError):
        return
    for d in glob.glob("/data/zw4424/st/panel/shared_*"):
        if os.path.isdir(d) and not os.path.basename(d).startswith(f"shared_{live}_") and NOW - newest(d) > 6 * 3600 and not in_use(d):
            drop(d, "shared panel set of an old live version, idle 6 h")
    # 11 Nov (TB: 1,796 such dirs had piled up, /data at 24 GB free): a finished shipcheck's own fresh/panel map dirs (panel/TAG*), idle 6 h,
    # not a pending read's, not in use. Fresh maps are single-use: no read ever reuses them.
    try:  # 12 Nov (Builder: fresh-first throughput piles up panel dirs, /data 93%): idle 2 h while /data has < 80 GB free, else 6 h
        free = os.statvfs("/data").f_bavail * os.statvfs("/data").f_frsize
    except OSError:
        free = 1e12
    lim_h = 2 if free < 80e9 else 6
    for d in glob.glob("/data/zw4424/st/panel/[0-9]*"):
        tag = re.match(r"\d+", os.path.basename(d)).group(0)
        if os.path.isdir(d) and tag not in PENDING and NOW - newest(d) > lim_h * 3600 and not in_use(d):
            drop(d, f"a finished shipcheck's panel/fresh maps, idle {lim_h} h")
    # 12 Nov ~21:5xZ (Builder: /data 98%; 1,452 idle panel/tc<hash> dirs = trunk-code gates' single-use fresh maps, ~5 GB): idle 3 h (6 h
    # with >= 80 GB free), not in use
    for d in glob.glob("/data/zw4424/st/panel/tc[0-9a-f]*"):
        if os.path.isdir(d) and NOW - newest(d) > max(3, lim_h) * 3600 and not in_use(d):
            drop(d, f"a trunk-code gate's fresh maps, idle {max(3, lim_h)} h")


def step_idcache():
    for f in glob.glob("/data/zw4424/mergecheck/games/*"):
        try:
            if NOW - os.lstat(f).st_mtime > 24 * 3600 and not in_use(f):
                drop(f, "mergecheck game cache of an old base, 24 h")
        except OSError:
            pass
    for d in glob.glob("/data/zw4424/st/trunkmerge/*_id"):
        if os.path.isdir(d) and not in_use(d) and NOW - newest(d) > 24 * 3600:
            drop(d, "trunkmerge identity games, 24 h")


def step_smoke():
    ment = None
    for g in glob.glob("/data/zw4424/st/smoke/*/g"):
        d = os.path.dirname(g)
        tag = os.path.basename(d)
        if tag in PENDING or in_use(d) or NOW - newest(d) < 6 * 3600:
            continue
        ment = recent_mentions() if ment is None else ment
        if f"smoke/{tag}" not in ment:
            drop(g, "smokefarm's kept replays, idle 6 h")


def step_probe():
    ment = None
    for p in glob.glob("/data/zw4424/st/panel/*/probe"):
        d = os.path.dirname(p)
        tag = os.path.basename(d)
        if not os.path.exists(f"/data/zw4424/st/info/{tag}/result.txt") or in_use(d) or NOW - newest(d) < 36 * 3600:
            continue
        ment = recent_mentions() if ment is None else ment
        if tag not in ment:
            drop(p, "finished read's draft probe games, idle 36 h")


def step_est():
    """one log line a run, no process per file (5 Nov: a process per path filled /var through syslog)"""
    ment = None
    for d in glob.glob("/data/zw4424/st/est/runs/*"):
        run = os.path.basename(d)
        if not os.path.isdir(d) or run in PENDING or in_use(d) or NOW - newest(d) < 48 * 3600:
            continue
        ment = recent_mentions() if ment is None else ment
        if run in ment:
            continue
        n = b = 0
        for r, _, fs in os.walk(d):
            for f in fs:
                q = os.path.join(r, f)
                s = os.lstat(q).st_size
                if f == "report.txt" or (s < 65536 and not f.endswith(".repl26a")):
                    continue
                n += 1
                b += s
                if APPLY:
                    os.remove(q)
        if n:
            tot["n"] += 1
            tot["b"] += b
            lines.append(f"{'rm' if APPLY else 'would rm'} {n} files in {d} ({b / 1e6:.1f} MB; estcheck replays and rows, idle 48 h)")


def step_cxecache():
    """9 Nov 18:05Z (owner: make sure /data has room): the cxe build caches (st/cxe so 19 GB, obj 12, proj/bots 11, dbg 4.5; ~6 GB/h new) had no
    age rule. They are content-addressed and rebuilt on demand (~20 s a bot): an entry untouched (read or written) for 48 h goes, 24 h once
    /data has under 150 GB free. The live bot's and baseline's libraries are rebuilt the first time they are needed."""
    try:
        st = os.statvfs("/data")
        free = st.f_bavail * st.f_frsize
    except OSError:
        return
    # 12 Nov ~05:2xZ (Coordinator: /data 73G and falling): tighter under pressure: 12 h below 90 GB free, 6 h below 60 GB
    lim = (2 if free < 60e9 else 12 if free < 90e9 else 24 if free < 150e9 else 48) * 3600  # 12 Nov ~18:1xZ (TB: /data 95%): 6 h -> 2 h below 60 GB
    # 12 Nov ~22:5xZ (Builder: /data 98%): proj/pilotwasm (pilot-built release wasm by tree hash, rebuilt in ~30 s) held 28 GB, 23.5k files, never pruned
    for d in ("/data/zw4424/st/cxe/so", "/data/zw4424/st/cxe/obj", "/data/zw4424/st/cxe/dbg", "/data/zw4424/st/cxe/proj/bots",
              "/data/zw4424/st/cxe/proj/pilotwasm"):
        try:
            ents = list(os.scandir(d))
        except OSError:
            continue
        for e in ents:
            try:
                s = os.lstat(e.path)
                if NOW - max(s.st_atime, s.st_mtime) > lim and (not e.is_dir() or NOW - newest(e.path) > lim) and not in_use(e.path):
                    drop(e.path, f"cxe build cache, untouched {lim // 3600} h")
            except OSError:
                continue


def step_archive():
    """12 Nov (owner: "delete all unnecessary files"): condab's collected batch dirs (condor_runs_archive), idle 24 h; results already
    live in the caller's out dir. Names in pending_reads / keep_paths are kept by drop()."""
    for d in glob.glob("/data/zw4424/condor_runs_archive/cq_*"):
        if os.path.isdir(d) and NOW - os.path.getmtime(d) > 24 * 3600 and not in_use(d):
            drop(d, "condab archive, collected, idle 24 h")


def step_dswork():
    """12 Nov: draftstock work/lu_KEY_PID dirs are never removed by draftstock; drop those whose PID is gone and idle 12 h."""
    for d in glob.glob("/data/zw4424/st/draftstock/work/lu_*"):
        m = re.search(r"_(\d+)$", d)
        if not os.path.isdir(d) or (m and os.path.exists(f"/proc/{m.group(1)}")) or in_use(d):
            continue
        if NOW - newest(d) > 12 * 3600:
            drop(d, "draftstock work dir, owner gone, idle 12 h")


def step_buildcaches():
    """12 Nov (owner: "delete all unnecessary files fast"; 61 GB freed by hand): content-addressed build caches untouched 24 h:
    trunkproj/wasm/*.wasm (flip.sh's predicted wasm, rebuilt in ~1 min) unless the bot is live / armed / running, and mergecheck
    builds/ and ws/ entries."""
    keepb = set()
    try:
        keepb |= {ln.split()[1] for ln in open("/data/zw4424/st/bq/live.txt") if len(ln.split()) > 1}
        keepb |= {os.path.basename(os.path.dirname(m)) for m in glob.glob(f"{REPO}/bots/*/SHIPCHECK")}
        keepb |= set(re.findall(r"nova_[A-Za-z0-9_]+", subprocess.run(["ps", "-u", str(os.getuid()), "-o", "args="], capture_output=True, text=True).stdout))
    except OSError:
        return
    try:  # 13 Nov (TB: /data 98%, trunk wasm 20 GB, ~8k files at tonight's arm rate): 6 h while /data < 60 GB free (rebuilt in ~1 min)
        lim_w = 6 if os.statvfs("/data").f_bavail * os.statvfs("/data").f_frsize < 60e9 else 24
    except OSError:
        lim_w = 24
    for f in glob.glob("/data/zw4424/trunkproj/wasm/*.wasm"):
        try:
            if NOW - os.path.getmtime(f) > lim_w * 3600 and re.sub(r"-[0-9a-f]{8,}.*$", "", os.path.basename(f)) not in keepb:
                drop(f, f"trunk wasm cache, untouched {lim_w} h")
        except OSError:
            pass
    # 13 Nov (TB: 4,352 heavy-fuel dirs of finished checks held ~10 GB, /data at 99%): st/heavy/<TAG...> (heavyfuel.py's per-game fuel
    # histograms, read only by the running check) idle 2 h and not in use
    for d in glob.glob("/data/zw4424/st/heavy/*"):
        try:
            if os.path.isdir(d) and NOW - newest(d) > 2 * 3600 and not in_use(d):
                drop(d, "heavy-fuel histograms of a finished check, idle 2 h")
        except OSError:
            pass
    # 13 Nov (TB: 11 dead draftstock lineup work dirs held 19.7 GB, /data at 98%): draftstock/work/lu_<key>_<pid> whose pid is gone, idle 2 h
    for d in glob.glob("/data/zw4424/st/draftstock/work/lu_*"):
        try:
            pid = d.rsplit("_", 1)[-1]
            if not (pid.isdigit() and os.path.exists(f"/proc/{pid}")) and NOW - newest(d) > 2 * 3600:
                drop(d, "draftstock lineups work dir of a finished run, idle 2 h")
        except OSError:
            pass
    # 13 Nov (TB, owner: "make sure our data is cleaned regularly"): cxeident run dirs (cxe/ident/*, a check's identity games, read once by
    # the check) idle 3 h, and inforead / gate panel dirs that the [0-9]* and tc* globs above miss (panel/ir*, panel/sp*, panel/fp*) idle 24 h
    for d in glob.glob("/data/zw4424/st/cxe/ident/*"):
        try:
            if NOW - newest(d) > 3 * 3600 and not in_use(d):
                drop(d, "cxeident run dir, idle 3 h")
        except OSError:
            pass
    for d in glob.glob("/data/zw4424/st/panel/ir*") + glob.glob("/data/zw4424/st/panel/sp*") + glob.glob("/data/zw4424/st/panel/fp*"):
        try:
            if os.path.isdir(d) and NOW - newest(d) > 24 * 3600 and not in_use(d):
                drop(d, "inforead / gate panel dir, idle 24 h")
        except OSError:
            pass
    # 13 Nov (TB: home at 11,090 MB, over condab's 11,000 MB slow-down; 45 orphan spot dirs held 394 MB): cxecondab's CLI spot-check dirs
    # (condor-runs/cxespot/spot-*/PID_MS) are removed at exit, but a killed batch leaves them: drop those untouched 6 h whose PIDs are all gone
    for d in glob.glob("/homes/zw4424/condor-runs/cxespot/spot-*"):
        try:
            pids = [x.split("_")[0] for x in os.listdir(d)]
            if NOW - newest(d) > 6 * 3600 and not any(p.isdigit() and os.path.exists(f"/proc/{p}") for p in pids):
                drop(d, "orphan CLI spot-check dir (its batch is gone), untouched 6 h")
        except OSError:
            pass
    # 12 Nov (TB): ws/* only ever saw ws/bots (one dir, always fresh), so its ~5,600 build dirs (17 GB) were never pruned: walk ws/bots/*
    for d in glob.glob("/data/zw4424/mergecheck/builds/*") + glob.glob("/data/zw4424/mergecheck/ws/bots/*"):
        try:
            try:  # 12 Nov ~23:5xZ (Builder: /data 99%; mergecheck builds+ws held 28 GB at tonight's arm rate): 3 h while /data < 60 GB free
                lim_m = 3 if os.statvfs("/data").f_bavail * os.statvfs("/data").f_frsize < 60e9 else 24
            except OSError:
                lim_m = 24
            if NOW - newest(d) > lim_m * 3600 and not in_use(d):
                drop(d, f"mergecheck build cache, untouched {lim_m} h")
        except OSError:
            pass


def step_tools():
    for t in ("closedprune.py", "idleprune.py", "probeprune.py"):
        r = subprocess.run(["python3", "-I", os.path.join(REPO, "tools/lab", t)] + (["--apply"] if APPLY else []),
                           capture_output=True, text=True, timeout=3600)
        lines.append(f"{t}: " + ((r.stdout + r.stderr).strip().splitlines() or ["(no output)"])[-1][:300])


def main():
    t0 = time.time()
    for st in (step_readmany, step_info, step_loopprof, step_stage, step_sharedpanel, step_idcache, step_smoke, step_probe, step_est, step_cxecache, step_buildcaches, step_archive, step_dswork, step_tools):
        t1 = time.time()
        try:
            st()
        except Exception as e:  # noqa: BLE001  one step failing must not stop the rest
            lines.append(f"!! {st.__name__}: {e}")
        if APPLY:
            with open(LOG, "a") as f:
                f.write(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {st.__name__} done in {time.time() - t1:.0f} s; so far {tot['n']} items, {tot['b'] / 1e9:.2f} GB\n")
    head = (f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} autoclean {'APPLY' if APPLY else 'DRY'}: "
            f"{tot['n']} items, {tot['b'] / 1e9:.2f} GB, {time.time() - t0:.0f} s")
    if APPLY:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(head + "\n" + "".join("  " + x + "\n" for x in lines if not x.startswith("rm ")) +
                    "".join("  " + x + "\n" for x in lines if x.startswith("rm "))[:20000])
        open(os.path.join(os.path.dirname(LOG), "finished"), "w").write(head + "\n")  # the hook's check: this run got to the end
    print(head)
    for x in lines:
        print("  " + x)


if __name__ == "__main__":
    import fcntl  # 11 Nov (TB): the daemon loop and a hook call ran two --apply passes at once, ~75% CPU each for minutes: one at a time
    _lk = open("/data/zw4424/st/autoclean/.run.lock", "a")
    try:
        fcntl.flock(_lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("autoclean: another pass is running; skipped")
        sys.exit(0)
    main()
