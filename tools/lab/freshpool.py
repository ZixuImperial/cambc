#!/usr/bin/env python3
"""freshpool: a pool of pre-generated, never-seen stratmaps sets, each handed out once. Tool builder, 1 Nov (owner: faster
iterations; Builder: agents waited 5-15 min for per-run map generation).

  python3 -I tools/lab/freshpool.py --loop [--target 20] [--par 3] [--n 300]   the daemon (pid in POOL/daemon.pid, log POOL/daemon.log)
  python3 -I tools/lab/freshpool.py --status                        ready / building / taken sets
  python3 -I tools/lab/stratmaps.py DIR --n N --take [--who NAME]    a consumer: take pool sets into DIR, else generate

Pool /data/USER/st/freshpool: building/ID (stratmaps.py at nice 19, stratmaps' weird share (50%), kind-labelled), ready/ID once its
otf.json is written, taken/ID after a take. A take claims a set with ONE os.rename(ready/ID -> taken/ID): two consumers can
never get the same set, and a taken set is never handed out again. It then moves the maps into DIR and writes DIR/otf.json
(the stratmaps format, with "pool": [IDs] and "taken_by"), and logs the take to POOL/taken.log (time, who, IDs, DIR, pid,
the parent's command line). N > 300 takes several sets (their map names never clash: each set has its own tag); maps beyond N
are dropped. The daemon keeps --target sets ready (owner 1 Nov: "use as much compute as you can": 20), --par builds at once, starts
none while the load average is above 24 or /data has under FP_MIN_FREE_GB (10) GB free, removes building/ dirs left by a dead build, and removes taken sets 2 days after their take (the consumer's
DIR holds the maps it plays; taken/ID keeps only a stub with its otf.json). It also expires gate.py's kept fresh reads
(PANEL/TAG/REUSABLE) unclaimed for FP_REUSE_TTL_H (6) hours: REUSABLE -> EXPIRED (atomic) and their maps removed."""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
POOL = "/data/USER/st/freshpool"
XPOOL = "/homes/USER/condor-runs/freshpool"  # 2 Nov: sets built on Condor nodes (tools/lab/freshjobs.py), one .tgz each, unpacked into POOL by the take
PANEL = "/data/USER/st/panel"
REUSE_TTL = float(os.environ.get("FP_REUSE_TTL_H", 6)) * 3600  # gate.py's kept fresh maps, unclaimed this long, are dropped
REPO = "/homes/USER/cambc"
SET_N = 300
# 4 Nov (Tool builder 2; Tool Builder's iteration report: 30+ info reads took every new set while shipchecks 1381/1382 waited 47-52
# min and went INCONCLUSIVE): low-priority takes (info reads, draft probes, gate pre-reads, agents) leave the last RESERVE sets
# for shipcheck / drift reads. FRESH_PRIO=high in a consumer's environment marks it high too.
RESERVE = int(os.environ.get("FRESH_RESERVE", 6))
HIGH = re.compile(r"^(stylepanel:(\d|driftv|sc)|shipcheck|sc\d)")


def high_prio(who):
    return bool(HIGH.match(who or "")) or os.environ.get("FRESH_PRIO") == "high"


def say(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    try:
        with open(f"{POOL}/daemon.log", "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


ROOT = {}  # set id -> the pool holding it


FP_GAMES_FIRST_KEEP = int(os.environ.get("FP_GAMES_FIRST_KEEP", "4"))  # with fewer sets ready than this, build even while local games wait


def ready():
    out = []
    for root in (POOL, XPOOL):
        for d in sorted(glob.glob(f"{root}/ready/*")):
            try:
                out.append((os.path.getmtime(d), os.path.basename(d)))  # a node-built set's name keeps its .tgz until the take
                ROOT[os.path.basename(d)] = root
            except OSError:
                pass
    return [i for _, i in sorted(out)]


def building():
    """Sets being built on nodes now (freshjobs counts anything older than 2 h as dead)."""
    now, out = time.time(), []
    for d in glob.glob(f"{XPOOL}/building/*"):
        try:  # a set that finishes or moves between the glob and here (4 Nov: killed a stratmaps take, then its stylepanel)
            if now - os.path.getmtime(d) < 2 * 3600:
                out.append(d)
        except OSError:
            pass
    return out


def topup():
    """Replace what was taken, in the background: a take never waits for it, and its failure only means fewer ready sets."""
    try:
        subprocess.Popen(["python3", "-I", os.path.join(REPO, "tools/lab/freshjobs.py")], cwd=REPO, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _parent_cmd():
    try:
        return open(f"/proc/{os.getppid()}/cmdline").read().replace("\0", " ")[:200]
    except OSError:
        return "?"


def take(dest, n, who):
    """Move ceil(n / SET_N) pool sets into dest -> the number of maps placed, or 0 when the pool is short (nothing taken)."""
    os.makedirs(f"{POOL}/taken", exist_ok=True)
    topup()
    got, maps, logs = [], [], []
    need = max(1, -(-n // SET_N))
    rd = ready()
    if not high_prio(who) and len(rd) - need < RESERVE:
        return 0  # the reserve is for shipchecks; topup() above has queued node builds
    for sid in rd:
        if len(got) == need:
            break
        try:
            os.makedirs(f"{ROOT[sid]}/taken", exist_ok=True)
            os.rename(f"{ROOT[sid]}/ready/{sid}", f"{ROOT[sid]}/taken/{sid}")  # the claim: atomic, single winner
        except OSError:
            continue
        got.append(sid)
    if len(got) < need:  # not enough: give back what we claimed (still unseen: nothing was read from it)
        for sid in got:
            try:
                os.rename(f"{ROOT[sid]}/taken/{sid}", f"{ROOT[sid]}/ready/{sid}")
            except OSError:
                pass
        return 0
    os.makedirs(dest, exist_ok=True)
    for k, sid in enumerate(got):
        if sid.endswith(".tgz"):  # unpack on this disk, then the pack goes: the home holds a set only while it waits
            pack = f"{ROOT[sid]}/taken/{sid}"
            sid = sid[:-4]
            got[k] = sid
            ROOT[sid] = POOL
            os.makedirs(f"{POOL}/taken/{sid}")
            subprocess.run(["tar", "-xzf", pack, "-C", f"{POOL}/taken/{sid}"], check=True)
            os.remove(pack)
    for sid in got:
        meta = json.load(open(f"{ROOT[sid]}/taken/{sid}/otf.json"))
        for m in meta["maps"]:
            if len(maps) >= n:
                os.remove(f"{ROOT[sid]}/taken/{sid}/{m['name']}.map26a")
                continue
            shutil.move(f"{ROOT[sid]}/taken/{sid}/{m['name']}.map26a", f"{dest}/{m['name']}.map26a")
            maps.append(m)
        logs += meta.get("log", [])
        with open(f"{ROOT[sid]}/taken/{sid}/TAKEN", "w") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {who} -> {dest}\n")
    json.dump(dict(maps=maps, log=logs + [f"freshpool: {len(maps)} maps from pool sets {' '.join(got)}"], tag="+".join(got),
                   pool=got, taken_by=who, made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
              open(f"{dest}/otf.json.part", "w"))
    os.replace(f"{dest}/otf.json.part", f"{dest}/otf.json")
    with open(f"{POOL}/taken.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} who={who} sets={','.join(got)} maps={len(maps)} "
                f"dest={dest} pid={os.getpid()} parent={_parent_cmd()}\n")
    return len(maps)


def start_build(n, weird):
    """Start one stratmaps run at nice 19 into building/ID -> (ID, Popen, start time)."""
    sid = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "_" + os.urandom(2).hex()
    d = f"{POOL}/building/{sid}"
    os.makedirs(d)
    with open(f"{d}/BUILDER", "w") as f:
        f.write(str(os.getpid()))
    lg = open(f"{d}/build.log", "w")
    pr = subprocess.Popen(["nice", "-n", "19", "python3", "-I", "tools/lab/stratmaps.py", d, "--n", str(n), "--weird", str(weird),
                           "--jobs", "4"], cwd=REPO, stdout=lg, stderr=subprocess.STDOUT)
    return sid, pr, time.time()


def finish_build(sid, rc, t0, n):
    d = f"{POOL}/building/{sid}"
    out = open(f"{d}/build.log", errors="replace").read() if os.path.exists(f"{d}/build.log") else ""
    if rc != 0 or not os.path.exists(f"{d}/otf.json"):
        say(f"build {sid} FAILED rc {rc}: {out.strip()[-200:]}")
        shutil.rmtree(d, ignore_errors=True)
        return False
    k = len(json.load(open(f"{d}/otf.json"))["maps"])
    if k < 0.95 * n:
        say(f"build {sid}: only {k} of {n} maps, discarded")
        shutil.rmtree(d, ignore_errors=True)
        return False
    os.remove(f"{d}/BUILDER")
    os.remove(f"{d}/build.log")
    os.makedirs(f"{POOL}/ready", exist_ok=True)
    os.rename(d, f"{POOL}/ready/{sid}")
    say(f"ready {sid}: {k} maps in {time.time() - t0:.0f} s")
    return True


ADOPTED = {}  # building/ID -> adoption time: a build whose daemon was restarted while its stratmaps ran on


def stratmaps_alive(d):
    """True while a stratmaps.py process still writes into building dir d."""
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                c = open(f"/proc/{p}/cmdline", "rb").read().split(b"\0")
            except OSError:
                continue
            if any(x.endswith(b"tools/lab/stratmaps.py") for x in c) and d.encode() in c:
                return True
    return False


def housekeep():
    for d in [x for x in glob.glob(f"{POOL}/building/*") if os.path.isdir(x)]:  # a dead build (its daemon was killed mid-set)
        try:
            os.kill(int(open(f"{d}/BUILDER").read()), 0)
            continue  # its daemon is alive
        except (OSError, ValueError):
            pass
        sid = os.path.basename(d)
        if stratmaps_alive(d):  # 4 Nov: a daemon restart adopts the builds still running instead of deleting them under stratmaps
            if sid not in ADOPTED:
                ADOPTED[sid] = time.time()
                say(f"adopted running build {sid}")
            continue
        if sid in ADOPTED:
            finish_build(sid, 0, ADOPTED.pop(sid), SET_N)
            continue
        shutil.rmtree(d, ignore_errors=True)
        say(f"removed dead build {os.path.basename(d)}")
    for r in glob.glob(f"{PANEL}/*/REUSABLE"):  # 1 Nov: gate.py keeps a complete fresh read's maps for shipcheck to adopt
        try:
            if time.time() - os.path.getmtime(r) < REUSE_TTL:
                continue
            d = os.path.dirname(r)
            os.rename(r, f"{d}/EXPIRED")  # the same atomic claim stylepanel --reuse-fresh uses: never both
        except OSError:
            continue
        n = 0
        for f in glob.glob(f"{d}/*.map26a"):
            os.remove(f)
            n += 1
        say(f"expired the unclaimed fresh read {os.path.basename(d)} ({n} maps removed; its sp/fp records stay)")
    for d in glob.glob(f"{POOL}/taken/*"):
        t = f"{d}/TAKEN"
        if os.path.exists(t) and time.time() - os.path.getmtime(t) > 2 * 86400:
            for f in glob.glob(f"{d}/*.map26a"):
                os.remove(f)


def disk_pct():
    st = os.statvfs("/data")
    return 100 * (1 - st.f_bavail / st.f_blocks)


FP_MIN_FREE_GB = float(os.environ.get("FP_MIN_FREE_GB", 10))  # 5 Nov (TB2): /data holds root's cachefilesd cache (/data/.fscache, ~215 GB, keeps free space at 3-10%), so % used reads 90-97% whatever we store; guard on absolute free space


def disk_free_gb():
    st = os.statvfs("/data")
    return st.f_bavail * st.f_frsize / 1e9


def status():
    rd = ready()
    bd = glob.glob(f"{POOL}/building/*")
    print(f"ready {len(rd)}: {' '.join(rd)}\nbuilding {len(bd)}: {' '.join(map(os.path.basename, bd))}")
    try:
        lines = open(f"{POOL}/taken.log").read().splitlines()
        print(f"taken {len(lines)}; last:\n  " + "\n  ".join(x[:200] for x in lines[-5:]))
    except OSError:
        print("taken 0")
    try:
        pid = int(open(f"{POOL}/daemon.pid").read())
        os.kill(pid, 0)
        print(f"daemon pid {pid} alive")
    except (OSError, ValueError):
        print("daemon NOT running")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--target", type=int, default=20)
    ap.add_argument("--par", type=int, default=3, help="concurrent builds (each stratmaps --jobs 4 at nice 19)")
    ap.add_argument("--n", type=int, default=SET_N)
    ap.add_argument("--weird", type=float, default=None, help="default: stratmaps.WEIRD (0.50)")
    a = ap.parse_args()
    if a.weird is None:
        import stratmaps
        a.weird = stratmaps.WEIRD
    for s in ("ready", "building", "taken"):
        os.makedirs(f"{POOL}/{s}", exist_ok=True)
    if a.status or not a.loop:
        status()
        return 0
    with open(f"{POOL}/daemon.pid", "w") as f:
        f.write(str(os.getpid()))
    say(f"daemon start: target {a.target} sets of {a.n} maps, weird {a.weird}, {a.par} builds at once")
    fails, run = 0, {}
    while True:
        try:  # 11 Nov: the pid file went stale (577020 while 1403213 ran) and every --status said "daemon NOT running"
            if open(f"{POOL}/daemon.pid").read().strip() != str(os.getpid()):
                open(f"{POOL}/daemon.pid", "w").write(str(os.getpid()))
        except OSError:
            pass
        for sid, (pr, t0) in list(run.items()):
            if pr.poll() is not None:
                del run[sid]
                fails = 0 if finish_build(sid, pr.returncode, t0, a.n) else fails + 1
        if fails >= 3:
            say("3 failed builds in a row: pausing 10 min")
            time.sleep(600)
            fails = 0
        housekeep()
        la = os.getloadavg()[0]
        try:  # owner 8 Nov: Condor whenever it beats this machine: with pilots up the sets are built on them (freshjobs); this machine stays the fallback
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
            import pilotd
            pilots = len(pilotd.alive_pilots()) >= int(os.environ.get("FRESH_PILOT_MIN", 4))
        except Exception:  # noqa: BLE001
            pilots = False
        if pilots and not run:
            if len(ready()) + len(building()) < a.target:
                subprocess.Popen(["python3", "-I", os.path.join(REPO, "tools/lab/freshjobs.py")], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(30)
            continue
        try:  # 5 Nov HOST: three set builds (12 workers) pushed load past cxe's 24 cap, so 210 local games waited on 2 slots; games first
            cxe_wait = sum(1 for f in os.listdir("/data/USER/st/cxe/slots/wait") if not f.startswith("."))
        except OSError:
            cxe_wait = 0
        if cxe_wait and len(ready()) >= FP_GAMES_FIRST_KEEP:
            time.sleep(30)
            continue
        while (len(ready()) + len(run) + len(ADOPTED) < a.target and len(run) + len(ADOPTED) < a.par and la < 24 and disk_free_gb() >= FP_MIN_FREE_GB):
            sid, pr, t0 = start_build(a.n, a.weird)
            run[sid] = (pr, t0)
        time.sleep(5 if run else 30)


if __name__ == "__main__":
    sys.exit(main())
