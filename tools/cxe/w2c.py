"""w2c: translate a WebAssembly module to C for cxe (the C++ test engine). Our own translator (no third-party code).
Output: one C file; functions take the instance (w2c_inst*) first; imports call host functions
cxe_imp_<module>__<name>(w2c_inst*, ...); exports are reached through <prefix>_module.export_fn(name).
--fuel adds wasmtime-style fuel metering: every instruction costs 1 except nop, drop, block, loop, else, end, return,
unreachable, memory.grow (cost 0); the CLI also charges 1 per function entry and 1 per byte moved by memory.copy /
memory.fill (fitted exactly on 7,991 turns of a CLI fuel log, tools/cxe/README.md); pending cost is flushed into I->fuel before calls, branches and other control flow, and fuel is
checked at function entry and loop headers (out when consumed - budget >= 0), which is where wasmtime checks it.
usage: python3 -I w2c.py IN.wasm OUT.c --prefix NAME [--fuel] [--profile] [--fuelprof] [--split N (writes OUT.0.c .. OUT.N-1.c and OUT.data.c)]"""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wasmparse  # noqa: E402

CT = {"i32": "uint32_t", "i64": "uint64_t", "f32": "float", "f64": "double", "v128": "v128",
      "funcref": "uint32_t", "externref": "uint32_t", "exnref": "uint32_t", "ref": "uint32_t"}
SC = {"i32": "i", "i64": "l", "f32": "f", "f64": "d", "v128": "v", "funcref": "r", "externref": "r", "exnref": "r", "ref": "r"}
GF = {"i32": "i32", "i64": "i64", "f32": "f32", "f64": "f64", "v128": "v", "funcref": "i32", "externref": "i32", "exnref": "i32"}
# --profile counter slots (I->prof[k]): executed zero-cost ops, memory.copy bytes, memory.fill bytes, memory.copy
# calls, memory.fill calls, try_table entries, import calls, call_indirect, direct calls, memory.grow, throws,
# loop iterations (header passes), function entries, br_if taken
PROF = {"zero": 0, "copyb": 1, "fillb": 2, "copy": 3, "fill": 4, "try": 5, "imp": 6, "ind": 7, "call": 8, "grow": 9,
        "throw": 10, "loop": 11, "entry": 12, "costed": 13}
# --profile: per-opcode execution counters I->opc[OPIDS[name]] (every opcode name the decoder knows)
OPIDS = {n: i for i, n in enumerate(sorted({v[0] for v in wasmparse.OPS.values()} | {v[0] for v in wasmparse.FC.values()}
                                           | {v[0] for v in wasmparse.SIMD.values()}))}
ZERO_COST = {"nop", "drop", "block", "loop", "unreachable", "return", "else", "end", "memory.grow"}
FLUSH = {"call", "call_indirect", "return", "unreachable", "throw", "throw_ref", "br", "br_if", "br_table", "if", "else",
         "end", "block", "loop", "try_table", "memory.grow"}

# binary scalar ops: name -> (operand type, result type, C expression with {a} {b})
BIN = {}
for t, u, s in (("i32", "uint32_t", "int32_t"), ("i64", "uint64_t", "int64_t")):
    BIN.update({f"{t}.add": (t, t, "{a} + {b}"), f"{t}.sub": (t, t, "{a} - {b}"), f"{t}.mul": (t, t, "{a} * {b}"),
                f"{t}.and": (t, t, "{a} & {b}"), f"{t}.or": (t, t, "{a} | {b}"), f"{t}.xor": (t, t, "{a} ^ {b}"),
                f"{t}.eq": (t, "i32", "{a} == {b}"), f"{t}.ne": (t, "i32", "{a} != {b}"),
                f"{t}.lt_u": (t, "i32", "{a} < {b}"), f"{t}.gt_u": (t, "i32", "{a} > {b}"),
                f"{t}.le_u": (t, "i32", "{a} <= {b}"), f"{t}.ge_u": (t, "i32", "{a} >= {b}"),
                f"{t}.lt_s": (t, "i32", f"({s}){{a}} < ({s}){{b}}"), f"{t}.gt_s": (t, "i32", f"({s}){{a}} > ({s}){{b}}"),
                f"{t}.le_s": (t, "i32", f"({s}){{a}} <= ({s}){{b}}"), f"{t}.ge_s": (t, "i32", f"({s}){{a}} >= ({s}){{b}}"),
                f"{t}.div_s": (t, t, f"{t}_div_s(I, {{a}}, {{b}})"), f"{t}.div_u": (t, t, f"{t}_div_u(I, {{a}}, {{b}})"),
                f"{t}.rem_s": (t, t, f"{t}_rem_s(I, {{a}}, {{b}})"), f"{t}.rem_u": (t, t, f"{t}_rem_u(I, {{a}}, {{b}})"),
                f"{t}.rotl": (t, t, f"{t}_rotl({{a}}, {{b}})"), f"{t}.rotr": (t, t, f"{t}_rotr({{a}}, {{b}})")})
BIN.update({"i32.shl": ("i32", "i32", "{a} << ({b} & 31)"), "i32.shr_u": ("i32", "i32", "{a} >> ({b} & 31)"),
            "i32.shr_s": ("i32", "i32", "(uint32_t)((int32_t){a} >> ({b} & 31))"),
            "i64.shl": ("i64", "i64", "{a} << ({b} & 63)"), "i64.shr_u": ("i64", "i64", "{a} >> ({b} & 63)"),
            "i64.shr_s": ("i64", "i64", "(uint64_t)((int64_t){a} >> ({b} & 63))")})
for t in ("f32", "f64"):
    BIN.update({f"{t}.add": (t, t, "{a} + {b}"), f"{t}.sub": (t, t, "{a} - {b}"), f"{t}.mul": (t, t, "{a} * {b}"),
                f"{t}.div": (t, t, "{a} / {b}"), f"{t}.min": (t, t, f"{t}_min({{a}}, {{b}})"),
                f"{t}.max": (t, t, f"{t}_max({{a}}, {{b}})"), f"{t}.copysign": (t, t, f"{t}_copysign({{a}}, {{b}})"),
                f"{t}.eq": (t, "i32", "{a} == {b}"), f"{t}.ne": (t, "i32", "{a} != {b}"), f"{t}.lt": (t, "i32", "{a} < {b}"),
                f"{t}.gt": (t, "i32", "{a} > {b}"), f"{t}.le": (t, "i32", "{a} <= {b}"), f"{t}.ge": (t, "i32", "{a} >= {b}")})
# unary scalar ops: name -> (operand type, result type, C expression with {a})
UN = {"i32.eqz": ("i32", "i32", "{a} == 0"), "i64.eqz": ("i64", "i32", "{a} == 0"),
      "i32.clz": ("i32", "i32", "i32_clz({a})"), "i32.ctz": ("i32", "i32", "i32_ctz({a})"),
      "i32.popcnt": ("i32", "i32", "(uint32_t)__builtin_popcount({a})"),
      "i64.clz": ("i64", "i64", "i64_clz({a})"), "i64.ctz": ("i64", "i64", "i64_ctz({a})"),
      "i64.popcnt": ("i64", "i64", "(uint64_t)__builtin_popcountll({a})"),
      "f32.abs": ("f32", "f32", "f32_abs({a})"), "f32.neg": ("f32", "f32", "f32_neg({a})"),
      "f32.ceil": ("f32", "f32", "__builtin_ceilf({a})"), "f32.floor": ("f32", "f32", "__builtin_floorf({a})"),
      "f32.trunc": ("f32", "f32", "__builtin_truncf({a})"), "f32.nearest": ("f32", "f32", "f32_nearest({a})"),
      "f32.sqrt": ("f32", "f32", "__builtin_sqrtf({a})"),
      "f64.abs": ("f64", "f64", "f64_abs({a})"), "f64.neg": ("f64", "f64", "f64_neg({a})"),
      "f64.ceil": ("f64", "f64", "__builtin_ceil({a})"), "f64.floor": ("f64", "f64", "__builtin_floor({a})"),
      "f64.trunc": ("f64", "f64", "__builtin_trunc({a})"), "f64.nearest": ("f64", "f64", "f64_nearest({a})"),
      "f64.sqrt": ("f64", "f64", "__builtin_sqrt({a})"),
      "i32.wrap_i64": ("i64", "i32", "(uint32_t){a}"),
      "i64.extend_i32_s": ("i32", "i64", "(uint64_t)(int64_t)(int32_t){a}"), "i64.extend_i32_u": ("i32", "i64", "(uint64_t){a}"),
      "i32.trunc_f32_s": ("f32", "i32", "i32_trunc_f32_s(I, {a})"), "i32.trunc_f32_u": ("f32", "i32", "i32_trunc_f32_u(I, {a})"),
      "i32.trunc_f64_s": ("f64", "i32", "i32_trunc_f64_s(I, {a})"), "i32.trunc_f64_u": ("f64", "i32", "i32_trunc_f64_u(I, {a})"),
      "i64.trunc_f32_s": ("f32", "i64", "i64_trunc_f32_s(I, {a})"), "i64.trunc_f32_u": ("f32", "i64", "i64_trunc_f32_u(I, {a})"),
      "i64.trunc_f64_s": ("f64", "i64", "i64_trunc_f64_s(I, {a})"), "i64.trunc_f64_u": ("f64", "i64", "i64_trunc_f64_u(I, {a})"),
      "f32.convert_i32_s": ("i32", "f32", "(float)(int32_t){a}"), "f32.convert_i32_u": ("i32", "f32", "(float){a}"),
      "f32.convert_i64_s": ("i64", "f32", "(float)(int64_t){a}"), "f32.convert_i64_u": ("i64", "f32", "(float){a}"),
      "f32.demote_f64": ("f64", "f32", "(float){a}"),
      "f64.convert_i32_s": ("i32", "f64", "(double)(int32_t){a}"), "f64.convert_i32_u": ("i32", "f64", "(double){a}"),
      "f64.convert_i64_s": ("i64", "f64", "(double)(int64_t){a}"), "f64.convert_i64_u": ("i64", "f64", "(double){a}"),
      "f64.promote_f32": ("f32", "f64", "(double){a}"),
      "i32.reinterpret_f32": ("f32", "i32", "bits_f32({a})"), "i64.reinterpret_f64": ("f64", "i64", "bits_f64({a})"),
      "f32.reinterpret_i32": ("i32", "f32", "f32_bits({a})"), "f64.reinterpret_i64": ("i64", "f64", "f64_bits({a})"),
      "i32.extend8_s": ("i32", "i32", "(uint32_t)(int32_t)(int8_t){a}"), "i32.extend16_s": ("i32", "i32", "(uint32_t)(int32_t)(int16_t){a}"),
      "i64.extend8_s": ("i64", "i64", "(uint64_t)(int64_t)(int8_t){a}"), "i64.extend16_s": ("i64", "i64", "(uint64_t)(int64_t)(int16_t){a}"),
      "i64.extend32_s": ("i64", "i64", "(uint64_t)(int64_t)(int32_t){a}")}
for t in ("i32", "i64"):
    for f in ("f32", "f64"):
        for sg in ("s", "u"):
            UN[f"{t}.trunc_sat_{f}_{sg}"] = (f, t, f"{t}_trunc_sat_{f}_{sg}({{a}})")
LOAD = {"i32.load": ("i32", "ld_u32({m}, {p})"), "i64.load": ("i64", "ld_u64({m}, {p})"), "f32.load": ("f32", "ld_f32({m}, {p})"),
        "f64.load": ("f64", "ld_f64({m}, {p})"), "i32.load8_s": ("i32", "(uint32_t)(int32_t)ld_i8({m}, {p})"),
        "i32.load8_u": ("i32", "(uint32_t)ld_u8({m}, {p})"), "i32.load16_s": ("i32", "(uint32_t)(int32_t)ld_i16({m}, {p})"),
        "i32.load16_u": ("i32", "(uint32_t)ld_u16({m}, {p})"), "i64.load8_s": ("i64", "(uint64_t)(int64_t)ld_i8({m}, {p})"),
        "i64.load8_u": ("i64", "(uint64_t)ld_u8({m}, {p})"), "i64.load16_s": ("i64", "(uint64_t)(int64_t)ld_i16({m}, {p})"),
        "i64.load16_u": ("i64", "(uint64_t)ld_u16({m}, {p})"), "i64.load32_s": ("i64", "(uint64_t)(int64_t)ld_i32s({m}, {p})"),
        "i64.load32_u": ("i64", "(uint64_t)ld_u32({m}, {p})"), "v128.load": ("v128", "ld_v128({m}, {p})"),
        "v128.load8_splat": ("v128", "v_load_splat8({m}, {p})"), "v128.load16_splat": ("v128", "v_load_splat16({m}, {p})"),
        "v128.load32_splat": ("v128", "v_load_splat32({m}, {p})"), "v128.load64_splat": ("v128", "v_load_splat64({m}, {p})"),
        "v128.load32_zero": ("v128", "v_load32_zero({m}, {p})"), "v128.load64_zero": ("v128", "v_load64_zero({m}, {p})")}
for n, (src, dst) in {"8x8_s": ("v_i8", "v_i16"), "8x8_u": ("v_u8", "v_u16"), "16x4_s": ("v_i16", "v_i32"),
                      "16x4_u": ("v_u16", "v_u32"), "32x2_s": ("v_i32", "v_i64"), "32x2_u": ("v_u32", "v_u64")}.items():
    LOAD[f"v128.load{n}"] = ("v128", f"(v128)__builtin_convertvector(__builtin_shufflevector(({src})v_load64_zero({{m}}, {{p}}), ({src})v_load64_zero({{m}}, {{p}}), "
                                     + ", ".join(str(i) for i in range({"8": 8, "16": 4, "32": 2}[n.split("x")[0]])) + f"), {dst})")
STORE = {"i32.store": ("i32", "st_u32({m}, {p}, {v})"), "i64.store": ("i64", "st_u64({m}, {p}, {v})"),
         "f32.store": ("f32", "st_f32({m}, {p}, {v})"), "f64.store": ("f64", "st_f64({m}, {p}, {v})"),
         "i32.store8": ("i32", "st_u8({m}, {p}, (uint8_t){v})"), "i32.store16": ("i32", "st_u16({m}, {p}, (uint16_t){v})"),
         "i64.store8": ("i64", "st_u8({m}, {p}, (uint8_t){v})"), "i64.store16": ("i64", "st_u16({m}, {p}, (uint16_t){v})"),
         "i64.store32": ("i64", "st_u32({m}, {p}, (uint32_t){v})"), "v128.store": ("v128", "st_v128({m}, {p}, {v})")}
# SIMD: lane vector type per shape
VT = {"i8x16": ("v_u8", "v_i8"), "i16x8": ("v_u16", "v_i16"), "i32x4": ("v_u32", "v_i32"), "i64x2": ("v_u64", "v_i64"),
      "f32x4": ("v_f32", "v_f32"), "f64x2": ("v_f64", "v_f64")}
SPLAT = {"i8x16": ("i32", 16, "(uint8_t)"), "i16x8": ("i32", 8, "(uint16_t)"), "i32x4": ("i32", 4, ""),
         "i64x2": ("i64", 2, ""), "f32x4": ("f32", 4, ""), "f64x2": ("f64", 2, "")}
VBIN = {"v128.and": "{a} & {b}", "v128.or": "{a} | {b}", "v128.xor": "{a} ^ {b}", "v128.andnot": "{a} & ~{b}"}
for sh, (u, s) in VT.items():
    for op, sym in (("add", "+"), ("sub", "-"), ("mul", "*")):
        VBIN[f"{sh}.{op}"] = f"(v128)(({u}){{a}} {sym} ({u}){{b}})"
    if sh[0] == "f":
        VBIN[f"{sh}.div"] = f"(v128)(({u}){{a}} / ({u}){{b}})"
        for op, sym in (("eq", "=="), ("ne", "!="), ("lt", "<"), ("gt", ">"), ("le", "<="), ("ge", ">=")):
            VBIN[f"{sh}.{op}"] = f"(v128)(({u}){{a}} {sym} ({u}){{b}})"
    else:
        for op, sym in (("eq", "=="), ("ne", "!=")):
            VBIN[f"{sh}.{op}"] = f"(v128)(({u}){{a}} {sym} ({u}){{b}})"
        for op, sym in (("lt", "<"), ("gt", ">"), ("le", "<="), ("ge", ">=")):
            VBIN[f"{sh}.{op}_s"] = f"(v128)(({s}){{a}} {sym} ({s}){{b}})"
            VBIN[f"{sh}.{op}_u"] = f"(v128)(({u}){{a}} {sym} ({u}){{b}})"
for n in ("min_s", "min_u", "max_s", "max_u", "add_sat_s", "add_sat_u", "sub_sat_s", "sub_sat_u", "avgr_u", "narrow_i16x8_s",
          "narrow_i16x8_u", "swizzle"):
    VBIN[f"i8x16.{n}"] = f"i8x16_{n}({{a}}, {{b}})"
for n in ("min_s", "min_u", "max_s", "max_u", "add_sat_s", "add_sat_u", "sub_sat_s", "sub_sat_u", "avgr_u", "narrow_i32x4_s",
          "narrow_i32x4_u", "q15mulr_sat_s", "extmul_low_i8x16_s", "extmul_high_i8x16_s", "extmul_low_i8x16_u", "extmul_high_i8x16_u"):
    VBIN[f"i16x8.{n}"] = f"i16x8_{n}({{a}}, {{b}})"
for n in ("min_s", "min_u", "max_s", "max_u", "dot_i16x8_s", "extmul_low_i16x8_s", "extmul_high_i16x8_s", "extmul_low_i16x8_u",
          "extmul_high_i16x8_u"):
    VBIN[f"i32x4.{n}"] = f"i32x4_{n}({{a}}, {{b}})"
for n in ("extmul_low_i32x4_s", "extmul_high_i32x4_s", "extmul_low_i32x4_u", "extmul_high_i32x4_u"):
    VBIN[f"i64x2.{n}"] = f"i64x2_{n}({{a}}, {{b}})"
VBIN.update({"i64x2.lt_s": "(v128)((v_i64){a} < (v_i64){b})", "i64x2.gt_s": "(v128)((v_i64){a} > (v_i64){b})",
             "i64x2.le_s": "(v128)((v_i64){a} <= (v_i64){b})", "i64x2.ge_s": "(v128)((v_i64){a} >= (v_i64){b})"})
for sh in ("f32x4", "f64x2"):
    for n in ("min", "max", "pmin", "pmax"):
        VBIN[f"{sh}.{n}"] = f"{sh}_{n}({{a}}, {{b}})"
VUN = {"v128.not": "~{a}"}
for sh, (u, s) in VT.items():
    VUN[f"{sh}.neg"] = f"(v128)(-({s}){{a}})" if sh[0] != "f" else f"{sh}_neg({{a}})"
for n in ("i8x16.abs", "i16x8.abs", "i32x4.abs", "i64x2.abs", "i8x16.popcnt", "f32x4.abs", "f32x4.sqrt", "f32x4.ceil",
          "f32x4.floor", "f32x4.trunc", "f32x4.nearest", "f64x2.abs", "f64x2.sqrt", "f64x2.ceil", "f64x2.floor",
          "f64x2.trunc", "f64x2.nearest", "i16x8.extend_low_i8x16_s", "i16x8.extend_high_i8x16_s",
          "i16x8.extend_low_i8x16_u", "i16x8.extend_high_i8x16_u", "i32x4.extend_low_i16x8_s",
          "i32x4.extend_high_i16x8_s", "i32x4.extend_low_i16x8_u", "i32x4.extend_high_i16x8_u",
          "i64x2.extend_low_i32x4_s", "i64x2.extend_high_i32x4_s", "i64x2.extend_low_i32x4_u",
          "i64x2.extend_high_i32x4_u", "i32x4.trunc_sat_f32x4_s", "i32x4.trunc_sat_f32x4_u",
          "i32x4.trunc_sat_f64x2_s_zero", "i32x4.trunc_sat_f64x2_u_zero", "f32x4.convert_i32x4_s",
          "f32x4.convert_i32x4_u", "f64x2.convert_low_i32x4_s", "f64x2.convert_low_i32x4_u", "f32x4.demote_f64x2_zero",
          "f64x2.promote_low_f32x4", "i16x8.extadd_pairwise_i8x16_s", "i16x8.extadd_pairwise_i8x16_u",
          "i32x4.extadd_pairwise_i16x8_s", "i32x4.extadd_pairwise_i16x8_u"):
    VUN[n] = n.replace(".", "_") + "({a})"
VTEST = {"v128.any_true": "v128_any_true({a})"}
for sh in ("i8x16", "i16x8", "i32x4", "i64x2"):
    VTEST[f"{sh}.all_true"] = f"{sh}_all_true({{a}})"
    VTEST[f"{sh}.bitmask"] = f"{sh}_bitmask({{a}})"
VSHIFT = {f"{sh}.{o}" for sh in ("i8x16", "i16x8", "i32x4", "i64x2") for o in ("shl", "shr_s", "shr_u")}


def cname(s):
    return "".join(c if c.isalnum() else "_" for c in s)


class Frame:
    __slots__ = ("kind", "lab", "params", "results", "base", "eh_out", "eh_in", "has_else", "catches", "ehid")

    def __init__(self, **k):
        for a in self.__slots__:
            setattr(self, a, k.get(a))


class FuncGen:
    def __init__(self, g, fi, k):
        self.g, self.m, self.fi = g, g.m, fi
        self.params, self.results = self.m.ftype(fi)
        self.locs_decl, self.code = self.m.body(k)
        self.ltypes = list(self.params) + [t for n, t in self.locs_decl for _ in range(n)]
        self.out = []
        self.st = []
        self.slots = set()
        self.nlab = 0
        self.pending = self.pzero = self.pcost = 0
        self.popc = collections.Counter()
        self.dead = False
        self.frames = []
        self.has_try = any(n == "try_table" for n, _ in self.code)

    def slot(self, k, t):
        n = f"s{k}{SC[t]}"
        self.slots.add((n, t))
        return n

    def push(self, t, expr):
        n = self.slot(len(self.st), t)
        self.out.append(f"{n} = {expr};")
        self.st.append(t)

    def pop(self):
        t = self.st.pop()
        return self.slot(len(self.st), t), t

    def flush(self):
        if self.g.fuel and self.pending:
            self.out.append(f"fuel += {self.pending};")
            if self.g.fuelprof:
                self.out.append(f"I->fprof[{self.fi}] += {self.pending};")
        if self.g.profile:
            for o, n in self.popc.items():
                self.out.append(f"I->opc[{OPIDS[o]}] += {n};")
            self.popc = collections.Counter()
            if self.pzero:
                self.out.append(f"I->prof[0] += {self.pzero};")
            if self.pcost:
                self.out.append(f"I->prof[13] += {self.pcost};")
        self.pending = self.pzero = self.pcost = 0

    def prof(self, k, n="1"):
        if self.g.profile:
            self.out.append(f"I->prof[{PROF[k]}] += {n};")

    def save_fuel(self):
        if self.g.fuel:
            self.out.append("I->fuel = fuel;")

    def load_fuel(self):
        if self.g.fuel:
            self.out.append("fuel = I->fuel;")

    def fuel_check(self):
        if self.g.fuel:
            self.out.append(f"FUEL_CHECK_AT({self.fi});" if self.g.fuelprof else "FUEL_CHECK();")

    def bt(self, b):
        if b[0] == "empty":
            return [], []
        if b[0] == "val":
            return [], [b[1]]
        return self.m.types[b[1]]

    def label_arity(self, f):
        return f.params if f.kind == "loop" else f.results

    def branch_to(self, depth, cond=None):
        """Emit a branch to the frame `depth` levels out (values on top of the stack carried)."""
        f = self.frames[-1 - depth]
        types = self.label_arity(f)
        n = len(types)
        moves = []
        for i, t in enumerate(types):
            src = self.slot(len(self.st) - n + i, t)
            dst = self.slot(f.base + i, t)
            if src != dst:
                moves.append(f"{dst} = {src};")
        eh = []
        cur = self.frames[-1].eh_in if self.frames else "eh0"
        if self.has_try and f.eh_out != cur:
            eh.append(f"I->eh_top = {f.eh_out};")
        if f.kind == "func":
            body = moves + eh + self.ret_stmt(types)
        else:
            body = moves + eh + [f"goto {'T' if f.kind == 'loop' else 'L'}{f.lab};"]
        if cond is None:
            self.out.extend(body)
        else:
            self.out.append(f"if ({cond}) {{ " + " ".join(body) + " }")

    def ret_stmt(self, types):
        pre = []
        if self.has_try:
            pre.append("I->eh_top = eh0;")
        if self.g.fuel:
            pre.append("I->fuel = fuel;")
        if not types:
            return pre + ["return;"]
        return pre + [f"return {self.slot(len(self.st) - 1, types[0])};"]

    def call_expr(self, target, args, ptypes, rtypes, fnptr=None):
        call = f"{fnptr or target}(I{''.join(', ' + a for a in args)})"
        if self.g.fuelprof and target and target.startswith("cxe_imp_") and not target.endswith("__yield"):
            # host charges of this import go to the calling function
            self.save_fuel()
            self.out.append("{ int64_t f0_ = I->fuel;")
            if rtypes:
                self.push(rtypes[0], call)
            else:
                self.out.append(call + ";")
            self.out.append(f"I->fprof[{self.fi}] += (uint64_t)(I->fuel - f0_); }}")
            self.load_fuel()
            return
        self.save_fuel()
        if rtypes:
            self.push(rtypes[0], call)
        else:
            self.out.append(call + ";")
        self.load_fuel()

    def gen(self):
        g, m = self.g, self.m
        self.frames.append(Frame(kind="func", lab=0, params=[], results=list(self.results), base=0, eh_out="eh0", eh_in="eh0"))
        if g.fuel:
            self.pending = 1  # the CLI charges 1 per function entry
            self.flush()
        self.fuel_check()
        self.prof("entry")
        for op, imm in self.code:
            if self.dead:
                self.dead_op(op, imm)
                continue
            if g.fuel and op not in g.zero_cost:
                self.pending += 1
            if g.profile:
                self.popc[op] += 1
                if op in ZERO_COST:
                    self.pzero += 1
                else:
                    self.pcost += 1
            if op in FLUSH:
                self.flush()
            self.op(op, imm)
        return self.emit()

    def dead_op(self, op, imm):
        if op in ("block", "loop", "if", "try_table"):
            self.frames.append(Frame(kind="dead"))
        elif op == "else":
            f = self.frames[-1]
            if f.kind != "dead":
                self.out.append(f"E{f.lab}:;")
                f.has_else = True
                del self.st[f.base:]
                self.st.extend(f.params)
                self.dead = False
        elif op == "end":
            f = self.frames[-1]
            if f.kind == "dead":
                self.frames.pop()
            else:
                self.pending = 0
                self.end_frame(f)

    def end_frame(self, f):
        self.frames.pop()
        del self.st[f.base:]
        self.st.extend(f.results)
        self.dead = False
        if f.kind == "func":
            self.frames.append(f)
            return
        if f.kind == "if" and not f.has_else:
            self.out.append(f"E{f.lab}:;")
        if f.kind == "try":
            self.out.append(f"I->eh_top = {f.eh_out};")
        if f.kind != "loop":
            self.out.append(f"L{f.lab}:;")

    def newlab(self):
        self.nlab += 1
        return self.nlab

    def op(self, op, imm):
        g, m, out = self.g, self.m, self.out
        cur_eh = self.frames[-1].eh_in
        if op in ("block", "loop", "if", "try_table"):
            params, results = self.bt(imm[0] if op == "try_table" else imm)
            cond = None
            if op == "if":
                cond, _ = self.pop()
            lab = self.newlab()
            f = Frame(kind={"try_table": "try"}.get(op, op), lab=lab, params=list(params), results=list(results),
                      base=len(self.st) - len(params), eh_out=cur_eh, eh_in=cur_eh, has_else=False)
            if params and op != "loop":
                raise NotImplementedError("block parameters")
            if op == "loop":
                self.frames.append(f)
                out.append(f"T{lab}:;")
                self.fuel_check()
                self.prof("loop")
                return
            if op == "if":
                out.append(f"if (!({cond})) goto E{lab};")
                self.frames.append(f)
                return
            if op == "try_table":
                self.prof("try")
                f.eh_in = f"(&ehf{lab})"
                f.catches = imm[1]
                g.uses_setjmp = True
                self.frames.append(f)
                self.ehframes.append(lab)
                out.append(f"ehf{lab}.prev = I->eh_top; I->eh_top = &ehf{lab};")
                out.append(f"if (W2C_UNLIKELY(w2c_sj_set(ehf{lab}.jb))) {{")
                out.append(f"I->eh_top = ehf{lab}.prev;")
                self.load_fuel()
                out.append("{ w2c_exn *X = &I->exn[I->cur_exn - 1]; (void)X;")
                # catch labels are relative to the try_table's enclosing context
                for ck, tag, l in imm[1]:
                    tf = self.frames[-2 - l]
                    tt = self.label_arity(tf)
                    vals = []
                    if ck in (0, 1):
                        ptypes = g.tag_params(tag)
                        vals = [f"X->v[{i}].{GF[t]}" for i, t in enumerate(ptypes)]
                    if ck in (1, 3):
                        vals.append("I->cur_exn")
                    assigns = [f"{self.slot(tf.base + i, t)} = {v};" for i, (t, v) in enumerate(zip(tt, vals))]
                    eh = [f"I->eh_top = {tf.eh_out};"] if tf.eh_out != cur_eh else []
                    tgt = f"goto {'T' if tf.kind == 'loop' else 'L'}{tf.lab};" if tf.kind != "func" else " ".join(self.ret_from_catch(tt, assigns))
                    body = assigns + eh + [tgt] if tf.kind != "func" else [tgt]
                    if ck in (0, 1):
                        out.append(f"if (X->tag == {tag}) {{ {' '.join(body)} }}")
                    else:
                        out.append(f"{{ {' '.join(body)} }}")
                out.append("w2c_throw_cur(I); } }")
                return
            self.frames.append(f)
            return
        if op == "else":
            f = self.frames[-1]
            self.branch_to(0)
            out.append(f"E{f.lab}:;")
            f.has_else = True
            del self.st[f.base:]
            self.st.extend(f.params)
            return
        if op == "end":
            self.end_frame(self.frames[-1])
            if len(self.frames) == 1 and self.frames[0].kind == "func" and self.code_done():
                pass
            return
        if op == "br":
            self.branch_to(imm)
            self.dead = True
            return
        if op == "br_if":
            c, _ = self.pop()
            self.branch_to(imm, cond=c)
            return
        if op == "br_table":
            idx, _ = self.pop()
            labs, dflt = imm
            out.append(f"switch ({idx}) {{")
            for i, l in enumerate(labs):
                out.append(f"case {i}: {{")
                self.branch_to(l)
                out.append("}")
            out.append("default: {")
            self.branch_to(dflt)
            out.append("} }")
            self.dead = True
            return
        if op == "return":
            self.branch_to(len(self.frames) - 1)
            self.dead = True
            return
        if op == "unreachable":
            self.save_fuel()
            out.append("w2c_trap(I, W2C_TRAP_UNREACHABLE);")
            self.dead = True
            return
        if op == "nop":
            return
        if op == "drop":
            self.pop()
            return
        if op == "select":
            c, _ = self.pop()
            b, t = self.pop()
            a, _ = self.pop()
            self.push(t, f"{c} ? {a} : {b}")
            return
        if op == "local.get":
            self.push(self.ltypes[imm], f"l{imm}")
            return
        if op == "local.set":
            v, _ = self.pop()
            out.append(f"l{imm} = {v};")
            return
        if op == "local.tee":
            v, t = self.st[-1], None
            out.append(f"l{imm} = {self.slot(len(self.st) - 1, self.st[-1])};")
            return
        if op == "global.get":
            t = g.gtypes[imm]
            self.push(t, f"I->G[{imm}].{GF[t]}")
            return
        if op == "global.set":
            v, t = self.pop()
            out.append(f"I->G[{imm}].{GF[t]} = {v};")
            return
        if op == "call":
            ps, rs = m.ftype(imm)
            args = [self.pop()[0] for _ in ps][::-1]
            self.prof("imp" if imm < m.nimp else "call")
            self.call_expr(g.fname(imm), args, ps, rs)
            return
        if op == "call_indirect":
            ti, tab = imm
            ps, rs = m.types[ti]
            idx, _ = self.pop()
            args = [self.pop()[0] for _ in ps][::-1]
            sig = f"{CT[rs[0]] if rs else 'void'} (*)(w2c_inst *{''.join(', ' + CT[p] for p in ps)})"
            self.prof("ind")
            fp = f"(({sig})w2c_indirect(I, {idx}, {g.canon[ti]}))"
            self.call_expr(None, args, ps, rs, fnptr=fp)
            return
        if op == "throw":
            ptypes = g.tag_params(imm)
            vals = [self.pop()[0] for _ in ptypes][::-1]
            self.prof("throw")
            out.append(f"{{ uint32_t x_ = w2c_exn_new(I, {imm});")
            for i, (t, v) in enumerate(zip(ptypes, vals)):
                out.append(f"I->exn[x_ - 1].v[{i}].{GF[t]} = {v};")
            self.save_fuel()
            out.append("I->cur_exn = x_; w2c_throw_cur(I); }")
            self.dead = True
            return
        if op == "throw_ref":
            x, _ = self.pop()
            self.save_fuel()
            out.append(f"w2c_throw_ref(I, {x});")
            self.dead = True
            return
        if op in LOAD:
            a, _ = self.pop()
            t, e = LOAD[op]
            self.push(t, e.format(m="M", p=f"(uint64_t){a} + {imm[1]}u"))
            return
        if op in STORE:
            v, _ = self.pop()
            a, _ = self.pop()
            out.append(STORE[op][1].format(m="M", p=f"(uint64_t){a} + {imm[1]}u", v=v) + ";")
            return
        if op == "memory.size":
            self.push("i32", "(uint32_t)I->pages")
            return
        if op == "memory.grow":
            d, _ = self.pop()
            self.prof("grow")
            self.push("i32", f"w2c_mem_grow(I, {d})")
            out.append("M = I->mem;")
            return
        if op == "memory.copy":
            n, _ = self.pop()
            s, _ = self.pop()
            d, _ = self.pop()
            self.prof("copy")
            self.prof("copyb", n)
            if g.profile:
                out.append(("I->fuel = fuel; " if g.fuel else "") + f"w2c_prof_bulk(I, 0, {d}, {s}, {n});")
            if g.fuel:
                self.flush()  # conf 6 Nov: the CLI checks fuel at a bulk op (after charging its bytes), so cuts land here first
                out.append(f"fuel += {n};")
                if g.fuelprof:
                    out.append(f"I->fprof[{self.fi}] += {n};")
            out.append(f"mem_copy(I, {d}, {s}, {n});")
            self.fuel_check()
            return
        if op == "memory.fill":
            n, _ = self.pop()
            v, _ = self.pop()
            d, _ = self.pop()
            self.prof("fill")
            self.prof("fillb", n)
            if g.profile:
                out.append(("I->fuel = fuel; " if g.fuel else "") + f"w2c_prof_bulk(I, 1, {d}, {v}, {n});")
            if g.fuel:
                self.flush()  # conf 6 Nov: the CLI checks fuel at a bulk op (after charging its bytes), so cuts land here first
                out.append(f"fuel += {n};")
                if g.fuelprof:
                    out.append(f"I->fprof[{self.fi}] += {n};")
            out.append(f"mem_fill(I, {d}, {v}, {n});")
            self.fuel_check()
            return
        if op == "i32.const":
            self.push("i32", f"{imm & 0xffffffff}u")
            return
        if op == "i64.const":
            self.push("i64", f"{imm & 0xffffffffffffffff}ull")
            return
        if op == "f32.const":
            self.push("f32", f"f32_bits({struct.unpack('<I', imm)[0]:#x}u)")
            return
        if op == "f64.const":
            self.push("f64", f"f64_bits({struct.unpack('<Q', imm)[0]:#x}ull)")
            return
        if op in BIN:
            b, _ = self.pop()
            a, _ = self.pop()
            self.push(BIN[op][1], BIN[op][2].format(a=a, b=b))
            return
        if op in UN:
            a, _ = self.pop()
            self.push(UN[op][1], UN[op][2].format(a=a))
            return
        # SIMD
        if op == "v128.const":
            self.push("v128", "(v128){" + ", ".join(str(x) for x in imm) + "}")
            return
        if op in VBIN:
            b, _ = self.pop()
            a, _ = self.pop()
            self.push("v128", VBIN[op].format(a=a, b=b))
            return
        if op in VUN:
            a, _ = self.pop()
            self.push("v128", VUN[op].format(a=a))
            return
        if op in VTEST:
            a, _ = self.pop()
            self.push("i32", VTEST[op].format(a=a))
            return
        if op in VSHIFT:
            n, _ = self.pop()
            a, _ = self.pop()
            self.push("v128", f"{op.replace('.', '_')}({a}, {n})")
            return
        if op == "v128.bitselect":
            c, _ = self.pop()
            b, _ = self.pop()
            a, _ = self.pop()
            self.push("v128", f"({a} & {c}) | ({b} & ~{c})")
            return
        if op == "i8x16.shuffle":
            b, _ = self.pop()
            a, _ = self.pop()
            self.push("v128", f"(v128)__builtin_shufflevector((v_u8){a}, (v_u8){b}, {', '.join(str(x) for x in imm)})")
            return
        if op.endswith(".splat"):
            sh = op.split(".")[0]
            x, _ = self.pop()
            st, nl, cast = SPLAT[sh]
            self.push("v128", f"(v128)(({VT[sh][0]}){{{', '.join([cast + x] * nl)}}})")
            return
        if ".extract_lane" in op:
            sh = op.split(".")[0]
            a, _ = self.pop()
            u, s = VT[sh]
            if op.endswith("_s"):
                self.push("i32", f"(uint32_t)(int32_t)(({s}){a})[{imm}]")
            else:
                self.push(SPLAT[sh][0], f"({VT[sh][0]}){a})[{imm}]".replace(f"({VT[sh][0]}){a})", f"(({VT[sh][0]}){a})"))
            return
        if ".replace_lane" in op:
            sh = op.split(".")[0]
            x, _ = self.pop()
            a, _ = self.pop()
            u = VT[sh][0]
            self.push("v128", f"({{ {u} t_ = ({u}){a}; t_[{imm}] = {SPLAT[sh][2]}{x}; (v128)t_; }})")
            return
        if op.endswith("_lane") and op.startswith("v128.load"):
            v, _ = self.pop()
            a, _ = self.pop()
            bits = op[len("v128.load"):].split("_")[0]
            self.push("v128", f"v_load{bits}_lane(M, (uint64_t){a} + {imm[0][1]}u, {v}, {imm[1]})")
            return
        if op.endswith("_lane") and op.startswith("v128.store"):
            v, _ = self.pop()
            a, _ = self.pop()
            bits = op[len("v128.store"):].split("_")[0]
            out.append(f"v_store{bits}_lane(M, (uint64_t){a} + {imm[0][1]}u, {v}, {imm[1]});")
            return
        raise NotImplementedError(op)

    def ret_from_catch(self, tt, assigns):
        # a catch that targets the function label returns the caught values
        pre = ["I->eh_top = eh0;"]
        if self.g.fuel:
            pre.append("I->fuel = fuel;")
        if not tt:
            return pre + ["return;"]
        return assigns + pre + [f"return {self.slot(self.frames[0].base, tt[0])};"]

    def code_done(self):
        return True

    def emit(self):
        g = self.g
        f = self.frames[0]
        tail = [] if self.dead else self.ret_stmt(f.results)
        lines = [g.proto(self.fi) + " {"]
        vol = self.volatile_locals() if self.has_try else set()
        for i, t in enumerate(self.ltypes):
            if i >= len(self.params):
                lines.append(f"{'volatile ' if i in vol else ''}{CT[t]} l{i} = {'{0}' if t == 'v128' else '0'};")
        if vol:
            # parameters written inside a try body: shadow them with volatile copies
            for i in sorted(v for v in vol if v < len(self.params)):
                lines.append(f"volatile {CT[self.ltypes[i]]} l{i}_v = l{i};")
        for n, t in sorted(self.slots):
            lines.append(f"{CT[t]} {n} = {{0}};" if t == "v128" else f"{CT[t]} {n} = 0;")
        lines.append("uint8_t *M = I->mem; (void)M;")
        if g.fuel:
            lines.append("int64_t fuel = I->fuel;")
        if self.has_try:
            lines.append("w2c_eh_frame *eh0 = I->eh_top;")
            for lab in self.ehframes:
                lines.append(f"w2c_eh_frame ehf{lab};")
        body = "\n".join(self.out)
        if vol:
            for i in sorted(v for v in vol if v < len(self.params)):
                import re
                body = re.sub(rf"\bl{i}\b", f"l{i}_v", body)
        lines.append(body)
        # function end: the final 'end' leaves results on the stack
        lines.extend(tail)
        lines.append("}")
        return "\n".join(lines)

    def volatile_locals(self):
        vol = set()
        depth = 0
        stack = []
        for op, imm in self.code:
            if op in ("block", "loop", "if"):
                stack.append(False)
            elif op == "try_table":
                stack.append(True)
            elif op == "end":
                if stack:
                    stack.pop()
            elif op in ("local.set", "local.tee") and any(stack):
                vol.add(imm)
        return vol


class Gen:
    def __init__(self, m, prefix, fuel, zero_cost, profile=False, split=1, fuelprof=False):
        self.m, self.prefix, self.fuel, self.profile, self.split = m, prefix, fuel, profile, split
        self.fuelprof = fuelprof
        self.zero_cost = zero_cost
        self.uses_setjmp = False
        self.gtypes = [g[0] for i in m.imports if i[2] == 3 for g in [i[3]]] + [g[0] for g in m.globals]
        if any(i[2] == 3 for i in m.imports):
            raise NotImplementedError("imported globals")
        canon = {}
        self.canon = []
        for t in m.types:
            key = (tuple(t[0]), tuple(t[1]))
            canon.setdefault(key, len(canon))
            self.canon.append(canon[key])
        # multi-value is supported for block types (C++ landing pads: [] -> [i32, exnref]), not for functions
        for t in set(m.funcs) | {i[3] for i in m.imports if i[2] == 0}:
            if len(m.types[t][1]) > 1:
                raise NotImplementedError("multi-value function results")
        self.fimports = [i for i in m.imports if i[2] == 0]

    def tag_params(self, tag):
        alltags = self.m.import_tags + self.m.tags
        return self.m.types[alltags[tag]][0]

    def fname(self, fi):
        if fi < self.m.nimp:
            mod, name, _, _ = self.fimports[fi]
            return f"cxe_imp_{cname(mod)}__{cname(name)}"
        return f"f{fi}"

    def proto(self, fi, static=True):
        ps, rs = self.m.ftype(fi)
        r = CT[rs[0]] if rs else "void"
        args = "".join(f", {CT[p]} l{i}" for i, p in enumerate(ps))
        if fi >= self.m.nimp and static:
            # one file: static; split into several files: hidden (visible across the parts, not outside the library)
            return f"{'__attribute__((visibility(\"hidden\"))) ' if self.split > 1 else 'static '}{r} {self.fname(fi)}(w2c_inst *I{args})"
        return f"{r} {self.fname(fi)}(w2c_inst *I{args})"

    def run(self, outs):
        m, P = self.m, self.prefix
        sizes = [0] * len(outs)

        def w(t):
            for o in outs:
                o.write(t)
        w(f"/* generated by tools/cxe/w2c.py from a WebAssembly module: {len(m.funcs)} functions, fuel {'on' if self.fuel else 'off'} */\n")
        w('#include "w2c_rt.h"\n#include <stdlib.h>\n')
        if self.fuelprof:
            # 10 Nov (Rule Checker, confirmed): the count went up at EVERY out-of-fuel check, but w2c_out_of_fuel usually just refills the next
            # slice (100k slices of the 10M draft turn and the 200k first turn): step_groups_t read 2.5 'cuts'/g from 315k fuel/g. Count only a
            # real cut: the host's w2c_fuel_will_cut (the same reserve arithmetic, no side effects) says this check suspends the bot.
            w("int w2c_fuel_will_cut(w2c_inst *I);\n")
            w(f"#define FUEL_CHECK_AT(F) do {{ if (W2C_UNLIKELY(fuel >= 0)) {{ I->fuel = fuel; if (w2c_fuel_will_cut(I)) I->fprof[{len(m.funcs) + m.nimp} + (F)]++; w2c_out_of_fuel(I); fuel = I->fuel; }} }} while (0)\n")
        if self.fuel:
            w("#define FUEL_CHECK() do { if (W2C_UNLIKELY(fuel >= 0)) { I->fuel = fuel; w2c_out_of_fuel(I); fuel = I->fuel; } } while (0)\n")
        w("void *w2c_indirect(w2c_inst *I, uint32_t idx, uint32_t type);\n")
        if self.profile:
            w("void w2c_prof_bulk(w2c_inst *I, int kind, uint32_t d, uint32_t s, uint32_t n);\n")
        for fi in range(m.nimp):
            w(f"extern {self.proto(fi)};\n")
        for fi in range(m.nimp, m.nimp + len(m.funcs)):
            w(self.proto(fi) + ";\n")
        # canonical type ids for call_indirect, per function
        ftypeid = [self.canon[self.fimports[fi][3]] if fi < m.nimp else self.canon[m.funcs[fi - m.nimp]]
                   for fi in range(m.nimp + len(m.funcs))]
        for k in range(len(m.funcs)):
            fi = m.nimp + k
            fg = FuncGen(self, fi, k)
            fg.ehframes = []
            try:
                body = fg.gen() + "\n"
                part = sizes.index(min(sizes[:self.split] if len(outs) > self.split else sizes))  # balance the code parts by generated size
                outs[part].write(body)
                sizes[part] += len(body)
            except NotImplementedError as e:
                raise NotImplementedError(f"function {fi} ({m.names.get(fi, '?')}): {e}")
        # data, init and exports: in the extra data part when split (OUT.data.c: a data-only flip of a bot changes only this part, so
        # cxebuild's object cache reuses every compiled code part), else in the one file
        w = outs[-1].write
        # data segments
        for i, (kind, off, data) in enumerate(m.datas):
            w(f"static const uint8_t data{i}[{max(1, len(data))}] = {{{','.join(str(b) for b in data) or '0'}}};\n")
        # init
        w(f"static int {P}_init(w2c_inst *I) {{\n")
        mn, mx = m.mems[0] if m.mems else (0, 0)
        w(f"  if (w2c_mem_alloc(I, {mn}u, {mx if mx is not None else 65536}u)) return 1;\n")
        for i, (t, mut, init) in enumerate(m.globals):
            if init[0] in ("i32", "i64"):
                w(f"  I->G[{i}].{GF[t]} = {init[1] & ((1 << 64) - 1)}ull;\n")
            elif init[0] == "f32":
                w(f"  I->G[{i}].f32 = f32_bits({struct.unpack('<I', init[1])[0]:#x}u);\n")
            elif init[0] == "f64":
                w(f"  I->G[{i}].f64 = f64_bits({struct.unpack('<Q', init[1])[0]:#x}ull);\n")
            elif init[0] == "global":
                w(f"  I->G[{i}] = I->G[{init[1]}];\n")
            else:
                w(f"  I->G[{i}].i32 = 0;\n")
        ntab = m.tables[0][1][0] if m.tables else 0
        w(f"  I->ntable = {ntab}u; I->table = (w2c_funcref *)calloc({max(1, ntab)}, sizeof(w2c_funcref));\n")
        for kind, ti, off, fis in m.elems:
            if kind != "active":
                continue
            base = off[1] if off[0] == "i32" else f"I->G[{off[1]}].i32"
            for j, fi in enumerate(fis):
                w(f"  I->table[{base} + {j}] = (w2c_funcref){{{ftypeid[fi]}u, (void *){self.fname(fi)}}};\n")
        for i, (kind, off, data) in enumerate(m.datas):
            if kind == "active" and data:
                base = f"{off[1] & 0xffffffff}u" if off[0] == "i32" else f"I->G[{off[1]}].i32"
                w(f"  memcpy(I->mem + {base}, data{i}, {len(data)});\n")
        w("  return 0;\n}\n")
        # exports
        w(f"static void *{P}_export(const char *n) {{\n")
        for name, kind, idx in m.exports:
            if kind == 0:
                w(f'  if (!strcmp(n, "{name}")) return (void *){self.fname(idx)};\n')
        w("  return 0;\n}\n")
        w(f'const w2c_module {P}_module = {{"{P}", {len(m.funcs)}u, {m.nimp}u, {len(m.types)}u, {P}_init, {P}_export}};\n')


def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    prefix = a[a.index("--prefix") + 1] if "--prefix" in a else "mod"
    zero = set(ZERO_COST)
    if "--zero-cost" in a:
        zero = set(a[a.index("--zero-cost") + 1].split(","))
    m = wasmparse.Module(src)
    split = int(a[a.index("--split") + 1]) if "--split" in a else 1
    g = Gen(m, prefix, "--fuel" in a, zero, "--profile" in a, split, "--fuelprof" in a)
    if "--opids" in a:  # the opcode index the --profile counters use
        with open(a[a.index("--opids") + 1], "w") as f:
            f.write("\n".join(sorted(OPIDS, key=OPIDS.get)) + "\n")
    if "--protos" in a:
        # import prototypes for the host (compile-time check that host and module agree)
        with open(a[a.index("--protos") + 1], "w") as f:
            f.write("/* generated by tools/cxe/w2c.py --protos */\n#ifdef __cplusplus\nextern \"C\" {\n#endif\n")
            for fi in range(m.nimp):
                f.write(g.proto(fi) + ";\n")
            f.write("#ifdef __cplusplus\n}\n#endif\n")
    if split <= 1:
        tmp = dst + ".tmp"
        with open(tmp, "w") as f:
            g.run([f])
        os.replace(tmp, dst)
    else:  # DST.0.c ... DST.<N-1>.c
        base = dst[:-2] if dst.endswith(".c") else dst
        names = [f"{base}.{i}.c" for i in range(split)] + [f"{base}.data.c"]
        fs = [open(n + ".tmp", "w") for n in names]
        g.run(fs)
        for n, f in zip(names, fs):
            f.close()
            os.replace(n + ".tmp", n)


if __name__ == "__main__":
    main()
