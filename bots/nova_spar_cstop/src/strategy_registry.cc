// strategy_registry.cc: every strategy, in Mode order. Adding a strategy: see strategy.h.
#include "strategy.h"
namespace nova::strat {
extern const Policy POLICY_BASE;
extern const Policy POLICY_CENTER;
extern const Policy POLICY_ECON;
extern const Policy POLICY_SIEGE;
extern const Policy POLICY_RAID;
extern const Policy POLICY_ALTAR;
const Policy* const POLICIES[NMODES] = { &POLICY_BASE, &POLICY_CENTER, &POLICY_ECON, &POLICY_SIEGE, &POLICY_RAID, &POLICY_ALTAR };
} // namespace nova::strat
