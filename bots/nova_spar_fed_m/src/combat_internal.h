#pragma once
// combat_internal.h: what every combat_*.cc file needs in scope: the headers it uses and its file-local macros.
#include "combat.h"
#include "contest_play.h"

#include "comms.h"
#include "intel.h"
#include "econ.h"  // lift threat_seen blacklists of dead foes
#include "mapinfo.h"
#include "plan.h"
#include "move.h"
#include "champ_willow.h"
#include "squad.h"
#include "champ_prism.h"
#include "champions.h" // kit layers (Prism)
#include "rules.h"
#include "engage.h"
#include "ward.h"
#include "multipliers.h"
#include "strategy.h"
