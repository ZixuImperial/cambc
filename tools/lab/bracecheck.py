#!/usr/bin/env python3
"""bracecheck: a line inserted right after an unbraced if/for/while/else in BASE becomes that statement's body, and BASE's real body
then runs unconditionally (8 Nov, b1554 ESC: a flag-0 hook placed inside an unbraced if in want_bank played .26 at flag 0; found by b1573,
whose check this is). Lines that can't take over the body are not flagged: a brace, a comment, a preprocessor line, a blank line.

usage: python3 -I tools/lab/bracecheck.py CAND BASE        bots or src dirs; prints each hit, exit 1 on a hit not waived
Waivers (known false positives): /data/USER/st/bq/bracecheck_waive.txt, one per line: FILE:TEXT (TEXT: a substring of the inserted
line, or of the control line) with a '#' comment saying why. Used by prearm.py and shipcheck's base check."""
import difflib
import os
import re
import sys

REPO = "/homes/USER/cambc"
WAIVE = os.environ.get("BRACECHECK_WAIVE", "/data/USER/st/bq/bracecheck_waive.txt")
CTL = re.compile(r"^\s*(?:\}\s*)?(if|for|while|else\s+if)\b.*\)\s*(//.*)?$|^\s*(?:\}\s*)?else\s*(//.*)?$")
INERT = re.compile(r"^\s*($|\{|//|/\*|\*|#)")


def src(x):
    if os.path.isdir(os.path.join(x, "src")):
        return os.path.join(x, "src")
    if os.path.isdir(x):
        return x
    return os.path.join(os.path.realpath(os.path.join(REPO, "bots", x)), "src")


def waivers():
    out = []
    try:
        for ln in open(WAIVE):
            ln = ln.split("#", 1)[0].strip()
            if ":" in ln:
                f, t = ln.split(":", 1)
                out.append((f.strip(), t.strip()))
    except OSError:
        pass
    return out


def stmts(lines):
    """top-level statements in LINES, roughly: code lines ending in ';' at brace depth 0, and each braced block closing back to depth 0
    as one (`if (..) { a; b; }` is one statement); a comment is ignored, `if (..)` alone is the head of the next one"""
    n = d = 0
    for x in lines:
        i = x.find("//")
        code = (x if i < 0 else x[:i]).strip()
        if not code:
            continue
        d0 = d
        d += code.count("{") - code.count("}")
        if d0 == 0 and d == 0 and code.endswith(";"):
            n += 1
        elif d0 > 0 and d <= 0:
            n += 1
            d = 0
    return n


def hits(cand, base):
    """-> [(file, line, control line, inserted line, base body, waived)]"""
    cs, bs, wv, out = src(cand), src(base), waivers(), []
    for fn in sorted(os.listdir(bs)):
        if not fn.endswith((".cpp", ".cc", ".h")) or not os.path.exists(os.path.join(cs, fn)):
            continue
        a = open(os.path.join(bs, fn), errors="replace").read().split("\n")
        b = open(os.path.join(cs, fn), errors="replace").read().split("\n")
        if a == b:
            continue
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op not in ("insert", "replace") or j1 == 0 or i1 == 0 or i1 >= len(a):
                continue
            ctl, new = b[j1 - 1], b[j1]
            if not CTL.match(ctl) or a[i1 - 1] != ctl or INERT.match(new):
                continue
            if new.strip() == a[i1].strip():
                continue  # difflib aligned an identical copy of the body here (a moved block): the body is unchanged
            if op == "replace" and stmts(b[j1:j2]) <= stmts(a[i1:i2]):
                continue  # 10 Nov (b1791 FB bundle): the body itself was rewritten (a comment edit, or one statement as `if (..) x;`), nothing pushed out
            w = any(f == fn and (t in new or t in ctl) for f, t in wv)
            out.append((fn, j1 + 1, ctl.strip(), new.strip(), a[i1].strip(), w))
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    bad = 0
    for fn, ln, ctl, new, body, w in hits(sys.argv[1], sys.argv[2]):
        print(f"{'WAIVED ' if w else ''}{fn}:{ln}: '{new[:70]}' inserted after unbraced '{ctl[:70]}' (its body was '{body[:60]}')")
        bad += not w
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
