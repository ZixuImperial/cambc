// allocator.cc: Replaces global new and delete with size-class free lists (fuel). Why: every container growth, std::vector copy and
// bitboard went through dlmalloc/dlfree (about 125 + 100 wasm ops a pair, 1-3.5% of all turn fuel). Here a small block costs about
// 12 ops to get and 10 to give back. How: blocks of up to NA_SMALL bytes come from 64 KB pages; each page holds one size class, and
// a 64 KB table maps a page to its class (0 = not ours), so delete needs no header and no size. Pages are cut from 1 MB slabs taken
// from malloc and are never returned. Larger or over-aligned blocks go to malloc/aligned_alloc as usual. No code reads pointer
// values, so play is unaffected.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>

namespace
{
constexpr std::size_t NA_PAGE = 65536;
constexpr std::size_t NA_SLAB_PAGES = 16;
constexpr std::size_t NA_SMALL = 8192;
constexpr unsigned NA_NCLS = 64 + 28 + 1; // 16-byte steps to 1024, then 256-byte steps to 8192

unsigned char na_pcls[65536];		 // page index (address >> 16) -> size class, 0 = not ours
void* na_free[NA_NCLS];				 // free list heads
std::uintptr_t na_bump[NA_NCLS];	 // next uncut byte of the class's current page
std::uintptr_t na_end[NA_NCLS];		 // end of that page
std::uintptr_t na_slab = 0, na_slab_end = 0;

inline unsigned nova_size_class(std::size_t n)
{
	if (n <= 1024)
		return n == 0 ? 1u : static_cast<unsigned>((n + 15) >> 4);
	return 64u + static_cast<unsigned>((n - 1024 + 255) >> 8);
}

inline std::size_t na_size(unsigned c) { return c <= 64 ? std::size_t(c) << 4 : 1024 + (std::size_t(c - 64) << 8); }

__attribute__((noinline)) void* nova_refill_class(unsigned c)
{
	const std::size_t sz = na_size(c);
	if (na_bump[c] + sz > na_end[c])
	{
		if (na_slab >= na_slab_end)
		{
			void* raw = std::malloc(NA_SLAB_PAGES * NA_PAGE + NA_PAGE);
			if (!raw)
				return nullptr;
			na_slab = (reinterpret_cast<std::uintptr_t>(raw) + NA_PAGE - 1) & ~(NA_PAGE - 1);
			na_slab_end = na_slab + NA_SLAB_PAGES * NA_PAGE;
		}
		const std::uintptr_t page = na_slab;
		na_slab += NA_PAGE;
		na_pcls[page >> 16] = static_cast<unsigned char>(c);
		na_bump[c] = page;
		na_end[c] = page + NA_PAGE;
	}
	const std::uintptr_t p = na_bump[c];
	na_bump[c] = p + sz;
	return reinterpret_cast<void*>(p);
}

inline void* nova_alloc(std::size_t n)
{
	if (n <= NA_SMALL)
	{
		const unsigned c = nova_size_class(n);
		void* p = na_free[c];
		if (p)
		{
			na_free[c] = *static_cast<void**>(p);
			return p;
		}
		return nova_refill_class(c);
	}
	return std::malloc(n);
}

inline void nova_release(void* p)
{
	if (!p)
		return;
	const unsigned c = na_pcls[reinterpret_cast<std::uintptr_t>(p) >> 16];
	if (c)
	{
		*static_cast<void**>(p) = na_free[c];
		na_free[c] = p;
		return;
	}
	std::free(p);
}

inline void* nova_alloc_aligned(std::size_t n, std::size_t al)
{
	if (al <= 16)
		return nova_alloc(n); // every small block is 16-aligned (class sizes are multiples of 16 in 64 KB pages)
	const std::size_t m = (n + al - 1) & ~(al - 1);
	return std::aligned_alloc(al, m ? m : al);
}

[[noreturn]] void na_oom() { throw std::bad_alloc(); }
} // namespace
void* operator new(std::size_t n)
{
	void* p = nova_alloc(n);
	if (!p)
		na_oom();
	return p;
}
void* operator new[](std::size_t n)
{
	void* p = nova_alloc(n);
	if (!p)
		na_oom();
	return p;
}
void* operator new(std::size_t n, const std::nothrow_t&) noexcept { return nova_alloc(n); }
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept { return nova_alloc(n); }
void* operator new(std::size_t n, std::align_val_t a)
{
	void* p = nova_alloc_aligned(n, static_cast<std::size_t>(a));
	if (!p)
		na_oom();
	return p;
}
void* operator new[](std::size_t n, std::align_val_t a)
{
	void* p = nova_alloc_aligned(n, static_cast<std::size_t>(a));
	if (!p)
		na_oom();
	return p;
}
void* operator new(std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept { return nova_alloc_aligned(n, static_cast<std::size_t>(a)); }
void* operator new[](std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept { return nova_alloc_aligned(n, static_cast<std::size_t>(a)); }

void operator delete(void* p) noexcept { nova_release(p); }
void operator delete[](void* p) noexcept { nova_release(p); }
void operator delete(void* p, std::size_t) noexcept { nova_release(p); }
void operator delete[](void* p, std::size_t) noexcept { nova_release(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { nova_release(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { nova_release(p); }
void operator delete(void* p, std::align_val_t) noexcept { nova_release(p); }
void operator delete[](void* p, std::align_val_t) noexcept { nova_release(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { nova_release(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { nova_release(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept { nova_release(p); }
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept { nova_release(p); }
