// champ_tavi.cc: TAVI LAYER, Tavi's rules (hooks and flags: champ_tavi.h). Holds TVG (rent then Greed: on spawn he sells his latest
// planned emblems and buys 25 Greed shards). Unity build: econ's helpers are in scope.
#include "econ.h"
#include "champions.h"
// Tavi's econ rules.
namespace nova::econ {
// inlined: the first early-out test is inline at the call site, the rest is out of line
__attribute__((always_inline)) void tavi_sell_emblems_buy_greed()
{
	if (!W.alive || !W.on_spawn || !tavi_layer::me())
		return;
	tavi_sell_emblems_buy_greed_slow();
}
__attribute__((noinline)) void tavi_sell_emblems_buy_greed_slow()
{
	if (!W.alive || !W.on_spawn || !tavi_layer::me() || now() < std::max(10, static_cast<int>(TVG_TAB[2])) ||
		fuel() < TVG_FUEL)
		return; // never on the setup turns, never on a short turn (saves fuel)
	try
	{
		const auto& me = cambc::self();
		auto c = me.item_count();
		{
			int all = static_cast<int>(me.gold_count()); // cheap bound first: every non-Greed item at resale
			for (int i = 0; i < 84; ++i)
				if (i / 6 != 12)
					all += static_cast<int>(c[cambc::item_type(static_cast<std::uint32_t>(i))]) * ((i & 1) ? 150 : 30);
			if (all < 750)
				return;
		}
		if (!build_ready)
			make_build();
		int rank[84];
		for (int i = 0; i < 84; ++i)
			rank[i] = 1000; // not in the build: sold first
		for (int i = 0; i < static_cast<int>(build.size()); ++i)
		{
			const int si = static_cast<int>(static_cast<std::uint32_t>(build[static_cast<std::size_t>(i)])) & ~1;
			if (si >= 0 && si + 1 < 84)
				rank[si] = rank[si + 1] = (rank[si] == 1000 ? i : std::max(rank[si], i));
		}
		auto sellable = [&](int i) { return i / 6 != 12 && rank[i] >= TVG_TAB[4] && static_cast<int>(c[cambc::item_type(static_cast<std::uint32_t>(i))]) > 0; };
		int gold = static_cast<int>(me.gold_count());
		int liquid = gold;
		for (int i = 0; i < 84; ++i)
			if (sellable(i))
				liquid += static_cast<int>(c[cambc::item_type(static_cast<std::uint32_t>(i))]) * ((i & 1) ? 150 : 30);
		if (liquid < 750)
			return;
		cancel_spin_before_action(); // a running spin blocks the shop: cancel it first
		for (int guard = 0; gold < 750 && guard < 64; ++guard)
		{
			int best = -1;
			for (int i = 0; i < 84; ++i) // latest build slot first; at equal rank shards (even ids) before emblems
				if (sellable(i) && (best < 0 || rank[i] > rank[best] || (rank[i] == rank[best] && (i & 1) < (best & 1))))
					best = i;
			if (best < 0)
				break;
			me.sell(cambc::item_type(static_cast<std::uint32_t>(best)), 1);
			c = me.item_count();
			gold = static_cast<int>(me.gold_count());
		}
		if (gold >= 750)
			me.buy(cambc::item_type(static_cast<std::uint32_t>(72 + 2 * std::clamp(static_cast<int>(TVG_TAB[3]), 0, 2))), 25u);
		prism::fam_reset();
	}
	catch (...)
	{
	}
	try
	{
		W.gold = cambc::self().gold_count();
	}
	catch (...)
	{
	}
	own.checked = -1000;
	refresh_self();
}
} // namespace nova::econ
