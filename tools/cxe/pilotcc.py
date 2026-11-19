#!/usr/bin/env python3
"""pilotcc: compile a bot library's C parts on the Condor pilots with HOST's OWN clang (sc1, 6 Nov; owner: "make condor do more work that you
can offload"). The clang wave was the largest local cost of a new bot (~66 s CPU, 8 parts at ~8 s + the data part).

Identical code. Nodes never use their own compiler. stage() copies this machine's clang, every library it loads, its ld-linux and the system
headers the parts include to /homes (RT_HOME/cc-HASH, ~200 MB, ~101 files); nodes start `RT/ld-linux-x86-64.so.2 --library-path RT RT/clang -cc1 ARGS`.
ARGS are the cc1 line this machine's own driver prints for CFLAGS (`clang -###`), with only the include dirs moved under RT/inc. -cc1 is used so that no
driver probing (host CPU, gcc install, sysroot) happens on the node. Objects came back byte-identical to local ones (--selftest; report build_sc1_pilotcc.md).
Every batch re-proves it: each item also compiles the data part, a local compile of the same part is compared with it, and CXE_CC_AUDIT (0.1) of
batches also compile one code part locally. An item whose check differs is thrown away and the parts go local, with a PILOTCC MISMATCH line.

cxebuild.compile_all calls compile_parts(); parts it returns are done, the rest go down the usual local path, so any failure or timeout is only slower.
Off: CXE_CC_LOCAL=1. CXE_CC_MIN (2): with fewer parts to compile stay local (a data-only flip: one part, 0.7 s). CXE_CC_ITEMS (1): pilot items per build.
CXE_CC_PICKUP (25 s): no pilot started by then -> local. CXE_CC_WAIT (90 s): the whole budget. CXE_CC_AUDIT (0.1).
CLI: python3 -I tools/cxe/pilotcc.py --selftest [N]   N pilot items each compile every part of one wasm; all objects compared with local ones."""
import contextlib
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
RT_HOME = "/homes/USER/condor-runs/cxe"  # nodes read /homes, not /data
STAGE = "/homes/USER/condor-runs/stage"
MEMO = os.path.join(os.environ.get("CXE_ROOT", "/data/USER/st/cxe"), "pilotcc_stage.json")
LOGF = os.path.join(os.environ.get("CXE_ROOT", "/data/USER/st/cxe"), "pilotcc.log")
PRIO = 20
PART_HDR = '#include "w2c_rt.h"\n#include <stdlib.h>\n#include <stdio.h>\n'  # all the headers w2c.py's parts use (stdio: the profiling variants)
# 11 Nov (Builder/b1841: dbgso's shim failed on bits/types/once_flag.h and built locally, 400+ s): dbgshim.c defines _GNU_SOURCE, which
# pulls more headers; the bundle also packs what this stub includes
SHIM_HDR = '#define _GNU_SOURCE\n#include <stdint.h>\n#include <string.h>\n#include <stdlib.h>\n#include <stdio.h>\n#include <dlfcn.h>\n#include "w2c_rt.h"\n'


def _sig(paths):
    out = []
    for p in sorted(paths):
        s = os.stat(p)
        out.append([p, s.st_size, s.st_mtime_ns])
    return out


def _probe(cflags):
    """-> (clang path, {name: library path}, [header paths], cc1 args with @-marks). Three process starts, so only when the memo is stale."""
    drv = os.path.realpath(shutil.which("clang"))
    libs = {"ld-linux-x86-64.so.2": os.path.realpath("/lib64/ld-linux-x86-64.so.2")}
    for ln in subprocess.run(["ldd", drv], capture_output=True, text=True, check=True).stdout.splitlines():
        p = ln.split()
        if "=>" in p and len(p) > 2 and p[2].startswith("/"):
            libs[p[0]] = os.path.realpath(p[2])
    with tempfile.TemporaryDirectory() as d:
        stub = os.path.join(d, "part.c")
        with open(stub, "w") as f:
            f.write(PART_HDR)
        cmd = ["clang", "-fPIC"] + cflags + ["-c", stub, "-o", os.path.join(d, "part.o")]
        dep = subprocess.run(cmd[:-4] + ["-M", stub], capture_output=True, text=True, check=True).stdout
        stub2 = os.path.join(d, "shim.c")
        with open(stub2, "w") as f:
            f.write(SHIM_HDR)
        dep += " " + subprocess.run(cmd[:-4] + ["-M", stub2], capture_output=True, text=True, check=True).stdout.split(":", 1)[1]
        hdrs = sorted({os.path.normpath(x) for x in dep.replace("\\\n", " ").split()[1:] if x.endswith(".h") and x not in (stub, stub2)})
        line = subprocess.run(cmd + ["-###"], capture_output=True, text=True, check=True).stderr.strip().splitlines()[-1]
    a = [x.encode().decode("unicode_escape") for x in re.findall(r'"((?:[^"\\]|\\.)*)"', line)]
    if a[1] != "-cc1" or a[-1] != stub:
        raise RuntimeError(f"pilotcc: unexpected driver line {line[:200]}")
    a, out, i = a[2:-1], [], 0  # drop the program and the input; marks replace what names this file or this machine
    while i < len(a):
        k = a[i]
        v = a[i + 1] if i + 1 < len(a) else ""
        if k == "-main-file-name":
            out += [k, "@MAIN@"]
        elif k == "-o":
            out += [k, "@OUT@"]
        elif k in ("-internal-isystem", "-internal-externc-isystem"):
            out += [k, "@RT@/inc" + os.path.normpath(v)]
        elif k == "-resource-dir":
            out += [k, "@RT@/inc" + os.path.normpath(v)]
        elif k == "-I":
            out += [k, "."]  # the parts' own #include "w2c_rt.h" lies next to them
        else:
            out.append(re.sub(r"^(-f(debug|coverage)-compilation-dir=).*", r"\1/", k))  # debug info only, and we have none; local builds vary it too
            i -= 1
        i += 2
    return drv, libs, hdrs, out


def stage(cflags):
    """-> (rt dir, cc1 arg list). The bundle is reused while the files it was copied from are unchanged and all of it is still there."""
    want = " ".join(cflags[:-1]) + PART_HDR + SHIM_HDR
    try:
        with open(MEMO) as f:
            m = json.load(f)
        if m["flags"] == want and _sig(x[0] for x in m["src"]) == m["src"] and all(os.path.exists(os.path.join(m["rt"], n)) for n in m["files"]):
            os.utime(m["rt"])
            return m["rt"], m["args"]
    except (OSError, ValueError, KeyError):
        pass
    drv, libs, hdrs, args = _probe(cflags)
    hdrs = [h for h in hdrs if os.path.basename(h) != "w2c_rt.h"]  # goes with each batch (it is part of the OBJ key, and changes)
    src = {"clang": drv, **libs}
    src.update({"inc" + h: h for h in hdrs})
    h = hashlib.sha1(json.dumps(args).encode())
    for k in sorted(src):
        h.update(k.encode())
        with open(src[k], "rb") as f:
            h.update(f.read())
    rt = os.path.join(RT_HOME, "cc-" + h.hexdigest()[:12])
    if os.path.isdir(rt) and not all(os.path.exists(os.path.join(rt, k)) for k in src):
        shutil.rmtree(rt, ignore_errors=True)
    if not os.path.isdir(rt):
        tmp = f"{rt}.{os.getpid()}.tmp"
        for k, p in src.items():
            os.makedirs(os.path.dirname(os.path.join(tmp, k)), exist_ok=True)
            shutil.copyfile(p, os.path.join(tmp, k))  # not copy2: fresh dates (5 Nov: a cleanup took old-dated library copies)
            os.chmod(os.path.join(tmp, k), 0o755)
        try:
            os.replace(tmp, rt)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
    ccs = sorted((d for d in os.listdir(RT_HOME) if d.startswith("cc-") and not d.endswith(".tmp")), key=lambda d: os.path.getmtime(os.path.join(RT_HOME, d)))
    for d in ccs[:-2]:
        if os.path.join(RT_HOME, d) != rt:
            shutil.rmtree(os.path.join(RT_HOME, d), ignore_errors=True)
    tmp = f"{MEMO}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(dict(flags=want, rt=rt, args=args, src=_sig(src.values()), files=sorted(src)), f)
    os.replace(tmp, MEMO)
    return rt, args


def _quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _job(pd, i, rt, args, names, par):
    """Item i's script: compile each part in the pilot's scratch dir, then gzip it to the stage under ITEM.NAME.o.gz (a rename, so a name there is whole)."""
    cc = " ".join(_quote(x) if "@" not in x else '"' + x.replace("@RT@", "$RT").replace("@MAIN@", "$1.c").replace("@OUT@", "$PWD/$1.o") + '"' for x in args)
    sh = [f"RT={rt}", f"PD={pd}", f"I={i}",
          'hostname > "$PD/.h$I" && mv "$PD/.h$I" "$PD/started_$I"',
          'cp "$PD/w2c_rt.h" . || exit 1',
          "one() {",
          '  cp "$PD/$1.c" . || { echo copy > "$PD/$I.$1.err"; return; }',
          f'  if nice -n 10 "$RT/ld-linux-x86-64.so.2" --library-path "$RT" "$RT/clang" -cc1 {cc} "$1.c" 2> "$1.log"; then',
          '    gzip -1 -c "$1.o" > "$PD/.$I.$1" && mv "$PD/.$I.$1" "$PD/$I.$1.o.gz"',
          "  else",
          '    tail -c 2000 "$1.log" > "$PD/.$I.$1" ; mv "$PD/.$I.$1" "$PD/$I.$1.err"',
          "  fi",
          "}"]
    for k in range(0, len(names), par):
        sh += [f"one {n} &" for n in names[k:k + par]] + ["wait"]
    with open(f"{pd}/job_{i}.sh", "w") as f:
        f.write("\n".join(sh) + "\n")


def _log(msg):
    try:
        with open(LOGF, "a") as f:
            f.write(time.strftime("%FT%TZ ", time.gmtime()) + msg + "\n")
    except OSError:
        pass


def _unzip(p):
    with gzip.open(p, "rb") as f:
        return f.read()


def _local(c, out, cflags):
    """The same compile cxebuild does locally; out is any path (no name of it reaches the object)."""
    subprocess.run(["nice", "-n", "10", "clang", "-fPIC"] + cflags + ["-c", c, "-o", out], check=True, capture_output=True)
    with open(out, "rb") as f:
        return f.read()


def _prune():
    now = time.time()
    for d in os.listdir(STAGE):
        p = os.path.join(STAGE, d)
        try:
            if d.startswith("cc_") and now - os.path.getmtime(p) > 3600:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def use_pilots(n):
    """Worth a pilot? Not on request, not for few parts, not without a fresh manager and an idle pilot (the pickup then only delays a build)."""
    if os.environ.get("CXE_CC_LOCAL") == "1" or n < int(os.environ.get("CXE_CC_MIN", 2)):
        return False
    import pilotd as pl
    hb = pl.mtime(pl.q("pilotd.hb"))
    if hb is None or time.time() - hb > 300:
        return False
    pil = pl.alive_pilots()
    if any(p.get("item") is None and not p.get("retiring") for p in pil):
        return True
    # 9 Nov ~22:50Z (owner: raise the build-agent cap, offload more to Condor): with the local load high and a working pool, compile on the pilots
    # anyway (its items go near the front of the queue, so a pilot takes one within ~a minute) instead of adding clang processes here
    try:
        hi = os.getloadavg()[0] > float(os.environ.get("CXE_CC_OFFLOAD_LOAD", "20"))
    except OSError:
        hi = False
    return hi and len(pil) >= int(os.environ.get("CXE_CC_OFFLOAD_PILOTS", "20"))


def _err(msg):
    print(msg, file=sys.stderr, flush=True)  # not stdout: callers of `cxebuild.py BOT` read the library path there


def compile_parts(parts, data, cflags, say=_err, items=None, slot=contextlib.nullcontext):
    """parts: .c paths to compile; data: a small part used as every item's check. On return the parts in the result have their .o beside the .c, each from
    an item whose check matched. Never raises for a pilot's sake."""
    t0 = time.time()
    import pilotd as pl
    pd, bid, done, th = None, None, [], None
    try:
        rt, args = stage(cflags)
        os.makedirs(STAGE, exist_ok=True)
        _prune()
        pd = tempfile.mkdtemp(prefix=f"cc_{os.getpid()}_", dir=STAGE)
        os.chmod(pd, 0o755)
        nm = lambda c: os.path.basename(c)[:-2]  # noqa: E731
        by = {nm(c): c for c in parts}
        by[nm(data)] = data
        n_it = max(1, min(items or int(os.environ.get("CXE_CC_ITEMS", 1)), len(parts)))
        code = [c for c in parts if c != data]
        audit = random.choice(code) if code and random.random() < float(os.environ.get("CXE_CC_AUDIT", 0.1)) else None
        lots = [[nm(data)] + [nm(c) for c in code[i::n_it]] for i in range(n_it)]
        for c in by.values():
            shutil.copyfile(c, os.path.join(pd, os.path.basename(c)))
        shutil.copyfile(os.path.join(HERE, "w2c_rt.h"), f"{pd}/w2c_rt.h")
        rows = []
        for i, names in enumerate(lots):
            _job(pd, i, rt, args, names, 16)
            rows.append((i, [f"run:{pd}/job_{i}.sh", 12]))
        pl.demand()
        bid = pl.enqueue(pd, rows, PRIO)
        checks = {}  # part name -> local bytes
        def chk():
            for c in [data] + ([audit] if audit else []):
                try:
                    with slot():
                        checks[nm(c)] = _local(c, c[:-2] + ".chk.o", cflags)
                    os.remove(c[:-2] + ".chk.o")
                except (subprocess.CalledProcessError, OSError):
                    checks[nm(c)] = None
        th = threading.Thread(target=chk, daemon=True)
        th.start()
        pickup, wait = float(os.environ.get("CXE_CC_PICKUP", 25)), float(os.environ.get("CXE_CC_WAIT", 90))
        hosts, reason = {}, "ok"
        back = lambda s: [f"{i}.{n}" for i, ns in enumerate(lots) for n in ns if f"{i}.{n}{s}" in seen]  # noqa: E731
        while True:
            seen = set(pl.ls(pd))
            for i in range(n_it):
                if f"started_{i}" in seen and i not in hosts:
                    hosts[i] = open(f"{pd}/started_{i}").read().strip()
            errs = back(".err")
            if len(back(".o.gz")) + len(errs) >= sum(map(len, lots)):
                break
            el = time.time() - t0
            if len(hosts) < n_it and el > pickup:
                reason = f"{n_it - len(hosts)} of {n_it} items not started in {pickup:.0f} s"
                break
            if el > wait:
                reason = f"not done in {wait:.0f} s"
                break
            time.sleep(1)
        t_back = time.time() - t0
        th.join()
        seen = set(pl.ls(pd))
        ok_items = []
        for i, names in enumerate(lots):
            good = f"{i}.{nm(data)}.o.gz" in seen and checks.get(nm(data)) and _unzip(f"{pd}/{i}.{nm(data)}.o.gz") == checks[nm(data)]
            if good and audit and nm(audit) in names and f"{i}.{nm(audit)}.o.gz" in seen and checks.get(nm(audit)):
                good = _unzip(f"{pd}/{i}.{nm(audit)}.o.gz") == checks[nm(audit)]
            if good:
                ok_items.append(i)
            elif f"{i}.{nm(data)}.o.gz" in seen:
                msg = f"PILOTCC MISMATCH item {i} on {hosts.get(i)}: a check object differs from the local one, its parts go local (rt {rt})"
                say("pilotcc: " + msg)
                _log(msg)
        for i in ok_items:
            for n in lots[i]:
                p = f"{pd}/{i}.{n}.o.gz"
                if n in by and by[n] in parts and by[n] not in done and f"{i}.{n}.o.gz" in seen:
                    b = _unzip(p)
                    if b[:4] != b"\x7fELF":
                        continue
                    tmp = f"{by[n][:-2]}.o.{os.getpid()}"
                    with open(tmp, "wb") as f:
                        f.write(b)
                    os.replace(tmp, by[n][:-2] + ".o")
                    done.append(by[n])
        for e in sorted(x for x in seen if x.endswith(".err"))[:1]:
            reason = f"{e}: " + open(f"{pd}/{e}", errors="replace").read()[-300:].replace("\n", " ")
        line = (f"{len(done)} of {len(parts)} parts on {','.join(sorted(set(hosts.values()))) or 'no pilot'} in {t_back:.0f} s"
                f" ({n_it} items, checked {'data+code' if audit else 'data'}): {reason}")
        say("pilotcc: " + line)
        _log(line)
        return done
    except Exception as e:  # noqa: BLE001  a pilot problem must never fail a build
        say(f"pilotcc: {type(e).__name__}: {str(e)[:200]}; compiling locally")
        _log(f"error {type(e).__name__}: {str(e)[:200]}")
        return [c for c in done if os.path.exists(c[:-2] + ".o")]
    finally:
        try:
            if bid and len(done) < len(parts):
                pl.cancel(bid)
        except Exception:  # noqa: BLE001
            pass
        if th:
            th.join()  # its .chk.o must not outlive the build's own clean-up
        if pd:
            shutil.rmtree(pd, ignore_errors=True)


def selftest(n, d):
    """N pilot items each compile every part in d (X.0.c ... X.data.c, made by w2c.py); each object is compared with a local compile of the same .c."""
    import glob
    import pilotd as pl
    import cxebuild
    cf = cxebuild.CFLAGS
    cs = sorted(glob.glob(f"{d}/*.c"))
    rt, args = stage(cf)
    print(f"selftest: rt {rt}, {len(cs)} parts, {n} items")
    ref = {}
    for c in cs:
        p = c[:-2] + ".ref.o"
        if not os.path.exists(p):
            subprocess.run(["nice", "-n", "19", "clang", "-fPIC"] + cf + ["-c", c, "-o", p], check=True)
        ref[os.path.basename(c)[:-2]] = open(p, "rb").read()
    pd = tempfile.mkdtemp(prefix=f"cc_{os.getpid()}_", dir=STAGE)
    os.chmod(pd, 0o755)
    try:
        for c in cs:
            shutil.copyfile(c, os.path.join(pd, os.path.basename(c)))
        shutil.copyfile(os.path.join(HERE, "w2c_rt.h"), f"{pd}/w2c_rt.h")
        rows = []
        for i in range(n):
            _job(pd, i, rt, args, list(ref), 16)
            rows.append((i, [f"run:{pd}/job_{i}.sh", 12]))
        pl.demand()
        t0 = time.time()
        pl.enqueue(pd, rows, PRIO)
        while time.time() - t0 < 600:
            seen = set(pl.ls(pd))
            if sum(f"{i}.{m}{e}" in seen for i in range(n) for m in ref for e in (".o.gz", ".err")) >= n * len(ref):
                break
            time.sleep(2)
        print(f"selftest: {time.time() - t0:.0f} s")
        bad = 0
        for i in range(n):
            h = open(f"{pd}/started_{i}").read().strip() if f"started_{i}" in seen else "?"
            same = [m for m in ref if f"{i}.{m}.o.gz" in seen and _unzip(f"{pd}/{i}.{m}.o.gz") == ref[m]]
            errs = [open(f"{pd}/{i}.{m}.err", errors="replace").read()[-200:] for m in ref if f"{i}.{m}.err" in seen]
            print(f"  item {i} on {h}: {len(same)}/{len(ref)} byte-identical {errs[:1] or ''}")
            bad += len(same) != len(ref)
        return 1 if bad else 0
    finally:
        shutil.rmtree(pd, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.path.insert(0, HERE)
        sys.exit(selftest(int(sys.argv[2]) if len(sys.argv) > 2 else 4, sys.argv[3] if len(sys.argv) > 3 else "/data/USER/st/sc1/ref"))
    sys.exit(__doc__)
