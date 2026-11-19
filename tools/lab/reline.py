#!/usr/bin/env python3
"""reline: after a ship, the next baseline trunk: the newest nova_cbase_tNN with LIVE's own flag changes as defaults (Tool builder, 6 Nov; owner: "why are iterations so
slow"; shipcheck 1762 was refused on nova_cbase_t26: 'live's flag values missing'. That refusal is right: a flip of such a trunk would turn the shipped flags off).
armq's own line (nova_trunkNN) is rebuilt from live on every ship; the cbase line is not, and b1405 made nova_cbase_t28 by hand. This does that step:
  1. the flags live changed against its parent, by value. Only those: other flags of the head are the line's own work and stay;
  2. a newbot.sh copy of the head with those `#define FLAG V` edits;
  3. shipcheck's own base_check v live, then mergecheck NEW LIVE (null identity, build). Only then a registry line. A head with a flag live lacks, a failed check: no trunk,
     the reason in bq/reline.log and on stdout, exit 1.
Nothing to do (the head already carries them): exit 0. It arms nothing and never touches the head.
usage: python3 -I tools/lab/reline.py [--head BOT] [--new NAME] [--no-register] [--dry]
armq starts this once per new live (off: touch /data/zw4424/st/bq/reline_OFF). --dry prints the edits only."""
import argparse
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
LAB = f"{REPO}/tools/lab"
sys.path.insert(0, LAB)
BQ = "/data/zw4424/st/bq"
REG = os.environ.get("TRUNK_REGISTRY", "/homes/zw4424/condor-work/reports/trunk_registry.md")


def say(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}"
    print(line, flush=True)
    with open(f"{BQ}/reline.log", "a") as f:
        f.write(line + "\n")


def live_pair():
    a, b = open(f"{BQ}/live.txt").read().splitlines()[:2]
    return a.split()[0], a.split()[1], b.split()[1]


def heads():
    """cbase trunk names by registry order, newest last, that still exist"""
    names = re.findall(r"^- (nova_cbase_t\d+)\b", open(REG, errors="replace").read(), re.M)
    return [n for n in names if os.path.isdir(f"{REPO}/bots/{n}/src")]


def next_name(names):
    return f"nova_cbase_t{max(int(n.rsplit('t', 1)[1]) for n in names) + 1:02d}"


def edit(src, flags):
    """FLAG=V edits of `#define FLAG <int>`; each must match exactly once across the sources. -> [] or the flags it could not set"""
    bad = []
    files = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs if f.endswith((".h", ".cpp", ".cc"))]
    text = {p: open(p, errors="surrogateescape").read() for p in files}
    for k, v in flags.items():
        rx = re.compile(rf"^([ \t]*#[ \t]*define[ \t]+{re.escape(k)}[ \t]+)-?\d+([ \t]*(?://.*)?)$", re.M)
        hit = [p for p, t in text.items() if rx.search(t)]
        if len(hit) != 1 or len(rx.findall(text[hit[0]])) != 1:
            bad.append(k)
            continue
        text[hit[0]] = rx.sub(lambda m: f"{m.group(1)}{v}{m.group(2)}", text[hit[0]])
    if not bad:
        for p in files:
            with open(p, "w", errors="surrogateescape") as f:
                f.write(text[p])
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--head")
    ap.add_argument("--new")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--dry", action="store_true")
    o = ap.parse_args()
    import shipcheck as sc
    ver, live, parent = live_pair()
    names = heads()
    head = o.head or names[-1]
    lv, pv, hv = sc.flag_values(live), sc.flag_values(parent), sc.flag_values(head)
    own = {k: v for k, v in lv.items() if (k in pv and pv[k] != v) or (k not in pv and v != "0")}  # shipcheck.flags_carried's rule, so the two can't disagree
    want = {k: v for k, v in own.items() if hv.get(k) != v}
    if not want:
        say(f"reline {ver}: {head} already carries live's {len(own)} changed flag(s)")
        return 0
    miss = sorted(k for k in want if k not in hv)
    if miss:
        say(f"reline {ver}: NO TRUNK: {head} has no table for {' '.join(miss)}: merge {live} first")
        return 1
    fl = " ".join(f"{k}={v}" for k, v in want.items())
    if o.dry:
        print(f"{head} + {fl}")
        return 0
    new = o.new or next_name(names)
    t0 = time.time()
    r = subprocess.run(["sh", f"{LAB}/newbot.sh", head, new], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        say(f"reline {ver}: NO TRUNK: newbot {new}: {(r.stdout + r.stderr).strip()[-200:]}")
        return 1
    bad = edit(f"{REPO}/bots/{new}/src", want)
    if bad:
        say(f"reline {ver}: NO TRUNK: {new} left unpublished: no single #define for {' '.join(bad)}")
        return 1
    ok, why = sc.base_check(new, live, parent)
    if not ok:
        say(f"reline {ver}: NO TRUNK: {new} left unpublished: base_check v {live}: {why}")
        return 1
    r = subprocess.run([sys.executable, "-I", f"{LAB}/mergecheck.py", new, live, "--quiet"], cwd=REPO, capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    if r.returncode:
        say(f"reline {ver}: NO TRUNK: {new} left unpublished: mergecheck v {live}: {tail[0][:200]}")
        return 1
    if not o.no_register:
        with open(REG, "a") as f:
            f.write(f"- {new} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}; reline): {head} with {ver}'s flags in source ({fl}); identity v {live}: {tail[0][:120]}\n")
    say(f"reline {ver}: {new} = {head} + {fl}; {tail[0][:120]} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
