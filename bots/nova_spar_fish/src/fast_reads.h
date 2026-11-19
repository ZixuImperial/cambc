#pragma once
// fast_reads.h: Fast reads of positions and my items, and memory copy helpers.
#include "common_flags.h"
namespace nova {
// Which of a fixed list of tiles lie within Chebyshev r of p, 8 at a time (wasm i16x8: sub, abs, max, compare, bitmask: ~16 fuel per
// 8 tiles against ~14 a tile for the scalar loop). Bits ascend in list order, so a caller that walks the set bits low to high visits
// exactly the tiles the scalar loop's `cheb(.., p) > r) continue;` kept, in its order.
struct PosSoA
{
	std::vector<std::int16_t> x, y; // padded to a multiple of 8 with far tiles
	std::size_t n = static_cast<std::size_t>(-1);
};
NOVA_INLINE unsigned pos_within_r_mask(const PosSoA& s, std::size_t k, vec2 p, int r)
{
	const v128_t px = wasm_i16x8_splat(static_cast<std::int16_t>(p.x)), py = wasm_i16x8_splat(static_cast<std::int16_t>(p.y));
	const v128_t dx = wasm_i16x8_abs(wasm_i16x8_sub(wasm_v128_load(s.x.data() + k), px));
	const v128_t dy = wasm_i16x8_abs(wasm_i16x8_sub(wasm_v128_load(s.y.data() + k), py));
	return wasm_i16x8_bitmask(wasm_i16x8_le(wasm_i16x8_max(dx, dy), wasm_i16x8_splat(static_cast<std::int16_t>(r))));
}
// The altars' tiles (M.altars is built once from the altar board), rebuilt if the list changes size.
const PosSoA& altar_soa();

// The engine charges memory.copy / memory.fill one fuel a byte; 16-byte vector moves cost ~1 fuel each (plus addressing). vcopy /
// vzero move a trivially copyable object with unrolled v128 (then 8/4-byte) loads and stores: the same bytes end up in the
// destination as with the memcpy / memset the compiler emits for `d = s` / `d = T{}` (all-zero T). FxmItems: my item counts as
// cambc::self().item_count() gives them, without enum_map's zero fill (84 x 4 = 336 bytes of memory.fill = 336 fuel a call): the
// host writes all 84 entries or fails, and then check() throws as item_count() does. operator[] throws on a bad key as enum_map's
// .at() does. Use it only where the counts stay local (never where an enum_map is passed on).
struct FxmItems
{
	std::array<std::uint32_t, 84> v;
	std::uint32_t operator[](cambc::item_type t) const
	{
		const auto k = static_cast<std::size_t>(static_cast<std::uint32_t>(t));
		if (k >= v.size())
			throw std::out_of_range("FxmItems");
		return v[k];
	}
};
static_assert(sizeof(decltype(cambc::self().item_count())) == sizeof(FxmItems), "FXM: item count layout");
inline void my_item_counts(FxmItems& r)
{
	(void)cambc::self(); // the same throw during drafting
	cambc::detail::check(cambc::detail::sdk_champion_items(static_cast<std::uint32_t>(cambc::detail::cached_my_champion), r.v.data()));
}
template <std::size_t N, std::size_t I = 0> NOVA_INLINE void vmove_n(unsigned char* d, const unsigned char* s)
{
	if constexpr (I + 16 <= N)
	{
		wasm_v128_store(d + I, wasm_v128_load(s + I));
		vmove_n<N, I + 16>(d, s);
	}
	else if constexpr (I + 8 <= N)
	{
		std::uint64_t v;
		__builtin_memcpy(&v, s + I, 8);
		__builtin_memcpy(d + I, &v, 8);
		vmove_n<N, I + 8>(d, s);
	}
	else if constexpr (I + 4 <= N)
	{
		std::uint32_t v;
		__builtin_memcpy(&v, s + I, 4);
		__builtin_memcpy(d + I, &v, 4);
		vmove_n<N, I + 4>(d, s);
	}
	else if constexpr (I < N)
	{
		d[I] = s[I];
		vmove_n<N, I + 1>(d, s);
	}
}
template <std::size_t N, std::size_t I = 0> NOVA_INLINE void vzero_n(unsigned char* d)
{
	if constexpr (I + 16 <= N)
	{
		wasm_v128_store(d + I, wasm_i64x2_splat(0));
		vzero_n<N, I + 16>(d);
	}
	else if constexpr (I + 8 <= N)
	{
		const std::uint64_t v = 0;
		__builtin_memcpy(d + I, &v, 8);
		vzero_n<N, I + 8>(d);
	}
	else if constexpr (I + 4 <= N)
	{
		const std::uint32_t v = 0;
		__builtin_memcpy(d + I, &v, 4);
		vzero_n<N, I + 4>(d);
	}
	else if constexpr (I < N)
	{
		d[I] = 0;
		vzero_n<N, I + 1>(d);
	}
}
template <class T> NOVA_INLINE void vcopy(T& d, const T& s)
{
	static_assert(std::is_trivially_copyable_v<T>);
	if (&d != &s)
		vmove_n<sizeof(T)>(reinterpret_cast<unsigned char*>(&d), reinterpret_cast<const unsigned char*>(&s));
}
template <class T> NOVA_INLINE void vzero(T& d)
{
	static_assert(std::is_trivially_copyable_v<T>);
	vzero_n<sizeof(T)>(reinterpret_cast<unsigned char*>(&d));
}

// My item counts straight into a reused buffer. cambc::self().item_count() first zero-fills a fresh enum_map (a memory.fill, one
// fuel a byte) that the engine then overwrites in full. Throws exactly as item_count() does.
constexpr std::size_t ITEM_N = static_cast<std::size_t>(cambc::item_type::enum_type::count);
inline const std::uint32_t* my_items_raw()
{
	static std::uint32_t buf[ITEM_N];
	cambc::detail::check(cambc::detail::sdk_champion_items(static_cast<std::uint32_t>(cambc::detail::cached_my_champion), buf));
	return buf;
}

// Two boards equal, word by word (direct layout only; callers check NOVA_GDIRECT).
inline bool boards_equal(const bitboard& a, const bitboard& b)
{
	const std::uint64_t* x = a.ptr();
	const std::uint64_t* y = b.ptr();
	const int n = G.ch * G.stride;
	for (int i = 0; i < n; ++i)
		if (x[i] != y[i])
			return false;
	return true;
}
} // namespace nova
