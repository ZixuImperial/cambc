#!/usr/bin/env python3
"""dgkit: the shared diag copy, logger and reader, so build agents stop hand-writing them. Tool builder, 2 Nov.

  python3 -I tools/lab/dgkit.py make BASE NEW SPEC.py          bots/NEW = BASE + the logger + SPEC's hooks
  python3 -I tools/lab/dgkit.py run NEW OPP MAPLIST DIR [--rounds N] [--allow-zero] [--engine cxe|cli]   play both seats on Condor (debug build) into DIR/rep
      --release (12 Nov, Coordinator + Path Finding: release v release): NEW plays as a RELEASE build too. A copy NEW_dgrel (in
      /data/USER/st/new/bots, linked in bots/) has dgkit's debug_block wrappers taken off its own lines only (DG, slot, drain), so the records
      print in release; cxe keeps the team stdout (CXE_STDOUT=1). The copy keeps release fuel timing, apart from the record writes themselves.
      engine cxe (default, 10 Nov; owner: everything on Condor uses the fast engine): NEW as a cxe library of its DEBUG build (tools/cxe/dbgso.py),
      OPP as its release library (or dbgso when OPP is a diag copy too), games on the pilots through tools/cxe/cxerun.py with CXE_STDOUT=1; each
      game is packed as the CLI's bundle (DIR/rep/MAP__a|b.repl26a: replay.repl26a + team-a/b.stdout), so readers see the same layout.
      --engine cli or DGKIT_ENGINE=cli: the old CLI debug run (cqbatch --debug, wasmtime, ~8x the pool time); also the fallback when dbgso fails.
      Priority: CQB_PRIO / READ_PRIO / CONDAB_PRIO, else 9 (Step 0 diags).
  python3 -I tools/lab/dgkit.py read DIR-or-replay [--tag T]   counts per tag, or T's lines
SPEC.py is Python calling at(file, anchor, code, where="after"|"before"|"replace"); the anchor must occur exactly once (it also gets src and
base_src, the two src dirs, for whole-file edits; tools/lab/dgspec_trace.py is the decision trace). In code, write
  DG("tag", a, b, ...);   integers only (int64; cast floats yourself, e.g. int(100 * x)). Nothing else is needed.
For example: at("econ.cpp", "void set_target(int gi, float rate, int crew)\\n{\\n", 'DG("st", gi, crew);\\n')
Each record is the stdout line `D ROUND SLOT tag a b ...`, written with an integer writer inside debug_block (never printf): free in debug builds,
skipped in release, so a diag copy plays only in debug. Debug timing can differ from release: measure with it, never score with it.
In Python, `import dgkit; dgkit.records(path)` yields dict(team="a"|"b", r, slot, tag, v=[ints]), ready for a readmany.py reader:
  def read(path, meta): return dict(n=sum(1 for x in dgkit.records(path) if x["team"] == meta["seat"] and x["tag"] == "st"))
Never arm a diag copy. newbot.sh puts it on /data with a link, so it costs one home file.
DRAFT TURN: DG() records made during the draft never come out (the buffer drains at a play turn's end, debug only). For draft values use
tools/lab/dglog.h + tools/lab/draftdiag.py (release build, native engine, every record kept, games stop after round 2)."""
import collections
import glob
import re
import os
import shutil
import subprocess
import sys
import time
import zipfile

REPO = "/homes/USER/cambc"
HOOK = "planner::stat_turn_end(planned);\n"
HOOK2 = "\tact_first_mark_overlong_turn();\n"  # v698 on: play_turn's turn end (no planner stats)
START = "\tcomms::read();\n"  # brain.cpp turn(): early in every turn  # brain.cpp: every path through a turn (3 places, with SPIN_SELF's loop); the buffer drains here
HEADER = r'''#pragma once
// dgkit logger (tools/lab/dgkit.py): integer records in a static buffer, written to stdout at each turn end. Debug builds only.
#include <cstdint>
#include <cstdio>
#include <initializer_list>
namespace dgv
{
inline char buf[1 << 19];
inline int n = 0, slot = -1;  // slot: set when the plan is built, so -1 on records before it
inline void s(const char* p) noexcept
{
	while (*p && n < static_cast<int>(sizeof(buf)) - 1)
		buf[n++] = *p++;
}
inline void i(std::int64_t v) noexcept
{
	char t[24];
	int k = 0;
	std::uint64_t u = v < 0 ? -static_cast<std::uint64_t>(v) : static_cast<std::uint64_t>(v);
	do
	{
		t[k++] = static_cast<char>('0' + u % 10);
		u /= 10;
	} while (u && k < 23);
	if (v < 0 && n < static_cast<int>(sizeof(buf)) - 1)
		buf[n++] = '-';
	while (k && n < static_cast<int>(sizeof(buf)) - 1)
		buf[n++] = t[--k];
}
inline void rec(std::int64_t r, std::int64_t slot, const char* tag, std::initializer_list<std::int64_t> v) noexcept
{
	s("D ");
	i(r);
	s(" ");
	i(slot);
	s(" ");
	s(tag);
	for (std::int64_t x : v)
	{
		s(" ");
		i(x);
	}
	s("\n");
}
inline void drain() noexcept
{
	if (n > 0)
		std::fwrite(buf, 1, static_cast<std::size_t>(n), stdout);
	n = 0;
	std::fflush(stdout);
}
} // namespace dgv
// do-while: debug_block is an if/else construct, so `if (c) DG(...); else ...` or a later else bound to the wrong if (b927, 3 Nov: no records at all)
#define DG(tag, ...) do { debug_block({ dgv::rec(static_cast<std::int64_t>(cambc::round_number()), dgv::slot, tag, {__VA_ARGS__}); }); } while (0)
'''


def same_statement(old, new):
    """True when NEW (a replace of OLD) starts with the same keyword or token and has as many top-level ';' as OLD: it rewrites the
    statement in place (e.g. a counter added inside an if's condition) instead of adding one"""
    def first(x):
        m = re.match(r"\s*([A-Za-z_]\w*|\S)", re.sub(r"//[^\n]*", "", x))
        return m.group(1) if m else ""
    def semis(x):
        x, d, n = re.sub(r"//[^\n]*", "", x), 0, 0
        for c in x:
            d += {"(": 1, "[": 1, ")": -1, "]": -1}.get(c, 0)
            n += c == ";" and d == 0
        return n
    return first(old) == first(new) and semis(old) == semis(new)


def unbraced_head(before):
    """The control keyword whose unbraced body would start right after BEFORE (the source text up to an insertion point), else ''.
    9 Nov (b1760 ALT): a line-based check missed an if whose condition spans two lines; this walks back over the closing ')' to its '('."""
    s = re.sub(r"//[^\n]*", "", before)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S).rstrip()
    if re.search(r"(^|[^A-Za-z0-9_])else$", s):
        return "else"
    if not s.endswith(")"):
        return ""
    depth, i = 0, len(s) - 1
    while i >= 0:
        c = s[i]
        if c == ")":
            depth += 1
        elif c == "(":
            depth -= 1
            if depth == 0:
                break
        i -= 1
    m = re.search(r"(?:^|[^A-Za-z0-9_])(if|for|while|switch)\s*$", s[:max(i, 0)])
    return m.group(1) if m and m.group(1) != "switch" else ""


def make(base, new, spec):
    r = subprocess.run(["sh", f"{REPO}/tools/lab/newbot.sh", base, new], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    src = os.path.join(os.path.realpath(f"{REPO}/bots/{new}"), "src") + "/"

    def resolve(fn, anchor):
        """new layout: an old file name (econ.cpp) resolves to the one file holding the anchor"""
        if os.path.exists(src + fn):
            return fn
        hits = [f for f in sorted(os.listdir(src)) if f.endswith((".cc", ".h")) and anchor in open(src + f, errors="surrogateescape").read()]
        if len(hits) != 1:
            sys.exit(f"dgkit: {fn}: no such file, and the anchor is in {len(hits)} files: {anchor[:70]!r}\nbots/{new} is only partly edited: do not play it; use a new name")
        return hits[0]

    def at(fn, anchor, code, where="after"):
        fn = resolve(fn, anchor)
        s = open(src + fn).read()
        k = s.count(anchor)
        if k != 1:
            sys.exit(f"dgkit: {fn}: anchor found {k} times: {anchor[:70]!r}\nbots/{new} is only partly edited: do not play it; use a new name")
        if where not in ("after", "before", "replace"):
            sys.exit(f"dgkit: bad where {where!r}")
        # 3 Nov (b935) / 9 Nov (b1760 ALT, a two-line if condition): code that lands where an unbraced if/for/while/else body starts becomes
        # that body, and the original body then runs every time. Checked on the source text up to the insertion point, conditions of any length.
        cut = s.index(anchor) + (len(anchor) if where == "after" else 0)
        head = unbraced_head(s[:cut])
        if head and where == "replace" and same_statement(anchor, code):
            head = ""  # 10 Nov (b1802 TRB, firecount): `if (c)` -> `if ((c) && DG(..))` under an unbraced for is still that for's one statement
        if head:
            sys.exit(f"dgkit: {fn}: code {where} this anchor would become the body of an unbraced '{head}' and the original statement would run "
                     f"every time. Anchor on the control statement too and rewrite it braced, or hook elsewhere"
                     f"\nbots/{new} is only partly edited: do not play it; use a new name")
        open(src + fn, "w").write(s.replace(anchor, anchor + code if where == "after" else code + anchor if where == "before" else code))
    open(src + "dgkit.h", "w").write(HEADER)
    at("common.h", "#pragma once\n", '#include "dgkit.h"\n')
    at("plan.cpp", "\t\t\tP.my_slot = i;\n\t}\n", "\tdebug_block({ dgv::slot = P.my_slot; }); // dgkit\n")
    brain = ["brain.cpp"] if os.path.exists(src + "brain.cpp") else sorted(f for f in os.listdir(src) if f.startswith("brain_") and f.endswith(".cc"))
    texts = {f: open(src + f, errors="surrogateescape").read() for f in brain}
    # 10 Nov (b1818): v698 (fxb18z) dropped planner::stat_turn_end from play_turn; fall back to the line after it (play_turn's turn end)
    hook = HOOK if any(HOOK in t for t in texts.values()) else HOOK2
    if not any(hook in t for t in texts.values()):
        sys.exit(f"dgkit: {brain}: no turn-end hook {HOOK!r} or {HOOK2!r}")
    for f, s in texts.items():
        s = s.replace(hook, hook + "debug_block({ dgv::drain(); }); // dgkit\n")
        # 3 Nov (b927): a turn that throws never reaches its end, so its records stayed in the buffer for good; drain at each turn's start as well
        if s.count(START) == 1:
            s = s.replace(START, "debug_block({ dgv::drain(); }); // dgkit\n" + START)
        open(src + f, "w", errors="surrogateescape").write(s)
    # 3 Nov (Combat): specs also get src (NEW's src dir, after the logger edits) and base_src (BASE's), for whole-file edits
    exec(compile(open(spec).read(), spec, "exec"), dict(at=at, src=src, base_src=os.path.join(os.path.realpath(f"{REPO}/bots/{base}"), "src") + "/"))
    print(f"dgkit: bots/{new} ready; play it with: dgkit.py run {new} OPP MAPLIST DIR")


ALLOW_ZERO = "--allow-zero" in sys.argv


PRIO = os.environ.get("CQB_PRIO") or os.environ.get("READ_PRIO") or os.environ.get("CONDAB_PRIO") or "9"  # as cqbatch --debug (DEBUG_PRIO 9)


def maps_of(maplist):
    out, seen = [], set()
    for ln in open(maplist):
        m = ln.strip()
        if not m or m in seen:
            continue
        seen.add(m)
        mp = m if m.endswith(".map26a") else f"/data/USER/work301/maps/{m}.map26a"
        out.append((os.path.basename(mp)[:-7], mp))
    return out


def is_diag(bot):
    """A dgkit diag copy (its src holds the logger): it needs the debug build to print anything."""
    src = f"{REPO}/bots/{bot}/src"
    for f in glob.glob(src + "/*"):
        try:
            if "dgv::" in open(f, errors="replace").read():
                return True
        except OSError:
            pass
    return False


def zero_check(rc, d):
    n = sum(1 for f in glob.glob(f"{d}/rep/*.repl26a") for _ in records(f))
    if rc == 0 and n == 0 and not ALLOW_ZERO:  # 3 Nov (b935): a copy whose hooks never ran read as 'nothing happened'
        print(f"dgkit: 0 records in {len(glob.glob(f'{d}/rep/*.repl26a'))} games: the hooks never ran, or the build was not debug. Check the call sites "
              f"(one unconditional DG at each hook), or pass --allow-zero if none is expected.", file=sys.stderr)
        return 3
    return rc


def run_cli(bot, opp, maplist, d, rounds):
    os.makedirs(f"{d}/rep", exist_ok=True)
    B, O = f"{REPO}/bots/{bot}", f"{REPO}/bots/{opp}"
    lines = []
    for nm, mp in maps_of(maplist):
        lines += [f"{B} {O} {mp} rep/{nm}__a.repl26a", f"{O} {B} {mp} rep/{nm}__b.repl26a"]
    open(f"{d}/man.txt", "w").write("\n".join(lines) + "\n")
    cmd = ["nice", "-n", "10", "python3", "-I", f"{REPO}/tools/lab/cqbatch.py", "man.txt", "--debug", "--log-limit", "8000000"]
    if rounds:
        cmd += ["--rounds", str(rounds)]
    return zero_check(subprocess.run(cmd, cwd=d).returncode, d)


REL_SUBS = (("do { debug_block({ dgv::rec(", "do { { dgv::rec("), ("{__VA_ARGS__}); }); } while (0)", "{__VA_ARGS__}); } } while (0)"),
            ("debug_block({ dgv::slot = P.my_slot; }); // dgkit", "{ dgv::slot = P.my_slot; } // dgkit"),
            ("debug_block({ dgv::drain(); }); // dgkit", "{ dgv::drain(); } // dgkit"))


def release_copy(bot):
    """12 Nov (--release): NEW_dgrel, a copy of the diag copy whose dgkit hooks print in a release build. -> its name, or exits."""
    name = bot + "_dgrel"
    src = os.path.join(REPO, "bots", bot, "src")
    if not os.path.isdir(src):
        sys.exit(f"dgkit --release: no {src}")
    real = f"/data/USER/st/new/bots/{name}"
    link = os.path.join(REPO, "bots", name)
    if os.path.lexists(link) and os.path.realpath(link) != real:
        sys.exit(f"dgkit --release: bots/{name} exists and is not this tool's copy: not touching it")
    shutil.rmtree(real, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "bots", bot), real, symlinks=True, ignore=shutil.ignore_patterns("build", ".cambc", "SHIPCHECK*"))
    if any(os.path.islink(os.path.join(dp, x)) for dp, dn, fn in os.walk(real) for x in dn + fn):
        sys.exit(f"dgkit --release: {real} holds symlinks: not patching it")
    left = 0
    for dp, _, fn in os.walk(os.path.join(real, "src")):
        for x in fn:
            p = os.path.join(dp, x)
            try:
                t = open(p).read()
            except (OSError, UnicodeDecodeError):
                continue
            t2 = t
            for a_, b_ in REL_SUBS:
                t2 = t2.replace(a_, b_)
            left += t2.count("debug_block({ dgv::")
            if t2 != t:
                open(p, "w").write(t2)
    if left:
        sys.exit(f"dgkit --release: {left} dgkit debug_block wrapper(s) of an unknown form left in {real}/src: not run")
    if not os.path.lexists(link):
        os.symlink(real, link)
    return name


def cxe_libs(bot, opp, release=False):
    """-> (NEW's debug .so, OPP's .so) or None (logged): both built at once, each in its own process (the builders sys.exit on errors)."""
    py = [sys.executable, "-I"]
    if release:  # 12 Nov: release v release (NEW's records print in its release build)
        bot = release_copy(bot)
    pb = subprocess.Popen(py + [f"{REPO}/tools/cxe/{'cxebuild.py' if release else 'dbgso.py'}", bot], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    po = None
    if opp != bot:
        tool = "dbgso.py" if is_diag(opp) and not release else "cxebuild.py"
        po = subprocess.Popen(py + [f"{REPO}/tools/cxe/{tool}", opp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    res = []
    for who, p in ((bot, pb), (opp, po)):
        if p is None:
            res.append(res[0])
            continue
        out, err = p.communicate()
        so = (out.strip().splitlines() or [""])[-1]
        if p.returncode or not so.endswith(".so") or not os.path.exists(so):
            # 11 Nov (Builder 1aa65e, b1828 nlp0): a compile error made the CLI fallback fail the same way, read as a slow run. A compiler
            # error now stops here; other failures (e.g. engine imports cxe lacks: dbgso's list) still fall back to the CLI.
            txt = (err or "") + "\n" + (out or "")
            m = re.search(r"^\S+:\d+:\d+: (?:fatal )?error: .*$", txt, re.M) or re.search(r"^.*\b(?:error|fatal error): .*$", txt, re.M)
            if m:
                print(f"dgkit: diag copy failed to compile: {who}: {m.group(0).strip()[:400]}", file=sys.stderr, flush=True)
                sys.exit(3)
            print(f"dgkit: cxe library of {who} failed (rc {p.returncode}): {(err or out).strip()[-300:]}", file=sys.stderr)
            res.append(None)
        else:
            res.append(so)
    return tuple(res) if all(res) else None


def pack(pre, out):
    """cxe's game files (PRE.repl26a raw, PRE.team-a/b.stdout) -> the CLI's bundle at OUT (zip: replay.repl26a, team-a.stdout, team-b.stdout)."""
    if not os.path.exists(pre + ".repl26a"):
        return False
    with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pre + ".repl26a", "replay.repl26a")
        for t in ("a", "b"):
            f = f"{pre}.team-{t}.stdout"
            if os.path.exists(f):
                z.write(f, f"team-{t}.stdout")
            else:
                z.writestr(f"team-{t}.stdout", "")
    os.replace(out + ".tmp", out)
    for x in (".repl26a", ".team-a.stdout", ".team-b.stdout"):
        try:
            os.remove(pre + x)
        except OSError:
            pass
    return True


def run_cxe(bot, opp, maplist, d, rounds, release=False):
    """-> rc, or None: no cxe library (the caller runs the CLI path)."""
    t0 = time.time()
    libs = cxe_libs(bot, opp, release)
    if libs is None:
        return None
    sb, so = libs
    print(f"dgkit: cxe libraries ready in {time.time() - t0:.0f} s: {bot} ({'release, records on' if release else 'debug'}) {sb}, {opp} {so}", flush=True)
    os.makedirs(f"{d}/rep", exist_ok=True)
    os.makedirs(f"{d}/cxeg", exist_ok=True)
    extra = f" --rounds {int(rounds)}" if rounds else ""
    lines, games = [], []
    for nm, mp in maps_of(maplist):
        for seat, a, b in (("a", sb, so), ("b", so, sb)):
            pre = f"{d}/cxeg/{nm}__{seat}"
            lines.append(f"{a} {b} {mp} {pre}{extra}")
            games.append((pre, f"{d}/rep/{nm}__{seat}.repl26a"))
    open(f"{d}/man_cxe.txt", "w").write("\n".join(lines) + "\n")
    env = dict(os.environ, CXE_STDOUT="1", CXE_PRIO=PRIO)
    env.setdefault("CXEFARM", "1")  # owner 10 Nov: Condor, even for a small run (the main machine stays light); CXEFARM=0 / CXE_LOCAL=1: local
    rc = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxerun.py", f"{d}/man_cxe.txt"], env=env).returncode
    got = sum(pack(pre, out) for pre, out in games)
    try:
        os.rmdir(f"{d}/cxeg")
    except OSError:
        pass
    print(f"dgkit: cxe: {got}/{len(games)} games in {time.time() - t0:.0f} s (engine cxe, {'release' if release else 'debug'} {bot}, priority {PRIO})", flush=True)
    if got < len(games):
        rc = rc or 1
    return zero_check(rc, d)


def run_games(bot, opp, maplist, d, rounds, engine="cxe", release=False):
    if engine == "cxe":
        rc = run_cxe(bot, opp, maplist, d, rounds, release)
        if rc is not None:
            return rc
        if release:
            print("dgkit --release: no cxe library: no CLI fallback for a release run (the CLI keeps no release stdout)", file=sys.stderr)
            return 1
        print("dgkit: FALLBACK: no cxe library (see above): playing on the CLI engine (cqbatch --debug, ~8x the pool time)", file=sys.stderr, flush=True)
    return run_cli(bot, opp, maplist, d, rounds)


def records(path):
    """Yield dict(team, r, slot, tag, v) from a replay bundle's team stdouts. Also takes a raw cxe replay PRE.repl26a (not a zip): its
    stdouts are the files PRE.team-a.stdout / PRE.team-b.stdout beside it."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            txts = {t: z.read(f"team-{t}.stdout").decode("latin1") for t in ("a", "b") if f"team-{t}.stdout" in z.namelist()}
    else:
        pre = path[:-8] if path.endswith(".repl26a") else path
        txts = {t: open(f"{pre}.team-{t}.stdout", encoding="latin1").read() for t in ("a", "b") if os.path.exists(f"{pre}.team-{t}.stdout")}
    for team in ("a", "b"):
        txt = txts.get(team)
        if txt is None:
            continue
        for ln in txt.splitlines():
            p = ln.replace("\0", "").split()  # chunks of a team's stdout can start with NUL bytes
            if len(p) >= 4 and p[0] == "D":
                try:
                    yield dict(team=team, r=int(p[1]), slot=int(p[2]), tag=p[3], v=[int(x) for x in p[4:]])
                except ValueError:
                    pass


def read(src, tag):
    rd = os.path.join(src, "rep") if os.path.isdir(os.path.join(src, "rep")) else src  # DIR (DIR/rep) or a directory of replays (cxe's g/)
    files = [src] if os.path.isfile(src) else [os.path.join(rd, f) for f in sorted(os.listdir(rd)) if f.endswith(".repl26a")]
    c = collections.Counter()
    for f in files:
        for x in records(f):
            c[x["tag"]] += 1
            if tag and x["tag"] == tag:
                print(os.path.basename(f), x["team"], x["r"], x["slot"], *x["v"])
    print(f"{len(files)} replays; records per tag: {dict(c.most_common())}")


def main():
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "make":
        return make(*a[1:])
    if a[:1] == ["run"] and len(a) >= 5:
        rounds = int(a[a.index("--rounds") + 1]) if "--rounds" in a else 0
        engine = a[a.index("--engine") + 1] if "--engine" in a else os.environ.get("DGKIT_ENGINE", "cxe")
        if engine not in ("cxe", "cli"):
            sys.exit("dgkit: --engine cxe|cli")
        if "--release" in a and engine != "cxe":
            sys.exit("dgkit: --release needs --engine cxe")
        return run_games(a[1], a[2], a[3], os.path.abspath(a[4]), rounds, engine, "--release" in a)
    if a[:1] == ["read"] and len(a) >= 2:
        return read(a[1], a[a.index("--tag") + 1] if "--tag" in a else None)
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
