#!/usr/bin/env python3
"""paramdiff: is CAND's source diff vs BASE a pure parameter change (numeric literals / #define values only)?

usage: python3 -I tools/lab/paramdiff.py CAND BASE      (bots/ names or dirs; exit 0 = param-only, 1 = not, 2 = error)
Tool builder, 30 Oct (Builder: LANE=param skips ubaudit on such diffs; sweepd.py checks every variant it builds).
Param-only means every changed src/ file differs from BASE's only in lines whose numeric literals changed, after
  - comments (// to the end of a line, when no '"' comes before it) and runs of whitespace are ignored,
  - every numeric literal (123, 0.7f, 1e-3, .5, 60u) is replaced by '#';
and the changed lines pair up one for one (no line added or removed, except blank or comment-only ones). Not param-only:
  - a file added or removed; a sign, hex or identifier change (normalized lines differ);
  - a changed literal inside [...] or on a 'for (' line (an array index, size or loop bound can read out of bounds);
  - a changed #define whose name is used inside [...], <...> (an array or template size) or in a 'for (' header anywhere
    in src/ (the same out-of-bounds risk, one step removed).
"""
import difflib
import os
import re
import sys

REPO = "/homes/USER/cambc"
NUM = re.compile(r"(?<![\w.])(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFlLuU]*(?![\w.])")
DEF = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\b")


def code(line):
    """line without its // comment (kept when a '"' comes before the //)."""
    i = line.find("//")
    return line[:i] if i >= 0 and '"' not in line[:i] else line


def norm(line):
    return " ".join(NUM.sub("#", code(line)).split())


def trivial(line):
    s = line.strip()
    return not s or s.startswith("//")


def src_dir(bot):
    d = bot if os.sep in bot else os.path.join(REPO, "bots", bot)
    return os.path.join(os.path.realpath(d), "src")


def files(d):
    out = {}
    for r, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, d)] = p
    return out


def check(cand, base):
    """-> dict(ok, reason, changes=[(file, line, old_text, new_text)], defines=[names])."""
    cd, bd = src_dir(cand), src_dir(base)
    if not os.path.isdir(cd) or not os.path.isdir(bd):
        raise FileNotFoundError(f"no src/ in {cand if not os.path.isdir(cd) else base}")
    cf, bf = files(cd), files(bd)
    if set(cf) != set(bf):
        extra = sorted(set(cf) ^ set(bf))
        return dict(ok=False, reason=f"files added or removed: {' '.join(extra[:5])}", changes=[], defines=[])
    changes, defines = [], set()
    for rel in sorted(cf):
        a, b = open(bf[rel], errors="replace").read(), open(cf[rel], errors="replace").read()
        if a == b:
            continue
        al, bl = a.splitlines(), b.splitlines()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            old = [x for x in al[i1:i2] if not trivial(x)]
            new = [(j1 + k + 1, x) for k, x in enumerate(bl[j1:j2]) if not trivial(x)]
            if len(old) != len(new):
                return dict(ok=False, reason=f"{rel}:{j1 + 1}: lines added or removed", changes=changes, defines=[])
            for o, (ln, n) in zip(old, new):
                if norm(o) != norm(n):
                    return dict(ok=False, reason=f"{rel}:{ln}: not only numbers changed: {n.strip()[:70]!r}",
                                changes=changes, defines=[])
                code_o, code_n = code(o), code(n)
                if code_o.split() == code_n.split():
                    continue  # a comment-only edit
                if re.search(r"\bfor\s*\(", code_n):
                    return dict(ok=False, reason=f"{rel}:{ln}: a number changed on a for-loop line", changes=changes,
                                defines=[])
                for x, y in zip(NUM.finditer(code_o), NUM.finditer(code_n)):
                    if x.group(0) != y.group(0) and code_n[:y.start()].count("[") > code_n[:y.start()].count("]"):
                        return dict(ok=False, reason=f"{rel}:{ln}: a number changed inside [...]", changes=changes,
                                    defines=[])
                dm = DEF.match(code_n)
                if dm:
                    defines.add(dm.group(1))
                changes.append((rel, ln, o.strip(), n.strip()))
    if not changes:
        return dict(ok=False, reason="no numeric change (identical, or comments only)", changes=[], defines=[])
    text = "\n".join(open(p, errors="replace").read() for p in cf.values())
    for name in sorted(defines):
        w = rf"\b{re.escape(name)}\b"
        if (re.search(rf"\[[^\]\n]*{w}", text) or re.search(rf"<[^<>;\n]*{w}[^<>;\n]*>", text)
                or re.search(rf"\bfor\s*\([^)\n]*{w}", text)):
            return dict(ok=False, reason=f"#define {name} sizes an array/template or bounds a loop", changes=changes,
                        defines=sorted(defines))
    return dict(ok=True, reason=f"param-only: {len(changes)} line(s) in "
                f"{len({c[0] for c in changes})} file(s)" + (f", defines {' '.join(sorted(defines))}" if defines else ""),
                changes=changes, defines=sorted(defines))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    try:
        r = check(sys.argv[1], sys.argv[2])
    except (OSError, FileNotFoundError) as e:
        print(f"paramdiff: {e}")
        sys.exit(2)
    print(("PARAM-ONLY " if r["ok"] else "NOT PARAM-ONLY ") + r["reason"])
    for f, ln, o, n in r["changes"]:
        print(f"  {f}:{ln}: {o[:90]}\n  {' ' * len(f)}  -> {n[:90]}")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
