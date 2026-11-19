#!/usr/bin/env python3
"""pending: the reads left unfinished when an agent's box ended, and their state. Tool builder, 3 Nov (owner: "make sure promising upgrades
are not missed by time out"; primer RULE TIMEOUT: agents append 'PENDING: <what> <TAG or dir> <command to read it> <bar>' to
/data/USER/st/bq/pending_reads.txt; shipcheck appends a capacity INCONCLUSIVE that came back INCONCLUSIVE after its one re-arm).

usage: python3 -I tools/lab/pending.py                 every PENDING line, numbered, with its state, then the inforead runs
       python3 -I tools/lab/pending.py done N [note]   mark line N finished (pending_reads.done; the line itself stays)
       python3 -I tools/lab/pending.py --stale [--apply]  WAITING lines that no longer decide anything (5 Nov, Builder + TB):
         SHIPPED  every FLAG=V the line names already has that value in the live bot;
         ENGINE   its newest bot predates the engine 3.0.0 switch (2026-11-04T23:35:46Z: older reads do not count for shipping);
         OLDBASE  its newest bot is older than the bot shipped 3 ships ago (owner: an old read counts only on the current base;
                  re-open it with tools/lab/reopen.py and ONE fresh read on live instead).
         Lines saying HOLD are never marked (listed apart). --apply marks the rest done with that reason (pending_reads.done; the lines stay and can be re-read).
State per line, from the tags and paths it names:
  DONE     marked with `done`, or every named run has finished: an inforead TAG with .done, a gate dir with verdict.txt,
           shipcheck_N.txt, a condab run's BQ/NAME.condor.txt with its summary line, a dir holding .done / result.txt
  RUNNING  some process's command line names one of its tags or dirs
  WAITING  neither: someone has to start or read it (the line's own command says how)
A line naming nothing this can check reads WAITING until marked done."""
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
BQ = "/data/USER/st/bq"
FILE = BQ + "/pending_reads.txt"
DONE = BQ + "/pending_reads.done"
TOKEN = re.compile(r"(/data/USER/\S+?)(?=[\s,;)'\"]|$)|\b(ir[A-Za-z0-9]+_\d{8})\b|\bshipcheck_(\d+)\b|\b((?:fp|pc|pl|nd|cf|kg)[a-z]*\d[A-Za-z0-9_]*)\b")  # a condab run name has a digit (fp1259, pcirtb_03125938_0)


def lines():
    out = []
    for i, x in enumerate(open(FILE).read().splitlines() if os.path.exists(FILE) else ()):
        if x.strip().startswith("PENDING"):
            out.append((len(out) + 1, x.strip()))
    return out


def marked():
    m = {}
    for x in open(DONE).read().splitlines() if os.path.exists(DONE) else ():
        p = x.split(" ", 2)
        if len(p) >= 2 and p[1].isdigit():
            m[int(p[1])] = x
    return m


def cmdlines():
    skip, p = set(), os.getpid()
    while p > 1:  # this process and its parents (the shell that ran it names the tags too)
        skip.add(p)
        try:
            p = int(open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) not in skip:
            try:
                out.append(open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace"))
            except OSError:
                pass
    return out


def finished(kind, v):
    """True / False for a token this can judge, None for one it can't."""
    if kind == "path":
        if os.path.isdir(v):
            return any(os.path.exists(os.path.join(v, f)) for f in (".done", "verdict.txt", "result.txt", "summary.txt"))
        if os.path.isfile(v):
            return True
        return None
    if kind == "ir":
        d = f"/data/USER/st/info/{v}"
        return os.path.exists(d + "/.done") if os.path.isdir(d) else None
    if kind == "sc":
        return os.path.exists(f"{BQ}/shipcheck_{v}.txt")
    if kind == "run":
        f = f"{BQ}/{v}.condor.txt"
        if not os.path.exists(f):
            return None
        return re.search(r"^\s+ALL\s+n\s+\d+", open(f, errors="replace").read(), re.M) is not None
    return None


def state(text, procs):
    toks = []
    for m in TOKEN.finditer(text):
        path, ir, sc, run = m.groups()
        toks += [("path", path.rstrip(".:"))] if path else [("ir", ir)] if ir else [("sc", sc)] if sc else [("run", run)]
    names = {os.path.basename(v.rstrip("/")) if k == "path" else v for k, v in toks if k != "sc"}  # a shipcheck's tag isn't on its command line
    names = {n for n in names if len(n) >= 5}
    if any(n in c for c in procs for n in names):
        return "RUNNING", toks
    judged = [finished(k, v) for k, v in toks]
    judged = [j for j in judged if j is not None]
    if judged and all(judged):
        return "DONE", toks
    return "WAITING", toks


def bot_no(name):
    m = re.match(r"nova_b(\d+)_", name)
    return int(m.group(1)) if m else None


def stale(rows, mk, procs):
    """-> {line: reason} for WAITING lines that no longer decide anything (see the docstring)."""
    live_lines = [ln.split() for ln in open(BQ + "/live.txt") if ln.strip()]
    live = live_lines[0][1]
    nums = [bot_no(f[1]) for f in live_lines if len(f) > 1 and bot_no(f[1])]
    old3 = nums[3] if len(nums) > 3 else 0
    eng = min((bot_no(f[1]) for f in live_lines if len(f) > 2 and f[2] >= "2026-11-04T23:35:46Z" and bot_no(f[1])), default=0)
    src = os.path.join(REPO, "bots", live, "src")
    defs = {}
    for f in os.listdir(src):
        if f.endswith((".h", ".cpp")):
            for m in re.finditer(r"^#define (\w+)\s+\(?(-?\d+)\)?", open(os.path.join(src, f), errors="replace").read(), re.M):
                defs[m.group(1)] = m.group(2)
    out = {}
    for i, x in rows:
        if i in mk or state(x, procs)[0] != "WAITING":
            continue
        if "HOLD" in x:
            continue  # an owner/Builder hold decides when it runs: never marked stale (listed apart by --stale)
        flips = re.findall(r"\b([A-Z][A-Z0-9_]{2,})=(-?\d+)\b", x)
        if flips and all(defs.get(k) == v for k, v in flips):
            out[i] = "SHIPPED: " + " ".join(f"{k}={v}" for k, v in flips) + f" already in live {live}"
            continue
        bots = [int(n) for n in re.findall(r"\bnova_b(\d+)_", x)] + [int(n) for n in re.findall(r"\bb(\d{3,4})\b", x)]
        if not bots:
            continue
        nb = max(bots)
        if eng and nb < eng:
            out[i] = f"ENGINE: newest bot b{nb} predates the 3.0.0 switch (first 3.0.0 ship b{eng})"
        elif old3 and nb < old3:
            out[i] = f"OLDBASE: newest bot b{nb} older than the ship 3 back (b{old3}); reopen once on live if still wanted"
    return out


def main():
    a = sys.argv[1:]
    if a[:1] == ["--stale"]:
        mk, procs, rows = marked(), cmdlines(), lines()
        st = stale(rows, mk, procs)
        text = dict(rows)
        for i, why in sorted(st.items()):
            print(f"{i:3d} {why} | {text[i][:150]}")
        kinds = {}
        for why in st.values():
            kinds[why.split(":")[0]] = kinds.get(why.split(":")[0], 0) + 1
        waiting = sum(1 for i, x in rows if i not in mk and state(x, procs)[0] == "WAITING")
        holds = [i for i, x in rows if i not in mk and "HOLD" in x and state(x, procs)[0] == "WAITING"]
        if holds:
            print(f"# on HOLD (kept, never marked stale): lines {', '.join(map(str, holds))}")
        print(f"# {len(st)} of {waiting} waiting lines are stale: {kinds}" + ("" if "--apply" in a else " (DRY: --apply marks them done)"))
        if "--apply" in a:
            with open(DONE, "a") as f:
                for i, why in sorted(st.items()):
                    f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {i} stale {why}\n")
            print(f"marked {len(st)} lines done (pending_reads.done)")
        return
    if a[:1] == ["done"] and len(a) >= 2 and a[1].isdigit():
        n = int(a[1])
        if not any(i == n for i, _ in lines()):
            sys.exit(f"pending: no line {n}")
        with open(DONE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {n} {' '.join(a[2:]) or 'done'}\n")
        return print(f"line {n} marked done")
    if a:
        sys.exit(__doc__)
    mk, procs = marked(), cmdlines()
    rows = lines()
    count = {"DONE": 0, "RUNNING": 0, "WAITING": 0}
    for i, x in rows:
        st = ("DONE", []) if i in mk else state(x, procs)
        count[st[0]] += 1
        note = f" ({mk[i].split(' ', 2)[2]})" if i in mk else ""
        print(f"{i:3d} {st[0]:7s}{note} {x[:260]}")
    print(f"# {len(rows)} pending lines in {FILE}: {count['WAITING']} waiting, {count['RUNNING']} running, {count['DONE']} done\n")
    print("inforead runs:", flush=True)
    subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/inforead.py"), "status"])


if __name__ == "__main__":
    main()
