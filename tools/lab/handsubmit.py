#!/usr/bin/env python3
"""handsubmit: the CLAUDE.md section 4.6 hand-submit, plus the live.txt record (Tool Builder, 11 Nov: the Builder's hand-submit v785 was
never written to live.txt, so the pipeline kept v784 as live and auto-shipped xde1 on top of it as v786, without v785's fix).
usage: python3 -I tools/lab/handsubmit.py vNNN BOT "NOTE (<= 80 chars)"
  vNNN  the live version you built on (live.txt's first line must still say it, checked inside the submit lock)
Inside /data/USER/plat/.shipcheck_submit.lock: refuses when live.txt moved or the platform has a newer upload than live.txt;
submits bots/BOT with the note; on "Submitted bot version N" prepends "vN BOT UTC parent=PREV hand" to live.txt. Then run shiprec.py."""
import fcntl, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shipcheck as sc  # noqa: E402

LOCK = "/data/USER/plat/.shipcheck_submit.lock"
LIVE = "/data/USER/st/bq/live.txt"
REPO = "/homes/USER/cambc"


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    ver, bot, note = sys.argv[1], sys.argv[2], sys.argv[3]
    if len(note) > 80:
        sys.exit(f"handsubmit: note is {len(note)} chars (the platform rejects > 80)")
    try:  # 12 Nov ~22:3xZ (owner: "For each submission, write percentage of maps it changes as well"): append affects.py's share if it fits
        rows = [ln.rstrip("\n").split("\t") for ln in open("/data/USER/st/bq/affects.tsv") if f"\t{bot}\t" in ln]
        rows = [p for p in rows if len(p) >= 6 and p[5]]
        if rows and "% maps" not in note:
            p_ = rows[-1]
            add = f" [0% maps, fuel cuts/g {p_[6]}]" if float(p_[5]) == 0 and len(p_) >= 7 and p_[6] else f" [{float(p_[5]):g}% maps]"
            if len(note) + len(add) <= 80:
                note += add
            else:
                print(f"handsubmit: note has no room for '{add.strip()}' (80 chars); shorten it to include the changed-map share")
    except OSError:
        pass
    if not os.path.isdir(os.path.join(REPO, "bots", bot, "src")):
        sys.exit(f"handsubmit: no bots/{bot}")
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        head = open(LIVE).readline().split()
        if not head or head[0] != ver:
            sys.exit(f"handsubmit: live.txt says {head[:2]}, not {ver}: rebuild on the new live")
        pv = sc.platform_live()
        if pv is None:
            sys.exit("handsubmit: the platform listing failed: not submitting blind")
        if pv > int(ver.lstrip("v")):
            sys.exit(f"handsubmit: the platform already has v{pv}, newer than live.txt {ver}: record it first")
        r = subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", sc.CLI, "submit", "-n", note, f"bots/{bot}"],
                           capture_output=True, text=True, timeout=900, cwd=REPO)
        out = r.stdout + r.stderr
        m = re.search(r"Submitted bot version (\d+)", out)
        if not m:
            sys.exit(f"handsubmit: no version in the platform's answer (rc {r.returncode}): {out.strip()[-300:]}")
        v = m.group(1)
        sc.prepend_live(f"v{v} {bot} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} parent={head[1]} hand", LIVE)
    print(f"handsubmit: v{v} = {bot} submitted and written to live.txt (parent {head[1]}). Next: python3 -I tools/lab/shiprec.py \"WHAT CHANGED\"")


if __name__ == "__main__":
    main()
