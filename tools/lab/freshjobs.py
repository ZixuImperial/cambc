#!/usr/bin/env python3
"""freshjobs: top up the fresh map pool from Condor nodes, on demand, so HOST stays light. Tool builder, 2 Nov. No daemon.

usage: python3 -I tools/lab/freshjobs.py [--cap 12] [--status]
Counts the ready sets and the sets being built, and queues one Condor job per missing set up to --cap (FRESH_CAP, default 12: one gate takes 2-6;
6 ran short on 2 Nov). Each job runs stratmaps.py on a node into XPOOL/building/ID on the shared scratch, and renames it to XPOOL/ready/ID if it
holds at least 95% of its maps; a failed job leaves nothing ready. freshpool.take reads XPOOL/ready as well as its own pool (same
single-use claim) and starts this script after every take, so sets are only ever made as they are used. Maps here are regenerable
and unseen until taken. Anything building for over 2 h counts as dead (Condor removes such a job)."""
import fcntl
import glob
import os
import subprocess
import sys
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

XPOOL = "/homes/USER/condor-runs/freshpool"  # 2 Nov (owner: no bitbucket): one .tgz per set on the home, unpacked by the take
LOGD = "/data/USER/st/freshpool/xlogs"
REPO = "/homes/USER/cambc"
SET_N = 300
DEAD = 2 * 3600
JOB = """#!/bin/sh
d=/tmp/USER-fresh-$1
x=%s
trap 'rm -rf "$d"; rmdir "$x/building/$1" 2>/dev/null' EXIT
cd %s && nice -n 10 python3 -I tools/lab/stratmaps.py "$d" --n %d --jobs "${2:-4}" || exit 1
n=$(ls "$d" | grep -c '\\.map26a$')
[ -f "$d/otf.json" ] && [ "$n" -ge %d ] || { echo "only $n maps"; exit 1; }
tar -czf "$x/ready/.$1.tmp" -C "$d" . && mv "$x/ready/.$1.tmp" "$x/ready/$1.tgz"
""" % (XPOOL, REPO, SET_N, int(0.95 * SET_N))


def counts():
    now = time.time()
    for f in glob.glob(f"{XPOOL}/logs/*") + glob.glob(f"{LOGD}/*"):
        if now - os.path.getmtime(f) > DEAD:
            os.remove(f)
    ready = glob.glob(f"{XPOOL}/ready/*")
    live, dead = [], []
    for d in glob.glob(f"{XPOOL}/building/*"):
        (live if now - os.path.getmtime(d) < DEAD else dead).append(d)
    return ready, live, dead


def env():
    """A daemon's Kerberos cache can be gone (pilotd, 30 Oct): use the newest one."""
    e = dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", ""))
    cc = e.get("KRB5CCNAME", "")
    if not os.path.exists(cc[5:] if cc.startswith("FILE:") else cc):
        files = sorted(glob.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
        if files:
            e["KRB5CCNAME"] = "FILE:" + files[-1]
    return e


PRUN = f"{XPOOL}/prun"  # pilot items' run dirs (one per set: a pilot skips an item whose output file exists)


def submit_pilot(sid):
    """4 Nov: a set as a pilot item (high priority) when pilots run: as its own Condor job it waited behind our own pilots, which held
    65 of the 70 machines that would take it, and shipcheck legs then waited 16 min for maps."""
    import pilotd
    if len(pilotd.alive_pilots()) < int(os.environ.get("FRESH_PILOT_MIN", 4)):
        return False
    os.makedirs(f"{XPOOL}/building/{sid}")
    pilotd.enqueue(f"{PRUN}/{sid}", [(0, [sid, 4])], int(os.environ.get("FRESH_PILOT_PRIO", 40)), node=f"{XPOOL}/job.sh")
    return True


def submit(sid):
    if os.environ.get("FRESH_PILOT", "1") != "0" and submit_pilot(sid):
        return True
    os.makedirs(LOGD, exist_ok=True)
    sub = f"{LOGD}/{sid}.sub"  # 2 Nov: 4 files a set on the home, 800 at a time
    open(sub, "w").write(f"""universe = vanilla
executable = {XPOOL}/job.sh
arguments = {sid}
initialdir = {XPOOL}/logs
output = /dev/null
error = /dev/null
log = {LOGD}/{sid}.log
request_cpus = 4
request_memory = 4000
priority = 15
batch_name = fresh_set
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv = True
should_transfer_files = NO
periodic_remove = (time() - QDate) > {DEAD}
queue 1
""")
    os.makedirs(f"{XPOOL}/building/{sid}")
    r = subprocess.run(["condor_submit", sub], capture_output=True, text=True, env=env())
    if r.returncode:
        os.rmdir(f"{XPOOL}/building/{sid}")
        print(f"freshjobs: submit failed: {(r.stdout + r.stderr).strip()[-160:]}")
        return False
    return True


def main():
    a = sys.argv[1:]
    cap = int(a[a.index("--cap") + 1]) if "--cap" in a else int(os.environ.get("FRESH_CAP", 200))  # 9 Nov (Builder: 16 agents + shipchecks drew the pool dry at 24; ~0.4 MB a set on home)
    for d in ("ready", "building", "logs", "taken"):
        os.makedirs(f"{XPOOL}/{d}", exist_ok=True)
    ready, live, dead = counts()
    if "--status" in a:
        print(f"scratch pool: ready {len(ready)}, building {len(live)}, dead {len(dead)}, cap {cap}")
        return 0
    with open(f"{XPOOL}/.lock", "a") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another top-up is running
        if not os.path.exists(f"{XPOOL}/job.sh") or open(f"{XPOOL}/job.sh").read() != JOB:  # atomically: a job exec'ing a half-written
            tmp = f"{XPOOL}/.job.sh.{os.getpid()}"                                          # file was held (Exec format error, 4 Nov)
            open(tmp, "w").write(JOB)
            os.chmod(tmp, 0o755)
            os.replace(tmp, f"{XPOOL}/job.sh")
        for d in glob.glob(f"{PRUN}/*"):  # finished pilot items' run dirs
            try:  # 9 Nov 17:15Z: a finished item (its job output is back) goes after 10 min, not 2 h: at 200 sets ~1,800 of these held the home
                # over cxefarm's 54k-file gate and stalled every identity check; an unfinished one still waits DEAD
                age = time.time() - os.path.getmtime(d)
                if age > DEAD or (age > 600 and glob.glob(f"{d}/job_p*.out")):
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        ready, live, dead = counts()
        need = cap - len(ready) - len(live)
        made = 0
        for _ in range(max(0, need)):
            sid = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "_" + os.urandom(2).hex()
            made += bool(submit(sid))
        print(f"freshjobs: ready {len(ready)}, building {len(live)}, queued {made} (cap {cap})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
