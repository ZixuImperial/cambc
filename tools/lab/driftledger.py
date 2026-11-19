#!/usr/bin/env python3
"""driftledger: one honest progress number per ship. Tool builder, 2 Nov (owner: rigorous, aiming for rank 1).

usage: python3 -I tools/lab/driftledger.py BOT VERSION [--anchors A,B]   play one ship against the fixed anchors, append one line
       python3 -I tools/lab/driftledger.py --catchup [N]                 the same for the newest N live.txt versions missing (default 3)
Appends to LEDGER: map-pair score [95% CI] of the ship against each anchor, head to head on the full pool ("all": pool + fresh +
held-out, both seats). 0.5 = no difference; above 0.5 = the ship beats the anchor. Anchors stay fixed so lines compare over time,
unlike anchor.txt, which moves. A changed pool or anchor source shows in the pool= and anchor hash fields: compare only equal ones.
This is a self-play measure on saved maps, not the fresh-map gate, and not a rating. Runs at CONDAB_PRIO -50, behind every gate.
shipcheck starts it in the background after a submit, so it never blocks a ship; hand submits are picked up by --catchup."""
import fcntl
import hashlib
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
LEDGER = os.environ.get("LEDGER", "/homes/zw4424/condor-work/reports/drift_ledger.md")
Q = "/data/zw4424/st/bq"
LIVE = Q + "/live.txt"
ANCHORS = ["nova_b633_rythhp", "nova_b1016_bundle32"]  # v368, the fixed anchor; v396, the recent one
LEG_S = int(os.environ.get("LEDGER_LEG_S", 6 * 3600))
sys.path.insert(0, REPO + "/tools/lab")
HEAD = ("# Drift ledger: each ship vs fixed anchors, full pool, head to head (see tools/lab/driftledger.py)\n"
        "Map-pair score [95% CI]: above 0.5 = better than the anchor. Self-play on saved maps: a direction, not a rating.\n\n")


def read_score(name):
    try:
        txt = open(os.path.join(Q, f"{name}.condor.txt")).read()
    except OSError:
        return None
    m = re.search(r"^\s+ALL\s+(\d+) maps: .*?score ([\d.]+) \[([\d.]+), ([\d.]+)\]", txt, re.M)
    return f"{float(m.group(2)):.3f} [{float(m.group(3)):.3f}, {float(m.group(4)):.3f}] n {m.group(1)}" if m else None


def one(bot, anchor, version, i):
    env = {k: v for k, v in os.environ.items() if k not in ("STOP", "STOP_PASS", "STOP_REF", "SET", "SUBSET", "CONFIRM", "KEEP", "CONDAB_TIMEBOX")}
    env.update(OTF="0", CONDAB_PRIO=os.environ.get("LEDGER_PRIO", "-50"))
    for k in range(1, 50):
        name = f"dl{version}x{i}" + (f"r{k}" if k > 1 else "")
        if not os.path.exists(os.path.join(Q, f"{name}.condor.txt")):
            break
    try:
        r = subprocess.run(["sh", REPO + "/tools/lab/condab.sh", bot, anchor, name, "all"], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=LEG_S)
    except (OSError, subprocess.SubprocessError) as e:
        return f"no result ({str(e)[:60]})"
    return read_score(name) or f"no result (condab exit {r.returncode}, {name})"


def run(bot, version, anchors):
    import abindex
    import condab
    pool = hashlib.sha1("\n".join(sorted(condab.set_maps("all"))).encode()).hexdigest()[:8]
    parts = []
    for i, a in enumerate(anchors, 1):
        res = "self" if a == bot else one(bot, a, version, i)
        parts.append(f"vs {a} ({abindex.bot_hash(a)[:8]}) {res}")
    line = (f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} v{version} {bot} ({abindex.bot_hash(bot)[:8]}) pool={pool}: "
            + "; ".join(parts) + "\n")
    with open(LEDGER, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if f.tell() == 0 and os.path.getsize(LEDGER) == 0:
            f.write(HEAD)
        f.write(line)
    print(line, end="")


def main():
    a = sys.argv[1:]
    anchors = ANCHORS
    if "--anchors" in a:
        i = a.index("--anchors")
        anchors = a[i + 1].split(",")
        del a[i:i + 2]
    if a[:1] == ["--catchup"]:
        n = int(a[1]) if len(a) > 1 else 3
        have = set(re.findall(r"^- \S+ v(\d+) ", open(LEDGER).read(), re.M)) if os.path.exists(LEDGER) else set()
        rows = [ln.split() for ln in open(LIVE).read().splitlines()[:n] if ln.startswith("v")]
        for r in reversed(rows):
            if r[0][1:] not in have:
                run(r[1], r[0][1:], anchors)
        return 0
    if len(a) != 2:
        sys.exit(__doc__)
    run(a[0], a[1], anchors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
