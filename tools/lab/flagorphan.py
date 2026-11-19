#!/usr/bin/env python3
"""flagorphan: which runtime flag tables a refactor orphaned (Tool builder 2, 7 Nov; Builder: the rf4 refactor (v590, "same play")
dropped the prism::pg9_turn() call, so PG9_BITS became dead code and its table went constexpr. Identity tests can't see this: at
flag 0 the call did nothing, so a bank entry, reopen candidate or replaycheck fix on that flag would silently read as inert).

usage: python3 -I tools/lab/flagorphan.py BASE CAND [--all] [--json OUT]
Reads the COMPILED release wasm of both bots (what plays), not the C++: the linker drops every function nothing calls, so a feature
whose caller a refactor removed leaves no code that touches its table. Per flag table X_TAB (inline ... volatile int X_TAB[n] =
{ 0xMAGIC, ... } in the source; the magic locates the table in the data segment):
  refs     instructions whose constant address (i32.const, a load/store offset, or i32.const + offset) falls in the table, and the
           number of functions holding them, in BASE and CAND
  ORPHANED BASE's code reads the table and CAND's never does, though the table is still in CAND's data (a flip there does nothing)
  BAKED-0  volatile in BASE, not volatile (constexpr / const / gone) in CAND while BASE's value is 0: a flag-off feature folded away
  BAKED    volatile in BASE, not volatile in CAND at a non-zero value (play kept at that value; the flag can no longer be flipped)
  GONE     volatile in BASE, no declaration in CAND at all
  FEWER    CAND reads it from fewer functions than BASE (listed with --all; a merge of two readers is normal, a lost one is not)
Source pass, EVERY table (constexpr too; name-based call graph from main(), so a shared name can hide a dead reader, never invent one):
  UNREACHED       CAND still has readers of the table, but none is called (BASE had called ones)
  PART-UNREACHED  some of CAND's readers lost every caller (PG9 in rf4: pg9_turn kept, its call dropped); 'lost' names them
  REMOVED-0       no reader left in CAND and the value is 0: the flag-off feature was deleted (a flip or bank entry can't revive it)
  FOLDED          no reader left, value non-zero: folded in at its value (fine if identity holds; --all lists them)
  READER-LOST     a BASE reader no longer reads it while others still do (mostly functions split by the refactor; --all)
Exit 0 when nothing is ORPHANED, UNREACHED, PART-UNREACHED, REMOVED-0, BAKED-0 or GONE, 1 otherwise. Builds a missing release wasm through tools/cxe/cxebuild.wasm_for.
"""
import json
import os
import re
import struct
import sys

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, REPO + "/tools/cxe")
import cxebuild  # noqa: E402
import wasmparse  # noqa: E402

DEFINE = re.compile(r"^\s*#\s*define\s+(\w+)\s+\(?\s*(-?\d+)\s*\)?\s*(?://.*)?$", re.M)
DECL = re.compile(r"inline\s+((?:const\s+|constexpr\s+|volatile\s+)*)int\s+(\w+_TAB)\s*\[\s*(\w*)\s*\]\s*=\s*\{\s*(0x[0-9A-Fa-f]+)")


def src_tables(bot):
    """{NAME_TAB: dict(magic, volatile)} from the bot's sources."""
    d = os.path.join(REPO, "bots", bot, "src") if not os.path.isdir(bot) else os.path.join(bot, "src")
    out, defs, second = {}, {}, {}
    for f in sorted(os.listdir(d)):
        if f.endswith((".h", ".cpp", ".cc")):
            txt = open(os.path.join(d, f), errors="replace").read()
            defs.update({m.group(1): int(m.group(2)) for m in DEFINE.finditer(txt)})
            for m in DECL.finditer(txt):
                out[m.group(2)] = dict(magic=int(m.group(4), 16), volatile="volatile" in m.group(1), file=f, size=int(m.group(3)) if m.group(3).isdigit() else 2)
                v = re.match(r"\s*,\s*([\w-]+)", txt[m.end():])
                second[m.group(2)] = v.group(1) if v else None
    for t, v in second.items():  # the table's value (slot 1) from the source: a number or a #define
        out[t]["value"] = int(v) if v and re.fullmatch(r"-?\d+", v) else defs.get(v)
    return out


def wasm_refs(bot, tabs):
    """{NAME_TAB: dict(addr, value, refs, funcs)} for the tables found in the wasm's data by their magic."""
    w = cxebuild.wasm_for(bot)
    mod = wasmparse.Module(w)
    mem = []  # (start, bytes)
    for kind, off, b in mod.datas:
        off = off[1] if isinstance(off, tuple) else off  # wasmparse gives ('i32', value)
        if kind == "active" and isinstance(off, int):
            mem.append((off, b))
    where = {}
    for name, t in tabs.items():
        key = struct.pack("<I", t["magic"])
        for start, b in mem:
            i = b.find(key)
            while i >= 0:
                if i % 4 == 0:
                    val = struct.unpack("<i", b[i + 4:i + 8])[0] if i + 8 <= len(b) else None
                    where[name] = dict(addr=start + i, value=val)
                    break
                i = b.find(key, i + 1)
            if name in where:
                break
    # every constant address in code: i32.const values, memarg offsets, and i32.const + the next access's offset
    spans = sorted((v["addr"], v["addr"] + 4 * tabs[n]["size"], n) for n, v in where.items())  # each table's own bytes
    hits = {n: [0, set()] for n in where}
    import bisect
    starts = [s[0] for s in spans]

    def mark(a, fi):
        k = bisect.bisect_right(starts, a) - 1
        if k >= 0 and spans[k][0] <= a < spans[k][1]:
            h = hits[spans[k][2]]
            h[0] += 1
            h[1].add(fi)
    for fi in range(len(mod.bodies)):
        _, ins = mod.body(fi)
        last = None
        for name, imm in ins:
            if name == "i32.const":
                mark(imm & 0xffffffff, fi)
                last = imm & 0xffffffff
                continue
            if isinstance(imm, tuple) and len(imm) == 3 and ("load" in name or "store" in name):
                off = imm[1]
                if off:
                    mark(off, fi)
                    if last is not None:
                        mark(last + off, fi)
            last = None
    for n in where:
        where[n]["refs"], where[n]["funcs"] = hits[n][0], len(hits[n][1])
    return where


def src_reach(bot, names):
    """Source pass (every table, volatile or constexpr): {NAME_TAB: (reachable reader functions, all reader functions)}. A reader is a
    function whose code names the table or a macro over it; reachable = called, by name, on some chain from main() or from code
    outside any function (initialisers). Name-based, so a shared name can make a dead reader look reachable (misses, never false alarms)."""
    sys.path.insert(0, REPO + "/tools/lab")
    import codeindex
    d = os.path.join(REPO, "bots", bot, "src") if not os.path.isdir(bot) else os.path.join(bot, "src")
    tok = re.compile(r"[A-Za-z_]\w*")
    proto = re.compile(r"^[\w:<>\*&,\s]+\b(\w+)\s*\([^;{]*\)\s*(const)?\s*(noexcept)?\s*;")
    funcs, outside, macros = [], set(), {}
    for f in sorted(os.listdir(d)):
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        path = os.path.join(d, f)
        lines = [codeindex.code(x) for x in open(path, errors="replace").read().split("\n")]
        for m in re.finditer(r"^\s*#\s*define\s+(\w+)\s*\(.*", "\n".join(lines), re.M):
            for t in names:
                if re.search(r"\b" + t + r"\b", m.group(0)):
                    macros.setdefault(t, set()).add(m.group(1))
        inside = [False] * (len(lines) + 2)
        for a, b, ns, name, sig, _ in codeindex.index_file(path):
            body = lines[a - 1:b]
            nm = re.sub(r"__attribute__\s*\(\(.*?\)\)\s*", "", sig).split("(")[0].split()
            funcs.append(((nm[-1] if nm else name).split("::")[-1], set(tok.findall("\n".join(body[1:])))))
            for k in range(a - 1, b):
                inside[k] = True
        for k, ln in enumerate(lines):
            if not inside[k] and not ln.lstrip().startswith("#") and not proto.match(ln.strip()):
                outside |= set(tok.findall(ln))
    fnames = {n for n, _ in funcs}
    uses = {}
    for n, toks in funcs:
        uses.setdefault(n, set()).update(toks & fnames)
    seen, todo = set(), ["main"] + sorted(outside & fnames)
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo += [x for x in uses.get(n, ()) if x not in seen]
    out = {}
    for t in names:
        keys = {t} | macros.get(t, set())
        rd = {n for n, toks in funcs if toks & keys}
        out[t] = (sorted(rd & seen), sorted(rd))
    return out


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    base, cand = a[0], a[1]
    tb, tc = src_tables(base), src_tables(cand)
    wb = wasm_refs(base, {k: v for k, v in tb.items() if v["volatile"]})
    wc = wasm_refs(cand, {k: v for k, v in tc.items() if v["volatile"]})
    rows, bad = [], 0
    for n in sorted(k for k, v in tb.items() if v["volatile"]):
        b = wb.get(n, {})
        c = wc.get(n)
        val = b.get("value")
        if n not in tc:
            st = "GONE"
        elif not tc[n]["volatile"]:
            st = "BAKED-0" if not val else "BAKED"
        elif c is None:
            st = "NOT-IN-DATA"
        elif b.get("refs", 0) > 0 and c["refs"] == 0:
            st = "ORPHANED"
        elif c["funcs"] < b.get("funcs", 0):
            st = "FEWER"
        else:
            st = "ok"
        if st in ("ORPHANED", "BAKED-0", "GONE"):
            bad += 1
        rows.append(dict(table=n, status=st, base_value=val, base_refs=b.get("refs"), base_funcs=b.get("funcs"),
                         cand_refs=(c or {}).get("refs"), cand_funcs=(c or {}).get("funcs"), file=tb[n]["file"]))
    # source pass over EVERY table (constexpr ones too: PG9 was constexpr at 0 when rf4 dropped its caller, invisible in the wasm)
    allt = sorted(set(tb) & set(tc))
    rb, rc = src_reach(base, allt), src_reach(cand, allt)
    for n in allt:
        lost = [f for f in rb[n][0] if f not in rc[n][0]]
        val = tc[n].get("value")
        dead = [f for f in rc[n][1] if f not in rc[n][0] and f not in (set(rb[n][1]) - set(rb[n][0]))]  # uncalled in CAND, not already dead in BASE
        if rb[n][0] and not rc[n][0] and rc[n][1]:
            st = "UNREACHED"  # readers still in the code, nothing calls them
        elif rb[n][0] and dead:
            st = "PART-UNREACHED"  # some readers lost every caller (PG9 in rf4: pg9_turn kept, its call dropped)
            lost = dead
        elif rb[n][0] and not rc[n][1]:
            st = "REMOVED-0" if val == 0 else "FOLDED"  # no reader left: at 0 the feature is gone; else folded in at its value
        elif lost:
            st = "READER-LOST"
        else:
            continue
        if st in ("UNREACHED", "PART-UNREACHED", "REMOVED-0"):
            bad += 1
        rows.append(dict(table=n, status=st, base_value=tb[n].get("value"), volatile=tc[n]["volatile"],
                         base_readers=rb[n][0], cand_reachable=rc[n][0], cand_readers=rc[n][1], lost=lost, file=tc[n]["file"]))
    show = [r for r in rows if "--all" in a or r["status"] not in ("ok", "FEWER", "BAKED", "READER-LOST", "FOLDED")]
    print(f"flagorphan {base} -> {cand}: {len(tb)} tables in BASE ({sum(v['volatile'] for v in tb.values())} volatile); " + ", ".join(
        f"{s} {sum(r['status'] == s for r in rows)}" for s in ("ORPHANED", "UNREACHED", "PART-UNREACHED", "REMOVED-0", "BAKED-0", "GONE", "NOT-IN-DATA", "FOLDED", "READER-LOST", "BAKED", "FEWER", "ok")))
    for r in show:
        if r["status"] in ("UNREACHED", "PART-UNREACHED", "READER-LOST", "REMOVED-0", "FOLDED"):
            print(f"  {r['status']:<11} {r['table']:<14} {'volatile' if r['volatile'] else 'constexpr'} value {r['base_value']}; reachable readers base "
                  f"{','.join(r['base_readers'])}; cand reachable {','.join(r['cand_reachable']) or '-'} of {','.join(r['cand_readers']) or '-'}"
                  f"; lost {','.join(r['lost'])}  ({r['file']})")
            continue
        print(f"  {r['status']:<11} {r['table']:<14} base value {r['base_value']}, refs base {r['base_refs']} in {r['base_funcs']} fn, "
              f"cand {r['cand_refs']} in {r['cand_funcs']} fn  ({r['file']})")
    if "--json" in a:
        json.dump(rows, open(a[a.index("--json") + 1], "w"), indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
