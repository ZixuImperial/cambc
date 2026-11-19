/* w2c_rt.c - shared runtime for translated modules (see w2c_rt.h): memory reservation, growth, traps,
 * call_indirect checks and exception objects. The host overrides w2c_out_of_fuel (weak default: trap). */
#include "w2c_rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>

#define W2C_RESERVE (8ull << 30) + (1ull << 16)

int w2c_mem_alloc(w2c_inst *I, uint64_t pages, uint64_t max_pages) {
  void *p = mmap(NULL, W2C_RESERVE, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
  if (p == MAP_FAILED) return 1;
  if (pages && mprotect(p, pages << 16, PROT_READ | PROT_WRITE)) return 1;
  I->mem = (uint8_t *)p;
  I->pages = pages;
  I->max_pages = max_pages > 65536 ? 65536 : max_pages;
  return 0;
}

void w2c_mem_free(w2c_inst *I) {
  if (I->mem) munmap(I->mem, W2C_RESERVE);
  I->mem = NULL;
}

uint32_t w2c_mem_grow(w2c_inst *I, uint32_t delta) {
  uint64_t old = I->pages;
  if (delta == 0) return (uint32_t)old;
  if (old + delta > I->max_pages) return 0xffffffffu;
  if (mprotect(I->mem + (old << 16), (uint64_t)delta << 16, PROT_READ | PROT_WRITE)) return 0xffffffffu;
  I->pages = old + delta;
  return (uint32_t)old;
}

/* setjmp/longjmp for try_table frames (w2c_rt.h): buf = rbx rbp r12 r13 r14 r15, caller's rsp, return address */
__asm__(".text\n.globl w2c_sj_set\n.type w2c_sj_set,@function\nw2c_sj_set:\n"
        "movq %rbx, 0(%rdi)\nmovq %rbp, 8(%rdi)\nmovq %r12, 16(%rdi)\nmovq %r13, 24(%rdi)\nmovq %r14, 32(%rdi)\nmovq %r15, 40(%rdi)\n"
        "leaq 8(%rsp), %rdx\nmovq %rdx, 48(%rdi)\nmovq (%rsp), %rdx\nmovq %rdx, 56(%rdi)\nxorl %eax, %eax\nret\n"
        ".globl w2c_sj_jump\n.type w2c_sj_jump,@function\nw2c_sj_jump:\n"
        "movq 0(%rdi), %rbx\nmovq 8(%rdi), %rbp\nmovq 16(%rdi), %r12\nmovq 24(%rdi), %r13\nmovq 32(%rdi), %r14\nmovq 40(%rdi), %r15\n"
        "movq 48(%rdi), %rsp\nmovl $1, %eax\njmpq *56(%rdi)\n");

void w2c_trap(w2c_inst *I, w2c_trap_kind k) {
  I->trap = k;
  if (I->trap_jb) longjmp(*I->trap_jb, 1);
  fprintf(stderr, "w2c: trap %d with no handler\n", (int)k);
  abort();
}

__attribute__((weak)) void w2c_out_of_fuel(w2c_inst *I) { w2c_trap(I, W2C_TRAP_HOST); }

void *w2c_indirect(w2c_inst *I, uint32_t idx, uint32_t type) {
  if (idx >= I->ntable || !I->table[idx].fn) w2c_trap(I, W2C_TRAP_INDIRECT_NULL);
  if (I->table[idx].type != type) w2c_trap(I, W2C_TRAP_INDIRECT_TYPE);
  return I->table[idx].fn;
}

uint32_t w2c_exn_new(w2c_inst *I, uint32_t tag) {
  /* exception objects live until the instance dies; C++ bots throw rarely (bot errors) */
  if (I->nexn == I->capexn) {
    I->capexn = I->capexn ? I->capexn * 2 : 64;
    I->exn = (w2c_exn *)realloc(I->exn, I->capexn * sizeof(w2c_exn));
  }
  I->exn[I->nexn].tag = tag;
  return ++I->nexn;
}
