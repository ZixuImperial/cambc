"""lineprof: line-level fuel profile of a bot (Tool Builder, 10 Nov; Rule Checker x138: split the inlined roots turn<0> and econ::observe).
fuelprof attributes fuel per wasm function, so everything the -O3 single-TU build inlines lands in its root. This plays BOT's "lineprof"
build (tools/cxe/w2c_lineprof.py: one counter per fuel-flush block, fuel charged to each instruction's code offset) v OPP on N maps x 2
seats (Condor pilots via cxefarm, local fallback) and maps every offset to its source line and inline chain through a copy of the CLI's
release compile with -gline-tables-only (same code: checked every run by stripping the debug sections and comparing the whole module
with the CLI's bot.wasm; the run stops if they differ) and llvm-symbolizer --inlining.
usage: python3 -I tools/cxe/lineprof.py BOT [--opp BOT2] [--maps 8] [--seed 1] [--root FUNC ...] [--top 25] [--mapdir DIR] [--local]
                                      [--check-replays K]
  --root: substring of a demangled function name (repeatable); default turn<0>, econ::observe, play_turn_body<0>, combat::assess,
          target_turn<0>. --check-replays K (default 2): the first K games are also played with the normal build and the replays compared
          byte for byte (the profile build must play identically).
Run it as its own unit (the -g compile is ~1 min of one clang at a few GB):
  systemd-run --user --unit nova-lineprof-X -p MemoryMax=8G --working-directory=/homes/zw4424/cambc nice -n 10 python3 -I tools/cxe/lineprof.py BOT ...
Writes /data/zw4424/st/cxe/lineprof/<bot>_<stamp>-<pid>/: report.txt, lines.tsv (root, innermost file:line, fuel), chains.tsv (root, full
inline chain, fuel), identity.txt."""
import collections
import difflib
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402
import wasmparse  # noqa: E402
from w2c_lineprof import op_offsets, code_start  # noqa: E402  (importing it patches w2c in this process only; nothing is translated here)

MAPDIR = "/data/zw4424/ablproj_4.0.0/maps"
SDKBIN = "/data/zw4424/cambc-cache/wasi-sdk-33/bin"
DEFAULT_ROOTS = ["::turn<0>()", "econ::observe()", "::play_turn_body<0>()", "combat::assess()", "::target_turn<0>()",
                 "::group_bounds(", "::group_bounds_loop("]  # 12 Nov (RC X519): group_bounds is on 55-82% of cut stacks
OUTROOT = os.path.join(cxebuild.ROOT, "lineprof")


def demangle(names):
    names = sorted(set(names))
    r = subprocess.run([os.path.join(SDKBIN, "llvm-cxxfilt")], input="\n".join(names), capture_output=True, text=True)
    out = r.stdout.splitlines() if r.returncode == 0 else names
    return dict(zip(names, out))


def ninja_vars(text, stanza):
    i = text.index(stanza)
    v = {}
    for ln in text[i:].splitlines()[1:]:
        if not ln.startswith("  "):
            break
        k, _, x = ln.strip().partition(" = ")
        v[k] = x
    return v


def debug_wasm(bot, log):
    """-> (g.wasm with line tables, the CLI's bot.wasm). The CLI's own compile and link commands with -gline-tables-only added; the
    stripped modules must be byte-identical (else exit)."""
    cli = cxebuild.wasm_of(bot, release=False)
    bd = os.path.dirname(cli)
    key = hashlib.sha256(open(cli, "rb").read()).hexdigest()[:16]
    gd = os.path.join(OUTROOT, "gwasm", f"{os.path.basename(os.path.dirname(os.path.dirname(bd)))}-{key}")
    gw = os.path.join(gd, "g.wasm")
    if not os.path.exists(gw):
        os.makedirs(gd, exist_ok=True)
        cc = json.load(open(os.path.join(bd, "compile_commands.json")))[0]
        args = shlex.split(cc["command"])
        o = args.index("-o")
        obj = os.path.join(gd, f"g.{os.getpid()}.obj")
        args = args[:o] + ["-gline-tables-only", "-o", obj] + args[o + 2:]
        nin = open(os.path.join(bd, "build.ninja")).read()
        lv = ninja_vars(nin, "build bot.wasm:")
        rule = open(os.path.join(bd, "CMakeFiles", "rules.ninja")).read()
        rv = ninja_vars(rule, "rule CXX_EXECUTABLE_LINKER__bot_Release")
        cmd = rv["command"].split("&&")[1].strip()
        for k in ("FLAGS", "LINK_FLAGS", "LINK_PATH", "LINK_LIBRARIES"):
            cmd = cmd.replace("$" + k, lv.get(k, ""))
        tdir = os.path.join(gd, f"tmp{os.getpid()}")  # the output is named bot.wasm like the CLI's: the name section records it
        os.makedirs(tdir, exist_ok=True)
        tmpw = os.path.join(tdir, "bot.wasm")
        cmd = cmd.replace("$in", shlex.quote(obj)).replace("$TARGET_FILE", shlex.quote(tmpw))
        log(f"lineprof: -g compile of {bot} ({cc['file']})")
        subprocess.run(["nice", "-n", "10"] + args, cwd=cc["directory"], check=True)
        subprocess.run(["nice", "-n", "10", "sh", "-c", cmd], cwd=bd, check=True)
        os.remove(obj)
        os.replace(tmpw, gw)
        os.rmdir(tdir)
    return gw, cli


def strip_cmp(gw, cli, out):
    oc = os.path.join(SDKBIN, "llvm-objcopy")
    a, b = os.path.join(out, "cli.strip.wasm"), os.path.join(out, "g.strip.wasm")
    subprocess.run([oc, "--strip-debug", cli, a], check=True)
    subprocess.run([oc, "--strip-debug", gw, b], check=True)
    da, db = open(a, "rb").read(), open(b, "rb").read()
    ok = da == db
    ma, mb = wasmparse.Module(cli), wasmparse.Module(gw)
    code_same = len(ma.bodies) == len(mb.bodies) and all(x[0][x[1]:x[2]] == y[0][y[1]:y[2]] for x, y in zip(ma.bodies, mb.bodies))
    msg = (f"strip-debug(CLI bot.wasm) {len(da)} B sha {hashlib.sha256(da).hexdigest()[:16]}; strip-debug(-g build) {len(db)} B sha "
           f"{hashlib.sha256(db).hexdigest()[:16]}: {'IDENTICAL' if ok else 'DIFFER'}; function bodies {'identical' if code_same else 'DIFFER'} "
           f"({len(ma.bodies)} functions)")
    os.remove(a)
    os.remove(b)
    return ok and code_same, msg


def offset_map(inj, cli):
    """code offset in the injected (running) wasm -> code offset in the CLI's bot.wasm (the -g build's offsets). The CLI's injection
    changes a few function bodies by a few bytes: those are aligned instruction by instruction."""
    bi, bc = open(inj, "rb").read(), open(cli, "rb").read()
    mi, mc = wasmparse.Module(inj), wasmparse.Module(cli)
    ci, cc = code_start(bi), code_start(bc)
    fmap, changed = [], []
    for k, (x, y) in enumerate(zip(mi.bodies, mc.bodies)):
        if x[0][x[1]:x[2]] == y[0][y[1]:y[2]]:
            fmap.append((y[1] - cc) - (x[1] - ci))
            continue
        oi = [o - ci for o in op_offsets(*x)]
        oc = [o - cc for o in op_offsets(*y)]
        si, sc = [repr(x) for x in mi.body(k)[1]], [repr(x) for x in mc.body(k)[1]]
        m = {}
        for a, b, n in difflib.SequenceMatcher(None, si, sc, autojunk=False).get_matching_blocks():
            for j in range(n):
                m[oi[a + j]] = oc[b + j]
        last = oc[0] if oc else 0
        for o in oi:
            if o in m:
                last = m[o]
            else:
                m[o] = last
        fmap.append(m)
        changed.append(k + mi.nimp)
    return fmap, changed, mi.nimp


def symbolize(gw, addrs):
    """-> {addr: [(function, file, line), ...] innermost first}"""
    res = {}
    addrs = sorted(addrs)
    p = subprocess.run([os.path.join(SDKBIN, "llvm-symbolizer"), "--obj=" + gw, "--inlining", "--output-style=JSON", "--demangle"],
                       input="\n".join(f"0x{a:x}" for a in addrs), capture_output=True, text=True, check=True)
    for ln in p.stdout.splitlines():
        if not ln.strip():
            continue
        j = json.loads(ln)
        a = int(j["Address"], 16)
        res[a] = [(s.get("FunctionName", "?"), s.get("FileName", ""), s.get("Line", 0)) for s in j.get("Symbol", [])]
    return res


def strip_args(n):
    """'void a::(anonymous namespace)::f<0>(int) const' -> 'a::f<0>': the parameter list (the last balanced (...)) and return type dropped."""
    n = n.replace("(anonymous namespace)::", "")
    if n.endswith(")") or n.endswith(") const"):
        d, i = 0, len(n.rstrip(" const")) - 1
        while i >= 0:
            d += {")": 1, "(": -1}.get(n[i], 0)
            if d == 0:
                break
            i -= 1
        n = n[:max(i, 0)]
    return n.split(" ")[-1] if " " in n and "<" not in n.split(" ")[0] else n


def short_file(f):
    return f.split("/src/", 1)[1] if "/src/" in f else os.path.basename(f) or "?"


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("--"):
        sys.exit(__doc__)
    bot = a[0]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    opp = opt("--opp", bot)
    n = int(opt("--maps", 8))
    top = int(opt("--top", 25))
    nchk = int(opt("--check-replays", 2))
    roots = [a[i + 1] for i, x in enumerate(a) if x == "--root"] or DEFAULT_ROOTS
    rng = random.Random(int(opt("--seed", 1)))
    out = os.path.join(OUTROOT, f"{os.path.basename(os.path.normpath(bot))}_{time.strftime('%m%d%H%M%S')}-{os.getpid()}")
    os.makedirs(out, exist_ok=True)
    say = lambda x: print(x, flush=True)
    exe = cxebuild.build_host()
    so_p = cxebuild.build_bot(bot, "lineprof")
    sites_p = so_p[:-3] + ".sites.tsv"
    if not os.path.exists(sites_p):
        sys.exit(f"lineprof: {sites_p} missing (remove {so_p} and rerun)")
    so_o = cxebuild.build_bot(opp)
    so_n = cxebuild.build_bot(bot) if nchk else None
    gw, cli = debug_wasm(bot, say)
    ok, idmsg = strip_cmp(gw, cli, out)
    hdr = open(sites_p).readline().split()
    inj = hdr[2]
    idlines = [f"bot {bot}; running wasm {inj}", f"CLI bot.wasm {cli}", f"-g build {gw}", idmsg]
    if not os.path.exists(inj) or hashlib.sha256(open(inj, "rb").read()).hexdigest() != hdr[3]:
        sys.exit(f"lineprof: the translated wasm {inj} changed since the lineprof build")
    if not ok:
        open(f"{out}/identity.txt", "w").write("\n".join(idlines) + "\nSTOP: the -g build's code differs; a line profile of it would be wrong\n")
        sys.exit("lineprof: " + idmsg)
    sites = []
    for ln in open(sites_p):
        if ln.startswith("#"):
            continue
        s, fi, kind, offs = ln.rstrip("\n").split("\t")
        sites.append((int(fi), kind, [int(x) for x in offs.split(",")]))
    mapdir = opt("--mapdir", MAPDIR)
    allm = sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a"))
    maps = allm if "--mapdir" in a else rng.sample(allm, n)
    games = []
    for i, m in enumerate(maps):
        games.append((2 * i, so_p, so_o, m, 0))
        games.append((2 * i + 1, so_o, so_p, m, 1))
    chk = [(100000 + k, so_n if x == so_p else x, so_n if y == so_p else y, m, t) for k, x, y, m, t in games[:nchk]]
    env_of = lambda k: {"CXE_LINEPROF": "@D@/lp.tsv", "CXE_FUELPROF": "@D@/fp.tsv"} if k < 100000 else {}
    files_of = lambda k: ({"lp.tsv": f"{out}/lp_{k}.tsv", "fp.tsv": f"{out}/fp_{k}.tsv"} if k < 100000 else {}) | (
        {"g.repl26a": f"{out}/g{k}.repl26a"} if k % 100000 < nchk else {})
    allg = games + chk
    pend = list(allg)
    if "--local" not in a:
        import cxefarm
        fg = [dict(id=k, a=x, b=y, map=os.path.join(mapdir, m), env=env_of(k), files=files_of(k)) for k, x, y, m, t in allg]
        if cxefarm.run(fg, say=say) is not None:
            pend = [g for g in allg if not all(os.path.exists(p) for p in files_of(g[0]).values())]
    procs = []
    while pend or procs:
        while pend and len(procs) < 6:
            k, x, y, m, t = g = pend.pop(0)
            d = os.path.join(out, f"d{k}")
            os.makedirs(d, exist_ok=True)
            env = dict(os.environ, **{e: v.replace("@D@", d) for e, v in env_of(k).items()})
            procs.append((g, d, subprocess.Popen(["nice", "-n", "10", exe, x, y, os.path.join(mapdir, m), f"{d}/g"], env=env,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        for item in list(procs):
            if item[2].poll() is not None:
                procs.remove(item)
                g, d = item[0], item[1]
                for nm, dst in files_of(g[0]).items():
                    if os.path.exists(f"{d}/{nm}"):
                        shutil.move(f"{d}/{nm}", dst)
                shutil.rmtree(d, ignore_errors=True)
        time.sleep(0.05)
    # replay identity
    for k, x, y, m, t in games[:nchk]:
        p1, p2 = f"{out}/g{k}.repl26a", f"{out}/g{100000 + k}.repl26a"
        same = os.path.exists(p1) and os.path.exists(p2) and open(p1, "rb").read() == open(p2, "rb").read()
        idlines.append(f"replay {m} seat {'AB'[t]}: lineprof build v normal build {'IDENTICAL' if same else 'DIFFER'}"
                       f" ({os.path.getsize(p1) if os.path.exists(p1) else 0} B)")
    for k in range(nchk):
        for p in (f"{out}/g{k}.repl26a", f"{out}/g{100000 + k}.repl26a"):
            if os.path.exists(p):
                os.remove(p)
    open(f"{out}/identity.txt", "w").write("\n".join(idlines) + "\n")
    # counts -> fuel per (function, injected offset)
    fuel_at = collections.Counter()
    fprof = collections.Counter()
    ng, neg = 0, 0
    calls_at = collections.Counter()
    for k, x, y, m, team in games:
        p, q = f"{out}/lp_{k}.tsv", f"{out}/fp_{k}.tsv"
        if not os.path.exists(p):
            continue
        ng += 1
        for ln in open(p):
            s, c = ln.split()
            c = int(c)
            fi, kind, offs = sites[int(s)]
            if kind == "b":
                for o in offs:
                    fuel_at[(fi, o)] += c
            elif kind == "e":  # 11 Nov (RC X418): the function-entry charge = calls (1 fuel each, at the first instruction)
                fuel_at[(fi, offs[0])] += c
                calls_at[fi] += c
            else:
                if c >= 1 << 63:
                    c, neg = 0, neg + 1
                fuel_at[(fi, offs[0])] += c
        if os.path.exists(q):
            for ln in open(q):
                t, fi, f, cuts = ln.split()
                if int(t) == team:
                    v = int(f)
                    fprof[int(fi)] += v - (1 << 64) if v >= 1 << 63 else v
            os.remove(q)
        os.remove(p)
    if not ng:
        sys.exit("lineprof: no game returned counters")
    fmap, changed, nimp = offset_map(inj, cli)
    names = wasmparse.Module(cli).names
    dm = demangle([names.get(fi, f"f{fi}") for fi, _ in fuel_at])
    fname = lambda fi: dm.get(names.get(fi, f"f{fi}"), f"f{fi}")
    cfuel = collections.Counter()
    for (fi, o), f in fuel_at.items():
        mp = fmap[fi - nimp]
        cfuel[(fi, mp[o] if isinstance(mp, dict) else o + mp)] += f
    # 10 Nov (Rule Checker X148/X153, verified): llvm-symbolizer's DWARF lines and inline frames for wasm take CODE-SECTION-RELATIVE
    # addresses; the stored offsets are code-relative, so they go in as they are. (The first build added the code start, 0x157e: every
    # line and inline label landed 0x157e bytes late. Function containment checks missed it because big functions such as turn<0> hold
    # both addresses and the outermost name comes from the symbol table.) Check: a `call` to a host import resolves to its sdk_ wrapper.
    sym = symbolize(gw, {o for _, o in cfuel})
    total = sum(cfuel.values())
    # cross-check with the per-function counters (fuelprof's)
    perf = collections.Counter()
    for (fi, o), f in cfuel.items():
        perf[fi] += f
    bad = [fi for fi in set(perf) | set(fprof) if perf[fi] != max(fprof[fi], 0) and fprof[fi] >= 0]
    lines = [f"lineprof {bot} v {opp}: {ng} games ({len(maps)} maps x 2 seats); bot fuel {total:,} = {total / ng:,.0f} per game",
             *idlines,
             f"check: per-function sums of the line counters v fuelprof's counters: {'equal' if not bad else f'{len(bad)} functions differ'}"
             + (f"; {neg} negative host charges (draft slice refill) counted as 0" if neg else ""),
             f"functions changed by the CLI's injection (aligned by instruction): {len(changed)}", ""]
    rows_line, rows_chain = [], []
    for root in roots:
        fis = sorted({fi for fi, _ in cfuel if root in fname(fi)})
        if not fis:
            lines += [f"== root '{root}': no function matches", ""]
            continue
        byline, bychain, byfunc, bycall, byself = (collections.Counter() for _ in range(5))
        chain_of_line = collections.defaultdict(collections.Counter)
        rt, nosym = 0, 0
        for (fi, o), f in cfuel.items():
            if fi not in fis:
                continue
            rt += f
            fr = sym.get(o) or []
            if not fr or not fr[0][1]:
                nosym += f
                fr = [("?", "?", 0)]
            inner = f"{short_file(fr[0][1])}:{fr[0][2]}"
            ch = " > ".join(f"{strip_args(fn)}@{short_file(fl)}:{ln}" for fn, fl, ln in reversed(fr))
            byline[inner] += f
            bychain[ch] += f
            chain_of_line[inner][ch] += f
            byself[strip_args(fr[0][0])] += f
            bycall[f"{short_file(fr[-1][1])}:{fr[-1][2]}" + (f" ({strip_args(fr[-2][0])})" if len(fr) > 1 else " (own)")] += f
            for fn in {strip_args(x[0]) for x in fr[:-1]}:
                byfunc[fn] += f
        lines += [f"== root '{root}': {len(fis)} function(s) {', '.join(fname(fi)[:60] for fi in fis[:3])}; {rt / ng:,.0f} fuel/game "
                  f"({100 * rt / total:.2f}%); no line info: {nosym / ng:,.0f}/g", "",
                  f"top {top} source lines (innermost frame) | fuel/game | share of root | main inline chain (outer > inner; APPROXIMATE: -O3 DWARF scope names can be wrong, rank by the file:line column) [share of line]"]
        for ln_, f in byline.most_common(top):
            ch, cf = chain_of_line[ln_].most_common(1)[0]
            lines.append(f"  {ln_:34s} {f / ng:11,.0f} {100 * f / rt:5.1f}%  {ch[:230]} [{100 * cf / f:.0f}%]")
        lines += ["", f"top {top} call sites in the root's own body (the outermost frame's line; the function inlined there)"]
        for k_, f in bycall.most_common(top):
            lines.append(f"  {f / ng:11,.0f} {100 * f / rt:5.1f}%  {k_[:160]}")
        lines += ["", f"top {top} inlined functions, inclusive (every frame below the root)"]
        for k_, f in byfunc.most_common(top):
            lines.append(f"  {f / ng:11,.0f} {100 * f / rt:5.1f}%  {k_[:160]}")
        lines += ["", f"top {top} innermost functions (self)"]
        for k_, f in byself.most_common(top):
            lines.append(f"  {f / ng:11,.0f} {100 * f / rt:5.1f}%  {k_[:160]}")
        lines.append("")
        rows_line += [(root, k_, f) for k_, f in byline.most_common()]
        rows_chain += [(root, k_, f) for k_, f in bychain.most_common()]
    rep = "\n".join(lines) + "\n"
    open(f"{out}/report.txt", "w").write(rep)
    with open(f"{out}/lines.tsv", "w") as f:
        f.write("root\tline\tfuel_per_game\tfuel\n")
        for r, k_, v in rows_line:
            f.write(f"{r}\t{k_}\t{v / ng:.0f}\t{v}\n")
    with open(f"{out}/chains.tsv", "w") as f:
        f.write("root\tchain\tfuel_per_game\tfuel\n")
        for r, k_, v in rows_chain:
            f.write(f"{r}\t{k_}\t{v / ng:.0f}\t{v}\n")
    with open(f"{out}/calls.tsv", "w") as f:  # 11 Nov (RC X418): calls per function (entry charges); a first instruction's fuel = calls + its runs
        f.write("function\tcalls\tcalls_per_game\n")
        for fi, v in calls_at.most_common():
            f.write(f"{fname(fi)[:120]}\t{v}\t{v / ng:.1f}\n")
    with open(f"{out}/offsets.tsv", "w") as f:  # every charged offset of every function, with its chain
        f.write("# a function's first instruction also carries its entry charge (1 per call, calls.tsv): executions there = fuel - calls\n")
        f.write("function\tcli_offset\tfuel\tchain\n")
        for (fi, o), v in cfuel.most_common():
            fr = sym.get(o) or []
            f.write(f"{fname(fi)[:120]}\t0x{o:x}\t{v}\t{' > '.join(f'{x[0][:80]}@{short_file(x[1])}:{x[2]}' for x in reversed(fr))}\n")
    print(rep + f"(tables: {out}/lines.tsv, chains.tsv, offsets.tsv)")


if __name__ == "__main__":
    main()
