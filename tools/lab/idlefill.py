#!/usr/bin/env python3
"""idlefill (13 Nov, owner: "If nothing running test bug fixes and fuel optimisations"). Tool Builder.

Every IF_EVERY (60) s: when fewer than IF_MIN_RUNNING (3) shipchecks run AND armq has no waiting line, arm the NEXT unused line of
bq/idle_fill.txt (one `armq.py add` argument line per entry, shell-quoted, e.g.
  nova_b2387_gtm1:nova_base_v897 "GTM_BITS=1" fix "fix(fuel): GTM1 hs3 resize cut" gtm1 --q1bar
), at most one per tick. Entries are prepared by the Builder / Rule Checker (bug fixes: --bugbar; fuel cuts: --q1bar, play-identical ones
take shipcheck's IDENT route). Armed / failed entries move to bq/idle_fill.done with the armq output tail. '#' lines are comments.
usage: idlefill.py loop | once | status"""
import os
import re
import shlex
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
Q = "/data/zw4424/st/bq"
LIST, DONE, LOG = f"{Q}/idle_fill.txt", f"{Q}/idle_fill.done", f"{Q}/idlefill.log"


def log(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def running():
    out = subprocess.run(["pgrep", "-af", "[s]hipcheck.py nova_"], capture_output=True, text=True).stdout
    return sum(1 for ln in out.splitlines() if re.search(r"shipcheck\.py nova_\S+ \d+", ln))


def waiting():
    out = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/armq.py", "list"], capture_output=True, text=True, cwd=REPO).stdout
    return sum(1 for ln in out.splitlines() if ln.startswith("{"))


def entries():
    try:
        return [ln.rstrip("\n") for ln in open(LIST) if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def once():
    r, w = running(), waiting()
    es = entries()
    if r >= int(os.environ.get("IF_MIN_RUNNING", 3)) or w > 0 or not es:
        return f"idle check: {r} running, {w} waiting, {len(es)} entries: nothing to do"
    e = es[0]
    p = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/armq.py", "add"] + shlex.split(e), capture_output=True, text=True, cwd=REPO,
                       timeout=900)
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
    with open(DONE, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\trc {p.returncode}\t{e}\t{tail[0][:200]}\n")
    rest = [ln for ln in open(LIST)]
    i = next((k for k, ln in enumerate(rest) if ln.rstrip("\n") == e), None)
    if i is not None:
        del rest[i]
        tmp = LIST + f".new.{os.getpid()}"
        open(tmp, "w").writelines(rest)
        os.replace(tmp, LIST)
    msg = f"armed from idle_fill ({r} running, 0 waiting): rc {p.returncode}: {e[:120]} -> {tail[0][:120]}"
    log(msg)
    return msg


def main():
    a = sys.argv[1:]
    if a[:1] == ["once"]:
        print(once())
    elif a[:1] == ["status"]:
        print(f"{running()} running, {waiting()} waiting, {len(entries())} entries in {LIST}")
    elif a[:1] == ["loop"]:
        while True:
            try:
                once()
            except Exception as e:  # noqa: BLE001  a daemon: log and go on
                log(f"error {type(e).__name__}: {e}")
            time.sleep(int(os.environ.get("IF_EVERY", 60)))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
