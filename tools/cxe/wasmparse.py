"""wasmparse: a WebAssembly binary decoder for cxe (the C++ test engine): sections, types, imports, exports, globals,
data/element segments, tags and every function body decoded into instructions (name, immediates).
Covers the instruction set the engine and nova bots use: MVP, sign-extension, saturating truncation, bulk memory,
multi-value block types, fixed-width SIMD and the exception-handling proposal (try_table / throw / throw_ref).
usage: python3 -I wasmparse.py FILE.wasm [--exports] [--imports] [--ops]"""
import struct
import sys

VT = {0x7f: "i32", 0x7e: "i64", 0x7d: "f32", 0x7c: "f64", 0x7b: "v128", 0x70: "funcref", 0x6f: "externref", 0x69: "exnref"}


class R:
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def u8(self):
        v = self.b[self.p]
        self.p += 1
        return v

    def u32(self):
        r = s = 0
        while True:
            x = self.b[self.p]
            self.p += 1
            r |= (x & 0x7f) << s
            s += 7
            if not x & 0x80:
                return r

    def sleb(self, bits):
        r = s = 0
        while True:
            x = self.b[self.p]
            self.p += 1
            r |= (x & 0x7f) << s
            s += 7
            if not x & 0x80:
                break
        if s < 64 and x & 0x40:
            r -= 1 << s
        m = (1 << bits) - 1
        r &= m
        return r - (1 << bits) if r >> (bits - 1) else r

    def raw(self, n):
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def name(self):
        return self.raw(self.u32()).decode("utf-8", "replace")

    def vt(self):
        t = self.u8()
        if t in (0x63, 0x64):  # (ref null ht) / (ref ht): typed references, read the heap type
            self.sleb(33)
            return "ref"
        return VT[t]

    def blocktype(self):
        t = self.b[self.p]
        if t == 0x40:
            self.p += 1
            return ("empty",)
        if t in VT or t in (0x63, 0x64):
            return ("val", self.vt())
        return ("type", self.sleb(33))

    def limits(self):
        f = self.u8()
        mn = self.u32()
        mx = self.u32() if f & 1 else None
        return mn, mx


# opcode -> (name, immediate kind)
OPS = {0x00: ("unreachable", ""), 0x01: ("nop", ""), 0x02: ("block", "bt"), 0x03: ("loop", "bt"), 0x04: ("if", "bt"),
       0x05: ("else", ""), 0x08: ("throw", "u"), 0x0a: ("throw_ref", ""), 0x0b: ("end", ""), 0x0c: ("br", "u"),
       0x0d: ("br_if", "u"), 0x0e: ("br_table", "table"), 0x0f: ("return", ""), 0x10: ("call", "u"),
       0x11: ("call_indirect", "uu"), 0x1a: ("drop", ""), 0x1b: ("select", ""), 0x1c: ("select", "selt"),
       0x1f: ("try_table", "try"), 0x20: ("local.get", "u"), 0x21: ("local.set", "u"), 0x22: ("local.tee", "u"),
       0x23: ("global.get", "u"), 0x24: ("global.set", "u"), 0x25: ("table.get", "u"), 0x26: ("table.set", "u"),
       0x3f: ("memory.size", "b"), 0x40: ("memory.grow", "b"), 0x41: ("i32.const", "i32"), 0x42: ("i64.const", "i64"),
       0x43: ("f32.const", "f32"), 0x44: ("f64.const", "f64"), 0xd0: ("ref.null", "b"), 0xd1: ("ref.is_null", ""),
       0xd2: ("ref.func", "u")}
for i, n in enumerate("i32.load i64.load f32.load f64.load i32.load8_s i32.load8_u i32.load16_s i32.load16_u i64.load8_s "
                      "i64.load8_u i64.load16_s i64.load16_u i64.load32_s i64.load32_u i32.store i64.store f32.store "
                      "f64.store i32.store8 i32.store16 i64.store8 i64.store16 i64.store32".split()):
    OPS[0x28 + i] = (n, "mem")
for i, n in enumerate(
        "i32.eqz i32.eq i32.ne i32.lt_s i32.lt_u i32.gt_s i32.gt_u i32.le_s i32.le_u i32.ge_s i32.ge_u i64.eqz i64.eq "
        "i64.ne i64.lt_s i64.lt_u i64.gt_s i64.gt_u i64.le_s i64.le_u i64.ge_s i64.ge_u f32.eq f32.ne f32.lt f32.gt "
        "f32.le f32.ge f64.eq f64.ne f64.lt f64.gt f64.le f64.ge i32.clz i32.ctz i32.popcnt i32.add i32.sub i32.mul "
        "i32.div_s i32.div_u i32.rem_s i32.rem_u i32.and i32.or i32.xor i32.shl i32.shr_s i32.shr_u i32.rotl i32.rotr "
        "i64.clz i64.ctz i64.popcnt i64.add i64.sub i64.mul i64.div_s i64.div_u i64.rem_s i64.rem_u i64.and i64.or "
        "i64.xor i64.shl i64.shr_s i64.shr_u i64.rotl i64.rotr f32.abs f32.neg f32.ceil f32.floor f32.trunc f32.nearest "
        "f32.sqrt f32.add f32.sub f32.mul f32.div f32.min f32.max f32.copysign f64.abs f64.neg f64.ceil f64.floor "
        "f64.trunc f64.nearest f64.sqrt f64.add f64.sub f64.mul f64.div f64.min f64.max f64.copysign i32.wrap_i64 "
        "i32.trunc_f32_s i32.trunc_f32_u i32.trunc_f64_s i32.trunc_f64_u i64.extend_i32_s i64.extend_i32_u "
        "i64.trunc_f32_s i64.trunc_f32_u i64.trunc_f64_s i64.trunc_f64_u f32.convert_i32_s f32.convert_i32_u "
        "f32.convert_i64_s f32.convert_i64_u f32.demote_f64 f64.convert_i32_s f64.convert_i32_u f64.convert_i64_s "
        "f64.convert_i64_u f64.promote_f32 i32.reinterpret_f32 i64.reinterpret_f64 f32.reinterpret_i32 "
        "f64.reinterpret_i64 i32.extend8_s i32.extend16_s i64.extend8_s i64.extend16_s i64.extend32_s".split()):
    OPS[0x45 + i] = (n, "")
FC = {i: (n, "") for i, n in enumerate("i32.trunc_sat_f32_s i32.trunc_sat_f32_u i32.trunc_sat_f64_s i32.trunc_sat_f64_u "
                                       "i64.trunc_sat_f32_s i64.trunc_sat_f32_u i64.trunc_sat_f64_s i64.trunc_sat_f64_u".split())}
FC.update({8: ("memory.init", "ub"), 9: ("data.drop", "u"), 10: ("memory.copy", "bb"), 11: ("memory.fill", "b"),
           12: ("table.init", "uu"), 13: ("elem.drop", "u"), 14: ("table.copy", "uu"), 15: ("table.grow", "u"),
           16: ("table.size", "u"), 17: ("table.fill", "u")})
# SIMD (0xfd prefix), by sub-opcode; immediates: mem = memarg, lane = 1 byte, memlane = memarg + lane, c16 = 16 bytes
_SIMD = """0 v128.load mem;1 v128.load8x8_s mem;2 v128.load8x8_u mem;3 v128.load16x4_s mem;4 v128.load16x4_u mem;
5 v128.load32x2_s mem;6 v128.load32x2_u mem;7 v128.load8_splat mem;8 v128.load16_splat mem;9 v128.load32_splat mem;
10 v128.load64_splat mem;11 v128.store mem;12 v128.const c16;13 i8x16.shuffle c16;14 i8x16.swizzle;15 i8x16.splat;
16 i16x8.splat;17 i32x4.splat;18 i64x2.splat;19 f32x4.splat;20 f64x2.splat;21 i8x16.extract_lane_s lane;
22 i8x16.extract_lane_u lane;23 i8x16.replace_lane lane;24 i16x8.extract_lane_s lane;25 i16x8.extract_lane_u lane;
26 i16x8.replace_lane lane;27 i32x4.extract_lane lane;28 i32x4.replace_lane lane;29 i64x2.extract_lane lane;
30 i64x2.replace_lane lane;31 f32x4.extract_lane lane;32 f32x4.replace_lane lane;33 f64x2.extract_lane lane;
34 f64x2.replace_lane lane;35 i8x16.eq;36 i8x16.ne;37 i8x16.lt_s;38 i8x16.lt_u;39 i8x16.gt_s;40 i8x16.gt_u;41 i8x16.le_s;
42 i8x16.le_u;43 i8x16.ge_s;44 i8x16.ge_u;45 i16x8.eq;46 i16x8.ne;47 i16x8.lt_s;48 i16x8.lt_u;49 i16x8.gt_s;50 i16x8.gt_u;
51 i16x8.le_s;52 i16x8.le_u;53 i16x8.ge_s;54 i16x8.ge_u;55 i32x4.eq;56 i32x4.ne;57 i32x4.lt_s;58 i32x4.lt_u;59 i32x4.gt_s;
60 i32x4.gt_u;61 i32x4.le_s;62 i32x4.le_u;63 i32x4.ge_s;64 i32x4.ge_u;65 f32x4.eq;66 f32x4.ne;67 f32x4.lt;68 f32x4.gt;
69 f32x4.le;70 f32x4.ge;71 f64x2.eq;72 f64x2.ne;73 f64x2.lt;74 f64x2.gt;75 f64x2.le;76 f64x2.ge;77 v128.not;78 v128.and;
79 v128.andnot;80 v128.or;81 v128.xor;82 v128.bitselect;83 v128.any_true;84 v128.load8_lane memlane;
85 v128.load16_lane memlane;86 v128.load32_lane memlane;87 v128.load64_lane memlane;88 v128.store8_lane memlane;
89 v128.store16_lane memlane;90 v128.store32_lane memlane;91 v128.store64_lane memlane;92 v128.load32_zero mem;
93 v128.load64_zero mem;94 f32x4.demote_f64x2_zero;95 f64x2.promote_low_f32x4;96 i8x16.abs;97 i8x16.neg;98 i8x16.popcnt;
99 i8x16.all_true;100 i8x16.bitmask;101 i8x16.narrow_i16x8_s;102 i8x16.narrow_i16x8_u;103 f32x4.ceil;104 f32x4.floor;
105 f32x4.trunc;106 f32x4.nearest;107 i8x16.shl;108 i8x16.shr_s;109 i8x16.shr_u;110 i8x16.add;111 i8x16.add_sat_s;
112 i8x16.add_sat_u;113 i8x16.sub;114 i8x16.sub_sat_s;115 i8x16.sub_sat_u;116 f64x2.ceil;117 f64x2.floor;118 i8x16.min_s;
119 i8x16.min_u;120 i8x16.max_s;121 i8x16.max_u;122 f64x2.trunc;123 i8x16.avgr_u;124 i16x8.extadd_pairwise_i8x16_s;
125 i16x8.extadd_pairwise_i8x16_u;126 i32x4.extadd_pairwise_i16x8_s;127 i32x4.extadd_pairwise_i16x8_u;128 i16x8.abs;
129 i16x8.neg;130 i16x8.q15mulr_sat_s;131 i16x8.all_true;132 i16x8.bitmask;133 i16x8.narrow_i32x4_s;
134 i16x8.narrow_i32x4_u;135 i16x8.extend_low_i8x16_s;136 i16x8.extend_high_i8x16_s;137 i16x8.extend_low_i8x16_u;
138 i16x8.extend_high_i8x16_u;139 i16x8.shl;140 i16x8.shr_s;141 i16x8.shr_u;142 i16x8.add;143 i16x8.add_sat_s;
144 i16x8.add_sat_u;145 i16x8.sub;146 i16x8.sub_sat_s;147 i16x8.sub_sat_u;148 f64x2.nearest;149 i16x8.mul;150 i16x8.min_s;
151 i16x8.min_u;152 i16x8.max_s;153 i16x8.max_u;155 i16x8.avgr_u;156 i16x8.extmul_low_i8x16_s;
157 i16x8.extmul_high_i8x16_s;158 i16x8.extmul_low_i8x16_u;159 i16x8.extmul_high_i8x16_u;160 i32x4.abs;161 i32x4.neg;
163 i32x4.all_true;164 i32x4.bitmask;167 i32x4.extend_low_i16x8_s;168 i32x4.extend_high_i16x8_s;
169 i32x4.extend_low_i16x8_u;170 i32x4.extend_high_i16x8_u;171 i32x4.shl;172 i32x4.shr_s;173 i32x4.shr_u;174 i32x4.add;
177 i32x4.sub;181 i32x4.mul;182 i32x4.min_s;183 i32x4.min_u;184 i32x4.max_s;185 i32x4.max_u;186 i32x4.dot_i16x8_s;
188 i32x4.extmul_low_i16x8_s;189 i32x4.extmul_high_i16x8_s;190 i32x4.extmul_low_i16x8_u;191 i32x4.extmul_high_i16x8_u;
192 i64x2.abs;193 i64x2.neg;195 i64x2.all_true;196 i64x2.bitmask;199 i64x2.extend_low_i32x4_s;200 i64x2.extend_high_i32x4_s;
201 i64x2.extend_low_i32x4_u;202 i64x2.extend_high_i32x4_u;203 i64x2.shl;204 i64x2.shr_s;205 i64x2.shr_u;206 i64x2.add;
209 i64x2.sub;213 i64x2.mul;214 i64x2.eq;215 i64x2.ne;216 i64x2.lt_s;217 i64x2.gt_s;218 i64x2.le_s;219 i64x2.ge_s;
220 i64x2.extmul_low_i32x4_s;221 i64x2.extmul_high_i32x4_s;222 i64x2.extmul_low_i32x4_u;223 i64x2.extmul_high_i32x4_u;
224 f32x4.abs;225 f32x4.neg;227 f32x4.sqrt;228 f32x4.add;229 f32x4.sub;230 f32x4.mul;231 f32x4.div;232 f32x4.min;
233 f32x4.max;234 f32x4.pmin;235 f32x4.pmax;236 f64x2.abs;237 f64x2.neg;239 f64x2.sqrt;240 f64x2.add;241 f64x2.sub;
242 f64x2.mul;243 f64x2.div;244 f64x2.min;245 f64x2.max;246 f64x2.pmin;247 f64x2.pmax;248 i32x4.trunc_sat_f32x4_s;
249 i32x4.trunc_sat_f32x4_u;250 f32x4.convert_i32x4_s;251 f32x4.convert_i32x4_u;252 i32x4.trunc_sat_f64x2_s_zero;
253 i32x4.trunc_sat_f64x2_u_zero;254 f64x2.convert_low_i32x4_s;255 f64x2.convert_low_i32x4_u"""
SIMD = {}
for e in _SIMD.replace("\n", "").split(";"):
    p = e.split()
    SIMD[int(p[0])] = (p[1], p[2] if len(p) > 2 else "")


def memarg(r):
    a = r.u32()
    mem = r.u32() if a & 0x40 else 0
    return (a & 0x3f, r.u32(), mem)


def decode_body(b, p, end):
    """-> (locals [(n, type)], instrs [(name, imm)]); imm per kind (see OPS)."""
    r = R(b, p)
    locs = [(r.u32(), r.vt()) for _ in range(r.u32())]
    out = []
    while r.p < end:
        op = r.u8()
        if op == 0xfc:
            name, k = FC[r.u32()]
        elif op == 0xfd:
            name, k = SIMD[r.u32()]
        else:
            name, k = OPS[op]
        if k == "":
            imm = None
        elif k == "u":
            imm = r.u32()
        elif k == "uu":
            imm = (r.u32(), r.u32())
        elif k == "ub":
            imm = (r.u32(), r.u8())
        elif k in ("b", "bb"):
            imm = r.raw(len(k))
        elif k == "bt":
            imm = r.blocktype()
        elif k == "table":
            imm = ([r.u32() for _ in range(r.u32())], r.u32())
        elif k == "selt":
            imm = [r.vt() for _ in range(r.u32())]
        elif k == "try":
            bt = r.blocktype()
            cs = []
            for _ in range(r.u32()):
                ck = r.u8()
                tag = r.u32() if ck in (0, 1) else None
                cs.append((ck, tag, r.u32()))
            imm = (bt, cs)
        elif k == "mem":
            imm = memarg(r)
        elif k == "memlane":
            imm = (memarg(r), r.u8())
        elif k == "lane":
            imm = r.u8()
        elif k == "c16":
            imm = r.raw(16)
        elif k == "i32":
            imm = r.sleb(32)
        elif k == "i64":
            imm = r.sleb(64)
        elif k == "f32":
            imm = r.raw(4)
        elif k == "f64":
            imm = r.raw(8)
        else:
            raise ValueError(k)
        out.append((name, imm))
    return locs, out


def const_expr(r):
    """A constant expression (global init, segment offset): returns ('i32', v) / ('global', idx) / ..."""
    op = r.u8()
    if op == 0x41:
        v = ("i32", r.sleb(32))
    elif op == 0x42:
        v = ("i64", r.sleb(64))
    elif op == 0x43:
        v = ("f32", r.raw(4))
    elif op == 0x44:
        v = ("f64", r.raw(8))
    elif op == 0x23:
        v = ("global", r.u32())
    elif op == 0xd0:
        r.u8()
        v = ("null", 0)
    elif op == 0xd2:
        v = ("func", r.u32())
    elif op == 0xfd and r.u32() == 12:
        v = ("v128", r.raw(16))
    else:
        raise ValueError(f"const expr op {op:#x}")
    if r.u8() != 0x0b:
        raise ValueError("extended const expr unsupported")
    return v


class Module:
    def __init__(self, path):
        b = open(path, "rb").read()
        if b[:4] != b"\0asm":
            raise ValueError("not wasm")
        self.types, self.imports, self.funcs, self.tables, self.mems = [], [], [], [], []
        self.globals, self.exports, self.elems, self.datas, self.tags = [], [], [], [], []
        self.start, self.bodies, self.names = None, [], {}
        r = R(b, 8)
        while r.p < len(b):
            sid, size = r.u8(), r.u32()
            end = r.p + size
            if sid == 0:
                nm = r.name()
                if nm == "name":
                    self._names(R(b, r.p), end)
            elif sid == 1:
                for _ in range(r.u32()):
                    f = r.u8()
                    if f != 0x60:
                        raise ValueError(f"type form {f:#x}")
                    ps = [r.vt() for _ in range(r.u32())]
                    rs = [r.vt() for _ in range(r.u32())]
                    self.types.append((ps, rs))
            elif sid == 2:
                for _ in range(r.u32()):
                    m, n, k = r.name(), r.name(), r.u8()
                    if k == 0:
                        d = r.u32()
                    elif k == 1:
                        d = (r.vt(), r.limits())
                    elif k == 2:
                        d = r.limits()
                    elif k == 3:
                        d = (r.vt(), r.u8())
                    elif k == 4:
                        r.u8()
                        d = r.u32()
                    self.imports.append((m, n, k, d))
            elif sid == 3:
                self.funcs = [r.u32() for _ in range(r.u32())]
            elif sid == 4:
                self.tables = [(r.vt(), r.limits()) for _ in range(r.u32())]
            elif sid == 5:
                self.mems = [r.limits() for _ in range(r.u32())]
            elif sid == 6:
                for _ in range(r.u32()):
                    t, mut = r.vt(), r.u8()
                    self.globals.append((t, mut, const_expr(r)))
            elif sid == 7:
                for _ in range(r.u32()):
                    self.exports.append((r.name(), r.u8(), r.u32()))
            elif sid == 8:
                self.start = r.u32()
            elif sid == 9:
                for _ in range(r.u32()):
                    f = r.u32()
                    if f == 0:
                        off = const_expr(r)
                        self.elems.append(("active", 0, off, [r.u32() for _ in range(r.u32())]))
                    elif f == 1:
                        r.u8()
                        self.elems.append(("passive", 0, None, [r.u32() for _ in range(r.u32())]))
                    elif f == 2:
                        ti = r.u32()
                        off = const_expr(r)
                        r.u8()
                        self.elems.append(("active", ti, off, [r.u32() for _ in range(r.u32())]))
                    elif f == 3:
                        r.u8()
                        self.elems.append(("declarative", 0, None, [r.u32() for _ in range(r.u32())]))
                    else:
                        raise ValueError(f"elem flag {f}")
            elif sid == 10:
                for _ in range(r.u32()):
                    sz = r.u32()
                    self.bodies.append((b, r.p, r.p + sz))
                    r.p += sz
            elif sid == 11:
                for _ in range(r.u32()):
                    f = r.u32()
                    if f == 0:
                        off = const_expr(r)
                        self.datas.append(("active", off, r.raw(r.u32())))
                    elif f == 1:
                        self.datas.append(("passive", None, r.raw(r.u32())))
                    elif f == 2:
                        r.u32()
                        off = const_expr(r)
                        self.datas.append(("active", off, r.raw(r.u32())))
            elif sid == 12:
                r.u32()
            elif sid == 13:
                for _ in range(r.u32()):
                    r.u8()
                    self.tags.append(r.u32())
            r.p = end
        self.nimp = sum(1 for i in self.imports if i[2] == 0)
        self.import_tags = [i[3] for i in self.imports if i[2] == 4]

    def _names(self, r, end):
        while r.p < end:
            sub, size = r.u8(), r.u32()
            e = r.p + size
            if sub == 1:
                for _ in range(r.u32()):
                    i = r.u32()
                    self.names[i] = r.name()
            r.p = e

    def ftype(self, fi):
        """Function index (imports first) -> (params, results)."""
        if fi < self.nimp:
            return self.types[[i for i in self.imports if i[2] == 0][fi][3]]
        return self.types[self.funcs[fi - self.nimp]]

    def body(self, k):
        b, p, e = self.bodies[k]
        return decode_body(b, p, e)


if __name__ == "__main__":
    m = Module(sys.argv[1])
    if "--imports" in sys.argv:
        fi = 0
        for mod, n, k, d in m.imports:
            print(mod, n, k, m.types[d] if k == 0 else d)
    if "--exports" in sys.argv:
        for n, k, i in m.exports:
            print(n, k, m.ftype(i) if k == 0 else i)
    if "--ops" in sys.argv:
        import collections
        c = collections.Counter()
        for k in range(len(m.bodies)):
            for name, _ in m.body(k)[1]:
                c[name] += 1
        for n, v in c.most_common():
            print(v, n)
    print(f"# {len(m.types)} types, {len(m.imports)} imports, {len(m.funcs)} funcs, {len(m.globals)} globals, "
          f"{len(m.exports)} exports, {len(m.elems)} elem segs, {len(m.datas)} data segs, {len(m.tags)} tags, "
          f"mems {m.mems}, tables {m.tables}", file=sys.stderr)
