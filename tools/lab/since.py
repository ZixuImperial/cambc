#!/usr/bin/env python3
"""since: what changed since T, in a few lines (owner 5 Nov: spend fewer tokens; replaces greps over live.txt, shipwatch.log,
info/ and gate/ results, armq.txt, pending_reads.txt and pid files).
usage: python3 -I tools/lab/since.py [T] [--mark NAME] [--max N]
  T: 30m | 2h | 1d | an ISO time (2026-11-05T01:30Z) | omitted: 1h, or with --mark the time of NAME's last call
  --mark NAME: remember this call's time under NAME (/data/zw4424/st/bq/since_marks/NAME), so the next call with
               --mark NAME and no T shows only what is new since then. The Builder: `since.py --mark builder`.
  --max N: at most N lines per section (default 8; the rest is counted).
Sections, each skipped when empty: SHIPS (live.txt), SHIPCHECKS (ended: one digest line each; running), READS (inforead
results finished), GATES (gate verdicts written), QUEUE (armq lines waiting, pending reads), DAEMONS (only dead ones),
ALARM (cxe slot waiters stuck: tools/cxe/cxerun.py --health).
Digest lines come from tools/lab/digest.py; `digest.py TAG --rows` gives a check's failing rows in full."""
import calendar
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest  # noqa: E402

BQ = "/data/zw4424/st/bq"
ST = "/data/zw4424/st"
MARKS = f"{BQ}/since_marks"
DAEMONS = {"shipwatch": "[s]hipwatch.py", "armq": "[a]rmq.py --loop", "pilotd": "[p]ilotd.py", "livepipe": "[l]ivepipe",
           "quotaguard": "[q]uotaguard.py", "freshpool": "[f]reshpool.py", "critgame": "[c]ritgame.py auto",
           "healthwatch": "[h]ealthwatch.py --loop"}


def parse_t(s):
    """-> epoch seconds."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([mhd])", s)
    if m:
        return time.time() - float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    s = s.rstrip("Z").replace(" ", "T")
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return calendar.timegm(time.strptime(s, f))
        except ValueError:
            pass
    sys.exit(f"since: can't read the time {s!r} (use 30m, 2h, 1d or 2026-11-05T01:30Z)")


def iso_epoch(s):
    try:
        return calendar.timegm(time.strptime(s.rstrip("Z")[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0


def capped(lines, mx):
    return lines[:mx] + ([f"  ... +{len(lines) - mx} more"] if len(lines) > mx else [])


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d  # noqa: E731
    mark, mx = opt("--mark"), int(opt("--max", "8"))
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in ("--mark", "--max"))]
    now = time.time()
    if pos:
        t0 = parse_t(pos[0])
    elif mark and os.path.exists(f"{MARKS}/{mark}"):
        t0 = float(open(f"{MARKS}/{mark}").read().split()[0])
    else:
        t0 = now - 3600
    out = [f"since {time.strftime('%H:%MZ', time.gmtime(t0))} ({(now - t0) / 60:.0f} min)"]

    # SHIPS
    ships = []
    try:
        for ln in open(f"{BQ}/live.txt"):
            f = ln.split()
            if len(f) >= 3 and iso_epoch(f[2]) > t0:
                ships.append(f"  {f[0]} {f[1]} {f[2][11:16]}Z" + (f" ({f[3]})" if len(f) > 3 else ""))
    except OSError:
        pass
    if ships:
        out += ["SHIPS"] + capped(ships, mx)

    # SHIPCHECKS
    ended, running = [], {}
    try:
        for ln in open(f"{BQ}/shipwatch.log", errors="replace"):
            m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ) (start|ended) (\S+?):? (.*)", ln)
            if not m:
                continue
            ts, kind, bot = iso_epoch(m.group(1)), m.group(2), m.group(3)
            if kind == "start":
                tag = re.search(r"TAG=(\S+)", m.group(4))
                running[bot] = (tag.group(1) if tag else "?", ts)
            else:
                tag = running.pop(bot, ("?", 0))[0]
                if ts > t0:
                    ended.append((tag, bot, m.group(4).strip()))
    except OSError:
        pass
    sc = []
    for tag, bot, res in ended:
        p = digest.resolve(tag) if tag != "?" else None
        sc.append("  " + (digest.digest(p)[0] if p else f"{bot}: {res}"))
    sc += [f"  running: {tag} {bot} ({(now - ts) / 60:.0f} min)" for bot, (tag, ts) in running.items() if now - ts < 6 * 3600]
    if sc:
        out += ["SHIPCHECKS"] + capped(sc, mx)

    # READS (inforead results) and GATES
    for name, pat in (("READS", f"{ST}/info/*/result.txt"), ("GATES", f"{ST}/gate/*/verdict.txt")):
        got = []
        for p in glob.glob(pat):
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt > t0:
                got.append((mt, p))
        lines = []
        for _, p in sorted(got, reverse=True):
            lines.append("  " + digest.digest(p)[0])
        if lines:
            out += [name] + capped(lines, mx)

    # QUEUE
    q = []
    try:
        waiting = [ln.strip() for ln in open(f"{BQ}/armq.txt") if ln.strip() and not ln.startswith("#")]
        if waiting:
            q.append(f"  armq: {len(waiting)} waiting; next {digest.cut(waiting[0], 120)}")
    except OSError:
        pass
    try:
        pend = [ln for ln in open(f"{BQ}/pending_reads.txt") if ln.startswith("PENDING")]
        new = os.path.getmtime(f"{BQ}/pending_reads.txt") > t0
        if pend:
            q.append(f"  pending reads: {len(pend)}" + (" (file changed)" if new else ""))
    except OSError:
        pass
    if q:
        out += ["QUEUE"] + q

    # ARM FAILURES (10 Nov, Builder: 8 lines failed trunkmerge IDENTITY at arm at 22:14Z and 23:35Z and nobody saw them for hours)
    af, arm = [], {}  # arms run in parallel: a failure is matched to its arming line by the private trunk it names
    try:
        for ln in open(f"{BQ}/armq.log", errors="replace"):
            if " arming: " in ln:
                body = ln.split(" arming: ", 1)[1]
                pt = re.search(r"--private-trunk (\S+)", body)
                if pt:
                    arm[pt.group(1)] = " ".join(body.split()[:2])
                continue
            m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) FAILED: (.*)", ln)
            if not m or iso_epoch(m.group(1)) <= t0:
                continue
            pt = re.search(r"\b(nova_ptk_[a-z0-9]+?)(?:_id|_live\w*)?\b", m.group(2))
            what = (arm.get(pt.group(1), "?") + f" ({pt.group(1)})") if pt else "?"
            af.append(f"  {m.group(1)[11:16]}Z {digest.cut(what, 90)}: {digest.cut(m.group(2), 160)}")
    except OSError:
        pass
    if af:
        out += ["ARM FAILURES (armq.log)"] + capped(af, mx)

    # DAEMONS (only dead ones)
    import subprocess
    dead = [n for n, pat in DAEMONS.items()
            if not os.path.exists(f"{BQ}/{n}.nowatch")  # 8 Nov: a daemon stopped on purpose read as dead, and the Builder's tick reacts to dead daemons
            and subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode != 0]
    if dead:
        out += [f"DAEMONS dead: {', '.join(dead)}"]
    try:  # ALARMS: cxe slot waiters stuck (tools/cxe/cxerun.py --health; 5 Nov, 34 spot-checks hung 5 h with free slots)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cxe"))
        import cxerun
        h = cxerun.health()
        if h:
            out += [f"ALARM {h}"]
    except Exception as e:  # noqa: BLE001  (a broken check must not hide the rest)
        out += [f"ALARM check failed: {e}"]
    try:  # 12 Nov (Planner, failed-positive bank rule (b)): tools/lab/fpsites.py's site hits of the last 24 h (one re-test on live each)
        cut = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() - 86400))
        out += [ln.strip() for ln in open("/data/zw4424/st/bq/fpsites.alarm") if ln.startswith("ALARM FPBANK SITE HIT ") and ln.split()[4][:17] >= cut]
    except (OSError, IndexError):
        pass
    try:  # 10 Nov: tools/lab/varguard.py's steps (paused climbs, fewer slots, held shipwatch) while /var is low
        out += [ln.strip() for ln in open(f"{BQ}/varguard.alarm") if ln.startswith("ALARM")]
    except OSError:
        pass
    try:  # /var on maple04 (root's syslog grows ~2 KB per process started; full /var killed the schedd on 1 Nov): only root can clear it
        st = os.statvfs("/var")
        free_gb = st.f_bavail * st.f_frsize / 2**30
        if free_gb < 2.0:
            out += [f"ALARM /var {free_gb:.2f} GB free (root's syslog grows with every process we start: cut process churn; owner -> CSG)"]
    except OSError:
        pass
    try:  # each new live's fuel proof and cleanup-copy check (tools/lab/livefollow.py)
        for ln in open("/data/zw4424/st/lean/follow_status.txt"):
            if ln[:4].isdigit() and iso_epoch(ln.split()[0]) > t0:
                out.append("FOLLOW " + digest.cut(ln.strip(), 220))
    except (OSError, ValueError):
        pass
    try:  # healthwatch's stall checks (every 5 min); a stale file means the watchdog itself stopped
        pa = "/data/zw4424/st/bq/pipealarm.txt"
        if time.time() - os.path.getmtime(pa) > 900:
            out += ["ALARM healthwatch silent for 15+ min: nothing is watching the pipeline (see CLAUDE.md §6)"]
        else:
            out += [ln.strip() for ln in open(pa) if ln.startswith("ALARM")]
    except OSError:
        pass
    if len(out) == 1:
        out.append("  nothing new")
    print("\n".join(out))
    if mark:
        os.makedirs(MARKS, exist_ok=True)
        open(f"{MARKS}/{mark}", "w").write(f"{now:.0f}\n")


if __name__ == "__main__":
    main()
