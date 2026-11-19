// strategy_siege.cc: the SIEGE strategy. Team sieges of bosses and the heaviest groups.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_siege(const Kit&, int stat, bool healer)
{
	if (!healer)
	{
		const std::size_t at = item_index_after_treasure();
		for (std::size_t i = 0; i < build.size(); ++i)
			if (itm_family(build[i]) == I_MONSTER)
				build[i] = itm_shard(I_BRUISER, stat); // one Monster emblem is enough (passives never stack)
		itm_insert_at(at, itm_shard(I_MONSTER, stat));
	}
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_SIEGE = {
	.name = "siege",
	.item_plan = &econ::item_plan_siege
};
} // namespace nova::strat
