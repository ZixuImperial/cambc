#!/usr/bin/env python3
"""analyst_hook: keeps the analyser sessions and the Coordinator working on our games (owner 8 Nov: "Make a hook for the analysers or the coordinator to keep
analysing our games then to believe in themselves and find the core problem and find a viable solution"). A Stop hook in ~/.claude/settings.json; other sessions pass.
  (no argument)  a stop is blocked with analyst_hook.txt plus the live feed, at most CAP times per WINDOW seconds per session, so a one-line reply can't spin
  --rewake       asyncRewake: a Stop hook can't reach a session already idle, so one background waiter per session wakes it (exit 2) after IDLE seconds without activity
Off: touch /data/zw4424/st/nudge/KEEPBUSY_OFF. Edit analyst_hook.txt freely; it is read on every use."""
import fcntl
import glob
import json
import os
import subprocess
import sys
import time

DIR = os.environ.get("ANALYST_HOOK_DIR", "/data/zw4424/st/nudge")
SESSIONS = os.environ.get("ANALYST_HOOK_SESSIONS", os.path.expanduser("~/.claude/sessions"))
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MATCH = ("analys", "coordinator", "planner", "vv design", "builder", "ci design", "vv redesign")  # 10 Nov (owner: "make sure every session keeps working without needing reminding")
NOT = ("tool builder",)  # the Tool Builder runs its own resume tick; never wake it here
ROLE_TEXT = {"planner": "hook_planner.txt", "vv design": "hook_vv.txt", "vv redesign": "hook_vv.txt", "builder": "hook_builder.txt"}  # analysts: analyst_hook.txt
CAP, WINDOW = int(os.environ.get("ANALYST_HOOK_CAP", 6)), int(os.environ.get("ANALYST_HOOK_WINDOW", 1200))
GAP = int(os.environ.get("ANALYST_HOOK_GAP", 900))  # 8 Nov: blocks came 2 s apart: a session waiting on its walkers ended its turn, was blocked, and said so again, up to the cap
IDLE, LIFE = int(os.environ.get("ANALYST_HOOK_IDLE", 900)), int(os.environ.get("ANALYST_HOOK_LIFE", 21600))


def session_name(sid):
    for p in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            d = json.load(open(p))
        except (OSError, ValueError):
            continue
        if d.get("sessionId") == sid:
            return d.get("name") or ""
    return None


def feed():
    """Two lines of what is waiting right now; never fails the hook."""
    out = []
    for cmd, keep in ((["tools/lab/critgame.py", "status"], lambda ln: ln.startswith("OPEN")), (["tools/lab/ladderclimb.py", "losses"], lambda ln: ln.strip().startswith(("wait", "READY")))):
        try:
            r = subprocess.run([sys.executable, "-I"] + cmd, cwd=REPO, capture_output=True, text=True, timeout=8)
            out += [ln.strip()[:170] for ln in r.stdout.splitlines() if keep(ln)][:4]
        except (OSError, subprocess.SubprocessError):
            pass
    return ("\nWaiting now:\n" + "\n".join(out)) if out else ""


def text(sid=None):
    name = (session_name(sid) or "").lower() if sid else ""
    # 10 Nov (CI Analyser: renamed "CI Planner" got the Planner's text): "planner" / "builder" match the whole name only, so "CI Planner",
    # "Prism Planner" get the analyst text; the VV names still match as substrings
    f = next((v for k, v in ROLE_TEXT.items() if (name.strip() == k if k in ("planner", "builder") else k in name)), None)
    if f and os.path.exists(os.path.join(HERE, f)):
        return open(os.path.join(HERE, f)).read().strip()
    return open(os.path.join(HERE, "analyst_hook.txt")).read().strip() + feed()


def skipped(name):
    """analyst_hook_skip.txt in DIR: one session name per line (any case), for a session on another task the owner gave it"""
    try:
        return name.lower() in {x.strip().lower() for x in open(os.path.join(DIR, "analyst_hook_skip.txt")) if x.strip()}
    except OSError:
        return False


def ours(ev):
    sid = ev.get("session_id") or ""
    if not sid or ev.get("agent_id") or os.path.exists(os.path.join(DIR, "KEEPBUSY_OFF")):
        return None
    name = session_name(sid)
    return sid if (name and any(m in name.lower() for m in MATCH) and not any(x in name.lower() for x in NOT)
                   and not skipped(name)) else None


def block(sid):
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, "stops_" + "".join(c for c in sid if c.isalnum() or c in "-_"))
    now = time.time()
    try:
        ts = [float(x) for x in open(p).read().split() if now - float(x) < WINDOW]
    except (OSError, ValueError):
        ts = []
    if len(ts) >= CAP or (ts and now - max(ts) < GAP):
        return
    with open(p, "w") as f:
        f.write(" ".join(map(str, ts + [now])))
    print(json.dumps({"decision": "block", "reason": text(sid)}))


def rewake(sid, ev):
    os.makedirs(DIR, exist_ok=True)
    f = open(os.path.join(DIR, "rewake_" + "".join(c for c in sid if c.isalnum() or c in "-_") + ".lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # one waiter per session
    t0, tp = time.time(), ev.get("transcript_path") or ""
    while time.time() - t0 < LIFE:
        time.sleep(min(60, max(IDLE / 10, 1)))
        nm = session_name(sid)
        if os.path.exists(os.path.join(DIR, "KEEPBUSY_OFF")) or nm is None or skipped(nm):  # 10 Nov: a waiter started before a skip entry must stop too
            return 0
        try:
            if time.time() - os.path.getmtime(tp) >= IDLE:
                print(text(sid), file=sys.stderr)
                return 2
        except OSError:
            return 0
    return 0


def main():
    try:
        ev = json.load(sys.stdin)
        sid = ours(ev)
        if not sid:
            return 0
        if "--rewake" in sys.argv:
            return rewake(sid, ev)
        block(sid)
    except Exception:  # noqa: BLE001  a broken hook must never get in a session's way
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
