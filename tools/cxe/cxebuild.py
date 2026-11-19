"""cxebuild: build a bot for cxe (the native test engine). Copies bots/NAME/src into a private build dir (the bot dir is
never written: FROZEN BOT DIRS), builds the release WebAssembly with the official CLI (`cambc400 build --release`,
the same build the CLI plays), translates it with w2c.py (fuel metered) and compiles a shared library.
Everything is cached: sources by hash, the library by the hash of the WebAssembly, so a rebuild of identical code
costs nothing. Prints the .so path. Also builds the cxe host itself (engine + host) when missing or stale.
usage: python3 -I tools/cxe/cxebuild.py BOT [BOT...] [--pgo]   (BOT = a name under bots/ or a path to a bot dir;
       --pgo: profile-guided bot build, ~2 min more, ~6-8% faster games; worth it for long runs)
       python3 -I tools/cxe/cxebuild.py --host           (host only)"""
import concurrent.futures
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(os.path.dirname(HERE))
ROOT = os.environ.get("CXE_ROOT", "/data/USER/st/cxe")
PROJ = os.path.join(ROOT, "proj")             # CLI project (cambc.toml, sdk, cmake); bots are built under PROJ/bots
SO = os.path.join(ROOT, "so")                 # <wasm sha>.so
OBJ = os.path.join(ROOT, "obj")               # compiled bot parts by content (cxebuild compile_all)
CLANG_ID = subprocess.run(["clang", "--version"], capture_output=True, text=True).stdout.split("\n")[0]
RT_H = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "w2c_rt.h"), "rb").read()
HOSTD = os.path.join(ROOT, "host")            # cxe binary + objects
# engine versions (4 Nov: cambc 5.0.0 / engine v3_0_0 published; the bot wasm both CLIs build is byte-identical): the engine the
# translated host plays and the CLI that spot-checks and builds with it. ENGINE_SWITCH's first word picks the default for every
# tool (one edit moves the pipeline when the ladder moves); CXE_ENGINE_VER picks one per process; CXE_ENGINE / CXE_CLI override.
ENGINES = {"v2_0_0": ("/homes/USER/condor-work/engine/v2_0_0.wasm", "/data/USER/cambc400/bin/cambc400"),
           "v3_0_0": ("/homes/USER/condor-work/engine/v3_0_0.wasm", "/data/USER/cambc500/bin/cambc500")}
ENGINE_SWITCH = "/data/USER/st/bq/cxe_engine.txt"


def default_engine():
    try:
        v = open(ENGINE_SWITCH).read().split()[0]
        return v if v in ENGINES else "v2_0_0"
    except (OSError, IndexError):
        return "v2_0_0"


ENGINE_VER = os.environ.get("CXE_ENGINE_VER") or default_engine()
if ENGINE_VER not in ENGINES:
    sys.exit(f"cxebuild: unknown CXE_ENGINE_VER {ENGINE_VER} (known: {', '.join(ENGINES)})")
CLI = os.environ.get("CXE_CLI", ENGINES[ENGINE_VER][1])
ENGINE = os.environ.get("CXE_ENGINE", ENGINES[ENGINE_VER][0])
# profile-guided builds (4 Nov: engine ~4%, engine + bot ~10-12% less CPU, replays identical): the engine profile was
# recorded once over 24 random workspace maps; bot profiles are recorded per bot version with --pgo
ENGINE_PROFILE = os.path.join(ROOT, "pgo", "keep", "engine-v2_0_0.profdata")
PROFRT = "/usr/lib/llvm-21/lib/clang/21/lib/linux/libclang_rt.profile-x86_64.a"
SPLIT = int(os.environ.get("CXE_SPLIT", "8"))  # translated bot C is compiled as this many parts in parallel
CFLAGS = ["-O3", "-march=x86-64-v3", "-fno-strict-aliasing", "-ffp-contract=off", "-fno-fast-math", "-I" + HERE]


class build_slot:
    """One of CXE_BUILD_SLOTS (default 12) machine-wide build slots (flock), held around local CLI builds and C compiles (owner 4 Nov ~21:55Z: ~10
    builds at once on 16 cores crashed VS Code at load 48). Owner 6 Nov ~19:55Z asked for more under a safe limit. Slots past CXE_BUILD_SOFT (8) open only
    below load CXE_BUILD_LOAD_HI (28), so a build burst should end near load 40 from either tier (a CLI build = one core, 47 s, .6 GB; 12 at once from
    load 30 peaked at 38.3; clang parts have their own cap, flock_slot ccslots, which the 15:00Z run at 12 slots and load 43 did not have)."""
    def __enter__(self):
        def _lim(k, dflt):  # 10 Nov (owner: let the load go up, safely): env CXE_BUILD_LOAD[_HI] still wins, then loadlim's file
            try:
                if "/homes/USER/cambc/tools/lab" not in sys.path:
                    sys.path.append("/homes/USER/cambc/tools/lab")
                import loadlim
                return loadlim.get(k)
            except Exception:  # noqa: BLE001
                return float(dflt)
        d = os.path.join(ROOT, "buildslots")
        os.makedirs(d, exist_ok=True)
        while True:
            try:  # owner 6 Nov ~14:05Z: 8 slots (12 pushed load to 43 at 14:58Z), no new build while the 1-min load is above CXE_BUILD_LOAD (32); the crash was at load 48
                busy = os.getloadavg()[0] > _lim("cxe_build_load", 32)  # 10 Nov: tools/lab/loadlim.py (bq/load_limits), now 40
                with open("/proc/meminfo") as mf:  # and none while MemAvailable < CXE_BUILD_MEM_GB (10; owner 4 Nov RAM rule)
                    ma = next(int(l.split()[1]) for l in mf if l.startswith("MemAvailable"))
                busy = busy or ma < float(os.environ.get("CXE_BUILD_MEM_GB", "10")) * 1024 * 1024
            except (OSError, StopIteration, ValueError):
                busy = False
            if busy:
                time.sleep(2)
                continue
            n = int(os.environ.get("CXE_BUILD_SLOTS", "12"))
            if os.getloadavg()[0] > _lim("cxe_build_load_hi", 28):
                n = min(n, int(os.environ.get("CXE_BUILD_SOFT", "8")))
            for k in range(n):
                f = open(os.path.join(d, f"slot{k}.lock"), "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.f = f
                    return self
                except OSError:
                    f.close()
            time.sleep(0.5)

    def __exit__(self, *a):
        self.f.close()


class flock_slot:
    """One of N machine-wide slots (flock; frees when the holder dies), no load gate: flock_slot("ccslots", "CXE_CC_SLOTS", 6). ec1 6 Nov: a build_slot
    held 8 parallel clangs, so its 8 slots allowed 64 at once: 6 estcheck drivers building probe copies took HOST to load 67."""
    def __init__(self, sub, env, n):
        self.d, self.n = os.path.join(ROOT, sub), int(os.environ.get(env, n))

    def __enter__(self):
        os.makedirs(self.d, exist_ok=True)
        while True:
            for k in range(self.n):
                f = open(os.path.join(self.d, f"slot{k}.lock"), "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.f = f
                    return self
                except OSError:
                    f.close()
            time.sleep(0.3)

    def __exit__(self, *a):
        self.f.close()


def sh(cmd, **k):
    r = subprocess.run(cmd, capture_output=True, text=True, **k)
    if r.returncode:
        sys.exit(f"cxebuild: {' '.join(cmd[:3])}... failed:\n{(r.stdout + r.stderr)[-3000:]}")
    return r.stdout


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tree_hash(d):
    h = hashlib.sha1()
    for r, ds, fs in sorted(os.walk(d)):
        ds.sort()
        for f in sorted(fs):
            p = os.path.join(r, f)
            h.update(os.path.relpath(p, d).encode() + b"\0")
            with open(p, "rb") as fh:
                h.update(hashlib.sha1(fh.read()).digest())
    return h.hexdigest()[:12]


def host_sources():
    return [os.path.join(HERE, f) for f in ("cxe.cpp", "cxedec.cpp", "w2c_rt.c", "w2c_rt.h", "cxe_wasi.c", "cxe_imports.h", "w2c.py", "wasmparse.py")]


def build_host():
    """cxe = host (C++) + the translated engine + runtime. Rebuilt when any source or the engine changes.
    5 Nov (Tool builder): pipeline runs build only COMMITTED host source. With uncommitted edits in the host sources the current
    host for this engine is returned unchanged (a test build of a wrong fuel rule became the default for 2 minutes and 11 Condor
    batches staged it). CXE_DEV=1 builds the working copy for a test, and never moves the default links."""
    os.makedirs(HOSTD, exist_ok=True)
    dev = os.environ.get("CXE_DEV") == "1"
    if not dev:
        repo = [p for p in host_sources() if os.path.abspath(p).startswith(REPO_ROOT + os.sep)]
        dirty = subprocess.run(["git", "-C", REPO_ROOT, "status", "--porcelain", "--"] + repo, capture_output=True, text=True).stdout.strip()
        cur = os.path.join(HOSTD, "cxe-" + ENGINE_VER)
        if dirty and os.path.exists(cur) and "CXE_ENGINE" not in os.environ:
            print(f"cxebuild: uncommitted host source ({dirty.splitlines()[0].strip()} ...): using the current host {os.path.realpath(cur)}; "
                  "CXE_DEV=1 to test the working copy", file=sys.stderr)
            return os.path.realpath(cur)
    h = hashlib.sha1()
    for p in host_sources() + [ENGINE] + ([ENGINE_PROFILE] if os.path.exists(ENGINE_PROFILE) else []):
        h.update(open(p, "rb").read())
    h.update(" ".join(CFLAGS[:-1]).encode())
    key = h.hexdigest()[:12]
    exe = os.path.join(HOSTD, f"cxe-{key}")
    link = os.path.join(HOSTD, "cxe")  # the default engine's host only: a host for another engine never moves it
    objd = HOSTD if ENGINE == ENGINES["v2_0_0"][0] else os.path.join(HOSTD, "obj-" + hashlib.sha1(open(ENGINE, "rb").read()).hexdigest()[:12])
    os.makedirs(objd, exist_ok=True)
    with open(os.path.join(HOSTD, ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.exists(exe):
            eng_c = os.path.join(objd, "engine.c")
            sh([sys.executable, "-I", os.path.join(HERE, "w2c.py"), ENGINE, eng_c, "--prefix", "engine"])
            objs = []
            for src, out in ((eng_c, "engine.o"), (os.path.join(HERE, "w2c_rt.c"), "rt.o"), (os.path.join(HERE, "cxe_wasi.c"), "wasi.o")):
                o = os.path.join(objd, out)
                pgo = ["-fprofile-instr-use=" + ENGINE_PROFILE, "-Wno-profile-instr-unprofiled", "-Wno-profile-instr-out-of-date"] \
                    if out == "engine.o" and os.path.exists(ENGINE_PROFILE) else []
                sh(["nice", "-n", "10", "clang"] + CFLAGS + pgo + ["-c", src, "-o", o])
                objs.append(o)
            o = os.path.join(objd, "cxe.o")
            sh(["nice", "-n", "10", "g++", "-O2", "-std=c++17", "-fno-strict-aliasing", "-I" + HERE, "-c", os.path.join(HERE, "cxe.cpp"), "-o", o])
            od = os.path.join(objd, "cxedec.o")
            ename = [f'-DCXE_ENGINE_NAME="{ENGINE_VER}"'] if ENGINE_VER != "v2_0_0" and "CXE_ENGINE" not in os.environ else []
            sh(["nice", "-n", "10", "g++", "-O2", "-std=c++17", "-fno-strict-aliasing", "-I" + HERE] + ename + ["-c", os.path.join(HERE, "cxedec.cpp"), "-o", od])
            sh(["g++", "-rdynamic", "-o", exe + ".tmp", o, od] + objs + ["-ldl", "-lm"])
            os.replace(exe + ".tmp", exe)
            os.remove(eng_c)
        if "CXE_ENGINE" not in os.environ and not dev:  # host/cxe-<version> for each engine (cxedec picks one by the replay's header), host/cxe = default
            for ln in ([link] if ENGINE_VER == default_engine() else []) + [os.path.join(HOSTD, "cxe-" + ENGINE_VER)]:
                tmp = ln + ".tmp"
                if os.path.lexists(tmp):
                    os.remove(tmp)
                os.symlink(os.path.basename(exe), tmp)
                os.replace(tmp, ln)
    return exe


# the build recipe in the library key: bump it whenever how parts are compiled or linked changes (4 Nov: libraries linked before
# the data part was compiled stayed cached, keyed only on the translator)
BUILD_RECIPE = "2"
_MOD_OK = {}


class MissingImports(RuntimeError):
    """A bot library needs engine imports the cxe host does not implement (the CLI does): callers fall back to the CLI."""


_HOST_IMPORTS = []


def missing_imports(so):
    """Engine imports the library needs that the cxe host does not define (sorted)."""
    if not _HOST_IMPORTS:
        r = subprocess.run(["nm", "-D", "--defined-only", build_host()], capture_output=True, text=True)
        _HOST_IMPORTS.append({ln.split()[-1] for ln in r.stdout.splitlines() if "cxe_imp_" in ln})
    r = subprocess.run(["nm", "-D", "--undefined-only", so], capture_output=True, text=True)
    need = {ln.split()[-1] for ln in r.stdout.splitlines() if "cxe_imp_" in ln}
    return sorted(x.replace("cxe_imp_env__", "") for x in need - _HOST_IMPORTS[0])


def has_module(so):
    """The library defines bot_module (what cxe loads); cached per (path, mtime, size)."""
    try:
        st = os.stat(so)
    except OSError:
        return False
    k = (so, st.st_mtime_ns, st.st_size)
    if k not in _MOD_OK:
        r = subprocess.run(["nm", "-D", "--defined-only", so], capture_output=True, text=True)
        _MOD_OK[k] = any(ln.endswith(" bot_module") for ln in r.stdout.splitlines())
    return _MOD_OK[k]


def shared_wasm(srcdir):
    """A release wasm already built for this exact source tree under any bot name (pilot_wasm's cache, mergecheck's builds) -> path or
    None. 6 Nov: the CLI's wasm does not depend on the bot's name (a mergecheck mc_* build and a pilot_wasm build of the same src were
    byte-identical, 2,051,866 bytes), so cxeident and mergecheck no longer each build the same CAND on a pilot (~90 s each)."""
    import glob
    th = tree_hash(srcdir)
    for p in sorted(glob.glob(os.path.join(PROJ, "pilotwasm", f"*-{th}.wasm"))):
        if has_wasm_magic(p):
            return p
    return None


def save_shared_wasm(srcdir, wasm):
    """Record a release wasm built elsewhere (mergecheck's Condor build) for later shared_wasm lookups."""
    if not has_wasm_magic(wasm):
        return
    out = os.path.join(PROJ, "pilotwasm", f"shared-{tree_hash(srcdir)}.wasm")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = f"{out}.{os.getpid()}.tmp"
        shutil.copyfile(wasm, tmp)
        os.replace(tmp, out)


def pilot_wasm(bot):
    """The bot's release wasm built on a Condor pilot (tools/lab/pilotbuild.py, ~30 s off this machine; what flip.sh's trunk cache
    already uses) -> path, cached by source; None when no pilot built it (the caller builds locally). 4 Nov: local CLI builds of
    code candidates took 3-5 min each at load 100-140, ten at a time."""
    src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    if os.path.realpath(os.path.dirname(os.path.normpath(src))) != os.path.realpath(os.path.join(REPO, "bots")):
        return None  # pilotbuild packs bots/NAME/src
    th = tree_hash(os.path.join(src, "src"))
    out = os.path.join(PROJ, "pilotwasm", f"{name}-{th}.wasm")
    if os.path.exists(out):
        return out
    sw = shared_wasm(os.path.join(src, "src"))  # the same source built under another name (e.g. mergecheck's mc_* build)
    if sw:
        return sw
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.exists(out):
            r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/pilotbuild.py"), name, out], capture_output=True)
            if r.returncode or not os.path.exists(out) or not has_wasm_magic(out):
                return None
    return out


def has_wasm_magic(p):
    try:
        return open(p, "rb").read(4) == b"\0asm"
    except OSError:
        return False


def cli_build(bot):
    """The CLI's release build of the bot in PROJ (what CLI spot-checks run; wasm_of reads it) -> its bot-injected.wasm."""
    src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    th = tree_hash(os.path.join(src, "src"))
    bd = os.path.join(PROJ, "bots", f"{name}-{th}")
    wasm = os.path.join(bd, ".cambc", "build-release", "bot-injected.wasm")
    os.makedirs(os.path.join(PROJ, "bots"), exist_ok=True)
    with open(os.path.join(PROJ, f".build_{name}-{th}.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.exists(wasm):
            if not os.path.isdir(os.path.join(bd, "src")):
                tmp = bd + f".tmp{os.getpid()}"
                shutil.copytree(os.path.join(src, "src"), os.path.join(tmp, "src"))
                os.replace(tmp, bd)
            env = dict(os.environ, CAMBC_WASMTIME_CACHE=os.environ.get("CAMBC_WASMTIME_CACHE", "/data/USER/wtcache"))
            with build_slot():
                sh(["nice", "-n", "10", CLI, "build", os.path.relpath(bd, PROJ), "--release"], cwd=PROJ, env=env)
            if not os.path.exists(wasm):
                sys.exit(f"cxebuild: the CLI build produced no {wasm}")
    return wasm


def flip_wasm(src):
    """A flip's own wasm (bots/NAME/FLIP WASM=, flip.sh's data-patched trunk build: byte-identical to the CLI build of its source,
    checked on nova_b1378_dltg 4 Nov), when the FLIP file is at least as new as every source file; else None."""
    fl = os.path.join(src, "FLIP")
    try:
        w = dict(ln.split("=", 1) for ln in open(fl).read().splitlines() if "=" in ln).get("WASM", "")
        if not w or not os.path.exists(w):
            return None
        t = os.path.getmtime(fl)
        for r, _, fs in os.walk(os.path.join(src, "src")):
            for f in fs:
                if os.path.getmtime(os.path.join(r, f)) > t:
                    return None
        return w
    except (OSError, ValueError):
        return None


def build_bot(bot, variant="", wasm=None):
    """variant "": the playing build; "fuelprof": per-function fuel attribution (tools/cxe/fuelprof.py); "cutprof": fuelprof + a shadow call stack that credits a fuel cut to every function running at the cut (tools/cxe/w2c_cutprof.py, tools/cxe/cutprof.py)."""
    if wasm is None:
        src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
        name = os.path.basename(os.path.normpath(src))
        if not os.path.isdir(os.path.join(src, "src")):
            sys.exit(f"cxebuild: {src} has no src/")
        th = tree_hash(os.path.join(src, "src"))
        wasm = os.path.join(PROJ, "bots", f"{name}-{th}", ".cambc", "build-release", "bot-injected.wasm")
        if not os.path.exists(wasm):
            fw = flip_wasm(src) if variant not in ("fuelprof", "cutprof", "cutphase", "callmax", "lineprof") else None  # fuelprof reads the CLI build's names (bot.wasm)
            # a flip: translate flip.sh's own wasm (byte-identical to the CLI build). 4 Nov: no background CLI build any more: spot-checks
            # run the CLI's match runner on this same wasm (cxecondab), and wasm_of/cli_bot_dir build on demand. The background
            # builds (10+ wasm32 clang++ processes for minutes per flip) were most of HOST's load.
            wasm = fw or pilot_wasm(bot) or cli_build(bot)
    else:  # a given wasm (trunkmerge's identity check: the trunk wasm flip.sh caches), translated as is
        name, th = os.path.basename(os.path.normpath(bot)), "wasm"
    ws = sha(wasm)
    # the library also depends on the translator, its runtime header and the compiler flags: key on all of them
    kh = hashlib.sha256(ws.encode())
    for p in (os.path.join(HERE, "w2c.py"), os.path.join(HERE, "w2c_rt.h"), os.path.join(HERE, "wasmparse.py")):
        kh.update(open(p, "rb").read())
    kh.update(" ".join(CFLAGS[:-1]).encode())
    kh.update(variant.encode())
    kh.update(BUILD_RECIPE.encode())
    if variant == "cutprof":  # tools/cxe/w2c_cutprof.py (shadow-stack cut attribution) translates this variant
        kh.update(open(os.path.join(HERE, "w2c_cutprof.py"), "rb").read())
    if variant == "cutphase":  # tools/cxe/w2c_cutphase.py (cutprof + per-cut and 90%-crossing stacks with turn-phase call sites; fuelprof.py --cutphase)
        kh.update(open(os.path.join(HERE, "w2c_cutphase.py"), "rb").read())
    if variant == "callmax":  # tools/cxe/w2c_callmax.py (per-call inclusive fuel maxima)
        kh.update(open(os.path.join(HERE, "w2c_callmax.py"), "rb").read())
    if variant == "lineprof":  # tools/cxe/w2c_lineprof.py (per-flush-site counters; tools/cxe/lineprof.py); also writes SO/<key>.sites.tsv
        kh.update(open(os.path.join(HERE, "w2c_lineprof.py"), "rb").read())
    ws = kh.hexdigest()
    os.makedirs(SO, exist_ok=True)
    so = os.path.join(SO, ws[:16] + ".so")
    with open(os.path.join(SO, f".{ws[:16]}.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if os.path.exists(so) and not has_module(so):  # a broken cached library (4 Nov: linked without the data part) is rebuilt
            os.replace(so, so + ".bad")
        if not os.path.exists(so):
            base = os.path.join(SO, ws[:16])
            tr = {"cutprof": "w2c_cutprof.py", "cutphase": "w2c_cutphase.py", "callmax": "w2c_callmax.py", "lineprof": "w2c_lineprof.py"}.get(variant, "w2c.py")
            sh([sys.executable, "-I", os.path.join(HERE, tr), wasm, base + ".c", "--prefix", "bot", "--fuel", "--split", str(SPLIT)]
               + (["--fuelprof"] if variant in ("fuelprof", "cutprof", "cutphase", "callmax", "lineprof") else []) + (["--profile"] if variant == "profile" else []))  # profile: op-class counters, measurement only
            cs = [f"{base}.{i}.c" for i in range(SPLIT)] + [f"{base}.data.c"]

            def compile_all(extra, cache=True):
                # content-addressed object cache (OBJ): a part whose C text, flags and compiler match a compiled one is reused, so a
                # data-only flip recompiles only its data part (0.7 s) instead of all 8 code parts (~20 s under load)
                todo, keys = [], {}
                for c in cs:
                    # the runtime header is part of every object (4 Nov: objects from a since-reverted header were reused and the
                    # libraries referenced a symbol the host no longer had)
                    k = hashlib.sha256(open(c, "rb").read() + RT_H + " ".join(CFLAGS[:-1] + extra).encode() + CLANG_ID.encode()).hexdigest()[:24]
                    keys[c] = os.path.join(OBJ, k + ".o")
                    if cache and os.path.exists(keys[c]):
                        shutil.copyfile(keys[c], c[:-2] + ".o")
                        os.utime(keys[c])
                    else:
                        todo.append(c)
                def one(c):  # at most CXE_CC_SLOTS (12) clang parts machine-wide: HOST has ~11 free cores, so more only adds load, not speed
                    with flock_slot("ccslots", "CXE_CC_SLOTS", 6):
                        p = subprocess.Popen(["nice", "-n", "10", "clang", "-fPIC"] + CFLAGS + extra + ["-c", c, "-o", c[:-2] + ".o"],
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        return p, p.communicate()[0]
                # sc1 6 Nov: a whole wave goes to a pilot, compiled there with this machine's clang (tools/cxe/pilotcc.py; byte-identical objects, each batch
                # checked); parts it does not return, a flip's single part and CXE_CC_LOCAL=1 stay local below
                left = list(todo)
                if cache and not extra:
                    sys.path.insert(0, HERE)
                    import pilotcc
                    if pilotcc.use_pilots(len(todo)):
                        got = pilotcc.compile_parts(todo, cs[-1], CFLAGS, slot=lambda: flock_slot("ccslots", "CXE_CC_SLOTS", 6))
                        left = [c for c in todo if c not in got]
                res = []
                if left:
                    with build_slot(), concurrent.futures.ThreadPoolExecutor(len(left)) as ex:
                        res = list(ex.map(one, left))
                procs, errs = [x[0] for x in res], [x[1] for x in res]
                if any(p.returncode for p in procs):
                    sys.exit("cxebuild: compile failed:\n" + "\n".join(e[-2000:] for e in errs if e))
                if cache:
                    os.makedirs(OBJ, exist_ok=True)
                    for c in todo:
                        tmp = f"{keys[c]}.{os.getpid()}.tmp"
                        shutil.copyfile(c[:-2] + ".o", tmp)
                        os.replace(tmp, keys[c])
                    now = time.time()
                    for f in os.listdir(OBJ):  # keep objects used in the last 3 days
                        try:
                            if now - os.path.getmtime(os.path.join(OBJ, f)) > 3 * 86400:
                                os.remove(os.path.join(OBJ, f))
                        except OSError:
                            pass
                return len(cs) - len(todo)
            if variant == "pgo":
                prof = train_bot_profile(cs, base)
                compile_all(["-fprofile-instr-use=" + prof, "-Wno-profile-instr-unprofiled", "-Wno-profile-instr-out-of-date"], cache=False)
            else:
                compile_all([])
            sh(["clang", "-shared", "-o", so + ".tmp"] + [c[:-2] + ".o" for c in cs])
            if not has_module(so + ".tmp"):
                sys.exit(f"cxebuild: {so}.tmp defines no bot_module (a translated part was not compiled)")
            miss = missing_imports(so + ".tmp")
            if miss:  # b1167 4 Nov: such a bot failed to load at play time with only a dlopen error
                os.remove(so + ".tmp")
                raise MissingImports(f"cxebuild: {name} uses engine imports cxe does not implement yet: {', '.join(miss)} "
                                     f"(play it on the CLI; ask the Tool builder to add them)")
            os.replace(so + ".tmp", so)
            for c in cs:
                os.remove(c)
                os.remove(c[:-2] + ".o")
    with open(os.path.join(SO, "names.tsv"), "a") as f:
        f.write(f"{name}\t{th}\t{ws[:16]}{'\t' + variant if variant else ''}\n")
    return so


def train_bot_profile(cs, base, n_games=24):
    """Instrumented build of the bot, n_games self-play games on random workspace maps with an instrumented host,
    merged profile -> path. Profiles change only code layout and inlining, never results (checked: replays identical)."""
    procs = [subprocess.Popen(["nice", "-n", "10", "clang", "-fPIC"] + CFLAGS + ["-fprofile-instr-generate", "-c", c, "-o", c[:-2] + ".g.o"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for c in cs]
    for p in procs:
        p.communicate()
    gso = base + ".gen.so"
    sh(["clang", "-shared", "-fprofile-instr-generate", "-o", gso] + [c[:-2] + ".g.o" for c in cs])
    hexe = os.path.join(HOSTD, "cxe-profgen")
    if True:  # relinked every time (about a second) so it always matches the current host objects
        sh(["g++", "-rdynamic", "-Wl,-u,__llvm_profile_runtime", "-o", hexe] + [os.path.join(HOSTD, x) for x in ("cxe.o", "engine.o", "rt.o", "wasi.o")]
           + [PROFRT, "-ldl", "-lm"])
    mapdir = "/data/USER/ablproj_4.0.0/maps"
    import random
    maps = random.Random(5).sample(sorted(f for f in os.listdir(mapdir) if f.endswith(".map26a")), n_games)
    raws = []
    for i, m in enumerate(maps):
        raw = f"{base}.{i}.profraw"
        subprocess.run([hexe, gso, gso, os.path.join(mapdir, m), base + ".train"], env=dict(os.environ, LLVM_PROFILE_FILE=raw),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(raw):
            raws.append(raw)
    prof = base + ".profdata"
    sh(["llvm-profdata", "merge", "-o", prof] + raws)
    for f in raws + [gso] + [c[:-2] + ".g.o" for c in cs] + [base + ".train" + x for x in (".repl26a",)]:
        if os.path.exists(f):
            os.remove(f)
    return prof


def wasm_for(bot):
    """The wasm a bot's cxe library is translated from (the CLI build if present, else a flip's own wasm, else built now)."""
    src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    w = os.path.join(PROJ, "bots", f"{name}-{tree_hash(os.path.join(src, 'src'))}", ".cambc", "build-release", "bot-injected.wasm")
    return w if os.path.exists(w) else (flip_wasm(src) or pilot_wasm(bot) or cli_build(bot))


def cli_bot_dir(bot):
    """The bot's private copy the CLI builds in PROJ: what CLI spot-checks run (built here if a background build hasn't)."""
    cli_build(bot)
    src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    return os.path.join(PROJ, "bots", f"{name}-{tree_hash(os.path.join(src, 'src'))}")


def wasm_of(bot, release=True):
    """The CLI-built WebAssembly of a bot: bot-injected.wasm (what runs) or bot.wasm (has the names); built here if needed."""
    cli_build(bot)
    src = bot if os.path.isdir(bot) else os.path.join(REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    bd = os.path.join(PROJ, "bots", f"{name}-{tree_hash(os.path.join(src, 'src'))}", ".cambc", "build-release")
    return os.path.join(bd, "bot-injected.wasm" if release else "bot.wasm")


def main():
    a = sys.argv[1:]
    exe = build_host()
    if a == ["--host"]:
        print(exe)
        return
    if a[:1] == ["--cli"]:  # the background CLI build of a flip (build_bot)
        print(cli_build(a[1]))
        return
    variant = "pgo" if "--pgo" in a else ""
    for bot in [x for x in a if not x.startswith("--")]:
        print(build_bot(bot, variant))


if __name__ == "__main__":
    main()
