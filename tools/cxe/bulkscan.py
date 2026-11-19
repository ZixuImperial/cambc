#!/usr/bin/env python3
"""bulkscan: byte-charged bulk-memory waste in a built bot (Tool Builder, 10 Nov; Rule Checker X139: a 148-byte struct copied per call, a
1620-byte {} zero-init per object, a 384-byte vec2 array zeroed; the function fuel profile can't show these as such).

Every memory.fill / memory.copy is charged per byte. In wasm the byte count is the op's last operand, so a constant size is the i32.const
right before it. This lists the sites with a constant size >= --min (128) bytes, per function (demangled), largest first.
usage: python3 -I tools/cxe/bulkscan.py WASM_OR_BOT [--min 128] [--diff BASE_WASM_OR_BOT] [--top 40]
  WASM_OR_BOT: a .wasm, or a bot name (its newest trunk build in /data/USER/trunkproj/wasm, else bots/NAME/.cambc/build-release/bot.wasm)
  --diff BASE: only the sites NEW in WASM v BASE (same function, size not seen there): what a trunk added.
Static count only: a site in a hot loop costs far more than one in setup; read the top rows with the fuel profile (fuelprof / lineprof).
Source lines need a line-table build (tools/cxe/lineprof.py, when present); this lists functions."""
import collections
import glob
import os
import re
import subprocess
import sys

SDK = "/data/USER/cambc-cache/wasi-sdk-33/bin"
OBJDUMP, CXXFILT = SDK + "/llvm-objdump", SDK + "/llvm-cxxfilt"


def wasm_of(x):
    if x.endswith(".wasm") and os.path.isfile(x):
        return x
    c = sorted(glob.glob(f"/data/USER/trunkproj/wasm/{x}-*.wasm"), key=os.path.getmtime)
    if c:
        return c[-1]
    p = f"/homes/USER/cambc/bots/{x}/.cambc/build-release/bot.wasm"
    if os.path.isfile(p):
        return p
    sys.exit(f"bulkscan: no wasm for {x} (pass a .wasm path)")


def sites(wasm, mn):
    """-> {function: [(op, size), ...]} for constant-size bulk ops >= mn bytes"""
    out = subprocess.run([OBJDUMP, "-d", wasm], capture_output=True, text=True, check=True).stdout
    fn, prev, res = "?", None, collections.defaultdict(list)
    for ln in out.splitlines():
        m = re.match(r"^[0-9a-f]+ <(.+)>:$", ln)
        if m:
            fn, prev = m.group(1), None
            continue
        m = re.search(r"\t(\S+)(?:\t(\S+))?\s*$", ln)
        if not m:
            continue
        op, arg = m.group(1), m.group(2)
        if op in ("memory.fill", "memory.copy") and prev and prev[0] == "i32.const":
            n = int(prev[1])
            if n >= mn:
                res[fn].append((op.split(".")[1], n))
        prev = (op, arg)
    return res


def demangle(names):
    names = list(names)
    if not names:
        return {}
    r = subprocess.run([CXXFILT], input="\n".join(names), capture_output=True, text=True)
    d = r.stdout.splitlines() if r.returncode == 0 else names
    return dict(zip(names, d if len(d) == len(names) else names))


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)

    def opt(k, d):
        return a[a.index(k) + 1] if k in a else d
    mn, top = int(opt("--min", 128)), int(opt("--top", 40))
    w = wasm_of(a[0])
    cur = sites(w, mn)
    title = f"bulkscan {os.path.basename(w)}: constant memory.fill/copy >= {mn} B"
    if "--diff" in a:
        bw = wasm_of(opt("--diff", ""))
        base = sites(bw, mn)
        cur = {f: [s for s in v if s not in base.get(f, [])] for f, v in cur.items()}
        cur = {f: v for f, v in cur.items() if v}
        title += f", NEW v {os.path.basename(bw)}"
    dm = demangle(cur)
    rows = sorted(cur.items(), key=lambda kv: -max(n for _, n in kv[1]))
    print(f"{title}: {sum(len(v) for v in cur.values())} sites in {len(cur)} functions")
    for f, v in rows[:top]:
        sz = ", ".join(f"{op} {n}" for op, n in sorted(v, key=lambda s: -s[1])[:6]) + (" ..." if len(v) > 6 else "")
        print(f"  {max(n for _, n in v):6d} B max  {len(v):3d} site(s)  {dm.get(f, f)[:110]}  [{sz}]")
    if len(rows) > top:
        print(f"  ... {len(rows) - top} more functions (--top)")


if __name__ == "__main__":
    main()
