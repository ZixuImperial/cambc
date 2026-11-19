#!/usr/bin/env python3
"""bake: carry only the code live runs (owner 7 Nov: "why are we still carrying old baggage, surely we just carry diffs"; b1488).
A repeatable, unattended transform of a SHIPPED bot, on the X_TAB idiom (`inline const volatile int X_TAB[n] = { 0xMAGIC, X_BITS, ... }`):

  python3 -I tools/lab/bake.py LIVE NEW [--bake X_TAB,..|all] [--keep X_TAB,..] [--keep-file F] [--need DONOR[:BASE] ...] [--need-file F]
                               [--no-ideas] [--idea-min N] [--jobs N] [--check] [--maps 20] [--dry]

  1. KEEP (stays volatile, its code stays, still flippable): --keep/--keep-file tables; the tables every queued armq line flips
     (bq/armq.txt FLIPS) or its donor diff touches; the tables named in each --need donor's diff; then, repeated up to 4 times, the
     tables whose stripped lines sit where a need donor's 3-way merge onto NEW conflicts and onto LIVE does not (adjacent-line edits).
     A kept table's initializer macros stay unknown too, so code testing X_BITS directly also stays.
  2. BAKE + STRIP (tools/lab/deadstrip.py in-process): every other volatile table becomes constexpr at its live value; flag tests fold,
     dead arms, unreachable statements and helpers nothing live reaches go. --bake limits the bake to the listed tables (the rest kept).
  3. COMMENT: a shipped (non-zero) baked table's declaration gets ONE short comment, `// vNNN XXX: subject`, from docs/version_history.md
     and docs/claude_archive.md (the last version whose line sets one of its macros); unknown version: its comment is left as it was.
  4. IDEAS: each baked table whose bake removed >= --idea-min lines (default 3) is stored as an ideastore idea `off_<x>_<new>`: the diff
     NEW -> NEW with that table kept volatile and its code back. Reopen = `armq.py add idea:NAME "X_BITS=V" ...`. Index: REPORT/ideas.txt.
  5. --check: cxeident LIVE NEW (--maps maps x 2 seats, unlimited fuel; every game must match) + mergecheck NEW LIVE + flagorphan LIVE NEW
     + wasm size of both (release build). Exit 0 = identity holds (mergecheck/flagorphan are printed, not gating: a strip removes on purpose).
Records: /data/zw4424/st/bake/NEW/ (report.txt, keep.txt, removed.json, by_flag/, ideas.txt, conflicts.txt, check_*.txt); NEW/STRIPPED.
The source bot is ingested into the ideastore first (restorable). Never edits LIVE; NEW is a fresh newbot.sh copy."""
import collections
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import deadstrip as ds  # noqa: E402

REPO = "/homes/zw4424/cambc"
B = f"{REPO}/bots"
Q = "/data/zw4424/st/bq"
OUT = "/data/zw4424/st/bake"
VOL = re.compile(r"^\s*inline\s+const\s+volatile\s+int\s+([A-Z][A-Z0-9_]*)\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}", re.M)
TABDECL = re.compile(r"^(\s*inline\s+(?:const\s+volatile|constexpr)\s+int\s+([A-Z][A-Z0-9_]*)\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}\s*;)(.*)$", re.M)
DEFINE = re.compile(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*)\s+(-?(?:0x[0-9A-Fa-f]+|\d+))\b", re.M)
TOK = re.compile(r"\b[A-Z][A-Z0-9_]+\b")


def say(*a):
    print(time.strftime("%H:%M:%SZ", time.gmtime()), *a, flush=True)


# ---- deadstrip: a kept table, volatile or constexpr, is unknown, and so is every macro its initializer names (b1488)
_orig_table_at = ds.Ev.table_at


def _table_at(self, c, i, seen):
    T = c.T
    j = i + 1 + (T[i + 1] == "volatile" if i + 1 < c.n else 0)
    while j < c.n and (T[j] in ds.PLAIN or T[j] in ("std", "::")):
        j += 1
    if j < c.n - 1 and T[j] in self.keep and re.fullmatch(r"[A-Z][A-Z0-9_]*", T[j]):
        self.bad.add(T[j])
        if T[j + 1] == "[" and T[c.M[j + 1] + 1] == "=" and T[c.M[j + 1] + 2] == "{":
            a = c.M[j + 1] + 2
            self.bad.update(t for t in T[a + 1:c.M[a]] if re.fullmatch(r"[A-Z][A-Z0-9_]*", t))
        return
    return _orig_table_at(self, c, i, seen)


ds.Ev.table_at = _table_at


def srcfiles(d):
    return sorted(x for x in os.listdir(d) if x.endswith((".h", ".cpp", ".cc")))


def read(p):
    return open(p, encoding="utf-8", errors="surrogateescape").read()


def write(p, t):
    open(p, "w", encoding="utf-8", errors="surrogateescape").write(t)


def tables(src):
    """{X_TAB: (volatile?, [initializer macros])} and {macro: int value} of a src dir"""
    tabs, defs = {}, {}
    for x in srcfiles(src):
        t = read(os.path.join(src, x))
        for m in TABDECL.finditer(t):
            tabs[m.group(2)] = ("volatile" in m.group(1), TOK.findall(m.group(3)))
        for m in DEFINE.finditer(t):
            defs.setdefault(m.group(1), int(m.group(2), 0))
    return tabs, defs


def owner_tables(tabs, names):
    """tables whose name or initializer names any of `names` (flag macros, X_TAB, X_ON prefixes)"""
    names = set(names)
    pref = {n[:-3] for n in names if n.endswith("_ON")} | {n[:-4] for n in names if n.endswith("_TAB")}
    out = set()
    for t, (_, mac) in tabs.items():
        if t in names or t[:-4] in pref or names & set(mac):
            out.add(t)
    return out


# ---- need donors: what queued and in-flight lines carry
def lives():
    try:
        return [ln.split()[1] for ln in open(f"{Q}/live.txt").read().split("\n")[:8] if ln.strip()]
    except OSError:
        return []


def changed_lines(a, b):
    r = subprocess.run(["diff", "-r", "-U0", f"{a}/src", f"{b}/src"], capture_output=True, text=True, errors="replace")
    return [x for x in r.stdout.split("\n") if x[:1] in "+-" and not x.startswith(("+++", "---"))]


def need_donors(specs, live):
    """DONOR[:BASE] -> [(donor, base)]; a missing BASE is the recent live (or LIVE) whose source differs least"""
    out = []
    for s in specs:
        d, _, b = s.partition(":")
        if not os.path.isdir(f"{B}/{d}/src"):
            say(f"need: no bot {d}: skipped")
            continue
        if not b:
            cands = [x for x in [live] + lives() if os.path.isdir(f"{B}/{x}/src")]
            b = min(cands, key=lambda x: len(changed_lines(f"{B}/{x}", f"{B}/{d}")))
        out.append((d, b))
    return out


def armq_needs():
    """flips and donors of the waiting armq lines"""
    flips, donors = [], []
    try:
        for ln in open(f"{Q}/armq.txt"):
            try:
                j = json.loads(ln)
            except ValueError:
                continue
            flips += re.findall(r"([A-Z][A-Z0-9_]*)=", j.get("flips", ""))
            donors += [x for x in j.get("donors", "-").split(",") if x and x != "-" and not x.startswith("idea:")]
    except OSError:
        pass
    return flips, donors


def conflicts(target, base, donor, f):
    """conflict hunks of donor's change to f merged onto target: [(start, end) line ranges in target's file]"""
    ps = [os.path.join(B, x, "src", f) for x in (target, base, donor)]
    with tempfile.TemporaryDirectory() as td:
        for k, p in enumerate(ps):
            if not os.path.exists(p):
                ps[k] = os.path.join(td, f"e{k}")
                write(ps[k], "")
        r = subprocess.run(["git", "merge-file", "-p", "--quiet", *ps], capture_output=True, text=True, errors="replace")
    out, line, start, side, view = [], 0, None, None, []
    for ln in r.stdout.split("\n"):
        if ln.startswith("<<<<<<< "):
            start, side = line, "ours"
            continue
        if ln.startswith("=======") and side == "ours":
            out.append((start, line))
            side = "theirs"
            continue
        if ln.startswith(">>>>>>> ") and side == "theirs":
            side = None
            continue
        if side == "theirs":
            out[-1] = out[-1] + (ln,) if len(out[-1]) > 2 else (out[-1][0], out[-1][1], ln)
        else:
            line += 1
            view.append(ln)
    if not out:
        return out
    import difflib  # the merged text carries the donor's clean edits too: map its line numbers back onto the target's own file
    tl = read(ps[0]).split("\n")
    ops = difflib.SequenceMatcher(None, view, tl, autojunk=False).get_opcodes()

    def at(i):
        for _, i1, i2, j1, j2 in ops:
            if i1 <= i < i2 or (i1 == i2 == i):
                return j1 + min(i - i1, max(j2 - j1 - 1, 0))
        return len(tl)
    return [(at(h[0]), max(at(h[0]), at(max(h[1] - 1, h[0]))), h[2:]) for h in out]


def donor_files(d, b):
    r = subprocess.run(["diff", "-rq", f"{B}/{b}/src", f"{B}/{d}/src"], capture_output=True, text=True)
    fs = set()
    for m in re.finditer(r"Files \S+/src/(\S+) and \S+ differ|Only in \S+/src: (\S+)", r.stdout):
        fs.add(m.group(1) or m.group(2))
    return sorted(f for f in fs if f.endswith((".h", ".cpp", ".cc")))


def blame_conflicts(live, new, needs, tabs, removed=(), keep=frozenset()):
    """tables named in LIVE's lines that map onto a NEW-only conflict hunk (+-3 lines), and the tables behind the strip's removals of
    those lines (a helper whose callers a baked table killed): those to keep next round"""
    import difflib
    add, roots, rows = set(), set(), []
    for d, b in needs:
        for f in donor_files(d, b):
            cn = conflicts(new, b, d, f)
            if len(cn) <= len(conflicts(live, b, d, f)):
                continue
            lf, nf = (os.path.join(B, x, "src", f) for x in (live, new))
            if not os.path.exists(lf) or not os.path.exists(nf):
                continue
            L, N = read(lf).split("\n"), read(nf).split("\n")
            sm = difflib.SequenceMatcher(None, L, N, autojunk=False)
            ops = sm.get_opcodes()
            Ls, Ns = {x.strip() for x in L}, {x.strip() for x in N}
            for s, e, theirs in cn:
                lo, hi = s - 3, e + 3
                # the LIVE lines the donor's side of the hunk still has and NEW lost: what the strip took from under the donor
                gone = {x.strip() for x in theirs if len(x.strip()) > 8 and x.strip() in Ls and x.strip() not in Ns}
                names = {w for g in gone for w in TOK.findall(g)}
                for tag, i1, i2, j1, j2 in ops:  # and the edges (4 lines) of LIVE's changed runs at the hunk: adjacent-line edits
                    if j2 >= lo and j1 <= hi and tag != "equal":
                        for ln in L[i1:min(i2, i1 + 4)] + L[max(i2 - 4, i1):i2]:
                            names.update(TOK.findall(ln))
                got = owner_tables(tabs, names)
                for r in removed:
                    if r["file"] == f and r["flags"] and any(g in r["text"] for g in gone):
                        got |= owner_tables(tabs, r["flags"])
                fn = {m.group(1) for g in gone for m in re.finditer(r"^\s*#\s*define\s+([A-Za-z_]\w*)", g)}  # a macro the strip dropped
                if not got - keep:  # nothing new to keep: the dropped helpers themselves stay
                    fn |= {m.group(1) for g in gone for m in re.finditer(r"\b([a-z_][A-Za-z0-9_]*)\s*\(", g)} - ds.NOTDECL
                add |= got
                roots |= fn
                rows.append(f"{d}:{b} {f}:{s + 1}-{e + 1} -> {' '.join(sorted(got)) or ('roots ' + ' '.join(sorted(fn)) if fn else '(nothing named: left)')}")
    return add, roots, rows


# ---- strip one copy in place
ROOTS = set()  # helpers kept alive (unused at live) because a need donor's diff edits next to them


def strip_dir(src, keep, unused=True, quiet=True):
    ds.bake(src, keep)
    s = ds.Strip(src, keep, sorted(ROOTS | keep))  # a kept table is a root: the macros its initializer names must stay defined
    start = s.run(unused=unused, say=(lambda *_: None) if quiet else print)
    for f in s.files:
        write(f.path, f.text)
    return s, start


# ---- version comments
def version_map():
    """{macro: (version, subject)}: the last version whose line sets MACRO=V"""
    vm = {}
    texts = []
    try:
        t = read(f"{REPO}/docs/version_history.md")
        texts += [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^## v(\d+)[^\n]*\n([^\n]*)", t, re.M)]
    except OSError:
        pass
    try:
        t = read(f"{REPO}/docs/claude_archive.md")
        texts += [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^- \*\*v(\d+)\*\*([^\n]*)", t, re.M)]
    except OSError:
        pass
    for v, line in sorted(texts):
        line = re.split(r"\b(?:TRUNK|Shipcheck|h2h)\b", line)[0]
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]*)=(\d+)", line):
            rest = line[m.end():].lstrip()
            subj = ""
            if rest.startswith("("):
                depth, k = 0, 0
                for k, ch in enumerate(rest):
                    depth += ch == "("
                    depth -= ch == ")"
                    if depth == 0:
                        break
                subj = rest[1:k]
            subj = re.split(r"[;.]\s", subj)[0].strip()
            if len(subj) > 56:
                subj = subj[:56].rsplit(" ", 1)[0]
            vm[m.group(1)] = (v, subj)
    return vm


def add_comments(src, baked, vm, defs, fixed=None):
    """one `// vNNN XXX: subject` on each shipped baked table's declaration; returns the tables commented. fixed = (vNNN, subject):
    the ship path's own version and summary for every baked table"""
    done = []
    for x in srcfiles(src):
        p = os.path.join(src, x)
        t = read(p)

        def sub(m):
            name, mac = m.group(2), TOK.findall(m.group(3))
            if name not in baked or "volatile" in m.group(1):
                return m.group(0)
            bits = mac[0] if mac else None
            if fixed:
                done.append(name)
                return f"{m.group(1)} // {fixed[0]} {name[:-4]}{': ' + fixed[1] if fixed[1] else ''}"
            if bits is None or defs.get(bits, 1) == 0:
                return m.group(0)
            hits = [vm[k] for k in mac if k in vm]
            if not hits:
                return m.group(0)
            v, subj = max(hits)
            done.append(name)
            return f"{m.group(1)} // v{v} {name[:-4]}{': ' + subj if subj else ''}"
        t2 = TABDECL.sub(sub, t)
        if t2 != t:
            write(p, t2)
    return done


# ---- ideas
def lines_by_table(rows):
    L = collections.Counter()
    for r in rows:
        for f in r["flags"]:
            if f.endswith("_TAB"):
                L[f] += r["text"].count("\n")
    return L


def feature_copy(args):
    live_dir, work, keep, t, baked, vm, defs, fixed, roots = args
    ROOTS.clear()  # a forkserver worker does not inherit the parent's globals: the roots come with the job
    ROOTS.update(roots)
    d = os.path.join(work, t)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    shutil.copytree(f"{live_dir}/src", f"{d}/src")
    if os.path.exists(f"{live_dir}/compile_commands.json"):
        shutil.copy(f"{live_dir}/compile_commands.json", d)
    for x in srcfiles(f"{d}/src"):  # the idea's table comes back volatile, so its flip works (RULE FLIP-DECL)
        p = f"{d}/src/{x}"
        s = read(p)
        s2 = re.sub(rf"^(\s*)inline\s+constexpr\s+int\s+{t}\b", rf"\1inline const volatile int {t}", s, flags=re.M)
        if s2 != s:
            write(p, s2)
    strip_dir(f"{d}/src", keep | {t})
    add_comments(f"{d}/src", baked - {t}, vm, defs, fixed)
    return t, d


def make_patch(new_dir, feat_dir, out):
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/a")
        os.makedirs(f"{td}/b")
        os.symlink(f"{new_dir}/src", f"{td}/a/src")
        os.symlink(f"{feat_dir}/src", f"{td}/b/src")
        r = subprocess.run(["git", "diff", "--no-index", "--full-index", "--no-color", "--no-prefix", "a/src/", "b/src/"], cwd=td, capture_output=True, text=True,
                           errors="surrogateescape")
    write(out, r.stdout)
    return r.stdout.count("\n")


def store_ideas(live, new, new_dir, keep, baked, rows, vm, defs, rep, jobs, idea_min, tag, fixed=None):
    sys.path.insert(0, LAB)
    import ideastore
    ideastore.init()
    L = lines_by_table(rows)
    todo = sorted(t for t in baked if L[t] >= idea_min)
    work = os.path.join(rep, "feat")
    os.makedirs(work, exist_ok=True)
    say(f"ideas: {len(todo)} tables with >= {idea_min} stripped lines, {jobs} jobs")
    idx = []
    live_dir = os.path.realpath(f"{B}/{live}")
    ex = cf.ProcessPoolExecutor(jobs)
    try:
        for t, d in ex.map(feature_copy, [(live_dir, work, keep, t, baked, vm, defs, fixed, sorted(ROOTS)) for t in todo]):
            pf = os.path.join(rep, "patches", f"{t}.diff")
            os.makedirs(os.path.dirname(pf), exist_ok=True)
            n = make_patch(new_dir, d, pf)
            if n == 0:
                idx.append(f"{t} - no diff")
                shutil.rmtree(d, ignore_errors=True)
                continue
            name = f"off_{t[:-4].lower()}_{tag}"
            mac = tables(f"{d}/src")[0].get(t, (0, []))[1]
            v = defs.get(mac[0], "?") if mac else "?"
            subj = f"idea({t[:-4].lower()}): {t} code stripped by bake at {live}"[:60]
            try:
                msg = ideastore.idea_add(name, "-", new, "", patch=pf, lane="", subject=subj)
                idx.append(f"{t} {name} lines={L[t]} patch={n} live_bits={v} | {msg.split('. Arm')[0]}")
            except SystemExit as e:
                idx.append(f"{t} FAILED {e}")
            shutil.rmtree(d, ignore_errors=True)
    finally:  # never leave a worker pool behind (a SIGTERM, a crash): cancel what waits and stop the workers
        procs = list(getattr(ex, "_processes", {}).values())
        ex.shutdown(wait=False, cancel_futures=True)
        for pr in procs:
            try:
                pr.terminate()
            except Exception:  # noqa: BLE001
                pass
    write(os.path.join(rep, "ideas.txt"), "\n".join(idx) + "\n")
    return idx


# ---- checks
def run(cmd, out, timeout=3600):
    with open(out, "w") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return r.returncode


def wasm_size(bot, out):
    if subprocess.run(["python3", "-I", f"{LAB}/pilotbuild.py", bot, out], capture_output=True).returncode == 0 and os.path.exists(out):
        return os.path.getsize(out)
    return -1


def checks(live, new, rep, maps, baked):
    """-> (ok, summary). cxeident must be identical on every game; mergecheck must exit 0; flagorphan may only flag tables this bake
    baked on purpose (BAKED-0 / GONE / REMOVED-0 of a baked table is the strip; anything on a kept table fails)."""
    rc = run(["python3", "-I", f"{REPO}/tools/cxe/cxeident.py", live, new, "--maps", str(maps)], f"{rep}/check_cxeident.txt", 7200)
    ci = read(f"{rep}/check_cxeident.txt")
    m = re.search(r"(\d+)\s*/\s*(\d+)\s+games\s+(?:byte-)?identical", ci)
    ident = f"{m.group(1)}/{m.group(2)}" if m else ("ok" if rc == 0 else "FAIL")
    mc = run(["python3", "-I", f"{LAB}/mergecheck.py", new, live], f"{rep}/check_mergecheck.txt")
    run(["python3", "-I", f"{LAB}/flagorphan.py", live, new, "--json", f"{rep}/flagorphan.json"], f"{rep}/check_flagorphan.txt")
    try:
        fo = json.load(open(f"{rep}/flagorphan.json"))
    except (OSError, ValueError):
        fo = None
    badst = ("ORPHANED", "UNREACHED", "PART-UNREACHED", "REMOVED-0", "BAKED-0", "GONE")
    fo_bad = ["?"] if fo is None else [f"{r['status']}:{r['table']}" for r in fo if r["status"] in badst and r["table"] not in baked]
    fo_int = 0 if fo is None else sum(1 for r in fo if r["status"] in badst and r["table"] in baked)
    write(f"{rep}/check_flagorphan_verdict.txt", f"intended {fo_int}; unintended {len(fo_bad)}: {' '.join(fo_bad)}\n")
    a, b = wasm_size(live, f"{rep}/live.wasm"), wasm_size(new, f"{rep}/new.wasm")
    size = f"wasm {a} -> {b} ({(b - a) / max(a, 1) * 100:+.2f}%)"
    write(f"{rep}/check_size.txt", size + "\n")
    fu = re.findall(r"^.*(?:fuel|cut-off).*$", ci, re.M)
    write(f"{rep}/check_fuel.txt", "\n".join(fu) + "\n")
    ok = rc == 0 and mc == 0 and not fo_bad
    return ok, (f"cxeident {ident} rc {rc}; mergecheck rc {mc}; flagorphan intended {fo_int} unintended {len(fo_bad)}"
                f"{' (' + ' '.join(fo_bad[:6]) + ')' if fo_bad else ''}; {size}")



BAKE_KEEP = os.environ.get("BAKE_KEEP_FILE", "/data/zw4424/st/bq/bake_keep.txt")


def bake_keep():
    """8 Nov (Builder, Rule Checker R1): tables a test still needs flippable, one X_TAB per line (# comments): never baked, their off
    branches never stripped, by bake.py, deadstrip.py or shipbake.py"""
    try:
        return {w for ln in open(BAKE_KEEP) for w in ln.split("#", 1)[0].split() if w}
    except OSError:
        return set()


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith("-"):
        print(__doc__)
        return 2
    live, new = a[0], a[1]
    opt = lambda k, d="": a[a.index(k) + 1] if k in a else d

    def multi(k):
        return [a[i + 1] for i, x in enumerate(a) if x == k and i + 1 < len(a)]
    rep = os.path.join(OUT, new)
    live_dir = os.path.realpath(f"{B}/{live}")
    if not os.path.isdir(live_dir + "/src"):
        print(f"bake: no bot {live}")
        return 2
    tabs, defs = tables(live_dir + "/src")
    vols = {t for t, (v, _) in tabs.items() if v}
    keep = {x for x in opt("--keep").split(",") if x}
    if opt("--keep-file"):
        keep |= set(read(opt("--keep-file")).split())
    keep |= bake_keep()  # bq/bake_keep.txt: tables under test stay volatile with all their code
    if opt("--bake") and opt("--bake") != "all":
        keep |= set(tabs) - set(opt("--bake").split(","))  # every table not listed stays as it is (volatile or constexpr)
    fixed = None
    if "--flags" in a:  # the ship path: bake only the tables those flags live in; every other table (volatile or constexpr) stays as is
        fl = re.findall(r"([A-Z][A-Z0-9_]*)=", opt("--flags"))
        only = owner_tables(tabs, fl) & vols
        keep |= set(tabs) - only
        if "--check" not in a:
            a.append("--check")
        if not only:
            print(f"bake: SUMMARY {live} -> {new}: nothing to bake (no volatile table names {' '.join(fl)})")
            return 1
    if opt("--version"):
        fixed = (opt("--version") if opt("--version").startswith("v") else "v" + opt("--version"), opt("--subject"))
    flips, qd = armq_needs()
    keep |= owner_tables(tabs, flips)
    specs = multi("--need") + qd
    if opt("--need-file"):
        specs += [x for x in read(opt("--need-file")).split() if not x.startswith("#")]
    needs = need_donors(specs, live)
    for d, b in needs:
        keep |= owner_tables(tabs, {t for ln in changed_lines(f"{B}/{b}", f"{B}/{d}") for t in TOK.findall(ln)})
    bad = sorted(k for k in keep if k not in tabs)
    if bad:
        say(f"keep: not tables of {live}, ignored: {' '.join(bad)}")
        keep -= set(bad)
    os.makedirs(rep, exist_ok=True)
    say(f"bake {live} -> {new}: {len(vols)} volatile tables, keep {len(keep)} ({len(needs)} need donors, {len(flips)} queued flips)")
    if "--dry" in a:
        print(" ".join(sorted(keep)))
        return 0
    r = subprocess.run(["python3", "-I", f"{LAB}/ideastore.py", "ingest", live], capture_output=True, text=True)
    if r.returncode:
        say(f"bake: ideastore ingest {live} failed: {(r.stdout + r.stderr)[-200:]}")
        return 1
    r = subprocess.run(["sh", f"{LAB}/newbot.sh", live, new], capture_output=True, text=True)
    if r.returncode:
        say(f"bake: {(r.stdout + r.stderr).strip()}")
        return 1
    new_dir = os.path.realpath(f"{B}/{new}")
    pristine = os.path.join(rep, "pristine_src")
    shutil.rmtree(pristine, ignore_errors=True)
    shutil.copytree(new_dir + "/src", pristine)
    allrows = []
    for rnd in range(5):
        shutil.rmtree(new_dir + "/src")
        shutil.copytree(pristine, new_dir + "/src")
        s, start = strip_dir(new_dir + "/src", keep)
        if rnd == 4 or not needs:
            break
        add, roots, rows = blame_conflicts(live, new, needs, tabs, s.attribute(), keep)
        allrows += [f"round {rnd + 1}: {x}" for x in rows]
        add -= keep
        roots -= ROOTS
        say(f"conflict round {rnd + 1}: {len(rows)} new conflict hunks; keep +{len(add)}: {' '.join(sorted(add))}; roots +{len(roots)}: {' '.join(sorted(roots))}")
        if not add and not roots:
            break
        keep |= add
        ROOTS.update(roots)
    shutil.rmtree(pristine, ignore_errors=True)
    ds.write_report(s, live, new, start, rep, keep, live_dir + "/src", new_dir)
    write(f"{rep}/conflicts.txt", "\n".join(allrows) + "\n")
    write(f"{rep}/keep.txt", "\n".join(sorted(keep)) + "\n" + "".join(f"root {r}\n" for r in sorted(ROOTS)))
    baked = {t for t in tabs if t not in keep}  # constexpr tables fold too: their stripped code is an idea as well
    vm = version_map()
    com = add_comments(new_dir + "/src", baked, vm, defs, fixed)
    write(f"{new_dir}/STRIPPED", f"SOURCE={live}\nKEEP={','.join(sorted(keep))}\nWHEN={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\nTOOL=bake.py\n")
    rows = json.load(open(f"{rep}/removed.json"))["rows"]
    tot0 = sum(start.values())
    tot1 = sum(read(f"{new_dir}/src/{x}").count("\n") for x in srcfiles(new_dir + "/src"))
    say(f"stripped: {tot0} -> {tot1} lines ({tot1 - tot0:+d}); baked {len(vols - keep)} volatile tables; {len(com)} version comments; keep {len(keep)}")
    nid = 0
    res = {}
    th = None
    if "--check" in a:  # the checks (cxeident on the pilots, builds) run while the ideas are cut
        import threading
        th = threading.Thread(target=lambda: res.update(r=checks(live, new, rep, int(opt("--maps", 20)), baked)))
        th.start()
    if "--no-ideas" not in a:
        idx = store_ideas(live, new, new_dir, keep, baked, rows, vm, defs, rep, int(opt("--jobs", 4)), int(opt("--idea-min", 3)),
                          re.sub(r"[^a-z0-9]", "", new.split("_")[-1].lower())[:8] or "bk", fixed)
        nid = sum(1 for x in idx if " off_" in x)
        say(f"ideas: {nid} stored, index {rep}/ideas.txt")
    head = (f"bake: SUMMARY {live} -> {new}: {tot0} -> {tot1} lines ({tot1 - tot0:+d}), baked {len(vols - keep)} volatile tables, "
            f"kept {len(keep & vols)} volatile, {len(com)} comments, {nid} ideas")
    if "--check" in a:
        th.join()
        ok, summ = res.get("r", (False, "checks crashed"))
        print(f"{head}; {summ}; {'PASS' if ok else 'FAIL'} ({rep})", flush=True)
        return 0 if ok else 1
    print(f"{head}; unchecked ({rep})", flush=True)
    return 0


def _term(*_):
    raise SystemExit(143)


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, _term)
    sys.exit(main())
