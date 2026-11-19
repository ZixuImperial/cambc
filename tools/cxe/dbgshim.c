/* dbgso.py: the debug build's fuel_pause/resume/adjust imports (diag DG records run outside the bot's fuel; b1137, 4 Nov).
   5 Nov (bug hunter 50, codeaudit #229-236): a paused region runs on an effectively unlimited budget. Before, the counter kept
   running during the pause and was only restored at resume, so a long paused region (nova_check.h's 200-round flush of ~300
   checks) could hit the out-of-fuel cut INSIDE the pause: the check build then lost its turn and resumed stale ones (r%200 = 4-9),
   which the sweep read as A-CB-01/02, A-MV-42 and A-WD-20 violations. I->fuel is consumed - budget (>= 0 = out of fuel). */
#define _GNU_SOURCE /* RTLD_DEFAULT */
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <dlfcn.h>
#include "w2c_rt.h"
static int64_t b1137_saved; static int b1137_depth;
#define PAUSED_FUEL (INT64_MIN / 4)
uint32_t cxe_imp_env__fuel_pause(w2c_inst *I) { if (b1137_depth++ == 0) { b1137_saved = I->fuel; I->fuel = PAUSED_FUEL; } return 0; }
void cxe_imp_env__fuel_resume(w2c_inst *I) { if (b1137_depth > 0 && --b1137_depth == 0) I->fuel = b1137_saved; }
/* fuel_remaining as the bot sees it: while paused, the fuel it had at the pause (a check that measures a cost by reading fuel()
   inside a paused region sees the bot's own fuel, not the paused budget); otherwise the engine's formula (cxe.cpp ENV(fuel_remaining),
   minus its import trace, which check/diag runs do not record). dbgso links with -Bsymbolic-functions so this one binds. */
/* 7 Nov (Builder, b1521): since cxe meters multi-slice turns as the CLI does (7adf1628, T17), a turn's budget is the active slice
   (I->fuel) plus a held-back reserve (draft turn 1: 100 slices, first play turn: 2), and fuel_remaining = reserve + slice. This shim
   kept the old slice-only formula, so a debug bot saw ~100k on its 10M draft turn, skipped its draft analysis and wrote no draft
   fields (MCE's E read 1.00 in every debug cxe game; the CLI's debug games 1.01-1.60). The reserve now comes from the host's own
   fuel_remaining (the executable is linked -rdynamic; dlsym(RTLD_DEFAULT) finds it, not this library's definition). */
typedef uint64_t (*cxe_fr_fn)(w2c_inst *);
uint64_t cxe_imp_env__fuel_remaining(w2c_inst *I);
static uint64_t cxe_reserve(w2c_inst *I)
{
  static cxe_fr_fn host;
  if (!host) host = (cxe_fr_fn)dlsym(RTLD_DEFAULT, "cxe_imp_env__fuel_remaining");
  if (!host || host == cxe_imp_env__fuel_remaining) return 0;
  const uint64_t all = host(I), slice = I->fuel >= 0 ? 0 : (uint64_t)(-I->fuel);
  return all > slice ? all - slice : 0;
}
uint64_t cxe_imp_env__fuel_remaining(w2c_inst *I) { const int64_t f = b1137_depth > 0 ? b1137_saved : I->fuel; return cxe_reserve(I) + (f >= 0 ? 0 : (uint64_t)(-f)); }
void cxe_imp_env__fuel_adjust(w2c_inst *I, uint64_t d) { if (b1137_depth > 0) b1137_saved += (int64_t)d; else I->fuel += (int64_t)d; }

/* ORACLE (5 Nov, Planner pm_value_0515.md O1, test only): a per-team blackboard every body of a game can write and read with no
   bandwidth, encoding or fuel limit: the ceiling of any team channel. One cxe process plays one game, so this file's statics are that
   game's; entries are keyed by (team 0/1, ally slot 0-7), so a mirror (both teams the same .so) still keeps the teams apart.
   Bot side: NOVA_ORACLE_PUT / NOVA_ORACLE_GET in tools/lab/checks/nova_check.h (check/test copies only; tools/lab/platlock.sh refuses
   a submit with bot-declared imports or NOVA_CHECK). Which mates a reader may use (in its sight only, or all) is the reader's choice. */
#define ORA_MAX 1024
/* One store per process, shared by every library in it: cxe dlopens each bot .so RTLD_LOCAL, so plain statics are per library and
   a foe-knowledge reader (one .so) would never see the writer's entries (another .so). The first library allocates the store and
   leaves its address in the process environment; the others find it there (5 Nov: U1/U2's foe reads were all empty before this). */
struct ora_store { uint8_t buf[2][8][ORA_MAX]; uint32_t len[2][8]; int32_t round[2][8]; };
static struct ora_store *ora_get_store(void)
{
  static struct ora_store *st;
  if (st) return st;
  const char *e = getenv("NOVA_ORACLE_STORE");
  if (e) { st = (struct ora_store *)(uintptr_t)strtoull(e, NULL, 16); return st; }
  st = (struct ora_store *)calloc(1, sizeof *st);
  for (int t = 0; t < 2; ++t) for (int k = 0; k < 8; ++k) st->round[t][k] = -1;
  char b[32];
  snprintf(b, sizeof b, "%llx", (unsigned long long)(uintptr_t)st);
  setenv("NOVA_ORACLE_STORE", b, 1);
  return st;
}
static int ora_ok(w2c_inst *I, uint32_t p, uint32_t n) { return (uint64_t)p + n <= I->pages * 65536ull; }
/* write my entry: LEN bytes at guest address P, stamped ROUND */
void cxe_imp_env__nova_oracle_put(w2c_inst *I, uint32_t team, uint32_t slot, uint32_t round, uint32_t p, uint32_t len)
{
  if (team > 1 || slot > 7 || len > ORA_MAX || !ora_ok(I, p, len)) return;
  struct ora_store *o = ora_get_store();
  memcpy(o->buf[team][slot], I->mem + p, len);
  o->len[team][slot] = len;
  o->round[team][slot] = (int32_t)round;
}
/* read a mate's entry into P (at most LEN bytes) -> its stamp round + 1, 0 if it never wrote */
uint32_t cxe_imp_env__nova_oracle_get(w2c_inst *I, uint32_t team, uint32_t slot, uint32_t p, uint32_t len)
{
  struct ora_store *o = ora_get_store();
  if (team > 1 || slot > 7 || o->round[team][slot] < 0 || !ora_ok(I, p, len)) return 0;
  const uint32_t n = len < o->len[team][slot] ? len : o->len[team][slot];
  memcpy(I->mem + p, o->buf[team][slot], n);
  return (uint32_t)(o->round[team][slot] + 1);
}
