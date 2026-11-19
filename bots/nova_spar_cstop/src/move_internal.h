#pragma once
// move_internal.h: what every move_*.cc file needs in scope: the headers it uses and its file-local macros.
#include <wasm_simd128.h>
#include "move.h"

#include "combat.h" // Travel dash casts.
#include "mapinfo.h"
#include "plan.h"
#include "world.h"
#include "champions.h"
namespace nova::econ { bool hs3_pending_x(int gi); }
namespace nova::econ { bool keep_out_of_escaped_reach(vec2 dest); }

