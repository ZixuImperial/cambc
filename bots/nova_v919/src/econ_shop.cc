// econ_shop.cc: Buying at the shop.
#include "econ_internal.h"
namespace nova::econ {
void shop()
{
	if (W.gold < 30)
		return;
	if (build_ready && upitm_stale())
		build_ready = false; // the strategy mode changed: remake the build
	if (build_ready && pjm_rebuild_due())
		build_ready = false; // b2379 PJM 64: her build predates the map plan
	if (!build_ready)
		make_build();
	try
	{
		const auto& me = cambc::self();
		auto counts = me.item_count();
		if (W.me.kit && prism_layer::shop_wbt() && static_cast<int>(W.me.gems) >= WBT_BAG)
			tribute_emblem_to_front(counts);
		emblem_observe(); // income before this visit spends it
		emblem_rank(counts);
		nova::econ::emblem_order::passive_first(build, counts); // passive emblems before Greed
		greed_gate(counts);
		std::array<int, 96> need; // item ids reach 83 in engine 2.0.0 and later
		vzero(need); // zero the array with vector stores
		std::uint32_t gold = W.gold;
		for (const auto& sh : build)
		{
			const auto si = static_cast<std::size_t>(static_cast<std::uint32_t>(sh));
			const auto emblem = cambc::item_type(static_cast<std::uint32_t>(si + 1));
			++need[si];
			if (static_cast<int>(counts[emblem]) >= need[si])
				continue;
			const int have = static_cast<int>(counts[sh]);
			if (CI2_FARM() && nova::ci2::shop_hold(si, have))
				continue; // CI2 decision 8: the first Health shards are bought, the next emblem comes first
			// a Greed emblem combines from 25 shards (GameRules 289/301), every other family from 5.
			const int per = (static_cast<int>(si) / 6 == 12) ? 25 : 5;
			const int want = std::max(0, per - have);
			const int n = std::min<int>(want, static_cast<int>(gold / 30));
			if (n <= 0)
				break;
			if (sps_pending && !W.on_spawn)
				cancel_spin_before_action(); // a running spin refuses can_buy, and the spawn-brain code only clears it on the spawn
			if (!me.can_buy(sh, static_cast<std::uint32_t>(n)))
				break;
			cancel_spin_before_action();
			me.buy(sh, static_cast<std::uint32_t>(n));
			gold -= static_cast<std::uint32_t>(n) * 30;
			W.gold = gold; // X02 bit 1: booked now, so a later throw cannot leave it unspent
			emb_pgold = static_cast<int>(gold);
			own.checked = -1000;
			rcg_shop = now(); // a shop visit ends a recall chain
			prism::fam_reset(); // the next has_family reads the new emblem
			NLOG("r%d slot %d bought %d x %s\n", now(), P.my_slot, n, cambc::to_string(sh).c_str());
			if (n < want)
				break;
			counts = me.item_count();
		}
		W.gold = gold;
		emb_pgold = static_cast<int>(gold); // purchases are not income
		own.checked = -1000;
	}
	catch (const std::exception& e)
	{
		NLOG("r%d shop error %s\n", now(), e.what());
	}
}
} // namespace nova::econ
