#!/usr/bin/env python3
"""smerge: a structured 3-way merge for nova sources and FLIP files (Tool builder, 6 Nov; owner: "can we just not use git diffs if they are in
different sections" - most of today's rebases were not real conflicts: two donors adding flag tables at one spot, FLIP files, edits to
neighbouring functions). Used only when git merge-file reports a conflict (trunkmerge, armq's merge3). mergecheck (20/20 null identity,
build) and rulestest still decide whether a merged trunk is right; this only stops non-conflicts from stopping the line.

C++ (.h/.cpp): each file is cut into top-level UNITS - a function, a declaration, a flag table, a #define / #include, a struct - with the
comments and blank lines above it; namespace / extern "C" braces are transparent; #if/#else/#endif/#pragma lines and namespace closers are
glued to the unit after them. Units are keyed by their head (text before the body: a signature, 'inline const volatile int X_TAB[2]',
'#define X'), repeated heads by occurrence. Per key: only one side changed it -> that side; both changed it -> git merge-file on that unit
alone, conflict only if that fails; a unit new on one side -> kept, placed after the unit it follows on that side; new on both with
different text -> conflict; deleted on one side and changed on the other -> conflict.
FLIP: KEY=VALUE lines; FLIPS is a union of FLAG=V (conflict only when one flag gets two values); derived keys (TRUNK, TRUNK_HASH, DATA_BYTES,
WASM) keep CUR's.

usage: python3 -I tools/lab/smerge.py CUR BASE DONOR [-o OUT]   (files) -> exit 0 merged, 1 conflict (the reason on stderr)"""
import os
import re
import subprocess
import sys
import tempfile

GLUE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|else|elif|endif|pragma)\b")


def _units(text):
    """-> [(key, text)] top-level units of a C++ source"""
    units, buf, stack = [], [], []  # stack: 'N' (transparent namespace brace) or 'B'
    i, n, start = 0, len(text), 0
    head_from = 0

    def bdepth():
        return sum(1 for x in stack if x == "B")

    def cut(end):
        nonlocal start, head_from
        units.append(text[start:end])
        start = end
        head_from = end
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c == "#" and bdepth() == 0 and text[text.rfind("\n", 0, i) + 1:i].strip() == "":
            j = i
            while True:  # a preprocessor line (with continuations)
                k = text.find("\n", j)
                if k < 0:
                    k = n
                    break
                if text[k - 1] == "\\":
                    j = k + 1
                    continue
                break
            line = text[i:k]
            end = min(n, k + 1)
            if GLUE.match(line):
                i = end  # glued to the next unit
                continue
            cut(end)
            i = end
            continue
        if c == "{":
            pre = re.sub(r"//[^\n]*|/\*.*?\*/", " ", text[head_from:i], flags=re.S)
            last = pre.strip().split(";")[-1]
            if bdepth() == 0 and re.search(r'(^|\s)(inline\s+)?namespace(\s+[\w:]+)?\s*$|extern\s+"C"\s*$', last):
                stack.append("N")
                i += 1
                cut(i)  # the namespace opener is its own unit
                continue
            stack.append("B")
        elif c == "}":
            if stack:
                t = stack.pop()
                if t == "N":
                    i += 1
                    # a namespace closer: glue to the next unit (keep it with what follows)
                    continue
                if bdepth() == 0:
                    j = i + 1
                    while j < n and text[j] in " \t":
                        j += 1
                    if j < n and text[j] == ";":
                        j += 1
                    k = text.find("\n", j)
                    end = n if k < 0 else k + 1
                    if text[j:end].strip() == "" or text[j:end].lstrip().startswith("//"):
                        cut(end)
                        i = end
                        continue
        elif c == ";" and bdepth() == 0:
            k = text.find("\n", i)
            end = n if k < 0 else k + 1
            if text[i + 1:end].strip() == "" or text[i + 1:end].lstrip().startswith("//"):
                cut(end)
                i = end
                continue
        i += 1
    if start < n:
        units.append(text[start:])
    out, seen = [], {}
    for u in units:
        k = _key(u)
        seen[k] = seen.get(k, 0) + 1
        out.append((f"{k}#{seen[k]}", u))
    return out


def _key(u):
    s = re.sub(r"//[^\n]*|/\*.*?\*/", " ", u, flags=re.S)
    s = "\n".join(ln for ln in s.split("\n") if not GLUE.match(ln))
    s = s.strip()
    m = re.match(r"#\s*(define|undef)\s+(\w+)", s)
    if m:
        return f"#{m.group(1)} {m.group(2)}"
    m = re.match(r"#\s*include\s+(\S+)", s)
    if m:
        return f"#include {m.group(1)}"
    cut = len(s)
    for ch in "{=;":
        k = s.find(ch)
        if 0 <= k < cut:
            cut = k
    return re.sub(r"\s+", " ", s[:cut]).strip() or "(blank)"


def _merge_text(cur, base, donor):
    with tempfile.TemporaryDirectory() as t:
        ps = []
        for nm, x in (("c", cur), ("b", base), ("d", donor)):
            p = os.path.join(t, nm)
            open(p, "w", encoding="utf-8", errors="surrogateescape").write(x)
            ps.append(p)
        r = subprocess.run(["git", "merge-file", "-p", *ps], capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "surrogateescape"), True
        d3 = subprocess.run(["git", "merge-file", "-p", "--diff3", *ps], capture_output=True).stdout.decode("utf-8", "surrogateescape")
    res = _resolve_inserts(d3)
    return (res, True) if res is not None else (cur, False)


CONFLICT = re.compile(r"^<{7}[^\n]*\n(.*?)^\|{7}[^\n]*\n(.*?)^={7}\n(.*?)^>{7}[^\n]*\n", re.M | re.S)


def _resolve_inserts(d3):
    """Resolve diff3 conflict blocks where one side only ADDED lines at the start or end of the base block and the other rewrote it:
    the rewrite plus the additions (6 Nov: the trunk inlined read_tributes(); a donor appended a line after the call). Any other block -> None."""
    def fix(m):
        o, b, t = m.group(1), m.group(2), m.group(3)
        for x, y in ((t, o), (o, t)):  # x: the side that only added; y: the side that rewrote
            if x.startswith(b) and b:
                return y + x[len(b):]
            if x.endswith(b) and b:
                return x[:len(x) - len(b)] + y
        raise ValueError
    try:
        return CONFLICT.sub(fix, d3)
    except ValueError:
        return None


def merge_cpp(cur, base, donor):
    """-> (merged text or None, note)"""
    U = {nm: _units(x) for nm, x in (("c", cur), ("b", base), ("d", donor))}
    if any("".join(t for _, t in U[k]) != x for k, x in (("c", cur), ("b", base), ("d", donor))):
        return None, "unit split did not round-trip"
    M = {k: dict(v) for k, v in U.items()}
    out, conf, notes = [], [], 0
    for key, ct in U["c"]:
        bt, dt = M["b"].get(key), M["d"].get(key)
        if bt is None:  # new in cur
            if dt is not None and dt != ct:
                conf.append(f"{key[:60]}: added on both sides differently")
            out.append((key, ct))
        elif dt is None:  # the donor deleted it
            if ct == bt:
                continue
            conf.append(f"{key[:60]}: deleted by the donor, changed in the trunk")
            out.append((key, ct))
        elif dt == bt:
            out.append((key, ct))
        elif ct == bt or ct == dt:
            out.append((key, dt))
        else:
            mt, ok = _merge_text(ct, bt, dt)
            if not ok:
                conf.append(f"{key[:60]}: both sides changed it")
            notes += 1
            out.append((key, mt if ok else ct))
    have = {k for k, _ in out}
    dkeys = [k for k, _ in U["d"]]
    for idx, (key, dt) in enumerate(U["d"]):
        if key in have or key in M["c"]:
            continue
        bt = M["b"].get(key)
        if bt is not None:  # the trunk deleted it
            if dt != bt:
                conf.append(f"{key[:60]}: deleted in the trunk, changed by the donor")
            continue
        anchor = next((dkeys[j] for j in range(idx - 1, -1, -1) if dkeys[j] in have), None)  # new in the donor
        pos = 0 if anchor is None else next(i for i, (k, _) in enumerate(out) if k == anchor) + 1
        out.insert(pos, (key, dt))
        have.add(key)
    if conf:
        return None, "; ".join(conf[:4]) + (f" (+{len(conf) - 4})" if len(conf) > 4 else "")
    return "".join(t for _, t in out), f"structured merge ({notes} unit(s) line-merged)"


def merge_flip(cur, base, donor):
    def kv(x):
        d = {}
        for ln in x.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip()
        return d
    c, b, d = kv(cur), kv(base), kv(donor)
    out = dict(c)
    for k in set(b) | set(d):
        if k == "FLIPS":
            fl = {}
            for src in (c.get(k, ""), d.get(k, "")):
                for a in src.split():
                    f, _, v = a.partition("=")
                    if f in fl and fl[f] != v:
                        return None, f"FLIPS: {f} = {fl[f]} v {v}"
                    fl[f] = v
            out[k] = " ".join(f"{f}={v}" for f, v in fl.items())
        elif k in ("TRUNK", "TRUNK_HASH", "DATA_BYTES", "WASM"):
            continue
        elif d.get(k) != b.get(k) and c.get(k) == b.get(k) and k in d:
            out[k] = d[k]
        elif d.get(k) != b.get(k) and c.get(k) != b.get(k) and c.get(k) != d.get(k):
            return None, f"{k}: changed on both sides"
    return "".join(f"{k}={v}\n" for k, v in out.items()), "FLIP key union"


def merge_bytes(cur, base, donor, name):
    """bytes in -> (bytes or None, note). Only for a conflict git merge-file could not resolve."""
    dec = lambda x: x.decode("utf-8", "surrogateescape")  # noqa: E731
    if os.path.basename(name) == "FLIP":
        r, note = merge_flip(dec(cur), dec(base), dec(donor))
    elif name.endswith((".h", ".cpp", ".cc", ".hpp")):
        r, note = merge_cpp(dec(cur), dec(base), dec(donor))
    else:
        return None, "not a C++ source or FLIP"
    return (r.encode("utf-8", "surrogateescape") if r is not None else None), note


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        sys.exit(__doc__)
    rd = lambda p: open(p, "rb").read()  # noqa: E731
    r, note = merge_bytes(rd(a[0]), rd(a[1]), rd(a[2]), a[0])
    if r is None:
        print(f"smerge: conflict: {note}", file=sys.stderr)
        return 1
    if "-o" in a:
        open(a[a.index("-o") + 1], "wb").write(r)
    else:
        sys.stdout.buffer.write(r)
    print(f"smerge: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
