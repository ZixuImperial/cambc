// combat_calm.cc: Casts on a calm turn.
#include "combat_internal.h"
namespace nova::combat {
namespace calm
{
namespace tune
{
}
namespace {
static int hfc_prev = -1000; // the last unexplained hit (hidden_fire_slow)
static int hfp_round = -1000; // the round last written in a pay hold
// A camp that could explain the damage: it attacks, I am in its reach, unseen or awake, not known dead.
static __attribute__((always_inline)) inline bool camp_explains_damage(std::size_t ci)
{
	const auto& c = M.camps[ci];
	return c.attacks() && cheb(c.pos, W.me.pos) <= c.reach && (!bbget(W.vis, c.pos) || bbget(W.awake, c.pos)) &&
		!(econ::camp_known_dead(static_cast<int>(ci)));
}
__attribute__((noinline)) bool hidden_fire_slow()
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 6)
			return false;
	if (mv::camp_threat(W.me.pos) > 0 && !(nova::econ::threat_checks::cex_round == W.round))
		return false;
	// leaves less than 15% is kept (the hidden source may be a camp or a champion: last hit x k rounds)
	const int pay = econ::capture_pay_in();
	if (pay >= 0 && turn_memory.hp_lost_at_dmg_round * static_cast<float>(econ::camp_hits_before_capture_pay(pay)) < W.me.hp - 0.15f * W.me.maxhp)
	{
		bool camp = false;
		for (std::size_t ci = 0; ci < static_cast<std::size_t>(M.nc) && !camp; ++ci)
			camp = camp_explains_damage(ci);
		if (!camp)
		{
			hfc_prev = W.round;
			hfp_round = W.round;
			CODE_ERR_FIX_CNT(5, true);
		}
		return false;
	}
	// Camps we cannot see (behind walls, in bushes) or awake ones: step out of every reach that could cover me.
	std::vector<mv::Threat> th;
	for (std::size_t ci = 0; ci < static_cast<std::size_t>(M.nc); ++ci)
	{
		const auto& c = M.camps[ci];
		if (camp_explains_damage(ci))
		{
			th.push_back({ c.pos, c.reach });
			// Remember it as awake, so the walk home does not step straight back into its reach.
			if (!bbget(W.vis, c.pos))
				mv::note_awake(static_cast<int>(ci));
		}
	}
	if (th.empty()) // a Vesper in an unlit bush shot a carrier from fog
	{
		const bool again = W.round - hfc_prev <= 2;
		CODE_ERR_FIX_CNT(6, again && hfp_round == hfc_prev); // 'again' only because the pay hold remembered the last hit
		hfc_prev = W.round;
		if (again)
		{
			const int r = static_cast<int>(HFC_TAB[2]);
			for (int dy = -r; dy <= r && th.size() < 24; ++dy)
				for (int dx = -r; dx <= r && th.size() < 24; ++dx)
				{
					const vec2 p{ W.me.pos.x + dx, W.me.pos.y + dy };
					if (inb(p) && bbget(M.bushes, p) && !bbget(W.vis, p))
						th.push_back({ p, static_cast<int>(HFC_TAB[3]) });
				}
		}
	}
	if (th.empty())
		return false;
	NLOG("r%d hidden fire: %zu camps, hp %.0f\n", W.round, th.size(), W.me.hp);
	if (!mv::escape(th))
		return false;
	econ::note_camp_escape();
	return true;
}
__attribute__((noinline)) bool spell_poke_slow(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	bool acted = false;
	// A stun on a foe that is on top of a team mate (it loses its next turn: a peel without a step).
	if (k.slot_cc >= 0 && ready(k.slot_cc) && (!k.cc_excl || !W.moved))
		for (const auto& e : W.enemies)
		{
			if (e.stunned || marcella_layer::fight_stun_wasted(e) || foe_model::unreachable(e) || cheb(e.pos, W.me.pos) > static_cast<int>(k.cc_range))
				continue;
			bool on_mate = false;
			for (const auto& al : W.allies)
				on_mate |= cheb(al.pos, e.pos) <= std::max(1, e.range);
			if (on_mate && cast_on_champion(k.slot_cc, e))
			{
				acted = true;
				break;
			}
		}
	// The single-target damage spell on the weakest champion in its range.
	if (!W.cast && k.slot_dmg >= 0 && k.dmg_mod > 0 && ready(k.slot_dmg) && (!k.dmg_excl || !W.moved))
	{
		const Body* best = nullptr;
		float bh = 1e9f;
		for (const auto& e : W.enemies)
		{
			if (foe_model::unreachable(e) || cheb(e.pos, W.me.pos) > static_cast<int>(k.dmg_range))
				continue;
			const float h = eff_hp(e);
			if (h < bh)
			{
				bh = h;
				best = &e;
			}
		}
		if (best && cast_on_champion(k.slot_dmg, *best))
			acted = true;
	}
	// The area spell on the tile covering the most enemy champions (one at least).
	if (!W.cast && k.slot_aoe >= 0 && k.aoe_mod > 0 && ready(k.slot_aoe) && (!k.aoe_excl || !W.moved))
	{
		vec2 bt{ -1, -1 };
		int bn = 0;
		const int rad = static_cast<int>(k.aoe_radius);
		for (const auto& e : W.enemies)
			for (int dx = -rad; dx <= rad; ++dx)
				for (int dy = -rad; dy <= rad; ++dy)
				{
					const vec2 t{ e.pos.x + dx, e.pos.y + dy };
					if (!inb(t) || cheb(t, W.me.pos) > static_cast<int>(k.aoe_range))
						continue;
					if (BB12_ON(16) && kit_rules::ren_retaliation_of_cast(k.slot_aoe, 0u, 0u, t) >= eff_hp(W.me))
						continue; // BB12 RENT: the Rens it hits retaliate me dead
					int n = 0;
					for (const auto& o : W.enemies)
					{
						n += cheb(o.pos, t) <= rad && !(BB12_ON(1) && bbget(M.enemy_spawn, o.pos) && eff_hp(o) > k.aoe_mod * burst::spell_on(burst::spell_base(), o)) ? 1 : 0; // BB12 CALMSP
					}
					if (n > bn && !AreaGrid::wakes_other(t, rad, -1)) // the wake test only for a better tile
					{
						bn = n;
						bt = t;
					}
				}
		if (bn >= 1 && bt.x >= 0 && cast_at(k.slot_aoe, bt))
			acted = true;
	}
	return acted;
}
__attribute__((noinline)) bool kite_shot_after_move_slow()
{
	const Kit& k = *W.me.kit;
	for (const auto& e : W.enemies)
		if (e.kit && !e.kit->ranged && cheb(e.pos, W.me.pos) <= 2)
			return false; // kite shots next to a melee body die twice as often
	const Body* tgt = nullptr;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit) && (!tgt || eff_hp(e) < eff_hp(*tgt)))
			tgt = &e;
	return tgt && cast_self(k.slot_reset) && attack_champion(*tgt);
}
__attribute__((noinline)) bool assist_cast_slow()
{
	const vec2 me = W.me.pos;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= 6)
			return false; // the fight logic owns these turns
	const Kit& k = *W.me.kit;
	// Awake attackers an ally holds: an ally stands nearer to them than I do, so they keep hitting that ally.
	auto held = [&](const VisCamp& vc)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (!vc.awake || !c.attacks())
			return false;
		const int dm = cheb(c.pos, me);
		for (const auto& al : W.allies)
			if (!al.channeling() && cheb(al.pos, c.pos) < dm)
				return true;
		return false;
	};
	if (k.slot_aoe >= 0 && k.aoe_on_camps && ready(k.slot_aoe))
	{
		const int r = std::max(0, static_cast<int>(k.aoe_radius));
		std::array<int, 4> done{ -1, -1, -1, -1 };
		std::size_t nd = 0;
		for (const auto& vc : W.camps)
		{
			if (!held(vc) || cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, me) > static_cast<int>(k.aoe_range) + r)
				continue;
			const int gi = M.camps[static_cast<std::size_t>(vc.ci)].group;
			if (std::find(done.begin(), done.begin() + static_cast<std::ptrdiff_t>(nd), gi) != done.begin() + static_cast<std::ptrdiff_t>(nd))
				continue;
			if (nd < done.size())
				done[nd++] = gi;
			AreaGrid grid;
			grid.build(gi, r);
			int n = 0;
			const vec2 best = grid.best(me, static_cast<int>(k.aoe_range), false, &n, gi, r);
			if (best.x >= 0 && n >= 2 && cast_at(k.slot_aoe, best))
				return true;
		}
	}
	if (k.slot_dmg >= 0 && k.dmg_on_camps && ready(k.slot_dmg))
	{
		int best = -1;
		float best_hp = 1e9f;
		for (const auto& vc : W.camps)
			if (held(vc) && cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, me) <= static_cast<int>(k.dmg_range) && vc.hp < best_hp)
			{
				best_hp = vc.hp;
				best = vc.ci;
			}
		if (best >= 0 && cast_on_camp(k.slot_dmg, best))
		{
			if (!W.attacked)
				hit_camp(best);
			return true;
		}
	}
	return false;
}
} // namespace
} // namespace calm
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool hidden_fire()
{
	if (!took_damage(1) || W.on_spawn || stance::low_start_blocked())
		return false;
	return calm::hidden_fire_slow();
}
// the visible foes within 9 deal at least my HP + shield on their next turns (one-turn sum: lethal_burst_hit per foe, cooldowns as now).
bool visible_foes_lethal_next_turn()
{
	if (!W.alive || W.enemies.empty())
		return false;
	const float eff = W.me.hp + std::max(0.0f, W.me.shield);
	float s = 0.0f;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, W.me.pos);
		if (d <= 9)
		{
			float h = burst::lethal_burst_hit(e, d, 0, nullptr);
			h = burst::stun_takes_next_turn(e) ? 0.0f : burst::reach_burst_turns(e) >= 2 ? burst::lethal_burst_two_turn_hit(e, d, h) : h;
			s += std::max(0.0f, h);
		}
		if (s >= eff)
			return true;
	}
	return false;
}
bool is_caster_champion()
{
	const int t = static_cast<int>(W.me.type);
	return t >= 0 && t < 32 && ((PO_CASTER_MASK >> t) & 1u) != 0;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool spell_poke(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	if (a.stance != CALM || a.in_reach || W.cast || W.me.channeling() || W.me.frac() < 0.4f || W.enemies.empty() || stance::low_start_blocked())
		return false;
	return calm::spell_poke_slow(a);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool kite_shot_after_move()
{
	const Kit& k = *W.me.kit;
	if (!k.ranged || !W.moved || W.attacked || k.slot_reset < 0 || !ready(k.slot_reset) || W.me.frac() < 0.3f || W.me.channeling() || stance::low_start_blocked())
		return false;
	return calm::kite_shot_after_move_slow();
}
// True when no foe was seen within CU_HOLD_D (6) in the last CU_HOLD_AGE (2) rounds: camp spells are free (no spell hold).
// Prism skips it (her spell-free rule). CU_WALK / CU_HOLD are not read.
bool cast_uptime_walk_in_free()
{
	if (!W.me.kit || prism_layer::fight_skip_cu())
		return false;
	return nearest_foe_distance_seen(CAST_UPTIME_TAB[4]) > CAST_UPTIME_TAB[3];
}
// camp_abilities' spell hold without its Prism term (the callers add prism_layer::camp_stun_free_now per kit). My view this turn;
// mates near me (the siege, a shared clear) share the foe list. Memo per turn.
bool camp_spell_hold_without_prism()
{
	static int r = -1000, s = -1;
	static bool v = false;
	if (r != W.round || s != P.my_slot)
	{
		r = W.round;
		s = P.my_slot;
		v = !seen.empty() && W.me.kit && W.me.frac() >= camps::tune::CAMP_SPELLS_FREE_BELOW && !cast_uptime_walk_in_free();
	}
	return v;
}
bool caster_spell_reaches(int ci)
{
	if (ci < 0)
		return false;
	if (!is_caster_champion())
		return false;
	const Kit& k = *W.me.kit;
	const auto& c = M.camps[static_cast<std::size_t>(ci)];
	if (k.slot_dmg >= 0 && k.dmg_on_camps && ready(k.slot_dmg) && cheb(c.pos, W.me.pos) <= static_cast<int>(k.dmg_range))
		return true;
	if (k.slot_aoe >= 0 && k.aoe_on_camps && ready(k.slot_aoe))
		for (const auto& vc : W.camps)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group == c.group && cheb(cp.pos, W.me.pos) <= static_cast<int>(k.aoe_range + k.aoe_radius))
				return true;
		}
	return false;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool assist_cast()
{
	if (!is_caster_champion() || W.cast || W.moved || !W.me.kit)
		return false;
	return calm::assist_cast_slow();
}
} // namespace nova::combat
