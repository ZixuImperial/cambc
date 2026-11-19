/* w2c_rt.h - runtime for C translated from WebAssembly by tools/cxe/w2c.py (cxe test engine).
 * Values: i32 = uint32_t, i64 = uint64_t, f32 = float, f64 = double, v128 = 16-byte vector, refs = uint32_t.
 * Memory: one linear memory per instance inside an 8 GiB + guard PROT_NONE reservation, so an out-of-bounds access
 * faults instead of needing a check (the host turns the fault into a trap). Fuel: wasmtime's encoding, I->fuel is
 * consumed - budget, so the budget is spent when it reaches >= 0. Build with -fno-strict-aliasing -ffp-contract=off. */
#ifndef W2C_RT_H
#define W2C_RT_H
#include <math.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define W2C_LIKELY(x) __builtin_expect(!!(x), 1)
#define W2C_UNLIKELY(x) __builtin_expect(!!(x), 0)
#define W2C_MAX_GLOBALS 64
#define W2C_MAX_EXN_VALS 4

typedef uint8_t v128 __attribute__((vector_size(16), aligned(16)));
typedef int8_t v_i8 __attribute__((vector_size(16)));
typedef uint8_t v_u8 __attribute__((vector_size(16)));
typedef int16_t v_i16 __attribute__((vector_size(16)));
typedef uint16_t v_u16 __attribute__((vector_size(16)));
typedef int32_t v_i32 __attribute__((vector_size(16)));
typedef uint32_t v_u32 __attribute__((vector_size(16)));
typedef int64_t v_i64 __attribute__((vector_size(16)));
typedef uint64_t v_u64 __attribute__((vector_size(16)));
typedef float v_f32 __attribute__((vector_size(16)));
typedef double v_f64 __attribute__((vector_size(16)));

typedef union { uint32_t i32; uint64_t i64; float f32; double f64; v128 v; } w2c_val;

/* try_table frames: w2c_rt.c's own setjmp/longjmp (the 6 callee-saved registers, stack pointer and return address, as musl does):
   ~10 instructions against glibc _setjmp/__sigsetjmp's ~50 (pointer mangling, shadow stack), which were 3% of a game's instructions
   at ~300k try entries a game. returns_twice: the compiler treats it exactly as setjmp. (__builtin_setjmp was tried and broke
   catches: probe21 printed different values than the CLI.) */
int w2c_sj_set(void **buf) __attribute__((returns_twice));
void w2c_sj_jump(void **buf) __attribute__((noreturn));
typedef struct w2c_eh_frame { void *jb[8]; struct w2c_eh_frame *prev; } w2c_eh_frame;
typedef struct { uint32_t tag; w2c_val v[W2C_MAX_EXN_VALS]; } w2c_exn;
typedef struct { uint32_t type; void *fn; } w2c_funcref;

typedef enum { W2C_TRAP_NONE = 0, W2C_TRAP_UNREACHABLE, W2C_TRAP_DIV0, W2C_TRAP_OVERFLOW, W2C_TRAP_OOB,
               W2C_TRAP_INDIRECT_NULL, W2C_TRAP_INDIRECT_TYPE, W2C_TRAP_UNCAUGHT, W2C_TRAP_STACK, W2C_TRAP_HOST } w2c_trap_kind;

struct w2c_module;
typedef struct w2c_inst {
  uint8_t *mem;           /* base of linear memory */
  uint64_t pages, max_pages;
  int64_t fuel;           /* consumed - budget; >= 0 means out of fuel (fuel-metered modules only) */
  w2c_val G[W2C_MAX_GLOBALS];
  w2c_funcref *table;
  uint32_t ntable;
  w2c_eh_frame *eh_top;   /* innermost active try_table handler */
  w2c_exn *exn;           /* exception objects; exnref = index + 1 */
  uint32_t nexn, capexn, cur_exn;
  uint8_t *dropped;       /* data segments dropped (passive segments) */
  const struct w2c_module *mod;
  void *host;             /* host data: the champion / engine this instance serves */
  jmp_buf *trap_jb;       /* where a trap jumps (set by the host around each call into the module) */
  w2c_trap_kind trap;
  uint64_t prof[16];       /* --profile builds: executed-op class counters (see w2c.py PROF) */
  uint64_t *fprof;         /* --fuelprof builds: fuel spent per function (own instructions + bulk bytes + host charges of
                              imports it calls), indexed by function index; fprof[nfuncs + f] counts out-of-fuel cuts in f */
  uint32_t wasi_closed;    /* host WASI: bit fd set once the bot closed stdio fd 0..2 */
  uint64_t *opc;           /* --profile builds: executed count per opcode (index = w2c.py OPIDS order), host-allocated */
} w2c_inst;

typedef struct w2c_module {
  const char *name;
  uint32_t nfuncs, nimports, ntypes;
  int (*init)(w2c_inst *);             /* memory, globals, table, data; 0 = ok */
  void *(*export_fn)(const char *name); /* exported function pointer by name, or NULL */
} w2c_module;

/* host-provided */
void w2c_trap(w2c_inst *I, w2c_trap_kind k) __attribute__((noreturn));
void w2c_out_of_fuel(w2c_inst *I);
int w2c_mem_alloc(w2c_inst *I, uint64_t pages, uint64_t max_pages);
uint32_t w2c_mem_grow(w2c_inst *I, uint32_t delta);
uint32_t w2c_exn_new(w2c_inst *I, uint32_t tag);

/* ---- loads / stores (addresses are u64: base address + offset; the guard region catches out-of-bounds) */
#define W2C_LD(T, name) static inline T name(const uint8_t *M, uint64_t a) { T v; memcpy(&v, M + a, sizeof v); return v; }
W2C_LD(uint32_t, ld_u32) W2C_LD(uint64_t, ld_u64) W2C_LD(float, ld_f32) W2C_LD(double, ld_f64) W2C_LD(int8_t, ld_i8)
W2C_LD(uint8_t, ld_u8) W2C_LD(int16_t, ld_i16) W2C_LD(uint16_t, ld_u16) W2C_LD(int32_t, ld_i32s) W2C_LD(v128, ld_v128)
#define W2C_ST(T, name) static inline void name(uint8_t *M, uint64_t a, T v) { memcpy(M + a, &v, sizeof v); }
W2C_ST(uint32_t, st_u32) W2C_ST(uint64_t, st_u64) W2C_ST(float, st_f32) W2C_ST(double, st_f64) W2C_ST(uint8_t, st_u8)
W2C_ST(uint16_t, st_u16) W2C_ST(v128, st_v128)

/* ---- bit casts */
static inline float f32_bits(uint32_t x) { float f; memcpy(&f, &x, 4); return f; }
static inline double f64_bits(uint64_t x) { double f; memcpy(&f, &x, 8); return f; }
static inline uint32_t bits_f32(float f) { uint32_t x; memcpy(&x, &f, 4); return x; }
static inline uint64_t bits_f64(double f) { uint64_t x; memcpy(&x, &f, 8); return x; }

#ifndef W2C_HOST_ONLY
/* ---- integer ops with wasm semantics */
static inline uint32_t i32_div_s(w2c_inst *I, uint32_t a, uint32_t b) {
  if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0);
  if (W2C_UNLIKELY(a == 0x80000000u && b == 0xffffffffu)) w2c_trap(I, W2C_TRAP_OVERFLOW);
  return (uint32_t)((int32_t)a / (int32_t)b);
}
static inline uint32_t i32_div_u(w2c_inst *I, uint32_t a, uint32_t b) { if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0); return a / b; }
static inline uint32_t i32_rem_s(w2c_inst *I, uint32_t a, uint32_t b) {
  if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0);
  if (W2C_UNLIKELY(b == 0xffffffffu)) return 0;
  return (uint32_t)((int32_t)a % (int32_t)b);
}
static inline uint32_t i32_rem_u(w2c_inst *I, uint32_t a, uint32_t b) { if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0); return a % b; }
static inline uint64_t i64_div_s(w2c_inst *I, uint64_t a, uint64_t b) {
  if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0);
  if (W2C_UNLIKELY(a == 0x8000000000000000ull && b == ~0ull)) w2c_trap(I, W2C_TRAP_OVERFLOW);
  return (uint64_t)((int64_t)a / (int64_t)b);
}
static inline uint64_t i64_div_u(w2c_inst *I, uint64_t a, uint64_t b) { if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0); return a / b; }
static inline uint64_t i64_rem_s(w2c_inst *I, uint64_t a, uint64_t b) {
  if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0);
  if (W2C_UNLIKELY(b == ~0ull)) return 0;
  return (uint64_t)((int64_t)a % (int64_t)b);
}
static inline uint64_t i64_rem_u(w2c_inst *I, uint64_t a, uint64_t b) { if (W2C_UNLIKELY(b == 0)) w2c_trap(I, W2C_TRAP_DIV0); return a % b; }
static inline uint32_t i32_clz(uint32_t x) { return x ? (uint32_t)__builtin_clz(x) : 32; }
static inline uint32_t i32_ctz(uint32_t x) { return x ? (uint32_t)__builtin_ctz(x) : 32; }
static inline uint64_t i64_clz(uint64_t x) { return x ? (uint64_t)__builtin_clzll(x) : 64; }
static inline uint64_t i64_ctz(uint64_t x) { return x ? (uint64_t)__builtin_ctzll(x) : 64; }
static inline uint32_t i32_rotl(uint32_t a, uint32_t b) { b &= 31; return (a << b) | (a >> ((32 - b) & 31)); }
static inline uint32_t i32_rotr(uint32_t a, uint32_t b) { b &= 31; return (a >> b) | (a << ((32 - b) & 31)); }
static inline uint64_t i64_rotl(uint64_t a, uint64_t b) { b &= 63; return (a << b) | (a >> ((64 - b) & 63)); }
static inline uint64_t i64_rotr(uint64_t a, uint64_t b) { b &= 63; return (a >> b) | (a << ((64 - b) & 63)); }

/* ---- float ops with wasm semantics (abs / neg / copysign are pure sign-bit operations) */
static inline float f32_abs(float a) { return f32_bits(bits_f32(a) & 0x7fffffffu); }
static inline float f32_neg(float a) { return f32_bits(bits_f32(a) ^ 0x80000000u); }
static inline float f32_copysign(float a, float b) { return f32_bits((bits_f32(a) & 0x7fffffffu) | (bits_f32(b) & 0x80000000u)); }
static inline double f64_abs(double a) { return f64_bits(bits_f64(a) & 0x7fffffffffffffffull); }
static inline double f64_neg(double a) { return f64_bits(bits_f64(a) ^ 0x8000000000000000ull); }
static inline double f64_copysign(double a, double b) { return f64_bits((bits_f64(a) & 0x7fffffffffffffffull) | (bits_f64(b) & 0x8000000000000000ull)); }
static inline float f32_canon(float r) { return r != r ? f32_bits(0x7fc00000u) : r; }
static inline double f64_canon(double r) { return r != r ? f64_bits(0x7ff8000000000000ull) : r; }
static inline float f32_min(float a, float b) {
  if (a != a || b != b) return f32_bits(0x7fc00000u);
  if (a == 0 && b == 0) return f32_bits(bits_f32(a) | bits_f32(b));
  return a < b ? a : b;
}
static inline float f32_max(float a, float b) {
  if (a != a || b != b) return f32_bits(0x7fc00000u);
  if (a == 0 && b == 0) return f32_bits(bits_f32(a) & bits_f32(b));
  return a > b ? a : b;
}
static inline double f64_min(double a, double b) {
  if (a != a || b != b) return f64_bits(0x7ff8000000000000ull);
  if (a == 0 && b == 0) return f64_bits(bits_f64(a) | bits_f64(b));
  return a < b ? a : b;
}
static inline double f64_max(double a, double b) {
  if (a != a || b != b) return f64_bits(0x7ff8000000000000ull);
  if (a == 0 && b == 0) return f64_bits(bits_f64(a) & bits_f64(b));
  return a > b ? a : b;
}
static inline float f32_nearest(float a) { return __builtin_rintf(a); }
static inline double f64_nearest(double a) { return __builtin_rint(a); }

/* trapping truncation */
static inline uint32_t i32_trunc_f32_s(w2c_inst *I, float a) { if (!(a >= -2147483648.0f && a < 2147483648.0f)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint32_t)(int32_t)a; }
static inline uint32_t i32_trunc_f32_u(w2c_inst *I, float a) { if (!(a > -1.0f && a < 4294967296.0f)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint32_t)a; }
static inline uint32_t i32_trunc_f64_s(w2c_inst *I, double a) { if (!(a > -2147483649.0 && a < 2147483648.0)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint32_t)(int32_t)a; }
static inline uint32_t i32_trunc_f64_u(w2c_inst *I, double a) { if (!(a > -1.0 && a < 4294967296.0)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint32_t)a; }
static inline uint64_t i64_trunc_f32_s(w2c_inst *I, float a) { if (!(a >= -9223372036854775808.0f && a < 9223372036854775808.0f)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint64_t)(int64_t)a; }
static inline uint64_t i64_trunc_f32_u(w2c_inst *I, float a) { if (!(a > -1.0f && a < 18446744073709551616.0f)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint64_t)a; }
static inline uint64_t i64_trunc_f64_s(w2c_inst *I, double a) { if (!(a >= -9223372036854775808.0 && a < 9223372036854775808.0)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint64_t)(int64_t)a; }
static inline uint64_t i64_trunc_f64_u(w2c_inst *I, double a) { if (!(a > -1.0 && a < 18446744073709551616.0)) w2c_trap(I, W2C_TRAP_OVERFLOW); return (uint64_t)a; }
/* saturating truncation */
static inline uint32_t i32_trunc_sat_f32_s(float a) { if (a != a) return 0; if (a < -2147483648.0f) return 0x80000000u; if (a >= 2147483648.0f) return 0x7fffffffu; return (uint32_t)(int32_t)a; }
static inline uint32_t i32_trunc_sat_f32_u(float a) { if (a != a || a <= -1.0f) return 0; if (a >= 4294967296.0f) return 0xffffffffu; return (uint32_t)a; }
static inline uint32_t i32_trunc_sat_f64_s(double a) { if (a != a) return 0; if (a <= -2147483649.0) return 0x80000000u; if (a >= 2147483648.0) return 0x7fffffffu; return (uint32_t)(int32_t)a; }
static inline uint32_t i32_trunc_sat_f64_u(double a) { if (a != a || a <= -1.0) return 0; if (a >= 4294967296.0) return 0xffffffffu; return (uint32_t)a; }
static inline uint64_t i64_trunc_sat_f32_s(float a) { if (a != a) return 0; if (a < -9223372036854775808.0f) return 0x8000000000000000ull; if (a >= 9223372036854775808.0f) return 0x7fffffffffffffffull; return (uint64_t)(int64_t)a; }
static inline uint64_t i64_trunc_sat_f32_u(float a) { if (a != a || a <= -1.0f) return 0; if (a >= 18446744073709551616.0f) return ~0ull; return (uint64_t)a; }
static inline uint64_t i64_trunc_sat_f64_s(double a) { if (a != a) return 0; if (a < -9223372036854775808.0) return 0x8000000000000000ull; if (a >= 9223372036854775808.0) return 0x7fffffffffffffffull; return (uint64_t)(int64_t)a; }
static inline uint64_t i64_trunc_sat_f64_u(double a) { if (a != a || a <= -1.0) return 0; if (a >= 18446744073709551616.0) return ~0ull; return (uint64_t)a; }

/* ---- bulk memory (bounds-checked: these can touch any range) */
static inline void mem_check(w2c_inst *I, uint64_t a, uint64_t n) { if (W2C_UNLIKELY(a + n > I->pages * 65536ull)) w2c_trap(I, W2C_TRAP_OOB); }
static inline void mem_copy(w2c_inst *I, uint32_t d, uint32_t s, uint32_t n) { mem_check(I, d, n); mem_check(I, s, n); memmove(I->mem + d, I->mem + s, n); }
static inline void mem_fill(w2c_inst *I, uint32_t d, uint32_t v, uint32_t n) { mem_check(I, d, n); memset(I->mem + d, (int)(v & 0xff), n); }

/* ---- exceptions */
static inline void w2c_throw_cur(w2c_inst *I) __attribute__((noreturn));
static inline void w2c_throw_cur(w2c_inst *I) {
  w2c_eh_frame *f = I->eh_top;
  if (!f) w2c_trap(I, W2C_TRAP_UNCAUGHT);
  w2c_sj_jump(f->jb);
}
static inline void w2c_throw_ref(w2c_inst *I, uint32_t exn) {
  if (!exn) w2c_trap(I, W2C_TRAP_UNCAUGHT);
  I->cur_exn = exn;
  w2c_throw_cur(I);
}

/* ---- SIMD */
static inline v128 v_load_splat8(const uint8_t *M, uint64_t a) { uint8_t x = M[a]; v_u8 r = {x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x}; return (v128)r; }
static inline v128 v_load_splat16(const uint8_t *M, uint64_t a) { uint16_t x = ld_u16(M, a); v_u16 r = {x,x,x,x,x,x,x,x}; return (v128)r; }
static inline v128 v_load_splat32(const uint8_t *M, uint64_t a) { uint32_t x = ld_u32(M, a); v_u32 r = {x,x,x,x}; return (v128)r; }
static inline v128 v_load_splat64(const uint8_t *M, uint64_t a) { uint64_t x = ld_u64(M, a); v_u64 r = {x,x}; return (v128)r; }
static inline v128 v_load32_zero(const uint8_t *M, uint64_t a) { v_u32 r = {ld_u32(M, a),0,0,0}; return (v128)r; }
static inline v128 v_load64_zero(const uint8_t *M, uint64_t a) { v_u64 r = {ld_u64(M, a),0}; return (v128)r; }
#define V_LOADLANE(bits, T, VT) static inline v128 v_load##bits##_lane(const uint8_t *M, uint64_t a, v128 v, int l) { VT r = (VT)v; T x; memcpy(&x, M + a, sizeof x); r[l] = x; return (v128)r; } \
  static inline void v_store##bits##_lane(uint8_t *M, uint64_t a, v128 v, int l) { VT r = (VT)v; T x = r[l]; memcpy(M + a, &x, sizeof x); }
V_LOADLANE(8, uint8_t, v_u8) V_LOADLANE(16, uint16_t, v_u16) V_LOADLANE(32, uint32_t, v_u32) V_LOADLANE(64, uint64_t, v_u64)
#define V_EXT(name, NL, SRC, DST, off) static inline v128 name(v128 a) { SRC s = (SRC)a; DST r; for (int i = 0; i < NL; i++) r[i] = s[i + off]; return (v128)r; }
V_EXT(i16x8_extend_low_i8x16_s, 8, v_i8, v_i16, 0) V_EXT(i16x8_extend_high_i8x16_s, 8, v_i8, v_i16, 8)
V_EXT(i16x8_extend_low_i8x16_u, 8, v_u8, v_u16, 0) V_EXT(i16x8_extend_high_i8x16_u, 8, v_u8, v_u16, 8)
V_EXT(i32x4_extend_low_i16x8_s, 4, v_i16, v_i32, 0) V_EXT(i32x4_extend_high_i16x8_s, 4, v_i16, v_i32, 4)
V_EXT(i32x4_extend_low_i16x8_u, 4, v_u16, v_u32, 0) V_EXT(i32x4_extend_high_i16x8_u, 4, v_u16, v_u32, 4)
V_EXT(i64x2_extend_low_i32x4_s, 2, v_i32, v_i64, 0) V_EXT(i64x2_extend_high_i32x4_s, 2, v_i32, v_i64, 2)
V_EXT(i64x2_extend_low_i32x4_u, 2, v_u32, v_u64, 0) V_EXT(i64x2_extend_high_i32x4_u, 2, v_u32, v_u64, 2)
#define V_BITMASK(name, NL, VT) static inline uint32_t name(v128 a) { VT s = (VT)a; uint32_t r = 0; for (int i = 0; i < NL; i++) r |= (uint32_t)(s[i] < 0) << i; return r; }
V_BITMASK(i8x16_bitmask, 16, v_i8) V_BITMASK(i16x8_bitmask, 8, v_i16) V_BITMASK(i32x4_bitmask, 4, v_i32) V_BITMASK(i64x2_bitmask, 2, v_i64)
#define V_ALLTRUE(name, NL, VT) static inline uint32_t name(v128 a) { VT s = (VT)a; for (int i = 0; i < NL; i++) if (!s[i]) return 0; return 1; }
V_ALLTRUE(i8x16_all_true, 16, v_u8) V_ALLTRUE(i16x8_all_true, 8, v_u16) V_ALLTRUE(i32x4_all_true, 4, v_u32) V_ALLTRUE(i64x2_all_true, 2, v_u64)
static inline uint32_t v128_any_true(v128 a) { v_u64 s = (v_u64)a; return (s[0] | s[1]) != 0; }
#define V_SHIFT(name, VT, op, bits) static inline v128 name(v128 a, uint32_t n) { VT s = (VT)a; return (v128)(s op (VT){0} + (n & (bits - 1))); }
static inline v128 i8x16_shl(v128 a, uint32_t n) { v_u8 s = (v_u8)a; n &= 7; for (int i = 0; i < 16; i++) s[i] = (uint8_t)(s[i] << n); return (v128)s; }
static inline v128 i8x16_shr_s(v128 a, uint32_t n) { v_i8 s = (v_i8)a; n &= 7; for (int i = 0; i < 16; i++) s[i] = (int8_t)(s[i] >> n); return (v128)s; }
static inline v128 i8x16_shr_u(v128 a, uint32_t n) { v_u8 s = (v_u8)a; n &= 7; for (int i = 0; i < 16; i++) s[i] = (uint8_t)(s[i] >> n); return (v128)s; }
static inline v128 i16x8_shl(v128 a, uint32_t n) { v_u16 s = (v_u16)a; n &= 15; for (int i = 0; i < 8; i++) s[i] = (uint16_t)(s[i] << n); return (v128)s; }
static inline v128 i16x8_shr_s(v128 a, uint32_t n) { v_i16 s = (v_i16)a; n &= 15; for (int i = 0; i < 8; i++) s[i] = (int16_t)(s[i] >> n); return (v128)s; }
static inline v128 i16x8_shr_u(v128 a, uint32_t n) { v_u16 s = (v_u16)a; n &= 15; for (int i = 0; i < 8; i++) s[i] = (uint16_t)(s[i] >> n); return (v128)s; }
static inline v128 i32x4_shl(v128 a, uint32_t n) { v_u32 s = (v_u32)a; n &= 31; return (v128)(s << n); }
static inline v128 i32x4_shr_s(v128 a, uint32_t n) { v_i32 s = (v_i32)a; n &= 31; return (v128)(s >> (int32_t)n); }
static inline v128 i32x4_shr_u(v128 a, uint32_t n) { v_u32 s = (v_u32)a; n &= 31; return (v128)(s >> n); }
static inline v128 i64x2_shl(v128 a, uint32_t n) { v_u64 s = (v_u64)a; return (v128)(s << (uint64_t)(n & 63)); }
static inline v128 i64x2_shr_s(v128 a, uint32_t n) { v_i64 s = (v_i64)a; return (v128)(s >> (int64_t)(n & 63)); }
static inline v128 i64x2_shr_u(v128 a, uint32_t n) { v_u64 s = (v_u64)a; return (v128)(s >> (uint64_t)(n & 63)); }
#define V_LANEWISE2(name, NL, VT, expr) static inline v128 name(v128 a_, v128 b_) { VT a = (VT)a_, b = (VT)b_, r; for (int i = 0; i < NL; i++) r[i] = (expr); return (v128)r; }
V_LANEWISE2(i8x16_min_s, 16, v_i8, a[i] < b[i] ? a[i] : b[i]) V_LANEWISE2(i8x16_min_u, 16, v_u8, a[i] < b[i] ? a[i] : b[i])
V_LANEWISE2(i8x16_max_s, 16, v_i8, a[i] > b[i] ? a[i] : b[i]) V_LANEWISE2(i8x16_max_u, 16, v_u8, a[i] > b[i] ? a[i] : b[i])
V_LANEWISE2(i16x8_min_s, 8, v_i16, a[i] < b[i] ? a[i] : b[i]) V_LANEWISE2(i16x8_min_u, 8, v_u16, a[i] < b[i] ? a[i] : b[i])
V_LANEWISE2(i16x8_max_s, 8, v_i16, a[i] > b[i] ? a[i] : b[i]) V_LANEWISE2(i16x8_max_u, 8, v_u16, a[i] > b[i] ? a[i] : b[i])
V_LANEWISE2(i32x4_min_s, 4, v_i32, a[i] < b[i] ? a[i] : b[i]) V_LANEWISE2(i32x4_min_u, 4, v_u32, a[i] < b[i] ? a[i] : b[i])
V_LANEWISE2(i32x4_max_s, 4, v_i32, a[i] > b[i] ? a[i] : b[i]) V_LANEWISE2(i32x4_max_u, 4, v_u32, a[i] > b[i] ? a[i] : b[i])
V_LANEWISE2(i8x16_add_sat_u, 16, v_u8, (uint8_t)(a[i] + b[i] > 255 ? 255 : a[i] + b[i]))
V_LANEWISE2(i8x16_add_sat_s, 16, v_i8, (int8_t)(a[i] + b[i] > 127 ? 127 : a[i] + b[i] < -128 ? -128 : a[i] + b[i]))
V_LANEWISE2(i8x16_sub_sat_u, 16, v_u8, (uint8_t)(a[i] < b[i] ? 0 : a[i] - b[i]))
V_LANEWISE2(i8x16_sub_sat_s, 16, v_i8, (int8_t)(a[i] - b[i] > 127 ? 127 : a[i] - b[i] < -128 ? -128 : a[i] - b[i]))
V_LANEWISE2(i16x8_add_sat_u, 8, v_u16, (uint16_t)(a[i] + b[i] > 65535 ? 65535 : a[i] + b[i]))
V_LANEWISE2(i16x8_add_sat_s, 8, v_i16, (int16_t)(a[i] + b[i] > 32767 ? 32767 : a[i] + b[i] < -32768 ? -32768 : a[i] + b[i]))
V_LANEWISE2(i16x8_sub_sat_u, 8, v_u16, (uint16_t)(a[i] < b[i] ? 0 : a[i] - b[i]))
V_LANEWISE2(i16x8_sub_sat_s, 8, v_i16, (int16_t)(a[i] - b[i] > 32767 ? 32767 : a[i] - b[i] < -32768 ? -32768 : a[i] - b[i]))
V_LANEWISE2(i8x16_avgr_u, 16, v_u8, (uint8_t)((a[i] + b[i] + 1) >> 1)) V_LANEWISE2(i16x8_avgr_u, 8, v_u16, (uint16_t)((a[i] + b[i] + 1) >> 1))
V_LANEWISE2(f32x4_pmin, 4, v_f32, b[i] < a[i] ? b[i] : a[i]) V_LANEWISE2(f32x4_pmax, 4, v_f32, a[i] < b[i] ? b[i] : a[i])
V_LANEWISE2(f64x2_pmin, 2, v_f64, b[i] < a[i] ? b[i] : a[i]) V_LANEWISE2(f64x2_pmax, 2, v_f64, a[i] < b[i] ? b[i] : a[i])
V_LANEWISE2(f32x4_min, 4, v_f32, f32_min(a[i], b[i])) V_LANEWISE2(f32x4_max, 4, v_f32, f32_max(a[i], b[i]))
V_LANEWISE2(f64x2_min, 2, v_f64, f64_min(a[i], b[i])) V_LANEWISE2(f64x2_max, 2, v_f64, f64_max(a[i], b[i]))
static inline v128 i16x8_q15mulr_sat_s(v128 a_, v128 b_) { v_i16 a = (v_i16)a_, b = (v_i16)b_, r; for (int i = 0; i < 8; i++) { int32_t p = ((int32_t)a[i] * b[i] + 0x4000) >> 15; r[i] = (int16_t)(p > 32767 ? 32767 : p); } return (v128)r; }
#define V_LANEWISE1(name, NL, VT, expr) static inline v128 name(v128 a_) { VT a = (VT)a_, r; for (int i = 0; i < NL; i++) r[i] = (expr); return (v128)r; }
V_LANEWISE1(i8x16_abs, 16, v_i8, (int8_t)(a[i] < 0 ? -(uint8_t)a[i] : a[i])) V_LANEWISE1(i16x8_abs, 8, v_i16, (int16_t)(a[i] < 0 ? -(uint16_t)a[i] : a[i]))
V_LANEWISE1(i32x4_abs, 4, v_i32, (int32_t)(a[i] < 0 ? -(uint32_t)a[i] : (uint32_t)a[i])) V_LANEWISE1(i64x2_abs, 2, v_i64, (int64_t)(a[i] < 0 ? -(uint64_t)a[i] : (uint64_t)a[i]))
V_LANEWISE1(i8x16_popcnt, 16, v_u8, (uint8_t)__builtin_popcount(a[i]))
V_LANEWISE1(f32x4_abs, 4, v_f32, f32_abs(a[i])) V_LANEWISE1(f32x4_neg, 4, v_f32, f32_neg(a[i])) V_LANEWISE1(f32x4_sqrt, 4, v_f32, __builtin_sqrtf(a[i]))
V_LANEWISE1(f32x4_ceil, 4, v_f32, __builtin_ceilf(a[i])) V_LANEWISE1(f32x4_floor, 4, v_f32, __builtin_floorf(a[i]))
V_LANEWISE1(f32x4_trunc, 4, v_f32, __builtin_truncf(a[i])) V_LANEWISE1(f32x4_nearest, 4, v_f32, __builtin_rintf(a[i]))
V_LANEWISE1(f64x2_abs, 2, v_f64, f64_abs(a[i])) V_LANEWISE1(f64x2_neg, 2, v_f64, f64_neg(a[i])) V_LANEWISE1(f64x2_sqrt, 2, v_f64, __builtin_sqrt(a[i]))
V_LANEWISE1(f64x2_ceil, 2, v_f64, __builtin_ceil(a[i])) V_LANEWISE1(f64x2_floor, 2, v_f64, __builtin_floor(a[i]))
V_LANEWISE1(f64x2_trunc, 2, v_f64, __builtin_trunc(a[i])) V_LANEWISE1(f64x2_nearest, 2, v_f64, __builtin_rint(a[i]))
static inline v128 i32x4_trunc_sat_f32x4_s(v128 a_) { v_f32 a = (v_f32)a_; v_u32 r; for (int i = 0; i < 4; i++) r[i] = i32_trunc_sat_f32_s(a[i]); return (v128)r; }
static inline v128 i32x4_trunc_sat_f32x4_u(v128 a_) { v_f32 a = (v_f32)a_; v_u32 r; for (int i = 0; i < 4; i++) r[i] = i32_trunc_sat_f32_u(a[i]); return (v128)r; }
static inline v128 i32x4_trunc_sat_f64x2_s_zero(v128 a_) { v_f64 a = (v_f64)a_; v_u32 r = {i32_trunc_sat_f64_s(a[0]), i32_trunc_sat_f64_s(a[1]), 0, 0}; return (v128)r; }
static inline v128 i32x4_trunc_sat_f64x2_u_zero(v128 a_) { v_f64 a = (v_f64)a_; v_u32 r = {i32_trunc_sat_f64_u(a[0]), i32_trunc_sat_f64_u(a[1]), 0, 0}; return (v128)r; }
static inline v128 f32x4_convert_i32x4_s(v128 a) { return (v128)__builtin_convertvector((v_i32)a, v_f32); }
static inline v128 f32x4_convert_i32x4_u(v128 a) { return (v128)__builtin_convertvector((v_u32)a, v_f32); }
static inline v128 f64x2_convert_low_i32x4_s(v128 a_) { v_i32 a = (v_i32)a_; v_f64 r = {(double)a[0], (double)a[1]}; return (v128)r; }
static inline v128 f64x2_convert_low_i32x4_u(v128 a_) { v_u32 a = (v_u32)a_; v_f64 r = {(double)a[0], (double)a[1]}; return (v128)r; }
static inline v128 f32x4_demote_f64x2_zero(v128 a_) { v_f64 a = (v_f64)a_; v_f32 r = {(float)a[0], (float)a[1], 0, 0}; return (v128)r; }
static inline v128 f64x2_promote_low_f32x4(v128 a_) { v_f32 a = (v_f32)a_; v_f64 r = {(double)a[0], (double)a[1]}; return (v128)r; }
#define V_NARROW(name, NL, SRC, DST, lo, hi) static inline v128 name(v128 a_, v128 b_) { SRC a = (SRC)a_, b = (SRC)b_; DST r; \
  for (int i = 0; i < NL; i++) { int64_t x = i < NL / 2 ? a[i] : b[i - NL / 2]; r[i] = x < lo ? lo : x > hi ? hi : x; } return (v128)r; }
V_NARROW(i8x16_narrow_i16x8_s, 16, v_i16, v_i8, -128, 127) V_NARROW(i8x16_narrow_i16x8_u, 16, v_i16, v_u8, 0, 255)
V_NARROW(i16x8_narrow_i32x4_s, 8, v_i32, v_i16, -32768, 32767) V_NARROW(i16x8_narrow_i32x4_u, 8, v_i32, v_u16, 0, 65535)
static inline v128 i8x16_swizzle(v128 a_, v128 b_) { v_u8 a = (v_u8)a_, b = (v_u8)b_, r; for (int i = 0; i < 16; i++) r[i] = b[i] < 16 ? a[b[i]] : 0; return (v128)r; }
#define V_EXTADD(name, NL, SRC, DST) static inline v128 name(v128 a_) { SRC a = (SRC)a_; DST r; for (int i = 0; i < NL; i++) r[i] = a[2 * i] + a[2 * i + 1]; return (v128)r; }
V_EXTADD(i16x8_extadd_pairwise_i8x16_s, 8, v_i8, v_i16) V_EXTADD(i16x8_extadd_pairwise_i8x16_u, 8, v_u8, v_u16)
V_EXTADD(i32x4_extadd_pairwise_i16x8_s, 4, v_i16, v_i32) V_EXTADD(i32x4_extadd_pairwise_i16x8_u, 4, v_u16, v_u32)
#define V_EXTMUL(name, NL, SRC, DST, off) static inline v128 name(v128 a_, v128 b_) { SRC a = (SRC)a_, b = (SRC)b_; DST r; for (int i = 0; i < NL; i++) r[i] = (DST){0}[0] + a[i + off] * b[i + off]; return (v128)r; }
V_EXTMUL(i16x8_extmul_low_i8x16_s, 8, v_i8, v_i16, 0) V_EXTMUL(i16x8_extmul_high_i8x16_s, 8, v_i8, v_i16, 8)
V_EXTMUL(i16x8_extmul_low_i8x16_u, 8, v_u8, v_u16, 0) V_EXTMUL(i16x8_extmul_high_i8x16_u, 8, v_u8, v_u16, 8)
static inline v128 i32x4_extmul_low_i16x8_s(v128 a_, v128 b_) { v_i16 a = (v_i16)a_, b = (v_i16)b_; v_i32 r; for (int i = 0; i < 4; i++) r[i] = (int32_t)a[i] * b[i]; return (v128)r; }
static inline v128 i32x4_extmul_high_i16x8_s(v128 a_, v128 b_) { v_i16 a = (v_i16)a_, b = (v_i16)b_; v_i32 r; for (int i = 0; i < 4; i++) r[i] = (int32_t)a[i + 4] * b[i + 4]; return (v128)r; }
static inline v128 i32x4_extmul_low_i16x8_u(v128 a_, v128 b_) { v_u16 a = (v_u16)a_, b = (v_u16)b_; v_u32 r; for (int i = 0; i < 4; i++) r[i] = (uint32_t)a[i] * b[i]; return (v128)r; }
static inline v128 i32x4_extmul_high_i16x8_u(v128 a_, v128 b_) { v_u16 a = (v_u16)a_, b = (v_u16)b_; v_u32 r; for (int i = 0; i < 4; i++) r[i] = (uint32_t)a[i + 4] * b[i + 4]; return (v128)r; }
static inline v128 i64x2_extmul_low_i32x4_s(v128 a_, v128 b_) { v_i32 a = (v_i32)a_, b = (v_i32)b_; v_i64 r = {(int64_t)a[0] * b[0], (int64_t)a[1] * b[1]}; return (v128)r; }
static inline v128 i64x2_extmul_high_i32x4_s(v128 a_, v128 b_) { v_i32 a = (v_i32)a_, b = (v_i32)b_; v_i64 r = {(int64_t)a[2] * b[2], (int64_t)a[3] * b[3]}; return (v128)r; }
static inline v128 i64x2_extmul_low_i32x4_u(v128 a_, v128 b_) { v_u32 a = (v_u32)a_, b = (v_u32)b_; v_u64 r = {(uint64_t)a[0] * b[0], (uint64_t)a[1] * b[1]}; return (v128)r; }
static inline v128 i64x2_extmul_high_i32x4_u(v128 a_, v128 b_) { v_u32 a = (v_u32)a_, b = (v_u32)b_; v_u64 r = {(uint64_t)a[2] * b[2], (uint64_t)a[3] * b[3]}; return (v128)r; }
static inline v128 i32x4_dot_i16x8_s(v128 a_, v128 b_) { v_i16 a = (v_i16)a_, b = (v_i16)b_; v_i32 r; for (int i = 0; i < 4; i++) r[i] = (int32_t)((uint32_t)((int32_t)a[2*i] * b[2*i]) + (uint32_t)((int32_t)a[2*i+1] * b[2*i+1])); return (v128)r; }
#endif /* W2C_HOST_ONLY */
#endif
