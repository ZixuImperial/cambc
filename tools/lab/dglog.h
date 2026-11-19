// dglog.h: integer diag records for a `puppet.py --diag` copy (Tool builder 2, 7 Nov). A RELEASE build of a diag copy: cxe keeps each
// team's stdout (CXE_STDOUT=1), so no debug build is needed and the copy stays as close as possible to the release fuel timing.
// Use: copy this file into the diag copy's src/ (never into a tested bot), then where you want a record:
//     #include "dglog.h"
//     DGLOG(880, 890, 1, me_x, me_y, best_score, chosen);   // tag 1, four integers, only in rounds 880..890
// Each record is one line "DG tag round a b c d". Outside its window a DGLOG costs one round query and a compare, so the fuel used
// before the window is near the release build's; inside it, the writes cost a little fuel (puppet --diag prints the first round the
// diag game differs from the real one: read records only up to there). Integers only (no float formatting, CLAUDE.md bot rules).
#pragma once
#include <cstdint>
#include <cstdio>
namespace dglog
{
inline int round_now() noexcept
{
	std::uint32_t r = 0;
	(void)cambc::detail::sdk_bc_round_number(&r);
	return static_cast<int>(r);
}
inline void put(long tag, long rnd, long a, long b, long c, long d) noexcept
{
	char t[128];
	int n = 0;
	auto num = [&](long v) {
		char u[24];
		int k = 0;
		if (v < 0) { t[n++] = '-'; v = -v; }
		do { u[k++] = static_cast<char>('0' + v % 10); v /= 10; } while (v && k < 23);
		while (k) t[n++] = u[--k];
		t[n++] = ' ';
	};
	t[n++] = 'D'; t[n++] = 'G'; t[n++] = ' ';
	num(tag); num(rnd); num(a); num(b); num(c); num(d);
	t[n - 1] = '\n';
	std::fwrite(t, 1, static_cast<std::size_t>(n), stdout);
	std::fflush(stdout);
}
} // namespace dglog
#define DGLOG(lo, hi, tag, a, b, c, d) \
	do { const int dg_r_ = ::dglog::round_now(); \
		if (dg_r_ >= (lo) && dg_r_ <= (hi)) ::dglog::put((tag), dg_r_, static_cast<long>(a), static_cast<long>(b), static_cast<long>(c), static_cast<long>(d)); } while (0)
// DGP(tag, a, b, c, d) (9 Nov, for puppet --diag's fuel replay): one record through the cxe host's env.cxe_probe, which books the round,
// team and champion itself, so the hook makes NO counted host call (DGLOG's round query is one, and in a turn cut for fuel it can move
// the cut). Any turn, no window needed (under the fuel replay a hook's own fuel cost changes nothing). puppet writes the records as
// "DP tag round champion a b c d" (int32 values). Only cxe answers env.cxe_probe: a copy using DGP plays on cxe only, and platlock's
// submit guard refuses it.
extern "C" __attribute__((import_module("env"), import_name("cxe_probe"))) void dglog_cxe_probe(unsigned, unsigned, unsigned, unsigned, unsigned);
#define DGP(tag, a, b, c, d) \
	dglog_cxe_probe(static_cast<unsigned>(tag), static_cast<unsigned>(a), static_cast<unsigned>(b), static_cast<unsigned>(c), static_cast<unsigned>(d))
