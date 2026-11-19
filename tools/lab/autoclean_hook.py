#!/usr/bin/env python3
"""autoclean_hook: PostToolUse hook, any session (owner 8 Nov: "Add a hook to make sure you delete files for quota when we are filled"). At most every CHECK seconds
it starts itself detached (--run); that measures the home quota and /data and, when one is filled, runs tools/lab/autoclean.py --apply: only autoclean's guarded,
regenerable piles go. Filled: home files >= FILES, home space >= SPACE of the quota, or /data >= DATA. Off: touch /data/zw4424/st/autoclean/OFF. Log: /data/zw4424/st/autoclean/hook.log."""
import fcntl
import os
import re
import subprocess
import sys
import time

D = os.environ.get("AUTOCLEAN_DIR", "/data/zw4424/st/autoclean")
REPO = "/homes/zw4424/cambc"
CHECK = int(os.environ.get("AUTOCLEAN_CHECK", 300))
# 9 Nov 17:32Z: SPACE .90 -> .82 of the 11,719 MB quota (~9,600 MB): .90 (10,547 MB) fired only after condab had already slowed at 10,000 MB
FILES, SPACE, DATA = int(os.environ.get("AUTOCLEAN_FILES", 50000)), float(os.environ.get("AUTOCLEAN_SPACE", .82)), float(os.environ.get("AUTOCLEAN_DATA", .85))


def log(m):
    with open(D + "/hook.log", "a") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + m + "\n")


def filled():
    """why we are filled, or ''"""
    why = []
    r = subprocess.run(["quota", "-s"], capture_output=True, text=True, timeout=30)
    m = re.search(r"(\d+)M\*?\s+(\d+)M\s+\d+M\s+(?:\S+\s+)??(\d+)\*?\s+\d+\s+\d+", r.stdout)
    if not m:
        log("quota unreadable: " + r.stdout[-120:].replace("\n", " "))
    else:
        used, cap, files = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if files >= FILES:
            why.append(f"home files {files} >= {FILES}")
        if used >= SPACE * cap:
            why.append(f"home space {used}M >= {SPACE:.0%} of {cap}M")
    v = os.statvfs("/data")
    pct = 1 - v.f_bavail / max(v.f_blocks, 1)
    if pct >= DATA:
        why.append(f"/data {pct:.0%} >= {DATA:.0%}")
    return "; ".join(why)


def run():
    f = open(D + "/.hook.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    why = filled()
    if not why:
        return
    log("filled: " + why + ": autoclean --apply")
    args = [] if os.environ.get("AUTOCLEAN_DRY") == "1" else ["--apply"]
    r = subprocess.run(["nice", "-n", "19", "ionice", "-c3", "timeout", "3600", sys.executable, "-I", REPO + "/tools/lab/autoclean.py"] + args,
                       cwd=REPO, capture_output=True, text=True)
    log(f"autoclean exit {r.returncode}; now {filled() or 'below the marks'}")


def main():
    if "--run" in sys.argv:
        return run()
    try:  # 11 Nov (Coordinator: a hook-launched autoclean ran while loadguard held nova-autoclean paused at load 76): not above the load
        # where loadguard pauses deferrable units (bq/load_limits pause_load), and never while the unit is paused
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import loadlim
        if os.getloadavg()[0] > float(loadlim.get("pause_load") or 64):
            return 0
    except Exception:  # noqa: BLE001
        pass
    if os.path.exists(D + "/OFF"):
        return
    st = D + "/hook_check"
    try:
        if time.time() - os.path.getmtime(st) < CHECK:
            return
    except OSError:
        pass
    open(st, "a").close()
    os.utime(st)
    subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--run"], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001  a hook must never disturb the session
        pass
