#!/usr/bin/env python3
"""w2c_cutprof: w2c.py --fuelprof plus a per-instance shadow call stack, so a fuel cut is credited to EVERY function that was
running when the turn ran dry, not only the innermost one (Tool builder 2, 5 Nov; owner: "check why our fuel runs out").
fuelprof's cut column names the leaf (a vector copy, capture_recall: wherever the last fuel went); the shadow stack shows the
caller that spent the turn (group_bounds, build_team, ...). cxebuild variant "cutprof" calls this; w2c.py itself is untouched,
so the playing builds and their cache keys don't change. The added C statements spend no fuel: fuel is the same as fuelprof's.
Each bot instance (champion, draft) keeps its own stack (instances pause mid-call at a fuel cut and another one runs, so one
shared stack would mix them). At process exit, when CXE_CUTPROF names a file: 'N <cuts>' and 'I <func index> <cuts with that
function on the stack>' lines (a recursive function counts once per frame)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import w2c  # noqa: E402

DEPTH = 4096   # frames kept per instance (deeper frames are counted in the depth but not recorded)
NSTK = 64      # instances (5 champions + draft per team, both teams if both use this library)
_emit, _run, _ret, _rfc = w2c.FuncGen.emit, w2c.Gen.run, w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch


def ret_stmt(self, types):
    return ["cs_->d = cd0_;"] + _ret(self, types)


def ret_from_catch(self, tt, assigns):
    r = _rfc(self, tt, assigns)
    i = next(k for k, x in enumerate(r) if x.startswith("return"))
    return r[:i] + ["cs_->d = cd0_;"] + r[i:]


def emit(self):
    txt = _emit(self)
    a = "int64_t fuel = I->fuel;\n"
    assert a in txt, "w2c layout changed: no fuel local"
    P = self.g.prefix
    return txt.replace(a, a + f"{P}_cstk *cs_ = {P}_cs_get(I); const uint32_t cd0_ = cs_->d; if (cd0_ < {DEPTH}u) cs_->s[cd0_] = {self.fi}u; "
                          f"cs_->d = cd0_ + 1;\n", 1)


class _Proxy:
    """Adds the stack walk to the out-of-fuel branch of FUEL_CHECK_AT."""
    def __init__(self, f, P):
        self.f, self.P = f, P

    def write(self, t):
        if t.startswith("#define FUEL_CHECK_AT"):
            P = self.P
            walk = (f"{{ {P}_cstk *c2_ = {P}_cs_get(I); const uint32_t dd_ = c2_->d < {DEPTH}u ? c2_->d : {DEPTH}u; "
                    f"for (uint32_t q_ = 0; q_ < dd_; q_++) {P}_icut[c2_->s[q_]]++; {P}_ncut++; "
                    # 12 Nov (RC X531: per-cut stacks, not only per-function counts): each cut's stack, bottom to top, when CXE_CUTSTK names a file
                    f"if (!{P}_sfi) {{ const char *e_ = getenv(\"CXE_CUTSTK\"); {P}_sfi = 1; if (e_) {P}_sfp = fopen(e_, \"w\"); }} "
                    f"if ({P}_sfp) {{ fputc('S', {P}_sfp); for (uint32_t q_ = 0; q_ < dd_; q_++) fprintf({P}_sfp, \" %u\", c2_->s[q_]); fputc('\\n', {P}_sfp); }} }} ")
            # 10 Nov (Rule Checker): credit the stack only when this check really suspends the bot (w2c_fuel_will_cut), not at slice refills
            assert " w2c_out_of_fuel(I);" in t and "w2c_fuel_will_cut" in t, "w2c layout changed: FUEL_CHECK_AT"
            t = t.replace(" w2c_out_of_fuel(I);", " if (w2c_fuel_will_cut(I)) " + walk + "w2c_out_of_fuel(I);", 1)
        return self.f.write(t)


def run(self, outs):
    P = self.prefix
    nf = len(self.m.funcs) + self.m.nimp
    hdr = (f"#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\nextern FILE *{P}_sfp; extern int {P}_sfi;\ntypedef struct {{ void *I; uint32_t d; uint32_t s[{DEPTH}]; }} {P}_cstk;\n"
           f"extern {P}_cstk {P}_stk[{NSTK}]; extern void *{P}_csI; extern {P}_cstk *{P}_csP; extern uint64_t {P}_icut[]; extern uint64_t {P}_ncut;\n"
           f"static inline {P}_cstk *{P}_cs_get(void *I) {{ if (I == {P}_csI) return {P}_csP; "
           f"for (int i = 0; i < {NSTK}; i++) if ({P}_stk[i].I == I || !{P}_stk[i].I) {{ {P}_stk[i].I = I; {P}_csI = I; {P}_csP = &{P}_stk[i]; return {P}_csP; }} "
           f"return &{P}_stk[{NSTK} - 1]; }}\n")
    for o in outs:
        o.write(hdr)
    _run(self, [_Proxy(o, P) for o in outs])
    w = outs[-1].write
    w(f"#include <stdio.h>\nFILE *{P}_sfp; int {P}_sfi; {P}_cstk {P}_stk[{NSTK}]; void *{P}_csI; {P}_cstk *{P}_csP; uint64_t {P}_icut[{nf}]; uint64_t {P}_ncut;\n"
      f"__attribute__((destructor)) static void {P}_cutprof_dump(void) {{\n"
      f"  if ({P}_sfp) fclose({P}_sfp);\n"
      f"  const char *p = getenv(\"CXE_CUTPROF\"); if (!p) return;\n"
      f"  FILE *f = fopen(p, \"w\"); if (!f) return;\n"
      f"  fprintf(f, \"N\\t%llu\\n\", (unsigned long long){P}_ncut);\n"
      f"  for (unsigned i = 0; i < {nf}u; i++) if ({P}_icut[i]) fprintf(f, \"I\\t%u\\t%llu\\n\", i, (unsigned long long){P}_icut[i]);\n"
      f"  fclose(f);\n}}\n")


w2c.FuncGen.emit, w2c.Gen.run = emit, run
w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch = ret_stmt, ret_from_catch

if __name__ == "__main__":
    if "--fuelprof" not in sys.argv:
        sys.argv.append("--fuelprof")  # the cut counter sits in fuelprof's FUEL_CHECK_AT
    w2c.main()
