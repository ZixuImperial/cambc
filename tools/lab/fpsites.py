#!/usr/bin/env python3
"""fpsites: failed-positive bank re-test rule (b) made automatic (Tool Builder, 12 Nov; Planner: "re-test a banked idea once when a shipped
change touches the same site; nothing checks this, so it only happens when someone remembers").

usage: python3 -I tools/lab/fpsites.py [--new BOT --old BOT] [--ver vNNN] [--whole]      (default: live.txt lines 1 and 2: the newest ship)
For the ship: the functions its armed idea changed (funcdiff DONOR BASE, found from the ship's TRUNK= in armq.log; 12 Nov), else (hand-submits,
--whole) the functions the ship changed against the previous live (funcdiff NEW OLD, which also carries earlier ships' bakes). For every ACTIVE entry of the failed-positive bank (/data/zw4424/st/fs/bank.json):
the functions its donor changed (funcdiff DONOR BASE, per DONOR:BASE pair, cached by pair in /data/zw4424/st/fs/sites_cache.json). A function
in both = 'FPBANK SITE HIT: <id> <function> <ship vNNN>', appended to /data/zw4424/st/bq/fpsites.alarm (since.py and healthwatch show it);
an entry whose donor or base bot is gone (and not restorable here) is listed once as 'no site record'. The Planner rules on each hit:
one re-test on live, never a re-roll. Entries under the re-test bar (point < .503, or n < 1,200; rare 420) are written RULED at once (Planner 12 Nov). Read-only on bots; shiprec.py starts it in the background after each ship."""
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
BANK = "/data/zw4424/st/fs/bank.json"
CACHE = "/data/zw4424/st/fs/sites_cache.json"
ALARM = "/data/zw4424/st/bq/fpsites.alarm"
SIG = re.compile(r"^\s+\S+:\d+-\d+\s+\+\d+\s+-\d+\s+(.*)$")


def funcs(a, b):
    """{function names} changed in bots/a relative to bots/b, or None when either bot is missing."""
    if not (os.path.isdir(f"{REPO}/bots/{a}/src") and os.path.isdir(f"{REPO}/bots/{b}/src")):
        return None
    r = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/funcdiff.py", f"bots/{a}", f"bots/{b}"], cwd=REPO,
                       capture_output=True, text=True, timeout=300)
    out = set()
    for ln in r.stdout.splitlines():
        m = SIG.match(ln)
        if not m or m.group(1).startswith("("):
            continue  # '(outside functions: declarations, constants, includes)' is no site
        sig = re.sub(r"__attribute__\s*\(\([^)]*\)\)", " ", m.group(1))  # 12 Nov: '__attribute__((noinline)) bool f(' read as '__attribute__'
        n = re.search(r"([A-Za-z_][A-Za-z0-9_:~<>]*)\s*\(", sig)
        if n:
            if not n.group(1).startswith("__"):
                out.add(n.group(1).split("<")[0])
    return out


ARMQ_LOG = "/data/zw4424/st/bq/armq.log"


def donor_pair(bot):
    """(donor, base) the ship was armed from: its SHIPCHECK/FLIP TRUNK= private trunk, matched to the armq.log 'arming: DONOR:BASE ...
    --private-trunk TRUNK' line; None when not found (hand-submits, old ships). 12 Nov (TB): the ship v previous-live diff also carries the
    bake + deadstrip of earlier ships' flag tables (v814 NSG: 46 functions, 147 hits; its own donor diff: 3 functions)."""
    trunk = None
    for fn in ("SHIPCHECK", "FLIP"):
        try:
            for ln in open(f"{REPO}/bots/{bot}/{fn}"):
                if ln.startswith("TRUNK="):
                    trunk = ln.split("=", 1)[1].strip()
        except OSError:
            pass
        if trunk:
            break
    if not trunk:
        return None
    try:
        lines = open(ARMQ_LOG, errors="replace").read().splitlines()
    except OSError:
        return None
    for ln in reversed(lines):
        if "arming:" in ln and f"--private-trunk {trunk}" in ln:
            m = re.search(r"arming:\s+(\S+?):(\S+)\s", ln)
            if m:
                return m.group(1), m.group(2)
    return None


DIFFS = (f"{REPO}/tools/lab/bank", "/homes/zw4424/condor-work/ideastore/ideas")


def diff_funcs(name):
    """{function names} from the hunk headers of tools/lab/bank/NAME.diff or ideastore/ideas/NAME.diff (Planner 12 Nov: no restore, no build),
    or None when neither file exists."""
    for d in DIFFS:
        p = os.path.join(d, name + ".diff")
        if os.path.exists(p):
            out = set()
            for ln in open(p, errors="replace"):
                if ln.startswith("@@"):
                    ctx = ln.split("@@", 2)[-1]
                    ctx = re.sub(r"__attribute__\(\([^)]*\)\)", " ", ctx)
                    n = re.search(r"([A-Za-z_][A-Za-z0-9_:~]*)\s*\(", ctx)
                    if n and not n.group(1).startswith("__"):
                        out.add(n.group(1))
            return out
    return None


RETEST_PT, RETEST_N, RETEST_N_RARE = 0.503, 1200, 420


def below_bar(e):
    """'' when a bank entry may be re-tested on a site hit, else why not (Planner 12 Nov): point under .503, or n under 1,200 (420 for a rare-lane read)."""
    try:
        pt, n = float(e.get("point")), int(e.get("n"))
    except (TypeError, ValueError):
        return ""
    need = RETEST_N_RARE if e.get("lane") == "rare" else RETEST_N
    if pt < RETEST_PT:
        return f"below re-test bar (point {pt} < {RETEST_PT})"
    if n < need:
        return f"below re-test bar (n {n} < {need})"
    return ""


def main():
    a = sys.argv[1:]
    live = [ln.split() for ln in open("/data/zw4424/st/bq/live.txt") if ln.strip()]
    new = a[a.index("--new") + 1] if "--new" in a else live[0][1]
    old = a[a.index("--old") + 1] if "--old" in a else live[1][1]
    ver = a[a.index("--ver") + 1] if "--ver" in a else live[0][0]
    dp = None if "--whole" in a else donor_pair(new)
    shipped = funcs(*dp) if dp else None
    how = f"donor {dp[0]}:{dp[1]}" if shipped else f"{new} v {old}"
    if not shipped:
        shipped = funcs(new, old)
    if not shipped:
        print(f"fpsites: no changed functions for {new} v {old} (or a bot is missing)")
        return
    try:
        cache = json.load(open(CACHE))
    except (OSError, ValueError):
        cache = {}
    bank = json.load(open(BANK))
    rows = list(bank.values()) if isinstance(bank, dict) else bank
    hits, norec = [], []
    for e in rows:
        if not isinstance(e, dict) or e.get("state") != "active":
            continue
        site = set()
        known = False
        for pair in (e.get("donor") or "").split(","):
            if ":" not in pair:
                continue
            if pair not in cache:
                f = funcs(*pair.split(":", 1))
                cache[pair] = sorted(f) if f is not None else None
            if cache[pair] is not None:
                known = True
                site |= set(cache[pair])
        if not known:  # 12 Nov (Planner): the stored patch's hunk headers, when the donor bots are gone
            key = "diff:" + str(e.get("id"))
            if key not in cache:
                f = diff_funcs(str(e.get("id")))
                cache[key] = sorted(f) if f is not None else None
            if cache[key] is not None:
                known = True
                site |= set(cache[key])
        if not known:
            norec.append(e.get("id"))
            continue
        bar = below_bar(e)
        for fn in sorted(site & shipped):
            if bar:  # 12 Nov (Planner): recorded, but RULED at once, so it does not alarm
                hits.append(f"RULED FPBANK SITE HIT {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: {e.get('id')} {fn} {ver} (bank point {e.get('point')} n {e.get('n')}) | RULED auto: {bar}")
                continue
            hits.append(f"ALARM FPBANK SITE HIT {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: {e.get('id')} {fn} {ver} (bank point {e.get('point')} n {e.get('n')}; Planner rules: one re-test on live)")
    json.dump(cache, open(CACHE + ".tmp", "w"))
    os.replace(CACHE + ".tmp", CACHE)
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    lines = [f"# {stamp} fpsites {ver} ({how}): {len(shipped)} shipped functions; {sum(h.startswith('ALARM') for h in hits)} hit(s) to rule, {sum(h.startswith('RULED') for h in hits)} below the re-test bar; {len(norec)} active entries with no site record"]
    lines += hits
    if norec:
        lines.append(f"# no site record (donor or base gone): {', '.join(x for x in norec if x)[:900]}")
    open(ALARM, "a").write("\n".join(lines) + "\n")
    print("\n".join(lines[:20]))


if __name__ == "__main__":
    main()
