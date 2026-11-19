#!/usr/bin/env python3
"""sweeparm: arm up to 3 values of one runtime constant from one donor, with no agent in the loop (Builder 9 Nov; owner: "speed it up without
sacrificing accuracy"). Tool Builder.

usage: python3 -I tools/lab/sweeparm.py DONOR:BASE "CONST=v1,v2[,v3]" LANE "SUBJECT" [--with "FLAG=V ..."] [--front] [--dry]
  DONOR's CONST must already be a runtime data flag (flip.py check). --with: the donor's other flips, carried on every line.
What it runs:
  1. the FULL prearm once, on v1 (base, brace, flips, merge, identity at flag 0, fire, fault, private trunk): the value does not change the
     donor-level checks, so they are not repeated per value;
  2. for every further value, in parallel: flip.py check (data-only) and faultcheck (the release build with that value, 100 new maps x 2 seats
     on the pilots: faults and fuel runaway), the only checks the value can change;
  3. armq.py add for each value that passed, on the PARAMETER lane (--parambar: fresh maps only, point >= .505, LOS >= 90% on top of the
     lane bars; CLAUDE.md section 5). That bar, plus at most 3 values per constant per day (logged in bq/sweeparm.log), keeps the
     multiple-testing rate small; each value is read on its own fresh maps by shipcheck as usual.
Exit 0 when at least one value was armed, 1 when none, 2 bad use."""
import concurrent.futures as cf
import datetime
import json
import os
import re
import subprocess
import sys

REPO = "/homes/USER/cambc"
LAB = os.path.join(REPO, "tools/lab")
LOG = "/data/USER/st/bq/sweeparm.log"
CAP = int(os.environ.get("SWEEP_CAP", "3"))


def say(s):
    print(s, flush=True)


def run(cmd, timeout=3600, env=None):
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, **(env or {})))
    return r.returncode, (r.stdout + r.stderr)


def used_today(const):
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    n = 0
    try:
        for ln in open(LOG):
            d = json.loads(ln)
            if d.get("const") == const and d.get("t", "").startswith(today) and d.get("armed"):
                n += 1
    except (OSError, ValueError):
        pass
    return n


def src_of(donor):
    return os.path.join(REPO, "bots", donor, "src")


def main():
    a = sys.argv[1:]
    if len(a) < 4 or ":" not in a[0] or "=" not in a[1]:
        sys.exit(__doc__)
    dn_base, cv, lane, subject = a[0], a[1], a[2], a[3]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    others = opt("--with", "")
    dry = "--dry" in a
    const, vals = cv.split("=", 1)
    vals = [v.strip() for v in vals.split(",") if v.strip()]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", const) or not vals or not all(re.fullmatch(r"-?\d+", v) for v in vals):
        sys.exit("sweeparm: CONST=v1,v2 with integer values")
    left = CAP - used_today(const)
    if left <= 0:
        sys.exit(f"sweeparm: {const} already has {CAP} values armed today (bq/sweeparm.log): the multiple-testing cap")
    if len(vals) > left:
        say(f"sweeparm: only {left} more value(s) of {const} allowed today: arming {vals[:left]}, dropping {vals[left:]}")
        vals = vals[:left]
    donor = dn_base.split(":", 1)[0]
    flips = lambda v: " ".join(x for x in (others, f"{const}={v}") if x)  # noqa: E731
    slug = lambda v: re.sub(r"[^a-z0-9]", "", f"{const[:5].lower()}{v}")[:14]  # noqa: E731
    subj = lambda v: (subject[:max(10, 59 - len(f"{const}={v}"))].rstrip() + f" {const}={v}")[:60]  # noqa: E731
    # 1. the full prearm once, on the first value (it queues nothing: this tool arms every value at the end)
    say(f"sweeparm: full prearm on {const}={vals[0]} (donor-level checks run once)")
    rc, out = run([sys.executable, "-I", f"{LAB}/prearm.py", dn_base, flips(vals[0]), lane, subj(vals[0]), slug(vals[0]), "--parambar", "--no-queue"],
                  timeout=5400)
    verdict = next((ln for ln in out.splitlines() if ln.startswith("PREARM ")), "PREARM ? (no verdict line)")
    say("  " + verdict[:300])
    if not verdict.startswith("PREARM PASS"):
        return 1
    passed = [vals[0]]

    # 2. the value-dependent checks for the rest, in parallel
    def per_value(v):
        rc1, o1 = run([sys.executable, "-I", f"{LAB}/flip.py", "check", src_of(donor), flips(v)], timeout=300)
        if rc1:
            return v, False, "flip check: " + o1.strip()[-200:]
        rc2, o2 = run([sys.executable, "-I", f"{LAB}/faultcheck.py", donor, flips(v)], timeout=3600, env={"FAULTCHECK_PRIO": "20"})
        last = (o2.strip().splitlines() or ["?"])[-1]
        return v, rc2 == 0, "fault: " + last[-200:]
    if len(vals) > 1:
        with cf.ThreadPoolExecutor(len(vals) - 1) as ex:
            for v, ok, why in ex.map(per_value, vals[1:]):
                say(f"  {const}={v}: {'ok' if ok else 'FAIL'} ({why})")
                if ok:
                    passed.append(v)
    # 3. arm every value that passed, on the parameter lane
    armed = []
    for v in passed:
        cmd = [sys.executable, "-I", f"{LAB}/armq.py", "add", dn_base, flips(v), lane, subj(v), slug(v), "--parambar"] + (["--front"] if "--front" in a else [])
        if dry:
            say("  DRY: " + " ".join(cmd[2:]))
            continue
        rc, out = run(cmd, timeout=600)
        say(f"  arm {const}={v}: {'queued' if rc == 0 else 'REFUSED'} {out.strip().splitlines()[-1][:200] if out.strip() else ''}")
        with open(LOG, "a") as f:
            f.write(json.dumps(dict(t=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), donor=dn_base, const=const, value=v,
                                    lane=lane, armed=rc == 0)) + "\n")
        if rc == 0:
            armed.append(v)
    say(f"sweeparm: {const}: {len(passed)} of {len(vals)} values passed checks; armed {armed or ('none (dry)' if dry else 'none')}")
    return 0 if armed or (dry and passed) else 1


if __name__ == "__main__":
    sys.exit(main())
