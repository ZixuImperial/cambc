/* test_engine.c - translator check: play a scripted game (fixed draft, every champion just ends its turn) on the
 * translated engine and write the replay, to compare byte for byte with the same script run by node on the
 * original engine WebAssembly (tools/cxe/eng_script.js).
 * usage: test_engine MAP ROUNDS OUT.replay */
#include "w2c_rt.h"
#include <stdio.h>
#include <stdlib.h>

extern const w2c_module engine_module;
static w2c_inst E;
#define X(name, ...) ((__VA_ARGS__)engine_module.export_fn(#name))
typedef uint32_t (*fi_t)(w2c_inst *, uint32_t);
typedef uint32_t (*fg_t)(w2c_inst *, uint64_t);
typedef uint32_t (*fgi_t)(w2c_inst *, uint64_t, uint32_t);
typedef uint32_t (*fgii_t)(w2c_inst *, uint64_t, uint32_t, uint32_t);
typedef uint32_t (*fiiii_t)(w2c_inst *, uint32_t, uint32_t, uint32_t, uint32_t);

int main(int argc, char **argv) {
  if (argc < 4) return 2;
  jmp_buf jb;
  E.trap_jb = &jb;
  if (setjmp(jb)) { fprintf(stderr, "engine trap %d\n", E.trap); return 1; }
  if (engine_module.init(&E)) return 1;
  ((void (*)(w2c_inst *))engine_module.export_fn("_initialize"))(&E);
  FILE *f = fopen(argv[1], "rb");
  fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
  uint32_t p = X(Engine_Malloc, fi_t)(&E, (uint32_t)n);
  if (fread(E.mem + p, 1, n, f) != (size_t)n) return 1;
  fclose(f);
  uint32_t out = X(Engine_Malloc, fi_t)(&E, 64);
  if (X(Game_FromMapFileBytes, fiiii_t)(&E, p, (uint32_t)n, out, 0)) return 1;
  uint64_t g = ld_u64(E.mem, out);
  if (X(Game_Runner_Init, fg_t)(&E, g)) return 1;
  fgi_t getstate = X(Game_Runner_GetState, fgi_t), endturn = X(Game_Runner_EndTurn, fgi_t), draft = X(Game_Action_Draft, fgi_t);
  fg_t begin = X(Game_Runner_BeginRound, fg_t), adv = X(Game_Runner_Advance, fg_t);
  int rounds = atoi(argv[2]), k = 0, first = 1, turns = 0;
  static const int picks[] = {0, 6, 11, 1, 2, 3, 4, 5, 7, 8, 9, 10};
  for (;;) {
    getstate(&E, g, out);
    int32_t ph = (int32_t)ld_u32(E.mem, out), team = (int32_t)ld_u32(E.mem, out + 4), round = (int32_t)ld_u32(E.mem, out + 8);
    if (ph == 2 || (ph == 1 && round > rounds)) break;
    if (ph == 0) { while (draft(&E, g, picks[k++ % 12])) {} if (endturn(&E, g, 0)) return 1; continue; }
    if (team == 2) { uint32_t rc = first ? begin(&E, g) : adv(&E, g); first = 0; if (rc) { fprintf(stderr, "round rc %u\n", rc); break; } continue; }
    uint32_t rc = endturn(&E, g, 0); turns++;
    if (rc && rc != 18) { fprintf(stderr, "end rc %u\n", rc); break; }
  }
  if (X(Game_SaveReplay, fg_t)(&E, g)) return 1;
  if (X(Game_FileBuffer, fgii_t)(&E, g, out, out + 8)) return 1;
  uint32_t rp = ld_u32(E.mem, out), rl = ld_u32(E.mem, out + 8);
  f = fopen(argv[3], "wb"); fwrite(E.mem + rp, 1, rl, f); fclose(f);
  printf("turns %d replay %u bytes\n", turns, rl);
  return 0;
}
