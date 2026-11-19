"""fuelprof: where does a bot's fuel go? Plays BOT (fuel-profiled build) v OPP on N maps in both seats on cxe and
attributes every unit of the bot's fuel to the C++ function that spent it: its own WebAssembly instructions, the bytes
of its memory.copy/memory.fill, and the host charges of the imports it calls (bitboards, distance fields, lists...).
It also counts, per function, how often the bot ran out of fuel there (the turn was cut while that function ran).
Fuel is exactly the CLI's (cxe is verified game-identical), so the shares are the real costs.
Report: top functions (self fuel, share, per game), the same rolled up by C++ scope (namespace / class: the "areas"),
and the out-of-fuel sites. Names come from the bot's WebAssembly name section, demangled.
usage: python3 -I tools/cxe/fuelprof.py BOT [--opp BOT2] [--maps 12] [--seed 1] [--top 40] [--jobs 6] [--mapdir DIR] [--local] [--cutphase]
  --mapdir: profile on every .map26a in DIR (e.g. the maps where shipchecks see fuel cuts) instead of --maps random pool maps
  --cutphase (10 Nov, Rule Checker X160 T1): the "cutphase" build (tools/cxe/w2c_cutphase.py): the same fuel tables, plus each fuel cut
    tagged with its turn phase (setup / perceive / dead / stunned / observe / assess / stages / bail / tail / background / outside) and
    the call stack the first time each turn crosses 90% of the 100k budget (top stacks by count and by fuel past the mark). Every game
    is also played with the normal build and the replays' hashes are compared (identity proof in the report). Opp should differ from BOT.
Writes /data/USER/st/cxe/fuelprof/<bot>_<stamp>/report.txt (and functions.tsv with every function)."""
import collections
import hashlib
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402
import wasmparse  # noqa: E402

MAPDIR = "/data/USER/ablproj_4.0.0/maps"
CXXFILT = "/data/USER/cambc-cache/wasi-sdk-33/bin/llvm-cxxfilt"


def demangle(names):
    if not names:
        return {}
    r = subprocess.run([CXXFILT], input="\n".join(names), capture_output=True, text=True)
    out = r.stdout.splitlines() if r.returncode == 0 else names
    return dict(zip(names, out))


def scope(name):
    """C++ scope of a demangled function name: namespace::class (2 levels), anonymous namespaces dropped."""
    n = re.sub(r"\(anonymous namespace\)::", "", name)
    n = re.sub(r"<.*>", "", n.split("(")[0]).strip()
    n = n.split()[-1] if n.split() else n  # drop a leading return type (template functions demangle with one)
    parts = [p for p in n.split("::") if p]
    if len(parts) <= 1:
        return "(global)"
    return "::".join(parts[:min(2, len(parts) - 1)])


SOFT = 10000  # w2c_cutphase.SOFT: the 90% mark of the 100k budget
PHASES = ["setup", "perceive", "dead", "stunned", "observe", "assess", "stages", "bail", "tail", "background", "pre-body", "post-body", "draft", "outside play_turn_body"]
_STAGE0 = re.compile(r"support::wl2_heal|support::heal_any\(|econ::end_hold|econ::go_home|bank_winning_bag")
_DEAD = re.compile(r"econ::death_reset|econ::shop\(|recall_hop_prebuy|spawn_crystal_prebuy|buy_altar_lock")
_SETUP = re.compile(r"start_prestep|opening_blind_step|::setup\(")


def short(n):
    n = re.sub(r"\(anonymous namespace\)::|std::__2::|^void |nova::", "", n)
    n = re.sub(r"\((?:[^()]|\([^()]*\))*\)( const)?$", "", n)  # the argument list
    return n[:70]


def phase_maps(calls, names):
    """per turn<N> / play_turn_body<N> function: site -> callee name and the anchor sites (from the cutphase build's calls.tsv)"""
    by = collections.defaultdict(list)
    for ln in open(calls):
        f, s, c = map(int, ln.split())
        by[f].append((s, names.get(c, "")))
    mp = {}
    for f, L in by.items():
        L.sort()
        if "play_turn_body<" in names.get(f, ""):
            T = next((s for s, c in L if "::turn<" in c), None)
            A = next((s for s, c in L if T is not None and s > T and "afc_after_bail" in c), T)
            E = next((s for s, c in L if T is not None and s > T and "intel::end_turn" in c), None)
            mp[f] = ("ptb", dict(L), T, A, E)
        else:
            obs = [s for s, c in L if "econ::observe()" in c]
            F, Lo = (obs[0], obs[-1]) if obs else (None, None)
            H = next((s for s, c in L if Lo is not None and s > Lo and _STAGE0.search(c)), None)
            mp[f] = ("turn", dict(L), F, Lo, H)
    return mp


def phase_of(stack, names, mp):
    """stack: [(fi, site)] root first. A frame's site is the op index of its last call (the active call, except in the leaf, whose code
    runs after it: position site + 0.5); 0xFFFFFFFF: no call yet; 0x80000000|k: in the catch of the try at op k."""
    j = max((i for i, (f, s) in enumerate(stack) if mp.get(f, ("",))[0] == "ptb"), default=None)
    if j is None:
        nm = " ".join(names.get(f, "") for f, s in stack)
        if re.search(r"act_first_mark_overlong_turn|dom_commit|dom_loop", nm):
            return "post-body"  # play_turn after play_turn_body: the overlong mark, the dom-commit free slot
        if "strat::begin_turn" in nm:
            return "pre-body"
        return "draft" if "draft" in nm else "outside play_turn_body"
    t = j + 1 if j + 1 < len(stack) and mp.get(stack[j + 1][0], ("",))[0] == "turn" else None
    i = t if t is not None else j
    f, s = stack[i]
    leaf = i == len(stack) - 1
    catch = s != 0xFFFFFFFF and bool(s & 0x80000000)
    p = -1 if s == 0xFFFFFFFF else (s & 0x7FFFFFFF) + (0.5 if leaf and not catch else 0)
    kind, sites, x1, x2, x3 = mp[f]
    callee = sites.get(int(p), "") if p >= 0 and p == int(p) else ""
    if kind == "ptb":
        T, A, E = x1, x2, x3
        if (callee and _SETUP.search(callee)) or T is None or p < T:
            return "setup"
        # 13 Nov (RC X851: 45 of 45 'bail' cuts in the v863 hms set sat at the inlined turn_tail's start right after turn<0>() returned, 0 in the
        # real catch): the position window T < p <= A is NOT the catch. 'bail' needs the catch flag on this frame, or a real catch / unwind / fallback
        # frame anywhere on the stack (af_throw, afc_after_bail, __cxa_*, _Unwind_*, the fallback step)
        nm_ = " ".join(names.get(fx, "") for fx, sx in stack)
        if catch or "__cxa_" in callee or "_Unwind_" in callee or re.search(r"af_throw|afc_after_bail|act_first_fallback|__cxa_|_Unwind_", nm_):
            return "bail"
        if E is None or p <= E:
            return "tail"
        return "background"
    F, Lo, H = x1, x2, x3
    if F is None or p < F:
        return "dead" if callee and _DEAD.search(callee) else "perceive"
    if p < Lo:
        return "stunned"
    if p == Lo:
        return "observe"
    if H is None or p < H:
        return "assess"
    return "stages"


def cutphase_report(out, done, so_p, m_named, sha, top):
    names = m_named.names  # the name section is demangled already
    calls = so_p[:-3] + ".calls.tsv"
    mp = phase_maps(calls, names) if os.path.exists(calls) else {}
    same = [k for k, *_ in done if k in sha and k + 100000 in sha and sha[k] == sha[k + 100000]]
    diff = [k for k, *_ in done if k in sha and k + 100000 in sha and sha[k] != sha[k + 100000]]
    L = ["", f"IDENTITY: replays of the cutphase build v the normal build in the same games: {len(same)} identical, {len(diff)} differ"
         + (f" (games {diff[:10]})" if diff else "") + f", {len(done) - len(same) - len(diff)} unchecked"]
    if not mp:
        return L + [f"(no {calls}: phase tags unavailable)"]
    cut_ph, x_ph = collections.Counter(), collections.Counter()
    xs = collections.defaultdict(lambda: [0, 0, 0])  # stack -> [count, sum left, sum past the mark]
    cut_st = collections.Counter()
    nx = nc = 0
    for k, *_ in done:
        p = f"{out}/ev_{k}.tsv"
        if not os.path.exists(p):
            continue
        for ln in open(p):
            v = ln.split()
            if len(v) < 4:
                continue
            kind, left = v[0], int(v[2])
            st = [tuple(map(int, x.split(":"))) for x in v[4:]]
            ph = phase_of(st, names, mp)
            j = max((i for i, (f, s) in enumerate(st) if mp.get(f, ("",))[0] == "ptb"), default=0)
            key = " > ".join(short(names.get(f, f"f{f}")) for f, s in st[j:])
            if kind == "C":
                nc += 1
                cut_ph[ph] += 1
                cut_st[key] += 1
            elif kind == "X":
                nx += 1
                x_ph[ph] += 1
                e = xs[key]
                e[0] += 1
                e[1] += left
                e[2] += SOFT - left
        os.rename(p, f"{out}/events_{k}.tsv")  # kept: the raw events (small)
        if os.path.exists(f"{out}/cs_{k}.tsv"):
            os.remove(f"{out}/cs_{k}.tsv")
    ng = max(len(done), 1)
    L += ["", f"fuel cuts by turn phase: {nc} cuts in {ng} games ({nc / ng:.2f}/game); 90% crossings (<= {SOFT:,} of the 100k budget left at a "
          f"check point; each instance's first turn skipped): {nx} ({nx / ng:.2f}/game)",
          f"{'phase':<24} {'cuts':>6} {'%':>6} {'cross':>7} {'%':>6}"]
    for ph in PHASES:
        if cut_ph[ph] or x_ph[ph]:
            L.append(f"{ph:<24} {cut_ph[ph]:6d} {100 * cut_ph[ph] / max(nc, 1):5.1f}% {x_ph[ph]:7d} {100 * x_ph[ph] / max(nx, 1):5.1f}%")
    L += ["  (phase: where play_turn_body<N> / turn<N> stood, from its frame's call site: perceive = turn_senses, before the normal-path",
          "   econ::observe; assess = after it up to the first stage call (heal / end_hold / bank_winning_bag); stages = the rest of turn();",
          "   bail = the AfBail catch; tail = after turn() up to intel::end_turn; background = after it; setup = before turn();",
          "   pre-/post-body = play_turn around play_turn_body (strat::begin_turn / act_first_mark_overlong_turn, dom_commit_switch, dom_loop))",
          "", f"call stacks at the 90% crossing, top {top // 4} by count (from play_turn_body down; left = fuel left at the first check past the mark)",
          f"{'n':>5} {'mean left':>9}  stack"]
    for key, e in sorted(xs.items(), key=lambda kv: -kv[1][0])[:top // 4]:
        L.append(f"{e[0]:5d} {e[1] / e[0]:9,.0f}  {key[:400]}")
    L += ["", f"call stacks at the 90% crossing, top {top // 4} by fuel already past the mark when first seen (sum of 10,000 - left: big jumps)",
          f"{'past sum':>9} {'n':>5} {'mean left':>9}  stack"]
    for key, e in sorted(xs.items(), key=lambda kv: -kv[1][2])[:top // 4]:
        L.append(f"{e[2]:9,} {e[0]:5d} {e[1] / e[0]:9,.0f}  {key[:400]}")
    if cut_st:
        L += ["", "call stacks at the fuel cuts (from play_turn_body down)", f"{'n':>5}  stack"]
        for key, n in cut_st.most_common(top // 4):
            L.append(f"{n:5d}  {key[:400]}")
    return L


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("--"):
        sys.exit(__doc__)
    bot = a[0]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    opp = opt("--opp", bot)
    n = int(opt("--maps", 12))
    top = int(opt("--top", 40))
    jobs = int(opt("--jobs", 6))
    rng = random.Random(int(opt("--seed", 1)))
    exe = cxebuild.build_host()
    cp = "--cutphase" in a
    so_p = cxebuild.build_bot(bot, "cutphase" if cp else "fuelprof")
    so_n = cxebuild.build_bot(bot) if cp else None
    so_o = cxebuild.build_bot(opp)
    mapdir = opt("--mapdir", MAPDIR)
    allm = sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a"))
    maps = allm if "--mapdir" in a else rng.sample(allm, n)
    n = len(maps)
    out = os.path.join(cxebuild.ROOT, "fuelprof", f"{os.path.basename(os.path.normpath(bot))}_{time.strftime('%m%d%H%M%S')}_{os.getpid()}")  # 10 Nov: pid too; two runs in one second clobbered each other
    os.makedirs(out, exist_ok=True)
    games = []
    for i, m in enumerate(maps):
        games.append((2 * i, so_p, so_o, m, 0))      # bot as team A
        games.append((2 * i + 1, so_o, so_p, m, 1))  # bot as team B
    # --cutphase: each game again with the normal build (id + 100000, no profile outputs) for the identity check
    twins = [(k + 100000, so_n if x == so_p else x, so_n if y == so_p else y, m, team) for k, x, y, m, team in games] if cp else []
    procs, done = [], []

    def env_of(k, d):  # profile outputs of game k (d: its node dir, None: local); twins write none
        if k >= 100000:
            return {}
        e = {"CXE_FUELPROF": f"{d}/fp.tsv" if d else f"{out}/fp_{k}.tsv"}
        if cp:
            e.update(CXE_CUTPROF=f"{d}/cs.tsv" if d else f"{out}/cs_{k}.tsv", CXE_CUTPHASE=f"{d}/ev.tsv" if d else f"{out}/ev_{k}.tsv")
        return e

    def start(g):
        k, x, y, m, team = g
        env = dict(os.environ, **env_of(k, None))
        return g, subprocess.Popen(["nice", "-n", "10", exe, x, y, os.path.join(mapdir, m), f"{out}/g{k}"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    allg = games + twins
    pend = list(allg)
    if "--local" not in a:  # 6 Nov: the games on the Condor pilots (tools/cxe/cxefarm.py); local play is the fallback
        import cxefarm
        fg = [dict(id=k, a=x, b=y, map=os.path.join(mapdir, m), env=env_of(k, "@D@"), digest=cp,
                   files={**({"fp.tsv": f"{out}/fp_{k}.tsv"} if k < 100000 else {}),
                          **({"cs.tsv": f"{out}/cs_{k}.tsv", "ev.tsv": f"{out}/ev_{k}.tsv"} if cp and k < 100000 else {}),
                          **({"g.sha1": f"{out}/g{k}.sha1"} if cp else {})}) for k, x, y, m, team in allg]
        if cxefarm.run(fg, say=lambda x_: print(x_, flush=True)) is not None:
            done = [g for g in allg if os.path.exists(f"{out}/fp_{g[0]}.tsv") or (g[0] >= 100000 and os.path.exists(f"{out}/g{g[0]}.sha1"))]
            pend = [g for g in allg if g not in done]
    while pend or procs:
        while pend and len(procs) < jobs:
            procs.append(start(pend.pop(0)))
        for item in list(procs):
            if item[1].poll() is not None:
                procs.remove(item)
                done.append(item[0])
        time.sleep(0.05)
    sha = {}
    for k, x, y, m, team in done:  # replay hashes (--cutphase identity check)
        if os.path.exists(f"{out}/g{k}.sha1"):
            sha[k] = open(f"{out}/g{k}.sha1").read().strip()[:40]
            os.remove(f"{out}/g{k}.sha1")
        elif cp and os.path.exists(f"{out}/g{k}.repl26a"):
            sha[k] = hashlib.sha1(open(f"{out}/g{k}.repl26a", "rb").read()).hexdigest()
        if k >= 100000 and os.path.exists(f"{out}/g{k}.repl26a"):
            os.remove(f"{out}/g{k}.repl26a")
    done = [g for g in done if g[0] < 100000]
    fuel, cuts = collections.Counter(), collections.Counter()
    wrapped = set()
    for k, x, y, m, team in done:
        p = f"{out}/fp_{k}.tsv"
        if not os.path.exists(p):
            continue
        for ln in open(p):
            t, fi, f, c = ln.split()
            if int(t) == team:
                v = int(f)
                if v >= 1 << 63:  # 8 Nov: an import charged across a fuel slice refill (draft turn) is negative in the runtime's unsigned counter: read it as signed, count nothing below 0
                    wrapped.add(int(fi))
                    v = max(v - (1 << 64), 0)
                fuel[int(fi)] += v
                cuts[int(fi)] += int(c)
        os.remove(p)
        for ext in (".repl26a",):
            if os.path.exists(f"{out}/g{k}{ext}"):
                os.remove(f"{out}/g{k}{ext}")
    m_named = wasmparse.Module(cxebuild.wasm_of(bot, release=False))  # bot.wasm keeps the name section
    raw = {fi: m_named.names.get(fi, f"f{fi}") for fi in set(fuel) | set(cuts)}
    dm = demangle(sorted(set(raw.values())))
    name = {fi: dm.get(r, r) for fi, r in raw.items()}
    total = sum(fuel.values())
    ng = len(done)
    lines = [f"fuelprof {bot} v {opp}: {ng} games ({n} maps x 2 seats); bot fuel {total:,} = {total / max(ng, 1):,.0f} per game",
             *([f"NOTE: {len(wrapped)} functions undercounted (a host call crossed a fuel slice refill on the draft turn): {', '.join(sorted(name.get(i, str(i))[:40] for i in wrapped)[:8])}"] if wrapped else []),
             "", f"top {top} functions by self fuel (own instructions + bulk-copy bytes + host charges of imports they call)",
             f"{'share':>7} {'fuel/game':>12} {'cuts':>6}  function"]
    loc = {}
    try:  # 13 Nov (RC: hs3_bg(long) was taken for hole_shortcut_top_ready): each listed function's source file:line from the -g build's
        # line table at its first instruction (outermost frame), so a symbol can be checked against the code it really is. FUELPROF_LOC=0: off
        if os.environ.get("FUELPROF_LOC", "1") == "1":
            import lineprof as LP
            import w2c_lineprof as WL
            gw, cli = LP.debug_wasm(bot, lambda m: None)
            mc, bc = wasmparse.Module(cli), open(cli, "rb").read()
            cs = WL.code_start(bc)
            want = [fi for fi, _ in fuel.most_common(top)] + [fi for fi, _ in cuts.most_common(top)]
            addr = {}
            for fi in set(want):
                k = fi - mc.nimp
                if 0 <= k < len(mc.bodies):
                    ops = WL.op_offsets(*mc.bodies[k])
                    if ops:
                        addr[fi] = ops[0] - cs
            sy = LP.symbolize(gw, set(addr.values()))
            for fi, a in addr.items():
                fr = sy.get(a) or []
                if fr:
                    loc[fi] = f"{LP.short_file(fr[-1][1])}:{fr[-1][2]}"
    except Exception as e:  # noqa: BLE001  a missing -g build only drops the column
        lines.append(f"(source locations not resolved: {type(e).__name__}: {str(e)[:100]})")
    for fi, f in fuel.most_common(top):
        lines.append(f"{100 * f / total:6.2f}% {f / ng:12,.0f} {cuts[fi]:6d}  {name[fi][:150]}" + (f"  [{loc[fi]}]" if fi in loc else ""))
    area = collections.Counter()
    for fi, f in fuel.items():
        area[scope(name[fi])] += f
    lines += ["", "by area (C++ namespace::class)", f"{'share':>7} {'fuel/game':>12}  area"]
    for s_, f in area.most_common(25):
        lines.append(f"{100 * f / total:6.2f}% {f / ng:12,.0f}  {s_}")
    tc = sum(cuts.values())
    lines += ["", f"out-of-fuel cuts: {tc} in {ng} games ({tc / max(ng, 1):.1f} per game); where the bot was when its turn was cut",
              f"{'cuts':>6} {'share':>7}  function"]
    for fi, c in [x for x in cuts.most_common(20) if x[1]]:
        lines.append(f"{c:6d} {100 * c / max(tc, 1):6.1f}%  {name[fi][:150]}")
    if cp:
        lines += cutphase_report(out, done, so_p, m_named, sha, top)
    rep = "\n".join(lines) + "\n"
    open(f"{out}/report.txt", "w").write(rep)
    with open(f"{out}/functions.tsv", "w") as f:
        f.write("fuel\tcuts\tfunction\n")
        for fi, v in fuel.most_common():
            f.write(f"{v}\t{cuts[fi]}\t{name[fi]}\n")
    print(rep + f"(full table: {out}/functions.tsv)")


if __name__ == "__main__":
    main()
