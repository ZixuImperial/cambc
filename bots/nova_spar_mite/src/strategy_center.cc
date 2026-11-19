// strategy_center.cc: the CENTER strategy. Take and hold the middle's heavy groups with a crew or pack.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_center(const Kit&, int stat, bool healer)
{
	constexpr int HEALTH = 2;
	// Capture for the crew lead: the capped timer holds for the whole team while the holder stands on the region.
	if (!healer && P.my_slot >= 0 && P.tank_order[static_cast<std::size_t>(P.my_slot)] < ITM_CENTER_N)
	{
		bool done = false;
		for (auto& t : build)
			if (!done && itm_family(t) == I_BRUISER && itm_stat(t) == HEALTH)
			{
				t = itm_shard(I_CAPTURE, HEALTH);
				done = true;
			}
		if (!done)
			itm_insert_at(item_index_after_treasure(), itm_shard(I_CAPTURE, HEALTH));
	}
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_CENTER = {
	.name = "center",
	.item_plan = &econ::item_plan_center
};
} // namespace nova::strat
