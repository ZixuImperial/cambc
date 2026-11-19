// brain_low_hp.cc: Low health turns and holds near Willow.
#include "brain_internal.h"
namespace nova::econ {
} // namespace nova::econ
namespace nova {
namespace {
// Threat points for retreating: visible enemies and awake attackers in reach.
std::vector<vec2> danger_points(const combat::Assessment& a)
{
	std::vector<vec2> pts = a.threats;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 1)
			pts.push_back(c.pos);
	}
	return pts;
}

// Low health: get out of danger, then walk home or recall once nothing can hit us. True if the turn is used. With an enemy in sight
// a body leaves at 45% (a burst finishes it below that); alone it farms down to 30%. WILLOW_REGEN (champ_willow.h): health at the
// start of my last non-channel turn (the recall's start), the hold streak.
float wr_pre_frac = 1.0f;
float wr_last_hp = 0;
int wr_hold_r = -1000;
int wr_hold_n = 0;
// Willow regen: may this hurt body skip a heal recall for our Willow? why = 1: her heal is back soon (any cooldown at >= 50% HP) and
// no foe within its reach + 2; why = 2 (most of the enemy dead): at least half the enemy bodies are dead with the first respawn >=
// WR_DM_RESP rounds away, she is within WR_DM_R (any cooldown), I am >= WR_DM_HOME walk from home, and no foe can hit me next turn
// (below 20% HP: none within its reach + 3). Returns her body, nullptr: recall as usual.
const Body* willow_recall_skip(const combat::Assessment& a, int& why)
{
	why = 0;
	const float fr = W.me.frac(); // v699 R2B bit 4096 TFH2: unhealed field Health is not missing HP
	if (const Body* h = support::ready_healer_near(WR_R, fr >= 0.5f ? 8 : WR_CD))
		if (support::no_foe_reach_within_margin(a, 2))
		{
			why = 1;
			return h;
		}
	const int tot = intel::enemies_total();
	if (tot <= 0 || intel::enemies_alive() * 2 > tot || intel::earliest_respawn() - W.round < WR_DM_RESP)
		return nullptr;
	if (econ::home_dist() < WR_DM_HOME || !support::no_foe_reach_within_margin(a, fr < 0.2f ? 3 : 0))
		return nullptr;
	if (const Body* h = support::ready_healer_near(WR_DM_R, 99))
	{
		why = 2;
		return h;
	}
	return nullptr;
}
// Instead of a heal recall or a heal walk home, hold within 2 of our Willow while she can heal me soon and nothing can reach me.
// True if the turn is used (a step toward her, out of camp reach, or standing).
bool hold_near_willow(const combat::Assessment& a)
{
	if (W.on_spawn || W.me.channeling() || !W.me.kit || willow_layer::regen_skip())
		return false;
	int why = 0;
	const Body* h = willow_recall_skip(a, why);
	if (!h)
		return false;
	if (wr_hold_r < W.round - 1 || W.me.hp > wr_last_hp + 1.0f)
		wr_hold_n = 0; // a new hold, or a heal landed
	if (wr_hold_n >= (why == 2 ? WR_HOLD_DM : WR_HOLD))
		return false; // No heal came: walk home as usual.
	++wr_hold_n;
	wr_hold_r = W.round;
	wr_last_hp = W.me.hp;
	NLOG("r%d slot %d WR hold%d hp %.0f willow d %d\n", W.round, P.my_slot, why, W.me.hp, cheb(h->pos, W.me.pos));
	if (!W.can_move())
		return true;
	const mv::AvoidCampReach guard;
	if (mv::camp_threat(W.me.pos) > 0)
	{
		const auto z = mv::camp_threats_near(7);
		if (!z.empty() && mv::escape(z))
			return true;
	}
	if (cheb(h->pos, W.me.pos) > 2 && !mv::step_to(h->pos, 2, 40))
		mv::step_greedy(h->pos);
	return true;
}
// The FLEE-streak recall is skipped when willow_recall_skip allows (the flee goes on).
bool flee_recall_skip_for_willow(const combat::Assessment& a)
{
	if (!W.me.kit || willow_layer::regen_skip())
		return false;
	int why = 0;
	return willow_recall_skip(a, why) != nullptr;
}
// A heal recall that our Willow's heal has made pointless: cancel it.
bool willow_recall_cancel_ok(const combat::Assessment& a)
{
	if (!W.me.kit || willow_layer::regen_skip() || W.me.gems >= 10 || econ::busy_capturing())
		return false;
	const float fr = W.me.frac();
	if ((fr) < static_cast<float>(WR_CANCEL_X100) / 100.0f || fr < wr_pre_frac + 0.25f) // v699 R2B bit 4096 TFH2 (the +.25 gain stays raw: wr_pre_frac is raw)
		return false;
	if (!support::ready_healer_near(WR_R, 8) || !support::no_foe_reach_within_margin(a, 2) || econ::want_shop())
		return false;
	return true;
}


// LKC: the unused attack that lock_hit would spend on an enemy altar lock in range goes to a foe champion in range instead (lowest effective HP; not on its
// spawn; not a lethal retaliation), unless my own bag waits on that altar.
static bool hit_champion_before_lock_slow();
// Inlined: the first early-out test sits at the call site, the rest is out of line.
static __attribute__((always_inline)) bool hit_champion_before_lock()
{
	if (!M.has_altar || !W.me.kit || heart_layer::ctx_lkc_skip() || W.enemies.empty())
		return false;
	return hit_champion_before_lock_slow();
}
static __attribute__((noinline)) bool hit_champion_before_lock_slow()
{
	const int r = std::max(1, W.me.range);
	bool lock = false;
	for (const auto& al : M.altars)
	{
		if (cheb(al.pos, W.me.pos) > r)
			continue;
		try
		{
			if (!cambc::vision::has_altar_lock(al.pos))
				continue;
			if (!cambc::vision::altar_lock_at(al.pos).is_enemy())
			{
				const bool en = econ::enemy_lock_on(al.pos);
				ALTAR_LOCK_SPLIT_CNT(0, en);
				if (!en)
					continue;
			}
		}
		catch (...)
		{
			FXR_PASS();
			continue;
		}
		if (W.me.gems >= 10u && cheb(al.pos, W.me.pos) <= 1)
			return false; // my bag needs this altar: the lock first
		lock = true;
	}
	if (!lock)
		return false;
	const Body* best = nullptr;
	for (const auto& e : W.enemies)
	{
		if (e.hp <= 0 || cheb(e.pos, W.me.pos) > W.me.range || bbget(M.enemy_spawn, e.pos))
			continue;
		if (combat::ren_kills_me(e))
			continue;
		if (!best || mu::ehp(e) < mu::ehp(*best))
			best = &e;
	}
	if (!best)
		return false;
	refresh_self();
	if (!W.can_attack() || W.me.channeling() || (W.me.kit->ranged && W.moved))
		return false;
	return combat::attack_champion(*best);
}
int mfb_lh_r = -1000; // The last round a foe-near low-HP leave ran.
bool handle_low_hp(const combat::Assessment& a)
{
	AF_CHECK();
	float frac = W.me.frac(); // v699 R2B bit 4096 TFH2: unhealed field Health is not missing HP
	// Cassi and Issac: my death kills my linked body too, so I leave earlier.
	const bool lk = combat::linked_slot() >= 0 && !CI2_FIGHT(); // CI2: no extra HP bars
	// EHC bit 4 HLX: on a crewed awake herd a foe counts as near at 6, not 8
	if (frac >=(((XCF_ON(1) ? (a.nearest <= 6 || (a.nearest <= 8 && !econ::ehc_herd_crew(3))) : a.nearest <= ((econ::ehc_herd_crew(3)) ? 6 : 8)) || // v775 XCF bit 1 LHE1: ehc only decides 7..8
				 (W.round - mfb_lh_r <= MFB_TAB[2])) ? (lk ? ((std::max(0.55f, static_cast<float>(B438_LOWHP_X100) / 100.0f))) : static_cast<float>(B438_LOWHP_X100) / 100.0f) :
		 (lk ? 0.4f : 0.3f)) || W.on_spawn)
		return false;
	// PASSIVE HoR/Varg/Ren: a clear that ends within a few rounds with health to spare is finished, not walked off.
	if (a.foes.empty() && a.nearest > 8 && econ::finish_clear_ok())
		return false;
	if (a.foes.empty() && a.nearest > 8 && econ::finish_low_camp_ok(frac))
		return false;
	// A capture pays within a few rounds and damage does not stop it: finish it while nothing is hitting us.
	// D4: right after a clear the last camp hits still count as recent damage, which made the body walk home from a
	// cleared group instead of standing on it; nothing in reach and no enemy near is enough to capture first.
	if (econ::about_to_capture() && (econ::recall_safe() || // v7xx WFB bit 64 LHC1: not a paid capture
		 (mv::camp_threat(W.me.pos) <= 0 && a.nearest > 6 && frac > 0.12f &&
		!(combat::took_damage(1)))))
		return false;
	if (a.nearest > 6 && econ::idle_escape_holds_capture() && combat::hit_explained_by_camp())
		return false;
	if (a.nearest <= 8) // Only a foe in sight renews it, so it ends.
		mfb_lh_r = W.round;
	const float ct = mv::camp_threat(W.me.pos);
	const bool danger = ct > 0 || a.nearest <= 4;
	// Inside an awake camp's reach, step_away's one greedy step keeps the most distance from the danger points, so with the way out
	// blocked it slides between two tiles inside the reach, hit every round. Just outside it, go_home's homeward path can lead straight
	// back in. So: inside, take the shortest path out of every reach (mv::escape); outside, the guard keeps every step and path out of
	// the awake camps' reach, and when no way home avoids them the body waits outside (a camp sleeps after 2 rounds with no champion in
	// reach) instead of farming.
	const mv::AvoidCampReach guard;
	if (danger)
	{
		if (ct > 0)
		{
			std::vector<mv::Threat> z = mv::camp_threats_near(7);
			nova::econ::threat_checks::low_hp_flee_zones(a, z); // flee()'s danger zones.
			if (mv::escape(z))
			{
				econ::note_camp_escape();
				return true;
			}
		}
		// Away from the foes, but toward the nearest ally (else home) among the steps that leave the danger.
		if (ct <= 0 && a.nearest <= 4 && fuel() > 25000)
		{
			std::vector<mv::Threat> z;
			nova::econ::threat_checks::low_hp_flee_zones(a, z); // flee()'s danger zones.
			const vec2 goal = combat::react_rally();
			if (!z.empty() && mv::retreat_step(z, 2, goal))
			{
				return true;
			}
		}
		const auto pts = danger_points(a);
		if (!pts.empty() && mv::step_away(pts))
			return true;
	}
	if (hold_near_willow(a))
		return true;
	if (econ::go_home())
		return true;
	// Free to move, outside every awake camp's reach, and no step home avoids them: hold here this turn.
	return guard.active && W.can_move() && !W.moved;
}
} // namespace
} // namespace nova
