#!/usr/bin/env python3
"""w2c_lineprof: w2c.py --fuelprof plus one counter per fuel-flush site (Tool Builder, 10 Nov; Rule Checker x138: split the inlined roots
turn<0> and econ::observe by source line). Every flush of pending instruction fuel bumps {P}_lp[site] by one (the block ran once); the site
table lists the code-section offset of each fuel-charged instruction in the block, so fuel per instruction = executions x 1. Bulk-op bytes
(memory.copy/fill) and the host charges of an import call add their fuel to their own site at that instruction's offset. Measurement
only: the fuel accounting and the generated play code are w2c.py's; counters are extra statements (cxebuild variant "lineprof"; the
playing builds and their cache keys don't change).
Outputs: the translation as w2c.py, plus OUT_BASE.sites.tsv: '# wasm PATH SHA256' then 'site fi kind offsets' (offsets: comma list,
code-section relative, i.e. what DWARF and llvm-symbolizer use). At process exit, when CXE_LINEPROF names a file: 'site count' lines.
kind: b = block (count = executions, each listed instruction costs 1 per execution), x = bulk bytes, h = host charge (count = fuel),
e = function entry (count = calls; 1 fuel each, at the body's first instruction; 11 Nov: was booked as 'b', doubling that instruction)."""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import w2c  # noqa: E402
import wasmparse  # noqa: E402

SITES = []      # (fi, kind, [offsets])
STATS = {"mismatch": 0, "entry": 0}
CODE0 = [0]     # file offset of the code section payload
_init, _gen, _flush, _op, _run = w2c.FuncGen.__init__, w2c.FuncGen.gen, w2c.FuncGen.flush, w2c.FuncGen.op, w2c.Gen.run


def code_start(b):
    r = wasmparse.R(b, 8)
    while r.p < len(b):
        sid, size = r.u8(), r.u32()
        if sid == 10:
            return r.p
        r.p += size
    raise ValueError("no code section")


def op_offsets(b, p, end):
    """Byte offset of every instruction in a body: wasmparse.decode_body's loop, recording where each op starts (checked against it)."""
    r = wasmparse.R(b, p)
    for _ in range(r.u32()):
        r.u32()
        r.vt()
    offs = []
    while r.p < end:
        offs.append(r.p)
        op = r.u8()
        if op == 0xfc:
            name, k = wasmparse.FC[r.u32()]
        elif op == 0xfd:
            name, k = wasmparse.SIMD[r.u32()]
        else:
            name, k = wasmparse.OPS[op]
        if k == "":
            pass
        elif k in ("u",):
            r.u32()
        elif k == "uu":
            r.u32(), r.u32()
        elif k == "ub":
            r.u32(), r.u8()
        elif k in ("b", "bb"):
            r.raw(len(k))
        elif k == "bt":
            r.blocktype()
        elif k == "table":
            [r.u32() for _ in range(r.u32())]
            r.u32()
        elif k == "selt":
            [r.vt() for _ in range(r.u32())]
        elif k == "try":
            r.blocktype()
            for _ in range(r.u32()):
                ck = r.u8()
                if ck in (0, 1):
                    r.u32()
                r.u32()
        elif k == "mem":
            wasmparse.memarg(r)
        elif k == "memlane":
            wasmparse.memarg(r), r.u8()
        elif k == "lane":
            r.u8()
        elif k == "c16":
            r.raw(16)
        elif k == "i32":
            r.sleb(32)
        elif k == "i64":
            r.sleb(64)
        elif k == "f32":
            r.raw(4)
        elif k == "f64":
            r.raw(8)
        else:
            raise ValueError(k)
    assert r.p == end
    return offs


class _Code(list):
    """self.code for gen(): notes each charged instruction's offset as gen() walks it (same rule as gen: not dead, not zero-cost)."""
    def __init__(self, fg, items, offs):
        super().__init__(items)
        self.fg, self.offs, self.active = fg, offs, True

    def __iter__(self):
        if not self.active:
            yield from list.__iter__(self)
            return
        fg, zc = self.fg, self.fg.g.zero_cost
        for i, (op, imm) in enumerate(list.__iter__(self)):
            fg.lp_cur = self.offs[i]
            if fg.pending == 0:
                fg.lp_pend = []
            if not fg.dead and op not in zc:
                fg.lp_pend.append(self.offs[i])
            yield op, imm
        self.active = False


def init(self, g, fi, k):
    _init(self, g, fi, k)
    b, p, e = self.m.bodies[k]
    offs = op_offsets(b, p, e)
    assert len(offs) == len(self.code), f"lineprof: offsets of function {fi} disagree with wasmparse"
    self.code = _Code(self, self.code, [o - CODE0[0] for o in offs])
    self.lp_pend, self.lp_cur = [], (offs[0] if offs else p) - CODE0[0]
    self.lp_entry = self.lp_cur


def site(self, kind, offs):
    SITES.append((self.fi, kind, offs))
    return len(SITES) - 1


def flush(self):
    n = self.pending if self.g.fuel else 0
    _flush(self)
    if n:
        offs = self.lp_pend
        if len(offs) != n:
            if not offs and n == 1:  # the function-entry charge (gen() starts with pending 1): its own site kind 'e' (count = calls, 1 fuel
                # each) at the body's first instruction. 11 Nov (RC X418): booked as kind 'b' it counted that instruction twice (calls + runs)
                STATS["entry"] += 1
                self.out.append(f"{self.g.prefix}_lp[{site(self, 'e', [self.lp_entry])}]++;")
                self.lp_pend = []
                return
            else:
                STATS["mismatch"] += 1
                offs = (offs + [offs[-1] if offs else self.lp_cur] * n)[:n]
        self.out.append(f"{self.g.prefix}_lp[{site(self, 'b', offs)}]++;")
    self.lp_pend = []


def op(self, o, imm):
    k0 = len(self.out)
    _op(self, o, imm)
    P, F = self.g.prefix, f"I->fprof[{self.fi}] += "
    for j in range(k0, len(self.out)):
        ln = self.out[j]
        if ln == F + "(uint64_t)(I->fuel - f0_); }":  # host charges of an import call (w2c.call_expr)
            s = site(self, "h", [self.lp_cur])
            self.out[j] = f"{{ const uint64_t d_ = (uint64_t)(I->fuel - f0_); {F}d_; {P}_lp[{s}] += d_; }} }}"
        elif ln.startswith(F) and ln.endswith(";") and not ln[len(F):-1].isdigit():  # bulk bytes (memory.copy / memory.fill)
            s = site(self, "x", [self.lp_cur])
            self.out[j] = ln + f" {P}_lp[{s}] += {ln[len(F):-1]};"


def run(self, outs):
    P = self.prefix
    for o in outs:
        o.write(f"#include <stdint.h>\nextern uint64_t {P}_lp[];\n")
    _run(self, outs)
    w = outs[-1].write
    n = max(1, len(SITES))
    w(f"#include <stdio.h>\n#include <stdlib.h>\nuint64_t {P}_lp[{n}];\n"
      f"__attribute__((destructor)) static void {P}_lineprof_dump(void) {{\n"
      f"  const char *p = getenv(\"CXE_LINEPROF\"); if (!p) return;\n"
      f"  FILE *f = fopen(p, \"w\"); if (!f) return;\n"
      f"  for (unsigned i = 0; i < {n}u; i++) if ({P}_lp[i]) fprintf(f, \"%u\\t%llu\\n\", i, (unsigned long long){P}_lp[i]);\n"
      f"  fclose(f);\n}}\n")


w2c.FuncGen.__init__, w2c.FuncGen.flush, w2c.FuncGen.op, w2c.Gen.run = init, flush, op, run

if __name__ == "__main__":
    if "--fuelprof" not in sys.argv:
        sys.argv.append("--fuelprof")
    src, dst = sys.argv[1], sys.argv[2]
    data = open(src, "rb").read()
    CODE0[0] = code_start(data)
    w2c.main()
    base = dst[:-2] if dst.endswith(".c") else dst
    with open(base + ".sites.tsv.tmp", "w") as f:
        f.write(f"# wasm {os.path.abspath(src)} {hashlib.sha256(data).hexdigest()} sites {len(SITES)} entry {STATS['entry']} mismatch {STATS['mismatch']}\n")
        for i, (fi, kind, offs) in enumerate(SITES):
            f.write(f"{i}\t{fi}\t{kind}\t{','.join(map(str, offs))}\n")
    os.replace(base + ".sites.tsv.tmp", base + ".sites.tsv")
    print(f"w2c_lineprof: {len(SITES)} sites, {STATS['entry']} entry, {STATS['mismatch']} mismatched blocks", file=sys.stderr)
