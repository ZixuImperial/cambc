#!/usr/bin/env python3
"""mergecheck: merge-integrity check of a candidate bot (01 Nov, merge-integrity agent; owner: "make sure the changes are all
merging together correctly").

usage: python3 -I tools/lab/mergecheck.py CAND BASE [--donor D[:DBASE] ...] [options]
  CAND, BASE, D: bot names under bots/ or bot directories. DBASE (the donor's own base) is inferred when left out: the
  live version (vNNN = bots/NAME in CLAUDE.md) or BASE whose source differs least from D.

Sections (FAIL = exit 1; WARN/INFO never fail):
 (a) FUNCS   every function CAND changes vs BASE (funcdiff.py); with donors, changed functions no donor touches are WARN
             (adaptation lines such as a merged TAB, or an unexpected edit: read them).
 (b) DONORS  per donor: every line the donor adds (removes) vs DBASE is present in (gone from) CAND, by line multiset
             counts per file (as agents did by hand). A missing line with a close match among CAND's own additions is
             ADAPTED (WARN: e.g. a TAB slot renamed in the merge); otherwise MISSING (FAIL) unless --allow-missing REGEX
             matches it. Lines CAND adds that no donor adds are listed as UNACCOUNTED (INFO). Also rebuilds BASE + every
             donor by `git merge-file` (donor order) and says which files equal CAND and where merge-file conflicted.
             Limits: counts ignore order (a line moved into the wrong function still counts as present); trivial lines
             (braces, blank, comments, break/return) are skipped.
 (c) STATIC  #define names defined twice (not in exclusive #if branches, not include guards, not #undef'd; .cpp-only
             pairs in different files are separate TUs and skipped): same value = DUP, different = CONFLICT; runtime TAB
             arrays (`volatile int NAME[..] = {..}`) declared twice; slot-0 magic numbers reused by two TABs; TAB reads
             past the array; SHIPCHECK's NULLSW defined exactly once. Only issues CAND adds over BASE FAIL.
 (d) MARKERS conflict markers (<<<<<<< ======= >>>>>>> at line start) in src; stray *.orig/*.rej (FAIL), *.BASE/*.LOCAL/
             *.REMOTE/*~/*.new/*.bak* (WARN) anywhere in the bot dir.
 (e) NULL    builds CAND and its null (every runtime TAB entry CAND adds or changes set back: new TABs BITS slot 1 to 0, parameters kept; changed TABs
             to BASE's entries with BASE's define values; --nullsw NAME instead sets `#define NAME 0`; --null-bot DIR uses
             a ready null) with `cambc400 build --release` in /data/zw4424/mergecheck/ws (cached by source hash, equal-length
             dir names; default one Condor job builds both, --build-on local uses taskset to --cores CPUs at nice
             10); code sections must be byte-identical (data bytes may differ);
             then BASE and NULL each play nova_spar_nochase2 on N maps x 2 seats at --fuel-quantum 1e7 (the SPSA/b673
             identity check: cqbatch.py on Condor) and every replay.repl26a must be byte-identical. BASE games are cached
             per (BASE hash, opponent hash, fuel) in /data/zw4424/mergecheck/games.
options: --donor D[:DBASE] (repeat) --allow-missing REGEX (repeat) --maps N (10) --maplist FILE --no-build --no-play
         --null-bot DIR --nullsw NAME (repeat) --cores N (2) --cpus LIST (taskset list, e.g. 1) --build-on condor|local --quiet (no funcdiff
         listing)
"""
import fcntl
import argparse
import collections
import difflib
import hashlib
import os
import re
import shutil
import struct
import tarfile
import subprocess
import sys
import time
import zipfile

LAB = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(LAB))
CLI = "/data/zw4424/cambc500/bin/cambc500"
ROOT = "/data/zw4424/mergecheck"
WS = ROOT + "/ws"
GAMES = ROOT + "/games"
SEED_WS = "/data/zw4424/rswproj"
MAPDIR = "/data/zw4424/ablproj_4.0.0/maps"
sys.path.insert(0, "/homes/zw4424/cambc/tools/lab"); import idopp  # noqa: E402,E702
OPP = idopp.id_opp()
FUELQ = "10000000"
DEFAULT_MAPS = ["gen_g5_037", "gen_dom_067", "gen_bk2_00012", "gen_hbd_299", "gen_s_003",  # the SPSA identity maps
                "00road-of-riches", "01islands", "00swirl", "gen_u_010", "gen_fv_007"]

FAILS, WARNS = [], []
CPUS = ""  # --cpus: taskset list for builds (default the first --cores CPUs)


def fail(msg):
    FAILS.append(msg); print("  FAIL " + msg)


def warn(msg):
    WARNS.append(msg); print("  WARN " + msg)


def info(msg):
    print("  " + msg)


# ---------------------------------------------------------------- files
def botdir(x):
    if os.path.isdir(os.path.join(x, "src")):
        return os.path.realpath(x)
    d = os.path.join(REPO, "bots", x)
    if os.path.isdir(os.path.join(d, "src")):
        return os.path.realpath(d)
    sys.exit(f"mergecheck: no bot {x!r} (no src/)")


def name_of(d):
    return os.path.basename(d.rstrip("/"))


def srcfiles(bot):
    s = os.path.join(bot, "src"); out = {}
    for f in sorted(os.listdir(s)):
        p = os.path.join(s, f)
        if os.path.isfile(p) and f.endswith((".cpp", ".h", ".hpp", ".cc", ".c", ".txt", ".cmake")):
            out[f] = open(p, encoding="utf-8", errors="replace").read()
    return out


def src_hash(files):
    h = hashlib.sha1()
    for f in sorted(files):
        h.update(f.encode() + b"\0" + files[f].encode() + b"\0")
    return h.hexdigest()[:12]


def code_files(files):
    return {f: t for f, t in files.items() if f.endswith((".cpp", ".h", ".hpp", ".cc", ".c"))}


def norm(s):
    return " ".join(s.split())


TRIVIAL = re.compile(r"^(\{|\}|\};|\}\s*else\s*\{?|else|else\s*\{|break;|continue;|return;|return 0;|return false;|"
                     r"return true;|#endif.*|#else|\)|\);|\{\s*\}|default:|\}\s*//.*)$")


def trivial(l):
    l = l.strip()
    return len(l) < 4 or l.startswith(("//", "/*", "*")) or bool(TRIVIAL.match(l))


# ---------------------------------------------------------------- (a)
FD_LINE = re.compile(r"^\s+(\S+?):(\d+)-(\d+)(?: \(in BASE\))?\s+[+-]\d+(?: -\d+)?\s+(?:NEW |DELETED )?(.*)$")


def funcdiff(a, b):
    r = subprocess.run([sys.executable, "-I", os.path.join(LAB, "funcdiff.py"), a, b], capture_output=True, text=True)
    return r.stdout


def changed_sigs(fd_out):
    out = set()
    for line in fd_out.splitlines():
        m = FD_LINE.match(line)
        if m:
            out.add((m.group(1), m.group(4).strip()[:100]))
    return out


# ---------------------------------------------------------------- (b)
def live_versions():
    names = []
    try:  # 5 Nov: live.txt ("vNNN BOT UTC ...", newest first) is the reliable list; CLAUDE.md keeps only the newest versions
        names += [ln.split()[1] for ln in open("/data/zw4424/st/bq/live.txt") if len(ln.split()) > 1][:12]
    except OSError:
        pass
    for p in (os.path.join(REPO, "CLAUDE.md"), "/homes/zw4424/condor-work/reports/subagent_primer.md"):
        try:
            names += re.findall(r"v\d+ = (?:bots/)?`?(nova_\w+)", open(p, encoding="utf-8", errors="replace").read())
        except OSError:
            pass
    seen, out = set(), []
    for n in names:
        if n not in seen and os.path.isdir(os.path.join(REPO, "bots", n, "src")):
            seen.add(n); out.append(n)
    return out


def infer_base(d, base):
    fd = code_files(srcfiles(d))
    best = None
    for n in [name_of(base)] + live_versions():
        if n == name_of(d):
            continue
        fb = code_files(srcfiles(botdir(n)))
        diff = [f for f in set(fd) | set(fb) if fd.get(f) != fb.get(f)]
        key = (len(diff), sum(abs(len(fd.get(f, "")) - len(fb.get(f, ""))) for f in diff))
        if best is None or key < best[0]:
            best = (key, n, diff)
    # among ties on the file count, the fewest changed lines
    return botdir(best[1])


def edits(old, new):
    """Lines new adds and old loses, with 1-based line numbers (difflib opcodes)."""
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    adds, rems = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            adds += [(j + 1, new[j]) for j in range(j1, j2)]
        if tag in ("delete", "replace"):
            rems += [(i + 1, old[i]) for i in range(i1, i2)]
    return adds, rems


def func_compare(cand, d, db, fd, fdb, fc):
    """Per function the donor changes: is CAND's version the donor's (SAME), the donor base's (NOT TAKEN), or other?"""
    sys.path.insert(0, LAB)
    from codeindex import index_file
    res = collections.Counter()
    for f in sorted(fd):
        if fd.get(f) == fdb.get(f) or f not in fc:
            continue
        def idx(bot, txt):
            lines = txt.split("\n")
            return {(ns, name, sig): "\n".join(norm(x) for x in lines[a - 1:b] if not trivial(x))
                    for a, b, ns, name, sig, com in index_file(os.path.join(bot, "src", f))}, \
                {(ns, name, sig): (a, b) for a, b, ns, name, sig, com in index_file(os.path.join(bot, "src", f))}
        D, Dl = idx(d, fd[f]); B, _ = idx(db, fdb[f]) if f in fdb else ({}, {})
        C, Cl = idx(cand, fc[f])
        cby = {(k[0], k[1]): k for k in C}
        for k, body in sorted(D.items(), key=lambda kv: Dl[kv[0]]):
            if B.get(k) == body:
                continue
            ck = k if k in C else cby.get((k[0], k[1]))
            where = f"{name_of(d)}/src/{f}:{Dl[k][0]} {k[1]}"
            if ck is None:
                res["absent"] += 1; info(f"FUNC ABSENT from CAND: {where} ({'new in donor' if k not in B else 'changed'})")
            elif C[ck] == body:
                res["same"] += 1
            elif k in B and C[ck] == B[k]:
                res["not_taken"] += 1; info(f"FUNC NOT TAKEN (CAND = donor base): {where}")
            else:
                a_, r_ = edits(body.split("\n"), C[ck].split("\n"))
                res["differs"] += 1
                info(f"FUNC DIFFERS from donor: {where} -> CAND src/{f}:{Cl[ck][0]}: +{len(a_)} -{len(r_)} non-trivial lines"
                     + "".join(f"\n      - {x[:110]}" for _, x in r_[:6]) + "".join(f"\n      + {x[:110]}" for _, x in a_[:6]))
    info(f"donor functions: {res['same']} same as donor, {res['differs']} differ, {res['not_taken']} not taken, "
         f"{res['absent']} absent")


def donor_check(cand, base, donors, allow):
    fc, fb = srcfiles(cand), srcfiles(base)
    donor_adds = collections.defaultdict(set)  # file -> normalized lines some donor adds
    for d, db in donors:
        fd, fdb = srcfiles(d), srcfiles(db)
        print(f"-- donor {name_of(d)} (its base {name_of(db)})")
        tot = dict(add=0, ok=0, adapted=0, missing=0, allowed=0, rem=0, rem_ok=0, rem_left=0)
        shown = 0
        for f in sorted(set(fd) | set(fdb)):
            ld, ldb = fd.get(f, "").split("\n"), fdb.get(f, "").split("\n")
            if fd.get(f) == fdb.get(f):
                continue
            if f not in fd:
                (fail if f in fc else info)(f"{f}: the donor deletes the file; CAND {'still has' if f in fc else 'drops'} it")
                continue
            lc = fc.get(f, "").split("\n") if f in fc else []
            if f not in fc:
                fail(f"{f}: donor file missing from CAND"); continue
            cc = collections.Counter(map(norm, lc)); bc = collections.Counter(map(norm, fb.get(f, "").split("\n")))
            dc = collections.Counter(map(norm, ld)); dbc = collections.Counter(map(norm, ldb))
            cand_new = [l for l in cc if cc[l] > bc[l] and not trivial(l)]
            adds, rems = edits(ldb, ld)
            fa = fm = fr = 0
            done = set()
            for ln, raw in adds:
                L = norm(raw)
                donor_adds[f].add(L)
                if trivial(L) or L in done:
                    continue
                done.add(L)
                delta = dc[L] - dbc[L]
                if delta <= 0:
                    continue  # moved, not added
                tot["add"] += 1; fa += 1
                if cc[L] - bc[L] >= delta or cc[L] >= dc[L]:
                    tot["ok"] += 1; continue
                if any(re.search(a, raw) for a in allow):
                    tot["allowed"] += 1; continue
                close = difflib.get_close_matches(L, cand_new, n=1, cutoff=0.75)
                if close:
                    tot["adapted"] += 1
                    if shown < 25:
                        warn(f"ADAPTED {name_of(d)}/src/{f}:{ln}: {L[:110]!r} ~ CAND {close[0][:80]!r}"); shown += 1
                else:
                    tot["missing"] += 1; fm += 1
                    if shown < 40:
                        fail(f"MISSING {name_of(d)}/src/{f}:{ln} (in CAND {cc[L]}x, donor {dc[L]}x, BASE {bc[L]}x): "
                             f"{L[:120]!r}"); shown += 1
            done = set()
            for ln, raw in rems:
                L = norm(raw)
                if trivial(L) or L in done:
                    continue
                done.add(L)
                delta = dbc[L] - dc[L]
                if delta <= 0:
                    continue
                tot["rem"] += 1
                if bc[L] - cc[L] >= delta or cc[L] <= dc[L]:
                    tot["rem_ok"] += 1
                elif any(re.search(a, raw) for a in allow):
                    tot["allowed"] += 1
                else:
                    tot["rem_left"] += 1; fr += 1
                    if shown < 40:
                        fail(f"NOT REMOVED {name_of(db)}/src/{f}:{ln} (donor removes it; CAND {cc[L]}x, BASE {bc[L]}x): "
                             f"{L[:120]!r}"); shown += 1
            info(f"{f}: donor +{len(adds)} -{len(rems)} lines; {fa} distinct non-trivial added: {fa - fm} accounted"
                 + (f", {fm} MISSING" if fm else "") + (f", {fr} removals left in CAND" if fr else ""))
        func_compare(cand, d, db, fd, fdb, fc)
        info(f"donor total: {tot['add']} distinct added lines: {tot['ok']} present, {tot['adapted']} adapted, "
             f"{tot['missing']} missing, {tot['allowed']} allowed by --allow-missing; {tot['rem']} removed lines: "
             f"{tot['rem_ok']} gone, {tot['rem_left']} still in CAND")
    # CAND additions no donor explains
    print("-- CAND additions vs BASE that no donor adds (UNACCOUNTED: merge adaptations or unexpected edits)")
    n = 0
    for f in sorted(fc):
        if fc[f] == fb.get(f):
            continue
        lc, lb = fc[f].split("\n"), fb.get(f, "").split("\n")
        adds, _ = edits(lb, lc)
        bc = collections.Counter(map(norm, lb)); cc = collections.Counter(map(norm, lc))
        seen = set()
        for ln, raw in adds:
            L = norm(raw)
            if trivial(L) or L in seen or L in donor_adds.get(f, ()) or cc[L] <= bc[L]:
                continue
            seen.add(L); n += 1
            if n <= 30:
                info(f"UNACCOUNTED {name_of(cand)}/src/{f}:{ln}: {L[:120]!r}")
    info(f"{n} unaccounted non-trivial CAND lines" + (" (first 30 shown)" if n > 30 else ""))
    # mechanical reconstruction BASE + donors (merge-file in donor order)
    print("-- reconstruction: BASE + donors by git merge-file, compared with CAND")
    tmp = os.path.join(ROOT, "tmp", f"{os.getpid()}"); os.makedirs(tmp, exist_ok=True)
    dsrc = [(srcfiles(d), srcfiles(db), d) for d, db in donors]
    touched = sorted({f for sd, sdb, _ in dsrc for f in set(sd) | set(sdb) if sd.get(f) != sdb.get(f)})
    same, conf = [], []
    for f in touched:
        cur = fb.get(f, "")
        for sd, sdb, d in dsrc:
            a, o = sd.get(f), sdb.get(f)
            if a == o or a is None:
                continue
            p = [os.path.join(tmp, x) for x in ("cur", "old", "new")]
            for path, txt in zip(p, (cur, o or "", a)):
                open(path, "w").write(txt)
            r = subprocess.run(["git", "merge-file", "-p", p[0], p[1], p[2]], capture_output=True, text=True)
            if r.returncode:
                conf.append(f"{f} (+{name_of(d)}: {r.returncode} conflicts)")
            cur = r.stdout
        (same if cur == fc.get(f, "") else []).append(f)
        if cur != fc.get(f, "") and f in fc:
            a_, r_ = edits(cur.split("\n"), fc[f].split("\n"))
            info(f"{f}: CAND differs from the mechanical merge by +{len(a_)} -{len(r_)} lines")
    shutil.rmtree(tmp, ignore_errors=True)
    info(f"files equal to the mechanical merge: {len(same)}/{len(touched)} {same}")
    if conf:
        info("merge-file conflicts (hand-resolved in CAND; check those spots): " + "; ".join(conf))


# ---------------------------------------------------------------- (c)
DEF = re.compile(r"^\s*#\s*define\s+(\w+)(\([^)]*\))?(.*)$")
PP = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif|undef)\b\s*(\w*)")
TABRE = re.compile(r"\bvolatile\b[^;={}\n]*?\bint\s+(\w+)\s*\[([^\]]*)\]\s*=\s*\{(.*?)\}\s*;", re.S)
TABREAD = re.compile(r"\b(\w+)\s*\[\s*(\d+)\s*\]")


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def defines(files):
    """name -> [(file, line, value, cond path)], plus the set of #undef'd names."""
    out, undef = collections.defaultdict(list), set()
    ids = 0
    for f, txt in files.items():
        lines = txt.split("\n"); stack = []; guard = None
        i = 0
        while i < len(lines):
            l = lines[i]; ln = i + 1
            while l.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1; l = l.rstrip()[:-1] + " " + lines[i]
            m = PP.match(l)
            if m:
                k, nm = m.groups()
                if k in ("if", "ifdef", "ifndef"):
                    ids += 1; stack.append([ids, 0, nm if k == "ifndef" else None])
                elif k in ("elif", "else") and stack:
                    stack[-1][1] += 1; stack[-1][2] = None
                elif k == "endif" and stack:
                    stack.pop()
                elif k == "undef":
                    undef.add(nm)
            else:
                m = DEF.match(l)
                if m:
                    nm = m.group(1)
                    if not (stack and stack[-1][2] == nm):  # include guard / default-if-undefined
                        val = norm(strip_comments((m.group(2) or "") + m.group(3)))
                        out[nm].append((f, ln, val, tuple((a, b) for a, b, _ in stack)))
            i += 1
    return out, undef


def exclusive(p, q):
    dp = dict(p)
    return any(a in dp and dp[a] != b for a, b in q)


def define_issues(files):
    defs, undef = defines(files)
    issues = {}
    for nm, lst in defs.items():
        if len(lst) < 2 or nm in undef:
            continue
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i], lst[j]
                if exclusive(a[3], b[3]):
                    continue
                if a[0] != b[0] and a[0].endswith(".cpp") and b[0].endswith(".cpp"):
                    continue
                kind = "DUP" if a[2] == b[2] else "CONFLICT"
                issues.setdefault((nm, kind), []).append((a, b))
    return issues, defs


def split_top(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def tabs(files):
    out = collections.defaultdict(list)
    for f, txt in files.items():
        for m in TABRE.finditer(txt):
            ents = split_top(strip_comments(m.group(3)))
            out[m.group(1)].append(dict(file=f, line=txt.count("\n", 0, m.start()) + 1, size=m.group(2).strip(),
                                        ents=ents, span=m.span(3)))
    return out


def magic(e):
    try:
        return int(e, 0)
    except ValueError:
        return None


def unity_problems(files):
    """3 Nov (b1066 unity build): nova_all.cpp defines NOVA_UNITY_ALL, includes every guarded .cpp as one translation unit and #undefs each file's own
    macros right after it (tools/lab/mkunity.sh). -> what is wrong with that here ([] when the bot is not a unity build)."""
    na = files.get("nova_all.cpp")
    if na is None:
        return []
    if "NOVA_UNITY_ALL" not in na:  # new layout: one .cpp, listing every .cc
        inc = re.findall(r'^\s*#\s*include\s+"([^"]+\.cc)"', na, re.M)
        out = [f"nova_all.cpp includes {f}, which is missing" for f in inc if f not in files]
        out += [f"{f} is not in nova_all.cpp: its code is never compiled" for f in files if f.endswith(".cc") and f not in inc]
        out += [f"{f} is a second .cpp: the platform compiles it on its own" for f in files if f.endswith(".cpp") and f != "nova_all.cpp"]
        return out
    after, cur, out = {}, None, []
    for ln in na.split("\n"):
        m = re.match(r'\s*#\s*include\s+"([^"]+\.cpp)"', ln)
        if m:
            cur = m.group(1)
            after[cur] = set()
            continue
        m = re.match(r"\s*#\s*undef\s+(\w+)", ln)
        if m and cur:
            after[cur].add(m.group(1))
    for f, txt in sorted(files.items()):
        if not f.endswith(".cpp") or f == "nova_all.cpp":
            continue
        guarded = txt.split("\n", 1)[0].startswith("#ifdef NOVA_UNITY_ALL")
        if f in after and not guarded:
            out.append(f"{f} is included by nova_all.cpp but has no NOVA_UNITY_ALL guard: compiled twice")
        elif guarded and f not in after:
            out.append(f"{f} has the NOVA_UNITY_ALL guard but nova_all.cpp does not include it: its code is never compiled")
        if f in after:
            leak = set(re.findall(r"^\s*#\s*define\s+([A-Za-z_]\w*)", txt, re.M)) - {"NOVA_UNITY_ALL"} - after[f]
            if leak:
                out.append(f"{f} #defines {', '.join(sorted(leak)[:6])} with no #undef after it in nova_all.cpp: leaks into the files after it")
    out += [f"nova_all.cpp includes {f}, which is missing" for f in after if f not in files]
    return out


def static_checks(cand, base):
    fca, fba = code_files(srcfiles(cand)), code_files(srcfiles(base))
    # 3 Nov (b1066): nova_all.cpp #undefs every .cpp macro, which would hide every .cpp-v-header #define clash below: left out of the scan
    fc, fb = ({k: v for k, v in x.items() if k != "nova_all.cpp"} for x in (fca, fba))
    ub = set(unity_problems(fba))
    for pr in unity_problems(fca):
        (warn if pr in ub else fail)(f"unity build: {pr} (fix: sh tools/lab/mkunity.sh bots/NAME/src)")
    if "nova_all.cpp" in fca:
        info("unity build: nova_all.cpp checked (guards, includes, per-file #undef); a .cpp #define that a header also defines is unsafe here, since the "
             "#undef after that .cpp removes the header's macro for every later file")
    ic, defs = define_issues(fc)
    ib, _ = define_issues(fb)
    old = 0
    for key, pairs in sorted(ic.items()):
        vals = {(a[0], a[2]) for a, b in pairs} | {(b[0], b[2]) for a, b in pairs}
        bvals = {(a[0], a[2]) for a, b in ib.get(key, [])} | {(b[0], b[2]) for a, b in ib.get(key, [])}
        if key in ib and vals <= bvals:
            old += 1; continue
        a, b = pairs[0]
        (fail if key[1] == "CONFLICT" or not key in ib else warn)(
            f"#define {key[0]} {key[1]}: {a[0]}:{a[1]} = {a[2][:60]!r} and {b[0]}:{b[1]} = {b[2][:60]!r}"
            + (f" (+{len(pairs) - 1} more pairs)" if len(pairs) > 1 else ""))
    info(f"#define duplicates already in BASE (not counted): {old}")
    tc, tb = tabs(fc), tabs(fb)
    for nm, lst in sorted(tc.items()):
        if len(lst) > 1 and len(tb.get(nm, [])) < len(lst):
            fail(f"TAB {nm} declared {len(lst)}x: " + ", ".join(f"{t['file']}:{t['line']}" for t in lst))
    mag = collections.defaultdict(list)
    for nm, lst in tc.items():
        for t in lst:
            m = magic(t["ents"][0]) if t["ents"] else None
            if m is not None:
                mag[m].append((nm, t))
    bmag = collections.defaultdict(set)
    for nm, lst in tb.items():
        for t in lst:
            m = magic(t["ents"][0]) if t["ents"] else None
            if m is not None:
                bmag[m].add(nm)
    for m, lst in sorted(mag.items()):
        names = {nm for nm, t in lst}
        if len(names) > 1 and not names <= bmag.get(m, set()):
            fail(f"slot-0 magic 0x{m:08X} shared by " + ", ".join(f"{nm} ({t['file']}:{t['line']})" for nm, t in lst))
    # reads past the array; declared size vs initializers
    for f, txt in fc.items():
        body = strip_comments(txt)
        for m in TABREAD.finditer(body):
            nm, idx = m.group(1), int(m.group(2))
            if nm not in tc or re.search(r"\bint\s+$", body[max(0, m.start() - 12):m.start()]):
                continue
            t = tc[nm][0]
            n = int(t["size"]) if t["size"].isdigit() else len(t["ents"])
            if idx >= n:
                fail(f"{f}:{body.count(chr(10), 0, m.start()) + 1}: {nm}[{idx}] reads past {nm}[{n}] "
                     f"({t['file']}:{t['line']})")
    for nm, lst in tc.items():
        t = lst[0]
        if t["size"].isdigit() and len(t["ents"]) != int(t["size"]) and nm not in tb:
            warn(f"TAB {nm} {t['file']}:{t['line']}: size {t['size']} but {len(t['ents'])} initializers")
    # runtime flags read AFTER other work on a line CAND adds: at flag 0 the work still runs and spends fuel, which moves
    # the bot's own relative spend caps (e.g. compute_travel's dash_floor = fuel() - 8000) -> null != BASE (v382 01islands)
    flagnames = {nm for nm, lst in defs.items() if any(re.search(r"\b\w+_TAB\s*\[", v[2]) for v in lst)}
    if flagnames:
        fpat = re.compile(r"([A-Za-z_][\w:.>-]*\([^()]*\))\s*&&\s*!?\(?\s*(" + "|".join(sorted(flagnames)) + r")\b")
        nlate = 0
        for f, txt in fc.items():
            if txt == fb.get(f):
                continue
            lc, lb = txt.split("\n"), fb.get(f, "").split("\n")
            for ln, raw in edits(lb, lc)[0]:
                m = fpat.search(strip_comments(raw))
                if m:
                    nlate += 1
                    warn(f"flag read after a call: {f}:{ln}: {m.group(1)[:50]} && {m.group(2)} (read the flag first)")
        info(f"{nlate} added lines read a runtime flag after a call")
    new_tabs = sorted(nm for nm in tc if nm not in tb)
    chg_tabs = sorted(nm for nm in tc if nm in tb and [norm(e) for e in tc[nm][0]["ents"]]
                      != [norm(e) for e in tb[nm][0]["ents"]])
    info(f"runtime TABs: {len(tc)} in CAND; new vs BASE: {new_tabs or 'none'}; changed: {chg_tabs or 'none'}")
    # SHIPCHECK NULLSW
    sc = os.path.join(cand, "SHIPCHECK")
    if os.path.isfile(sc):
        m = re.search(r"^NULLSW=(\w+)", open(sc).read(), re.M)
        if m:
            nsw = m.group(1); hits = defs.get(nsw, [])
            if len(hits) != 1:
                fail(f"SHIPCHECK NULLSW={nsw}: #define {nsw} occurs {len(hits)}x (shipcheck needs exactly one)")
            elif hits[0][2] in ("0", ""):
                fail(f"SHIPCHECK NULLSW={nsw}: {hits[0][0]}:{hits[0][1]} is already {hits[0][2]!r}")
            else:
                info(f"SHIPCHECK NULLSW={nsw}: {hits[0][0]}:{hits[0][1]} = {hits[0][2]} (one definition)")
    return tc, tb


# ---------------------------------------------------------------- (d)
def markers(cand):
    s = os.path.join(cand, "src"); n = 0
    for f, txt in srcfiles(cand).items():
        for i, l in enumerate(txt.split("\n")):
            if re.match(r"^(<{7}|={7}|>{7}|\|{7})(\s|$)", l):
                fail(f"conflict marker {s}/{f}:{i + 1}: {l[:60]!r}"); n += 1
    for dp, dn, fn in os.walk(cand):
        dn[:] = [x for x in dn if x not in (".cambc", "build", "target")]
        for x in fn:
            p = os.path.join(dp, x)
            if x.endswith((".orig", ".rej")):
                fail(f"stray file {p}"); n += 1
            elif re.search(r"(\.BASE|\.LOCAL|\.REMOTE|~|\.new|\.bak.*|\.old|\.swp)$", x):
                warn(f"stray file {p}"); n += 1
    info(f"{n} markers / stray files")


# ---------------------------------------------------------------- (e)
def make_null(cand, base, tc, tb, nullsw):
    fc, fb = srcfiles(cand), srcfiles(base)
    out = dict(fc)
    if nullsw:
        for nm in nullsw:
            pat = re.compile(rf"^([ \t]*#[ \t]*define[ \t]+{nm}[ \t]+)(\S+)(.*)$", re.M)
            hits = [(f, m) for f, t in out.items() for m in pat.finditer(t)]
            if len(hits) != 1:
                fail(f"--nullsw {nm}: #define {nm} occurs {len(hits)}x"); return None, []
            f, m = hits[0]
            out[f] = out[f][:m.start(2)] + "0" + out[f][m.end(2):]
        return out, [f"#define {nm} 0" for nm in nullsw]
    bdefs, _ = defines(code_files(fb)); cdefs, _ = defines(code_files(fc))

    def bval(nm):
        v = [x for x in bdefs.get(nm, []) if not x[3]] or bdefs.get(nm, [])
        return v[-1][2] if v else None

    def cval(nm):
        v = [x for x in cdefs.get(nm, []) if not x[3]] or cdefs.get(nm, [])
        return v[-1][2] if v else None

    def to_base(e):  # BASE's define values for identifiers whose value CAND changed
        def sub(m):
            nm = m.group(0); b, c = bval(nm), cval(nm)
            return f"({b})" if b is not None and c is not None and b != c else nm
        return re.sub(r"\b[A-Za-z_]\w*\b", sub, e)

    edits_, notes = collections.defaultdict(list), []
    for nm, lst in tc.items():
        t = lst[0]
        if nm not in tb:
            # 3 Nov (b1033 sose): only the BITS slot goes to 0. Zeroing the parameter slots too changes how the table is emitted, so every later data address moved
            # (26,656 code sites, code length equal) and a harmless flag failed. A table whose parameters do work at BITS 0 still fails the identity games.
            new = [t["ents"][0], "0"] + t["ents"][2:] if len(t["ents"]) > 1 else list(t["ents"])
            notes.append(f"{nm} (new): slot 1 (BITS) -> 0, parameters kept")
        else:
            be = tb[nm][0]["ents"]
            # 3 Nov (b1062 FL_CMT_X100: 7/20 false FAILs): a slot BASE lacks keeps CAND's value, as a new table's parameters do
            new = [t["ents"][0]] + [to_base(be[i]) if i < len(be) else t["ents"][i] for i in range(1, len(t["ents"]))]
            if [norm(x) for x in new] == [norm(x) for x in t["ents"]]:
                continue
            notes.append(f"{nm} (changed): -> BASE entries {[norm(x)[:40] for x in new[1:]]}")
        edits_[t["file"]].append((t["span"], " " + ", ".join(new) + " "))
    for f, lst in edits_.items():
        txt = out[f]
        for (a, b), rep in sorted(lst, reverse=True):
            txt = txt[:a] + rep + txt[b:]
        out[f] = txt
    return out, notes


def place(files, tag=""):
    h = src_hash(files)
    d = os.path.join(WS, "bots", "mc_" + h)
    if not os.path.isdir(os.path.join(d, "src")):
        os.makedirs(os.path.join(d, "src"))
        for f, t in files.items():
            open(os.path.join(d, "src", f), "w").write(t)
    return d


def setup_ws():
    """Create or repair the build workspace from SEED_WS, piece by piece (10 Nov: a host move left ws missing and every pilot build
    failed; a half-copied ws, e.g. cambc.toml without sdk/, is repaired too). Each piece lands under a temp name, then renames,
    so a concurrent caller never sees a partial sdk/."""
    os.makedirs(os.path.join(WS, "bots"), exist_ok=True)
    if not os.path.isfile(os.path.join(WS, "cambc.toml")):
        shutil.copy(os.path.join(SEED_WS, "cambc.toml"), os.path.join(WS, f".cambc.toml.{os.getpid()}"))
        os.replace(os.path.join(WS, f".cambc.toml.{os.getpid()}"), os.path.join(WS, "cambc.toml"))
    for x in ("sdk", "cmake"):
        if not os.path.isdir(os.path.join(WS, x)):
            tmp = os.path.join(WS, f".{x}.{os.getpid()}")
            shutil.copytree(os.path.join(SEED_WS, x), tmp)
            try:
                os.rename(tmp, os.path.join(WS, x))
            except OSError:  # another caller won the race
                shutil.rmtree(tmp, ignore_errors=True)


def build(d, cores):
    w = os.path.join(d, ".cambc", "build-release", "bot-injected.wasm")
    if os.path.isfile(w) and os.path.isfile(os.path.join(d, ".mc_built")):
        return w
    cpus = CPUS or ",".join(str(i) for i in range(max(1, cores)))
    env = dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL=str(max(1, cores)))
    log = os.path.join(d, "build.log")
    t = time.time()
    with open(log, "w") as fh:
        r = subprocess.run(["taskset", "-c", cpus, "nice", "-n", "10", CLI, "build", "--release",
                            os.path.relpath(d, WS)], cwd=WS, stdout=fh, stderr=subprocess.STDOUT, env=env)
    if r.returncode or not os.path.isfile(w):
        tail = open(log, errors="replace").read()[-1500:]
        fail(f"build of {d} failed (log {log}):\n{tail}"); return None
    open(os.path.join(d, ".mc_built"), "w").write(f"{time.time() - t:.0f}s\n")
    return w


def condor_env():
    env = dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", ""))
    cc = env.get("KRB5CCNAME", "")
    path = cc[5:] if cc.startswith("FILE:") else cc
    if not (path and os.path.exists(path)):
        import glob
        files = sorted(glob.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
        if files:
            env["KRB5CCNAME"] = "FILE:" + files[-1]
    return env


BUILD_WAIT, LOCAL_BUILDS = 90, 3


def pilot_build(run, names, wait=420, debug=False):
    """mergecheck_node.sh as a pilot item, just behind a shipcheck. True once out.tgz is in run; False: no pilot, or no result in wait s."""
    try:
        sys.path.insert(0, LAB)
        import pilotd as pl
        if not pl.alive_pilots():
            return False
    except Exception:  # noqa: BLE001
        return False
    pd = f"/homes/zw4424/condor-runs/stage/mcb_{os.path.basename(run)}"
    os.makedirs(pd, exist_ok=True)
    shutil.copy(os.path.join(run, "in.tgz"), pd)
    open(f"{pd}/job.sh", "w").write(f"cp {pd}/in.tgz . && {'MCB_DEBUG=1 ' if debug else ''}sh {os.path.join(LAB, 'mergecheck_node.sh')} in.tgz out.tgz ${{1:-4}} {names} && cp out.tgz {pd}/.out.tmp && mv {pd}/.out.tmp {pd}/out.tgz\n")
    t0 = time.time()
    pl.enqueue(pd, [(0, [f"run:{pd}/job.sh", 4])], 11)  # 7 Nov: the node passes its slot_par (cores - 1) as $1: the compile uses it (was a fixed 4 of ~16 cores)
    info(f"building on a pilot ({pd})")
    try:
        while time.time() - t0 < wait:
            if os.path.exists(f"{pd}/out.tgz"):
                shutil.move(f"{pd}/out.tgz", os.path.join(run, "out.tgz"))
                info(f"built on a pilot in {time.time() - t0:.0f} s")
                return True
            time.sleep(2)
        return False
    finally:
        shutil.rmtree(pd, ignore_errors=True)


def local_build(run, names):
    """mergecheck_node.sh in the run dir on this machine, in one of LOCAL_BUILDS slots."""
    locks = os.path.join(ROOT, "builds", ".slots")
    os.makedirs(locks, exist_ok=True)
    while True:
        for k in range(LOCAL_BUILDS):
            fh = open(os.path.join(locks, str(k)), "a")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                continue
            try:
                subprocess.run(["nice", "-n", "5", "sh", os.path.join(LAB, "mergecheck_node.sh"), "in.tgz", "out.tgz", "4"] + names.split(), cwd=run,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                fh.close()
            return
        time.sleep(3)


def build_condor(dirs, wait_max=5400):
    """Release-build every dir in one Condor job (same node, same paths for all); wasm into DIR/.cambc/build-release."""
    todo = [d for d in dict.fromkeys(dirs) if not os.path.isfile(os.path.join(d, ".mc_built"))]
    try:  # 6 Nov: a wasm already built for the same source (cxeident's pilot_wasm, an earlier check) is reused, not rebuilt
        sys.path.insert(0, os.path.join(os.path.dirname(LAB), "cxe"))
        import cxebuild
        for d in list(todo):
            sw = cxebuild.shared_wasm(os.path.join(d, "src"))
            if sw:
                os.makedirs(os.path.join(d, ".cambc", "build-release"), exist_ok=True)
                shutil.copy(sw, os.path.join(d, ".cambc", "build-release", "bot-injected.wasm"))
                open(os.path.join(d, ".mc_built"), "w").write(f"shared {sw}\n")
                todo.remove(d)
                info(f"build: reused {sw} (same source, built earlier)")
    except Exception as e:  # noqa: BLE001  the build below always works
        info(f"build: no shared wasm lookup ({str(e)[:80]})")
        cxebuild = None
    if todo:
        run = os.path.join(ROOT, "builds", time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"_{os.getpid()}")
        os.makedirs(run)
        with tarfile.open(os.path.join(run, "in.tgz"), "w:gz") as tf:
            for x in ("cambc.toml", "sdk", "cmake"):
                tf.add(os.path.join(WS, x), arcname="proj/" + x)
            for d in todo:
                tf.add(os.path.join(d, "src"), arcname=f"proj/bots/{name_of(d)}/src")
        names = " ".join(name_of(d) for d in todo)
        open(os.path.join(run, "job.sub"), "w").write(f"""universe = vanilla
executable = {os.path.join(LAB, "mergecheck_node.sh")}
arguments = "in.tgz out.tgz 4 {names}"
initialdir = {run}
transfer_input_files = in.tgz
transfer_output_files = out.tgz
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
output = node.out
error = node.err
log = job.log
request_cpus = 4
request_memory = 8000
priority = 15
batch_name = mergecheck_build
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv = True
queue 1
""")
        t0 = time.time()
        built = pilot_build(run, names)  # pilots hold the pool's slots: a Condor job waited up to 869 s
        cl = None
        if not built:
            r = subprocess.run(["condor_submit", "job.sub"], capture_output=True, text=True, env=condor_env(), cwd=run)
            m = re.search(r"submitted to cluster (\d+)", r.stdout)
            if r.returncode or not m:
                fail(f"condor_submit failed: {(r.stdout + r.stderr).strip()[-300:]}"); return {}
            cl = m.group(1); t0 = time.time()
            info(f"building {len(todo)} bots on Condor (cluster {cl}, {run})")
        while cl:
            time.sleep(15)
            q = subprocess.run(["condor_q", cl, "-af", "JobStatus"], capture_output=True, text=True, env=condor_env())
            if q.returncode:
                continue
            st = q.stdout.strip()
            if st == "1" and time.time() - t0 > BUILD_WAIT:  # 2 Nov: pilots hold the pool's slots and builds waited 869 s: build here, a few at a time
                subprocess.run(["condor_rm", cl], capture_output=True, env=condor_env())
                info(f"no slot in {BUILD_WAIT} s: building here")
                local_build(run, names)
                break
            if st == "5" or time.time() - t0 > wait_max:
                subprocess.run(["condor_rm", cl], capture_output=True, env=condor_env())
                fail(f"Condor build {cl} {'held' if st == '5' else 'timed out'} ({run})"); return {}
            if not st:
                break
        out = os.path.join(run, "out.tgz")
        for _ in range(8):
            if os.path.isfile(out):
                break
            time.sleep(15)
        if not os.path.isfile(out):
            fail(f"Condor build {cl} returned no out.tgz ({run})"); return {}
        res = os.path.join(run, "res")
        with tarfile.open(out) as tf:
            tf.extractall(res, filter="data")
        for d in todo:
            w = os.path.join(res, name_of(d) + ".wasm")
            if os.path.isfile(w):
                os.makedirs(os.path.join(d, ".cambc", "build-release"), exist_ok=True)
                shutil.copy(w, os.path.join(d, ".cambc", "build-release", "bot-injected.wasm"))
                shutil.copy(os.path.join(res, name_of(d) + ".log"), os.path.join(d, "build.log"))
                open(os.path.join(d, ".mc_built"), "w").write(f"condor {cl}\n")
                if cxebuild:
                    try:
                        cxebuild.save_shared_wasm(os.path.join(d, "src"), os.path.join(d, ".cambc", "build-release", "bot-injected.wasm"))
                    except OSError:
                        pass
            else:
                tail = open(os.path.join(res, name_of(d) + ".log"), errors="replace").read()[-1500:] \
                    if os.path.isfile(os.path.join(res, name_of(d) + ".log")) else "(no log)"
                fail(f"build of {d} failed on Condor ({run}):\n{tail}")
    return {d: os.path.join(d, ".cambc", "build-release", "bot-injected.wasm") for d in dirs
            if os.path.isfile(os.path.join(d, ".mc_built"))}


def leb(b, i):
    r = s = 0
    while True:
        x = b[i]; i += 1
        r |= (x & 0x7f) << s; s += 7
        if x < 0x80:
            return r, i


def sections(b):
    i = 8; out = {}
    while i < len(b):
        sid = b[i]; n, j = leb(b, i + 1)
        if sid != 0:
            out[sid] = b[j:j + n]
        i = j + n
    return out


def data_ranges(d):
    """[(start, end)] of the active data segments (section 11) whose offset is an i32.const."""
    out = []
    try:
        n, i = leb(d, 0)
        for _ in range(n):
            kind, i = leb(d, i)
            if kind == 1:  # passive: no address
                ln, i = leb(d, i); i += ln; continue
            if kind == 2:
                _, i = leb(d, i)
            if d[i] != 0x41:
                return out
            v, i = leb(d, i + 1)
            i += 1  # 0x0b end
            ln, i = leb(d, i)
            out.append((v, v + ln))
            i += ln
    except IndexError:
        pass
    return out


def relocated_only(ca, cb, rng):
    """Code sections of one length that differ only inside load/store memarg OFFSETS that point into data (both builds): the data layout
    moved (3 Nov, b1009: a new table nulled to all-zero parameter slots shifted every later address by 16), not a compiled flag. An i32.const
    or opcode difference is never excused. -> number of relocated references, or None."""
    if len(ca) != len(cb) or not rng:
        return None
    lo, hi = min(r[0] for r in rng), max(r[1] for r in rng)
    seen = set()
    for k in (i for i, (x, y) in enumerate(zip(ca, cb)) if x != y):
        hit = None
        for p in range(max(0, k - 7), k):  # opcode, align byte, LEB offset covering k
            if 0x28 <= ca[p] <= 0x3e and ca[p] == cb[p] and ca[p + 1] == cb[p + 1] and ca[p + 1] <= 4:
                try:
                    va, ea = leb(ca, p + 2)
                    vb, eb = leb(cb, p + 2)
                except IndexError:
                    continue
                if ea == eb and p + 2 <= k < ea and lo <= va < hi and lo <= vb < hi:
                    hit = p
        if hit is None:
            return None
        seen.add(hit)
    return len(seen)


def wsec(wa, wb):
    A, B = sections(open(wa, "rb").read()), sections(open(wb, "rb").read())
    code_same = A.get(10) == B.get(10)
    if not code_same:
        moved = relocated_only(A.get(10, b""), B.get(10, b""), data_ranges(A.get(11, b"")))
        if moved is not None and moved == relocated_only(A.get(10, b""), B.get(10, b""), data_ranges(B.get(11, b""))):
            code_same = f"relocated {moved}"
    da, db = A.get(11, b""), B.get(11, b"")
    nd = sum(1 for x, y in zip(da, db) if x != y) + abs(len(da) - len(db))
    other = [k for k in set(A) | set(B) if k not in (10, 11) and A.get(k) != B.get(k)]
    return code_same, len(A.get(10, b"")), nd, other


def play(base, null, maps, opp):
    oppd = botdir(opp)
    bh, nh, oh = src_hash(srcfiles(base)), src_hash(srcfiles(null)), src_hash(srcfiles(oppd))
    # keyed by the engine too (4 Nov finals patch: b1165's null games cached on 2.0.0 met base games on 3.0.0 -> false 0/20)
    ev = subprocess.run([CLI, "--version"], capture_output=True, text=True).stdout.split()[-1]
    eng = "" if ev == "4.0.0" else f"_c{ev}"  # 4.0.0 dirs keep their old names
    gb = os.path.join(GAMES, f"{bh}_{oh}_q{FUELQ}{eng}"); gn = os.path.join(GAMES, f"{nh}_{oh}_q{FUELQ}{eng}")
    os.makedirs(gb, exist_ok=True); os.makedirs(gn, exist_ok=True)
    rows = []
    for mp in maps:
        mf = os.path.join(MAPDIR, mp + ".map26a")
        for bot, g in ((base, gb), (null, gn)):
            for seat in "AB":
                out = os.path.join(g, f"{mp}__{seat}.repl26a")
                if not os.path.isfile(out):
                    a, b = (bot, oppd) if seat == "A" else (oppd, bot)
                    rows.append(f"{a} {b} {mf} {out}")
    if rows:
        run = os.path.join(GAMES, "runs", time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"_{os.getpid()}")
        os.makedirs(run, exist_ok=True)
        open(os.path.join(run, "manifest.txt"), "w").write("\n".join(rows) + "\n")
        info(f"playing {len(rows)} games on Condor (cqbatch, --fuel-quantum {FUELQ}); log {run}/cq.log")
        with open(os.path.join(run, "cq.log"), "w") as fh:
            subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(LAB, "cqbatch.py"),
                            os.path.join(run, "manifest.txt"), "--debug", "--fuel-quantum", FUELQ, "--timeout", "3600"],
                           cwd=run, stdout=fh, stderr=subprocess.STDOUT,
                           env=dict(os.environ, CQB_PRIO=os.environ.get("CQB_PRIO", "20")))  # 40 games, as trunkmerge's identity: at 5 agents waited up to 46 min (2 Nov)
    same = diff = miss = 0
    for mp in maps:
        for seat in "AB":
            pa, pb = os.path.join(gb, f"{mp}__{seat}.repl26a"), os.path.join(gn, f"{mp}__{seat}.repl26a")
            try:
                ra = zipfile.ZipFile(pa).read("replay.repl26a"); rb = zipfile.ZipFile(pb).read("replay.repl26a")
            except (OSError, KeyError, zipfile.BadZipFile):
                miss += 1; fail(f"game missing: {mp} seat {seat} ({pa} / {pb})"); continue
            if ra == rb:
                same += 1
            else:
                diff += 1; fail(f"NULL plays differently from BASE: {mp} seat {seat} ({pa} vs {pb})")
    info(f"null vs BASE at unlimited fuel: {same}/{same + diff + miss} games byte-identical")


def play_cxe(base, nd, wn, maps, opp):
    """The null-identity games on cxe at unlimited fuel, played on the Condor pilots (tools/cxe/pilotcxe.py; owner 6 Nov: "make
    condor do more work"): BASE's and NULL's libraries (NULL from the wasm this check already built on a pilot), byte-identical
    replays required. -> True when it decided (PASS or FAIL rows written), False to fall back to the CLI games on Condor.
    MERGECHECK_CXE=0: always the CLI path."""
    if os.environ.get("MERGECHECK_CXE", "1") in ("", "0") or not wn or not os.path.exists(wn):
        return False
    try:
        cxd = os.path.join(os.path.dirname(LAB), "cxe")
        sys.path.insert(0, cxd)
        import cxebuild
        import pilotcxe
        sb, so, sn = cxebuild.build_bot(name_of(base)), cxebuild.build_bot(opp), cxebuild.build_bot(nd, wasm=wn)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        info(f"cxe identity unavailable ({str(e)[:120]}): CLI games on Condor")
        return False
    out = os.path.join(GAMES, "cxe", time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"_{os.getpid()}")
    os.makedirs(out, exist_ok=True)
    games, keys = [], []
    for mp in maps:
        mf = os.path.join(MAPDIR, mp + ".map26a")
        for who, lib in (("b", sb), ("n", sn)):
            for seat in "AB":
                a, b = (lib, so) if seat == "A" else (so, lib)
                games.append((a, b, mf, f"{out}/{mp}__{seat}_{who}", "--fuel 1000000000"))
        keys += [(mp, "A"), (mp, "B")]
    t0 = time.time()
    ok = pilotcxe.run(games, say=lambda m: info(m))
    if not ok:
        man = os.path.join(out, "man.txt")
        open(man, "w").write("".join(f"{a} {b} {m} {o} {x}\n" for a, b, m, o, x in games))
        r = subprocess.run([sys.executable, "-I", os.path.join(cxd, "cxerun.py"), man, "--jobs", "4"], capture_output=True, text=True)
        if r.returncode:
            info(f"cxe identity: local cxe failed too ({r.stdout[-200:]}): CLI games on Condor")
            shutil.rmtree(out, ignore_errors=True)
            return False
    same = diff = 0
    for mp, seat in keys:
        try:
            ra = open(f"{out}/{mp}__{seat}_b.repl26a", "rb").read()
            rb = open(f"{out}/{mp}__{seat}_n.repl26a", "rb").read()
        except OSError:
            info(f"cxe identity: a replay is missing ({mp} {seat}): CLI games on Condor")
            shutil.rmtree(out, ignore_errors=True)
            return False
        if ra == rb:
            same += 1
        else:
            diff += 1
            fail(f"NULL plays differently from BASE: {mp} seat {seat} (cxe, unlimited fuel)")
    info(f"null vs BASE at unlimited fuel: {same}/{same + diff} games byte-identical (cxe, "
         f"{'pilots' if ok else 'local'}, {time.time() - t0:.0f} s)")
    shutil.rmtree(out, ignore_errors=True)
    return True


def null_check(cand, base, tc, tb, a):
    setup_ws()
    null_is_cand = False
    if a.null_bot:
        nd = place(srcfiles(botdir(a.null_bot)))
        info(f"null = {a.null_bot}")
    else:
        nf, notes = make_null(cand, base, tc, tb, a.nullsw)
        if nf is None:
            return
        if not notes:
            warn("CAND adds or changes no runtime TAB entry: the null equals CAND (all changes are code)")
            null_is_cand = not a.nullsw  # owner 8 Nov: a ship needs no switch, so a switchless play change has no null to prove equal to BASE
        for n_ in notes:
            info("null: " + n_)
        nd = place(nf)
    cd = place(srcfiles(cand))
    info(f"build dirs: CAND {cd}  NULL {nd}")
    if not a.no_build:
        if a.build_on == "condor":
            got = build_condor([cd, nd]); wc, wn = got.get(cd), got.get(nd)
        else:
            wc = build(cd, a.cores); wn = build(nd, a.cores) if nd != cd else wc
        if wc and wn:
            same, nbytes, ndata, other = wsec(wc, wn)
            if same:
                info(f"wsec CAND vs NULL: code section IDENTICAL ({nbytes} bytes"
                     + (f"; only {same.split()[1]} load/store offsets into data moved: data layout, not code" if isinstance(same, str) else "")
                     + f"), {ndata} data bytes differ"
                     + (f"; other sections differ: {other}" if other else ""))
            else:
                fail(f"wsec CAND vs NULL: code section DIFFERS ({wc} vs {wn}): a flag is compiled (#if or folded const), "
                     "not runtime data")
    if null_is_cand:
        info("null identity skipped: no switch, so no null to compare with BASE")
    if not a.no_play and not null_is_cand:
        maps = DEFAULT_MAPS
        if a.maplist:
            maps = [l.strip().replace(".map26a", "") for l in open(a.maplist) if l.strip()]
        maps = [m for m in maps if os.path.isfile(os.path.join(MAPDIR, m + ".map26a"))][:a.maps]
        if not play_cxe(base, nd, wn if not a.no_build else None, maps, OPP):
            play(base, nd, maps, OPP)


def main():
    sys.stdout.reconfigure(line_buffering=True)  # 2 Nov: buffered output left 0-byte logs that read as hangs under timeout or nohup
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("cand"); ap.add_argument("base")
    ap.add_argument("--donor", action="append", default=[])
    ap.add_argument("--allow-missing", action="append", default=[])
    ap.add_argument("--maps", type=int, default=10); ap.add_argument("--maplist")
    ap.add_argument("--no-build", action="store_true"); ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--null-bot"); ap.add_argument("--nullsw", action="append", default=[])
    ap.add_argument("--cores", type=int, default=2); ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--cpus", default="")
    ap.add_argument("--build-on", choices=("condor", "local"), default="condor")
    a = ap.parse_args()
    global CPUS
    CPUS = a.cpus
    cand, base = botdir(a.cand), botdir(a.base)
    print(f"== mergecheck {name_of(cand)} vs {name_of(base)} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})")
    donors = []
    for d in a.donor:
        dn, _, db = d.partition(":")
        dd = botdir(dn)
        donors.append((dd, botdir(db) if db else infer_base(dd, base)))
    print("== (a) functions CAND changes vs BASE")
    fd = funcdiff(cand, base)
    if not a.quiet:
        print("\n".join("  " + l for l in fd.splitlines()))
    if donors:
        dsig = set()
        for d, db in donors:
            dsig |= changed_sigs(funcdiff(d, db))
        dfn = {s for f, s in dsig}
        extra = [(f, s) for f, s in sorted(changed_sigs(fd)) if s not in dfn]
        for f, s in extra:
            warn(f"changed in CAND, by no donor: {f}: {s[:100]}")
        info(f"{len(changed_sigs(fd))} changed places in CAND, {len(extra)} not changed by any donor")
    print("== (b) donor accounting")
    if donors:
        donor_check(cand, base, donors, a.allow_missing)
    else:
        info("no --donor given")
    print("== (c) defines, TABs, magics")
    tc, tb = static_checks(cand, base)
    print("== (d) conflict markers, stray files")
    markers(cand)
    try:  # 6 Nov (owner: one change consistent across the code base; primer RULE SINGLE-SOURCE): hand-written rule numbers, WARN only
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ruleslint
        rl = ruleslint.diff(base, cand)
        for f, k, r, h, t in rl[:12]:
            warn(f"rules lint {f}:{k} {r}: call {h} | {t[:90]}")
        if len(rl) > 12:
            warn(f"rules lint: {len(rl) - 12} more (python3 -I tools/lab/ruleslint.py diff BASE CAND)")
        info(f"rules lint: {len(rl)} added line(s) with a hand-written rule number")
        nb, nn, grew = ruleslint.ratchet(base, cand)  # 6 Nov (owner): a merge may not add hand-written rule numbers
        if nn > nb:
            fail(f"rules lint ratchet: {nb} -> {nn} hand-written rule numbers ({dict(grew)}); call the helper, or list a policy constant in "
                 "tools/lab/ruleslint_allow.txt")
        else:
            info(f"rules lint ratchet: {nb} -> {nn} (ok)")
    except Exception as e:  # noqa: BLE001  a lint never stops the check
        info(f"rules lint skipped: {e}")
    try:  # 6 Nov (owner: numbers correct and consistent): rule helpers v the Rule checker's tables (tools/lab/rulestest.py); FAIL on a
        # direct-helper mismatch, skipped when rs.h / mult.h and the tables equal BASE's and BASE passed
        r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rulestest.py"),
                            os.path.basename(os.path.normpath(cand)), "--base", os.path.basename(os.path.normpath(base))],
                           capture_output=True, text=True, timeout=1800)
        first = (r.stdout.strip().splitlines() or ["(no output)"])[0]
        if r.returncode == 1:
            fail(f"rules test: {first} (python3 -I tools/lab/rulestest.py CAND)")
        elif r.returncode == 2:
            warn(f"rules test could not run: {first[:160]}")
        else:
            info(f"rules test: {first[:160]}")
    except Exception as e:  # noqa: BLE001
        warn(f"rules test skipped: {e}")
    print("== (e) null build + identity at unlimited fuel")
    null_check(cand, base, tc, tb, a)
    v = "FAIL" if FAILS else "PASS"
    print(f"== MERGECHECK {v}: {name_of(cand)} vs {name_of(base)}: {len(FAILS)} FAIL, {len(WARNS)} WARN")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
