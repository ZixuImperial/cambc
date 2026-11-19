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
namespace nova::econ { inline int klx_last = -1000; } // b2131 GBZ KLX1: the newest kill_round written (resets only lower it)
#include "econ_linear_score.h"
