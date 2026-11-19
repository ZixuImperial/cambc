#!/usr/bin/env python3
"""hostpilots: run Condor-pilot workers directly on other DoC machines (HOST, HOST, ...) when pilot work is queued (Tool builder,
6 Nov; owner: faster tests -> more tests -> more certainty). A pilot only needs /homes (the queue, stage dirs, cxe runtime and node scripts
live there), so any machine can serve the same queue. Measured 6 Nov ~12:00Z: HOST load 0.1 (16 cores, no other user), HOST load 6-8
(16 cores, one other user ~7 cores), HOST load 23-27.

usage: python3 -I tools/lab/hostpilots.py --loop [--max N] [--cpus C] [--load L] [--var-mb M] [--allow U1,U2|'*'] [--stop-load L]  (run ON the helper machine, detached)
       python3 -I tools/lab/hostpilots.py --start HOST [--max N] ...                     (from any machine: starts the loop on HOST by ssh)
       python3 -I tools/lab/hostpilots.py --status                                        (every helper's loop and pilots, by ssh)
       python3 -I tools/lab/hostpilots.py --stop HOST
The loop, every 20 s: if any other user is logged in, or the load is >= 16 (HOSTPILOT_STOP_LOAD), it stops its pilots (SIGTERM: each
gives its item back) and starts none (owner 7 Nov: "if no1 is using HOST use it"). Otherwise, while pilot items are queued, pilots on this machine < --max (default 2), the 1-min load is below --load (default 12)
and /var has >= --var-mb free (default 700: every program start is audit-logged there; HOST's /var was 97% full), it starts one pilot
(nice 19, PILOT_SLOT_CPUS=--cpus (default 6): each plays cpus-1 games at once, so 2 x 6 is ~10 cores). Pilots leave by themselves after pilotd's idle time.
State: /homes/USER/condor-runs/hostpilots/HOST.{pid,log}. Off for all hosts: touch /data/USER/st/bq/hostpilots_OFF (read on HOST
via /homes copy: /homes/USER/condor-runs/hostpilots/OFF)."""
import os
import socket
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
D = "/homes/USER/condor-runs/hostpilots"
Q = "/homes/USER/condor-runs/pilotq"
HOST = socket.gethostname().split(".")[0]
HOSTS = ("HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST", "HOST")  # owner 7 Nov: idle maples, maples only rv622 uses, HOST (owner there)
STOP_LOAD = float(os.environ.get("HOSTPILOT_STOP_LOAD", 16))  # 7 Nov: pilots stop when the load goes over this (ours ~12 at 2 x 7 cpus)


def opt(a, k, d):
    return type(d)(a[a.index(k) + 1]) if k in a else d


def log(s):
    with open(f"{D}/{HOST}.log", "a") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + s + "\n")


def mine():
    """pids of pilots this loop started that are still running"""
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                c = open(f"/proc/{p}/cmdline", "rb").read().split(b"\0")
                e = open(f"/proc/{p}/environ", "rb").read()
            except OSError:
                continue
            if any(x.endswith(b"pilotd.py") for x in c) and b"--pilot" in c and b"HOSTPILOT=1" in e:
                out.append(int(p))
    return out


def loop(a):
    mx, ld, vm, cpus = opt(a, "--max", 2), opt(a, "--load", 12.0), opt(a, "--var-mb", 700), opt(a, "--cpus", 6)
    stop_load = opt(a, "--stop-load", STOP_LOAD)
    ncpu = os.cpu_count() or 8
    if "--load" not in a:  # 12 Nov (lab machines, 24+ cores): thresholds follow the core count unless given
        ld = max(ld, 0.6 * ncpu)
    if "--stop-load" not in a:
        stop_load = max(stop_load, 0.9 * ncpu)
    # users who may be logged in: '*' any (owner 7 Nov: HOST, where the owner sits); rv622 (owner: machines only rv622 uses)
    allow = set(filter(None, opt(a, "--allow", "").split(",")))
    # 12 Nov ~15:0xZ (owner, choosing option 2 of "free computers outside labs": "do 2"): with other users logged in, keep up to --shared N
    # (default 1) pilots of --shared-cpus (2) cores at nice 19 instead of standing down; the load rules still apply (--load to start,
    # --stop-load stops everything), so a busy user's machine is left alone. --shared 0 restores the old stand-down.
    shared, shared_cpus = opt(a, "--shared", 0), opt(a, "--shared-cpus", 2)  # owner 12 Nov ~15:1xZ: "do not do that": off (stand down as before)
    os.makedirs(D, exist_ok=True)
    open(f"{D}/{HOST}.pid", "w").write(f"{os.getpid()}\n")
    try:  # 12 Nov 20:3xZ (b2347: birnhorn's Xeon E5-2643 v1 has no AVX2: "Illegal instruction" in every cxe game): no loop on such a CPU
        flags = set(next((ln for ln in open("/proc/cpuinfo") if ln.startswith("flags")), "").split())
        miss = [x for x in os.environ.get("PILOT_CPU_FLAGS", "avx2 fma bmi2").split() if flags and x not in flags]
    except OSError:
        miss = []
    if miss:
        log(f"no helper here: CPU lacks {' '.join(miss)} (native cxe builds die with Illegal instruction); loop ends")
        return
    log(f"start pid {os.getpid()}: max {mx} pilots x {cpus} cpus, load < {ld}, /var >= {vm} MB, stop on any other user"
        + (f" than {','.join(sorted(allow))}" if allow else "") + f" or load >= {stop_load:g}")
    last = ""
    while True:
        if os.path.exists(f"{D}/OFF") or os.path.exists(f"{D}/{HOST}.OFF"):
            log("OFF file: loop ends (running pilots finish their items)")
            return
        try:
            queued = sum(1 for n in os.listdir(f"{Q}/queue") if not n.startswith("."))
        except OSError:
            queued = 0
        st = os.statvfs("/var")
        var_mb = st.f_bavail * st.f_frsize // 2 ** 20
        # 12 Nov (TB: lab pilots exited at once, "/tmp low: 1945 MB free < 2000", and this loop restarted them every 20 s: no work, a home
        # log file per restart): pilots here need HP_TMP_MIN_MB (1000) free in /tmp, and none is started below it
        tmp_min = int(os.environ.get("HP_TMP_MIN_MB", 1000))
        try:
            st2 = os.statvfs("/var/tmp")
            tmp_mb = st2.f_bavail * st2.f_frsize // 2 ** 20
        except OSError:
            tmp_mb = 10 ** 6
        load = float(open("/proc/loadavg").read().split()[0])
        run = mine()
        others = sorted({ln.split()[0] for ln in subprocess.run(["who"], capture_output=True, text=True).stdout.splitlines()
                         if ln.split() and ln.split()[0] != os.environ.get("USER", "USER") and ln.split()[0] not in allow and "*" not in allow})
        if others and os.environ.get("HP_SSH_SHARE", "1") != "0":
            # 12 Nov ~15:4xZ (owner: "yes just use as much compute if the others are by direct-ssh"): only a person AT the machine
            # (a seat/tty/X login) makes this loop stand down; users whose every session is remote ssh (and their jobs) share the
            # machine. The load rules still apply (a busy machine starts nothing, --stop-load stops ours).
            at_desk = set()
            for ln in subprocess.run(["who"], capture_output=True, text=True).stdout.splitlines():
                w = ln.split()
                if len(w) < 2:
                    continue
                origin = ln[ln.rfind("(") + 1:ln.rfind(")")] if "(" in ln else ""
                if w[1].startswith(("seat", "tty", ":")) or origin.startswith(":") or not origin:
                    at_desk.add(w[0])
            others = [u for u in others if u in at_desk]
        if others and os.environ.get("HP_SHARE_BC", "1") != "0":
            # 12 Nov ~15:3xZ (owner: "If someone is running battlecode games across the lab machines that isn't us, share with them"):
            # a logged-in user whose processes here include the Battlecode engine (cambc / cambc-wasm) is another team's test farm,
            # not a person at the desk: ours run beside it. Anyone else still makes this loop stand down (owner 12 Nov: no sharing).
            try:
                ps = subprocess.run(["ps", "-eo", "user:32,comm"], capture_output=True, text=True, timeout=20).stdout.splitlines()
                bc = {x.split()[0] for x in ps if len(x.split()) > 1 and x.split()[1].startswith("cambc")}
                others = [u for u in others if u not in bc]
            except (OSError, subprocess.SubprocessError):
                pass
        if os.environ.get("HP_FOREIGN_LOAD", "1") != "0":
            # 12 Nov ~18:5xZ (TB; owner: "share with them" / "use as much compute if the others are by direct-ssh"): lab load 12-16 of 16
            # cores was other users' remote farms (rv622 cambc-wasm, pb825 python3), so no helper started. CPU of processes owned by users
            # who are NOT at the desk (remote ssh jobs, root excluded) leaves the load rules; ours run at nice 19, so the CFS gives their
            # nice-0 jobs the CPU first and ours take only the idle cycles. A person at the desk still counts in full.
            try:
                desk = set()
                for ln in subprocess.run(["who"], capture_output=True, text=True).stdout.splitlines():
                    w = ln.split()
                    if len(w) >= 2:
                        origin = ln[ln.rfind("(") + 1:ln.rfind(")")] if "(" in ln else ""
                        if w[1].startswith(("seat", "tty", ":")) or origin.startswith(":") or not origin:
                            desk.add(w[0])
                me_u = os.environ.get("USER", "USER")
                fl = 0.0
                for x in subprocess.run(["ps", "-eo", "user:32,pcpu"], capture_output=True, text=True, timeout=20).stdout.splitlines()[1:]:
                    w = x.split()
                    if len(w) == 2 and w[0] not in (me_u, "root") and w[0] not in desk:
                        c = float(w[1])
                        if c >= 20:
                            fl += c / 100
                if fl > 0.5:
                    load = max(0.0, load - min(fl, load))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        cap, ccpu = mx, cpus
        if others and load < stop_load and shared > 0:  # owner 12 Nov: share the machine with one small low-priority pilot
            cap, ccpu = shared, shared_cpus
            for pid in run[shared:]:
                try:
                    os.kill(pid, 15)  # extras give their items back
                except OSError:
                    pass
            run = run[:shared]
            others = []
        if others or load >= stop_load:  # owner 7 Nov: only while nobody else uses the machine; leave at once if someone logs in
            for pid in run:
                try:
                    os.kill(pid, 15)  # a pilot gives its item back on SIGTERM
                except OSError:
                    pass
            why = f"stand down: {'users ' + ','.join(others) if others else f'load {load:.1f} >= {stop_load:g}'} ({len(run)} pilot(s) stopped)"
            if why != last:
                log(why)
                last = why
            time.sleep(20)
            continue
        try:  # 12 Nov ~20:5xZ (Coordinator): no new helper pilot while the home holds >= PILOT_HOME_STOP (58,500) files (hard quota 61k)
            if not hasattr(loop, "_hq") or time.time() - loop._hq[0] > 120:
                q_ = subprocess.run(["python3", "-I", f"{REPO}/tools/lab/homequota.py"], capture_output=True, text=True, timeout=30).stdout.split()
                loop._hq = (time.time(), int(q_[0]) if q_ else 0)
            home_hi = loop._hq[1] >= int(os.environ.get("PILOT_HOME_STOP", 58800))
        except Exception:  # noqa: BLE001
            home_hi = False
        why = ("no work" if not queued else f"home {loop._hq[1]} files" if home_hi else f"/var {var_mb} MB" if var_mb < vm else f"/tmp {tmp_mb} MB" if tmp_mb < tmp_min else f"load {load:.1f}" if load >= ld
               else f"{len(run)} pilots (max{' shared' if cap != mx else ''})" if len(run) >= cap else "")
        if not why:
            env = dict(os.environ, HOSTPILOT="1", PILOT_JOB=f"{HOST}.{int(time.time())}", PILOT_SLOT_CPUS=str(ccpu), PILOT_TMP_MIN_MB=str(tmp_min))
            subprocess.Popen(["nice", "-n", "19", sys.executable, "-I", f"{REPO}/tools/lab/pilotd.py", "--pilot"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, cwd="/tmp")
            why = f"started a pilot ({len(run) + 1} running, {queued} queued, load {load:.1f}, /var {var_mb} MB)"
        if why != last:
            log(why)
            last = why
        time.sleep(20)


def ssh(h, cmd):
    return subprocess.run(["timeout", "30", "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", h, cmd], capture_output=True, text=True)


def main():
    a = sys.argv[1:]
    if "--loop" in a:
        return loop(a)
    if "--start" in a:
        h = a[a.index("--start") + 1]
        import shlex  # 7 Nov: an unquoted '*' was globbed by the remote shell
        extra = " ".join(f"{k} {shlex.quote(str(opt(a, k, '')))}" for k in ("--max", "--load", "--var-mb", "--cpus", "--allow", "--stop-load") if k in a)
        off = f"{D}/{h}.OFF"
        if os.path.exists(off):  # 9 Nov: --stop then --start left the OFF file, and the new loop read it and quit at once (6 maples idle 40 min)
            time.sleep(25)  # the old loop checks every 20 s: let it see the OFF file and end first
            os.remove(off)
        r = ssh(h, f"cd /tmp && setsid nohup python3 -I {REPO}/tools/lab/hostpilots.py --loop {extra} > /dev/null 2>&1 < /dev/null & echo started")
        print(h, (r.stdout + r.stderr).strip()[-200:])
        return 0
    if "--stop" in a:
        h = a[a.index("--stop") + 1]
        open(f"{D}/{h}.OFF", "w").close()
        print(f"{h}: OFF file written; its loop ends within 20 s (remove {D}/{h}.OFF to allow a restart)")
        return 0
    if "--status" in a:
        for h in HOSTS:
            r = ssh(h, f"p=$(cat {D}/{h}.pid 2>/dev/null); [ -n \"$p\" ] && [ -d /proc/$p ] && echo loop $p || echo 'no loop'; "
                       f"grep -l HOSTPILOT=1 /proc/[0-9]*/environ 2>/dev/null | wc -l; tail -1 {D}/{h}.log 2>/dev/null; cut -d' ' -f1 /proc/loadavg")
            print(h, " | ".join((r.stdout or r.stderr).split("\n")).strip())
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
