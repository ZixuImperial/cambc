#!/usr/bin/env python3
"""hunkdup: does a new armq line carry code that another waiting, arming or running line already carries? (Tool Builder 6ad907,
11 Nov ~01:45Z; Builder/owner check-in: lfb127 duplicated x3i31c's LBM1/LBE1 hunks and only the Rule Checker caught it.)

usage: python3 -I tools/lab/hunkdup.py DONOR:BASE [DONOR:BASE ...] [--self SLUG] [--strict] [--quiet]
  DONOR:BASE  the new line's donors (as in armq add); each donor's change = its src v its base src
  --self SLUG skip that queue line / running check (the line being re-checked)
  --strict    count same-agent overlaps too (default: a donor of the same agent bNNNN is a revision: listed, not counted)
Compared against: every line in bq/armq.txt, every arm journalled in bq/armq_inflight/, and every RUNNING shipcheck (its donors
from armq.log 'diff model for SLUG: live X + DONORS').
Overlap rule: an added line counts when it is real code (stripped, >= 12 chars, not a comment or brace). Two changes overlap when
they share >= 3 such added lines and the shared part is >= 30% of the smaller change, or they share one identical hunk of >= 2
such lines. Flag-table values and flag macro names are normalised (FOO_BITS = 7 == BAR_BITS = 3; TOM_ON(N) == BF12_ON(N)); // comments are dropped.
Output: one line per overlap, then a JSON line {"overlaps": [...], "checked": N}. Exit 0 = none, 1 = overlap, 2 = error."""
import difflib
import glob
import json
import os
import re
import sys

REPO = "/homes/zw4424/cambc"
BQ = "/data/zw4424/st/bq"
STRAY = (".orig", ".rej")
CODE_EXT = (".cc", ".cpp", ".h", ".hpp", ".c")
FLAGVAL = re.compile(r"\b([A-Z][A-Z0-9_]*_(?:BITS|ON|K|CAP|B|N|R|WIN|ROUNDS|MAX|MIN)\b\s*[=(,]\s*)-?\d+")
_cache = {}


def src_of(bot):
    if bot not in _cache:
        d = os.path.realpath(f"{REPO}/bots/{bot}") + "/src"
        if not os.path.isdir(d):
            raise FileNotFoundError(f"no src for {bot} ({d})")
        _cache[bot] = {f: open(os.path.join(d, f), encoding="utf-8", errors="replace").read().splitlines()
                       for f in os.listdir(d) if f.endswith(CODE_EXT) and not f.endswith(STRAY) and os.path.isfile(os.path.join(d, f))}
    return _cache[bot]


FLAGNAME = re.compile(r"\b[A-Z][A-Z0-9]*_(ON|CNT|TAB|BITS|FIRE|FC)\b")  # 11 Nov (Builder: tom2 v bf12b, same code under TOM_ON v BF12_ON)
FLAGFN = re.compile(r"\b[a-z][a-z0-9]*_fc_(\d+)\b")  # per-line fire-count helpers (nbf_fc_4)
COMMENT = re.compile(r"\s*//.*$")


def norm(line):
    s = COMMENT.sub("", line)
    s = " ".join(s.split())
    s = FLAGVAL.sub(r"\1N", s)
    s = FLAGNAME.sub(r"FLAG_\1", s)
    s = FLAGFN.sub(r"flag_fc_\1", s)
    return s


BOILER = re.compile(r"^(#define FLAG_(BITS|ON|CNT|FIRE)\b|inline const volatile int FLAG_TAB\[|#include\b|#pragma once|namespace [\w:]+ ?\{?$|\} ?// namespace|using namespace )")
# 11 Nov (Builder: DTA v tkf1 flagged on 3 newfeat.py template lines): the flag-table stub, includes and namespace lines are boilerplate


def real(s):
    return len(s) >= 12 and not s.startswith(("//", "/*", "*")) and not BOILER.match(s) and s.strip("{}();, ") != ""


def change(donor):
    """donor 'D:B' -> (added real lines set, [hunk tuples]) of D's src v B's src."""
    d, _, b = donor.partition(":")
    if not b:
        raise ValueError(f"donor {donor!r} has no :BASE")
    ds, bs = src_of(d), src_of(b)
    added, hunks = set(), []
    for f in sorted(set(ds) | set(bs)):
        a, c = bs.get(f, []), ds.get(f, [])
        if a == c:
            continue
        sm = difflib.SequenceMatcher(None, a, c, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("replace", "insert"):
                h = tuple(x for x in (norm(y) for y in c[j1:j2]) if real(x))
                if h:
                    hunks.append(h)
                    added.update(h)
    return added, hunks


def agent(donor):
    m = re.match(r"nova_(b\d+)_", donor.split(":")[0])
    return m.group(1) if m else donor


def others(skip):
    """[(label, [donors])] for queued, in-flight and running lines."""
    out = []
    try:
        for x in open(os.path.join(BQ, "armq.txt")).read().splitlines():
            try:
                r = json.loads(x)
            except ValueError:
                continue
            if r.get("slug") == skip or not r.get("donors"):
                continue
            out.append((f"queued {r.get('slug') or r['flips']}", r["donors"].split(",")))
    except OSError:
        pass
    for p in glob.glob(os.path.join(BQ, "armq_inflight", "*")):
        try:
            r = json.loads(open(p).read().splitlines()[0])
            if r.get("slug") != skip and r.get("donors"):
                out.append((f"arming {r.get('slug') or os.path.basename(p)}", r["donors"].split(",")))
        except (OSError, ValueError, IndexError, AttributeError):
            continue
    running = set()
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            c = open(p).read().split("\0")
            i = next(k for k, x in enumerate(c) if x.endswith("shipcheck.py"))
            running.add(c[i + 1])
        except (OSError, StopIteration, IndexError):
            continue
    if running:
        models = {}
        try:
            for ln in open(os.path.join(BQ, "armq.log"), errors="replace"):
                m = re.search(r"diff model for (\S+): live \S+ \+ (\S+)", ln)
                if m:
                    models[m.group(1)] = m.group(2).split(",")
        except OSError:
            pass
        for bot in sorted(running):
            slug = bot.split("_", 2)[-1]
            if slug == skip or slug not in models:
                continue
            out.append((f"running {slug}", models[slug]))
    return out


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if a else 2
    skip = a[a.index("--self") + 1] if "--self" in a else None
    strict, quiet = "--strict" in a, "--quiet" in a
    mine = [x for i, x in enumerate(a) if ":" in x and not x.startswith("--") and (i == 0 or a[i - 1] != "--self")]
    if not mine:
        print("hunkdup: no DONOR:BASE given", file=sys.stderr)
        return 2
    try:
        new = [(d, *change(d)) for d in mine]
    except (OSError, ValueError) as e:
        print(json.dumps({"error": str(e)[:300]}))
        return 2
    mydonors = {d.split(":")[0] for d in mine}
    found, checked = [], 0
    for label, donors in others(skip):
        for od in donors:
            if od.split(":")[0] in mydonors:
                continue  # the same donor dir (a variant with other flips) is expected to share its code
            try:
                oadd, ohunks = change(od)
            except (OSError, ValueError):
                continue
            checked += 1
            ohs = {h for h in ohunks if len(h) >= 2}
            for d, add, hunks in new:
                shared = add & oadd
                same_hunk = [h for h in hunks if len(h) >= 2 and h in ohs]
                small = min(len(add), len(oadd)) or 1
                if not (same_hunk or (len(shared) >= 3 and len(shared) / small >= 0.30)):
                    continue
                rev = agent(d) == agent(od)
                f = dict(new=d, other=od, where=label, shared=len(shared), frac=round(len(shared) / small, 2),
                         same_hunks=len(same_hunk), same_agent=rev, counted=strict or not rev,
                         sample=sorted(shared, key=len, reverse=True)[:2])
                found.append(f)
                if not quiet:
                    print(f"{'OVERLAP' if f['counted'] else 'revision'}: {d} shares {len(shared)} code lines ({f['frac']:.0%} of the smaller change"
                          f"{', ' + str(len(same_hunk)) + ' identical hunk(s)' if same_hunk else ''}) with {label} {od}"
                          + (" (same agent: a revision?)" if rev else ""))
    print(json.dumps({"overlaps": found, "checked": checked}))
    return 1 if any(f["counted"] for f in found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
