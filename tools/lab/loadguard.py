#!/usr/bin/env python3
"""loadguard: let the load run higher without the machine or VS Code going down (Tool Builder, 10 Nov; owner: "allow the load to go up
and make sure to keep the load safe" and "make sure the computer doesn't crash").

What crashed us before: 4 Nov load 48-150 starved VS Code (HOST rebooted); 9 Nov the kernel OOM killer picked VS Code (39 GB). VS Code
(app-com.microsoft.VSCode-*.scope) and our units (nova-*.service) are siblings in the user manager's app.slice, so cgroup weights decide
who gets the CPU under contention, whatever the load number says. Every PROTECT_EVERY (120) s:
  - CPUWeight: nova-* units 40, VS Code and tmux session scopes 400 (default 100): VS Code keeps ~10x a batch unit's share when busy.
  - oom_score_adj 500 on every process of a nova-* unit except the core daemons' main processes (healthwatch, memguard, varguard,
    loadguard, pilotd, armq, shipwatch, quotaguard, livepipe): if memory still runs out (memguard acts first, under 5 GB), the kernel
    kills a batch job, not VS Code. Children inherit it.
Every POLL (15) s, the valve (limits from tools/lab/loadlim.py, file bq/load_limits):
  - load1 > pause_load and cpu pressure (some avg10) > pause_psi: SIGSTOP the deferrable units (DEFER below).
  - load1 > hold_load and the same pressure: also the build-agent units (nova-b1*).
  - resume what loadguard paused once load1 < resume_load and pressure < resume_psi (50) for 4 polls running; never a unit varguard holds.
Logs /data/USER/st/bq/loadguard.log; ALARM lines in bq/loadguard.alarm while anything is paused (healthwatch-style). State
bq/loadguard.state. Off: touch /data/USER/st/bq/loadguard_OFF (the loop resumes what it paused, then idles).
usage: python3 -I tools/lab/loadguard.py [--once] [--dry]"""
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadlim  # noqa: E402

BQ = "/data/USER/st/bq"
LOG, STATE, ALARM, OFF = f"{BQ}/loadguard.log", f"{BQ}/loadguard.state", f"{BQ}/loadguard.alarm", f"{BQ}/loadguard_OFF"
VARSTATE = f"{BQ}/varguard.state"
POLL, PROTECT_EVERY, CALM_POLLS = 15, 120, 4
DEFER = [  # 10 Nov ~22:55Z (owner: use the ladder quota fully; Coordinator): ladder climb lanes wait on the platform, not the CPU: never paused
         "nova-triagefill",  # 11 Nov (Builder): nova-freshpool off this list: its sets build on the pilots, and a paused pool sent agents to generate locally "nova-losstable", "nova-draftstock", "nova-critgame",
         "nova-autoclean"]
HOLD = ["nova-b1"]
CORE = {"nova-healthwatch", "nova-memguard", "nova-varguard", "nova-loadguard", "nova-pilotd", "nova-armq", "nova-shipwatch",
        "nova-quotaguard", "nova-livepipe"}
W_BATCH, W_UI, OOM_ADJ = 40, 400, 500
DRY = "--dry" in sys.argv
CG = "/sys/fs/cgroup"


def say(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}{' [DRY]' if DRY else ''} {m}"
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sctl(*a):
    return subprocess.run(["systemctl", "--user", *a], capture_output=True, text=True, timeout=60)


def running(prefixes):
    r = sctl("list-units", "nova-*", "--no-legend", "--state=running", "--plain")
    us = [ln.split()[0] for ln in r.stdout.splitlines() if ln.split()]
    return [u for u in us if any(u.startswith(p) for p in prefixes)] if prefixes else us


def pressure():
    try:
        for ln in open("/proc/pressure/cpu"):
            if ln.startswith("some"):
                return float(ln.split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"paused": {}, "calm": 0}


def var_held():
    try:
        return {u for us in json.load(open(VARSTATE)).get("paused", {}).values() for u in us}
    except (OSError, ValueError, AttributeError):
        return set()


def protect():
    """CPU weights and OOM scores; only writes what differs, so it costs a few systemctl show calls."""
    changed = []
    for u in running(None):
        base = u.rsplit(".", 1)[0]
        want = 100 if base in CORE else W_BATCH  # core daemons keep the default share: memguard must act under pressure
        cur = sctl("show", u, "-p", "CPUWeight", "--value").stdout.strip()
        if cur not in (str(want), "[not set]" if want == 100 else "-"):
            if not DRY:
                sctl("set-property", "--runtime", u, f"CPUWeight={want}")
            changed.append(f"{u} CPUWeight {cur or '?'}->{want}")
        main = sctl("show", u, "-p", "MainPID", "--value").stdout.strip() if base in CORE else ""
        cg = sctl("show", u, "-p", "ControlGroup", "--value").stdout.strip()
        n = 0
        for procs in glob.glob(f"{CG}{cg}/**/cgroup.procs", recursive=True) if cg else []:
            try:
                pids = open(procs).read().split()
            except OSError:
                continue
            for p in pids:
                if p == main:
                    continue
                try:
                    f = f"/proc/{p}/oom_score_adj"
                    if int(open(f).read()) < OOM_ADJ:
                        if not DRY:
                            open(f, "w").write(str(OOM_ADJ))
                        n += 1
                except (OSError, ValueError):
                    pass
        if n:
            changed.append(f"{u} oom_score_adj {OOM_ADJ} on {n} pids")
    r = sctl("list-units", "--type=scope", "--no-legend", "--plain")
    for ln in r.stdout.splitlines():
        s = ln.split()[0] if ln.split() else ""
        if s.startswith("app-com.microsoft.VSCode") or s.startswith("tmux-spawn"):
            cur = sctl("show", s, "-p", "CPUWeight", "--value").stdout.strip()
            if not (cur.isdigit() and int(cur) >= W_UI):  # only ever raise (VS Code was already given 1000)
                if not DRY:
                    sctl("set-property", "--runtime", s, f"CPUWeight={W_UI}")
                changed.append(f"{s} CPUWeight {cur or '?'}->{W_UI}")
    if changed:
        say(f"protect ({len(changed)} changes): " + "; ".join(changed)[:3000])


def sig(units, s):
    for u in units:
        if not DRY:
            sctl("kill", "-s", s, u)


def write_alarm(st, l1, psi):
    held = [u for us in st["paused"].values() for u in us]
    txt = (f"ALARM loadguard: {len(held)} units paused for load (1-min {l1:.0f}, cpu pressure {psi:.0f}%): {' '.join(held)[:300]}\n"
           if held else "")
    if not DRY:
        open(ALARM, "w").write(txt)


def step(st):
    l1 = os.getloadavg()[0]
    psi = pressure()
    lim = {k: loadlim.get(k) for k in ("pause_load", "hold_load", "pause_psi", "resume_load")}
    off = os.path.exists(OFF)
    hot = psi > lim["pause_psi"] and not off
    for name, prefixes, thr in (("defer", DEFER, lim["pause_load"]), ("hold", HOLD, lim["hold_load"])):
        if hot and l1 > thr:
            new = [u for u in running(prefixes) if u not in st["paused"].get(name, [])]
            if new:
                sig(new, "SIGSTOP")
                st["paused"][name] = st["paused"].get(name, []) + new
                say(f"PAUSE {name}: load {l1:.1f} > {thr:g}, cpu pressure {psi:.0f}% > {lim['pause_psi']:g}: {' '.join(new)}")
            st["calm"] = 0
    # 10 Nov ~22:50Z (Coordinator: 12 lanes stayed paused at load ~40, pressure ~46%): resume below resume_load with pressure under
    # resume_psi (bq/load_limits, default 50); pause_psi/2 (30) is never reached on 16 cores with 24-30 shipchecks
    calm = off or (l1 < lim["resume_load"] and psi < float(loadlim.get("resume_psi") or 50))
    st["calm"] = st.get("calm", 0) + 1 if calm else 0
    if st["paused"] and (off or st["calm"] >= CALM_POLLS):
        vh = var_held()
        for name in ("hold", "defer"):
            us = st["paused"].pop(name, [])
            go = [u for u in us if u not in vh]
            sig(go, "SIGCONT")
            if go:
                say(f"RESUME {name}: load {l1:.1f}, cpu pressure {psi:.0f}%{' (loadguard_OFF)' if off else ''}: {' '.join(go)}"
                    + (f"; left to varguard: {' '.join(sorted(set(us) - set(go)))}" if set(us) - set(go) else ""))
    write_alarm(st, l1, psi)
    if not DRY:
        json.dump(st, open(STATE + ".tmp", "w"))
        os.replace(STATE + ".tmp", STATE)
    return l1, psi


def main():
    st = load_state()
    if "--once" in sys.argv:
        protect()
        l1, psi = step(st)
        print(f"load {l1:.1f}, cpu pressure {psi:.0f}%, paused {st['paused'] or 'nothing'}; log {LOG}")
        return
    say(f"loadguard up (pid {os.getpid()}): limits " + ", ".join(f"{k} {loadlim.get(k):g}" for k in loadlim.DEFAULTS))
    last_p = 0.0
    while True:
        try:
            if time.time() - last_p >= PROTECT_EVERY and not os.path.exists(OFF):
                protect()
                last_p = time.time()
            step(st)
        except Exception as e:  # noqa: BLE001  (a guard must not die on one bad read)
            say(f"error: {e!r}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
