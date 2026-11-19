// cxe.cpp - the cxe test engine host: plays one Cambridge Battlecode 2026 match natively.
// The rules are the real engine 2.0.0 (condor-work/engine/v2_0_0.wasm translated to C by tools/cxe/w2c.py); each
// team's bot is its own WebAssembly build translated the same way with fuel metering and loaded as a shared library.
// This file re-implements what the official CLI host does around them: one bot instance per draft team and per
// champion, run as coroutines that suspend on yield or when out of fuel, the 91 env imports (spec:
// /data/zw4424/st/cxe/importmap.md, read from the CLI's own host code), per-turn fuel budgets, and the runner loop.
// usage: cxe BOT_A.so BOT_B.so MAP.map26a OUT_PREFIX [--fuel N] [--rounds N]
//   writes OUT_PREFIX.repl26a (the engine's own replay), OUT_PREFIX.fuel.tsv (per-turn fuel use) and prints a summary.
#define W2C_HOST_ONLY 1
extern "C" {
#include "w2c_rt.h"
#include "cxe_imports.h"
extern const w2c_module engine_module;
void w2c_mem_free(w2c_inst *I);
typedef void (*cxe_log_fn)(w2c_inst *I, int fd, const uint8_t *p, uint32_t n);
extern cxe_log_fn cxe_log_sink;
}
#include <dlfcn.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <deque>
#include <map>
#include <tuple>

// ------------------------------------------------------------------ engine
static w2c_inst EI;     // engine instance
static uint64_t G;      // game handle
static uint32_t SC;     // engine scratch base (Engine_Malloc)
enum : uint32_t { SC_IDENT = 0, SC_META = 16, SC_ST = 48, SC_TMP = 64, SC_T2 = 128, SC_POS = 192, SC_TGT = 200, SC_BUF = 1024 };
static const uint32_t SC_SIZE = 1u << 21;
static uint32_t META[5], BB, FB, CH;
static uint8_t METAB[28];

template <class... A> static inline uint32_t ec(void *f, A... a) { return ((uint32_t(*)(w2c_inst *, A...))f)(&EI, a...); }
static void *efn(const char *n) {
  void *f = engine_module.export_fn(n);
  if (!f) { fprintf(stderr, "cxe: engine export %s missing\n", n); abort(); }
  return f;
}
#define EF(name) ([]() -> void * { static void *f_ = efn(#name); return f_; }())
#define E(name, ...) ec(EF(name), __VA_ARGS__)
static inline uint8_t *em() { return EI.mem; }
static inline uint32_t erd(uint32_t a) { return ld_u32(EI.mem, a); }
static inline void ewr(uint32_t a, uint32_t v) { st_u32(EI.mem, a, v); }

// ------------------------------------------------------------------ coroutines
// Minimal x86-64 SysV context switch: saves the callee-saved registers and the SSE/x87 control words on the
// current stack, stores the stack pointer in *from and resumes *to. No signal-mask system call (swapcontext made
// one per switch: ~21,000 a game).
extern "C" void cxe_ctx_switch(void **from, void *to);
__asm__(".text\n.globl cxe_ctx_switch\n.type cxe_ctx_switch,@function\ncxe_ctx_switch:\n"
        "pushq %rbp\npushq %rbx\npushq %r12\npushq %r13\npushq %r14\npushq %r15\n"
        "subq $8, %rsp\nstmxcsr (%rsp)\nfnstcw 4(%rsp)\n"
        "movq %rsp, (%rdi)\nmovq %rsi, %rsp\n"
        "ldmxcsr (%rsp)\nfldcw 4(%rsp)\naddq $8, %rsp\n"
        "popq %r15\npopq %r14\npopq %r13\npopq %r12\npopq %rbx\npopq %rbp\nret\n");
// a fresh context that starts in entry() on the given stack
static void *ctx_new(void *stack, size_t size, void (*entry)()) {
  uintptr_t top = ((uintptr_t)stack + size) & ~(uintptr_t)15;
  uint64_t *a = (uint64_t *)(top - 16);  // return address slot: entry then sees rsp % 16 == 8, as after a call
  a[0] = (uint64_t)(uintptr_t)entry;
  for (int i = 1; i <= 6; i++) a[-i] = 0;       // rbp rbx r12 r13 r14 r15
  uint32_t *cw = (uint32_t *)(a - 7);
  cw[0] = 0x1f80;                               // MXCSR default
  cw[1] = 0x037f;                               // x87 control word default
  return (void *)(a - 7);
}

// ------------------------------------------------------------------ bots
enum Stop { ST_NONE, ST_YIELD, ST_FUEL, ST_TRAP, ST_EXIT };
struct Bot {
  w2c_inst I;
  const w2c_module *mod;
  int team, champ;  // champ = engine champion index, -1 for the draft instance
  void *ctx;  // saved stack pointer while suspended
  void *stack;
  size_t stack_size;
  bool started, finished;
  bool picked;  // the draft instance made a pick this turn (GameRules :88)
  Stop stop;
  jmp_buf trap_jb;
  int64_t budget;
  // The CLI meters a turn in slices of one quantum (first draft turn 100, first champion turn 2): I->fuel is the active slice, reserve what is held back.
  // Measured 7 Nov, 953 readings of 5,988 bot-games: a wasm fuel check refills the slice and keeps any overshoot; until that check a reading stops at the slice end
  // (the CLI's value is a multiple of the quantum); a host charge works on that value, so an overshoot is forgiven, and one that reaches the slice end starts the next slice.
  int64_t reserve, slice;
  uint64_t opc0[512];
  int64_t carry;  // fuel used past the budget in a cut turn; the CLI's log books it to the bot's next turn
  bool phase_v2 = false;  // 13 Nov (owner via Shared Mem: intentional v unintentional fuel): a "2FPH" marker also holds [3] = fuel used before the post-action phase
  int64_t phase_addr = -1;  // 12 Nov (PCQ, RC C848 B3): linear-memory address of the bot's cut-phase word (nova_fuel_phase), -1 = none
};
static void *host_ctx;
static Bot *cur;
static FILE *g_pagelog = nullptr;  // CXE_PAGES_LOG=1: OUT_PREFIX.pages.tsv
static FILE *g_cphase = nullptr;  // OUT_PREFIX.cphase.tsv, opened at the first out-of-fuel stop of a bot that holds the cut-phase marker
static std::string g_pre;
static const size_t STACK = 64u << 20;  // lazily committed; wasm call depth maps onto it

static void bot_entry() {
  Bot *b = cur;
  b->I.trap_jb = &b->trap_jb;
  if (!setjmp(b->trap_jb)) {
    ((void (*)(w2c_inst *))b->mod->export_fn("_start"))(&b->I);
    b->stop = ST_EXIT;
  } else {
    b->stop = ST_TRAP;
  }
  b->finished = true;
  cxe_ctx_switch(&b->ctx, host_ctx);
  abort();  // never resumed
}

// --fork-at R --alt ALT.so: the bytes where ALT's initial linear memory differs from the base module's (a data-only flip
// changes only its flag tables), applied to every instance of the flipped team in a forked child (and to its later instances)
struct Patch {
  std::string name;
  std::vector<uint32_t> off;
  std::vector<uint8_t> base, alt;
};
static const Patch *g_patch;
static int g_patch_team = -1;
static int apply_patch(w2c_inst *I, const Patch &p) {  // -> bytes that no longer held the base's initial value (not const data)
  int changed = 0;
  for (size_t k = 0; k < p.off.size(); k++) {
    changed += I->mem[p.off[k]] != p.base[k];
    I->mem[p.off[k]] = p.alt[k];
  }
  return changed;
}

static Bot *new_bot(const w2c_module *mod, int team, int champ) {
  Bot *b = new Bot();
  b->mod = mod;
  b->team = team;
  b->champ = champ;
  b->I.host = b;
  if (mod->init(&b->I)) { fprintf(stderr, "cxe: bot init failed\n"); exit(1); }
  {  // 11 Nov (Path Finding DFG / owner game 01a1ca3d): CXE_MAX_PAGES=N caps a BOT's memory.grow at N wasm pages (grow returns -1 above
     // it, as wasm does) to test a lower platform memory limit. Unset: no change (the module's own maximum). The engine is never capped.
    static const long long cap = getenv("CXE_MAX_PAGES") ? atoll(getenv("CXE_MAX_PAGES")) : 0;
    if (cap > 0 && b->I.max_pages > (uint64_t)cap) b->I.max_pages = b->I.pages > (uint64_t)cap ? b->I.pages : (uint64_t)cap;
  }
  if (g_patch && team == g_patch_team) apply_patch(&b->I, *g_patch);  // before _start: as if built from the flip
  {  // 12 Nov (PCQ cut-phase marker, owner via the Coordinator; RC C848 B3): a bot may hold, in its data segment,
     //   alignas(4) volatile uint32_t nova_fuel_phase[3] = {0x41564F4Eu, 0x48504631u, 0};   ("NOVA" "1FPH" then the phase word)
     // and set [2] = 1 where its post-action phase begins, 0 at turn start. cxe finds the two magic words once here (no call into the bot)
     // and, at each out-of-fuel stop, logs the phase word to OUT.cphase.tsv. A bot without the marker: nothing found, nothing logged.
    // 13 Nov (owner, typed to Shared Mem: "differentiate between intentional and unintentional fuel faults"): v2 marker
    //   alignas(4) volatile uint32_t nova_fuel_phase[4] = {0x41564F4Eu, 0x48504632u, 0, 0};   ("NOVA" "2FPH", phase word, pre-action used)
    // the bot sets [3] = fuel used this turn at the moment it sets [2] = 1 (0 both at turn start); the fuel log's last column 'pre' then
    // holds [3] for a turn whose phase reached 1, else the whole turn (a turn cut before its actions ends counts in full). Logging only.
    static const uint32_t MG[2] = {0x41564F4Eu, 0x48504631u};
    static const uint32_t MG2[2] = {0x41564F4Eu, 0x48504632u};
    uint64_t n = b->I.pages << 16;
    for (uint64_t a = 0; a + 16 <= n; a += 4) {
      if (!memcmp(b->I.mem + a, MG, 8)) { b->phase_addr = (int64_t)(a + 8); break; }
      if (!memcmp(b->I.mem + a, MG2, 8)) { b->phase_addr = (int64_t)(a + 8); b->phase_v2 = true; break; }
    }
  }
  b->I.opc = (uint64_t *)calloc(512, sizeof(uint64_t));
  b->I.fprof = (uint64_t *)calloc(2 * (size_t)(mod->nfuncs + mod->nimports) + 2, sizeof(uint64_t));
  b->stack_size = STACK;
  b->stack = mmap(nullptr, STACK, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
  return b;
}
// CXE_FUELPROF=PATH: per-team totals of --fuelprof bots' per-function fuel (instances are summed when freed)
static std::vector<uint64_t> g_fprof[2];
static void fprof_add(Bot *b) {
  size_t n = 2 * (size_t)(b->mod->nfuncs + b->mod->nimports);
  auto &v = g_fprof[b->team];
  if (v.size() < n) v.resize(n, 0);
  for (size_t i = 0; i < n; i++) v[i] += b->I.fprof[i];
}
static void free_bot(Bot *b) {
  fprof_add(b);
  free(b->I.fprof);
  free(b->I.opc);
  w2c_mem_free(&b->I);
  munmap(b->stack, b->stack_size);
  free(b->I.table);
  free(b->I.exn);
  delete b;
}

// ------------------------------------------------------------------ fuel record / replay (9 Nov, puppet --diag)
// CXE_FUEL_REC=PATH: per bot turn, every value fuel_remaining() returned and how the turn ended (yield, or out of fuel after k
// counted host calls) -> PATH. CXE_FUEL_PLAY=PATH: each turn found in PATH (key phase, round, team, champion) plays with no fuel
// limit (cap FP_CAP), fuel_remaining() returns the recorded values in order, and a turn recorded as cut after k host calls is
// suspended at its (k+1)-th, before running it, as an out-of-fuel suspension would be. A diag copy whose code differs (so its
// instruction counts do) then sees the fuel and the cut-offs of the real game. Counted calls: every env import with TI() plus
// yield; pure ones (bitboard algebra, cxe_probe, WASI writes) are not counted, so they may land on either side of a cut. Turns
// without a record, or whose readings/end differ, are reported on stderr ("cxe: fuel-play"); a turn without a record plays with
// normal metering. Neither variable set: nothing here runs (normal games are unchanged). Not supported with --fork-at.
struct FpTurn { int stop = 0; long calls = 0; std::vector<uint64_t> v; };
static FILE *g_fprec;
static bool g_fpon;              // either mode
static bool g_fpplay;            // CXE_FUEL_PLAY loaded
static std::map<std::tuple<int, int, int, int>, std::deque<FpTurn>> g_fptab;
static FpTurn g_fpcur;           // play: this turn's record
static FpTurn *g_fpt;            // play: &g_fpcur when this turn replays, else null
static size_t g_fpvi;            // play: next value
static long g_fpcalls;           // counted host calls in this turn
static std::vector<uint64_t> g_fprv;  // rec: this turn's readings
static int g_fpk[4];             // this turn: phase round team champ
static long g_fp_turns, g_fp_bad, g_fp_nokey;
static bool g_fp_turnbad;
static const int64_t FP_CAP = 4000000000LL;
static void fp_warn(const char *why, long a = 0, long b = 0) {
  if (!g_fp_turnbad) g_fp_bad++;
  g_fp_turnbad = true;
  if (g_fp_bad <= 30)
    fprintf(stderr, "cxe: fuel-play mismatch phase %d r%d team %c champ %d: %s (%ld %ld)\n", g_fpk[0], g_fpk[1], "AB"[g_fpk[2] & 1], g_fpk[3], why, a, b);
}
static void fp_begin(int ph, int round, int team, int ch) {
  g_fpk[0] = ph; g_fpk[1] = round; g_fpk[2] = team; g_fpk[3] = ch;
  g_fpcalls = 0;
  g_fpvi = 0;
  g_fp_turnbad = false;
  g_fprv.clear();
  g_fpt = nullptr;
  if (!g_fpplay) return;
  auto it = g_fptab.find(std::make_tuple(ph, round, team, ch));
  if (it == g_fptab.end() || it->second.empty()) {
    g_fp_nokey++;
    if (g_fp_nokey <= 10) fprintf(stderr, "cxe: fuel-play: no record for phase %d r%d team %c champ %d: normal metering\n", ph, round, "AB"[team & 1], ch);
    return;
  }
  g_fpcur = std::move(it->second.front());
  it->second.pop_front();
  g_fpt = &g_fpcur;
  g_fp_turns++;
}
static void fp_end(int why) {
  if (g_fprec) {
    fprintf(g_fprec, "%d %d %d %d %d %ld %zu", g_fpk[0], g_fpk[1], g_fpk[2], g_fpk[3], why, g_fpcalls, g_fprv.size());
    for (uint64_t v : g_fprv) fprintf(g_fprec, " %llu", (unsigned long long)v);
    fputc('\n', g_fprec);
  }
  if (g_fpt) {
    if (why != g_fpt->stop) fp_warn("turn end differs (stop rec/play; 1 yield 2 fuel 3 trap 4 exit)", g_fpt->stop, why);
    else if (why == ST_YIELD && g_fpcalls != g_fpt->calls) fp_warn("host calls before yield differ (rec/play)", g_fpt->calls, g_fpcalls);
    if (g_fpvi < g_fpt->v.size()) fp_warn("fewer fuel readings than recorded (rec/play)", (long)g_fpt->v.size(), (long)g_fpvi);
  }
  g_fpt = nullptr;
}

// run b for one turn with the given budget; returns why it stopped
static inline int64_t used_of(Bot *b) { return b->I.fuel + b->budget - b->reserve; }
static Stop run_turn(Bot *b, int64_t budget, int64_t slice) {
  if (b->finished) return ST_EXIT;
  cur = b;
  b->budget = budget;
  b->slice = slice;
  int64_t active = budget < slice ? budget : slice;
  b->reserve = budget - active;
  b->I.fuel = -active;
  if (g_fpt) { b->reserve = 0; b->I.fuel = -FP_CAP; }  // CXE_FUEL_PLAY: the record sets the readings and the cut
  b->stop = ST_NONE;
  b->picked = false;
  if (!b->started) {
    b->started = true;
    b->ctx = ctx_new(b->stack, b->stack_size, bot_entry);
  }
  cxe_ctx_switch(&host_ctx, b->ctx);
  cur = nullptr;
  return b->stop;
}

static bool g_trace_bulk;  // CXE_TRACE_BULK with CXE_TRACE=ROUND:CHAMP: log bulk memory ops of a --profile bot
extern "C" void w2c_prof_bulk(w2c_inst *I, int kind, uint32_t d, uint32_t s, uint32_t n);
// 10 Nov (Rule Checker): fuelprof/cutprof builds ask this before w2c_out_of_fuel, so only a real cut is counted: true when the
// reserve can't bring the fuel back under the budget, i.e. the call below will suspend the bot (same arithmetic, no side effects).
extern "C" int w2c_fuel_will_cut(w2c_inst *I) {
  Bot *b = (Bot *)I->host;
  int64_t f = I->fuel, r = b->reserve;
  while (f >= 0 && r > 0) { int64_t a = r < b->slice ? r : b->slice; r -= a; f -= a; }
  return f >= 0;
}
extern "C" void w2c_out_of_fuel(w2c_inst *I) {
  Bot *b = (Bot *)I->host;
  while (I->fuel >= 0 && b->reserve > 0) {  // the next slice; the overshoot stays
    int64_t a = b->reserve < b->slice ? b->reserve : b->slice;
    b->reserve -= a;
    I->fuel -= a;
  }
  if (I->fuel < 0) return;
  b->stop = ST_FUEL;
  cxe_ctx_switch(&b->ctx, host_ctx);
}
// a counted host call (fuel record / replay): in a replayed turn recorded as cut after k calls, the (k+1)-th suspends before it runs
static inline void fp_call(w2c_inst *I) {
  if (!g_fpon) return;
  g_fpcalls++;
  while (g_fpt && g_fpt->stop == ST_FUEL && g_fpcalls == g_fpt->calls + 1) {
    Bot *b = (Bot *)I->host;
    b->stop = ST_FUEL;
    cxe_ctx_switch(&b->ctx, host_ctx);
    g_fpcalls = 1;  // resumed in a new turn (fp_begin reset the count): this call is its first
  }
}
extern "C" void cxe_imp_env__yield(w2c_inst *I) {
  fp_call(I);
  Bot *b = (Bot *)I->host;
  b->stop = ST_YIELD;
  cxe_ctx_switch(&b->ctx, host_ctx);
}

static int g_round;
static int g_wards[2];
static bool g_trace_err, g_trace_list;  // CXE_TRACE_ERR / CXE_TRACE_LIST, read once  // successful ward placements per team (the CLI's wardPlacement events)
static bool g_trace_imports;  // CXE_TRACE_IMPORTS=1 with CXE_TRACE=ROUND:CHAMP
struct TraceImport {
  w2c_inst *I; const char *f; bool on;
  TraceImport(w2c_inst *i, const char *fn);
  ~TraceImport();
};
// ------------------------------------------------------------------ marshalling between bot and engine memory
static inline Bot *B(w2c_inst *I) { return (Bot *)I->host; }
TraceImport::TraceImport(w2c_inst *i, const char *fn) : I(i), f(fn), on(false) {
  fp_call(i);
  extern int g_trace_turn_key();
  on = g_trace_imports && g_trace_turn_key() == g_round * 100 + B(I)->champ + 1;
  if (on) fprintf(stderr, "imp %s used %lld\n", f + 13, (long long)used_of(B(I)));
}
TraceImport::~TraceImport() { if (on) fprintf(stderr, "    -> used %lld\n", (long long)used_of(B(I))); }
static inline uint64_t bmsize(w2c_inst *I) { return I->pages << 16; }
// pointer checks: memory family (null ok) and guest_ptr family (null with a non-zero size fails)
static inline bool okm(w2c_inst *I, uint32_t p, uint64_t n, uint32_t al) {
  return (int32_t)p >= 0 && (uint64_t)p + n <= bmsize(I) && (al <= 1 || p % al == 0);
}
static inline bool okg(w2c_inst *I, uint32_t p, uint64_t n, uint32_t al) { return !(p == 0 && n > 0) && okm(I, p, n, al); }
static int g_trace = -2;
int g_trace_turn_key() { return g_trace; }  // CXE_TRACE=ROUND:CHAMP logs every host fuel charge in that turn
#include <map>
static bool g_chargelog;
static FILE *g_opclog;  // CXE_CHARGELOG=1: per-turn host fuel by import -> OUT.charges.tsv
static std::map<const char *, std::pair<long, long long>> g_turn_charges;
static inline void charge_(w2c_inst *I, int64_t u, const char *who) {
  Bot *b = (Bot *)I->host;
  int64_t left = I->fuel < 0 ? -I->fuel : 0;
  if (u > 0 && b->reserve > 0 && u >= left) {  // the charge is taken from the total as the bot reads it (an overshoot is forgiven), and the next slice starts here
    int64_t a = b->reserve < b->slice ? b->reserve : b->slice;
    b->reserve -= a;
    I->fuel = u - left - a;
  } else I->fuel += u;
  if (g_chargelog) { auto &e = g_turn_charges[who]; e.first++; e.second += u; }
  if (g_trace >= 0 && g_trace == g_round * 100 + ((Bot *)I->host)->champ + 1) fprintf(stderr, "charge %s %lld\n", who, (long long)u);
}
#define charge(I, u) charge_(I, u, __func__)
static inline uint32_t c8(uint64_t n) { return (uint32_t)((n + 7) / 8); }

struct Mx {  // one call's buffers
  w2c_inst *I;
  uint32_t bump = SC + SC_BUF;
  struct Buf { uint32_t g, e, n; bool back; };
  Buf v[12];
  int k = 0;
  explicit Mx(w2c_inst *i) : I(i) {}
  uint32_t map(uint32_t g, uint32_t n, bool back) {
    for (int i = 0; i < k; i++)
      if (v[i].g == g && n) {
        if (n > v[i].n) { memcpy(em() + v[i].e + v[i].n, I->mem + g + v[i].n, n - v[i].n); v[i].n = n; }
        v[i].back |= back;
        return v[i].e;
      }
    uint32_t e = (bump + 15) & ~15u;
    bump = e + n;
    if (n) memcpy(em() + e, I->mem + g, n);
    v[k++] = {g, e, n, back};
    return e;
  }
  uint32_t in(uint32_t g, uint32_t n) { return map(g, n, false); }
  uint32_t out(uint32_t g, uint32_t n) { return map(g, n, true); }
  ~Mx() {
    for (int i = 0; i < k; i++)
      if (v[i].back && v[i].n) memcpy(I->mem + v[i].g, em() + v[i].e, v[i].n);
  }
};
static inline uint32_t ident(w2c_inst *I) {
  ewr(SC + SC_IDENT, (uint32_t)B(I)->team);
  ewr(SC + SC_IDENT + 4, (uint32_t)B(I)->champ);
  return SC + SC_IDENT;
}
static inline uint32_t meta() { return SC + SC_META; }
static inline uint32_t pos(int32_t x, int32_t y) { ewr(SC + SC_POS, (uint32_t)x); ewr(SC + SC_POS + 4, (uint32_t)y); return SC + SC_POS; }
static void get_state(int32_t s[4]) {
  E(Game_Runner_GetState, G, SC + SC_ST);
  for (int i = 0; i < 4; i++) s[i] = (int32_t)erd(SC + SC_ST + 4 * i);
}
static bool idchk(w2c_inst *I) {
  int32_t s[4];
  get_state(s);
  Bot *b = B(I);
  return s[0] != 2 && s[1] == b->team && (s[0] == 0 ? b->champ == -1 : b->champ == s[3]);
}
#define NEG1 0xffffffffu
// out-pointer query: engine(g, &ident?, args..., out) with an n-byte out record
#define QOUT(n, al, call)                    \
  do {                                       \
    if (!okm(I, out, n, al)) return NEG1;    \
    Mx m(I);                                 \
    uint32_t o = m.out(out, n);              \
    return call;                             \
  } while (0)

// --record: every action call (round, champion, action, return code, arguments[, the result word it wrote]) and every turn's
// fuel, host-side only (no engine call), written as the "cxe" part of OUT.rdec.json
static bool g_rec;
static std::string g_acts, g_turnrec;
static uint32_t rec_act(w2c_inst *I, const char *nm, uint32_t rc, std::initializer_list<long long> a, uint32_t out = 0) {
  if (!g_rec) return rc;
  char b[96];
  int n = snprintf(b, sizeof b, "%s[%d,%d,\"%s\",%u", g_acts.empty() ? "" : ",", g_round, B(I)->champ, nm, rc);
  g_acts.append(b, n);
  for (long long v : a) { n = snprintf(b, sizeof b, ",%lld", v); g_acts.append(b, n); }
  if (out) { n = snprintf(b, sizeof b, ",%u", ld_u32(I->mem, out)); g_acts.append(b, n); }
  g_acts += ']';
  return rc;
}
#define REC(nm, call, ...) rec_act(I, nm, (call), {__VA_ARGS__})
#define RECO(nm, call, ...) rec_act(I, nm, (call), {__VA_ARGS__}, out)

extern "C" {
#define ENV(name) cxe_imp_env__##name
#define TI() TraceImport ti_(I, __func__)
// ---- host state
uint32_t ENV(my_team)(w2c_inst *I) { TI(); return (uint32_t)B(I)->team; }
uint32_t ENV(my_champion)(w2c_inst *I) { TI(); return (uint32_t)B(I)->champ; }
// 11 Nov (Path Finding / ab68d3: dgkit debug copies import these; MissingImports in cxeident). CAMBC_DEBUG-only SDK imports
// (imports.h): fuel_pause() starts a free window (the meter's count is saved and the window gets ample room, so no cut lands
// inside it), fuel_resume() restores the saved count, fuel_adjust(d) refunds d (a positive d lowers the charged count, floor 0; the
// SDK's DebugGuard calls adjust(2) to refund its own call overhead, then resume; inside a window it adjusts the count resume restores). Release bots never import them.
static int64_t g_pause_saved[2][64];
static bool g_paused[2][64];
static inline int pause_slot(w2c_inst *I) { int c = B(I)->champ + 1; return c < 0 ? 0 : (c > 63 ? 63 : c); }
uint32_t ENV(fuel_pause)(w2c_inst *I) { TI();
  int t = B(I)->team & 1, c = pause_slot(I);
  if (g_paused[t][c]) return 1;
  g_paused[t][c] = true;
  g_pause_saved[t][c] = I->fuel;
  I->fuel = I->fuel - (int64_t)1000000000000LL;
  return 0;
}
void ENV(fuel_resume)(w2c_inst *I) { TI();
  int t = B(I)->team & 1, c = pause_slot(I);
  if (!g_paused[t][c]) return;
  g_paused[t][c] = false;
  I->fuel = g_pause_saved[t][c];
}
void ENV(fuel_adjust)(w2c_inst *I, uint64_t d) { TI();
  int t = B(I)->team & 1, c = pause_slot(I);
  int64_t &f = g_paused[t][c] ? g_pause_saved[t][c] : I->fuel;
  int64_t floor_f = B(I)->reserve - B(I)->budget;  // used_of() == 0 at this value
  f -= (int64_t)d;
  if (f < floor_f) f = floor_f;
}
uint64_t ENV(fuel_remaining)(w2c_inst *I) { TI();
  // CXE_FUEL_CONST=N (8 Nov, test only, never set by the pipeline): fuel_remaining() always N, so a bot's self-measured costs (draft
  // cost_plan, dashnav build cost ...) are 0 in every build: a pattern- v zero-init differential then shows only uninitialised reads
  static const char *fc = getenv("CXE_FUEL_CONST");
  if (fc) return strtoull(fc, nullptr, 10);
  if (g_fpt) {  // CXE_FUEL_PLAY: the recorded reading; past the record, what normal metering would read (and say so)
    if (g_fpvi < g_fpt->v.size()) return g_fpt->v[g_fpvi++];
    fp_warn("more fuel readings than recorded (rec, reading no.)", (long)g_fpt->v.size(), (long)++g_fpvi);
    int64_t used = FP_CAP + I->fuel;
    return used < B(I)->budget ? (uint64_t)(B(I)->budget - used) : 0;
  }
  uint64_t v = (uint64_t)B(I)->reserve + (I->fuel >= 0 ? 0 : (uint64_t)(-I->fuel));
  if (g_fprec) g_fprv.push_back(v);
  return v; }
// CXE_PROBE=PATH (estimator check, tools/cxe/estcheck.py): env.cxe_probe(kind, a, b, c, v) from a probe copy (tools/cxe/estprobe.py,
// nova_est_*) appends "round team champion kind a b c v" (tab-separated) to PATH, written at exit. No host fuel charge (the guest's
// call itself is metered as usual). No normal bot imports it, so normal games are unchanged (cxeverify); platlock.sh's submit guard
// refuses a bot that declares a host import, so a probe copy can never ship.
static std::string g_probe;
static bool g_probe_on;
void ENV(cxe_probe)(w2c_inst *I, uint32_t k, uint32_t a, uint32_t b, uint32_t c, uint32_t v) {
  if (!g_probe_on) return;
  char s[112];
  int n = snprintf(s, sizeof s, "%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n", g_round, B(I)->team, B(I)->champ, (int32_t)k, (int32_t)a, (int32_t)b,
                   (int32_t)c, (int32_t)v);
  g_probe.append(s, n);
}
uint32_t ENV(bc_metadata)(w2c_inst *I, uint32_t out) { TI();
  if (!okm(I, out, 28, 4)) return NEG1;
  memcpy(I->mem + out, METAB, 28);
  return 0;
}
// ---- actions and draft
uint32_t ENV(draft_memory_size)(w2c_inst *I, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_GetDraftMemorySize, G, o)); }
#define OUTFIRST() do { if (!okm(I, out, 4, 4)) return NEG1; st_u32(I->mem, out, 0); if (!idchk(I)) return 18; } while (0)
uint32_t ENV(move_to_with_result)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI();
  OUTFIRST(); uint32_t rc; { Mx m(I); uint32_t o = m.out(out, 4); rc = E(Game_Action_Move, G, x, y, o); }
  return RECO("move", rc, (int32_t)x, (int32_t)y);
}
uint32_t ENV(attack)(w2c_inst *I, uint32_t kind, uint32_t handle) { TI();
  if (!idchk(I)) return 18;
  ewr(SC + SC_TGT, kind); ewr(SC + SC_TGT + 4, handle);
  return REC("attack", E(Game_Action_Attack, G, SC + SC_TGT), kind, handle);
}
uint32_t ENV(cast_with_result)(w2c_inst *I, uint32_t slot, uint32_t kind, uint32_t handle, uint32_t x, uint32_t y, uint32_t out) { TI();
  OUTFIRST(); uint32_t rc;
  { Mx m(I); uint32_t o = m.out(out, 4);
    ewr(SC + SC_TGT, kind); ewr(SC + SC_TGT + 4, handle);
    rc = E(Game_Action_Cast, G, slot, SC + SC_TGT, pos((int32_t)x, (int32_t)y), o); }
  return RECO("cast", rc, slot, kind, handle, (int32_t)x, (int32_t)y);
}
uint32_t ENV(use_consumable_with_result)(w2c_inst *I, uint32_t item, uint32_t x, uint32_t y, uint32_t out) { TI();
  OUTFIRST(); uint32_t rc; { Mx m(I); uint32_t o = m.out(out, 4); rc = E(Game_Action_UseConsumable, G, item, pos((int32_t)x, (int32_t)y), o); }
  return RECO("consumable", rc, item, (int32_t)x, (int32_t)y);
}
uint32_t ENV(place_ward_with_result)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI();
  OUTFIRST();
  uint32_t rc;
  { Mx m(I); uint32_t o = m.out(out, 4); rc = E(Game_Action_PlaceWard, G, pos((int32_t)x, (int32_t)y), o); }
  if (rc == 0 && ld_u32(I->mem, out) == 1) g_wards[B(I)->team]++;  // result 1 = placed (matches the CLI's wardPlacement events)
  return RECO("ward", rc, (int32_t)x, (int32_t)y);
}
uint32_t ENV(submit_gems)(w2c_inst *I, uint32_t x, uint32_t y) { TI();
  if (!idchk(I)) return 18; return REC("submit", E(Game_Action_SubmitGems, G, pos((int32_t)x, (int32_t)y)), (int32_t)x, (int32_t)y);
}
uint32_t ENV(recall)(w2c_inst *I) {
  TI();
  if (!idchk(I)) return 18;
  uint32_t rc = E(Game_Action_Recall, G);
  if (ti_.on) {
    uint32_t p = ((uint32_t(*)(w2c_inst *))EF(GetLastErrorMsg))(&EI);
    int32_t s[4]; get_state(s);
    fprintf(stderr, "    recall rc %u (%s) state %d %d %d %d\n", rc, p ? (const char *)em() + p : "", s[0], s[1], s[2], s[3]);
  }
  return REC("recall", rc, 0);
}
uint32_t ENV(cancel_channel)(w2c_inst *I) { TI(); if (!idchk(I)) return 18; return REC("cancel", E(Game_Action_CancelChannel, G), 0); }
uint32_t ENV(sell)(w2c_inst *I, uint32_t item) { TI(); if (!idchk(I)) return 18; return REC("sell", E(Game_Action_Sell, G, item), item); }
uint32_t ENV(buy_item)(w2c_inst *I, uint32_t t, uint32_t n) { TI(); if (!idchk(I)) return 18; return REC("buy", E(Game_Action_BuyItem, G, t, n), t, n); }
uint32_t ENV(buy_consumable)(w2c_inst *I, uint32_t t) { TI(); if (!idchk(I)) return 18; return REC("buy_consumable", E(Game_Action_BuyConsumable, G, t), t); }
uint32_t ENV(set_priority)(w2c_inst *I, uint32_t p) { TI(); if (!idchk(I)) return 18; return REC("priority", E(Game_Action_SetPriority, G, p), p); }
uint32_t ENV(draft_champion)(w2c_inst *I, uint32_t pick) { TI();
  if (E(Game_API_Draft_GetCurrentTeam, G, SC + SC_TMP) || (int32_t)erd(SC + SC_TMP) != B(I)->team) return 18;
  if (!idchk(I)) return 18;
  uint32_t rc = REC("draft", E(Game_Action_Draft, G, pick), pick);
  if (rc == 0) B(I)->picked = true;
  return rc;
}
uint32_t ENV(draft_get)(w2c_inst *I, uint32_t team, uint32_t round, uint32_t out) { TI();
  QOUT(4, 4, E(Game_API_Draft_Get, G, team, round & 0xffu, o));
}
uint32_t ENV(draft_num_rounds)(w2c_inst *I, uint32_t out) { TI();
  if (!okg(I, out, 1, 1)) return NEG1;
  Mx m(I); uint32_t o = m.out(out, 1); return E(Game_API_Draft_GetNumRounds, G, o);
}
// ---- bitboards
#define BBCHK(p) if (!okg(I, p, BB, 16)) return NEG1
uint32_t ENV(bc_Bitboard_Zero)(w2c_inst *I, uint32_t b) { TI(); BBCHK(b); charge(I, CH); Mx m(I); return E(Bitboard_Zero, meta(), m.out(b, BB)); }
uint32_t ENV(bc_Bitboard_Set)(w2c_inst *I, uint32_t b, uint32_t x, uint32_t y, uint32_t v) { TI(); BBCHK(b); Mx m(I); return E(Bitboard_Set, meta(), m.out(b, BB), x, y, v); }
uint32_t ENV(bc_Bitboard_Test)(w2c_inst *I, uint32_t b, uint32_t x, uint32_t y, uint32_t out) { TI();
  BBCHK(b); if (!okg(I, out, 4, 4)) return NEG1; Mx m(I); uint32_t e = m.in(b, BB); return E(Bitboard_Test, meta(), e, x, y, m.out(out, 4));
}
uint32_t ENV(bc_Bitboard_IsZero)(w2c_inst *I, uint32_t b, uint32_t out) { TI();
  BBCHK(b); if (!okg(I, out, 4, 4)) return NEG1; charge(I, CH); Mx m(I); uint32_t e = m.in(b, BB); return E(Bitboard_IsZero, meta(), e, m.out(out, 4));
}
uint32_t ENV(bc_Bitboard_NumSetBits)(w2c_inst *I, uint32_t b, uint32_t out) { TI();
  BBCHK(b); if (!okg(I, out, 4, 4)) return NEG1; charge(I, CH); Mx m(I); uint32_t e = m.in(b, BB); return E(Bitboard_NumSetBits, meta(), e, m.out(out, 4));
}
uint32_t ENV(bc_Bitboard_GetSetBits)(w2c_inst *I, uint32_t b, uint32_t p, uint32_t cap, uint32_t count) { TI();
  if ((int32_t)cap < 0) return NEG1;
  BBCHK(b); if (!okg(I, p, (uint64_t)cap * 8, 4) || !okg(I, count, 4, 4)) return NEG1;
  uint32_t rc;
  {
    Mx m(I); uint32_t e = m.in(b, BB), ep = m.out(p, cap * 8), ec_ = m.out(count, 4);
    rc = E(Bitboard_GetSetBits, meta(), e, ep, cap, ec_);
  }
  uint32_t n = ld_u32(I->mem, count);
  charge(I, CH + (rc == 0 ? (n < cap ? n : cap) : 0));
  return rc;
}
#define BB1(name) uint32_t ENV(bc_Bitboard_##name)(w2c_inst *I, uint32_t a, uint32_t out) { \
  BBCHK(a); BBCHK(out); charge(I, CH); Mx m(I); uint32_t ea = m.in(a, BB); return E(Bitboard_##name, meta(), ea, m.out(out, BB)); }
BB1(Not)
#define BB2(name) uint32_t ENV(bc_Bitboard_##name)(w2c_inst *I, uint32_t a, uint32_t b, uint32_t out) { \
  BBCHK(a); BBCHK(b); BBCHK(out); charge(I, CH); Mx m(I); uint32_t ea = m.in(a, BB), eb = m.in(b, BB); return E(Bitboard_##name, meta(), ea, eb, m.out(out, BB)); }
BB2(Union) BB2(Intersect) BB2(Xor)
uint32_t ENV(bc_Bitboard_IsEqual)(w2c_inst *I, uint32_t a, uint32_t b, uint32_t out) { TI();
  BBCHK(a); BBCHK(b); if (!okg(I, out, 4, 4)) return NEG1; charge(I, CH);
  Mx m(I); uint32_t ea = m.in(a, BB), eb = m.in(b, BB); return E(Bitboard_IsEqual, meta(), ea, eb, m.out(out, 4));
}
#define BBSH(name) uint32_t ENV(bc_Bitboard_##name)(w2c_inst *I, uint32_t s, uint32_t out, uint32_t n) { \
  BBCHK(s); BBCHK(out); charge(I, CH); Mx m(I); uint32_t es = m.in(s, BB); return E(Bitboard_##name, meta(), es, m.out(out, BB), n); }
BBSH(ShiftRight) BBSH(ShiftUp)
uint32_t ENV(bc_Bitboard_ImportRawBuffer)(w2c_inst *I, uint32_t b, uint32_t bytes, uint32_t size) { TI();
  if ((int32_t)size < 0) return NEG1;
  BBCHK(b); if (!okg(I, bytes, size, 1)) return NEG1; charge(I, CH);
  Mx m(I); uint32_t eb = m.out(b, BB), ey = m.in(bytes, size); return E(Bitboard_ImportRawBuffer, meta(), eb, ey, size);
}
static int64_t span(int32_t c, int32_t r, int32_t N) {
  int32_t lo = c - r < 0 ? 0 : (c - r < N - 1 ? c - r : N - 1), hi = c + r < 0 ? 0 : (c + r < N - 1 ? c + r : N - 1);
  return (hi >> 3) - (lo >> 3) + 1;
}
uint32_t ENV(bc_Bitboard_DrawChebyshev)(w2c_inst *I, uint32_t b, uint32_t x, uint32_t y, float rad) { TI();
  BBCHK(b);
  int32_t W = (int32_t)META[0], H = (int32_t)META[1], r;
  if (std::isnan(rad) || std::isinf(rad)) r = W + H;
  else { float c = std::ceil(rad > 0 ? rad : 0); r = c > (float)(W + H) ? W + H : (int32_t)c; }
  charge(I, span((int32_t)x, r, W) * span((int32_t)y, r, H));
  Mx m(I); return E(Bitboard_DrawChebyshev, meta(), m.out(b, BB), x, y, rad);
}
// spec: walls/out checked; d > 0xffff -> 18; fuel (count + 2) * n_x * n_y + CH (chunk spans of [x-d, x+d] x [y-d, y+d] clamped as in
// DrawChebyshev, r = d), count = the engine's expansion count, charged after the call whatever its rc (4 Nov, b1167: was missing)
uint32_t ENV(bc_Bitboard_ReachableMask)(w2c_inst *I, uint32_t walls, uint32_t x, uint32_t y, uint32_t out, uint32_t d) { TI();
  BBCHK(walls); BBCHK(out);
  if (d > 0xffff) return 18;
  st_u32(EI.mem, SC + SC_T2, 0);
  uint32_t rc;
  { Mx m(I); uint32_t ew = m.in(walls, BB), eo = m.out(out, BB);
    rc = E(Bitboard_ReachableMaskWithExpansionCount, meta(), ew, x, y, eo, d, SC + SC_T2); }
  int64_t cnt = ld_u16(EI.mem, SC + SC_T2);
  charge(I, (cnt + 2) * span((int32_t)x, (int32_t)d, (int32_t)META[0]) * span((int32_t)y, (int32_t)d, (int32_t)META[1]) + CH);
  return rc;
}
// 6 Nov (Builder: b1354 SPV LOS needs it): shadow_cast. The CLI charges 2 x CH (chunk count) + scan/2 per call, whatever the radius or rc, scan = the
// engine's own count (Bitboard_ShadowCastWithScanCount); fitted on nova_ft_sccal (one call a turn) and checked by cxeverify on nova_ft_scprobe.
// CXE_TRACE_SC=1: one stderr line per call (round team champ x y d scan W H rc charge).
uint32_t ENV(bc_Bitboard_ShadowCast)(w2c_inst *I, uint32_t walls, uint32_t x, uint32_t y, uint32_t out, uint32_t d) { TI();
  BBCHK(walls); BBCHK(out);
  if (d > 0xffff) return 18;
  st_u32(EI.mem, SC + SC_T2, 0);
  uint32_t rc;
  { Mx m(I); uint32_t ew = m.in(walls, BB), eo = m.out(out, BB);
    rc = E(Bitboard_ShadowCastWithScanCount, meta(), ew, x, y, eo, d, SC + SC_T2); }
  int64_t cnt = ld_u16(EI.mem, SC + SC_T2);
  int64_t ch = 2 * (int64_t)CH + cnt / 2;  // the CLI's charge, measured: 2 x the board's chunk count + scan/2, whatever the radius or rc
  static const bool tr = getenv("CXE_TRACE_SC") != nullptr;
  if (tr) fprintf(stderr, "SC\t%d\t%d\t%d\t%u\t%u\t%u\t%lld\t%u\t%u\t%u\t%lld\n", g_round, B(I)->team, B(I)->champ, x, y, d, (long long)cnt,
                  META[0], META[1], rc, (long long)ch);
  charge(I, ch);
  return rc;
}
// ---- distance fields
#define FBCHK(p) if (!okg(I, p, FB, 2)) return NEG1
uint32_t ENV(bc_DistanceField_Get)(w2c_inst *I, uint32_t f, uint32_t x, uint32_t y, uint32_t out) { TI();
  FBCHK(f); if (!okg(I, out, 2, 2)) return NEG1; Mx m(I); uint32_t ef = m.in(f, FB); return E(DistanceField_Get, meta(), ef, x, y, m.out(out, 2));
}
uint32_t ENV(bc_DistanceField_Set)(w2c_inst *I, uint32_t f, uint32_t x, uint32_t y, uint32_t v) { TI();
  FBCHK(f); if (v > 0xffff) return 18; Mx m(I); return E(DistanceField_Set, meta(), m.out(f, FB), x, y, v);
}
uint32_t ENV(bc_DistanceField_ExportLinearBuffer)(w2c_inst *I, uint32_t f, uint32_t bytes, uint32_t size) { TI();
  if ((int32_t)size < 0) return NEG1;
  FBCHK(f); if (!okg(I, bytes, size, 1)) return NEG1; charge(I, c8(size));
  Mx m(I); uint32_t ef = m.in(f, FB); return E(DistanceField_ExportLinearBuffer, meta(), ef, m.out(bytes, size), size);
}
static uint32_t df_charge(w2c_inst *I, uint32_t rc, uint32_t count) {
  int64_t u = (int64_t)((rc == 0 ? ld_u16(I->mem, count) : 0) + 16) * CH;
  charge(I, u < 40000 ? u : 40000);
  return rc;
}
uint32_t ENV(bc_DistanceField_ComputeWithExpansionCount)(w2c_inst *I, uint32_t walls, uint32_t roots, uint32_t vis, uint32_t dist, uint32_t maxd, uint32_t count) { TI();
  BBCHK(walls); BBCHK(roots); BBCHK(vis); FBCHK(dist);
  if (maxd > 0xffff) return 18;
  if (!okg(I, count, 2, 2)) return NEG1;
  uint32_t rc;
  {
    Mx m(I); uint32_t ew = m.in(walls, BB), er = m.in(roots, BB), ev = m.out(vis, BB), ed = m.out(dist, FB), ecn = m.out(count, 2);
    rc = E(DistanceField_ComputeWithExpansionCount, meta(), ew, er, ev, ed, maxd, ecn);
  }
  return df_charge(I, rc, count);
}
uint32_t ENV(bc_DistanceField_ComputeToWithExpansionCount)(w2c_inst *I, uint32_t walls, uint32_t roots, uint32_t dests, uint32_t vis, uint32_t dist, uint32_t maxd, uint32_t count) { TI();
  BBCHK(walls); BBCHK(roots); BBCHK(dests); BBCHK(vis); FBCHK(dist);
  if (maxd > 0xffff) return 18;
  if (!okg(I, count, 2, 2)) return NEG1;
  uint32_t rc;
  {
    Mx m(I); uint32_t ew = m.in(walls, BB), er = m.in(roots, BB), es = m.in(dests, BB), ev = m.out(vis, BB), ed = m.out(dist, FB), ecn = m.out(count, 2);
    rc = E(DistanceField_ComputeToWithExpansionCount, meta(), ew, er, es, ev, ed, maxd, ecn);
  }
  return df_charge(I, rc, count);
}
// ---- board queries
#define BOARDQ(imp, eng) uint32_t ENV(imp)(w2c_inst *I, uint32_t out) { TI(); BBCHK(out); charge(I, CH); Mx m(I); return E(eng, G, ident(I), m.out(out, BB)); }
BOARDQ(board_camp_occupancy, Game_API_GetCampOccupancy)
BOARDQ(board_awake_camp_occupancy, Game_API_GetAwakeCampOccupancy)
BOARDQ(board_ally_occupancy, Game_API_GetAllyOccupancy)
BOARDQ(board_enemy_occupancy, Game_API_GetEnemyOccupancy)
BOARDQ(board_enemy_ward_occupancy, Game_API_GetEnemyWardOccupancy)
BOARDQ(board_ally_ward_occupancy, Game_API_GetAllyWardOccupancy)
BOARDQ(board_vision, Game_API_GetVision)
// 5 Nov (Builder, Rule checker Q39): the crystal teleport API: a reserved landing tile is visible 2 turns ahead to any body that sees it
BOARDQ(board_teleport_occupancy, Game_API_GetTeleportOccupancy)
uint32_t ENV(board_ward_vision_mask)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI();
  BBCHK(out); charge(I, 2 * CH); Mx m(I); return E(Game_API_GetWardVisionMask, G, ident(I), x, y, m.out(out, BB));
}
// 10 Nov (Builder, b1776 PFX: the SDK's hypothetical champion vision had no import here, so a bot using it could not run on cxe):
// board_vision_mask(design, x, y, out) = the engine's own Game_API_GetVisionMask (as bc_champion_vision uses for other bodies).
// Charge: probe28 v the CLI decides (2 x CH like the ward mask until measured).
uint32_t ENV(board_vision_mask)(w2c_inst *I, uint32_t kind, uint32_t x, uint32_t y, uint32_t out) { TI();
  BBCHK(out); charge(I, 2 * CH); Mx m(I); return E(Game_API_GetVisionMask, G, ident(I), kind, x, y, m.out(out, BB));
}
uint32_t ENV(bc_champion_vision)(w2c_inst *I, uint32_t champ, uint32_t out) { TI();
  BBCHK(out); charge(I, CH);
  Mx m(I);
  uint32_t eo = m.out(out, BB);
  if ((int32_t)champ == B(I)->champ) return E(Game_API_GetVision, G, ident(I), eo);
  uint32_t rc = E(Game_API_Champion_Get, G, ident(I), champ, SC + SC_T2);
  if (rc) return rc;
  int32_t type = (int32_t)erd(SC + SC_T2 + 4), x = (int32_t)erd(SC + SC_T2 + 8), y = (int32_t)erd(SC + SC_T2 + 12);
  if (x >= 0 && y >= 0) { charge(I, CH); return E(Game_API_GetVisionMask, G, ident(I), (uint32_t)type, (uint32_t)x, (uint32_t)y, eo); }
  return E(Bitboard_Zero, meta(), eo);
}
uint32_t ENV(bc_map_mask)(w2c_inst *I, uint32_t kind, uint32_t out) { TI();
  BBCHK(out); charge(I, CH);
  Mx m(I); uint32_t eo = m.out(out, BB);
  switch (kind) {
    case 0: return E(Game_API_Map_GetWallBitboard, G, ident(I), eo);
    case 1: return E(Game_API_Map_GetBushBitboard, G, ident(I), eo);
    case 2: return E(Game_API_Map_GetHoleBitboard, G, ident(I), eo);
    case 3: return E(Game_API_Map_GetAltarBitboard, G, ident(I), eo);
  }
  return 18;
}
// ---- memory
uint32_t ENV(shared_memory_size)(w2c_inst *I, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_GetSharedMemorySize, G, o)); }
uint32_t ENV(read_shared_memory)(w2c_inst *I, uint32_t off, uint32_t dst, uint32_t len) { TI();
  if ((int32_t)len < 0) return NEG1;
  if (len && !okm(I, dst, len, 1)) return NEG1;
  charge(I, c8(len));
  Mx m(I); return E(Game_API_ReadSharedMemory, G, (uint32_t)B(I)->team, off, len ? m.out(dst, len) : 0u, len);
}
uint32_t ENV(write_shared_memory)(w2c_inst *I, uint32_t off, uint32_t src, uint32_t len) { TI();
  if ((int32_t)len < 0) return NEG1;
  if (len && !okm(I, src, len, 1)) return NEG1;
  charge(I, c8(len));
  Mx m(I); return E(Game_API_WriteSharedMemory, G, (uint32_t)B(I)->team, off, len ? m.in(src, len) : 0u, len);
}
uint32_t ENV(read_draft_memory)(w2c_inst *I, uint32_t off, uint32_t dst, uint32_t len) { TI();
  if ((int32_t)len < 0) return NEG1;
  if (len && !okm(I, dst, len, 1)) return NEG1;
  charge(I, c8(len));
  Mx m(I); return E(Game_API_ReadDraftMemory, G, (uint32_t)B(I)->team, off, len ? m.out(dst, len) : 0u, len);
}
uint32_t ENV(bc_submit_draft_memory)(w2c_inst *I, uint32_t src, uint32_t len) { TI();
  if (E(Game_API_Draft_GetCurrentTeam, G, SC + SC_TMP) || (int32_t)erd(SC + SC_TMP) != B(I)->team) return 18;
  uint32_t rc = E(Game_API_GetDraftMemorySize, G, SC + SC_TMP);
  if (rc) return rc;
  if ((int32_t)len < 0) return NEG1;
  uint32_t sz = erd(SC + SC_TMP), n = len < sz ? len : sz;
  if (n && !okm(I, src, n, 1)) return NEG1;
  charge(I, c8(n));
  Mx m(I); return E(Game_API_WriteDraftMemory, G, (uint32_t)B(I)->team, 0u, n ? m.in(src, n) : 0u, n);
}
// ---- queries
uint32_t ENV(game_settings)(w2c_inst *I, uint32_t out) { TI(); QOUT(120, 8, E(Game_API_GetSettings, o)); }
uint32_t ENV(item_info)(w2c_inst *I, uint32_t item, uint32_t out) { TI(); QOUT(40, 4, E(Game_API_GetItemInfo, item, o)); }
uint32_t ENV(consumable_info)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(8, 4, E(Game_API_GetConsumableInfo, c, o)); }
uint32_t ENV(champion_design)(w2c_inst *I, uint32_t t, uint32_t out) { TI(); QOUT(128, 4, E(Game_API_Champion_Design, G, t, o)); }
uint32_t ENV(camp_design)(w2c_inst *I, uint32_t t, uint32_t out) { TI(); QOUT(124, 4, E(Game_API_Camp_Design, G, t, o)); }
uint32_t ENV(champion)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(44, 4, E(Game_API_Champion_Get, G, ident(I), c, o)); }
// spec: (x, y, out) -> GetChampion(g, &ident, x, y, out), the champion record at a tile (vision::champions(); 4 Nov, b1167: was missing)
uint32_t ENV(champion_at)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI(); QOUT(44, 4, E(Game_API_GetChampion, G, ident(I), x, y, o)); }
// camp_at (x, y, out) -> GetCamp(g, &ident, x, y, out): 32-byte camp like camp(); puppet.py's foe bots use it (b1182/b1184,
// 4 Nov; probe23 v the CLI)
uint32_t ENV(camp_at)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI(); QOUT(32, 4, E(Game_API_GetCamp, G, ident(I), x, y, o)); }
// teleport queries: is_occupied_by_teleport is an engine query with no host charge, as camp_at; teleport_info is 28 bytes
uint32_t ENV(is_occupied_by_teleport)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_IsOccupiedByTeleport, G, ident(I), x, y, o)); }
// teleport_at: the CLI charges the 28-byte record copy, c8(28) = 4 (cxeverify 5 Nov: 2,810 turns 4 fuel short per call without it)
uint32_t ENV(teleport_at)(w2c_inst *I, uint32_t x, uint32_t y, uint32_t out) { TI();
  if (!okm(I, out, 28, 4)) return NEG1;
  uint32_t rc; { Mx m(I); uint32_t o = m.out(out, 28); rc = E(Game_API_GetTeleport, G, ident(I), x, y, o); }
  if (rc == 0) charge(I, c8(28));
  return rc; }
// a camp's static map info {x, y, type} and its group index: the API header's camp position() reads them (probe23)
uint32_t ENV(map_camp_info)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(12, 4, E(Game_API_Map_CampInfo_Get, G, c, o)); }
uint32_t ENV(map_camp_group_of)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Map_CampInfo_GetGroup, G, c, o)); }
uint32_t ENV(champion_identity)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(8, 4, E(Game_API_Champion_GetIdentity, G, ident(I), c, o)); }
uint32_t ENV(champion_is_alive)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_IsAlive, G, c, o)); }
uint32_t ENV(bc_champion_channel_time)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetChannelTime, G, ident(I), c, o)); }
uint32_t ENV(camp_state)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Camp_GetState, G, ident(I), c, o)); }
uint32_t ENV(camp)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(32, 4, E(Game_API_Camp_Get, G, ident(I), c, o)); }
uint32_t ENV(camp_group_state)(w2c_inst *I, uint32_t g, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_CampGroup_GetState, G, ident(I), g, o)); }
uint32_t ENV(camp_group_cooldown)(w2c_inst *I, uint32_t g, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_CampGroup_GetCooldown, G, ident(I), g, o)); }
uint32_t ENV(camp_group_capture_state)(w2c_inst *I, uint32_t g, uint32_t out) { TI(); QOUT(8, 4, E(Game_API_CampGroup_GetCaptureState, G, ident(I), g, o)); }
uint32_t ENV(spawn_region)(w2c_inst *I, uint32_t t, uint32_t out) { TI(); QOUT(16, 4, E(Game_API_GetSpawnRegion, G, t, o)); }
uint32_t ENV(num_allies)(w2c_inst *I, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetNumAllies, G, ident(I), o)); }
uint32_t ENV(num_enemies)(w2c_inst *I, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetNumEnemies, G, ident(I), o)); }
uint32_t ENV(champion_items)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(336, 4, E(Game_API_Champion_GetItems, G, ident(I), c, o, 84u)); }
uint32_t ENV(champion_consumables)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(16, 4, E(Game_API_Champion_GetConsumables, G, ident(I), c, o, 4u)); }
uint32_t ENV(champion_wards)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(8, 4, E(Game_API_Champion_GetWards, G, ident(I), c, o)); }
uint32_t ENV(champion_ability_props)(w2c_inst *I, uint32_t c, uint32_t s, uint32_t out) { TI(); QOUT(36, 4, E(Game_API_Champion_GetAbilityProps, G, ident(I), c, s, o)); }
uint32_t ENV(champion_can_shop)(w2c_inst *I, uint32_t c, uint32_t a1, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_CanShop, G, ident(I), c, a1, o)); }
uint32_t ENV(altar_lock)(w2c_inst *I, uint32_t a0, uint32_t a1, uint32_t a2, uint32_t out) { TI(); QOUT(24, 4, E(Game_API_GetAltarLock, G, ident(I), a0, a1, a2, o)); }
uint32_t ENV(bc_champion_priority)(w2c_inst *I, uint32_t c, uint32_t nx, uint32_t out) { TI();
  if (!okg(I, out, 4, 4)) return NEG1; Mx m(I); return E(Game_API_Champion_GetPriority, G, ident(I), c, nx, m.out(out, 4));
}
uint32_t ENV(champion_gold)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetGold, G, ident(I), c, o)); }
uint32_t ENV(champion_gems)(w2c_inst *I, uint32_t c, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetGems, G, ident(I), c, o)); }
uint32_t ENV(champion_cooldown)(w2c_inst *I, uint32_t c, uint32_t s, uint32_t out) { TI(); QOUT(4, 4, E(Game_API_Champion_GetCooldown, G, ident(I), c, s, o)); }
uint32_t ENV(bc_round_number)(w2c_inst *I, uint32_t out) { TI();
  if (!okg(I, out, 4, 4)) return NEG1;
  ewr(SC + SC_TMP, 0); uint32_t rc = E(Game_API_GetRoundNumber, G, SC + SC_TMP); st_u32(I->mem, out, erd(SC + SC_TMP)); return rc;
}
uint32_t ENV(bc_submitted_gems)(w2c_inst *I, uint32_t t, uint32_t out) { TI();
  if (!okg(I, out, 4, 4)) return NEG1;
  ewr(SC + SC_TMP, 0); uint32_t rc = E(Game_API_GetSubmittedGemCount, G, t, SC + SC_TMP); st_u32(I->mem, out, erd(SC + SC_TMP)); return rc;
}
uint32_t ENV(bc_map_symmetry)(w2c_inst *I, uint32_t out) { TI(); if (!okg(I, out, 4, 4)) return NEG1; Mx m(I); return E(Game_API_Map_GetSymmetry, G, m.out(out, 4)); }
static bool overlap(uint32_t a, uint64_t an, uint32_t b, uint64_t bn) { return a < b + bn && b < a + an; }
#define LISTQ(imp, eng, rec) uint32_t ENV(imp)(w2c_inst *I, uint32_t buf, uint32_t cap, uint32_t count) { TI(); \
  if ((int32_t)cap < 0) return NEG1; \
  if (!okm(I, buf, (uint64_t)cap * rec, 4) || !okm(I, count, 4, 4) || (cap && overlap(buf, (uint64_t)cap * rec, count, 4))) return NEG1; \
  uint32_t rc; { Mx m(I); uint32_t eb = cap ? m.out(buf, cap * rec) : 0u, ecn = m.out(count, 4); rc = E(eng, G, ident(I), eb, cap, ecn); } \
  if (rc == 0) { uint32_t n = ld_u32(I->mem, count); charge(I, c8((uint64_t)(n < cap ? n : cap) * rec)); \
    if (g_trace_list) fprintf(stderr, "list %s round %d champ %d cap %u n %u\n", #imp, g_round, B(I)->champ, cap, n); } \
  return rc; }
LISTQ(allies, Game_API_Champion_GetAllies, 4)
LISTQ(enemies, Game_API_Champion_GetEnemies, 4)
LISTQ(wards, Game_API_GetWards, 24)
LISTQ(teleports, Game_API_GetTeleports, 28)
static std::vector<uint32_t> LAYOUT;
static uint32_t LAYOUT_RC;
static void build_layout() {
  LAYOUT.clear();
  uint32_t t = SC + SC_BUF;
  if ((LAYOUT_RC = E(Game_API_Map_GetNumCampGroups, G, t))) return;
  uint32_t n = erd(t), gl = t + 64;
  if ((LAYOUT_RC = E(Game_API_Map_GetCampGroups, G, gl, n, t + 8))) return;
  uint32_t c = erd(t + 8);
  if (c > n) c = n;
  uint32_t cl = gl + 4 * n + 64;
  for (uint32_t i = 0; i < c; i++) {
    uint32_t h = erd(gl + 4 * i);
    if ((LAYOUT_RC = E(Game_API_Map_CampGroup_Get, G, h, t + 16))) return;
    uint32_t gems = erd(t + 16), gold = erd(t + 20);
    if ((LAYOUT_RC = E(Game_API_Map_CampGroup_GetRespawnTime, G, h, t + 24))) return;
    uint32_t r = erd(t + 24);
    if ((LAYOUT_RC = E(Game_API_Map_CampGroup_GetNumCamps, G, h, t + 28))) return;
    uint32_t mm = erd(t + 28);
    if ((LAYOUT_RC = E(Game_API_Map_CampGroup_GetCampInfo, G, h, cl, mm, t + 32))) return;
    uint32_t k = erd(t + 32);
    if (k > mm) k = mm;
    LAYOUT.insert(LAYOUT.end(), {h, gold, gems, r, k});
    for (uint32_t j = 0; j < k; j++) {
      uint32_t ch = erd(cl + 4 * j);
      if ((LAYOUT_RC = E(Game_API_Map_CampInfo_Get, G, ch, t + 40))) return;
      LAYOUT.insert(LAYOUT.end(), {ch, erd(t + 48), erd(t + 40), erd(t + 44)});
    }
  }
}
uint32_t ENV(map_camp_layout)(w2c_inst *I, uint32_t buf, uint32_t cap, uint32_t count) { TI();
  if (LAYOUT_RC) return LAYOUT_RC;
  if ((int32_t)cap < 0) return NEG1;
  if (!okm(I, buf, (uint64_t)cap * 4, 4) || !okm(I, count, 4, 4)) return NEG1;
  uint32_t len = (uint32_t)LAYOUT.size(), n = len < cap ? len : cap;
  charge(I, (n + 1) / 2);
  if (cap) memcpy(I->mem + buf, LAYOUT.data(), 4ull * n);
  st_u32(I->mem, count, len);
  return 0;
}
uint32_t ENV(champion_buff_data)(w2c_inst *I, uint32_t c, uint32_t buf, uint32_t cap, uint32_t count) { TI();
  if ((int32_t)cap < 0) return NEG1;
  if (!okm(I, buf, (uint64_t)cap * 12, 4) || !okm(I, count, 4, 4)) return NEG1;
  uint32_t t = SC + SC_BUF;
  uint32_t rc = E(Game_API_Champion_GetBuffData, G, ident(I), c, t, cap < 3 ? cap : 3u, t + 64);
  if (rc) return rc;
  uint32_t n = erd(t + 64);
  if (cap) memcpy(I->mem + buf, em() + t, 12ull * n);
  st_u32(I->mem, count, n);
  return 0;
}
// 6 Nov (Builder: Rule checker batch 3, b1368: camp stun state): camp_buffs, as champion_buff_data (12-byte records type, magnitude,
// timer; charged as a copy of the records, c8(12 n)), from Game_API_Camp_GetBuffs; checked against the CLI by cxeverify on a probe bot (nova_ft_cbprobe).
uint32_t ENV(camp_buffs)(w2c_inst *I, uint32_t h, uint32_t buf, uint32_t cap, uint32_t count) { TI();
  if ((int32_t)cap < 0) return NEG1;
  if (!okm(I, buf, (uint64_t)cap * 12, 4) || !okm(I, count, 4, 4)) return NEG1;
  uint32_t t = SC + SC_BUF;
  uint32_t rc = E(Game_API_Camp_GetBuffs, G, ident(I), h, t, cap < 3 ? cap : 3u, t + 64);
  if (rc) return rc;
  uint32_t n = erd(t + 64);
  static const bool tr = getenv("CXE_TRACE_CB") != nullptr;
  if (tr) fprintf(stderr, "CB\t%d\t%d\t%d\t%u\t%u\t%u\n", g_round, B(I)->team, B(I)->champ, h, cap, n);
  if (cap) memcpy(I->mem + buf, em() + t, 12ull * (n < cap ? n : cap));
  if (n) charge(I, c8(12ull * (n < cap ? n : cap)));  // the CLI's copy charge, measured: 0 for no buffs, 2 for one record (n >= 2 never seen in 71k calls: unmeasured)
  st_u32(I->mem, count, n);
  return 0;
}
uint32_t ENV(bc_get_last_error)(w2c_inst *I, uint32_t buf, uint32_t cap) { TI();
  uint32_t p = ((uint32_t(*)(w2c_inst *))EF(GetLastErrorMsg))(&EI);
  uint32_t len = p ? (uint32_t)strlen((const char *)em() + p) : 0;
  if ((int32_t)cap < 0) return NEG1;
  uint32_t n = cap < len ? cap : len;
  if (g_trace_err) fprintf(stderr, "lasterr round %d champ %d cap %u len %u msg %.60s\n", g_round, B(I)->champ, cap, len, p ? (const char *)em() + p : "");
  charge(I, c8(n));
  if (cap) {
    if (!okm(I, buf, cap, 1)) return NEG1;
    memcpy(I->mem + buf, em() + p, n);
  }
  return len;
}
}  // extern "C"

extern "C" void w2c_prof_bulk(w2c_inst *I, int kind, uint32_t d, uint32_t s, uint32_t n) {
  if (g_trace_bulk && g_trace == g_round * 100 + ((Bot *)I->host)->champ + 1)
    fprintf(stderr, "bulk %s d %u s %u n %u fuel %lld\n", kind ? "fill" : "copy", d, s, n, (long long)used_of((Bot *)I->host));
}
// ------------------------------------------------------------------ CXE_SAMPLE=1: time profile by component (SIGPROF, 0.1 ms)
static uintptr_t g_eng_lo, g_eng_hi;  // engine code range (engine_module's functions are in this executable)
static long g_samples[5];             // engine/host exe, bot .so, libc+other, bot-run total
static void on_prof(int, siginfo_t *, void *ctx) {
  uintptr_t ip = (uintptr_t)((ucontext_t *)ctx)->uc_mcontext.gregs[REG_RIP];
  Dl_info di;
  int k = 2;
  if (dladdr((void *)ip, &di) && di.dli_fname) {
    const char *f = di.dli_fname;
    if (strstr(f, "/so/") || strstr(f, ".so") && !strstr(f, "libc") && !strstr(f, "libm") && !strstr(f, "ld-linux") && !strstr(f, "libstdc")) k = 1;
    else if (!strstr(f, "lib")) k = (di.dli_sname && !strncmp(di.dli_sname, "cxe_imp", 7)) ? 3 : 0;
  }
  g_samples[k]++;
}
static void sample_start() {
  struct sigaction sa = {};
  sa.sa_sigaction = on_prof;
  sa.sa_flags = SA_SIGINFO | SA_RESTART;
  sigaction(SIGPROF, &sa, nullptr);
  struct itimerval it = {{0, 100}, {0, 100}};
  setitimer(ITIMER_PROF, &it, nullptr);
}
static void sample_report() {
  long t = g_samples[0] + g_samples[1] + g_samples[2] + g_samples[3];
  if (t) fprintf(stderr, "cxe sample: engine+host exe %.1f%% (of which imports %.1f%%), bots %.1f%%, libs %.1f%% (%ld samples)\n",
                 100.0 * (g_samples[0] + g_samples[3]) / t, 100.0 * g_samples[3] / t, 100.0 * g_samples[1] / t, 100.0 * g_samples[2] / t, t);
}
// ------------------------------------------------------------------ match
static FILE *LOGF[2];
static void bot_log(w2c_inst *I, int fd, const uint8_t *p, uint32_t n) {
  if (I == &EI || fd != 1) return;
  FILE *f = LOGF[((Bot *)I->host)->team];
  if (f) fwrite(p, 1, n, f);
}
static const w2c_module *load_bot(const char *path) {
  void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
  if (!h) { fprintf(stderr, "cxe: %s\n", dlerror()); exit(1); }
  const w2c_module *m = (const w2c_module *)dlsym(h, "bot_module");
  if (!m) { fprintf(stderr, "cxe: %s has no bot_module\n", path); exit(1); }
  return m;
}
static void drop_inst(w2c_inst *I) {
  w2c_mem_free(I);
  free(I->table);
  free(I->exn);
}
static Patch make_patch(const w2c_module *base, const char *alt_path) {
  const w2c_module *alt = load_bot(alt_path);
  if (alt->nfuncs != base->nfuncs || alt->nimports != base->nimports || alt->ntypes != base->ntypes) {
    fprintf(stderr, "cxe: --alt %s is not a data flip of the base (function/import/type counts differ)\n", alt_path);
    exit(2);
  }
  w2c_inst a{}, b{};
  if (base->init(&b) || alt->init(&a)) { fprintf(stderr, "cxe: --alt init failed\n"); exit(1); }
  if (a.pages != b.pages || a.ntable != b.ntable || memcmp(a.G, b.G, sizeof a.G)) {
    fprintf(stderr, "cxe: --alt %s is not a data flip of the base (memory size, table or globals differ)\n", alt_path);
    exit(2);
  }
  Patch p;
  p.name = alt_path;
  uint64_t n = b.pages << 16;
  for (uint64_t k = 0; k < n; k++)
    if (a.mem[k] != b.mem[k]) { p.off.push_back((uint32_t)k); p.base.push_back(b.mem[k]); p.alt.push_back(a.mem[k]); }
  drop_inst(&a);
  drop_inst(&b);
  return p;
}
static std::vector<uint8_t> slurp(const char *p) {
  FILE *f = fopen(p, "rb");
  if (!f) { perror(p); exit(1); }
  std::vector<uint8_t> v;
  uint8_t buf[65536];
  size_t n;
  while ((n = fread(buf, 1, sizeof buf, f)) > 0) v.insert(v.end(), buf, buf + n);
  fclose(f);
  return v;
}

// statistics JSON with the fields tools/lab/ablsum.py and condab.py read from the CLI's --statistics --json
// (engine Game_Statistics_*: summary u32 [1] winner 1/2, [2] rounds started, [4]/[6] submitted gems; champion
// record u32 [0] team, [3] kills, [4] deaths, [5] assists, u64 at [6] earned gold, [8] collected gems, [10]
// submitted gems, [12] spent gold, [14] gold, [15] gems, [192..275] item counts)
static const char *FAM[14] = {"Monster", "Power", "Durability", "Treasure", "Jungle", "Home", "Bruiser", "Tribute", "Capture", "Prospector", "Hunter", "Skirmish", "Greed", "Collectors"};
static const char *STAT[3] = {"Strength", "Focus", "Health"};
static int team_of(uint32_t c) {
  ewr(SC + SC_IDENT, 0); ewr(SC + SC_IDENT + 4, 0);
  if (E(Game_API_Champion_GetIdentity, G, SC + SC_IDENT, c, SC + SC_T2)) return -1;
  return (int)erd(SC + SC_T2);
}
static int type_of(uint32_t c) {  // 9 Nov: the champion's design (champion_identity {team, type}), for the stats' "name" like the platform's
  ewr(SC + SC_IDENT, 0); ewr(SC + SC_IDENT + 4, 0);
  if (E(Game_API_Champion_GetIdentity, G, SC + SC_IDENT, c, SC + SC_T2)) return -1;
  return (int)erd(SC + SC_T2 + 4);
}
static int g_cut_after[2] = {0, 0};  // 13 Nov (PCQ): out-of-fuel stops whose cut-phase word read 1 (after the turn's actions), per team
static int g_draftrand[2] = {0, 0};  // draft turns ended without a pick (see write_stats)
// 11 Nov (spot-check mismatches on many-group maps: a spar's 10M draft turn ran out of fuel before a pick): the CLI's own random pick,
// reproduced from its binary (runner::Game::default_draft, cambc 5.0.0). The RNG state starts as the FNV-1a 64 hash of the map file's
// bytes (the match "seed" in the CLI's statistics) and is shared by both teams for the whole game. Each random pick: a Fisher-Yates
// shuffle of 0..11 from the end (i = 11..1: state += golden; j = splitmix64 mix(state) % (i + 1); swap a[i], a[j]), then the first
// champion in that order that Game_Action_Draft accepts. The CLI picks BEFORE ending the turn and ends it with reason 1 when the bot
// ran out of fuel, else 2 (a yield without a pick, a crash, or a turn after the team's draft is off).
static uint64_t g_draft_rng = 0;
static void cli_default_draft() {
  uint32_t a[12];
  for (uint32_t i = 0; i < 12; i++) a[i] = i;
  for (uint32_t i = 11; i >= 1; i--) {
    g_draft_rng += 0x9e3779b97f4a7c15ULL;
    uint64_t z = g_draft_rng;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    z ^= z >> 31;
    uint32_t j = (uint32_t)(z % (i + 1)), t = a[i];
    a[i] = a[j];
    a[j] = t;
  }
  for (uint32_t k = 0; k < 12; k++) if (!E(Game_Action_Draft, G, a[k])) return;
}
static void write_stats(const char *path, int nfuel[2], int nfault[2]) {
  FILE *f = fopen(path, "w");
  uint32_t o = SC + SC_BUF;
  memset(em() + o, 0, 4096);
  E(Game_Statistics_GetSummary, G, o);
  uint32_t win = erd(o + 4), rounds = erd(o + 8), ga = erd(o + 16), gb = erd(o + 24);
  bool partial = (ga >= 1000 || gb >= 1000) && rounds > 0;
  fprintf(f, "{\"match\":{\"outcome\":\"%s\",\"roundsStarted\":%u,\"roundsCompleted\":%u,\"engine\":\"cxe\"},",
          win == 1 ? "teamA" : win == 2 ? "teamB" : "draw", rounds, partial ? rounds - 1 : rounds);
  fprintf(f, "\"teams\":[{\"team\":\"teamA\",\"submittedGems\":\"%u\"},{\"team\":\"teamB\",\"submittedGems\":\"%u\"}],\"champions\":[", ga, gb);
  for (uint32_t c = 0;; c++) {
    memset(em() + o, 0, 4096);
    if (E(Game_Statistics_GetChampion, G, c, o)) break;
    auto u = [&](int k) { return erd(o + 4 * k); };
    auto u64 = [&](int k) { return (unsigned long long)ld_u64(em(), o + 4 * k); };
    fprintf(f, "%s{\"id\":%u,\"team\":\"%s\",\"name\":\"Unknown champion (%d)\",\"metrics\":{\"kills\":\"%u\",\"deaths\":\"%u\",\"assists\":\"%u\",\"earnedGold\":\"%llu\",\"collectedGems\":\"%llu\",\"submittedGems\":\"%llu\",\"spentGold\":\"%llu\",\"gold\":\"%u\",\"gems\":\"%u\"},\"items\":[",
            c ? "," : "", c, team_of(c) ? "teamB" : "teamA", type_of(c), u(3), u(4), u(5), u64(6), u64(8), u64(10), u64(12), u(14), u(15));
    bool first = true;
    for (int i = 0; i < 84; i++)
      if (uint32_t q = u(192 + i)) {
        fprintf(f, "%s{\"item\":\"%s %s of %s (%d)\",\"quantity\":\"%u\"}", first ? "" : ",", FAM[i / 6], i % 2 ? "Emblem" : "Shard", STAT[(i % 6) / 2], i, q);
        first = false;
      }
    fprintf(f, "]}");
  }
  fprintf(f, "],\"events\":[");
  for (int t = 0; t < 2; t++) {
    const char *tn = t ? "teamB" : "teamA";
    fprintf(f, "%s{\"kind\":\"wardPlacement\",\"owner\":{\"team\":\"%s\"},\"entries\":[", t ? "," : "", tn);
    for (int i = 0; i < g_wards[t]; i++) fprintf(f, "%s{}", i ? "," : "");
    fprintf(f, "]},{\"kind\":\"fuelExhausted\",\"owner\":{\"team\":\"%s\"},\"entries\":[", tn);
    for (int i = 0; i < nfuel[t]; i++) fprintf(f, "%s{}", i ? "," : "");
    fprintf(f, "]}");
    if (g_cut_after[t] > 0) {  // 13 Nov (PCQ): only for a marker bot with an after-action cut, so every other game's statistics stay byte-identical
      fprintf(f, ",{\"kind\":\"fuelExhaustedAfterActions\",\"owner\":{\"team\":\"%s\"},\"entries\":[", tn);
      for (int i = 0; i < g_cut_after[t]; i++) fprintf(f, "%s{}", i ? "," : "");
      fprintf(f, "]}");
    }
  }
  // 10 Nov (dro3 drafted at random on the CLI: its 10M draft turns were cut before a pick): draft turns that ended with no pick, which the
  // CLI fills from its host RNG and cxe with the first legal pick, so cxe and the platform play different lineups from there
  fprintf(f, "],\"diagnostics\":{\"botFaults\":{\"teamA\":%d,\"teamB\":%d},\"draftRandomPicks\":{\"teamA\":%d,\"teamB\":%d}}}\n", nfault[0], nfault[1],
          g_draftrand[0], g_draftrand[1]);
  fclose(f);
}

int cxe_decode(const uint8_t *bytes, size_t n, const char *outPath, const std::string &extra);

// 8 Nov (sfx2, fm_f8f589_16): an out-of-bounds guest access lands in the PROT_NONE reservation (w2c_rt.h) and the host must turn it
// into a trap, as the engine does (one bot fault, the game goes on). There was no handler: the whole game died with SIGSEGV and every
// cxe read dropped exactly the games where a candidate faults. Faults outside the running bot's reservation still crash as before.
static const uint64_t CXE_RESERVE = (8ull << 30) + (1ull << 16);  // = W2C_RESERVE (w2c_rt.c)
static void on_segv(int sig, siginfo_t *si, void *) {
  Bot *b = cur;
  uint8_t *a = (uint8_t *)si->si_addr;
  if (b && b->I.mem && b->I.trap_jb && a >= b->I.mem && a < b->I.mem + CXE_RESERVE) {
    sigset_t m;
    sigemptyset(&m);
    sigaddset(&m, sig);
    sigprocmask(SIG_UNBLOCK, &m, nullptr);  // the handler leaves by longjmp, not by returning
    w2c_trap(&b->I, W2C_TRAP_OOB);
  }
  signal(sig, SIG_DFL);
  raise(sig);
}
static void install_segv() {
  static char alt[1 << 16];
  stack_t ss = {};
  ss.ss_sp = alt;
  ss.ss_size = sizeof alt;
  sigaltstack(&ss, nullptr);
  struct sigaction sa = {};
  sa.sa_sigaction = on_segv;
  sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
  sigemptyset(&sa.sa_mask);
  sigaction(SIGSEGV, &sa, nullptr);
  sigaction(SIGBUS, &sa, nullptr);
}

int main(int argc, char **argv) {
  if (argc >= 4 && !strcmp(argv[1], "--decode")) {  // cxe --decode REPLAY OUT.json: rdec.js's decode, natively (cxedec.cpp)
    std::vector<uint8_t> r = slurp(argv[2]);
    return cxe_decode(r.data(), r.size(), argv[3], "");
  }
  if (argc < 5) { fprintf(stderr, "usage: cxe BOT_A.so BOT_B.so MAP OUT_PREFIX [--fuel N]\n"); return 2; }
  install_segv();
  int64_t quantum = 100000;
  int max_rounds = 1 << 30;
  for (int i = 5; i + 1 < argc; i++)
    if (!strcmp(argv[i], "--rounds")) max_rounds = atoi(argv[i + 1]);
  g_trace_err = getenv("CXE_TRACE_ERR");
  g_trace_imports = getenv("CXE_TRACE_IMPORTS");
  g_chargelog = getenv("CXE_CHARGELOG");
  if (getenv("CXE_OPCLOG")) g_opclog = fopen((std::string(argv[4]) + ".opc.tsv").c_str(), "w");
  FILE *cl = g_chargelog ? fopen((std::string(argv[4]) + ".charges.tsv").c_str(), "w") : nullptr;
  long turn_no[2] = {0, 0};
  for (int i = 5; i < argc; i++) if (!strcmp(argv[i], "--record")) g_rec = true;
  g_probe_on = getenv("CXE_PROBE") != nullptr;
  if (const char *fr = getenv("CXE_FUEL_REC")) {
    if (!(g_fprec = fopen(fr, "w"))) { fprintf(stderr, "cxe: CXE_FUEL_REC %s: cannot write\n", fr); return 2; }
    g_fpon = true;
  }
  if (const char *fp = getenv("CXE_FUEL_PLAY")) {
    FILE *f = fopen(fp, "r");
    if (!f) { fprintf(stderr, "cxe: CXE_FUEL_PLAY %s: cannot read\n", fp); return 2; }
    int ph, rd, tm, ch, st; long calls; size_t n;
    long nt = 0;
    while (fscanf(f, "%d %d %d %d %d %ld %zu", &ph, &rd, &tm, &ch, &st, &calls, &n) == 7) {
      FpTurn t;
      t.stop = st; t.calls = calls; t.v.resize(n);
      for (size_t k = 0; k < n; k++) { unsigned long long v; if (fscanf(f, "%llu", &v) != 1) { fprintf(stderr, "cxe: CXE_FUEL_PLAY: truncated\n"); return 2; } t.v[k] = v; }
      g_fptab[std::make_tuple(ph, rd, tm, ch)].push_back(std::move(t));
      nt++;
    }
    fclose(f);
    if (!nt) { fprintf(stderr, "cxe: CXE_FUEL_PLAY %s: no turns\n", fp); return 2; }
    g_fpplay = g_fpon = true;
  }
  g_trace_bulk = getenv("CXE_TRACE_BULK");
  g_trace_list = getenv("CXE_TRACE_LIST");
  if (const char *t = getenv("CXE_TRACE")) g_trace = atoi(t) * 100 + atoi(strchr(t, ':') + 1) + 1;
  for (int i = 5; i + 1 < argc; i++)
    if (!strcmp(argv[i], "--fuel")) quantum = atoll(argv[i + 1]);
  const w2c_module *mods[2] = {load_bot(argv[1]), load_bot(argv[2])};
  std::string pre = argv[4];
  g_pre = pre;
  // --fork-at R [--fork-k K] [--alt-team A|B] --alt ALT.so [--alt ALT2.so ...]: play to the first turn of round R (0 = before
  // the draft), then for each ALT fork a child (one at a time) whose ALT-team instances get ALT's data bytes; it plays on and
  // writes OUT.altN.* (replay, --record, --statistics PATH.altN, fuel log and stdout from R). With --fork-k every game (the
  // parent too) stops after round R+K-1.
  int fork_at = -1, fork_k = 0, alt_team = 0;
  std::vector<Patch> alts;
  for (int i = 5; i + 1 < argc; i++) {
    if (!strcmp(argv[i], "--fork-at")) fork_at = atoi(argv[i + 1]);
    if (!strcmp(argv[i], "--fork-k")) fork_k = atoi(argv[i + 1]);
    if (!strcmp(argv[i], "--alt-team")) alt_team = argv[i + 1][0] == 'B' || argv[i + 1][0] == 'b' || argv[i + 1][0] == '1';
  }
  for (int i = 5; i + 1 < argc; i++)
    if (!strcmp(argv[i], "--alt")) alts.push_back(make_patch(mods[alt_team], argv[i + 1]));
  if (fork_at >= 0 && alts.empty()) { fprintf(stderr, "cxe: --fork-at needs --alt\n"); return 2; }
  int my_alt = -1;      // >= 0 in a forked child
  bool forked = fork_at < 0;
  std::string fork_note;
  bool sampling = getenv("CXE_SAMPLE");
  if (sampling) sample_start();
  if (engine_module.init(&EI)) return 1;
  ((void (*)(w2c_inst *))engine_module.export_fn("_initialize"))(&EI);
  std::vector<uint8_t> map = slurp(argv[3]);
  SC = E(Engine_Malloc, SC_SIZE);
  uint32_t mp = E(Engine_Malloc, (uint32_t)map.size());
  memcpy(em() + mp, map.data(), map.size());
  if (E(Game_FromMapFileBytes, mp, (uint32_t)map.size(), SC + SC_TMP, 0u)) { fprintf(stderr, "cxe: bad map\n"); return 1; }
  G = ld_u64(em(), SC + SC_TMP);
  g_draft_rng = 0xcbf29ce484222325ULL;  // the CLI's draft RNG seed: FNV-1a 64 of the map file (see cli_default_draft)
  for (uint8_t c : map) g_draft_rng = (g_draft_rng ^ c) * 0x100000001b3ULL;
  if (E(Game_Runner_Init, G)) return 1;
  E(Game_API_Map_GetBitboardMetadata, G, meta());
  for (int i = 0; i < 5; i++) META[i] = erd(meta() + 4 * i);
  E(Bitboard_GetRawBufferSize, meta(), SC + SC_TMP); BB = erd(SC + SC_TMP);
  E(DistanceField_GetRawBufferSize, meta(), SC + SC_TMP); FB = erd(SC + SC_TMP);
  CH = META[2] * META[3];
  memcpy(METAB, META, 20); memcpy(METAB + 20, &BB, 4); memcpy(METAB + 24, &FB, 4);
  build_layout();

  if (getenv("CXE_STDOUT")) {
    LOGF[0] = fopen((pre + ".team-a.stdout").c_str(), "w");
    LOGF[1] = fopen((pre + ".team-b.stdout").c_str(), "w");
    cxe_log_sink = bot_log;
  }
  // per-turn fuel log: diagnostics only (11% of a game's instructions when written every turn): --fuel-log or CXE_FUELLOG
  bool want_log = getenv("CXE_FUELLOG") || g_chargelog || g_opclog;
  for (int i = 5; i < argc; i++) if (!strcmp(argv[i], "--fuel-log")) want_log = true;
  FILE *fl = want_log ? fopen((pre + ".fuel.tsv").c_str(), "w") : nullptr;
  if (getenv("CXE_PAGES_LOG") && !strcmp(getenv("CXE_PAGES_LOG"), "1")) {
    g_pagelog = fopen((pre + ".pages.tsv").c_str(), "w");
    if (g_pagelog) fprintf(g_pagelog, "phase\tround\tteam\tchamp\tpages\tmax_pages\tstop\n");
  }
  if (fl) {
    fprintf(fl, "phase\tround\tteam\tchamp\talive\tbudget\tused\tstop");
    static const char *PN[15] = {"zero", "copyb", "fillb", "copy", "fill", "try", "imp", "ind", "call", "grow", "throw", "loop", "entry", "costed", "pre"};
    for (int k = 0; k < 15; k++) fprintf(fl, "\t%s", PN[k]);
    fprintf(fl, "\n");
  }
  Bot *draft[2] = {nullptr, nullptr};
  std::vector<Bot *> champs;
  std::vector<bool> retrap;  // champions whose instance trapped (their next instance starts at the normal budget)
  int ndraft[2] = {0, 0}, nfault[2] = {0, 0}, nfuel[2] = {0, 0};
  bool draft_off[2] = {false, false};  // GameRules :88: no more draft turns after one without a pick
  bool first_round = true;
  long turns = 0;
  for (;;) {
    int32_t s[4];
    get_state(s);
    int ph = s[0], team = s[1], round = s[2], ch = s[3];
    g_round = round;
    if (!forked && (fork_at == 0 || (ph == 1 && team != 2 && round >= fork_at))) {
      forked = true;
      for (size_t i = 0; i < alts.size() && my_alt < 0; i++) {
        fflush(nullptr);
        pid_t pid = fork();
        if (pid < 0) { perror("cxe: fork"); return 1; }
        if (pid == 0) { my_alt = (int)i; break; }
        int st = 0;
        waitpid(pid, &st, 0);
        if (!WIFEXITED(st) || WEXITSTATUS(st)) fprintf(stderr, "cxe: alt%zu child failed (status %d)\n", i, st);
      }
      if (fork_k > 0) max_rounds = (fork_at > 0 ? fork_at : 1) + fork_k - 1;
      if (my_alt >= 0) {
        const Patch &p = alts[my_alt];
        g_patch = &p;
        g_patch_team = alt_team;
        int nb = 0, changed = 0;
        for (Bot *x : champs) if (x && x->team == alt_team) { changed += apply_patch(&x->I, p); nb++; }
        if (draft[alt_team]) { changed += apply_patch(&draft[alt_team]->I, p); nb++; }
        char nt[256];
        snprintf(nt, sizeof nt, "alt%d %s: %zu bytes patched in %d instance(s) of team %c at round %d (%d not at their initial value) ",
                 my_alt, p.name.c_str(), p.off.size(), nb, "AB"[alt_team], round, changed);
        fork_note = nt;
        pre += ".alt" + std::to_string(my_alt);
        if (fl) {  // the child's own fuel log, from the fork on
          fclose(fl);
          fl = fopen((pre + ".fuel.tsv").c_str(), "w");
          fprintf(fl, "phase\tround\tteam\tchamp\talive\tbudget\tused\tstop\n");
        }
        if (g_pagelog) { fclose(g_pagelog); g_pagelog = fopen((pre + ".pages.tsv").c_str(), "w"); }
        if (g_cphase) { fclose(g_cphase); g_cphase = nullptr; }  // the child's own cut-phase log, from the fork on
        g_pre = pre;
        if (cl) { fclose(cl); cl = nullptr; }
        if (g_opclog) { fclose(g_opclog); g_opclog = nullptr; }
        for (int t = 0; t < 2; t++)
          if (LOGF[t]) { fclose(LOGF[t]); LOGF[t] = fopen((pre + (t ? ".team-b.stdout" : ".team-a.stdout")).c_str(), "w"); }
      }
    }
    if (ph == 2 || (ph == 1 && round > max_rounds)) break;
    if (ph == 1 && team == 2) {
      uint32_t rc = first_round ? E(Game_Runner_BeginRound, G) : E(Game_Runner_Advance, G);
      first_round = false;
      if (rc) { fprintf(stderr, "cxe: advance rc %u\n", rc); break; }
      continue;
    }
    Bot *b;
    int64_t budget;
    if (ph == 0 && draft_off[team]) {
      // GameRules :88: a draft bot that yields, exhausts its fuel or crashes without making a pick gets no more draft turns: the game
      // picks the rest at random (the CLI logs such a turn as 0 fuel and never resumes the instance). 7 Nov, probe27: cxe resumed it, so
      // a cut draft turn's late draft-memory writes and picks counted here and not in the CLI. The random pick: cli_default_draft (11 Nov),
      // made before the turn ends, which ends with reason 2 as in the CLI.
      ndraft[team]++;
      if (fl) fprintf(fl, "%d\t%d\t%d\t%d\t%d\t%lld\t%lld\t%d\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n", ph, round, team, -1, -1, (long long)quantum, 0LL, (int)ST_YIELD);  // (no 'pre' column on a yield row: readers treat a missing pre as the whole turn)
      if (g_rec) {
        char tb[96];
        int tn = snprintf(tb, sizeof tb, "%s[%d,%d,%d,%d,%lld,%lld,%d]", g_turnrec.empty() ? "" : ",", ph, round, team, -1, (long long)quantum, 0LL, (int)ST_YIELD - 1);
        g_turnrec.append(tb, tn);
      }
      turn_no[team]++;
      cli_default_draft();
      uint32_t rc = E(Game_Runner_EndTurn, G, 2u);
      if (rc == 135) {
        for (uint32_t p = 0; p < 12 && E(Game_Action_Draft, G, p); p++) {}
        rc = E(Game_Runner_EndTurn, G, 0u);
      }
      if (rc && rc != 18) { fprintf(stderr, "cxe: end turn rc %u at round %d\n", rc, round); break; }
      turns++;
      continue;
    }
    if (ph == 0) {
      if (!draft[team]) draft[team] = new_bot(mods[team], team, -1);
      b = draft[team];
      budget = ndraft[team]++ ? quantum : 100 * quantum;
    } else {
      if ((int)champs.size() <= ch) champs.resize(ch + 1, nullptr);
      if (!champs[ch]) {
        champs[ch] = new_bot(mods[team], team, ch);
        budget = (int)retrap.size() > ch && retrap[ch] ? quantum : 2 * quantum;  // after a trap: the normal budget
        if ((int)retrap.size() > ch) retrap[ch] = false;
      } else budget = quantum;
      b = champs[ch];
      if (ph == 1 && ndraft[0] + ndraft[1] && (draft[0] || draft[1])) {
        for (int t = 0; t < 2; t++) if (draft[t]) { free_bot(draft[t]); draft[t] = nullptr; }
      }
    }
    uint64_t p0[16];
    memcpy(p0, b->I.prof, sizeof p0);
    if (g_opclog) memcpy(b->opc0, b->I.opc, sizeof b->opc0);
    g_turn_charges.clear();
    if (g_fpon) fp_begin(ph, round, team, ch);
    Stop why = run_turn(b, budget, quantum);
    if (g_fpon) fp_end((int)why);
    int64_t used = used_of(b);
    int64_t logged = used < budget ? used : budget;  // a cut turn logs its budget; the overshoot is in the next turn (carried)
    if (why == ST_FUEL && b->phase_addr >= 0) {  // 12 Nov: the cut-phase word at the cut (0 = before the turn's actions were done, 1 = after)
      if (!g_cphase) {
        g_cphase = fopen((g_pre + ".cphase.tsv").c_str(), "w");
        if (g_cphase) fprintf(g_cphase, "phase\tround\tteam\tchamp\tcut_phase\n");
      }
      uint32_t cp = 0;
      memcpy(&cp, b->I.mem + b->phase_addr, 4);
      if (g_cphase) fprintf(g_cphase, "%d\t%d\t%d\t%d\t%u\n", ph, round, team, ch, cp);
      if (cp == 1) g_cut_after[team]++;
    }
    if (fl) {
      int alive = -1;  // after the bot's turn and before EndTurn (an engine call), so no bot sees its effect on the last error
      if (ph == 1) { E(Game_API_Champion_IsAlive, G, (uint32_t)ch, SC + SC_T2); alive = (int)erd(SC + SC_T2); }
      fprintf(fl, "%d\t%d\t%d\t%d\t%d\t%lld\t%lld\t%d", ph, round, team, ch, alive, (long long)budget, (long long)logged, (int)why);
      for (int k = 0; k < 14; k++) fprintf(fl, "\t%llu", (unsigned long long)(b->I.prof[k] - p0[k]));
      int64_t pre_used = logged;  // 13 Nov: the turn's fuel before its post-action phase (v2 marker bots), else the whole turn
      if (b->phase_addr >= 0 && b->phase_v2) {
        uint32_t w[2] = {0, 0};
        memcpy(w, b->I.mem + b->phase_addr, 8);
        if (w[0] == 1 && (int64_t)w[1] <= logged) pre_used = (int64_t)w[1];
      }
      fprintf(fl, "\t%lld\n", (long long)pre_used);
    }
    if (g_pagelog) fprintf(g_pagelog, "%d\t%d\t%d\t%d\t%llu\t%llu\t%d\n", ph, round, team, ch, (unsigned long long)b->I.pages,
                           (unsigned long long)b->I.max_pages, (int)why);  // CXE_PAGES_LOG=1: memory after each turn (pages only grow: = peak so far)
    if (g_opclog) {  // CXE_OPCLOG=1: per-turn opcode counts of --profile bots -> OUT.opc.tsv
      fprintf(g_opclog, "%d\t%ld", team, turn_no[team]);
      for (int k = 0; k < 512; k++) { fprintf(g_opclog, "\t%llu", (unsigned long long)(b->I.opc[k] - b->opc0[k])); }
      fprintf(g_opclog, "\n");
    }
    if (cl) {
      for (auto &e : g_turn_charges) fprintf(cl, "%d\t%ld\t%s\t%ld\t%lld\n", team, turn_no[team], e.first, e.second.first, e.second.second);
    }
    if (g_rec) {  // [phase, round, team, champ, budget, used (a cut turn: its budget), stop 0 yield 1 fuel 2 trap 3 exit]
      char tb[96];
      int tn = snprintf(tb, sizeof tb, "%s[%d,%d,%d,%d,%lld,%lld,%d]", g_turnrec.empty() ? "" : ",", ph, round, team, ch, (long long)budget, (long long)logged, (int)why - 1);
      g_turnrec.append(tb, tn);
    }
    turn_no[team]++;
    uint32_t reason = why == ST_YIELD ? 0 : why == ST_FUEL ? 1 : 2;
    if (why == ST_FUEL) nfuel[team]++;
    if (why == ST_TRAP || why == ST_EXIT) nfault[team]++;
    if (ph == 0 && !b->picked) {  // GameRules :88 (see above); the CLI's random pick first, then the end with its reason
      draft_off[team] = true;
      g_draftrand[team]++;
      cli_default_draft();
      reason = why == ST_FUEL ? 1 : 2;
    }
    uint32_t rc = E(Game_Runner_EndTurn, G, reason);
    if (rc == 135) {  // still no pick (should not happen after cli_default_draft): the first legal one
      for (uint32_t p = 0; p < 12 && E(Game_Action_Draft, G, p); p++) {}
      rc = E(Game_Runner_EndTurn, G, reason);
    }
    if (rc && rc != 18) { fprintf(stderr, "cxe: end turn rc %u at round %d\n", rc, round); break; }
    turns++;
    if (why == ST_TRAP && ph == 1) {  // 8 Nov (cxeverify, sfx2 fm_f8f589_16): a trapped champion gets a NEW instance on its next turn at the
      free_bot(b);                     // normal one-quantum budget (not a first turn's two). cxe kept it finished, so every later turn counted
      champs[ch] = nullptr;            // another fault (48 v the CLI's 1) and the game diverged
      if ((int)retrap.size() <= ch) retrap.resize(ch + 1, false);
      retrap[ch] = true;
    }
  }
  if (fl) fclose(fl);
  if (g_cphase) fclose(g_cphase);
  if (cl) fclose(cl);
  for (int t = 0; t < 2; t++) if (LOGF[t]) fclose(LOGF[t]);
  E(Game_SaveReplay, G);
  E(Game_FileBuffer, G, SC + SC_TMP, SC + SC_TMP + 8);
  uint32_t rp = erd(SC + SC_TMP), rl = erd(SC + SC_TMP + 8);
  FILE *f = fopen((pre + ".repl26a").c_str(), "wb");
  fwrite(em() + rp, 1, rl, f);
  fclose(f);
  for (int i = 5; i + 1 < argc; i++)
    if (!strcmp(argv[i], "--statistics")) write_stats((std::string(argv[i + 1]) + (my_alt >= 0 ? ".alt" + std::to_string(my_alt) : "")).c_str(), nfuel, nfault);
  for (int i = 5; i < argc; i++)
    if (!strcmp(argv[i], "--record")) {  // OUT.rdec.json: the rdec.js decode of this game (full per-turn and per-step data)
      std::vector<uint8_t> r(em() + rp, em() + rp + rl);
      std::string extra = ",\"cxe\":{\"actionCols\":[\"r\",\"c\",\"action\",\"rc\",\"args...\",\"result (move/cast/consumable/ward)\"],\"actions\":["
          + g_acts + "],\"turnCols\":[\"phase\",\"r\",\"team\",\"c\",\"budget\",\"used\",\"stop\"],\"turns\":[" + g_turnrec + "]}";
      if (cxe_decode(r.data(), r.size(), (pre + ".rdec.json").c_str(), extra)) fprintf(stderr, "cxe: --record decode failed\n");
    }
  if (getenv("CXE_DUMPSTATS")) {
    FILE *df = fopen((pre + ".statsdump").c_str(), "wb");
    uint32_t o = SC + SC_BUF;
    memset(em() + o, 0, 8192);
    uint32_t rc = E(Game_Statistics_GetSummary, G, o);
    fprintf(stderr, "summary rc %u\n", rc);
    fwrite(em() + o, 1, 4096, df);
    for (uint32_t c = 0; c < 12; c++) {
      memset(em() + o, 0, 8192);
      rc = E(Game_Statistics_GetChampion, G, c, o);
      fprintf(stderr, "champ %u rc %u\n", c, rc);
      fwrite(em() + o, 1, 4096, df);
    }
    fclose(df);
  }
  int32_t s[4];
  get_state(s);
  uint32_t g0 = 0, g1 = 0;
  E(Game_API_GetSubmittedGemCount, G, 0u, SC + SC_TMP); g0 = erd(SC + SC_TMP);
  E(Game_API_GetSubmittedGemCount, G, 1u, SC + SC_TMP); g1 = erd(SC + SC_TMP);
  if (sampling) sample_report();
  if (g_fprec) fclose(g_fprec);
  if (g_fpplay) {
    long left = 0;
    for (auto &e : g_fptab) left += (long)e.second.size();
    fprintf(stderr, "cxe: fuel-play: %ld turns replayed, %ld mismatched, %ld without a record, %ld recorded turns unused\n", g_fp_turns, g_fp_bad, g_fp_nokey, left);
  }
  if (g_probe_on) {  // CXE_PROBE: the probe records (estcheck.py)
    if (FILE *f = fopen(getenv("CXE_PROBE"), "w")) { fwrite(g_probe.data(), 1, g_probe.size(), f); fclose(f); }
  }
  if (const char *fp = getenv("CXE_FUELPROF")) {
    for (Bot *b : champs) if (b) fprof_add(b);
    for (int t = 0; t < 2; t++) if (draft[t]) fprof_add(draft[t]);
    FILE *f = fopen(fp, "w");
    for (int t = 0; t < 2; t++) {
      size_t half = g_fprof[t].size() / 2;
      for (size_t i = 0; i < half; i++)
        if (g_fprof[t][i] || g_fprof[t][half + i]) fprintf(f, "%d\t%zu\t%llu\t%llu\n", t, i, (unsigned long long)g_fprof[t][i], (unsigned long long)g_fprof[t][half + i]);
    }
    fclose(f);
  }
  printf("%srounds %d turns %ld gems %u %u fuel_cuts %d %d faults %d %d\n", fork_note.c_str(), s[2], turns, g0, g1, nfuel[0], nfuel[1], nfault[0], nfault[1]);
  return 0;
}
