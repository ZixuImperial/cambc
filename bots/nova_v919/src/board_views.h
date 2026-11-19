#pragma once
// board_views.h: Fast views of engine buffers: grids, bitboards and distance fields.
#include "common_flags.h"
namespace nova {
// Map geometry and the engine's chunked buffer layout (8x8 tiles per chunk).
struct Grid
{
	int w = 0, h = 0, cw = 0, ch = 0, stride = 0;
};
extern Grid G;
// The engine's bitboard and field layout is fixed, so it is read directly, without a per-read branch.
#define NOVA_GDIRECT true
// A bitboard row's byte offset, (y & ~7) * G.stride + (y & 7), for bbget and bview: one load. Filled by init_grid; rows start at
// -G_ROW_PAD.
inline constexpr int G_ROW_PAD = 64;
inline int G_ROW[320];

// Read the layout (sizes, chunk stride) and fill G_ROW. Safe to call more than once.
void init_grid();

// The same test as two unsigned compares (G.w, G.h >= 0, so x < 0 wraps to >= G.w); no short-circuit branches.
NOVA_INLINE bool inb(vec2 p) { return (static_cast<unsigned>(p.x) < static_cast<unsigned>(G.w)) & (static_cast<unsigned>(p.y) < static_cast<unsigned>(G.h)); }

// Cached raw views of engine buffers: one pointer fetch, then a few integer ops per read.
struct FView
{
	const std::uint16_t* p = nullptr;
	const distance_field* f = nullptr;
	int cw = 0;
	NOVA_INLINE std::uint16_t operator()(vec2 q) const
	{
		// No null test per read: fview() always sets p (a live field's buffer is never null; it is the SDK's zero table at worst).
		return p[((q.y >> 3) * cw + (q.x >> 3)) * 64 + ((q.y & 7) << 3) + (q.x & 7)];
	}
};
namespace fxdr
{
int launch_slot_of_group(int gi);
void launch_field_keep(int gi, distance_field&& f);
const distance_field* launch_field(int gi);
void launch_fields_free();
} // namespace fxdr
NOVA_INLINE FView fview(const distance_field& f)
{
	FView v;
	v.f = &f;
	v.cw = G.cw;
	if (NOVA_GDIRECT)
		v.p = f.ptr();
	return v;
}

struct BView
{
	const std::uint64_t* w = nullptr;
	const bitboard* b = nullptr;
	int stride = 0;
	NOVA_INLINE bool operator()(vec2 q) const
	{
		// No null test per read: bview() always sets w (a live bitboard's buffer is never null).
#ifdef __wasm__
		return (reinterpret_cast<const std::uint8_t*>(w)[G_ROW[q.y + G_ROW_PAD] + (q.x & ~7)] >> (q.x & 7)) & 1u; // As bbget.
#else
		return b->is_set(q);
#endif
	}
};
NOVA_INLINE BView bview(const bitboard& b)
{
	BView v;
	v.b = &b;
	v.stride = G.stride;
	if (NOVA_GDIRECT)
		v.w = b.ptr();
	return v;
}

NOVA_INLINE bool bbget(const bitboard& b, vec2 p)
{
	if (NOVA_GDIRECT)
	{
#ifdef __wasm__
		// Bit (y & 7) * 8 + (x & 7) of a little-endian word is bit x & 7 of its byte y & 7: an i32 byte read, no i64 shift or wrap.
		return (reinterpret_cast<const std::uint8_t*>(b.ptr())[G_ROW[p.y + G_ROW_PAD] + (p.x & ~7)] >> (p.x & 7)) & 1u;
#else
#endif
	}
	return b.is_set(p);
}

NOVA_INLINE void bbset(bitboard& b, vec2 p, bool v = true)
{
	if (NOVA_GDIRECT)
	{
		std::uint64_t* w = b.ptr();
		const std::uint64_t bit = std::uint64_t{ 1 } << (((p.y & 7) << 3) | (p.x & 7));
		auto& word = w[(p.y >> 3) * G.stride + (p.x >> 3)];
		word = v ? (word | bit) : (word & ~bit);
		return;
	}
	b.set(p, v);
}

NOVA_INLINE std::uint16_t dfget(const distance_field& f, vec2 p)
{
	return fview(f)(p);
}
// W.me.pos's field offset, recomputed only when the position differs from the one it was computed for, so it cannot go stale
// (dfget_me, world.h). init_grid resets the key when G.cw is set; the key is no tile.
inline std::int64_t me_off_key = INT64_MIN;
inline int me_off_v = 0;

// Call fn(vec2) for every set tile, reading the buffer directly (much cheaper than positions()).
template <class Fn> void bbforeach(const bitboard& b, Fn&& fn)
{
	if (!NOVA_GDIRECT)
	{
		for (vec2 p : b.positions())
			fn(p);
		return;
	}
	const std::uint64_t* w = b.ptr();
	for (int cy = 0; cy < G.ch; ++cy)
		for (int cx = 0; cx < G.cw; ++cx)
		{
			std::uint64_t word = w[cy * G.stride + cx];
			while (word)
			{
				const int bit = __builtin_ctzll(word);
				word &= word - 1;
				const vec2 p{ cx * 8 + (bit & 7), cy * 8 + (bit >> 3) };
				if (p.x < G.w && p.y < G.h)
					fn(p);
			}
		}
}

// Call fn(vec2) for every set tile within Chebyshev r of c, visiting only the 8x8 chunks that overlap the window.
template <class Fn> void bbforeach_near(const bitboard& b, vec2 c, int r, Fn&& fn)
{
	if (!NOVA_GDIRECT)
	{
		bbforeach(b, [&](vec2 p) { if (cheb(p, c) <= r) fn(p); });
		return;
	}
	const std::uint64_t* w = b.ptr();
	const int cx0 = std::max(0, c.x - r) >> 3, cx1 = std::min(G.w - 1, c.x + r) >> 3;
	const int cy0 = std::max(0, c.y - r) >> 3, cy1 = std::min(G.h - 1, c.y + r) >> 3;
	for (int cy = cy0; cy <= cy1; ++cy)
		for (int cx = cx0; cx <= cx1; ++cx)
		{
			std::uint64_t word = w[cy * G.stride + cx];
			while (word)
			{
				const int bit = __builtin_ctzll(word);
				word &= word - 1;
				const vec2 p{ cx * 8 + (bit & 7), cy * 8 + (bit >> 3) };
				if (p.x < G.w && p.y < G.h && cheb(p, c) <= r)
					fn(p);
			}
		}
}
// Used by the ward and intel code. Per-tile values stored by 8x8 cell, each cell allocated on its first write. Initialising a
// whole-map buffer costs about one fuel per byte, so sparse per-tile data (caches, labels) lives here instead. Unwritten tiles read
// as T{}.
template <class T> class TileMap
{
public:
	void reset()
	{
		cw_ = (G.w + 7) / 8;
		cells_.clear();
		cells_.resize(static_cast<std::size_t>(cw_) * static_cast<std::size_t>((G.h + 7) / 8));
	}
	bool ready() const { return !cells_.empty(); }
	T get(vec2 p) const
	{
		const std::size_t i = cell(p);
		if (i >= cells_.size())
			return T{};
		const auto& c = cells_[i];
		return c ? c[slot(p)] : T{};
	}
	// p must be on the map.
	T& at(vec2 p)
	{
		if (cells_.empty())
			reset();
		auto& c = cells_[cell(p)];
		if (!c)
		{
			c.reset(new T[64]);
			for (int i = 0; i < 64; ++i)
				c[static_cast<std::size_t>(i)] = T{};
		}
		return c[slot(p)];
	}
	// The 8x8 cell holding p (allocated as at() does): tiles (x & ~7) + k, k in 0..7, of row p.y sit at [k] of the result.
	T* row8(vec2 p) { return &at(vec2{ p.x & ~7, p.y }); }

private:
	std::vector<std::unique_ptr<T[]>> cells_;
	int cw_ = 0;
	std::size_t cell(vec2 p) const { return static_cast<std::size_t>((p.y >> 3) * cw_ + (p.x >> 3)); }
	static std::size_t slot(vec2 p) { return static_cast<std::size_t>(((p.y & 7) << 3) | (p.x & 7)); }
};
inline bool bbany(const bitboard& b)
{
	if (!NOVA_GDIRECT)
		return !b.is_empty();
	const std::uint64_t* w = b.ptr();
	const int n = G.ch * G.stride;
	for (int i = 0; i < n; ++i)
		if (w[i])
			return true;
	return false;
}

// The SDK's zero test, inlined; its out-of-line check runs only on an error (same throw).
NOVA_INLINE void nchk(std::int32_t c)
{
	if (__builtin_expect(c != 0, 0))
		cambc::detail::check(c);
}
// Three-address bitboard ops: one host call where clear + |= cost two. r may alias a.
NOVA_INLINE void bb3_or(const bitboard& a, const bitboard& b, bitboard& r) { nchk(cambc::detail::sdk_Bitboard_Union(a.ptr(), b.ptr(), r.ptr())); }
NOVA_INLINE void bb3_and(const bitboard& a, const bitboard& b, bitboard& r) { nchk(cambc::detail::sdk_Bitboard_Intersect(a.ptr(), b.ptr(), r.ptr())); }
NOVA_INLINE void bb3_xor(const bitboard& a, const bitboard& b, bitboard& r) { nchk(cambc::detail::sdk_Bitboard_Xor(a.ptr(), b.ptr(), r.ptr())); }
} // namespace nova
