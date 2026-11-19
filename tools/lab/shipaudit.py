#!/usr/bin/env python3
"""shipaudit: every AUDIT_EVERY (5) ships, re-read the current live against the live AUDIT_EVERY versions back on NEW fresh maps, both seats
(Tool Builder 11 Nov; owner: "go for it as long as it makes better iterations and faster iterations without stalling on stale data").
Each ship passes its own bar, but a sequential bar on many candidates still lets some lucky ones through; this read checks that the last
AUDIT_EVERY ships TOGETHER are a gain. Information only: it never blocks or delays a ship (lowest pilot priority SA_PRIO 5, its own unit),
and it plays only maps no candidate was picked on (stylepanel --fresh-only: stratmaps --take, half weird, never saved).

usage: python3 -I tools/lab/shipaudit.py tick            (armq's loop: start the audit a new live is due for; one audit at a time)
       python3 -I tools/lab/shipaudit.py run NEW OLD     (an audit now: NEW v OLD, e.g. v760 v755)
       python3 -I tools/lab/shipaudit.py status          (the audits and their verdicts)
Verdict (bq/shipaudit.log, one line per audit, and bq/shipaudit_vNEW.txt): HELD (point >= .50), FLAT (point < .50, CI upper >= .50), or
NEGATIVE (CI upper < .50): the last ships lost ground together; bisect them (shipaudit run vNEW-k vOLD) and roll back what doesn't hold
(CLAUDE.md 'Rollback'). Off: touch bq/shipaudit_OFF."""
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
Q = "/data/USER/st/bq"
LOG = os.path.join(Q, "shipaudit.log")
EVERY = int(os.environ.get("SA_EVERY", 5))
N = int(os.environ.get("SA_N", 3300))
PRIO = os.environ.get("SA_PRIO", "5")


def lives():
    """[(vNNN, bot)] newest first, from live.txt"""
    out = []
    for ln in open(os.path.join(Q, "live.txt")):
        p = ln.split()
        if len(p) >= 2 and re.fullmatch(r"v\d+", p[0]):
            out.append((p[0], p[1]))
    return out


def say(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def running():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", "nova-shipaudit"]).returncode == 0


def done_for():
    try:
        return {m.group(1) for m in re.finditer(r" (?:start|verdict) (v\d+) v ", open(LOG).read())}
    except OSError:
        return set()


def tick():
    if os.path.exists(os.path.join(Q, "shipaudit_OFF")) or running():
        return
    lv = lives()
    if len(lv) <= EVERY:
        return
    new, old = lv[0], lv[EVERY]
    vn = int(new[0][1:])
    if vn % EVERY or new[0] in done_for():
        return
    if not all(os.path.isdir(os.path.join(REPO, "bots", b, "src")) for _, b in (new, old)):
        say(f"skip {new[0]} v {old[0]}: a bot is gone ({new[1]}, {old[1]})")
        return
    subprocess.run(["sh", os.path.join(REPO, "tools/lab/detach.sh"), "-l", os.path.join(Q, "shipaudit.out"), "shipaudit",
                    sys.executable, "-I", os.path.abspath(__file__), "run", new[0], old[0]], cwd=REPO)


def run(vnew, vold):
    lv = dict(lives())
    new, old = lv[vnew], lv[vold]
    tag = f"sa{vnew[1:]}"
    say(f"start {vnew} v {vold}: {new} v {old}, {N} new fresh maps, both seats, prio {PRIO} (tag {tag})")
    env = dict(os.environ, SP_PRIO=PRIO, SP_KIND_Z="99")
    for k in ("SUBSET", "CONDAB_STOPFILE", "STOP", "SET", "BASE_ND", "BIG", "CONFIRM"):
        env.pop(k, None)
    with open(os.path.join(Q, f"sc_{tag}_sp.log"), "a") as lg:
        subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stylepanel.py"), new, old, tag, "--n", str(N),
                        "--fresh-only", "--par", "8"], cwd=REPO, env=env, stdout=lg, stderr=subprocess.STDOUT)
    txt = open(os.path.join(Q, f"sp{tag}.txt")).read() if os.path.exists(os.path.join(Q, f"sp{tag}.txt")) else ""
    m = re.search(r"^FRESH: \S+\s+CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", txt, re.M)
    if not m:
        say(f"verdict {vnew} v {vold}: NO RESULT (sp{tag}.txt has no fresh row)")
        return 2
    pt, lo, hi, n = float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))
    v = "HELD" if pt >= 0.5 else "FLAT" if hi >= 0.5 else "NEGATIVE"
    cl = re.search(r"^FRESH CLASS: (.*)$", txt, re.M)
    open(os.path.join(Q, f"shipaudit_{vnew}.txt"), "w").write(
        f"SHIP AUDIT {vnew} ({new}) v {vold} ({old}): {pt:.4f} [{lo:.4f}, {hi:.4f}] over {n} new fresh maps: {v}\n"
        + (f"FRESH CLASS: {cl.group(1)}\n" if cl else "")
        + ("NEGATIVE: the last ships lost ground together: bisect (shipaudit.py run vMID vOLD) and roll back what does not hold\n" if v == "NEGATIVE" else ""))
    say(f"verdict {vnew} v {vold}: {v} {pt:.4f} [{lo:.4f}, {hi:.4f}] n {n}")
    return 0


def status():
    try:
        print(open(LOG).read()[-3000:])
    except OSError:
        print("no audits yet")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if a[0] == "tick":
        tick()
    elif a[0] == "run" and len(a) == 3:
        sys.exit(run(a[1], a[2]))
    elif a[0] == "status":
        status()
    else:
        sys.exit(__doc__)
