// brain_setup.cc: First-turn setup.
#include "brain_internal.h"
namespace nova {
namespace {
// My next turn-order value; PRA encodes it.
NOVA_INLINE void set_prio(int v)
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	cambc::self().set_priority(v);
}

void setup()
{
	build_plan();
	strat::begin_turn(); // b1976 SMZ bit 1 (RC C316 D1): play_turn ran begin_turn before build_plan decoded the Mode
	world_init();
	econ::init();
	intel::init(); // Enemy roster and tables now, while the setup turn has fuel to spare.
	try
	{
		int pr = 0;
		if (P.my_slot >= 0)
			pr = P.prio[static_cast<std::size_t>(P.my_slot)];
		set_prio(pr);
	}
	catch (...)
	{
		FXR_PASS();
	}
	planned = true;
	NLOG("setup direct %d w %d h %d cw %d ch %d stride %d slot %d role %d party %d n %d mem %d flags %u\n", (int)NOVA_GDIRECT, G.w, G.h, G.cw, G.ch, G.stride, P.my_slot,
		P.my_slot >= 0 ? P.role[static_cast<std::size_t>(P.my_slot)] : -1,
		P.my_slot >= 0 ? P.party[static_cast<std::size_t>(P.my_slot)] : -1, P.n, (int)P.from_memory, P.flags);
}

int cur_prio = -1000; // turn (hoisted statics: shared by both instantiations)
// A value the engine took stands as mine.
NOVA_INLINE void adopt_prio(int v)
{
	try
	{
		set_prio(v);
		cur_prio = v;
	}
	catch (...)
	{
		FXR_PASS();
	}
}
vec2 rx_wc_from{ -1, -1 }; // My tile when this turn started.
int streak = 0, last_r = -10, start_d = 0;
bool pg_walk = false;
} // namespace
} // namespace nova
