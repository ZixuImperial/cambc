// strategy_base.cc: the BASE strategy. The default play: every decision as the shared code makes it.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_base(const Kit&, int stat, bool healer)
{
	// BASE plays most maps; on cluster maps Prospector pays every farmer when all non-healers hold it from r250 on maps with a cluster
	// share >= 0.15.
	if (!healer && item_in_top_holders(item_rank_cluster, ITM_PROS_BASE_N) && item_cluster_map())
		itm_insert_at(static_cast<unsigned long>(0), itm_shard(I_PROSPECTOR, stat));
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_BASE = {
	.name = "base",
	.item_plan = &econ::item_plan_base
};
} // namespace nova::strat
