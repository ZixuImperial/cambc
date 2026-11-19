// strategy_siege.cc: the SIEGE strategy. Team sieges of bosses and the heaviest groups.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void item_plan_siege(const Kit& k, int stat, bool healer) // k: SMZ_BITS bit 2 passes it to the base plan
{
	item_plan_base(k, stat, healer); // b1976 SMZ bit 2: SIEGE plays BASE's build until SSM bit 2 (the Monster plan, after it)
	return;
}
} // namespace
} // namespace nova::econ

namespace nova::strat {
extern const Policy POLICY_SIEGE = {
	.name = "siege",
	.item_plan = &econ::item_plan_siege
};
} // namespace nova::strat
