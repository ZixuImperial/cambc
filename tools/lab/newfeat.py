#!/usr/bin/env python3
"""newfeat: a new feature in its own files behind its own flag, in one command (Builder 7 Nov, owner: faster builds; primer RULE OWN-FILE:
a feature's code goes in src/feat_NAME.cpp/.h, shared files get only a flag-first hook line).

usage: python3 -I tools/lab/newfeat.py BASE NAME FLAG [--bits N] [--bot NEW]
  NEW (default nova_feat_NAME) = newbot.sh copy of BASE, plus
    src/feat_NAME.h   #define FLAG_BITS 0, inline const volatile int FLAG_TAB[2] = { MAGIC, FLAG_BITS } (a unique slot-0 magic),
                      #define FLAG_ON(b), and the namespace nova::feat::NAME with one function to fill in
    src/feat_NAME.cpp the unity-guarded body (econ, combat, move ... come first in nova_all.cpp, so their helpers are in scope)
    nova_all.cpp      re-made by tools/lab/mkunity.sh (the new file at the end; unity_order.txt, when the bot has one, gets it too)
  then prints the hook to paste where the feature acts: the #include and `if (FLAG_ON(1) && nova::feat::NAME::fn(...))`.
  FLAG is the stem (e.g. CTK: CTK_BITS, CTK_TAB, CTK_ON); --bits N documents how many bits the flag word uses (default 1).
usage: python3 -I tools/lab/newfeat.py check BOT BASE [--maps 20]
  one verdict before arming: (1) flip.py check of every new flag at 1 (data-only: defined once, read only in its table),
  (2) shipcheck's base_check_lines(BOT, BASE): every line BOT changes in BASE's files sits behind a switch (new files are free),
  (3) cxeident BASE BOT --maps N (N x 2 seats): flag 0 plays exactly as BASE. Prints PASS or FAIL per step and overall.
Then: tools/lab/firecount.py BOT "FLAG_BITS=1" for a firing count, then armq.py add.
"""
import os
import re
import subprocess
import sys

REPO = "/homes/zw4424/cambc"
LAB = f"{REPO}/tools/lab"
sys.path.insert(0, LAB)
MAGIC_RE = re.compile(r"inline\s+(?:const\s+)?(?:constexpr\s+)?(?:volatile\s+)?int\s+\w+_TAB\s*\[[^\]]*\]\s*=\s*\{\s*(0x[0-9A-Fa-f]+)")


def die(msg, code=2):
    print(f"newfeat: {msg}", file=sys.stderr)
    sys.exit(code)


def src_of(bot):
    return os.path.join(os.path.realpath(os.path.join(REPO, "bots", bot)), "src")


def used_magics(src):
    out = set()
    for f in os.listdir(src):
        if f.endswith((".h", ".cpp", ".cc")):
            out |= {int(m, 16) for m in MAGIC_RE.findall(open(os.path.join(src, f), errors="replace").read())}
    return out


def magic_for(flag, used):
    b = (flag.upper() + "1111")[:4].encode()
    m = int.from_bytes(b, "big")
    while m in used:
        m = (m + 1) & 0xFFFFFFFF
    return m


def make(a):
    if len(a) < 3:
        die(__doc__)
    base, name, flag = a[0], a[1], a[2]
    bits = int(a[a.index("--bits") + 1]) if "--bits" in a else 1  # new layout: --module econ|combat|brain|move|draft|plan|common names the flags header
    new = a[a.index("--bot") + 1] if "--bot" in a else f"nova_feat_{name}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        die("NAME: lower-case letters, digits and _ (it names src/feat_NAME.*)")
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", flag):
        die("FLAG: the stem in capitals, e.g. CTK (gives CTK_BITS, CTK_TAB, CTK_ON)")
    if not os.path.isdir(src_of(base)):
        die(f"no bot {base}")
    bsrc = src_of(base)
    for f in os.listdir(bsrc):
        if f.endswith((".h", ".cpp", ".cc")) and re.search(rf"\b{flag}_(BITS|TAB|ON)\b", open(os.path.join(bsrc, f), errors="replace").read()):
            die(f"{flag}_BITS/_TAB/_ON already exist in {base} ({f}): pick another stem")
    if os.path.exists(os.path.join(bsrc, f"feat_{name}.cpp")):
        die(f"{base} already has feat_{name}.cpp")
    r = subprocess.run(["sh", f"{LAB}/newbot.sh", base, new], capture_output=True, text=True, cwd=REPO)
    if r.returncode:
        die(f"newbot.sh: {(r.stdout + r.stderr).strip()[-300:]}", 1)
    src = src_of(new)
    mg = magic_for(flag, used_magics(src))
    if os.path.exists(os.path.join(src, "brain_turn.cc")):  # new layout (8 Nov, owner): no feature files; the code goes in the module that owns the decision
        mod = a[a.index("--module") + 1] if "--module" in a else "common"
        p = os.path.join(src, f"{mod}_flags.h")
        if not os.path.exists(p):
            die(f"no {mod}_flags.h: --module is one of econ, combat, brain, move, draft, plan, common")
        with open(p, "a") as g:
            g.write(f"""
// {flag} ({name}): <one line: what it does, and the spec or replay it comes from>. 0 = {base}. Bits ({bits}): 1 = <...>.
#define {flag}_BITS 0
inline const volatile int {flag}_TAB[2] = {{ 0x{mg:08X}, {flag}_BITS }}; // slot 0 magic keeps it out of .bss
#define {flag}_ON(b) (({flag}_TAB[1] & (b)) != 0)
""")
        print(f"bots/{new} = {base} + {flag}_BITS 0 in {mod}_flags.h (magic 0x{mg:08X}). Write the code in the file that owns the decision (docs/code-map.md), flag first: if ({flag}_ON(1) && ...)")
        print(f"next: python3 -I tools/lab/newfeat.py check {new} {base}; python3 -I tools/lab/armq.py add {new}:{base} \"{flag}_BITS=1\" fix|behaviour \"type(area): summary\"")
        return 0
    open(os.path.join(src, f"feat_{name}.h"), "w").write(f"""#pragma once
// feat_{name} ({flag}): <one line: what it does, and the spec or replay it comes from>. Flag {flag}_BITS, 0 = {base}.
// Bits ({bits}): 1 = <...>. Hook: `if ({flag}_ON(1) && nova::feat::{name}::act(...))` where the feature acts (flag first: 0 does no work).
#include "common.h"
#define {flag}_BITS 0
inline const volatile int {flag}_TAB[2] = {{ 0x{mg:08X}, {flag}_BITS }}; // slot 0 magic keeps it out of .bss
#define {flag}_ON(b) (({flag}_TAB[1] & (b)) != 0)
namespace nova::feat::{name}
{{
// True when the feature acted this turn (the caller then skips its own move). Change the arguments to what it needs.
bool act(int gi);
}} // namespace nova::feat::{name}
""")
    open(os.path.join(src, f"feat_{name}.cpp"), "w").write(f"""// feat_{name}.cpp ({flag}): the feature's code. Unity build: compiled only through nova_all.cpp, after the files before it,
// whose helpers are in scope. Only reached when {flag}_ON(...) is true at the hook.
#include "feat_{name}.h"
namespace nova::feat::{name}
{{
bool act(int gi)
{{
	(void)gi;
	return false;
}}
}} // namespace nova::feat::{name}
""")
    uo = os.path.join(src, "unity_order.txt")
    if os.path.exists(uo):
        open(uo, "a").write(f"feat_{name}.cpp\n")
    r = subprocess.run(["sh", f"{LAB}/mkunity.sh", src], capture_output=True, text=True)
    if r.returncode or f'#include "feat_{name}.cpp"' not in open(os.path.join(src, "nova_all.cpp")).read():
        die(f"mkunity.sh did not register feat_{name}.cpp: {(r.stdout + r.stderr).strip()[-300:]}", 1)
    print(f"bots/{new} = {base} + src/feat_{name}.h/.cpp ({flag}_BITS 0, {flag}_TAB magic 0x{mg:08X}), registered in nova_all.cpp"
          + (" and unity_order.txt" if os.path.exists(uo) else ""))
    print(f"""hook (paste where the feature acts; the include near the file's other includes):
    #include "feat_{name}.h" // {flag}
    if ({flag}_ON(1) && nova::feat::{name}::act(gi))
        return; // or whatever skips the old path
next: fill feat_{name}.cpp, then
    python3 -I tools/lab/newfeat.py check {new} {base}
    python3 -I tools/lab/firecount.py {new} "{flag}_BITS=1"
    python3 -I tools/lab/armq.py add {new}:{base} "{flag}_BITS=1" fix|behaviour "type(area): summary\"""")
    return 0


def new_flags(bot, base):
    """flag stems whose X_BITS #define is in BOT and not in BASE"""
    def defs(b):
        out = set()
        for f in os.listdir(src_of(b)):
            if f.endswith((".h", ".cpp", ".cc")):
                out |= set(re.findall(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*)_BITS\s+-?\d+", open(os.path.join(src_of(b), f), errors="replace").read(), re.M))
        return out
    return sorted(defs(bot) - defs(base))


def check(a):
    if len(a) < 2:
        die(__doc__)
    bot, base = a[0], a[1]
    maps = a[a.index("--maps") + 1] if "--maps" in a else "20"
    ok_all = True
    fl = new_flags(bot, base)
    for f in fl:
        r = subprocess.run([sys.executable, "-I", f"{LAB}/flip.py", "check", src_of(bot), f"{f}_BITS=1"], capture_output=True, text=True)
        ok = r.returncode == 0
        ok_all &= ok
        print(f"{'PASS' if ok else 'FAIL'}  flip check {f}_BITS=1 (data-only flag)" + ("" if ok else f": {(r.stdout + r.stderr).strip()[-200:]}"))
    if not fl:
        print("note  no new X_BITS flag found in BOT (a code-only change?)")
    sys.argv = ["shipcheck.py"]
    import shipcheck
    ok, why = shipcheck.base_check_lines(bot, base, None)
    ok_all &= ok
    print(f"{'PASS' if ok else 'FAIL'}  base check v {base}: {why[:300]}")
    r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", base, bot, "--maps", maps, "--seed", "1"],
                       capture_output=True, text=True)
    tail = [x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip()]
    ok = r.returncode == 0
    ok_all &= ok
    print(f"{'PASS' if ok else 'FAIL'}  identity at flag 0 (cxeident {maps} maps x 2 seats): " + " | ".join(tail[-2:])[:300])
    print(f"OVERALL: {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "check":
        return check(a[1:])
    return make(a)


if __name__ == "__main__":
    sys.exit(main())
