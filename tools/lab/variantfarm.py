#!/usr/bin/env python3
"""variantfarm: build N switch variants of a bot and test them all vs live in one command, one table. Tool builder, 30 Oct
(iteration-speed owner; Builder: build agents spent 45-60 min per idea, variants were built and tested one after another).

usage: python3 -I tools/lab/variantfarm.py BASE NAME 'X=1' 'X=2,Y=0' ... [--vs BOT] [--halving] [--maps N] [--no-base]
  BASE   a bot under bots/ that defines the switches (#define X <number>, exactly once in src/); it is only read
  NAME   a short run label ([a-z0-9]+): variants are bots/BASE_NAME<k> (newbot.sh copies; k = 1..N in argument order),
         condab runs vf<NAME><k>, the table /data/USER/st/bq/vf_<NAME>.txt
  --vs   the opponent (default: live from live.txt); --maps N: only the first N maps of the stage order (default 636)
  Each setting is a comma list of SWITCH=VALUE. A variant must differ from BASE only in those #define values (paramdiff).
Steps, all in parallel:
  1. build the N copies (newbot.sh, `find -type l` empty, the defines replaced, paramdiff-checked);
  2. a syntax-only compile of every copy (wasi-sdk clang++ -fsyntax-only, the flags of a real 4.0.0 build, 12 threads,
     ~35 s per copy); a copy that fails is stopped on Condor at once (its condab process group gets SIGTERM);
  3. `OTF=0 condab.sh VAR VS vf<NAME><k> MAPLIST` for every copy (and BASE unless --no-base), Condor priority 0, all at once:
     the pilots run them side by side; games already in the index (same sources, same map) cost nothing.
  Table: per variant the map-pair score vs VS [95% CI], LOS, mean gem share, faults, fuel, and the paired D vs BASE on the
  same maps (mean per-map pair-score difference [95% CI]).
--halving (SUCCESSIVE HALVING, Builder addendum A): stages on the nested prefixes 100, 200, 400, 636 of one fixed
  family-stratified map order (/data/USER/st/bq/subsets/vf_order.txt; nested, so a later stage replays nothing). After each
  stage the better half (rounded up) by map-pair score continues, at least 1. The survivor then gets
  an INDEPENDENT confirmation, `CONFIRM=650 condab.sh SURV VS vfc<NAME>` on fresh maps; the selection stages are never
  pooled into it (winner's curse). Games: N variants fully = N x 1272; halving with N = 8 = 1600 + 800 + 800 + 472 =
  3,672 (36%) + 1,300 confirmation.
After the table (or at the --halving confirmation), the best variant's ubaudit instrumented build starts in the background
(`ubaudit.sh --build-only`; VF_UBPRE=0 skips it), so a SHIPCHECK of it finds the ~7.5 min debug build done.
Never writes SHIPCHECK markers and never edits BASE. Log lines go to stdout and the table file.
"""
import json
import os
import random
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

REPO = "/homes/USER/cambc"
NEWB = "/data/USER/st/new/bots"
Q = "/data/USER/st/bq"
ORDER = os.path.join(Q, "subsets", "vf_order.txt")
CC_TEMPLATE = "/data/USER/st/vf/compile_template.json"  # one real 4.0.0 compile command (flags only are used)
STAGES = [100, 200, 400, 636]
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
import abindex  # noqa: E402
import paramdiff  # noqa: E402

OUT = []


def say(s):
    line = f"{time.strftime('%H:%M:%S', time.gmtime())} {s}"
    print(line, flush=True)
    OUT.append(line)


# ---------------------------------------------------------------- maps
def stage_order():
    """The 636-map pool in a fixed family-stratified random order (made once, then reused by every farm)."""
    if os.path.exists(ORDER):
        return [x.strip() for x in open(ORDER) if x.strip()]
    import condab
    ms = condab.set_maps("all")
    fam = {}
    for m in ms:
        fam.setdefault(abindex.map_set(m) or "other", []).append(m)
    rng = random.Random(20261030)
    for v in fam.values():
        rng.shuffle(v)
    out, taken = [], {k: 0 for k in fam}
    while len(out) < len(ms):  # largest deficit first: every prefix keeps the families' shares
        k = max(fam, key=lambda f: (len(fam[f]) * (len(out) + 1) / len(ms) - taken[f], len(fam[f])))
        if taken[k] >= len(fam[k]):
            fam.pop(k)
            continue
        out.append(fam[k][taken[k]])
        taken[k] += 1
    os.makedirs(os.path.dirname(ORDER), exist_ok=True)
    open(ORDER, "w").write("\n".join(out) + "\n")
    return out


def maplist(n):
    p = os.path.join(Q, "subsets", f"vf_first{n}.txt")
    if not os.path.exists(p):
        open(p, "w").write("\n".join(stage_order()[:n]) + "\n")
    return p


# ---------------------------------------------------------------- variants
def parse_setting(s):
    out = {}
    for kv in s.split(","):
        k, v = kv.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_]\w*", k.strip()) or not re.fullmatch(r"-?\d+(\.\d+)?f?", v.strip()):
            raise ValueError(f"bad setting {kv!r}: SWITCH=NUMBER")
        out[k.strip()] = v.strip()
    return out


def build(base, name, setting):
    r = subprocess.run(["sh", "tools/lab/newbot.sh", base, name], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr).strip()[:200])
    d = os.path.realpath(os.path.join(REPO, "bots", name))
    if subprocess.run(["find", d, "-type", "l"], capture_output=True, text=True).stdout.strip():
        raise RuntimeError(f"{d} has symlinks: not patched")
    src = os.path.join(d, "src")
    for k, v in setting.items():
        rx = re.compile(rf"^(\s*#\s*define\s+{re.escape(k)}\s+)(-?[\d.]+f?)(?=\s|$)", re.M)
        hits = [f for f in paramdiff.files(src).values() if rx.search(open(f).read())]
        if len(hits) != 1 or len(rx.findall(open(hits[0]).read())) != 1:
            raise RuntimeError(f"#define {k}: {len(hits)} files define it numerically (need exactly 1)")
        t = open(hits[0]).read()
        open(hits[0], "w").write(rx.sub(lambda m: m.group(1) + v, t, count=1))
    pr = paramdiff.check(name, base)
    changed = {c[2].split()[1] for c in pr["changes"] if c[2].lstrip().startswith("#")}
    if pr["changes"] and not changed <= set(setting):
        raise RuntimeError(f"unexpected changes vs {base}: {pr['reason']}")
    return name


_CC_SEM = threading.Semaphore(int(os.environ.get("VF_CC_PAR", "2")))  # 1 Nov (load 95/16): armfarm checks every arm at once


def load_threads(lo=12):
    """Local fan-out by /proc/loadavg (1 Nov, Builder): lo threads below load 40, 4 below 60, else 2."""
    la = os.getloadavg()[0]
    return lo if la < 40 else 4 if la < 60 else 2


def compile_check(bot):
    """-> (ok, first error). Syntax-only, every .cpp of bots/BOT/src, the flags of a real 4.0.0 build. At most VF_CC_PAR (2)
    bots at a time in this process, each with load_threads() clang processes."""
    with _CC_SEM:
        return _compile_check(bot)


def _cc_template():
    """10 Nov (Builder: /data/USER/st/vf/compile_template.json was gone, armfarm's compile step crashed): the old file if present, else the
    live bot's own compile_commands.json (one real wasi-sdk compile command; only its flags are used). None: no template anywhere."""
    for p in (CC_TEMPLATE, os.path.join(REPO, "bots", open("/data/USER/st/bq/live.txt").readline().split()[1], "compile_commands.json")):
        try:
            d = json.load(open(p))
            return d[0] if isinstance(d, list) else d
        except (OSError, ValueError, IndexError, KeyError):
            continue
    return None


def _compile_check(bot):
    tpl = _cc_template()
    if tpl is None:
        print("variantfarm: compile check skipped: no compile template (CC_TEMPLATE or the live bot's compile_commands.json)", flush=True)
        return True, ""
    a = shlex.split(tpl["command"]) if "command" in tpl else list(tpl["arguments"])
    flags, i = [], 0
    while i < len(a):
        if a[i] in ("-o",):
            i += 2
            continue
        if a[i] in ("-c", "-O3", "-O2") or a[i].endswith((".cpp", ".cc")):
            i += 1
            continue
        flags.append(a[i])
        i += 1
    src = os.path.join(os.path.realpath(os.path.join(REPO, "bots", bot)), "src")
    tus = sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(".cpp"))  # unity build: nova_all.cpp includes every .cc

    def one(f):
        r = subprocess.run(["nice", "-n", "10"] + flags + ["-fsyntax-only", f], capture_output=True, text=True, cwd=src)
        return r.returncode, r.stderr
    with ThreadPoolExecutor(load_threads()) as ex:
        res = list(ex.map(one, tus))
    bad = [e for rc, e in res if rc]
    return (not bad), (next((ln for ln in bad[0].splitlines() if "error" in ln), bad[0][:200]) if bad else "")


# ---------------------------------------------------------------- runs
def launch(bot, vs, run, ml, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("STOP", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND",
                                                            "KEEP", "CONFIRM", "CONDAB_TIMEBOX_EXT")}
    env.update(OTF="0", CONDAB_PRIO=os.environ.get("VF_PRIO", "0"), **(extra or {}))
    args = ["nice", "-n", "10", "sh", "tools/lab/condab.sh", bot, vs, run] + ([ml] if ml else [])
    lg = open(os.path.join(Q, f"{run}.vf.log"), "a")
    return subprocess.Popen(args, cwd=REPO, env=env, stdout=lg, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)


def stop(p, why):
    if p.poll() is None:
        say(f"stop pid {p.pid}: {why}")
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass


def rows(bot, vs, maps):
    """{map: (pair score, gem share)} of BOT vs VS on maps, from the index."""
    hb, hv = abindex.bot_hash(bot), abindex.bot_hash(vs)
    ix = abindex.Index({hb, hv})
    rs, _ = abindex.map_pairs(ix, hb, hv)
    ms = set(maps)
    return {m: (s, gx / max(1, gx + gy)) for m, _, s, gx, gy in rs if m in ms}


def faults_fuel(run, bot):
    try:
        t = open(os.path.join(Q, f"{run}.condor.txt")).read()
    except OSError:
        return "?", "?"
    m = re.search(rf"^\s+{re.escape(bot)}\s+faults (\d+) .*?fuel exhaustions (\d+)", t, re.M)
    return (m.group(1), m.group(2)) if m else ("?", "?")


def summary(r):
    n = len(r)
    if not n:
        return dict(n=0, score=0.0, lo=0.0, hi=0.0, los=0.5, gem=0.0)
    s = [v[0] for v in r.values()]
    mean = sum(s) / n
    se = (sum((x - mean) ** 2 for x in s) / max(1, n - 1) / n) ** 0.5
    w, l = sum(x == 1 for x in s), sum(x == 0 for x in s)
    import math
    los = 0.5 * (1 + math.erf((w - l) / math.sqrt(2 * (w + l)))) if w + l else 0.5
    return dict(n=n, score=mean, lo=mean - 1.96 * se, hi=mean + 1.96 * se, los=los, gem=sum(v[1] for v in r.values()) / n)


def paired(a, b):
    ms = sorted(set(a) & set(b))
    if len(ms) < 2:
        return None
    d = [a[m][0] - b[m][0] for m in ms]
    mu = sum(d) / len(d)
    se = (sum((x - mu) ** 2 for x in d) / (len(d) - 1) / len(d)) ** 0.5
    return mu, mu - 1.96 * se, mu + 1.96 * se, len(ms), sum(x != 0 for x in d)


def table(title, entries, base, vs, maps):
    br = rows(base, vs, maps) if base else {}
    L = [title, f"  {'variant':34s} {'setting':22s} {'n':>4s} {'score [95% CI]':22s} {'LOS':>4s} {'gem':>5s} "
         f"{'D vs BASE [95% CI] (maps changed)':38s} {'faults':>6s} {'fuel':>5s}"]
    res = {}
    for bot, label, run in entries:
        r = rows(bot, vs, maps)
        s = summary(r)
        res[bot] = (s, r)
        pd = paired(r, br) if base and bot != base else None
        f, fu = faults_fuel(run, bot)
        L.append(f"  {bot:34s} {label[:22]:22s} {s['n']:4d} {s['score']:.3f} [{s['lo']:.3f}, {s['hi']:.3f}]   "
                 f"{s['los'] * 100:3.0f}% {s['gem']:.3f} "
                 + (f"{pd[0]:+.3f} [{pd[1]:+.3f}, {pd[2]:+.3f}] ({pd[4]}/{pd[3]})".ljust(38) if pd else ("(base)" if bot == base else "-").ljust(38))
                 + f" {f:>6s} {fu:>5s}")
    return "\n".join(L), res


def run_stage(entries, vs, ml, tag):
    """entries: [(bot, label, run)] -> waits for every condab; returns {bot: returncode}."""
    procs = {bot: launch(bot, vs, run + tag, ml) for bot, label, run in entries}
    say(f"stage {tag or 'full'}: {len(procs)} condab runs on {ml or 'the full pool'} (pids "
        + " ".join(str(p.pid) for p in procs.values()) + ")")
    return procs


def ub_prebuild(bot, vs):
    """Start ubaudit's instrumented build of BOT (and VS) in the background (30 Oct, iteration-speed): a survivor is the next
    SHIPCHECK candidate, and its ~7.5 min debug build is then done before the gate's audit needs it. VF_UBPRE=0 skips it."""
    if os.environ.get("VF_UBPRE", "1") == "0":
        return
    subprocess.Popen(["nice", "-n", "10", "sh", os.path.join(REPO, "tools/lab/ubaudit.sh"), "--build-only", bot, vs], cwd=REPO,
                     stdout=open(os.path.join(Q, f"ubpre_{bot}.log"), "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    say(f"ubaudit instrumented build of {bot} started in the background (log {Q}/ubpre_{bot}.log)")


def main():
    a = sys.argv[1:]
    if len(a) < 3 or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    base, name = a[0], a[1]
    flags_with_val = {"--vs", "--maps"}
    sets = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and a[i - 1] not in flags_with_val]
    if not re.fullmatch(r"[a-z0-9]+", name):
        sys.exit("NAME must be [a-z0-9]+")
    vs = opt("--vs") or open(os.path.join(Q, "live.txt")).read().split()[1]
    halving = "--halving" in a
    nmaps = int(opt("--maps", 636))
    settings = [parse_setting(s) for s in sets]
    variants = []
    for k, st in enumerate(settings, 1):
        bot = f"{base}_{name}{k}"
        build(base, bot, st)
        variants.append((bot, ",".join(f"{x}={y}" for x, y in st.items()), f"vf{name}{k}"))
        say(f"built {bot}: {variants[-1][1]}")
    entries = variants + ([] if "--no-base" in a else [(base, "(base)", f"vf{name}0")])
    tfile = os.path.join(Q, f"vf_{name}.txt")
    stages = [n for n in STAGES if n < nmaps] + [nmaps] if halving else [nmaps]
    alive = list(entries)
    for si, n in enumerate(stages):
        ml = maplist(n)
        procs = run_stage(alive, vs, ml, f"s{n}" if halving else "")
        if si == 0:  # compile check in parallel with the first stage: a broken copy is stopped at once
            def check(bot):
                ok, err = compile_check(bot)
                say(f"compile {bot}: {'ok' if ok else 'FAILED: ' + err[:150]}")
                if not ok:
                    stop(procs[bot], "compile check failed")
            th = [threading.Thread(target=check, args=(b,)) for b, _, _ in variants]
            for t in th:
                t.start()
            for t in th:
                t.join()
        for bot, p in procs.items():
            p.wait()
        maps = stage_order()[:n]
        txt, res = table(f"VARIANT FARM {name}: vs {vs}, {n} maps (stage {si + 1}/{len(stages)})", alive, base
                         if any(b == base for b, _, _ in alive) else None, vs, maps)
        say("\n" + txt)
        open(tfile, "w").write("\n".join(OUT) + "\n")
        if not halving or si == len(stages) - 1:
            break
        cands = sorted([e for e in alive if e[0] != base], key=lambda e: -res[e[0]][0]["score"])
        keep = min(len(cands), max(1, (len(cands) + 1) // 2))
        alive = cands[:keep] + [e for e in alive if e[0] == base]
        say(f"halving: keep {', '.join(e[0] for e in cands[:keep])}; out {', '.join(e[0] for e in cands[keep:]) or '-'}")
    if halving:
        surv = sorted([e for e in alive if e[0] != base], key=lambda e: -res[e[0]][0]["score"])[0]
        run = f"vfc{name}"
        say(f"independent confirmation of {surv[0]}: CONFIRM=650 fresh maps ({run}); the stages are not pooled into it")
        ub_prebuild(surv[0], vs)
        p = launch(surv[0], vs, run, None, dict(CONFIRM="650"))
        p.wait()
        t = open(os.path.join(Q, f"{run}.condor.txt")).read() if os.path.exists(os.path.join(Q, f"{run}.condor.txt")) else ""
        m = re.search(r"^\s+confirm\s+\d+ maps: .*$", t, re.M)
        say(f"CONFIRM {surv[0]}: {m.group(0).strip() if m else 'no result (see ' + run + '.vf.log)'}")
    if not halving:  # the best variant by score that beats BASE on its paired D: the likely next SHIPCHECK
        best = sorted([e for e in alive if e[0] != base], key=lambda e: -res[e[0]][0]["score"])
        if best and (not any(b == base for b, _, _ in alive) or res[best[0][0]][0]["score"] > res[base][0]["score"]):
            ub_prebuild(best[0][0], vs)
    open(tfile, "w").write("\n".join(OUT) + "\n")
    say(f"table: {tfile}")


if __name__ == "__main__":
    main()
