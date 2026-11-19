#!/usr/bin/env python3
"""varguard: keep HOST's /var from filling (Tool Builder, 10 Nov ~03:20Z; owner: "make sure var doesn't fill up").

Root's /var/log/syslog logs every program we start (about 1.5 KB each, 2x the argv for long command lines) and only rotates at
~00:29Z, with delaycompress keeping yesterday's file uncompressed. On 9-10 Nov it grew ~2 GB/h with the pipeline here; HOST's own
host pilots were most of it (A/B: 331 -> 65 KB/s with them frozen), so those are off (condor-runs/hostpilots/HOST.OFF).

One long-lived process: os.statvfs every 60 s (no process starts of its own). Steps, each undone when /var is back over CLEAR_MB:
  < 3000 MB  pause (SIGSTOP) the unranked climb lanes (nova-ladderclimb-*): platform games are not the deciding reads
  < 2000 MB  also write bq/max_running 6 (shipwatch reads it every scan; the old value is kept in bq/varguard.state)
  < 1200 MB  also pause shipwatch and the build-agent units (nova-b1*); the loop then holds until /var recovers
Every change is logged to /data/USER/st/bq/varguard.log and written as an ALARM line in bq/varguard.alarm (since.py shows
healthwatch alarms; that file is for the Builder's tick). Off: touch /data/USER/st/bq/varguard_OFF.
usage: python3 -I tools/lab/varguard.py [--once] [--dry]"""
import json
import os
import subprocess
import sys
import time

BQ = "/data/USER/st/bq"
LOG = f"{BQ}/varguard.log"
STATE = f"{BQ}/varguard.state"
ALARM = f"{BQ}/varguard.alarm"
# 11 Nov (Coordinator): + 'warn' (alarm only) under 4 GB and 'reads' under 3 GB (bq/reads_hold: readslots admits no new big read)
STEPS = [(4000, "warn"), (3000, "climbs"), (3000, "reads"), (800, "slots"), (300, "hold")]  # 13 Nov 20:3xZ Coordinator: hold 1200 -> 600 -> 300 tonight (state on /data)
CLEAR_MB = int(os.environ.get("VARGUARD_CLEAR_MB", "4500"))
SAMPLES = f"{BQ}/var_samples.tsv"  # every SAMPLE_S (600): time, /var free MB, syslog MB, syslog growth MB/h since the last sample
SAMPLE_S = int(os.environ.get("VARGUARD_SAMPLE_S", "600"))
DRY = "--dry" in sys.argv


def say(m):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + m
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def free_mb():
    s = os.statvfs("/var")
    return s.f_bavail * s.f_frsize // (1 << 20)


def units(prefix):
    r = subprocess.run(["systemctl", "--user", "list-units", f"{prefix}*", "--no-legend", "--state=running"], capture_output=True, text=True)
    return [ln.split()[0] for ln in r.stdout.splitlines() if ln.split()]


def sig(us, s):
    for u in us:
        if not DRY:
            subprocess.run(["systemctl", "--user", "kill", "-s", s, u], capture_output=True)
    return us


def load():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"active": [], "paused": {}, "max_running": None}


def save(st):
    if not DRY:
        json.dump(st, open(STATE + ".tmp", "w"))
        os.replace(STATE + ".tmp", STATE)


def apply(step, st, mb):
    if step == "climbs":
        st["paused"]["climbs"] = sig(units("nova-ladderclimb"), "SIGSTOP")
    elif step == "slots":
        try:
            st["max_running"] = open(f"{BQ}/max_running").read().strip()
        except OSError:
            st["max_running"] = None
        if not DRY:
            open(f"{BQ}/max_running", "w").write("6\n")
    elif step == "hold":
        # 13 Nov 20:3xZ (Coordinator): shipwatch reads verdicts and AUTO-SUBMITS, so it is never stopped: the hold sets max_running 0
        # (no new checks; running ones finish, are read and ship) and stops only the build-agent units
        st["paused"]["hold"] = sig(units("nova-b1"), "SIGSTOP")
        if not DRY:
            try:
                st["mr_hold"] = open(f"{BQ}/max_running").read().strip()
            except OSError:
                st["mr_hold"] = None
            open(f"{BQ}/max_running", "w").write("0  # varguard hold: no new shipchecks while /var is critical\n")
    elif step == "reads" and not DRY:
        open(f"{BQ}/reads_hold", "w").write(f"varguard: /var {mb} MB free\n")
    st["active"].append(step)
    say(f"/var {mb} MB free: step '{step}' on")


def undo(step, st, mb):
    if step in ("climbs", "hold"):
        sig(st["paused"].pop(step, []), "SIGCONT")
        if step == "hold" and st.get("mr_hold") and not DRY:
            open(f"{BQ}/max_running", "w").write(st.pop("mr_hold") + "\n")
    elif step == "slots" and st.get("max_running") and not DRY:
        open(f"{BQ}/max_running", "w").write(st["max_running"] + "\n")
    elif step == "reads" and not DRY:
        try:
            os.remove(f"{BQ}/reads_hold")
        except OSError:
            pass
    st["active"].remove(step)
    say(f"/var {mb} MB free: step '{step}' off")


def sample(mb):
    """One line every SAMPLE_S to bq/var_samples.tsv (on /data): free MB, syslog size and its growth (MB/h)."""
    try:
        last = open(SAMPLES).read().splitlines()[-1].split("\t")
        lt, lsz = float(last[1]), float(last[3])
    except (OSError, IndexError, ValueError):
        lt, lsz = 0.0, None
    now = time.time()
    if now - lt < SAMPLE_S:
        return
    try:
        sz = os.stat("/var/log/syslog").st_size / (1 << 20)
    except OSError:
        sz = -1.0
    rate = (sz - lsz) / ((now - lt) / 3600) if lsz is not None and sz >= lsz and lt else float("nan")
    if not os.path.exists(SAMPLES):
        open(SAMPLES, "w").write("utc\tepoch\tvar_free_mb\tsyslog_mb\tsyslog_mb_per_h\n")
    with open(SAMPLES, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{now:.0f}\t{mb}\t{sz:.0f}\t{rate:.0f}\n")


def tick():
    st = load()
    mb = free_mb()
    try:
        if not DRY:
            sample(mb)
    except Exception:  # noqa: BLE001
        pass
    if os.path.exists(f"{BQ}/varguard_OFF"):
        return mb
    for lim, step in STEPS:
        if mb < lim and step not in st["active"]:
            apply(step, st, mb)
    if mb >= CLEAR_MB:
        for _, step in reversed(STEPS):
            if step in st["active"]:
                undo(step, st, mb)
    save(st)
    if not DRY:
        if st["active"]:
            open(ALARM, "w").write(f"ALARM /var {mb} MB free on HOST: varguard steps on: {', '.join(st['active'])} (CSG can compress /var/log/syslog.1)\n")
        elif os.path.exists(ALARM):
            os.remove(ALARM)
    return mb


def main():
    if "--once" in sys.argv:
        print(f"/var {tick()} MB free; state {load()}")
        return 0
    say(f"varguard up (pid {os.getpid()}): steps {STEPS}, clear at {CLEAR_MB} MB")
    while True:
        try:
            tick()
        except Exception as e:  # noqa: BLE001  the guard never dies on one bad pass
            say(f"!! tick: {e!r}")
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
