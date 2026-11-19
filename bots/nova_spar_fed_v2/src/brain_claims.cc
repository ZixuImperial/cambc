// brain_claims.cc: Publishing claims and tasks to mates.
#include "brain_internal.h"
namespace nova {
namespace {
// 0..3 from full to low health, the band claims and fight calls report.
NOVA_INLINE int hp_band(float f) { return f >= 0.75f ? 0 : f >= 0.5f ? 1 : f >= 0.25f ? 2 : 3; }

// The state part of my claim code. Fight states are simple writers; consumers come later.
int tm2_stance = 0, tm2_dead0 = -1, tm2_coming = -1, tm2_coming_r = -100;
int tm2_fl_r = -100, tm2_flv = 0; // This round's in-fight code (stance x 4 + HP band).
int claim_code_x(int group, bool engaged)
{
	if (W.alive)
		tm2_dead0 = -1;
	else if (tm2_dead0 < 0)
		tm2_dead0 = W.round;
	if (W.alive) // Near a foe, or walking to a call, the fight state replaces my group claim.
	{
		if (tm2_coming >= 0 && tm2_coming_r == W.round)
			return 200 + tm2_coming;
		if (tm2_fl_r == W.round)
			return 100 + tm2_flv;
	}
	if (group >= 0)
		return econ::team_mem_claim_state(group, engaged); // No bucket in the code.
	if (!W.alive)
	{
		const int rem = rs::champ_respawn_rounds() - (W.round - tm2_dead0); // Exact from the first own turn seen dead.
		return rem > 30 ? 1 : rem > 10 ? 2 : 3;
	}
	if (tm2_coming >= 0 && tm2_coming_r == W.round)
		return 200 + tm2_coming;
	if (tm2_stance == 0)
		return 0;
	const float f = W.me.frac();
	return 100 + (tm2_stance == 2 ? 8 : 0) + hp_band(f);
}
void publish(int group, bool engaged)
{
	const int x = claim_code_x(group, engaged);
	comms::claim_x(x);
	if (x >= 100) // the fight state goes out in place of the group (write_claim reads x only without a group)
	{
		group = -1;
		engaged = false;
	}
	comms::write_claim(P.my_slot, group, engaged);
}
void publish_task()
{
	publish(econ::claim_target(), econ::claim_engaged());
}
} // namespace
} // namespace nova
