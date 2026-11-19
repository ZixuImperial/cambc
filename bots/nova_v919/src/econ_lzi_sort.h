#pragma once
// b2187 LZI1 (RC X616): libc++'s std::sort (wasi-sdk-33, libc++ 22.1 __algorithm/sort.h __introsort) on the group bounds list, run
// lazily. Each outer step works only inside [first, last) (plus the fixed parent pivot at first - 1), sorts the left range before the
// right one and loops on the right: here the right range [i + 1, last) waits on a stack (top = leftmost) until a reader needs an index
// in it, and every leaf is libc++'s own __introsort call with libc++'s arguments. Disjoint ranges commute, so every index a reader
// reaches holds the entry std::sort puts there, ties included, and a drain gives std::sort's array.
#include <algorithm>
#include <cstddef>
#include <utility>
static_assert(_LIBCPP_VERSION == 220100, "LZI1 mirrors libc++ 22.1 __introsort: re-check sort.h before a toolchain change");
struct __attribute__((may_alias)) LziKV
{
	float f;
	int g;
};
static_assert(sizeof(LziKV) == sizeof(std::pair<float, int>), "LziKV layout");
struct LziCmp
{
	bool operator()(const LziKV& a, const LziKV& b) const { return a.f > b.f; }
};
static_assert(!std::__use_branchless_sort<LziCmp, LziKV*>, "LZI1: std::sort uses the classic partition on this type");
struct LziR
{
	int f, l, d;
	bool lm;
};
struct LziS
{
	int n = 0; // pending ranges; r[n - 1] is the leftmost
	LziR r[48];
};
namespace lzi {
using Pol = std::_ClassicAlgPolicy;
using Ref = std::__comp_ref_type<LziCmp&>;
inline void leaf(LziKV* f, LziKV* l, LziCmp& c, int d, bool lm)
{
	std::__introsort<Pol, LziCmp&, LziKV*, false>(f, l, c, static_cast<std::ptrdiff_t>(d), lm);
}
// __introsort's outer loop on [f, l) until its leftmost leaf is final; each right range goes on the stack instead of the loop.
__attribute__((noinline)) inline void run(LziS& s, LziKV* base, LziKV* f, LziKV* l, int d, bool lm)
{
	LziCmp c;
	while (true)
	{
		const std::ptrdiff_t len = l - f;
		if (len < 24 || d == 0) // sizes 0-5, the insertion sorts and the heap fallback: libc++'s own call
		{
			leaf(f, l, c, d, lm);
			return;
		}
		--d;
		const std::ptrdiff_t h = len / 2;
		if (len > 128)
		{
			std::__sort3<Pol, LziCmp&>(f, f + h, l - 1, c);
			std::__sort3<Pol, LziCmp&>(f + 1, f + (h - 1), l - 2, c);
			std::__sort3<Pol, LziCmp&>(f + 2, f + (h + 1), l - 3, c);
			std::__sort3<Pol, LziCmp&>(f + (h - 1), f + h, f + (h + 1), c);
			std::_IterOps<Pol>::iter_swap(f, f + h);
		}
		else
			std::__sort3<Pol, LziCmp&>(f + h, f, l - 1, c);
		if (!lm && !c(*(f - 1), *f))
		{
			f = std::__partition_with_equals_on_left<Pol, LziKV*, Ref>(f, l, Ref(c));
			continue;
		}
		const auto ret = std::__partition_with_equals_on_right<Pol, LziKV*, LziCmp&>(f, l, c);
		LziKV* i = ret.first;
		if (ret.second)
		{
			const bool fs = std::__insertion_sort_incomplete<Pol, LziCmp&>(f, i, c);
			if (std::__insertion_sort_incomplete<Pol, LziCmp&>(i + 1, l, c))
			{
				if (fs)
					return;
				l = i;
				continue;
			}
			if (fs)
			{
				f = ++i;
				continue;
			}
		}
		if (s.n < 48)
			s.r[s.n++] = { static_cast<int>(i + 1 - base), static_cast<int>(l - base), d, false };
		else
			leaf(i + 1, l, c, d, false); // never on a list under 2^23 entries (the stack's depths fall strictly)
		l = i;
	}
}
// every index <= k final
inline void need(LziS& s, LziKV* base, int k)
{
	while (s.n > 0 && s.r[s.n - 1].f <= k)
	{
		const LziR r = s.r[--s.n];
		run(s, base, base + r.f, base + r.l, r.d, r.lm);
	}
}
// the whole list final (std::sort's array)
inline void drain(LziS& s, LziKV* base)
{
	LziCmp c;
	while (s.n > 0)
	{
		const LziR r = s.r[--s.n];
		leaf(base + r.f, base + r.l, c, r.d, r.lm);
	}
}
// the unsorted list as one pending range with std::sort's depth limit
inline void start(LziS& s, int n)
{
	s.n = 0;
	if (n > 1)
		s.r[s.n++] = { 0, n, static_cast<int>(2 * std::__bit_log2(static_cast<std::size_t>(n))), true };
}
// a copy of the list from index k on (st_cand = cand[k, end)): every pending range starts after k
inline void shift(LziS& dst, const LziS& src, int k)
{
	dst.n = src.n;
	for (int j = 0; j < src.n; ++j)
		dst.r[j] = { src.r[j].f - k, src.r[j].l - k, src.r[j].d, src.r[j].lm };
}
} // namespace lzi
