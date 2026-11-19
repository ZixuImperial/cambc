#pragma once
// ward_internal.h: what every ward_*.cc file needs in scope: the headers it uses and its file-local macros.
#include <wasm_simd128.h>
#include "ward.h"
#include "combat.h" // For took_damage.
#include "move.h" // For camp_threat.

#include "comms.h"
#include "econ.h"
#include "intel.h"
#include "mapinfo.h"
#include "plan.h"
#include "world.h"
#include "contest_play.h"

