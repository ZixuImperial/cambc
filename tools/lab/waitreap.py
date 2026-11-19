#!/usr/bin/env python3
"""waitreap.py - find (and optionally stop) stalled shell waiter loops (owner, 1 Nov: "make sure the waiters are not stalled
forever").

A waiter is a `bash -c ...` process of user USER whose command holds an `until` / `while` loop and whose only child is a
`sleep`. It is flagged STALLED when either
  - SELF-MATCH: it polls `pgrep -f "PAT"` and PAT (without a [x] bracket trick) occurs in its own command line, so pgrep
    always finds the waiter itself and the loop can never end; or
  - OLD: it has run longer than --max-hours (default 6).
Other waiters older than --hours (default 1) are listed as INFO.

usage: python3 -I tools/lab/waitreap.py [--hours 1] [--max-hours 6] [--kill]
  --kill  sends SIGTERM to STALLED waiters only, after re-reading each one's command line (PID reuse guard). It never
          touches a process that is not a bash loop whose only child is sleep. Every stop is logged with the session (claude pid =
          its socket name) that made the waiter: /data/USER/st/bq/waitreap.log.
"""
import argparse
import os
import re
import signal
import subprocess


def procs():
    out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,ppid=,etimes=,args="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
    return rows


LOG = "/data/USER/st/bq/waitreap.log"


def session_of(pid, rows):
    """the claude process (= a session; its pid names its socket /run/user/16910/cc-socks/PID.sock) a waiter descends from, or None"""
    par = {p: (pp, args) for p, pp, _, args in rows}
    for _ in range(30):
        if pid not in par:
            return None
        pp = par[pid][0]
        a = par.get(pp, (0, ""))[1].split()
        if a and os.path.basename(a[0]) == "claude":
            return pp
        pid = pp
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--max-hours", type=float, default=6.0)
    ap.add_argument("--kill", action="store_true")
    a = ap.parse_args()
    rows = procs()
    kids = {}
    for pid, ppid, et, args in rows:
        kids.setdefault(ppid, []).append(args)
    me = os.getpid()
    n_stalled = 0
    for pid, ppid, et, args in rows:
        if pid == me or not args.startswith(("/bin/bash", "bash", "sh ")):
            continue
        if not re.search(r"\b(until|while)\b", args):
            continue
        ch = kids.get(pid, [])
        if not ch or not all(c.split()[0].endswith("sleep") for c in ch):
            continue
        hours = et / 3600.0
        why = []
        # 8 Nov: a self-matching pgrep only stalls the loop when it is the loop's whole condition; `until grep -q done LOG || ! pgrep -f X`
        # still ends through its grep (the reaper stopped such a Builder waiter at 08:32)
        cond = re.search(r"\b(until|while)\b(.*?);\s*do\b", args, re.S)
        cond_txt = cond.group(2) if cond else args
        other = re.sub(r"!?\s*pgrep[^;|&]*", "", cond_txt)
        only_pgrep = not re.search(r"\b(grep|test|ls|find|kill|ps)\b|\[|-[efs]\s", other)
        for pat in re.findall(r"pgrep[^\"']*[\"']([^\"']+)[\"']", cond_txt):
            if "[" not in pat and only_pgrep:
                why.append("SELF-MATCH pgrep '%s'" % pat[:60])
        if hours > a.max_hours:
            why.append("OLD %.1f h" % hours)
        loop = re.search(r"\b(until|while)\b[^;]{0,120}", args)
        desc = loop.group(0) if loop else args[:120]
        if why:
            n_stalled += 1
            print("STALLED pid %d %.1f h: %s | %s" % (pid, hours, "; ".join(why), desc))
            if a.kill:
                try:
                    now = open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(errors="replace")
                except OSError:
                    continue
                if desc[:40] in now:
                    os.kill(pid, signal.SIGTERM)
                    sess = session_of(pid, rows)
                    print("  stopped %d (session pid %s)" % (pid, sess))
                    try:  # 8 Nov: 56 self-matching waiters were stopped in one run with no trace of who made them
                        import time
                        with open(LOG, "a") as f:
                            f.write("%s stopped pid %d session %s %.1f h %s | %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), pid, sess,
                                                                                   hours, "; ".join(why), desc[:160]))
                    except OSError:
                        pass
        elif hours > a.hours:
            print("INFO    pid %d %.1f h: %s" % (pid, hours, desc))
    print("stalled waiters: %d" % n_stalled)


if __name__ == "__main__":
    main()
