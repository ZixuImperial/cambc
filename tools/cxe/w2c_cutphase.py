#!/usr/bin/env python3
"""w2c_cutphase: w2c_cutprof's shadow call stack (same N/I cut counts, CXE_CUTPROF) plus per-event stacks for the turn-phase report
(Tool Builder, 10 Nov; Rule Checker X160 T1: 37% of fuel cuts land outside turn() and the cut profile could not say where).
cxebuild variant "cutphase"; tools/cxe/fuelprof.py --cutphase reads it. w2c.py itself is untouched, so the playing builds and
their cache keys don't change. The added C statements spend no fuel and never touch I->fuel: games are identical to a normal build.

Each frame of an instance's shadow stack keeps its function index and the wasm op index of the last call it made (its 'site');
a catch landing sets the site to 0x80000000|<op index of the try_table>. Each instance counts its turns (seq: +1 after the
yield import returns and after a real fuel cut resumes; reset when _start is entered, so a new instance at a reused address
starts clean). Events, written to CXE_CUTPHASE (when set) as they happen:
  'C seq 0 depth fi:site ...'      a real fuel cut (w2c_fuel_will_cut) at a FUEL_CHECK_AT
  'X seq left depth fi:site ...'   the first check point of a turn with fuel >= -SOFT, i.e. <= 10,000 of the 100k budget left
                                   (90% used). The instance's first turn (seq 0: setup 200k, draft 10M) has a reserve and is skipped.
Check points are wasmtime's: function entry, loop header, bulk memory op. Also writes OUT_BASE.calls.tsv: 'fi site callee' for
every direct call in turn<..>() and play_turn_body<..>() (the report maps a frame's site to a turn phase)."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import w2c  # noqa: E402

DEPTH = 4096   # frames kept per instance
NSTK = 64      # instances (5 champions + draft per team, both teams if both use this library)
SOFT = 10000   # 90% of the 100k turn budget
LOGD = 512     # frames written per event
PHASE_FN = re.compile(r"play_turn_body<|::turn<\d+>\(")  # name section (demangled): nova::(anon)::play_turn_body<N>(), nova::(anon)::turn<N>()
CALLS = []     # (fi, site, callee) for PHASE_FN functions
_emit, _run, _ret, _rfc = w2c.FuncGen.emit, w2c.Gen.run, w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch
_op, _dop, _call = w2c.FuncGen.op, w2c.FuncGen.dead_op, w2c.FuncGen.call_expr


def ret_stmt(self, types):
    return ["cs_->d = cd0_;"] + _ret(self, types)


def ret_from_catch(self, tt, assigns):
    r = _rfc(self, tt, assigns)
    i = next(k for k, x in enumerate(r) if x.startswith("return"))
    return r[:i] + ["cs_->d = cd0_;"] + r[i:]


def op(self, o, imm):
    k = getattr(self, "_k", 0)
    self._k = k + 1
    self._site = k
    n0 = len(self.frames)
    r = _op(self, o, imm)
    if o == "try_table" and len(self.frames) > n0:
        self.__dict__.setdefault("_trylab", {})[self.frames[-1].lab] = k
    if o == "call" and PHASE_FN.search(self.g.m.names.get(self.fi, "")):
        CALLS.append((self.fi, k, imm))
    return r


def dead_op(self, o, imm):
    self._k = getattr(self, "_k", 0) + 1
    return _dop(self, o, imm)


def call_expr(self, target, args, ptypes, rtypes, fnptr=None):
    self.out.append(f"if (cd0_ < {DEPTH}u) cs_->ls[cd0_] = {self._site}u;")
    r = _call(self, target, args, ptypes, rtypes, fnptr)
    if target and target.endswith("__yield"):
        self.out.append("cs_->seq++;")  # the bot resumes here in its next turn
    return r


def emit(self):
    txt = _emit(self)
    a = "int64_t fuel = I->fuel;\n"
    assert a in txt, "w2c layout changed: no fuel local"
    P = self.g.prefix
    st = getattr(self.g, "_start_fi", None)
    reset = "cs_->d = 0; cs_->seq = 0; cs_->mk = 0; " if self.fi == st else ""
    txt = txt.replace(a, a + f"{P}_cstk *cs_ = {P}_cs_get(I); {reset}const uint32_t cd0_ = cs_->d; if (cd0_ < {DEPTH}u) {{ cs_->s[cd0_] = {self.fi}u; "
                         f"cs_->ls[cd0_] = 0xffffffffu; }} cs_->d = cd0_ + 1;\n", 1)
    tl = getattr(self, "_trylab", {})
    if tl:  # a catch landing: the frames the throw unwound are gone; this frame's site is the try
        def land(mo):
            k = tl.get(int(mo.group(1)))
            return mo.group(0) + ("" if k is None else f"\ncs_->d = cd0_ + 1; if (cd0_ < {DEPTH}u) cs_->ls[cd0_] = {0x80000000 | k}u;")
        txt = re.sub(r"^I->eh_top = ehf(\d+)\.prev;$", land, txt, flags=re.M)
    return txt


class _Proxy:
    """Cut walk + event, turn count after a cut, and the 90% soft mark, in FUEL_CHECK_AT."""
    def __init__(self, f, P):
        self.f, self.P = f, P

    def write(self, t):
        if t.startswith("#define FUEL_CHECK_AT"):
            P = self.P
            walk = (f"{{ {P}_cstk *c2_ = {P}_cs_get(I); const uint32_t dd_ = c2_->d < {DEPTH}u ? c2_->d : {DEPTH}u; "
                    f"for (uint32_t q_ = 0; q_ < dd_; q_++) {P}_icut[c2_->s[q_]]++; {P}_ncut++; {P}_cp_ev(c2_, 'C', 0); }} ")
            a = " w2c_out_of_fuel(I);"
            assert a in t and "w2c_fuel_will_cut" in t and "if (W2C_UNLIKELY(fuel >= 0))" in t, "w2c layout changed: FUEL_CHECK_AT"
            t = t.replace(a, f" if (w2c_fuel_will_cut(I)) {{ {walk}w2c_out_of_fuel(I); {P}_cs_get(I)->seq++; }} else w2c_out_of_fuel(I);", 1)
            t = t.replace("if (W2C_UNLIKELY(fuel >= 0))", f"if (W2C_UNLIKELY(fuel >= -{SOFT}LL)) {P}_cp_soft(I, fuel); if (W2C_UNLIKELY(fuel >= 0))", 1)
        return self.f.write(t)


def run(self, outs):
    P = self.prefix
    nf = len(self.m.funcs) + self.m.nimp
    self._start_fi = next((i for n, k, i in self.m.exports if n == "_start" and k == 0), None)
    hdr = (f"#include <stdint.h>\ntypedef struct {{ void *I; uint32_t d, seq, mk; uint32_t s[{DEPTH}]; uint32_t ls[{DEPTH}]; }} {P}_cstk;\n"
           f"extern {P}_cstk {P}_stk[{NSTK}]; extern void *{P}_csI; extern {P}_cstk *{P}_csP; extern uint64_t {P}_icut[]; extern uint64_t {P}_ncut;\n"
           f"void {P}_cp_ev({P}_cstk *c, int kind, int64_t left);\n"
           f"static inline {P}_cstk *{P}_cs_get(void *I) {{ if (I == {P}_csI) return {P}_csP; "
           f"for (int i = 0; i < {NSTK}; i++) if ({P}_stk[i].I == I || !{P}_stk[i].I) {{ {P}_stk[i].I = I; {P}_csI = I; {P}_csP = &{P}_stk[i]; return {P}_csP; }} "
           f"return &{P}_stk[{NSTK} - 1]; }}\n"
           f"static inline void {P}_cp_soft(void *I, int64_t f) {{ {P}_cstk *c = {P}_cs_get(I); "
           f"if (c->seq && c->mk != c->seq + 1) {{ c->mk = c->seq + 1; {P}_cp_ev(c, 'X', f < 0 ? -f : 0); }} }}\n")
    for o in outs:
        o.write(hdr)
    _run(self, [_Proxy(o, P) for o in outs])
    w = outs[-1].write
    w(f"#include <stdio.h>\n#include <stdlib.h>\n{P}_cstk {P}_stk[{NSTK}]; void *{P}_csI; {P}_cstk *{P}_csP; uint64_t {P}_icut[{nf}]; uint64_t {P}_ncut;\n"
      f"static FILE *{P}_cpf; static int {P}_cpo;\n"
      f"void {P}_cp_ev({P}_cstk *c, int kind, int64_t left) {{\n"
      f"  if (!{P}_cpo) {{ {P}_cpo = 1; const char *p = getenv(\"CXE_CUTPHASE\"); if (p) {P}_cpf = fopen(p, \"w\"); }}\n"
      f"  if (!{P}_cpf) return;\n"
      f"  const uint32_t d = c->d < {LOGD}u ? c->d : {LOGD}u;\n"
      f"  fprintf({P}_cpf, \"%c %u %lld %u\", kind, c->seq, (long long)left, c->d);\n"
      f"  for (uint32_t q = 0; q < d; q++) fprintf({P}_cpf, \" %u:%u\", c->s[q], c->ls[q]);\n"
      f"  fputc('\\n', {P}_cpf);\n}}\n"
      f"__attribute__((destructor)) static void {P}_cutprof_dump(void) {{\n"
      f"  if (!{P}_cpo) {{ const char *q = getenv(\"CXE_CUTPHASE\"); if (q) {P}_cpf = fopen(q, \"w\"); {P}_cpo = 1; }}  /* no events: an empty file (cxefarm wants it) */\n"
      f"  if ({P}_cpf) {{ fclose({P}_cpf); {P}_cpf = 0; }}\n"
      f"  const char *p = getenv(\"CXE_CUTPROF\"); if (!p) return;\n"
      f"  FILE *f = fopen(p, \"w\"); if (!f) return;\n"
      f"  fprintf(f, \"N\\t%llu\\n\", (unsigned long long){P}_ncut);\n"
      f"  for (unsigned i = 0; i < {nf}u; i++) if ({P}_icut[i]) fprintf(f, \"I\\t%u\\t%llu\\n\", i, (unsigned long long){P}_icut[i]);\n"
      f"  fclose(f);\n}}\n")


w2c.FuncGen.emit, w2c.Gen.run = emit, run
w2c.FuncGen.ret_stmt, w2c.FuncGen.ret_from_catch = ret_stmt, ret_from_catch
w2c.FuncGen.op, w2c.FuncGen.dead_op, w2c.FuncGen.call_expr = op, dead_op, call_expr

if __name__ == "__main__":
    if "--fuelprof" not in sys.argv:
        sys.argv.append("--fuelprof")  # the cut counter sits in fuelprof's FUEL_CHECK_AT
    w2c.main()
    dst = sys.argv[2]
    base = dst[:-2] if dst.endswith(".c") else dst
    with open(base + ".calls.tsv.tmp", "w") as f:
        f.write("".join(f"{a}\t{b}\t{c}\n" for a, b, c in CALLS))
    os.replace(base + ".calls.tsv.tmp", base + ".calls.tsv")
