#pragma once
// econ_internal.h: what every econ_*.cc file needs in scope: the headers it uses and its file-local macros.
#include "econ.h"
#include <cstring>
#include <wasm_simd128.h>
#include <memory>
#include <optional>
#include <algorithm>
#include <functional>
#include "intel.h"
#include "ward.h"

#include "combat.h"
#include "comms.h"
#include "dashnav.h"
#include "mapinfo.h"
#include "move.h"
#include "plan.h"
#include "planner.h"
#include "champ_willow.h"
#include "world.h"
#include "contest_play.h"
#include "strategy.h"
#include "item_upgrades.h"
#include "kill_gold.h"
#include "multipliers.h"
#include "squad.h"
#include "champ_prism.h"
#include "champions.h"
#include "rules.h"
#define CSX_RCT() (econ::csx_recall_t())
#include "engage.h"
#include "brain.h"

namespace nova::combat { int nearest_foe_distance_seen(int max_age); float foe_damage_over_ticks(int max_age, int ticks); } // combat.h declares them only when the Prism layer is on (champ_prism.h comes later)
#include "econ_linear_score.h"

// nova_spar_aggro: a group nearer the foe's spawn rates higher; the same factor goes into group_bounds so the sorted-bound break does not stop before the far groups.
#define SPAG_PUSH_X100 500
namespace nova::econ {
template <class G> inline float spag_factor(const G& g)
{
	if (g.d_home == UNREACH || g.d_enemy == UNREACH || g.d_home + g.d_enemy == 0)
		return 1.0f;
	const float sh = static_cast<float>(g.d_home) / static_cast<float>(g.d_home + g.d_enemy);
	return 1.0f + static_cast<float>(SPAG_PUSH_X100) / 100.0f * (sh > 0.25f ? sh - 0.25f : 0.0f);
}
} // namespace nova::econ
