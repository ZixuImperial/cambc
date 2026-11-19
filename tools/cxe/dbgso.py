"""dbgso: a cxe library of a bot's DEBUG build, for diag copies whose DG records need debug (primer RULE CXE-DIAG; b1137's tool,
adopted 4 Nov). The CLI's debug build (no --release) of the bot's src, translated with fuel like any cxe bot, every part the
translator writes compiled (glob, so translator changes such as the separate data part can't break it), plus dbgshim.c for the
debug build's fuel_pause/resume/adjust imports. Run the games with CXE_STDOUT=1: the records land in OUT.team-X.stdout.
usage: python3 -I tools/cxe/dbgso.py BOT  -> prints the .so path (/data/USER/st/cxe/dbg/BOT-<wasm sha>.so; rebuilt when the wasm changes)"""
import fcntl
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild as cb  # noqa: E402


def pilot_debug_wasm(src, name, th):
    """7 Nov (Builder: diag builds waited 10-30 min behind the local build gate): the CLI's debug build on a pilot (tools/lab/pilotbuild.py
    --debug) -> path, cached by source; None: no pilot built it (the caller builds locally, which also shows a compile error). DBGSO_LOCAL=1: local."""
    if os.environ.get("DBGSO_LOCAL") == "1":
        return None
    if os.path.realpath(os.path.dirname(os.path.normpath(src))) != os.path.realpath(os.path.join(cb.REPO, "bots")):
        return None  # pilotbuild packs bots/NAME/src
    out = os.path.join(cb.PROJ, "pilotwasm", f"dbg_{name}-{th}.wasm")
    if os.path.exists(out):
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.exists(out):
            r = subprocess.run([sys.executable, "-I", os.path.join(cb.REPO, "tools/lab/pilotbuild.py"), name, out, "--debug"], capture_output=True)
            if r.returncode or not os.path.exists(out) or not cb.has_wasm_magic(out):
                return None
    return out


def build(bot):
    src = bot if os.path.isdir(bot) else os.path.join(cb.REPO, "bots", bot)
    name = os.path.basename(os.path.normpath(src))
    th = cb.tree_hash(os.path.join(src, 'src'))
    bd = os.path.join(cb.PROJ, "bots", f"dbg_{name}-{th}")
    wasm = os.path.join(bd, ".cambc", "build", "bot-injected.wasm")
    if not os.path.exists(wasm):
        wasm = pilot_debug_wasm(src, name, th) or wasm
    if not os.path.exists(wasm) and not os.path.isdir(bd):
        tmp = f"{bd}.tmp{os.getpid()}"
        shutil.copytree(os.path.join(src, "src"), os.path.join(tmp, "src"))
        os.replace(tmp, bd)
    if not os.path.exists(wasm):
        env = dict(os.environ, CAMBC_WASMTIME_CACHE=os.environ.get("CAMBC_WASMTIME_CACHE", "/data/USER/wtcache"))
        with cb.build_slot():
            # 11 Nov (Combat: "cmake build failed" with no compiler output; the error was a DG line's unqualified name): keep the
            # build's output and print its error lines on failure
            r = subprocess.run(["nice", "-n", "10", cb.CLI, "build", os.path.relpath(bd, cb.PROJ)], cwd=cb.PROJ, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if r.returncode:
                errs = [ln for ln in r.stdout.splitlines() if re.search(r"error|undefined|fatal", ln, re.I)]
                sys.stderr.write("\n".join(errs[-12:] or r.stdout.splitlines()[-12:]) + "\n")
                raise subprocess.CalledProcessError(r.returncode, r.args)
    h = hashlib.sha256(open(wasm, "rb").read())
    for p in ("w2c.py", "w2c_rt.h", "wasmparse.py", "dbgshim.c"):
        h.update(open(os.path.join(HERE, p), "rb").read())
    out = os.path.join(cb.ROOT, "dbg")
    os.makedirs(out, exist_ok=True)
    so = os.path.join(out, f"{name}-{h.hexdigest()[:12]}.so")
    if os.path.exists(so):
        return so
    base = os.path.join(out, f".{name}.{os.getpid()}")
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "w2c.py"), wasm, base + ".c", "--prefix", "bot", "--fuel", "--split", str(cb.SPLIT)],
                   check=True)
    shutil.copyfile(os.path.join(HERE, "dbgshim.c"), base + ".shim.c")
    cs = sorted(glob.glob(base + ".*.c"))
    objs = [c[:-2] + ".o" for c in cs]
    left = cs
    if os.environ.get("DBGSO_LOCAL") != "1":  # 7 Nov: the parts compile on a pilot (tools/cxe/pilotcc.py, this machine's clang, each batch checked)
        try:
            import pilotcc
            if pilotcc.use_pilots(len(cs)):
                data = base + ".data.c" if os.path.exists(base + ".data.c") else cs[-1]
                got = pilotcc.compile_parts(cs, data, cb.CFLAGS)
                left = [c for c in cs if c not in got or not os.path.exists(c[:-2] + ".o")]
        except Exception as e:  # noqa: BLE001  local below
            print(f"dbgso: pilot compile failed ({str(e)[:120]}): local", file=sys.stderr)
    ps = [subprocess.Popen(["nice", "-n", "10", "clang", "-fPIC"] + cb.CFLAGS + ["-c", c, "-o", c[:-2] + ".o"]) for c in left]
    if not all(p.wait() == 0 for p in ps):
        sys.exit("dbgso: compile failed")
    subprocess.run(["clang", "-shared", "-Wl,-Bsymbolic-functions", "-o", so + ".tmp"] + objs, check=True)  # dbgshim's fuel_remaining binds
    miss = cb.missing_imports(so + ".tmp")  # 11 Nov (TB 6ad907: b1843's diag used board_ally_ward_occupancy, 300/300 games came back missing)
    if miss:
        os.remove(so + ".tmp")
        sys.exit(f"dbgso: {name} uses engine imports cxe does not implement yet: {', '.join(miss)} (dgkit falls back to the CLI; "
                 f"ask the Tool builder to add them)")
    os.replace(so + ".tmp", so)
    for f in glob.glob(base + ".*"):
        os.remove(f)
    return so


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(sys.argv[1]))
