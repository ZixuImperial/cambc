// strategy_raid.cc: the RAID strategy. Pressure in their half: pick-offs and denial.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_raid(const Kit&, int stat, bool healer)
{
	if (!healer && item_in_top_holders(item_rank_killer, ITM_RAID_N))
	{
		itm_insert_at(item_index_after_treasure(), itm_shard(I_HUNTER, stat));
		if (item_in_top_holders(item_rank_killer, 1))
		{
			const std::size_t ts = item_tail_start();
			if (ts < build.size())
				build[ts] = itm_shard(I_SKIRMISH, stat);
		}
	}
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_RAID = {
	.name = "raid",
	.item_plan = &econ::item_plan_raid
};
} // namespace nova::strat
