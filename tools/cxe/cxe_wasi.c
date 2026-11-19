/* cxe_wasi.c - the WASI imports translated modules use (engine and bots). No filesystem; fd_write to stdout/stderr
 * goes to the instance's log sink (dropped unless the host sets one); random_get is deterministic (the engine only
 * uses it to seed its hash maps at start-up). */
#include "w2c_rt.h"
#include <stdio.h>
#include <stdlib.h>

typedef void (*cxe_log_fn)(w2c_inst *I, int fd, const uint8_t *p, uint32_t n);
cxe_log_fn cxe_log_sink = 0;

#define W(n) cxe_imp_wasi_snapshot_preview1__##n
/* errno values as wasmtime-wasi returns them to the CLI's bots (probe 6, 4 Nov): stdio is not seekable (ESPIPE 70),
 * an fd that was never opened is EBADF (8). The C library's first stdout write takes a different path on the seek
 * answer, which costs the bot 106 fuel: getting these wrong made cxe's fuel differ from the CLI's. */
#define WASI_EBADF 8u
#define WASI_ESPIPE 70u
static int wasi_trace = -1;  /* CXE_TRACE_WASI=1: log every WASI call to stderr */
static int tracing(void) { if (wasi_trace < 0) wasi_trace = getenv("CXE_TRACE_WASI") != 0; return wasi_trace; }
/* stdio as the CLI (wasmtime-wasi) presents it, read with probe 12 on 4 Nov: fds 0..2 open, filetype UNKNOWN (0, so
 * isatty() is 0), flags 0, rights FD_READ (0x2) for stdin and FD_WRITE (0x40) for stdout/stderr; reading stdin is EOF;
 * anything else (and a closed stdio fd) is EBADF. The C library's stdout set-up branches on these answers. */
static int stdio_open(w2c_inst *I, uint32_t fd) { return fd <= 2 && !(I->wasi_closed >> fd & 1); }
uint32_t W(fd_write)(w2c_inst *I, uint32_t fd, uint32_t iovs, uint32_t n, uint32_t nw) {
  if (tracing()) {
    fprintf(stderr, "wasi fd_write fd %u n %u lens", fd, n);
    for (uint32_t i = 0; i < n; i++) fprintf(stderr, " %u", ld_u32(I->mem, (uint64_t)iovs + i * 8 + 4));
    fprintf(stderr, " fuel %lld\n", (long long)I->fuel);
  }
  if ((fd != 1 && fd != 2) || !stdio_open(I, fd)) return WASI_EBADF;
  /* wasmtime-wasi writes only the FIRST non-empty iovec and reports that count (probe 8: [4,6] -> 4, [0,6,2] -> 6);
   * the C library then loops for the rest. Writing all of them changed the bot's fuel (106 on its first printf). */
  uint32_t t = 0;
  for (uint32_t i = 0; i < n; i++) {
    uint32_t p = ld_u32(I->mem, (uint64_t)iovs + i * 8), l = ld_u32(I->mem, (uint64_t)iovs + i * 8 + 4);
    if (!l) continue;
    if (cxe_log_sink) cxe_log_sink(I, (int)fd, I->mem + p, l);
    t = l;
    break;
  }
  st_u32(I->mem, nw, t);
  return 0;
}
uint32_t W(fd_read)(w2c_inst *I, uint32_t fd, uint32_t iovs, uint32_t n, uint32_t nr) {
  (void)iovs; (void)n;
  if (fd != 0 || !stdio_open(I, fd)) return WASI_EBADF;
  st_u32(I->mem, nr, 0);  /* stdin: end of file */
  return 0;
}
uint32_t W(fd_close)(w2c_inst *I, uint32_t fd) {
  if (tracing()) fprintf(stderr, "wasi fd_close fd %u\n", fd);
  if (!stdio_open(I, fd)) return WASI_EBADF;
  I->wasi_closed |= 1u << fd;
  return 0;
}
uint32_t W(fd_seek)(w2c_inst *I, uint32_t fd, uint64_t off, uint32_t wh, uint32_t out) {
  (void)I; (void)out;
  if (tracing()) fprintf(stderr, "wasi fd_seek fd %u off %lld whence %u\n", fd, (long long)off, wh);
  return stdio_open(I, fd) ? WASI_ESPIPE : WASI_EBADF;
}
uint32_t W(fd_fdstat_get)(w2c_inst *I, uint32_t fd, uint32_t out) {
  if (!stdio_open(I, fd)) return WASI_EBADF;
  uint64_t rights = fd == 0 ? 0x2 : 0x40;
  I->mem[out] = 0;           /* fs_filetype UNKNOWN */
  st_u16(I->mem, out + 2, 0); /* fs_flags */
  st_u64(I->mem, out + 8, rights);
  st_u64(I->mem, out + 16, rights);
  return 0;
}
uint32_t W(fd_prestat_get)(w2c_inst *I, uint32_t fd, uint32_t out) { (void)I; (void)fd; (void)out; return 8; }
uint32_t W(fd_prestat_dir_name)(w2c_inst *I, uint32_t fd, uint32_t p, uint32_t l) { (void)I; (void)fd; (void)p; (void)l; return 8; }
uint32_t W(environ_get)(w2c_inst *I, uint32_t a, uint32_t b) { (void)I; (void)a; (void)b; return 0; }
uint32_t W(environ_sizes_get)(w2c_inst *I, uint32_t a, uint32_t b) { st_u32(I->mem, a, 0); st_u32(I->mem, b, 0); return 0; }
uint32_t W(random_get)(w2c_inst *I, uint32_t p, uint32_t n) { memset(I->mem + p, 7, n); return 0; }
void W(proc_exit)(w2c_inst *I, uint32_t code) { (void)code; w2c_trap(I, W2C_TRAP_HOST); }
