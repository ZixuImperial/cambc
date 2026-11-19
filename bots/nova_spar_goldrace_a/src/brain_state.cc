// brain_state.cc: Turn tunables and shared turn state.
#include "brain_internal.h"
namespace nova {
namespace brain_tune
{
inline constexpr long WALK_FUEL = 30000;         // a calm team walk needs this much left
inline constexpr long PROBE_FUEL = 20000;        // a bush probe, and its second look
inline constexpr long END_ESCAPE_FUEL = 22000;   // review i2: below this the turn-end camp escape would suspend the turn
inline constexpr long UNPARK_FUEL = 35000;
inline constexpr long REACT_FUEL = 25000;        // react_guard and the landing dash at a turn's end
inline constexpr long LAST_STEP_FUEL = 15000;    // the start step of an idle opening turn
inline constexpr long FREE_ACT_FUEL = 15000;     // unused attacks and heals after the turn
inline constexpr long INTEL_END_FUEL = 20000;
inline constexpr long FIRST_SETUP_FUEL = 50000; // The setup costs 18-29k; 50k keeps over 20k spare.
inline constexpr long MAP_INIT_FUEL = 50000; // Background map stages run above this, and stop at MAP_INIT_KEEP.
inline constexpr long MAP_INIT_KEEP = 35000;
inline constexpr long BG_FUEL = 40000;           // background fields and caches
inline constexpr long ANALYSE_FUEL = 34000;      // merge i1: ward and intel steps stop at 24k, not 16k
inline constexpr long ANALYSE_KEEP = 24000;
inline constexpr long ROUTE_KEEP = 26000;        // crystal routes from our spawn
inline constexpr float KEEP_SHARE = 0.25f;       // a capture holds while this share of my max HP is left
inline constexpr float KEEP_MIN = 150.0f;        // and at least this much
}

namespace combat {   }
namespace {
} // namespace
} // namespace nova
