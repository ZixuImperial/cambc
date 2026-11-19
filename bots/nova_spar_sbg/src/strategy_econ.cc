// strategy_econ.cc: the ECON strategy. Farm our side, bank on tempo, contest only what is free.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_econ(const Kit&, int stat, bool healer)
{
	if (!healer && item_in_top_holders(item_rank_cluster, ITM_ECON_N) && item_cluster_map())
		itm_insert_at(item_index_after_treasure(), itm_shard(I_PROSPECTOR, stat));
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_ECON = {
	.name = "econ",
	.item_plan = &econ::item_plan_econ
};
} // namespace nova::strat
