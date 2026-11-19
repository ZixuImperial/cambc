#!/usr/bin/env python3
"""Watchdog for the pipeline: restart dead daemons, raise stall ALARMs, log a health line every 20 min. Runs in unit nova-healthwatch.

usage: sh tools/lab/detach.sh -l /data/zw4424/st/bq/healthwatch.out healthwatch python3 -I tools/lab/healthwatch.py --loop --rating 0
       (DRY=1: log only, restart nothing; --check: print one round of stall checks and exit)
Daemons (found by their exact command line, not a pid file, so a Builder restart is never fought): shipwatch, armq, pilotd, livepipe,
quotaguard, freshpool, critgame; restarted through detach.sh, in their own units (pilotd's environment: /data/zw4424/st/bq/pilotd.env).
A daemon is restarted only after it was missing on 2 consecutive checks (~2 min), at most once per 10 min, and never
while its pause file exists: touch /data/zw4424/st/bq/<name>.nowatch BEFORE stopping a daemon on purpose.
Stall checks (every 5 min, spawning only quota and df): /data/zw4424/st/bq/pipealarm.txt holds the ALARM lines now active; since.py
prints them and the check-in hooks append them. Changes go to health.log. Kerberos: kinit -R every 2 h (the ticket lasts 10 h).
Each new live gets a UB audit on Condor (ub_live_tick; results in bq/ub_live.txt; a failure is an ALARM).
Health line (every --health s) to /data/zw4424/st/bq/health.log: load average (LOAD-HIGH above 3x cores), local cambc
run and ubaudit counts, running shipchecks, our Condor jobs (idle/running/held),
the last shipwatch verdict lines, daemons up/down, home files.
Rating (every --rating s, default 3600) to /homes/zw4424/condor-work/reports/live/rating.log: UTC, ladder rating and
rank (read-only `cambc400 ladder` via platlock.sh), live version (live.txt), total and new matches since the last line.
A RATING DROP line goes to health.log when the rating fell > 40 since just before a ship in the last 2 h, naming the
version(s) shipped in that window.
"""
import calendar
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
BQ = "/data/zw4424/st/bq"
HEALTH = BQ + "/health.log"
RATING = "/homes/zw4424/condor-work/reports/live/rating.log"
CLI = "/data/zw4424/cambc400/bin/cambc400"
DRY = os.environ.get("DRY") == "1"
ALARMS = BQ + "/pipealarm.txt"
RUNS = "/homes/zw4424/condor-runs"
PQ = RUNS + "/pilotq"
DAEMONS = {  # name: (command line, log, pid file some tool reads)
    "shipwatch": ("python3 -I tools/lab/shipwatch.py", BQ + "/shipwatch_daemon.log", None),
    "armq": ("python3 -I tools/lab/armq.py --loop", BQ + "/armq.log", None),
    "pilotd": ("python3 -I tools/lab/pilotd.py", "/dev/null", None),
    "livepipe": ("sh tools/lab/livepipe.sh --loop --every 600", "/data/zw4424/livepipe/loop.log", "/data/zw4424/livepipe/loop.pid"),
    "quotaguard": ("python3 -I tools/lab/quotaguard.py --loop --every 300", "/data/zw4424/quotaguard/loop.out", "/data/zw4424/quotaguard/loop.pid"),
    "freshpool": ("python3 -I /homes/zw4424/cambc/tools/lab/freshpool.py --loop --target 200 --par 24", "/data/zw4424/st/freshpool/daemon.out", "/data/zw4424/st/freshpool/daemon.pid"),
    "critgame": ("python3 -I tools/lab/critgame.py auto --loop --every 600", "/data/zw4424/st/crit/auto.log", "/data/zw4424/st/crit/auto.pid"),
}


STALE_DEPS = {"shipwatch": (), "armq": ("fastship.py", "ideastore.py"),
              "pilotd": (), "critgame": ()}  # modules a daemon imports once (a subprocess re-reads its script)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg, path=None):
    with open(path or HEALTH, "a") as f:
        f.write(f"{now()}{' [DRY]' if DRY else ''} {msg}\n")


def pids_of(cmd):
    """PIDs whose full command line is exactly cmd (shell wrappers that merely contain it are ignored). A loop started with
    another --every interval counts too (30 Oct 23:15: quotaguard restarted by hand with --every 300 did not match
    '--every 1200', so a second loop was started)."""
    out = []
    cmd = cmd.replace(REPO + "/", "")  # 5 Nov: armq re-executes itself by absolute path, which read as "armq down"
    base = cmd.split(" --every ")[0] + " --every " if " --every " in cmd else None
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            argv = open(f"/proc/{p}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        argv = [x.decode(errors="replace") for x in argv if x]
        if not argv:
            continue
        argv[0] = os.path.basename(argv[0])  # systemd starts /usr/bin/python3
        line = " ".join(argv).replace(REPO + "/", "")
        if line == cmd or (base and line.startswith(base) and line[len(base):].isdigit()):
            out.append(int(p))
    return out


def systemd_active(name):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", f"nova-{name}"]).returncode == 0


def start(name):
    cmd, logf, pidf = DAEMONS[name]
    if DRY:
        log(f"would restart {name}: {cmd}")
        return
    env = dict(os.environ)
    if name == "pilotd":
        try:
            env.update(ln.strip().split("=", 1) for ln in open(BQ + "/pilotd.env") if "=" in ln)
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import condorroute  # 8 Nov: pilotd.env still names ash09, which maple14 (own schedd) cannot reach: a restart would have stranded every pilot job
            if condorroute.local_schedd():
                env.pop("_CONDOR_SCHEDD_HOST", None)
                env.pop("_CONDOR_SCHEDD_NAME", None)
        except OSError as e:
            log(f"pilotd.env unreadable ({e}): restarting pilotd with the watchdog's environment")
    r = subprocess.run(["sh", "tools/lab/detach.sh", "-l", logf, name] + cmd.split(), cwd=REPO, env=env,  # exit 3: already running
                       capture_output=True, text=True)
    if r.returncode == 3:  # detach.sh: the unit is active, so the daemon is up and pids_of missed it: say so, never call it down
        log(f"{name}: its unit is running but its command line does not match {cmd!r}: not restarted; fix DAEMONS")
        return "up"
    if r.returncode:
        log(f"restart of {name} failed (exit {r.returncode}): {r.stderr.strip()[:200]}")
        return
    time.sleep(2)
    real = pids_of(cmd)
    if pidf and real:
        open(pidf, "w").write(f"{real[0]}\n")
    log(f"RESTARTED {name} (pid {real[0] if real else '?'}): {cmd}")


def condor_totals():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import condorroute  # 8 Nov: a hard-coded ash09 route read 'condor_q unreadable' on every tick once maple14 had its own schedd
    env = condorroute.env()
    out = subprocess.run(["condor_q", "-totals"], capture_output=True, text=True, env=env).stdout
    m = re.search(r"Total for query: (\d+) jobs;.*?(\d+) idle, (\d+) running, (\d+) held", out)
    return f"{m.group(1)} jobs ({m.group(2)} idle, {m.group(3)} running, {m.group(4)} held)" if m else "condor_q unreadable"


def live_version():
    try:
        return open(BQ + "/live.txt").read().split()[0]
    except (OSError, IndexError):
        return "?"


def rating_tick():
    """One rating line, plus the post-ship drop check."""
    import calendar
    import json
    team = None
    for page in (1, 2, 3):
        r = subprocess.run(["sh", REPO + "/tools/lab/platlock.sh", CLI, "ladder", "--page", str(page), "--limit", "60",
                            "--json"], capture_output=True, text=True, timeout=300, cwd=REPO)
        try:
            teams = json.loads(r.stdout)["teams"]
        except (ValueError, KeyError):
            log(f"rating: ladder call failed (exit {r.returncode})")
            return
        team = next((x for x in teams if x.get("name") == "BattleCats"), None)
        if team or len(teams) < 60:
            break
    if not team:
        log("rating: BattleCats not found in the first 180 ranks")
        return
    rows = []
    try:
        for ln in open(RATING):
            p = ln.split()
            if len(p) >= 5 and p[0].endswith("Z"):
                rows.append((calendar.timegm(time.strptime(p[0], "%Y-%m-%dT%H:%M:%SZ")), float(p[1]),
                             p[3], int(p[4])))
    except OSError:
        pass
    ver, m, rt = live_version(), int(team.get("matches", 0)), float(team["rating"])
    new = m - rows[-1][3] if rows else 0
    os.makedirs(os.path.dirname(RATING), exist_ok=True)
    with open(RATING, "a") as f:
        if not rows:
            f.write("# utc rating rank live matches_total new_matches\n")
        f.write(f"{now()} {rt:.1f} {team['rank']} {ver} {m} {new}\n")
    # drop check: the earliest live-version change within the last 2 h; baseline = the line before it
    t_now = time.time()
    rows.append((t_now, rt, ver, m))
    for i in range(1, len(rows)):
        if rows[i][2] != rows[i - 1][2] and t_now - rows[i][0] <= 7200:
            base = rows[i - 1][1]
            shipped = sorted({r[2] for r in rows[i:] if r[2] != rows[i - 1][2]})
            if rt < base - 40:
                log(f"RATING DROP {rt - base:+.0f} (from {base:.0f} to {rt:.0f}) since {', '.join(shipped)} shipped "
                    f"(baseline {rows[i - 1][2]}); consider a rollback")
            break


def health(state):
    checks = [l for l in (subprocess.run(["pgrep", "-af", "shipcheck.py"], capture_output=True, text=True).stdout
                          .splitlines()) if "python3 -I" in l and "pgrep" not in l]
    names = sorted({l.split()[-2] if len(l.split()) >= 2 else "?" for l in checks})
    try:
        tail = [l.strip() for l in open(BQ + "/shipwatch.log").readlines()[-200:]
                if re.search(r"PASS|FAIL|INCONCLUSIVE|SUBMITTED", l)][-3:]
    except OSError:
        tail = []
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import homequota  # the HOME server line, not the last mounted server
    hq = homequota.home_quota()
    files = hq["files"] if hq else "?"
    up = {n: bool(pids_of(DAEMONS[n][0])) for n in DAEMONS}
    l1, l5, _ = os.getloadavg()
    ncpu = os.cpu_count() or 1
    runs = subprocess.run(["pgrep", "-c", "-f", "cambc400 run"], capture_output=True, text=True).stdout.strip() or "0"
    audits = subprocess.run(["pgrep", "-c", "-f", "python3 -I .*ubaudit.py"], capture_output=True, text=True).stdout.strip() or "0"
    flag = f" LOAD-HIGH (> {3 * ncpu})" if l1 > 3 * ncpu else ""
    rate = ""
    try:  # rating trend: the latest rating vs the last reading before the current live version first appeared
        rows = [ln.split() for ln in open(RATING) if ln[:1].isdigit()]
        if len(rows) >= 2:
            cur, ver = float(rows[-1][1]), rows[-1][3]
            first = next(i for i in range(len(rows)) if all(r[3] == ver for r in rows[i:]))
            base = rows[first - 1] if first > 0 else rows[first]
            rate = f"; rating {cur:.0f} ({cur - float(base[1]):+.0f} since {ver} shipped, vs {base[3]} {float(base[1]):.0f})"
        elif rows:
            rate = f"; rating {float(rows[-1][1]):.0f} ({rows[-1][3]})"
    except (OSError, ValueError, IndexError, StopIteration):
        pass
    log(f"HEALTH load {l1:.0f}/{l5:.0f} on {ncpu} cores{flag}{rate}; local cambc runs {runs}, ubaudits {audits}; "
        f"shipchecks running {len(checks)} {names}; condor {condor_totals()}; home files {files}; daemons "
        + ", ".join(f"{n} {'up' if u else 'DOWN'}" for n, u in up.items())
        + (f"; last verdicts: {' | '.join(t[:120] for t in tail)}" if tail else ""))


def _free_gb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 2**30


def _proc_age(pattern):
    """Ages in seconds of this user's processes whose command line contains pattern."""
    with open("/proc/stat") as f:
        boot = next(int(ln.split()[1]) for ln in f if ln.startswith("btime"))
    tick, me, out = os.sysconf("SC_CLK_TCK"), os.getuid(), []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if os.stat("/proc/" + p).st_uid != me or pattern not in open(f"/proc/{p}/cmdline", "rb").read().decode(errors="replace"):
                    continue
                start = int(open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[19])
                out.append(time.time() - (boot + start / tick))
            except (OSError, ValueError, IndexError):
                continue
    return out


def _newest(d):
    """(newest mtime, entries) of a directory; (0, 0) if unreadable."""
    t, n = 0.0, 0
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.startswith("."):  # 5 Nov: stale .tmp files in pilotq/queue read as "15 items queued"
                    continue
                n += 1
                try:
                    t = max(t, e.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return t, n


_krb = [0.0, ""]  # last renewal attempt; the alarm it left


def kerberos_tick():
    """Renew every 2 h; the alarm says when only the owner can (a ticket is renewable for ~24 h, then needs a password)."""
    if time.time() - _krb[0] < 7200:
        return _krb[1]
    _krb[0], _krb[1] = time.time(), ""
    # 13 Nov (TB: after a restart without KRB5CCNAME, kinit -R looked in the keyring and alarmed although the FILE cache held a good ticket):
    # use the newest /tmp/krb5cc_<uid>_* file cache, as pilotd does
    import glob as _g
    _cc = sorted(_g.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
    _env = dict(os.environ, KRB5CCNAME="FILE:" + _cc[-1]) if _cc and not os.environ.get("KRB5CCNAME") else os.environ
    r = subprocess.run(["kinit", "-R"], capture_output=True, text=True, env=_env)
    if r.returncode:
        _krb[1] = f"ALARM kerberos renewal failed ({r.stderr.strip()[:100]}): the owner must run kinit on this machine"
        return _krb[1]
    m = re.search(r"renew until (\d\d/\d\d/\d\d \d\d:\d\d:\d\d)", subprocess.run(["klist"], capture_output=True, text=True, env=_env).stdout)
    if m:
        left = time.mktime(time.strptime(m.group(1), "%d/%m/%y %H:%M:%S")) - time.time()
        if left < 8 * 3600:
            _krb[1] = f"ALARM kerberos can be renewed for {left / 3600:.1f} h more: the owner must run kinit on this machine before then"
    return _krb[1]


_quiet = {"shipchecks": 0}
_pq = [None, time.time()]  # (queue+claimed names, when they last changed)


ENG_EXPECT = "/data/zw4424/st/bq/engine_expect.txt"
ENG_STATE = "/data/zw4424/st/bq/.engine_watch.state"
ENG_LOG = "/data/zw4424/st/bq/engine_watch.log"
ENG_NEW = "/data/zw4424/st/bq/engine_new.txt"


def engine_watch():
    import json
    exp = open(ENG_EXPECT).read().split() if os.path.exists(ENG_EXPECT) else ["3.0.0"]
    ver, hashes = exp[0], set(exp[1:])
    since = os.path.getmtime(ENG_STATE) if os.path.exists(ENG_STATE) else time.time() - 3 * 3600
    t0, new = time.time(), []
    seen = set()
    for d in os.scandir("/data/zw4424/plat"):
        if not (d.is_dir() and (d.name.startswith("rk_") or d.name.startswith("unr_"))):
            continue
        try:
            if d.stat().st_mtime < since:
                continue
            for e in os.scandir(d.path):
                if e.name.endswith(".json") and e.stat().st_mtime >= since:
                    try:
                        m = json.load(open(e.path)).get("match", {})
                    except (OSError, ValueError):
                        continue
                    v, h = m.get("engineVersion"), m.get("engineBuildHash", "")
                    if not v:
                        continue
                    if not hashes:  # first run: learn the current build
                        seen.add(h)
                    elif v != ver or h not in hashes:
                        new.append((d.name, e.name[:-5], v, h))
        except OSError:
            continue
    if not hashes and seen:
        open(ENG_EXPECT, "w").write(ver + "\n" + "\n".join(sorted(seen)) + "\n")
    open(ENG_STATE, "a").close()
    os.utime(ENG_STATE, (t0, t0))
    if new and not os.path.exists(ENG_NEW):
        st, mid, v, h = new[0]
        open(ENG_NEW, "w").write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} first match {mid} ({st}) engine {v} build {h[:16]}\n")
    if new:
        with open(ENG_LOG, "a") as f:
            for st, mid, v, h in new:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {st} {mid} engine {v} build {h[:16]}\n")
    if os.path.exists(ENG_NEW):
        return [f"ALARM NEW ENGINE in live matches: {open(ENG_NEW).read().strip()[:200]} - follow condor-work/reports/engine_switch_checklist.md, then rm {ENG_NEW}"]
    return []


_census = [0.0]


def census(files, mb):
    """8 Nov: home spiked 47.8k -> 58.4k files and +1.4 GB at 09:38 and fell back by 09:43, stalling condab on the home guard, and no one
    could say what it was (old mtimes: unpacked files). Above 54k files or 9.3 GB, at most every 3 min, log the folders holding the
    most files (3 levels under /homes/zw4424, inode counts) to bq/homecensus.log, so the next spike names its source."""
    if time.time() - _census[0] < 180:
        return
    _census[0] = time.time()
    try:
        r = subprocess.run(["timeout", "120", "du", "--inodes", "-x", "-d", "3", "/homes/zw4424"], capture_output=True, text=True)
        rows = sorted(((int(n), d) for n, d in (ln.split("\t", 1) for ln in r.stdout.splitlines() if "\t" in ln) if d.count("/") >= 4),
                      reverse=True)[:15]
        with open(BQ + "/homecensus.log", "a") as f:
            f.write(f"{now()} home {files} files {mb:.0f} MB; top folders by files: " + "; ".join(f"{d[13:]} {n}" for n, d in rows) + "\n")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def stall_checks(missing):
    """The ALARM lines true now; each says what is wrong and what to do."""
    out, now_t = [], time.time()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import homequota
    hq = homequota.home_quota() or {}
    files, mb = hq.get("files", 0), hq.get("mb", 0)
    if files >= 56500 or mb >= 10600:  # 12 Nov 20:5xZ (TB): cxefarm's gate is 57,500 now, new pilots stop at 58,500  # 12 Nov (Builder: b2242's prearms stuck at cxefarm's CXEFARM_HOME_FILES 54,000 gate): warn first  # 12 Nov (TB): condab's MB band moved to 11,000 / 11,400 (quota 11,719 soft); the text said 10,000 / 10,800
        out.append(f"ALARM home {files} files, {mb:.0f} MB (cxefarm stops staging at 57,500 files, new pilots stop at 58,500; condab slows at 58,000 / 11,000 MB, stops at 59,000 / 11,400 MB; quota 11,719 MB soft): "
                   "list what is idle in condor-runs and remove it with tools/lab/rmdata.sh")
    try:  # 9 Nov (owner: the analysts must see all our losses, continuously): losstable's backlog numbers
        lt = json.load(open("/data/zw4424/st/crit/losstable.json"))
        if lt.get("oldest_unclaimed_h") and lt["oldest_unclaimed_h"] > 1 and not os.path.exists("/data/zw4424/st/crit/AUTO_OFF"):  # 10 Nov: owner turned critgame off
            out.append(f"ALARM {lt['open_unclaimed']} flagged losses unclaimed, the oldest {lt['oldest_unclaimed_h']} h: analysts, claim from "
                       "`critgame.py status` (condor-work/reports/live/all_losses.md lists every loss)")
        if (lt.get("claimed_stale") or 0) >= 5:  # 9 Nov (Econ via Coordinator): claimed games nobody works on are the real analysis gap
            out.append(f"ALARM {lt['claimed_stale']} flagged losses claimed but untouched for > 4 h: owners, walk or release them "
                       "(`critgame.py status`)")
        if now_t - os.path.getmtime("/data/zw4424/st/crit/losstable.json") > 3600:
            out.append("ALARM losstable.json is over an hour old: nova-losstable (the all-losses table) is not refreshing")
        if lt.get("no_replay", 0) > 200:
            out.append(f"ALARM {lt['no_replay']} triaged losses have no replay on disk (losstable back-fills {os.environ.get("LT_FETCH_SHOWN", "60")} a pass, lower-ranked foes and newest versions first; list: losstable.py missing)")
    except (OSError, ValueError):
        pass
    try:  # 9 Nov: memguard stopped a job to keep the kernel's OOM killer off VS Code (and every session)
        mg = "/data/zw4424/st/memguard/ALARM"
        if now_t - os.path.getmtime(mg) < 3600:
            out.append("ALARM memguard stopped a job (memory ran low): " + open(mg).read().strip()[:220]
                       + "; run heavy jobs as units with -p MemoryMax=8G")
    except OSError:
        pass
    if files >= 57000 or mb >= 9300:  # du over the NFS home takes ~60 s: in a thread, so the checks never wait for it
        import threading
        threading.Thread(target=census, args=(files, mb), daemon=True).start()
    try:
        if now_t - os.path.getmtime(BQ + "/preflight_hold") < 600:
            out.append("ALARM condab batches are waiting on the home guard: free home files now")
    except OSError:
        pass
    for path, low in (("/var", 5.0), ("/data", 20.0), ("/tmp", 10.0)):  # 10 Nov: /tmp is RAM (tmpfs 30 GB): files there eat memory memguard can't free  # /var 2 -> 5 GB (10 Nov 00:25Z: syslog grew 23 GB in a day, ~1-2 GB/h on maple18)
        if _free_gb(path) < low:
            out.append(f"ALARM {path} {_free_gb(path):.1f} GB free"
                       + (" (root's syslog grows with every process we start: cut process churn; owner -> CSG)" if path == "/var" else ""))
    try:  # 10 Nov (Econ, Deep asked why the climbs stopped): varguard's active steps (climbs paused, fewer slots, shipwatch held), said plainly
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/varguard.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 10 Nov: loadguard's paused units (load + cpu pressure valve)
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/loadguard.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 10 Nov (Planner): a failed failed-positive-bank re-screen (flagscreen bank rescreen) used to fail silently
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/bankrescreen.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 10 Nov (Coordinator): Step 0 diags (prio <= 9) starving behind ship legs (tools/lab/staleq.py wait, every 30 min)
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/staleq.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 10 Nov (Coordinator): queued batches of closed ideas (tools/lab/closedq.py, hourly at :25)
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/closedq.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 10 Nov (Coordinator): a spec > 60 min old with no build agent, prereg, arm or batch (pipe.py handoff --alarm, nova-handoff timer)
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/handoff.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # 12 Nov (RC X593: FB6_TAB sat on bake_keep for a day after its named candidate obf7 ended FAIL): a bake_keep line whose named
        # candidate (a '(slug)' or nova_bNNNN_slug in its comment) has a final shipcheck verdict is probably stale
        ended = {}
        for ln in open("/data/zw4424/st/bq/shipwatch.log", errors="replace").readlines()[-20000:]:
            m = re.search(r" ended nova_b\d+_([a-z0-9]+): (PASS|FAIL)", ln)
            if m:
                ended[m.group(1)] = (m.group(2), ln[:16])
        for ln in open("/data/zw4424/st/bq/bake_keep.txt", errors="replace"):
            tab, _, com = ln.partition("#")
            if not tab.strip():
                continue
            names = set(re.findall(r"\(([a-z][a-z0-9]{2,})\)", com)) | set(re.findall(r"nova_b\d+_([a-z0-9]+)", com))
            done = [f"{x} {ended[x][0]} {ended[x][1]}Z" for x in sorted(names) if x in ended]
            if done:
                out.append(f"ALARM bake_keep: {tab.strip()} still held, but its named candidate ended ({'; '.join(done)}): remove the line if its value is settled")
    except OSError:
        pass
    try:  # 12 Nov (Planner, failed-positive bank rule (b)): tools/lab/fpsites.py's site hits of the last 24 h (one re-test on live each)
        cut = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() - 86400))
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/fpsites.alarm") if ln.startswith("ALARM FPBANK SITE HIT ") and ln.split()[4][:17] >= cut]
    except (OSError, IndexError):
        pass
    with open("/proc/meminfo") as f:
        avail = next(int(ln.split()[1]) for ln in f if ln.startswith("MemAvailable")) / 2**20
    if avail < 8:
        out.append(f"ALARM {avail:.1f} GB RAM available: stop adding local jobs")
    # pilots: work queued and nothing finishing. 5 Nov: done/ is emptied within a minute, so its newest file is no clock (an empty
    # dir read as "done 29,898,500 min ago"); progress = the set of queue and claimed names changing between checks
    _, queued = _newest(PQ + "/queue")
    _, claimed = _newest(PQ + "/claimed")
    alive, _ = _newest(PQ + "/pilots")
    try:
        sig = hash(tuple(sorted(os.listdir(PQ + "/queue")) + sorted(os.listdir(PQ + "/claimed"))))
    except OSError:
        sig = None
    if sig != _pq[0] or not (queued + claimed):
        _pq[:] = [sig, now_t]
    if queued and now_t - alive > 600:
        out.append(f"ALARM {queued} pilot items queued and no pilot heartbeat for {(now_t - alive) / 60:.0f} min: pilotd.py --status, condor_q via ash09")
    elif queued + claimed and now_t - _pq[1] > 1800:
        out.append(f"ALARM pilot queue not moving: {queued} queued, {claimed} claimed, unchanged for {(now_t - _pq[1]) / 60:.0f} min")
    try:
        if os.path.getsize(PQ + "/pilotd.hb") >= 0 and now_t - os.path.getmtime(PQ + "/pilotd.hb") > 900:
            out.append("ALARM pilotd heartbeat older than 15 min")
    except OSError:
        pass
    # 6 Nov (owner via Builder: the 4.0.0 balance patch is out; is the engine new?): every fetched live match records its engine. ALARM
    # the first time one is not the expected version or build (bq/engine_expect.txt: line 1 version, then known build hashes); the
    # first such match is logged in bq/engine_watch.log and the alarm stays until bq/engine_new.txt is removed (switch checklist:
    # condor-work/reports/engine_switch_checklist.md)
    try:
        out += engine_watch()
    except Exception as e:  # noqa: BLE001
        out.append(f"engine watch failed: {str(e)[:100]}")
    # 6 Nov (FUELX markers were rejected for an hour: shipwatch had run since 5 Nov 21:51 on the old parser): a daemon whose script or a
    # module it imports from tools/lab changed after the process started runs old code. ALARM with the restart hint.
    try:
        tick = os.sysconf("SC_CLK_TCK")
        boot = time.time() - float(open("/proc/uptime").read().split()[0])
        for name, (cmd, _log, _pidf) in DAEMONS.items():
            script = next((x for x in cmd.split() if x.endswith(".py")), None)
            if not script:
                continue
            path = script if script.startswith("/") else os.path.join(REPO, script)
            deps = [path] + [os.path.join(REPO, "tools/lab", m) for m in STALE_DEPS.get(name, ())]
            for pid in pids_of(cmd):
                st = boot + int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]) / tick
                if name == "armq":  # armq re-execs itself when armq.py changes (same pid and start time): its log has the real start
                    try:
                        with open(BQ + "/armq.log", "rb") as lf:
                            lf.seek(max(0, os.path.getsize(BQ + "/armq.log") - 400000))
                            hits = re.findall(rb"^(\S+Z) armq start pid", lf.read(), re.M)
                        if hits:
                            st = max(st, calendar.timegm(time.strptime(hits[-1].decode(), "%Y-%m-%dT%H:%M:%SZ")))
                    except (OSError, ValueError):
                        pass
                newer = [os.path.basename(d) for d in deps if os.path.exists(d) and os.path.getmtime(d) > st + 60]
                if newer:
                    out.append(f"ALARM {name} (pid {pid}, up since {time.strftime('%H:%M', time.gmtime(st))}Z) runs code older than "
                               f"{', '.join(newer)}: restart it (touch {BQ}/{name}.nowatch, kill {pid}, start, rm the .nowatch)")
    except (OSError, ValueError, IndexError):
        pass
    # held Condor jobs (6 Nov, b1340: direct cqbatch jobs HELD 'Failed to initialize user log': the ash09 schedd can't see this machine's /data)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import condorroute
        r = subprocess.run(["condor_q", os.environ.get("USER", "zw4424"), "-hold", "-af", "ClusterId", "HoldReason"], capture_output=True,
                           text=True, timeout=60, env=condorroute.env())
        held = [ln for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []
        if held:
            out.append(f"ALARM {len(held)} Condor jobs HELD (e.g. cluster {held[0][:160]}): condor_q -hold via ash09; condor_rm the clusters once read")
    except (OSError, subprocess.SubprocessError):
        pass
    # cxe on the nodes broken: batches fall back to the CLI (5 Nov: a pruned runtime sent all of them there)
    cli = 0
    with os.scandir(RUNS) as it:
        for e in it:
            if e.name.endswith("_cli"):
                try:
                    cli += now_t - e.stat().st_mtime < 900
                except OSError:
                    pass
    if cli:
        out.append(f"ALARM {cli} batches fell back to the CLI in the last 15 min: cxe spot-checks are failing (tools/cxe/cxecondab.py runtime, cxeident)")
    # armq repeating the same complaint
    try:
        if now_t - os.path.getmtime(BQ + "/armq.log") < 1800:
            with open(BQ + "/armq.log", "rb") as f:
                f.seek(max(0, os.path.getsize(BQ + "/armq.log") - 8000))
                tail = f.read().decode(errors="replace").splitlines()[-40:]
            seen = {}
            for ln in tail:
                if "!!" in ln:
                    k = re.sub(r"\d", "", ln)
                    seen[k] = (seen.get(k, (0, ""))[0] + 1, ln)
            for n, ln in seen.values():
                if n >= 5:
                    out.append(f"ALARM armq repeating ({n} of its last 40 lines): {ln.strip()[:140]}")
    except OSError:
        pass
    # shipchecks: stuck, or markers waiting with none running
    ages = _proc_age("shipcheck.py")
    if ages and max(ages) > 8 * 3600:
        out.append(f"ALARM a shipcheck has run {max(ages) / 3600:.1f} h: shipwatch.log, its .out file")
    _quiet["shipchecks"] = 0 if ages else _quiet["shipchecks"] + 1
    try:
        with open(BQ + "/shipwatch.log", "rb") as f:
            f.seek(max(0, os.path.getsize(BQ + "/shipwatch.log") - 1500))
            last = f.read().decode(errors="replace").splitlines()[-3:]
        if _quiet["shipchecks"] >= 3 and any(" waiting " in ln for ln in last):
            out.append("ALARM shipwatch has markers waiting and no shipcheck has run for 15 min: " + last[-1][:120])
    except OSError:
        pass
    try:  # cxe slot waiters stuck
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cxe"))
        import cxerun
        h = cxerun.health()
        if h:
            out.append(f"ALARM {h}")
    except Exception as e:  # noqa: BLE001  (a broken check must not hide the rest)
        out.append(f"ALARM cxe health check failed: {e}")
    for n, m in missing.items():
        if m >= 3 and not os.path.exists(f"{BQ}/{n}.nowatch"):
            out.append(f"ALARM daemon {n} is down and did not restart (health.log)")
    k = kerberos_tick()
    if k:
        out.append(k)
    try:  # the newest version's own report (tools/lab/livefollow.py)
        with open("/data/zw4424/st/lean/follow_status.txt") as f:
            lst = f.readlines()[-1:]
        if lst and ("MISMATCH" in lst[0] or "CONFLICT" in lst[0] or "FUEL PROOF FAILED" in lst[0]):
            out.append("ALARM livefollow: " + lst[0].strip()[:200])
    except OSError:
        pass
    u = ub_live_tick()
    if u:
        out.append(u)
    b = batchfail_check(now_t)
    if b:
        out.append(b)
    return out


def batchfail_check(now_t, window=3600, share=0.05):
    """7 Nov (Builder: b006 lost 8,578 of 9,730 games, Deep's readmany 550 of 550, both starved): an ALARM when a cxefarm batch in the
    last hour came back short by more than 5% of its games (cxefarm appends each short batch to bq/batchfail.jsonl with its reason)"""
    bad = []
    try:
        for ln in open(BQ + "/batchfail.jsonl"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if now_t - d.get("t", 0) < window and d.get("games", 0) >= 20 and d["back"] < (1 - share) * d["games"]:
                bad.append(d)
    except OSError:
        return None
    if not bad:
        return None
    starved = sum(1 for d in bad if d.get("queued"))
    worst = max(bad, key=lambda d: d["games"] - d["back"])
    return (f"ALARM {len(bad)} cxefarm batch(es) came back > 5% short in the last hour ({starved} starved in the queue, "
            f"{sum(1 for d in bad if d.get('short'))} with games missing from finished items); worst {worst['games'] - worst['back']} of "
            f"{worst['games']} games, priority {worst.get('prio')}, caller {worst.get('caller', '')[:80]} (bq/batchfail.jsonl)")


UB_STATE = BQ + "/ub_live.txt"  # one line per audited live: VER BOT PASS|FAIL|ERROR report-or-log
UB_N = os.environ.get("UB_LIVE_N", "40")


def ub_live_tick():
    """Audit each new live (5 Nov, owner: no undefined behaviour): data flips skip ubaudit in shipcheck, so flag-on paths reached live
    unaudited. On Condor, not local; one at a time, always the newest live; the map seed changes per version, so coverage grows.
    -> an ALARM line if the newest finished audit failed, else ''."""
    try:
        rows = [ln.split() for ln in open(UB_STATE) if ln.strip()]
    except OSError:
        rows = []
    run = BQ + "/ub_live_running"
    if os.path.exists(run):
        ver, bot, base, t0 = open(run).read().split()
        log_f = f"{BQ}/ub_live_{ver}.log"
        txt = open(log_f, errors="replace").read() if os.path.exists(log_f) else ""
        m = re.search(r"VERDICT: (PASS|FAIL)", txt)
        rep = re.search(r"report: (\S+)", txt)
        if not m and "Condor failed twice" in txt:  # 8 Nov: a full pool is no result: the next tick starts it again (it sat 'running' to the 90 min limit, then ERROR)
            os.replace(log_f, log_f + ".noslot")
            os.remove(run)
            if "condor_submit failed" in txt:  # 8 Nov: 'no slot' hid a dead schedd route for good: a refused submit is a fault, not a busy pool
                why = re.search(r"condor_submit failed \(([^)]*)", txt).group(1)[:120]
                log(f"UB audit of live {ver} {bot}: condor_submit refused ({why}); will retry")
                return f"ALARM UB audit of live {ver} {bot}: condor_submit refused ({why}): check the schedd route (condorroute.py)"
            log(f"UB audit of live {ver} {bot}: no Condor slot; will retry")
            return f"ALARM UB audit of live {rows[-1][0]} {rows[-1][1]}: {rows[-1][2]}: {rows[-1][3]}" if rows and rows[-1][2] != "PASS" else ""
        if m or time.time() - float(t0) > 5400:
            st = m.group(1) if m else "ERROR"
            with open(UB_STATE, "a") as f:
                f.write(f"{ver} {bot} {st} {rep.group(1) if rep else log_f}\n")
            rows.append([ver, bot, st, rep.group(1) if rep else log_f])
            os.remove(run)
            log(f"UB audit of live {ver} {bot}: {st}")
    else:
        try:
            ver, bot = open(BQ + "/live.txt").readline().split()[:2]
        except (OSError, ValueError):
            return ""
        if not any(r[0] == ver for r in rows):
            passed = [r[1] for r in rows if r[2] == "PASS"]
            base = passed[-1] if passed else bot
            log_f = f"{BQ}/ub_live_{ver}.log"
            cmd = ["sh", "tools/lab/detach.sh", "-l", log_f, f"ublive-{ver}", "env", "UB_REMOTE=1", "UB_REMOTE_START=1800", f"SEED={re.sub(chr(92) + 'D', '', ver)}",
                   "PATH=/usr/local/condor/release/bin:" + os.environ.get("PATH", ""), "sh", "tools/lab/ubaudit.sh", bot, base, UB_N]
            if not DRY and subprocess.run(cmd, cwd=REPO, capture_output=True).returncode == 0:
                open(run, "w").write(f"{ver} {bot} {base} {time.time():.0f}\n")
                log(f"UB audit of live {ver} {bot} started (v {base}, {UB_N} maps, seed from the version)")
    if rows and rows[-1][2] != "PASS":
        return f"ALARM UB audit of live {rows[-1][0]} {rows[-1][1]}: {rows[-1][2]}: {rows[-1][3]}"
    return ""


FUEL_STAMP = BQ + "/fueltrack.last"


def fuel_tick():
    """Hourly (owner 8 Nov: "analyse our fuel outs and keep track of it"): tools/lab/fueltrack.py rebuilds /data/zw4424/st/fueltrack. Detached, nice 19.
    touch bq/fueltrack_OFF stops it."""
    try:
        last = os.path.getmtime(FUEL_STAMP)
    except OSError:
        last = 0.0
    if time.time() - last < 3600 or os.path.exists(BQ + "/fueltrack_OFF") or DRY:
        return
    with open(FUEL_STAMP, "w") as f:
        f.write(now() + "\n")
    subprocess.run(["sh", "tools/lab/detach.sh", "-n", "19", "-l", "/data/zw4424/st/fueltrack/run.log", "fueltrack", "python3", "-I", "tools/lab/fueltrack.py", "--quiet"],
                   cwd=REPO, capture_output=True)


SWEEP_STAMP = BQ + "/ideasweep.last"  # a restart must not reset the hour (5 Nov: three restarts kept pushing the first pass back)


def sweep_tick():
    """Hourly: retire bots no work needs (ideastore.py sweep; owner 5 Nov OK). touch bq/ideasweep_OFF stops it. Detached so a long pass never delays the checks."""
    try:
        last = os.path.getmtime(SWEEP_STAMP)
    except OSError:
        last = 0.0
    if time.time() - last < 3600 or os.path.exists(BQ + "/ideasweep_OFF") or DRY:
        return
    with open(SWEEP_STAMP, "w") as f:
        f.write(now() + "\n")
    r = subprocess.run(["sh", "tools/lab/detach.sh", "-n", "19", "-l", BQ + "/ideasweep.log", "ideasweep", "python3", "-I", "tools/lab/ideastore.py", "sweep", "--apply"],
                       cwd=REPO, capture_output=True, text=True)
    log("idea sweep started" if r.returncode == 0 else f"idea sweep not started: {r.stderr.strip()[:120]}")


_reap = [0.0]


def reap_tick():
    """Every 10 min: waitreap.py --kill (8 Nov: one manual run found 56 self-matching waiters, which can never end; owner 1 Nov 'waiters
    must not stall forever'). Stops only SELF-MATCH and > 6 h waiters; each stop is logged with its session in bq/waitreap.log."""
    if time.time() - _reap[0] < 600 or DRY:
        return
    _reap[0] = time.time()
    try:
        r = subprocess.run(["python3", "-I", "tools/lab/waitreap.py", "--kill"], cwd=REPO, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return
    n = r.stdout.count("  stopped ")
    if n:
        log(f"waitreap stopped {n} stalled waiter(s) (bq/waitreap.log)")


_active = [set()]


def schedd_failover():
    """9 Nov 18:55Z: maple16 rebooted, its schedd was gone, every condor_q failed and all Condor pilots vanished (10 left, 0 items/min) until the
    route was moved by hand. When the last 5 min of pilot.log hold >= 5 '!! condor_q failed', try bq/schedd_candidates.txt in order (one host a
    line), move pilotd.env's _CONDOR_SCHEDD_NAME/HOST to the first whose condor_q answers, and restart pilotd (cqbatch/condorroute read the
    file on each call). At most once per 15 min."""
    st = BQ + "/schedd_failover.last"
    try:
        if time.time() - os.path.getmtime(st) < 900:
            return
    except OSError:
        pass
    try:
        with open(BQ + "/pilot.log", "rb") as f:
            f.seek(max(0, os.path.getsize(BQ + "/pilot.log") - 20000))
            tail = f.read().decode(errors="replace").splitlines()
    except OSError:
        return
    cut = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 300))
    fails = sum(1 for ln in tail if "!! condor_q failed" in ln and ln[:19] >= cut)
    if fails < 5:
        return
    open(st, "w").close()
    env = dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", ""))
    cur = next((ln.split("=", 1)[1].strip() for ln in open(BQ + "/pilotd.env") if ln.startswith("_CONDOR_SCHEDD_NAME=")), "")
    for h in [x.strip() for x in open(BQ + "/schedd_candidates.txt") if x.strip()]:
        r = subprocess.run(["condor_q", "-totals"], capture_output=True, text=True, timeout=30,
                           env=dict(env, _CONDOR_SCHEDD_NAME=h, _CONDOR_SCHEDD_HOST=h))
        if r.returncode == 0 and "Total for" in r.stdout:
            if h == cur:
                log(f"schedd failover: {fails} condor_q failures in 5 min but the current schedd {h} answers now: no change")
                return
            txt = open(BQ + "/pilotd.env").read().replace(cur, h) if cur else open(BQ + "/pilotd.env").read()
            open(BQ + "/pilotd.env.new", "w").write(txt)
            os.replace(BQ + "/pilotd.env.new", BQ + "/pilotd.env")
            subprocess.run(["systemctl", "--user", "restart", "nova-pilotd"], capture_output=True, timeout=60)
            log(f"ALARM schedd failover: {fails} condor_q failures in 5 min on {cur}: route moved to {h}, pilotd restarted")
            return
    log(f"ALARM schedd failover: {fails} condor_q failures in 5 min and no candidate schedd answers (bq/schedd_candidates.txt)")


def alarm_tick(missing):
    lines = stall_checks(missing)
    tmp = f"{ALARMS}.new.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(now() + "\n" + "".join(ln + "\n" for ln in lines))
    os.replace(tmp, ALARMS)
    keys = {re.sub(r"\d+(\.\d+)?", "#", ln) for ln in lines}
    for ln in lines:
        if re.sub(r"\d+(\.\d+)?", "#", ln) not in _active[0]:
            log(ln)
    for k in _active[0] - keys:
        log("CLEARED " + k)
    _active[0] = keys


def main():
    a = sys.argv[1:]
    if "--check" in a:
        global ub_live_tick
        ub_live_tick = lambda: ""  # a look must not start an audit
        print("\n".join(stall_checks({})) or "no alarms")
        return
    if "--loop" not in a:
        print(__doc__)
        sys.exit(1)
    every = int(a[a.index("--every") + 1]) if "--every" in a else 60
    hevery = int(a[a.index("--health") + 1]) if "--health" in a else 1200
    revery = int(a[a.index("--rating") + 1]) if "--rating" in a else 3600
    last_rating, last_alarm = 0.0, 0.0
    os.makedirs(BQ, exist_ok=True)
    missing, last_start, last_health = {n: 0 for n in DAEMONS}, {n: 0.0 for n in DAEMONS}, 0.0
    log(f"healthwatch started (pid {os.getpid()}; check every {every}s, health every {hevery}s)")
    while True:
        try:
            for n, (cmd, _, _) in DAEMONS.items():
                if pids_of(cmd):
                    missing[n] = 0
                    continue
                missing[n] += 1
                if os.path.exists(f"{BQ}/{n}.nowatch"):
                    continue
                if missing[n] >= 2 and time.time() - last_start[n] > 600:
                    start(n)  # a failed start must keep counting: stall_checks raises "down" at 3 misses
                    last_start[n] = time.time()
                    missing[n] = 0 if pids_of(cmd) or systemd_active(n) else missing[n]
            if time.time() - last_alarm >= 300:
                last_alarm = time.time()
                alarm_tick(missing)
                schedd_failover()
                sweep_tick()
                fuel_tick()
                reap_tick()
            if revery and time.time() - last_rating >= revery:
                last_rating = time.time()
                rating_tick()
            if time.time() - last_health >= hevery:
                health(missing)
                last_health = time.time()
        except Exception as e:  # noqa: BLE001  the watchdog must keep running overnight
            log(f"error: {type(e).__name__}: {e}")
        time.sleep(every)


if __name__ == "__main__":
    main()
