#!/usr/bin/env python3
"""Keep the home inode quota under condab's 57,000 preflight overnight, using only the owner-approved cleanup rules.

usage: python3 -I tools/lab/quotaguard.py --once | --loop [--every 1200]   (DRY=1: report only, remove nothing)
Protection (30 Oct 22:45): bots named by pending work (live jobs, batches with queued/claimed pilot items, part files < 2 h,
running processes), the first 8 CLAUDE.md names, spar bots and fixtures; copies untouched 30 min (QG_AGE 0.5).
Acts only when home files (quota -s) > HIGH (40,000; 52,000 before 30 Oct 21:45); removes until < LOW (35,000), in this order, cheapest first:
  1. condor-work/proj400/bots/NAME copies that condab regenerates on demand: the original /data/zw4424/st/new/bots/NAME
     exists, nothing in the copy changed in the last QG_AGE h (default 2; 6 before 30 Oct 18:20), its src is writable (read-only copies are protected), and
     NAME is not protected (CLAUDE.md's live chain, nova_spar_*, the selftest fixtures) or named by an active Condor job
     or a condor-runs part file of the last 24 h. Oldest first. Under condab's proj400/.sync.lock.
  2. condor-work/proj400/maps/*.map26a byte-identical to /data/zw4424/work301/maps (condab re-copies them), untouched (QG_AGE)
     for 6 h and not named by an active job.
  3. /homes/zw4424/condor-runs entries older than 24 h that no queued Condor job uses: each is tarred to
     /data/zw4424/condor_runs_archive/ and verified (entry count) before it is removed.
Every pass, quota or not: condor-work/buildcache capped at QG_BC_MB (800 MB; 400 when home space > QG_MB_HIGH 9,300 MB),
least recently used first, and tars unused for 2 days (owner OK 30 Oct; condab_node.sh touches a tar when it
unpacks it). Hourly: replay.py's decode cache (/data/zw4424/rdec_cache) entries not read for 2 days. Never touches /data/zw4424 originals, bots/, reports or anything else. Log: /data/zw4424/quotaguard/log.
"""
import collections
import glob
import fcntl
import filecmp
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
import keeplist  # noqa: E402  8 Nov: kept paths (condor-work/keep_paths.txt) are never deleted
keeplist.guard(os, shutil)

HOME = "/homes/zw4424"
PROJ = HOME + "/condor-work/proj400"
RUNS = HOME + "/condor-runs"
ORIG = "/data/zw4424/st/new/bots"
WMAPS = "/data/zw4424/work301/maps"
ARCH = "/data/zw4424/condor_runs_archive"
LOGD = "/data/zw4424/quotaguard"
HIGH, LOW = int(os.environ.get("QG_HIGH", 40000)), int(os.environ.get("QG_LOW", 35000))  # owner 30 Oct ~21:45: keep deleting what is not needed (was 52k / 48k)
AGE = float(os.environ.get("QG_AGE", 0.5)) * 3600  # 30 Oct 22:45: 2 -> 0.5 h; in_use() now protects every bot pending work names  # untouched this long (h) before a proj400 copy / map may go (30 Oct: 6 -> 2 h; variant farms make ~54-file copies by the hundred, and bots named by a live batch's part files stay protected)
DRY = os.environ.get("DRY") == "1"
FIXTURES = {"nova_b57_train3", "nova_b68_farmemb", "nova_b73_capearly", "nova_b82_nochase", "nova_b85_pocket", "nova_b89_merge"}


def log(msg):
    os.makedirs(LOGD, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + (" [DRY] " if DRY else " ") + msg
    with open(os.path.join(LOGD, "log"), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def files_used():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import homequota  # 1 Nov ~22:40: the HOME server quota line (quota -s lists other mounted servers too)
    q = homequota.home_quota()
    if q:
        return q["files"]
    out = subprocess.run(["quota", "-s"], capture_output=True, text=True).stdout
    nums = [ln.split() for ln in out.splitlines() if re.match(r"^\s*\d", ln)]
    if not nums:
        return None
    # 1 Nov 22:14: over a limit quota marks the used value with '*' ("60999*") and adds a grace field ("6days") after it;
    # take the 4th value that is a count (space used, quota, limit, then files used), whatever grace fields sit between
    vals = [t.rstrip("*") for t in nums[-1] if re.fullmatch(r"\d+[KMGT]?\*?", t)]
    try:
        return int(vals[3])
    except (IndexError, ValueError):
        return None


def protected():
    names = set(FIXTURES)
    try:
        chain = list(dict.fromkeys(re.findall(r"nova_[A-Za-z0-9_]+", open(HOME + "/cambc/CLAUDE.md").read())))
        names |= set(chain[:KEEP_CHAIN])  # 30 Oct 22:45: the live bot and its recent bases (CLAUDE.md names newest first), not all 55
    except OSError:
        pass
    return names


MAP_AGE = float(os.environ.get("QG_MAP_AGE", 2)) * 3600  # 1 Nov 01:40: 6 -> 2 h (map studies copy ~1.5k maps an hour; 6 h held 5.5k, home stuck at 50k; maps named by pending work stay protected); maps: 1 file each and re-copied by every batch (30 Oct 23:40: 0.5 h churned 800 maps)
INFRA = {"toolcache", "botpacks", "otfpacks", "stage", "cxe", "pilotq", "freshpool", "stratfarm", "readmany", "hostpilots"}  # caches and queues, never "finished runs"
KEEP_CHAIN = int(os.environ.get("QG_KEEP_CHAIN", 8))  # first CLAUDE.md bot names protected
RUN_AGE = float(os.environ.get("QG_RUN_AGE", 24)) * 3600  # condor-runs entries untouched this long (h) are archived + removed
RUN_AGE_TIGHT = float(os.environ.get("QG_RUN_AGE_TIGHT", 4)) * 3600  # ... over the 50k home alarm (4 Nov: 115 batch dirs
# of ~470 files each, all under 24 h old, held home at 51k with the 24 h rule freeing nothing)
RUN_AGE_FULL = float(os.environ.get("QG_RUN_AGE_FULL", 1)) * 3600  # ... over 55k (5 Nov: 301 finished dirs under 4 h old stopped 84 batches at the home guard)
PART_AGE = float(os.environ.get("QG_PART_AGE", 2)) * 3600  # part files this recent protect their bots (was 24 h)


def run_age(used):
    """How long a condor-runs entry must be untouched before it is archived, given home files in use."""
    return RUN_AGE_FULL if used > 55000 else RUN_AGE_TIGHT if used > 50000 else RUN_AGE


def condab_args():
    """Every argument of every running condab.py: a batch's name is among them, so its cq_NAME_K dirs are never idle."""
    out = set()
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                a = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace").split("\0")
            except OSError:
                continue
            if any(x.endswith("condab.py") for x in a):
                out |= {x for x in a if x and "/" not in x and not x.startswith("-")}
    return out


def held_by_condab(entry, args):
    return entry.startswith("cq_") and any(entry == "cq_" + t or entry.startswith("cq_" + t + "_") for t in args)


def pending_runs():
    """condor-runs dirs of batches with pilot items still queued or claimed (item batch cq-NAME-K-HASH -> cq_NAME_K)."""
    out = set()
    for sub in ("queue", "claimed"):
        try:
            names = os.listdir(os.path.join(RUNS, "pilotq", sub))
        except OSError:
            continue
        for n in names:
            m = re.match(r"^\d+_\d+_(cq-.+)-[0-9a-f]+_\d+", n)
            if m:
                out.add(os.path.join(RUNS, m.group(1).replace("-", "_")))
    return out


def proc_names():
    """nova_ names on the command line of any of this user's processes (a batch being planned, synced or collected)."""
    names = set()
    me = os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat("/proc/" + pid).st_uid != me:
                continue
            names |= set(re.findall(r"nova_[A-Za-z0-9_]+", open("/proc/%s/cmdline" % pid, "rb").read().decode(errors="replace")))
        except OSError:
            continue
    return names


def in_use():
    """Bot and map names that pending work needs, and the active run dirs. 30 Oct 22:45 (owner: keep deleting what is not
    needed; home 53.6k): a run dir's part files protect their bots while a Condor job runs there, while the batch still has
    pilot items queued or claimed, or for PART_AGE (2 h; was 24 h) after they were written; names on any running process's
    command line are protected too."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import condorroute  # 7 Nov: with no schedd here condor_q failed quietly and no direct Condor job's run dir counted as active
    try:
        iwd = subprocess.run(["condor_q", "-af", "Iwd"], capture_output=True, text=True, env=condorroute.env(), timeout=60).stdout.split()
    except subprocess.TimeoutExpired:  # the schedd is on another machine now: it must not stop the guard
        iwd = []
    active = {re.sub(r"/run$", "", d) for d in iwd} | pending_runs()
    text = []
    now = time.time()
    for d in [RUNS + "/" + x for x in os.listdir(RUNS)] if os.path.isdir(RUNS) else []:
        try:  # 1 Nov: a batch dir or part file removed by its own condab mid-scan aborted the whole pass (4 passes lost)
            names = os.listdir(d) if os.path.isdir(d) else []
        except OSError:
            continue
        for f in names:
            p = os.path.join(d, f)
            try:
                if f.startswith("part_") and os.path.isfile(p) and (d in active or now - os.path.getmtime(p) < PART_AGE):
                    text.append(open(p).read())
            except OSError:
                pass
    blob = "\n".join(text)
    return set(re.findall(r"nova_[A-Za-z0-9_]+", blob)) | proc_names(), blob, active


def mtime(p):
    """getmtime, or now for an entry that vanished (a racing condab removed it): never the oldest, so never pruned."""
    try:
        return os.path.getmtime(p)
    except OSError:
        return time.time()


def newest(d):
    t = mtime(d)
    for r, ds, fs in os.walk(d):
        for f in fs:
            try:
                t = max(t, os.lstat(os.path.join(r, f)).st_mtime)
            except OSError:
                pass
    return t


def count(d):
    return sum(len(fs) + len(ds) for _, ds, fs in os.walk(d)) + 1


def main():
    a = sys.argv[1:]
    loop, every = "--loop" in a, int(a[a.index("--every") + 1]) if "--every" in a else 1200
    if not loop and "--once" not in a:
        print(__doc__)
        sys.exit(1)
    while True:
        for _try in range(4):  # 1 Nov: a run dir or tar removed by condab mid-pass raised FileNotFoundError and aborted the whole pass (home stuck ~56k); retry the pass
            try:
                step()
                break
            except FileNotFoundError as e:
                log(f"error: FileNotFoundError: {e} (race with a concurrent cleanup; retrying the pass)")
            except Exception as e:  # noqa: BLE001  a failed pass must not kill the overnight loop
                log(f"error: {type(e).__name__}: {e}")
                break
        if not loop:
            return
        time.sleep(every)


BUILDCACHE = HOME + "/condor-work/buildcache"


BC_MAX_MB = int(os.environ.get("QG_BC_MB", 800))  # the shared build cache's size cap (least recently used tars go first)
MB_HIGH = int(os.environ.get("QG_MB_HIGH", 9300))  # home MB above this: the cache shrinks to BC_MAX_MB / 2 (condab refuses at 10,000)


def mb_used():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import homequota
    q = homequota.home_quota()
    if q:
        return q["mb"]
    out = subprocess.run(["quota", "-s"], capture_output=True, text=True).stdout
    nums = [ln.split() for ln in out.splitlines() if re.match(r"^\s*\d", ln)]
    try:
        return int(nums[-1][0].rstrip("M*")) if nums else None
    except ValueError:
        return None


def prune_buildcache():
    """Every pass, quota or not (owner OK, 30 Oct): condab_node.sh's shared build tars unused for 2 days (a node touches a tar
    when it unpacks it; the next node or condab prebuild rebuilds one on demand), and temp tars left over an hour."""
    if not os.path.isdir(BUILDCACHE):
        return
    now, n = time.time(), 0
    for f in os.listdir(BUILDCACHE):
        p = os.path.join(BUILDCACHE, f)
        try:  # 1 Nov: a build's temp file renamed mid-scan aborted the pass
            age = now - os.path.getmtime(p)
            if (f.endswith(".tar") and not f.startswith(".") and age > 2 * 86400) or (f.startswith(".") and f.endswith(".tmp") and age > 3600):
                if not DRY:
                    os.remove(p)
                n += 1
        except OSError:
            continue
    # size cap, least recently used first (a node touches a tar when it unpacks it); tighter when the home's MB are high
    mb = mb_used()
    cap = BC_MAX_MB // 2 if mb is not None and mb > MB_HIGH else BC_MAX_MB
    tars = []
    for f in os.listdir(BUILDCACHE):
        if f.endswith(".tar") and not f.startswith("."):
            try:
                st = os.stat(os.path.join(BUILDCACHE, f))
            except OSError:
                continue
            tars.append((st.st_mtime, st.st_size, f))
    tars.sort()
    size = sum(t[1] for t in tars)
    for _, sz, f in tars:
        if size <= cap * 1024 * 1024:
            break
        if not DRY:
            try:
                os.remove(os.path.join(BUILDCACHE, f))
            except OSError:
                pass
        size -= sz
        n += 1
    if n:
        log(f"build cache: removed {n} tar(s) (unused 2 days, stale temp, or over the {cap} MB cap"
            + (f"; home {mb} MB > {MB_HIGH}" if mb is not None and mb > MB_HIGH else "") + f"); now {size // 2 ** 20} MB")
    if mb is not None and mb > MB_HIGH:
        log(f"!! home space {mb} MB > {MB_HIGH} MB (condab refuses batches at 10,000 MB)")


RDEC = "/data/zw4424/rdec_cache"  # replay.py's content-addressed decode cache: any entry is rebuilt in 1-6 s when needed
RDEC_DAYS = float(os.environ.get("QG_RDEC_DAYS", 0.5))  # 4 Nov: 15 GB inside 2 days; a native decode takes ~1 s (was 2 days)
_last_rdec = [0.0]


def prune_rdec():
    """Hourly (owner 30 Oct 22:50: keep deleting what is not needed): decode-cache entries not read for RDEC_DAYS days
    (/data is mounted relatime, so atime is good to a day) and temp files older than a day."""
    if time.time() - _last_rdec[0] < 3600 or not os.path.isdir(RDEC):
        return
    _last_rdec[0] = time.time()
    now, n, mb = time.time(), 0, 0.0
    for e in os.scandir(RDEC):
        try:
            st = e.stat()
            if e.is_file() and ((e.name.endswith(".json.gz") and now - st.st_atime > RDEC_DAYS * 86400)
                                or (e.name.startswith(".") and now - st.st_mtime > 86400)):
                if not DRY:
                    os.remove(e.path)
                n, mb = n + 1, mb + st.st_size / 1e6
        except OSError:
            pass
    if n:
        log(f"decode cache: removed {n} entries not read for {RDEC_DAYS} days ({mb:.0f} MB)")


CXE = "/data/zw4424/st/cxe"
# cxe scratch (owner 4 Nov ~22:45Z: clear unused files automatically): entry -> hours with no file touched. xmaps = unpacked map
# packs (rebuilt from their .tar); ab/verify/ident/work = run dirs whose results are already printed or logged; dbg = debug
# libraries (rebuilt by dbgso in minutes); actlog/fork = record and rollout outputs people read by hand.
CXE_AGES = {"xmaps": 6, "verify": 24, "ident": 24, "work": 24, "ab": 48, "dbg": 48, "actlog": 48, "fork": 48, "closeread": 48}
_last_cxe = [0.0]


def prune_cxe():
    """Hourly: cxe scratch entries untouched for CXE_AGES hours (newest file inside, so a running batch's dir is never old)."""
    if time.time() - _last_cxe[0] < 3600:
        return
    _last_cxe[0] = time.time()
    now, n, mb = time.time(), 0, 0.0
    for sub, h in CXE_AGES.items():
        root = os.path.join(CXE, sub)
        for e in (os.scandir(root) if os.path.isdir(root) else []):
            try:
                if e.name.endswith(".tmp") or now - newest(e.path) <= h * 3600:
                    continue
                sz = sum(os.lstat(os.path.join(r, f)).st_size for r, _, fs in os.walk(e.path) for f in fs) if e.is_dir() else e.stat().st_size
                if not DRY:
                    shutil.rmtree(e.path) if e.is_dir() and not e.is_symlink() else os.remove(e.path)
                n, mb = n + 1, mb + sz / 1e6
            except OSError:
                pass
    if n:
        log(f"cxe scratch: removed {n} entries ({mb:.0f} MB)")


UBQ = HOME + "/condor-work/ubq"   # ubaudit's remote job dirs (removed by the audit itself unless it was killed)
CQB = "/data/zw4424/cqb"          # cqbatch run dirs (removed on success; kept on failure for the node logs)


def prune_jobdirs():
    """Every pass: ubq dirs untouched for 2 h (their audit is gone) and failed cqbatch dirs untouched for 2 days."""
    now = time.time()
    for root, age in ((UBQ, 7200), (CQB, 2 * 86400)):
        for e in (os.scandir(root) if os.path.isdir(root) else []):
            try:
                if e.is_dir() and now - newest(e.path) > age:
                    if not DRY:
                        shutil.rmtree(e.path)
                    log(f"removed stale job dir {e.path}")
            except OSError:
                pass
    # 11 Nov (Builder: home 53.6k files blocked cxefarm staging at 54k): stratmaps run dirs whose stratmaps died (it removes its own
    # on exit) and pilot cancel markers (only matter while a stage can still be claimed: callers wait <= 2 h), both after 3 h.
    sf = HOME + "/condor-runs/stratfarm"
    for e in (os.scandir(sf) if os.path.isdir(sf) else []):
        try:
            pid = e.name.split("_")[0]
            if e.is_dir() and pid.isdigit() and not os.path.exists(f"/proc/{pid}") and now - newest(e.path) > 3 * 3600:
                if not DRY:
                    shutil.rmtree(e.path)
                log(f"removed orphan stratmaps dir {e.path}")
        except OSError:
            pass
    n = 0
    cq = HOME + "/condor-runs/pilotq/cancel"
    for e in (os.scandir(cq) if os.path.isdir(cq) else []):
        try:
            if e.is_file() and now - e.stat().st_mtime > 2 * 3600:  # 12 Nov: 3 h -> 2 h (callers wait <= 2 h; home sat at the 54k staging gate)
                if not DRY:
                    os.remove(e.path)
                n += 1
        except OSError:
            pass
    if n:
        log(f"removed {n} pilot cancel markers older than 3 h")


def kill_root_finds():
    """12 Nov (TB: 7 agent `find /` searches (Claude Code runs find as bfs) crawled the whole filesystem incl. NFS for up to 7 h; load 64 ->
    46 when stopped): our own find/bfs processes searching from / older than 15 min are stopped (the search only; never its parent)."""
    me = os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != me:
                continue
            args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            a = [x.decode(errors="replace") for x in args if x]
            if not a or os.path.basename(a[0]) not in ("bfs", "find") or "/" not in a[1:]:
                continue
            with open(f"/proc/{pid}/stat") as f:
                st = f.read().split()
            age = os.times().elapsed - int(st[21]) / os.sysconf("SC_CLK_TCK")
            if age > 900:
                if not DRY:
                    os.kill(int(pid), 15)
                log(f"stopped a {age / 60:.0f}-min filesystem-wide search: pid {pid} {' '.join(a)[:120]}")
        except (OSError, ValueError, IndexError):
            continue


SWEEP_PAUSE = "/data/zw4424/st/bq/sweepd.pause"
SWEEP_MINE = "/data/zw4424/quotaguard/sweepd.paused_by_quotaguard"
SWEEP_HI, SWEEP_LO = int(os.environ.get("QG_SWEEP_HI", 50000)), int(os.environ.get("QG_SWEEP_LO", 44000))


def sweep_cap(used):
    """30 Oct 23:40 (Builder: cap sweeps first, ship legs and KEEPs must never hit condab's 57k): above SWEEP_HI home files,
    pause sweepd (its running batches finish; no new ones start); below SWEEP_LO, lift the pause, only if this set it."""
    if used > SWEEP_HI and not os.path.exists(SWEEP_PAUSE):
        if not DRY:
            open(SWEEP_PAUSE, "w").write(f"quotaguard: home files {used} > {SWEEP_HI}\n")
            open(SWEEP_MINE, "w").write(f"{used}\n")
        log(f"files {used} > {SWEEP_HI}: sweepd paused ({SWEEP_PAUSE})")
    elif used < SWEEP_LO and os.path.exists(SWEEP_MINE):
        if not DRY:
            for f in (SWEEP_PAUSE, SWEEP_MINE):
                try:
                    os.remove(f)
                except OSError:
                    pass
        log(f"files {used} < {SWEEP_LO}: sweepd resumed (the pause was quotaguard's)")


ABL = "/data/zw4424/abl"  # local A/B and collected Condor KEEP runs
AUD = "/data/zw4424/st/audit"   # ubaudit: instrumented builds (ubproj/bots/au_*) and run dirs (runs/*)
SESS = "/tmp/claude-16910/-homes-zw4424-cambc"  # Claude sessions' scratch dirs (this machine's /tmp is RAM)
_last_hourly = [0.0]


def _in_use_paths():
    out = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            out.add(os.readlink(f"/proc/{pid}/cwd"))
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    out.add(os.readlink(f"/proc/{pid}/fd/{fd}"))
                except OSError:
                    pass
        except OSError:
            continue
    return out


def abl_refs():
    """abl run names cited in the reports, docs, skills, memory or CLAUDE.md (their run dirs are never slimmed)."""
    refs = set()
    for root in (HOME + "/condor-work/reports", HOME + "/cambc/docs", HOME + "/cambc/.claude/skills",
                 HOME + "/.claude/projects/-homes-zw4424-cambc/memory"):
        for r, _, fs in os.walk(root):
            for f in fs:
                if f.endswith((".md", ".txt", ".tsv", ".log")):
                    try:
                        refs |= set(re.findall(r"abl/([A-Za-z0-9_.-]+)", open(os.path.join(r, f), errors="replace").read()))
                    except OSError:
                        pass
    try:
        refs |= set(re.findall(r"abl/([A-Za-z0-9_.-]+)", open(HOME + "/cambc/CLAUDE.md").read()))
    except OSError:
        pass
    return refs


DATA = "/data"
# 5 Nov (TB2): /data holds root's cachefilesd cache (/data/.fscache, ~215 GB, keeps free space at 3-10%), so % used reads 90-97% whatever we store; guard on absolute free space. The tiers are a 'pressure %' made from free space: tier 1 below QG_FREE1 GB free, tier 2 below QG_FREE2.
QG_FREE1 = float(os.environ.get("QG_FREE1", 80))  # free GB: statistics of abl runs idle 24 h go (hourly)
QG_FREE2 = float(os.environ.get("QG_FREE2", 50))  # free GB: statistics idle 12 h and replays idle 24 h go (each pass)
DATA_HI1, DATA_HI2 = 75.0, 85.0  # pressure % at the two tiers (data_pct() maps QG_FREE1 -> 75, QG_FREE2 -> 85)
_last_space = [0.0]


def data_pct():
    """pressure %: 75 at QG_FREE1 GB free, 85 at QG_FREE2, linear between and beyond (100 at 0 GB free under the
    QG_FREE2 slope); callers compare with DATA_HI1/DATA_HI2 as before"""
    free = shutil.disk_usage(DATA).free / 1e9
    if free >= QG_FREE2:
        return 75.0 + 10.0 * (QG_FREE1 - free) / max(1e-9, QG_FREE1 - QG_FREE2)
    return 85.0 + 15.0 * (QG_FREE2 - free) / max(1e-9, QG_FREE2)


def prune_scratch():
    """3 Nov (owner: /var, quota, /data; home 50k files, /data +9 GB/h): pure scratch of finished work, each pass. (a) condor-runs/stage/rm_* whose readmany pid is
    gone, idle 1 h (home files). (b) readmany runs on /data whose pid is gone, idle 1 h: their in_*.tar are copies of replays kept elsewhere. (c) at /data >= DATA_HI2:
    st/info/TAG/rep of a finished read (.done) 18 h after it finished; result.txt, mech and fight outputs stay, otf.json can rebuild the maps."""
    now, n = time.time(), collections.Counter()
    gone = lambda name: not os.path.exists("/proc/" + name.rsplit("_", 1)[-1])  # noqa: E731
    for d in glob.glob(RUNS + "/stage/rm_*"):
        if gone(d) and now - newest(d) > 3600:
            n["stage"] += count(d)
            if not DRY:
                shutil.rmtree(d, ignore_errors=True)
    # 4 Nov: cqbatch's pilot stage dirs (<stamp>_<pid>) of finished batches and mergecheck's build stages (mcb_*, minutes long),
    # idle 6 h: 556 MB of home space had piled up since 2 Nov
    for d in glob.glob(RUNS + "/stage/20*_*") + glob.glob(RUNS + "/stage/mcb_*"):
        # 13 Nov (TB, home at 11,580 of 11,719 MB): mergecheck's pilot build waits at most its `wait` and rmtree's its mcb_ dir in a finally,
        # so an mcb_ dir idle 2 h belongs to a killed mergecheck (was 6 h; 149 of them, 280 MB)
        if now - newest(d) > (2 if os.path.basename(d).startswith("mcb_") else 6) * 3600 and (os.path.basename(d).startswith("mcb_") or gone(d)):
            n["stage"] += count(d)
            if not DRY:
                shutil.rmtree(d, ignore_errors=True)
    for d in glob.glob("/data/zw4424/readmany/runs/*"):
        if gone(d) and now - mtime(d) > 3600:
            for f in glob.glob(d + "/in_*.tar") + glob.glob(d + "/noinput.tar"):
                n["rm_bytes"] += os.path.getsize(f)
                if not DRY:
                    os.remove(f)
    if data_pct() >= DATA_HI2:
        for r in glob.glob("/data/zw4424/st/info/*/rep"):
            done = os.path.join(os.path.dirname(r), ".done")
            if os.path.exists(done) and now - mtime(done) > 18 * 3600:
                n["info_reps"] += 1
                if not DRY:
                    shutil.rmtree(r, ignore_errors=True)
    if n:
        log(f"scratch: {n['stage']} stage files, {n['rm_bytes'] // 10 ** 6} MB readmany inputs, {n['info_reps']} expired info replay dirs")



SHARED_GRACE = int(os.environ.get("QG_SHARED_GRACE", 120))  # 11 Nov 02:4xZ: fresh-set tars are used once; 6 h kept 1.1 GB. A file no live jobs.sh names goes after 15 min


def prune_stage2():
    """11 Nov (TB 6ad907; home hit 10,272 MB, condab refuses at 10,000, and the passes above freed ~0): each pass, (a) cxefarm/cxecondab
    stage dirs (cf_PID_*, cc_PID_*) whose caller pid is gone, idle 30 min; (b) cxe/cc-* compiler bundles other than the newest that no
    stage jobs.sh names, idle 1 h (200 MB each; pilotcc uses the newest); (c) pilotq cancel markers older than 6 h (they live 6 h);
    (d) stage/shared (cxefarm's content-addressed maps tars and .so.gz) untouched SHARED_GRACE (15 min) and named in no stage/*/jobs.sh, so a queued or
    running batch always keeps its files."""
    now, n, mb = time.time(), collections.Counter(), 0.0
    stage = RUNS + "/stage"
    for d in glob.glob(stage + "/cf_*_*") + glob.glob(stage + "/cc_*_*"):
        pid = os.path.basename(d).split("_")[1]
        try:
            if pid.isdigit() and not os.path.exists("/proc/" + pid) and now - newest(d) > 1800:
                mb += sum(os.lstat(os.path.join(r, x)).st_size for r, _, fs in os.walk(d) for x in fs) / 1e6
                n["dead stage"] += 1
                if not DRY:
                    shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
    refs = ""
    for j in glob.glob(stage + "/*/jobs.sh"):
        try:
            refs += open(j, errors="replace").read()
        except OSError:
            pass
    ccs = sorted((d for d in glob.glob(RUNS + "/cxe/cc-*") if not d.endswith(".tmp") and os.path.isdir(d)), key=mtime)
    for d in ccs[:-1]:
        if os.path.basename(d) not in refs and now - newest(d) > 3600:
            mb += sum(os.lstat(os.path.join(r, x)).st_size for r, _, fs in os.walk(d) for x in fs) / 1e6
            n["old cc"] += 1
            if not DRY:
                shutil.rmtree(d, ignore_errors=True)
    for e in (os.scandir(RUNS + "/pilotq/cancel") if os.path.isdir(RUNS + "/pilotq/cancel") else []):
        try:
            if e.is_file() and now - e.stat().st_mtime > 6 * 3600:
                n["cancel"] += 1
                if not DRY:
                    os.remove(e.path)
        except OSError:
            pass
    for e in (os.scandir(stage + "/shared") if os.path.isdir(stage + "/shared") else []):
        try:
            if now - e.stat().st_mtime > SHARED_GRACE and e.name.split(".tmp")[0] not in refs:
                mb += e.stat().st_size / 1e6
                n["shared"] += 1
                if not DRY:
                    os.remove(e.path)
        except OSError:
            pass
    if n:
        log(f"stage2: {dict(n)} removed ({mb:.0f} MB)")


def prune_space():
    """/data space guard (owner 31 Oct 23:20 "consistently remove stale files so we don't run out of storage"; /data was 80%,
    abl growing ~50 GB a day): above DATA_HI1, the per-game statistics JSONs (st/, ~750 KB a game, the bulk) and job dirs
    (run/) of abl runs idle 24 h go, hourly; above DATA_HI2, st/ and run/ idle 12 h and replays (rep/, side/) idle 24 h go,
    every pass. games.jsonl, manifest, cli.txt and summaries always stay (results stay readable and reusable); runs cited
    in reports, docs, skills, memory or CLAUDE.md are never touched. A run's age: its newest dir / games.jsonl mtime."""
    pct = data_pct()
    if pct < DATA_HI1 or (pct < DATA_HI2 and time.time() - _last_space[0] < 3600):
        return
    _last_space[0] = time.time()
    hi = pct >= DATA_HI2
    lim = {"st": 12 * 3600 if hi else 24 * 3600, "run": 12 * 3600 if hi else 24 * 3600}
    if hi:
        lim.update(rep=24 * 3600, side=24 * 3600)
    refs, now, n = abl_refs(), time.time(), collections.Counter()
    for d in (os.scandir(ABL) if os.path.isdir(ABL) else []):
        if not d.is_dir() or d.name in refs:
            continue
        try:
            age = now - max(os.path.getmtime(p) for p in [d.path] + [os.path.join(d.path, x) for x in ("games.jsonl", "st", "rep")]
                            if os.path.exists(p))
        except (OSError, ValueError):
            continue
        for sub, a in lim.items():
            p = os.path.join(d.path, sub)
            if age > a and os.path.isdir(p):
                if not DRY:
                    shutil.rmtree(p, ignore_errors=True)
                n[sub] += 1
    if n:
        log(f"/data pressure {pct:.0f} ({shutil.disk_usage(DATA).free / 1e9:.0f} GB free; tier at {DATA_HI2 if hi else DATA_HI1:.0f}): removed " + ", ".join(f"{v} {k}/ dirs" for k, v in n.items())
            + f" from idle abl runs; now {data_pct():.0f}%")


def prune_hourly():
    """Hourly (owner 31 Oct 00:45 "delete files"): instrumented ubaudit builds idle 6 h lose .cambc + .ubbuilt (a local
    fallback audit rebuilds them; audits run on Condor), audit runs idle 6 h lose rep/ st/ side/ (sites live in ubcache;
    report.txt, ubx.txt and logs stay), and Claude session scratch dirs idle 24 h that no live process uses go."""
    if time.time() - _last_hourly[0] < 3600:
        return
    _last_hourly[0] = time.time()
    try:  # 11 Nov (Coordinator): critgame's rolling 50-version supersede also runs while critgame's own daemon is off
        r = subprocess.run([sys.executable, "-I", HOME + "/cambc/tools/lab/critgame.py", "supersede"], capture_output=True, text=True, timeout=300)
        if r.stdout.strip() and not r.stdout.startswith("supersede: 0 "):
            log(r.stdout.strip()[:200])
    except Exception:  # noqa: BLE001
        pass
    now, n = time.time(), collections.Counter()
    for d in (os.scandir(AUD + "/ubproj/bots") if os.path.isdir(AUD + "/ubproj/bots") else []):
        if d.name.startswith("au_") and os.path.isdir(d.path + "/.cambc") and now - newest(d.path) > 6 * 3600:
            if not DRY:
                shutil.rmtree(d.path + "/.cambc", ignore_errors=True)
                try:
                    os.remove(d.path + "/.ubbuilt")
                except OSError:
                    pass
            n["audit builds"] += 1
    for d in (os.scandir(AUD + "/runs") if os.path.isdir(AUD + "/runs") else []):
        sub = [d.path + "/" + x for x in ("rep", "st", "side") if os.path.isdir(d.path + "/" + x)]
        if sub and now - newest(d.path) > 6 * 3600:
            if not DRY:
                for x in sub:
                    shutil.rmtree(x, ignore_errors=True)
            n["audit runs"] += 1
    used = None
    for d in (os.scandir(SESS) if os.path.isdir(SESS) else []):
        if not d.is_dir() or now - newest(d.path) < 86400:
            continue
        t = os.path.join(HOME, ".claude/projects/-homes-zw4424-cambc", d.name + ".jsonl")
        if os.path.exists(t) and now - os.path.getmtime(t) < 86400:
            continue
        used = _in_use_paths() if used is None else used
        if any(u == d.path or u.startswith(d.path + "/") for u in used):
            continue
        if not DRY:
            shutil.rmtree(d.path, ignore_errors=True)
        n["session scratch dirs"] += 1
    # abl.sh / condab KEEP run dirs untouched 48 h and named nowhere in the reports, docs, skills, memory or CLAUDE.md:
    # replays, statistics and job dirs go; games.jsonl, manifest, cli.txt and summaries stay (the index reuses results)
    refs = abl_refs()
    for d in (os.scandir(ABL) if os.path.isdir(ABL) else []):
        sub = [d.path + "/" + x for x in ("rep", "st", "run", "side") if os.path.isdir(d.path + "/" + x)]
        if sub and d.name not in refs and now - newest(d.path) > 2 * 86400:
            if not DRY:
                for x in sub:
                    shutil.rmtree(x, ignore_errors=True)
            n["abl runs slimmed"] += 1
    if n:
        log("hourly prune: " + ", ".join(f"{v} {k}" for k, v in n.items()))


BQ_DIR = "/data/zw4424/st/bq"
SHIPPED_STORE = "/data/zw4424/st/shipped_bots"
SHIP_REAL = int(os.environ.get("QG_SHIP_REAL", "4"))


def delink_shipped():
    """10 Nov (Builder: home at 54,188 files held cxefarm's 54k gate; 22 shipped versions v650-v673 were real dirs in bots/, ~216 home files
    each). Shipping makes a bot a real dir (realbot.sh); after SHIP_REAL newer versions it moves to SHIPPED_STORE on /data and bots/NAME becomes
    a link to it: same files, same source hash (checked through the link), so puppet re-plays, rollback and reads keep working. The baseline and
    the newest SHIP_REAL live versions stay real. -> files freed (about)."""
    try:
        names = [ln.split()[1] for ln in open(os.path.join(BQ_DIR, "live.txt")) if len(ln.split()) > 1]
        base = {ln.split()[1] for ln in open(os.path.join(BQ_DIR, "baseline.txt")) if ln.strip() and not ln.startswith("#") and len(ln.split()) > 1}
    except OSError:
        return 0
    keep, freed = set(names[:SHIP_REAL]) | base, 0
    for b in dict.fromkeys(names[SHIP_REAL:]):
        d = os.path.join(HOME, "cambc/bots", b)
        if b in keep or not b.startswith("nova_") or os.path.islink(d) or not os.path.isdir(os.path.join(d, "src")):
            continue
        dst = os.path.join(SHIPPED_STORE, b)
        try:
            if os.path.exists(dst):
                log(f"delink {b}: {dst} exists already; left real")
                continue
            os.makedirs(SHIPPED_STORE, exist_ok=True)
            shutil.copytree(d, dst, symlinks=True)
            if subprocess.run(["diff", "-rq", d, dst], capture_output=True).returncode:
                shutil.rmtree(dst, ignore_errors=True)
                log(f"delink {b}: copy differs; left real")
                continue
            hs = lambda p: subprocess.run([sys.executable, "-I", os.path.join(HOME, "cambc/tools/lab/srchash.py"), p], capture_output=True, text=True).stdout.strip()  # noqa: E731
            h1 = hs(d)
            n = sum(len(fs) + len(ds) for _, ds, fs in os.walk(d)) + 1
            tmp = os.path.join(HOME, "cambc/bots", f".{b}.delink")
            os.rename(d, tmp)
            os.symlink(dst, d)
            if not h1 or hs(d) != h1:
                os.remove(d); os.rename(tmp, d)
                log(f"!! delink {b}: source hash changed through the link; restored the real dir")
                continue
            shutil.rmtree(tmp)
            freed += n
            log(f"delink {b}: real dir -> {dst} ({n} home files)")
        except OSError as e:
            log(f"!! delink {b}: {e}")
    return freed


def step():
    delink_shipped()
    prune_buildcache()
    prune_rdec()
    prune_cxe()
    prune_jobdirs()
    kill_root_finds()
    prune_hourly()
    prune_space()
    prune_scratch()
    prune_stage2()
    u = files_used()
    if u is not None:
        sweep_cap(u)
    used = files_used()
    if used is None:
        log("quota -s unreadable: skipping")
        return
    if used <= HIGH:
        log(f"files {used} <= {HIGH}: nothing to do")
        return
    log(f"files {used} > {HIGH}: cleaning towards {LOW}")
    prot, (busy, blob, active) = protected(), in_use()
    now, freed = time.time(), 0
    # 1. regenerable proj400 bot copies, oldest first, under condab's sync lock
    with open(os.path.join(PROJ, ".sync.lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cands = []
        for b in os.listdir(PROJ + "/bots"):
            d = os.path.join(PROJ, "bots", b)
            if (not b.startswith("nova_") or os.path.islink(d) or not os.path.isdir(d) or b in prot or b in busy
                    or b.startswith("nova_spar_") or not (os.path.isdir(os.path.join(ORIG, b)) or os.path.isdir(os.path.join(HOME, "cambc/bots", b, "src")))
                    or (os.path.isdir(d + "/src") and not os.access(d + "/src", os.W_OK))):
                continue
            t = newest(d)
            if now - t >= AGE:
                cands.append((t, b, d))
        for t, b, d in sorted(cands):
            if used - freed < LOW:
                break
            n = count(d)
            if not DRY:
                shutil.rmtree(d)
            freed += n
            log(f"removed proj400 copy {b} ({n} files; original kept in {ORIG})")
    # 2. regenerable proj400 maps: OFF by default (QG_MAPS=1 enables). 1 Nov 18:42 it raced condab: a batch's sync leaves an
    # identical old map untouched, its job lists did not exist yet, so the map read as unused and was removed between sync and
    # submit; the job that needed gen_s_122 lost all 98 games ("map does not exist", killgate kgb746sf1b). It was also pure
    # churn: 27,103 removals in 2 days, each map re-synced by the next batch.
    # 1 Nov ~20:10: back ON (QG_MAPS=0 turns it off): condab's sync now touches every map it uses, so a map synced for a
    # batch is younger than MAP_AGE until its job lists (which protect it while they run) exist; off, proj400 grew 1.5k files.
    if used - freed >= LOW and os.environ.get("QG_MAPS", "1") == "1":
        for m in sorted(os.listdir(PROJ + "/maps")):
            if used - freed < LOW:
                break
            p, w = os.path.join(PROJ, "maps", m), os.path.join(WMAPS, m)
            if (m.endswith(".map26a") and os.path.isfile(p) and not os.path.islink(p) and os.path.isfile(w)
                    and now - os.path.getmtime(p) >= MAP_AGE and not re.search(r"\b" + re.escape(m[:-7]) + r"\b", blob)
                    and filecmp.cmp(p, w, shallow=False)):
                if not DRY:
                    os.remove(p)
                freed += 1
                log(f"removed proj400 map {m} (identical copy in {WMAPS})")
    # 3. old finished condor-runs entries, archived and verified first
    if used - freed >= LOW and os.path.isdir(RUNS):
        os.makedirs(ARCH, exist_ok=True)
        args = condab_args()
        for e in sorted(os.listdir(RUNS), key=lambda x: mtime(os.path.join(RUNS, x))):
            if used - freed < LOW:
                break
            p = os.path.join(RUNS, e)
            if not os.path.lexists(p):
                continue
            age = now - (newest(p) if os.path.isdir(p) else mtime(p))
            if p in active or os.path.islink(p) or age < run_age(used) or held_by_condab(e, args):
                continue
            if e in INFRA:  # 9 Nov: toolcache was archived every pass (28 x 0.4 GB on /data in 12 h): it is re-created with its old mtime
                continue
            n = count(p) if os.path.isdir(p) else 1
            tgz = os.path.join(ARCH, f"qg_{e}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.tgz")
            if not DRY:
                with tarfile.open(tgz, "w:gz") as tf:
                    tf.add(p, arcname=e)
                with tarfile.open(tgz) as tf:
                    if len(tf.getmembers()) != n:
                        log(f"archive check failed for {e}: kept")
                        continue
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            freed += n
            log(f"archived {e} to {tgz} and removed it ({n} files)")
    log(f"pass done: ~{freed} files freed; quota now {files_used()}")


if __name__ == "__main__":
    main()
