// brain_tie_shop.cc: Tie seek and shop recall.
#include "brain_internal.h"
namespace nova {
namespace {
static int tsk_idle = 0; // tie_seek_turn's idle counter, at file scope so its reset test can be inline; the rest of tie_seek_turn is out of line.
static bool tie_seek_turn_slow(const combat::Assessment& a);
static bool rf2_earned = false; // I have held gold on some turn (my lifetime gold earned > 0).
static __attribute__((always_inline)) bool tie_seek_turn(const combat::Assessment& a)
{
	rf2_earned |= W.gold != 0;
	if (rf2_earned && W.gold == 0 && W.me.gems == 0 && W.tributed_us == 0 && W.tributed_them == 0)
		KIT_RULE_FIX_CNT(5, true);
	if (rf2_earned)
	{
		tsk_idle = 0;
		return false;
	}
	if (W.me.gems != 0 || W.gold != 0 || W.tributed_us != 0 || W.tributed_them != 0 || econ::claim_target() >= 0)
	{
		tsk_idle = 0;
		return false;
	}
	return tie_seek_turn_slow(a);
}
static __attribute__((noinline)) bool tie_seek_turn_slow(const combat::Assessment& a)
{
	int& idle = tsk_idle;
	++idle;
	if (idle < TSK_TAB[2] || !W.alive || !W.can_move() || W.me.channeling() || a.stance != combat::CALM)
		return false;
	if (cambc::detail::cached_my_team != 0)
		return false;
	static distance_field tf; // M.f_enemy isn't built when the draft stored the distances
	static bool tf_ok = false;
	if (!tf_ok)
	{
		if (fuel() < 40000)
			return false;
		bitboard visited;
		tf.compute(M.walls | M.holes | M.altars_bb | M.my_spawn, M.enemy_spawn, visited);
		tf_ok = true;
	}
	return mv::step_field(tf);
}
bool shop_recall_slow(const combat::Assessment& a);
// Inlined: the first early-out test sits at the call site, the rest is out of line.
__attribute__((always_inline)) bool shop_recall(const combat::Assessment& a)
{
	if (a.nearest <= 7 || !econ::want_shop())
		return false;
	return shop_recall_slow(a);
}
__attribute__((noinline)) bool shop_recall_slow(const combat::Assessment& a)
{
	if (econ::home_round_trip_too_costly())
		return false;
	if (W.me.gems >= 10 && M.any_altar && !(prism_layer::shop_recall_keeps_bag()))
		return false; // Bank first (the Prism carrier keeps her bag through a shop recall).
	if (econ::home_dist() > 7 && !econ::recall_safe())
		return false;
	return econ::go_home();
}
} // namespace
} // namespace nova
