#!/usr/bin/env python3
"""trunkmerge: merge one or more donors into a new trunk in one call. Tool builder (trunk keeper), 1 Nov (owner: "can merging be
faster?"; Builder: one call per batch of donors, one identity batch per new trunk).

usage: python3 -I tools/lab/trunkmerge.py DONOR[:BASE] [DONOR[:BASE] ...] TRUNK NEW --set "FLAG=VAL ..." [--live BOT]
                                        [--maps N] [--no-identity] [--dry]
  1. NEW = newbot.sh copy of TRUNK (no FLIP/SHIPCHECK).
  2. Per donor, in order: BASE = the given one, else mergecheck.infer_base (the live version the donor's files are closest to).
     For every source file the donor changed vs its BASE: the trunk still has BASE's text -> take the donor's file; else
     `git merge-file -p TRUNKFILE BASEFILE DONORFILE` (3-way). Any conflict stops the run: NEW is kept with the conflicted
     file (markers in it) for a hand fix. Donor file sha1s are recorded.
  3. --set: the trunk's values for the donors' flags (the live values: new features at 0, masters as their table needs),
     written as `#define FLAG VAL` (each defined exactly once), then `flip.py check` on them (data-only flags).
     New tables (slot-0 magics not in TRUNK) are listed with their values, so a forgotten flag shows.
  4. mergecheck NEW LIVE --donor D:BASE ... (static) must PASS.
  5. Build NEW (release, /data/zw4424/ablproj_4.0.0).
  6. ONE unlimited-fuel identity batch for the whole new trunk vs LIVE (default: live.txt's first line): N maps (default 10,
     incl. the spike maps) x 2 seats vs nova_spar_nochase2, cqbatch --release --fuel-quantum 10000000, replays byte-equal. A
     flag left on, or flag-0 work that changes play, fails here.
  7. Appends a line to condor-work/reports/trunk_registry.md. Prints a timing per step. Exit 0 only when everything passed.
  --union FILE (repeatable): a conflict in FILE keeps both sides, only if in every conflict block both sides purely add lines (empty base,
     e.g. two flag tables at one spot); any other conflict still stops. --subst "FILE|||OLD|||NEW" (repeatable): after the merges, an exact
     edit that must match once, for a one-line overlap given by hand. Both are recorded in the registry line; mergecheck and identity still decide.
  --union-auto: --union for every file (3 Nov, Builder: b995 needed two hand rebases for two flag-table blocks added at one anchor in
     common.h); still only where every conflict block is a pure addition on both sides. armq passes it.
  --dry: steps 1-3 into a scratch name and stop (no build, no games, no registry line), to preview the merge.
Develop-on-the-trunk: a donor built as `newbot.sh <current trunk> NEW` has the trunk as its BASE, so step 2 takes its files
(the trunk did not move) or 3-way merges against the trunk it started from (the trunk moved since): give DONOR:TRUNKNAME."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import sys
import time
import zipfile

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
import mergecheck as MC  # noqa: E402

REG = os.environ.get("TRUNK_REGISTRY", "/homes/zw4424/condor-work/reports/trunk_registry.md")  # a test run must not add a line
PROJ = "/data/zw4424/ablproj_4.0.0"
CLI = "/data/zw4424/cambc400/bin/cambc400"
MAPS = ["gen_bk2_00012", "gen_dom_067", "gen_g5_037", "gen_hbd_299", "gen_s_003", "gen_g3_023", "gen_bk2_00500", "gen_u_011",
        "gen_g_005", "gen_bk2_01234", "gen_bk2_00777", "gen_s_101", "gen_g4_039", "gen_bk2_02222"]
CMP = "/data/zw4424/st/b631/tools/cmp.py"
ID_FUEL = "10000000"
ID_PRIO = "20"  # the Condor order among our own jobs: ahead of pilots' 10 and cqbatch's 5
T0 = time.time()
TIMES = []


def step(name, t):
    TIMES.append((name, time.time() - t))


def sha(p):
    return hashlib.sha1(open(p, "rb").read()).hexdigest()[:12]


def die(msg, code=1):
    print(f"trunkmerge: {msg}")
    print("timings: " + ", ".join(f"{n} {s:.0f}s" for n, s in TIMES))
    sys.exit(code)


def tables(src):
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/flip.py"), "list", src], capture_output=True, text=True)
    out = {}
    for ln in r.stdout.splitlines():
        m = re.search(r"magic (0x[0-9A-Fa-f]+)", ln)
        if m:
            out[m.group(1).lower()] = ln.strip()
    return out


def id_cxe(idd, M, maps, live, new, tw):
    """The identity games on cxe: LIVE and NEW v nochase2, both seats, each map, at ID_FUEL; -> (games whose raw replays are
    byte-identical, games) or None (anything failed: the Condor batch decides as before). NEW is translated from flip.sh's trunk
    wasm when it exists (no second CLI build)."""
    try:
        sys.path.insert(0, os.path.join(REPO, "tools/cxe"))
        import cxebuild
        so_live, so_opp = cxebuild.build_bot(live), cxebuild.build_bot(MC.OPP)
        so_new = cxebuild.build_bot(new, wasm=tw) if os.path.exists(tw) else cxebuild.build_bot(new)
        d = os.path.join(idd, "cxe")
        os.makedirs(d, exist_ok=True)
        man, pairs = os.path.join(d, "man.txt"), []
        with open(man, "w") as f:
            for m in maps:
                for seat in "AB":
                    for tag, so in (("base", so_live), ("fix", so_new)):
                        a, b = (so, so_opp) if seat == "A" else (so_opp, so)
                        f.write(f"{a} {b} {M}/{m}.map26a {d}/{tag}_{seat}_{m} --fuel {ID_FUEL}\n")
                    pairs.append((f"{d}/base_{seat}_{m}.repl26a", f"{d}/fix_{seat}_{m}.repl26a"))
        import pilotcxe  # the pilots first (cxefarm: the same engine and libraries, byte-identical), local cxe as the fallback
        rows = [ln.split() for ln in open(man)]
        if pilotcxe.run([(x[0], x[1], x[2], x[3], " ".join(x[4:])) for x in rows], say=lambda m: print(m, flush=True)):
            r = subprocess.CompletedProcess([], 0, "", "")
        else:
            r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/cxe/cxerun.py"), man, "--jobs", "8"], capture_output=True,
                               text=True, env=dict(os.environ, CXE_PRIO="20"))
        same = sum(1 for x, y in pairs if os.path.exists(x) and os.path.exists(y) and open(x, "rb").read() == open(y, "rb").read())
        if r.returncode or not all(os.path.exists(x) and os.path.exists(y) for x, y in pairs):
            print(f"identity on cxe incomplete ({r.stdout[-200:]}): Condor", flush=True)
            return None
        for f in os.listdir(d):
            if f.endswith(".repl26a"):
                os.remove(os.path.join(d, f))
        return same, len(pairs)
    except (Exception, SystemExit) as e:  # noqa: BLE001  the Condor path still works
        print(f"identity on cxe failed ({str(e)[:200]}): Condor", flush=True)
        return None


def id_rows(idd, R, M, maps, live, new):
    """Manifest lines for the identity games the cache lacks, and (out file, cache file) pairs to store after the batch. A cached
    game is hard-linked into out/. Keyed by source hashes and fuel like mergecheck's games, but _release: mergecheck plays
    without --release, and the two must not mix. Games are deterministic, so a stale entry can only fail loudly."""
    opp = MC.OPP
    oh = MC.src_hash(MC.srcfiles(MC.botdir(opp)))
    lines, store = [], []
    for tag, b in (("base", live), ("fix", new)):
        g = os.path.join(MC.GAMES, f"{MC.src_hash(MC.srcfiles(MC.botdir(b)))}_{oh}_q{ID_FUEL}_release")
        os.makedirs(g, exist_ok=True)
        for m in maps:
            for seat, (x, y) in (("A", (b, opp)), ("B", (opp, b))):
                out, c = f"out/{tag}_{seat}_{m}.repl26a", os.path.join(g, f"{m}__{seat}.repl26a")
                if id_valid(c):
                    if not os.path.exists(os.path.join(idd, out)):
                        os.link(c, os.path.join(idd, out))
                else:
                    lines.append(f"{R}/{x} {R}/{y} {M}/{m}.map26a {out}")
                    store.append((out, c))
    return lines, store


def id_valid(p):
    try:
        with zipfile.ZipFile(p) as z:
            return "replay.repl26a" in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def id_store(idd, store):
    for out, c in store:
        p = os.path.join(idd, out)
        if id_valid(p) and not os.path.exists(c):
            try:
                os.link(p, c)
            except OSError:  # another run stored it first
                pass


def additive_conflicts(pt, pb, pd):
    """True when every conflict block of this 3-way merge has an empty base: both sides only add lines there."""
    out = subprocess.run(["git", "merge-file", "-p", "--diff3", pt, pb, pd], capture_output=True).stdout.decode("utf-8", "surrogateescape")
    blocks = re.findall(r"^\|{7}[^\n]*\n(.*?)^={7}$", out, re.M | re.S)
    return bool(blocks) and all(not b.strip() for b in blocks)


def live_bot():
    for ln in open("/data/zw4424/st/bq/live.txt"):
        m = re.match(r"v\d+\s+(\S+)", ln)
        if m:
            return m.group(1)
    die("no live line in live.txt")


DECL_ONLY = re.compile(r"^(//|/\*|\*|#|inline\s+(const\s+volatile|constexpr)\b|constexpr\b|static\s+constexpr\b|inline\s+[\w:<>]+\s+\w+\s*(=[^;()]*)?;)")


def provenance(donors, trunk, src):
    """-> ['FILE:LINE text', ...] merged blocks traceable to no single donor (see the call)"""
    import difflib
    def rd(p):
        try:
            return [x.strip() for x in open(p, encoding="utf-8", errors="replace").read().split("\n")]
        except OSError:
            return None
    def has(seq, win):
        if not win:
            return True
        k = len(win)
        return any(seq[i:i + k] == win for i in range(len(seq) - k + 1) if seq[i] == win[0])
    tdir = os.path.join(MC.botdir(trunk), "src")
    out = []
    for fn in sorted(os.listdir(src)):
        if not fn.endswith((".cc", ".cpp", ".h", ".hpp")):
            continue
        T, B = rd(os.path.join(src, fn)), rd(os.path.join(tdir, fn))
        if T is None or B is None or T == B:
            continue
        vers = []
        for spec in donors:
            dn, _, bn = spec.partition(":")
            dd = MC.botdir(dn)
            bd = MC.botdir(bn) if bn else MC.infer_base(dd, MC.botdir(trunk))
            dv, bv = rd(os.path.join(dd, "src", fn)), rd(os.path.join(bd, "src", fn))
            if dv is not None and dv != bv:
                vers.append(dv)
        if len(vers) < 2:
            continue  # one donor (or none) changed it: a plain take or 3-way of one change
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, B, T, autojunk=False).get_opcodes():
            if op not in ("insert", "replace"):
                continue
            win = T[max(0, j1 - 1):min(len(T), j2 + 1)]
            if all(DECL_ONLY.match(x) for x in T[j1:j2] if x):
                continue  # comments, #defines and flag-table declarations stacked by two donors (common_flags.h appends): no code splice
            if not any(has(v, win) for v in vers) and not has(B, win):
                out.append(f"{fn}:{j1 + 1} {' | '.join(x for x in T[j1:j2] if x)[:90]}")
    return out


def main():
    sys.stdout.reconfigure(line_buffering=True)  # 2 Nov: buffered output left 0-byte logs that read as hangs under timeout or nohup
    ap = argparse.ArgumentParser()
    ap.add_argument("args", nargs="+")
    ap.add_argument("--set", default="")
    ap.add_argument("--live")
    ap.add_argument("--maps", type=int, default=10)
    ap.add_argument("--no-identity", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--union", action="append", default=[])
    ap.add_argument("--union-auto", action="store_true")
    ap.add_argument("--subst", action="append", default=[])
    a = ap.parse_args()
    if len(a.args) < 3:
        sys.exit(__doc__)
    *donors, trunk, new = a.args
    live = a.live or live_bot()
    if a.dry:
        new = f"tmdry_{os.getpid()}"
    t = time.time()
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/newbot.sh"), trunk, new], capture_output=True, text=True)
    if r.returncode:
        die(f"newbot.sh {trunk} {new}: {(r.stdout + r.stderr).strip()[-300:]}")
    nd = os.path.realpath(os.path.join(REPO, "bots", new))
    src = os.path.join(nd, "src")
    rec, mc_donors = [], []
    for spec in donors:
        dn, _, bn = spec.partition(":")
        dd = MC.botdir(dn)
        bd = MC.botdir(bn) if bn else MC.infer_base(dd, MC.botdir(trunk))
        files = sorted(set(os.listdir(os.path.join(dd, "src"))) | set(os.listdir(os.path.join(bd, "src"))))
        took, merged, conf = [], [], []
        stray = [f for f in files if f.endswith((".orig", ".rej"))]  # 6 Nov (Builder: 3 refused merges): a patch run's leftovers, never source
        if stray:
            print(f"trunkmerge: {dn}: skipped patch leftovers {' '.join(stray)} (not copied into the trunk)", flush=True)
            files = [f for f in files if f not in stray]
        for f in files:
            pd, pb, pt = (os.path.join(x, "src", f) for x in (dd, bd, nd))
            if not os.path.isfile(pd):
                # 10 Nov (b1791 fbb8: the donor deletes the dead contest module; the trunk kept contest_play.cc, which then compiled against
                # the stripped support::me_active): a file the donor's BASE has and the donor dropped is a deletion. It is applied when the
                # trunk's copy is still the base's; a trunk that changed it since is a conflict, not a silent delete.
                if os.path.isfile(pb) and os.path.isfile(pt):
                    if open(pt, "rb").read() == open(pb, "rb").read():
                        os.remove(pt)
                        took.append(f"{f} (deleted)")
                    else:
                        conf.append(f"{f} (deleted in the donor, changed in the trunk)")
                continue
            if os.path.isfile(pb) and open(pd, "rb").read() == open(pb, "rb").read():
                continue  # the donor did not change it
            if (os.path.isfile(pb) and os.path.isfile(pt) and open(pt, "rb").read() == open(pb, "rb").read()) or \
                    (not os.path.isfile(pb) and not os.path.isfile(pt)):
                shutil.copyfile(pd, pt)
                took.append(f"{f} {sha(pd)}")
                continue
            if not os.path.isfile(pb):
                conf.append(f"{f} (new in the donor but the trunk has its own)")
                continue
            m = subprocess.run(["git", "merge-file", "-p", pt, pb, pd], capture_output=True)
            if m.returncode and (f in a.union or a.union_auto):
                if additive_conflicts(pt, pb, pd):
                    m = subprocess.run(["git", "merge-file", "-p", "--union", pt, pb, pd], capture_output=True)
                    merged.append(f"{f} {sha(pd)} (--union: both sides only add)")
                    open(pt, "wb").write(m.stdout)
                    continue
                print(f"--union {f}: a conflict block changes existing lines: not unioned")
            if m.returncode:  # 6 Nov (owner: "not git diffs if they are in different sections"): the structured merge (tools/lab/smerge.py)
                import smerge
                sm, note = smerge.merge_bytes(open(pt, "rb").read(), open(pb, "rb").read(), open(pd, "rb").read(), f)
                if sm is not None:
                    open(pt, "wb").write(sm)
                    merged.append(f"{f} {sha(pd)} (smerge: {note})")
                    print(f"smerge {f}: {note}")
                    continue
                print(f"smerge {f}: still a conflict: {note}")
            open(pt, "wb").write(m.stdout)
            (conf if m.returncode else merged).append(f"{f} {sha(pd)}" + (f" ({m.returncode} conflicts)" if m.returncode else ""))
        rec.append(f"{MC.name_of(dd)} (base {MC.name_of(bd)}): took {', '.join(took) or '-'}; merged {', '.join(merged) or '-'}")
        mc_donors += ["--donor", f"{MC.name_of(dd)}:{MC.name_of(bd)}"]
        print(f"donor {MC.name_of(dd)} base {MC.name_of(bd)}: took {len(took)}, 3-way {len(merged)}, conflicts {len(conf)}")
        if conf:
            die(f"conflicts in {', '.join(conf)}: fix them in {src} (markers in the files), then rerun the remaining steps "
                f"(mergecheck / build / identity) by hand", 2)
    # 10 Nov (Rule Checker: v687 fxb8z shipped an unconditional `return false;` at econ_late_picks.cc:218, spliced from FB35's two donors,
    # nova_b1807_rsg braced and nova_b1807_ip3 unbraced, killing every gate-siege start): in a file two or more donors changed, every
    # changed block of the merged trunk (with one line of context each side) must appear verbatim in one donor's file or in the trunk it
    # started from. A block found in none is a merge splice: the merge stops. TRUNKMERGE_PROVENANCE=0 skips it (hand-checked merges).
    if os.environ.get("TRUNKMERGE_PROVENANCE", "1") != "0" and len(donors) > 1:
        bad = provenance(donors, trunk, src)
        if bad:
            die("merge provenance: blocks that come from no single donor (a splice of two donors' edits?): " + "; ".join(bad[:4])
                + " -- merge by hand, or TRUNKMERGE_PROVENANCE=0 if checked", 2)
    for sp in a.subst:
        fn, old, newtxt = sp.split("|||")
        p = os.path.join(src, fn)
        s = open(p, encoding="utf-8", errors="surrogateescape").read()
        if s.count(old) != 1:
            die(f"--subst {fn}: found {s.count(old)} times: {old[:80]!r}", 2)
        open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(old, newtxt))
        rec.append(f"subst {fn}: {old.strip()[:60]} -> {newtxt.strip()[:90]}")
        mc_donors += ["--allow-missing", re.escape(old.strip())]  # this one donor line was replaced on purpose
        print(f"--subst {fn}: applied")
    if os.path.isfile(os.path.join(src, "nova_all.cpp")):  # 3 Nov (b1066): a unity trunk: a donor's new .cpp or new #define needs nova_all.cpp regenerated
        r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/mkunity.sh"), src], capture_output=True, text=True)
        if r.returncode:
            die(f"mkunity.sh {src}: {(r.stdout + r.stderr).strip()[-300:]}")
        rec.append("mkunity.sh: unity build regenerated")
        print("unity build: mkunity.sh regenerated nova_all.cpp")
    step("merge", t)
    t = time.time()
    sets = [x.split("=", 1) for x in a.set.split()]
    for k, v in sets:
        hits = []
        for f in os.listdir(src):
            p = os.path.join(src, f)
            if not os.path.isfile(p):
                continue
            s = open(p, encoding="utf-8", errors="replace").read()
            pat = re.compile(rf"^([ \t]*#[ \t]*define[ \t]+{re.escape(k)}[ \t]+)(-?\d+)(.*)$", re.M)
            if pat.search(s):
                hits.append((p, s, pat))
        if len(hits) != 1 or len(hits[0][2].findall(hits[0][1])) != 1:
            die(f"--set {k}: `#define {k} <int>` must occur exactly once (found {len(hits)} files)")
        p, s, pat = hits[0]
        open(p, "w").write(pat.sub(lambda m: m.group(1) + v + m.group(3), s, count=1))
    # 6 Nov (owner: "how can we parallelise the train"; pass 459 s: set 63, mergecheck 132, build 91, identity 173, all serial): the source is
    # final here, so flip.py check and the static mergecheck run alongside the pilot build and the identity games; any failure still stops the run
    flip_p = subprocess.Popen([sys.executable, "-I", os.path.join(REPO, "tools/lab/flip.py"), "check", src, a.set], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) if sets else None
    # 7 Nov (Builder: spec to ship in 20 min): the two flip.py list runs (12-35 s each under load) sat on the critical path, and
    # their output only goes to the printout and the registry line: they now run beside the build and identity, joined at the end
    import concurrent.futures as _cf
    _tx = _cf.ThreadPoolExecutor(2)
    _f_old = _tx.submit(tables, os.path.join(MC.botdir(trunk), "src"))
    _f_new = _tx.submit(tables, src)

    def new_tables():
        old = _f_old.result()
        nt = {k: v for k, v in _f_new.result().items() if k not in old}
        print("new tables (check every value is the trunk's live value):")
        for v in nt.values():
            print("  " + v)
        return nt
    step("set", t)
    def flip_done():
        if flip_p is not None:
            o = flip_p.communicate()[0]
            if flip_p.returncode:
                die(f"flip.py check: {(o or '').strip()[-400:]}")
    if a.dry:
        flip_done()
        print(f"--dry: merged into bots/{new} ({src}); not built, not checked. Remove it when done: rm bots/{new} and {nd}")
        return 0
    t_par = time.time()
    mc_p = subprocess.Popen([sys.executable, "-I", os.path.join(REPO, "tools/lab/mergecheck.py"), new, live, "--quiet", "--no-build",
                             "--no-play"] + mc_donors, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    mc_out = []
    threading.Thread(target=lambda: mc_out.append(mc_p.communicate()[0]), daemon=True).start()
    t = time.time()
    # 2 Nov: on a pilot, and the result is flip.sh's trunk cache, so the trunk compiles once, not twice here (load 56). A local build shows any compile error.
    sh = subprocess.run("find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12", shell=True, cwd=os.path.join(REPO, "bots", new), capture_output=True, text=True).stdout.strip()
    tw = f"/data/zw4424/trunkproj/wasm/{new}-{sh}.wasm"
    if subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/pilotbuild.py"), new, tw], capture_output=True).returncode:
        r = subprocess.run(["nice", "-n", "10", CLI, "build", os.path.join(REPO, "bots", new), "--release"], cwd=PROJ, capture_output=True,
                           text=True, env=dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL="3"))
        if r.returncode:  # 7 Nov (Builder: armq.log keeps 600 chars, the first compile error was cut): the full log on disk, the errors first
            out = r.stdout + r.stderr
            lg = f"/data/zw4424/st/trunkmerge/{new}_build.log"
            os.makedirs(os.path.dirname(lg), exist_ok=True)
            open(lg, "w").write(out)
            errs = [ln.strip() for ln in out.splitlines() if " error:" in ln or ln.lstrip().startswith("error:")]
            die(f"build failed ({len(errs)} error lines; full log {lg}): " + (" | ".join(errs[:4])[:900] if errs else out[-600:]))
    step("build", t)
    ident = "skipped"
    if not a.no_identity:
        t = time.time()
        idd = f"/data/zw4424/st/trunkmerge/{new}_id"
        os.makedirs(idd + "/out", exist_ok=True)
        R, M = os.path.join(REPO, "bots"), os.path.join(PROJ, "maps")
        maps = [x for x in MAPS if os.path.exists(os.path.join(M, x + ".map26a"))][:a.maps]
        cx = id_cxe(idd, M, maps, live, new, tw) if os.environ.get("TRUNKMERGE_ID_ENGINE", "cxe") == "cxe" else None
        if cx:  # 4 Nov: on cxe (game-identical to the CLI), seconds instead of a 1-2 min Condor batch
            c = f"identity base vs fix: {cx[0]}/{cx[1]} (cxe, fuel {ID_FUEL})"
        else:
            lines, store = id_rows(idd, R, M, maps, live, new)
            print(f"identity: {len(maps) * 4 - len(lines)} of {len(maps) * 4} games from the cache, playing {len(lines)}", flush=True)
            if lines:
                open(idd + "/man.txt", "w").write("\n".join(lines) + "\n")
                subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/cqbatch.py"), "man.txt", "--release",
                                "--fuel-quantum", ID_FUEL], cwd=idd, capture_output=True, text=True, env=dict(os.environ, CQB_PRIO=ID_PRIO))
                id_store(idd, store)
            c = subprocess.run([sys.executable, "-I", CMP, idd, "id", "base", "fix"], capture_output=True, text=True).stdout
        mm = re.search(r"identity base vs fix: (\d+)/(\d+)", c)
        step("identity", t)
        if not mm or mm.group(1) != mm.group(2) or mm.group(2) == "0":
            die(f"IDENTITY FAIL vs {live}: {c.strip()[-400:]} (dir {idd}): a flag is not at its live value, or flag-0 work changes play")
        ident = f"{mm.group(1)}/{mm.group(2)} vs {live} ({idd})"
        print(f"identity {ident}")
    flip_done()
    mc_p.wait()
    while not mc_out:
        time.sleep(0.1)
    mline = (re.findall(r"^== MERGECHECK .*$", mc_out[0] or "", re.M) or ["(no verdict line)"])[-1]
    print(mline)
    step("mergecheck (alongside build + identity, from their start)", t_par)
    if mc_p.returncode:
        die(f"mergecheck FAIL: {(mc_out[0] or '')[-1500:]}")
    h = subprocess.run(f"cd {nd} && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12", shell=True,
                       capture_output=True, text=True).stdout.strip()
    newt = new_tables()
    line = (f"- {new} (trunkmerge {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}; source {h}): {trunk} + "
            + "; ".join(rec) + f". --set {a.set or '-'}. New tables: " + ("; ".join(newt.values()) or "none")
            + f". {mline.strip('= ')}; identity {ident}.\n")
    with open(REG, "a") as f:
        f.write(line)
    print("timings: " + ", ".join(f"{n} {s:.0f}s" for n, s in TIMES) + f"; total {time.time() - T0:.0f}s")
    print(f"OK: bots/{new} = {trunk} + {len(donors)} donor(s); registry line written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
