#!/usr/bin/env python3
"""w2c_callmax: w2c.py --fuelprof plus per-call INCLUSIVE fuel per function (Tool Builder, 8 Nov; owner via the Coordinator: guards set to each
step's measured worst case instead of 40-60k floors). At entry a function notes the fuel counter and the instance's cut count; at a normal
return it records the fuel spent by the call and everything it called (host charges included): max, count, total, and a log2 histogram.
A call that crossed a fuel cut or slice refill (the cut count moved) is not measured, only counted ('crossed'); a frame left by an exception
(an AF bail, a throw) records nothing. Measurement only: cxebuild variant "callmax"; the playing builds and cache keys don't change.
At process exit, when CXE_CALLMAX names a file: one line per function with calls: 'F idx calls crossed max total h0 .. h39'
(h_k = calls costing [2^k, 2^(k+1)) fuel)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import w2c  # noqa: E402

NSTK = 64  # instances (5 champions + draft per team, both teams)
NB = 40
_emit, _run, _ret, _rfc = w2c.FuncGen.emit, w2c.Gen.run, w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch


def rec(self):
    P = self.g.prefix
    return (f"{{ const int64_t d_ = fuel - cf0_; if ({P}_cm_cut(I) == cc0_ && d_ >= 0) {P}_cmrec({self.fi}u, (uint64_t)d_); "
            f"else {P}_cm_x[{self.fi}u]++; }}")  # 8 Nov: a refill outside FUEL_CHECK_AT (host or bulk-op check) makes the delta negative: crossed


def ret_stmt(self, types):
    return [rec(self)] + _ret(self, types)


def ret_from_catch(self, tt, assigns):
    r = _rfc(self, tt, assigns)
    i = next(k for k, x in enumerate(r) if x.startswith("return"))
    return r[:i] + [rec(self)] + r[i:]


def emit(self):
    txt = _emit(self)
    a = "int64_t fuel = I->fuel;\n"
    assert a in txt, "w2c layout changed: no fuel local"
    P = self.g.prefix
    return txt.replace(a, a + f"const int64_t cf0_ = fuel; const uint64_t cc0_ = {P}_cm_cut(I);\n", 1)


class _Proxy:
    """Counts the instance's cuts and refills in the out-of-fuel branch of FUEL_CHECK_AT and the bulk-op check."""
    def __init__(self, f, P):
        self.f, self.P = f, P

    def write(self, t):
        if t.startswith("#define FUEL_CHECK_AT"):
            # 10 Nov: w2c's FUEL_CHECK_AT gained 'if (w2c_fuel_will_cut(I)) ...;' between these two statements (7f11aa87); anchor on the first
            assert "I->fuel = fuel;" in t and "w2c_out_of_fuel(I);" in t, "w2c layout changed: FUEL_CHECK_AT"
            t = t.replace("I->fuel = fuel;", f"{self.P}_cm_bump(I); I->fuel = fuel;", 1)
        return self.f.write(t)


def run(self, outs):
    P = self.prefix
    nf = len(self.m.funcs) + self.m.nimp
    hdr = (f"#include <stdint.h>\n"
           f"extern void *{P}_cmI[{NSTK}]; extern uint64_t {P}_cmC[{NSTK}]; extern uint64_t {P}_cm_n[], {P}_cm_x[], {P}_cm_max[], {P}_cm_sum[], {P}_cm_h[];\n"
           f"static inline int {P}_cm_slot(void *I) {{ for (int i = 0; i < {NSTK}; i++) if ({P}_cmI[i] == I || !{P}_cmI[i]) {{ {P}_cmI[i] = I; return i; }} return {NSTK} - 1; }}\n"
           f"static inline uint64_t {P}_cm_cut(void *I) {{ return {P}_cmC[{P}_cm_slot(I)]; }}\n"
           f"static inline void {P}_cm_bump(void *I) {{ {P}_cmC[{P}_cm_slot(I)]++; }}\n"
           f"static inline void {P}_cmrec(uint32_t f, uint64_t d) {{ {P}_cm_n[f]++; {P}_cm_sum[f] += d; if (d > {P}_cm_max[f]) {P}_cm_max[f] = d; "
           f"int b = 0; uint64_t v = d; while (v > 1 && b < {NB} - 1) {{ v >>= 1; b++; }} {P}_cm_h[(uint64_t)f * {NB} + b]++; }}\n")
    for o in outs:
        o.write(hdr)
    _run(self, [_Proxy(o, P) for o in outs])
    w = outs[-1].write
    w(f"#include <stdio.h>\n#include <stdlib.h>\nvoid *{P}_cmI[{NSTK}]; uint64_t {P}_cmC[{NSTK}]; uint64_t {P}_cm_n[{nf}], {P}_cm_x[{nf}], {P}_cm_max[{nf}], {P}_cm_sum[{nf}], {P}_cm_h[{nf * NB}];\n"
      f"__attribute__((destructor)) static void {P}_callmax_dump(void) {{\n"
      f"  const char *p = getenv(\"CXE_CALLMAX\"); if (!p) return;\n"
      f"  FILE *f = fopen(p, \"w\"); if (!f) return;\n"
      f"  for (unsigned i = 0; i < {nf}u; i++) if ({P}_cm_n[i] || {P}_cm_x[i]) {{\n"
      f"    fprintf(f, \"F\\t%u\\t%llu\\t%llu\\t%llu\\t%llu\", i, (unsigned long long){P}_cm_n[i], (unsigned long long){P}_cm_x[i], (unsigned long long){P}_cm_max[i], (unsigned long long){P}_cm_sum[i]);\n"
      f"    for (int b = 0; b < {NB}; b++) fprintf(f, \"\\t%llu\", (unsigned long long){P}_cm_h[(uint64_t)i * {NB} + b]);\n"
      f"    fprintf(f, \"\\n\"); }}\n"
      f"  fclose(f);\n}}\n")


w2c.FuncGen.emit, w2c.Gen.run = emit, run
w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch = ret_stmt, ret_from_catch

if __name__ == "__main__":
    if "--fuelprof" not in sys.argv:
        sys.argv.append("--fuelprof")
    w2c.main()
