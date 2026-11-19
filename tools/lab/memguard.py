#!/usr/bin/env python3
"""memguard: stop the biggest runaway job before the kernel's OOM killer does (Tool Builder, 9 Nov; owner: "make sure it doesn't crash again").
9 Nov 10:44:05Z the kernel OOM-killed the VS Code app (its memory group peaked at 39.4 GB on this 59 GB machine): every Claude session and every
subagent and command they ran died at once. The kernel picks inside the biggest group, so one heavy job started from a session took them all.

Every POLL (2) s it reads MemAvailable. Under WARN_GB (8) it logs the top processes once a minute. Under LOW_GB (5) it sends SIGTERM to the
largest of OUR processes that is a JOB (python3, cxe/engine hosts, clang/wasm tools, cambc), never VS Code, Claude, a shell, ssh, the desktop or
a core daemon (CORE below), and only when its RSS is at least MIN_GB (1). SIGKILL follows after 10 s if it is still alive and memory is still
low. Each kill is logged with its command line, RSS and cgroup, and written to ALARM (healthwatch/since show it).
usage: python3 -I tools/lab/memguard.py [--loop] [--dry]      (unit nova-memguard; --dry logs what it would stop)
Env: MG_LOW_GB, MG_WARN_GB, MG_MIN_GB, MG_POLL. Log /data/zw4424/st/memguard/log; last kill /data/zw4424/st/memguard/ALARM."""
import os
import signal
import subprocess
import sys
import time

D = "/data/zw4424/st/memguard"
LOG, ALARM = f"{D}/log", f"{D}/ALARM"
LOW = float(os.environ.get("MG_LOW_GB", 5)) * 2 ** 20  # kB
WARN = float(os.environ.get("MG_WARN_GB", 8)) * 2 ** 20
MINRSS = float(os.environ.get("MG_MIN_GB", 1)) * 2 ** 20
POLL = float(os.environ.get("MG_POLL", 2))
UID = os.getuid()
LOAD_HI = float(os.environ.get("MG_LOAD_HI", 3 * (os.cpu_count() or 16)))
JOB = ("python", "cxe", "clang", "wasm", "cambc", "w2c", "node_modules/.bin", "ld.lld", "readmany", "condab")
NEVER = ("/usr/share/code", "vscode", "claude", "native-binary", "bash", "/bin/sh", "sshd", "gnome", "Xorg", "systemd", "dbus", "firefox",
         "cpptools", "pulseaudio", "pipewire")
CORE = ("shipwatch.py", "armq.py", "pilotd.py", "healthwatch.py", "livepipe", "quotaguard.py", "freshpool.py", "critgame.py auto",
        "ladderclimb.py loop", "memguard.py", "draftstock_fill")


def say(s):
    os.makedirs(D, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + s + "\n")


def avail_kb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1])
    return 1 << 40


def procs():
    """[(rss_kb, pid, cmdline, cgroup)] of our processes"""
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            st = os.stat(f"/proc/{p}")
            if st.st_uid != UID:
                continue
            cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
            rss = 0
            for ln in open(f"/proc/{p}/status"):
                if ln.startswith("VmRSS:"):
                    rss = int(ln.split()[1])
                    break
            cg = open(f"/proc/{p}/cgroup").read().strip().split("::")[-1]
            out.append((rss, int(p), cmd, cg))
        except (OSError, ValueError):
            continue
    return sorted(out, reverse=True)


def killable(cmd):
    c = cmd.lower()
    if not cmd or any(x.lower() in c for x in NEVER) or any(x.lower() in c for x in CORE):
        return False
    return any(x in c for x in JOB)


CORE_UNITS = ("nova-shipwatch", "nova-armq", "nova-pilotd", "nova-healthwatch", "nova-memguard", "nova-livepipe", "nova-quotaguard",
              "nova-hostpilots")  # hostpilots' pilots stand down by themselves above their stop load
UNIT_CORES = float(os.environ.get("MG_UNIT_CORES", 6))   # a job unit above this many cores while the load is high gets capped
UNIT_QUOTA = os.environ.get("MG_UNIT_QUOTA", "400%")    # to this (4 cores); runtime only: gone when the unit ends


def throttle_units(state, l1):
    """9 Nov 15:58Z (load 125 for 10 min: one agent's local `cambc400 run-batch --jobs 10`; renicing to 19 does not stop one job taking every
    core): each call (every 60 s) measures every nova-* job unit's CPU use since the last call; while the 1-min load is above LOAD_HI, a unit
    using more than UNIT_CORES cores gets CPUQuota=UNIT_QUOTA (set-property --runtime). The job keeps running, only slower; core daemons
    (whose units hold the shipchecks) are never capped."""
    prev, now_t = state.setdefault("cpu", {}), time.time()
    try:
        out = subprocess.run(["systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-legend", "nova-*"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for ln in out.splitlines():
        u = ln.split()[0].lstrip("\u25cf ").strip() if ln.split() else ""
        u = u if u.endswith(".service") else next((x for x in ln.split() if x.endswith(".service")), "")
        if not u or u.rsplit(".", 1)[0] in CORE_UNITS:
            continue
        try:
            v = subprocess.run(["systemctl", "--user", "show", u, "-p", "CPUUsageNSec", "-p", "CPUQuotaPerSecUSec", "--value"],
                               capture_output=True, text=True, timeout=10).stdout.split()
            ns = int(v[0])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            continue
        p = prev.get(u)
        prev[u] = (ns, now_t)
        if not p or now_t <= p[1]:
            continue
        cores = (ns - p[0]) / 1e9 / (now_t - p[1])
        if l1 > LOAD_HI and cores > UNIT_CORES and (len(v) < 2 or v[1] == "infinity"):
            subprocess.run(["systemctl", "--user", "set-property", "--runtime", u, f"CPUQuota={UNIT_QUOTA}"], capture_output=True, timeout=20)
            say(f"load {l1:.0f} > {LOAD_HI:.0f}: {u} used {cores:.1f} cores: CPUQuota={UNIT_QUOTA} until it ends")
    for u in [k for k, (_, ts) in prev.items() if now_t - ts > 600]:
        prev.pop(u)


def guard_sessions(state):
    """9 Nov (owner: load must never crash it either): every 60 s, (1) VS Code's scopes (every Claude session lives there) get CPU and IO weight
    1000 v the default 100 of the job units, so jobs slow down before the sessions do; (2) when the 1-min load passes LOAD_HI (3 x cores), the
    5 jobs using the most CPU are reniced to 19. Nothing is stopped or killed for load."""
    if time.time() - state.get("sess", 0) < 60:
        return
    state["sess"] = time.time()
    try:
        out = subprocess.run(["systemctl", "--user", "list-units", "--type=scope", "--no-legend"], capture_output=True, text=True, timeout=20).stdout
        for ln in out.splitlines():
            u = ln.split()[0] if ln.split() else ""
            if "VSCode" in u:
                w = subprocess.run(["systemctl", "--user", "show", u, "-p", "CPUWeight", "--value"], capture_output=True, text=True, timeout=10).stdout.strip()
                if w != "1000":
                    subprocess.run(["systemctl", "--user", "set-property", "--runtime", u, "CPUWeight=1000", "IOWeight=1000"], capture_output=True, timeout=20)
                    say(f"VS Code scope {u}: CPU/IO weight set to 1000 (was {w or 'default'})")
    except (OSError, subprocess.SubprocessError):
        pass
    l1 = os.getloadavg()[0]
    throttle_units(state, l1)
    if l1 > LOAD_HI:
        top = []
        for p in os.listdir("/proc"):
            if not p.isdigit():
                continue
            try:
                if os.stat(f"/proc/{p}").st_uid != UID:
                    continue
                cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
                f = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
                top.append((int(f[11]) + int(f[12]), int(p), cmd))
            except (OSError, ValueError, IndexError):
                continue
        hit = [x for x in sorted(top, reverse=True) if killable(x[2])][:5]
        for _, pid, cmd in hit:
            try:
                os.setpriority(os.PRIO_PROCESS, pid, 19)
            except OSError:
                pass
        if hit:
            say(f"load {l1:.0f} > {LOAD_HI:.0f}: reniced to 19: " + "; ".join(f"{pid} {cmd[:60]}" for _, pid, cmd in hit))


def step(dry, state):
    guard_sessions(state)
    a = avail_kb()
    if a >= WARN:
        return
    ps = procs()
    if time.time() - state.get("warned", 0) > 60:
        state["warned"] = time.time()
        say(f"available {a / 2 ** 20:.1f} GB < {WARN / 2 ** 20:.0f}: top " + "; ".join(f"{r / 2 ** 20:.1f}G pid {pid} {cmd[:80]}" for r, pid, cmd, _ in ps[:4]))
    if a >= LOW:
        return
    cand = [(r, pid, cmd, cg) for r, pid, cmd, cg in ps if r >= MINRSS and killable(cmd)]
    if not cand:
        if time.time() - state.get("nocand", 0) > 60:
            state["nocand"] = time.time()
            say(f"!! available {a / 2 ** 20:.1f} GB < {LOW / 2 ** 20:.0f} but no job of {MINRSS / 2 ** 20:.0f}+ GB to stop (top: "
                + "; ".join(f"{r / 2 ** 20:.1f}G {cmd[:60]}" for r, _, cmd, _ in ps[:3]) + ")")
        return
    r, pid, cmd, cg = cand[0]
    msg = f"available {a / 2 ** 20:.1f} GB < {LOW / 2 ** 20:.0f}: {'WOULD STOP' if dry else 'stopping'} pid {pid} ({r / 2 ** 20:.1f} GB RSS, cgroup {cg}): {cmd[:300]}"
    say(msg)
    if dry:
        return
    open(ALARM, "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg + "\n")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        time.sleep(0.5)
        if not os.path.exists(f"/proc/{pid}"):
            say(f"pid {pid} gone after SIGTERM")
            return
    if avail_kb() < LOW:
        try:
            os.kill(pid, signal.SIGKILL)
            say(f"pid {pid} SIGKILL (still alive, memory still low)")
        except OSError:
            pass


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    state = {}
    if "--loop" not in a:
        step(dry, state)
        print(open(LOG).read().splitlines()[-1] if os.path.exists(LOG) else "memguard: nothing logged")
        return 0
    say(f"start (low {LOW / 2 ** 20:.0f} GB, warn {WARN / 2 ** 20:.0f} GB, poll {POLL} s{', DRY' if dry else ''})")
    while True:
        try:
            step(dry, state)
        except Exception as e:  # noqa: BLE001  the guard must keep running
            say(f"!! step: {e!r}"[:300])
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
