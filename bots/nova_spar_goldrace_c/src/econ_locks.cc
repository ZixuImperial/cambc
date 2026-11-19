// econ_locks.cc: Altar locks: hitting, reading and watching them.
#include "econ_internal.h"
namespace nova::econ {
// inlined: the first early-out test runs at the call site, the rest out of line
__attribute__((always_inline)) bool hit_claimed_camp_in_range()
{
	if (W.attacked || !W.alive || !W.me.kit || W.me.channeling() || (W.me.kit->ranged && W.moved) || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	return hit_claimed_camp_in_range_slow();
}
__attribute__((noinline)) bool hit_claimed_camp_in_range_slow()
{
	if (W.attacked || !W.alive || !W.me.kit || W.me.channeling() || (W.me.kit->ranged && W.moved) || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	const int r = std::max(1, W.me.range);
	int best = -1;
	float best_hp = 1e9f;
	for (const auto& vc : W.camps)
	{
		if (vc.ci < 0 || vc.ci >= M.nc || vc.hp <= 0.0f)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cheb(c.pos, W.me.pos) > r || c.group < 0 || c.group >= M.ng)
			continue;
		if (FB6_ON(16) && !(vc.hp < best_hp))
			continue; // FB6 RO5: no lower HP, nothing to test
		if (W.cast && !camp_alive_now(vc.ci)) // my own cast this turn killed it
			continue;
		if (varg_layer::prestep_splash() && !combat::prestep_splash_ok(vc.ci))
			continue; // FAC bit 512 VMR2: Varg's splash would wake a sleeping attacker group
		const auto& g = M.groups[static_cast<std::size_t>(c.group)];
		if ((g.n_att != 0 || c.attacks()) && !(PAW_ON && vc.awake && !varg_layer::paw_splash()))
			continue; // an awake camp is free to hit
		bool ours = c.group == T.target;
		for (int s = 0; !ours && s < TM.n; ++s)
			ours = claims(s, c.group);
		if (!ours)
			continue;
		if (vc.hp < best_hp)
		{
			best_hp = vc.hp;
			best = vc.ci;
		}
	}
	if (best < 0)
		return false;
	refresh_self();
	if (!W.can_attack() || W.me.channeling())
		return false;
	if ((M.groups[static_cast<std::size_t>(M.camps[static_cast<std::size_t>(best)].group)].n_att != 0))
		return combat::camp_hit_plain(best); // her kill refunds
	if (vendetta_layer::camp_kill_reset(*W.me.kit))
		return combat::hit_camp(best); // Vendetta: a kill refunds the reset (and the dash)
	return combat::attack_camp(best);
}
// the enemy team's lock on the altar, read directly (altar_lock_at prefers ours when both stand).
static bool enemy_altar_lock_direct(vec2 altar, cambc::detail::altar_lock_info& out)
{
	out = cambc::detail::altar_lock_info{};
	cancel_spin_before_action();
	return cambc::detail::sdk_altar_lock(altar.x, altar.y, cambc::detail::absolute_team(cambc::team::enemy), &out) == 0;
}
// the enemy team's lock on `altar`, read directly (altar_lock_at prefers ours when both stand).
bool enemy_lock_on(vec2 altar)
{
	cambc::detail::altar_lock_info i{};
	return enemy_altar_lock_direct(altar, i);
}
// v683 LKR bit 1 (called with the flag read first): a ranged body that walked resets its attack for the lock hit (quiet rule).
static bool lkr_reset_after_walk()
{
	if (!W.me.kit || !W.me.kit->ranged || !W.moved || W.attacked || W.cast || W.me.channeling() || W.me.kit->slot_reset < 0)
		return false;
	if (W.me.gems < 30u || !combat::ready(W.me.kit->slot_reset))
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8)
			return false;
	if (!combat::cast_self(W.me.kit->slot_reset))
		return false;
	refresh_self();
	return W.can_attack();
}
// inlined: the first early-out test runs at the call site, the rest out of line
__attribute__((always_inline)) bool lock_hit(bool refresh)
{
	if (W.attacked || !W.alive || !M.has_altar)
		return false;
	return lock_hit_slow(refresh);
}
__attribute__((noinline)) bool lock_hit_slow(bool refresh)
{
	if (W.attacked || !W.alive || !M.has_altar)
		return false;
	const int r = std::max(1, W.me.range);
	const PosSoA& alw = altar_soa(); // the altars within r, 8 at a time, in list order
	for (std::size_t alw_k = 0; alw_k < alw.n; alw_k += 8)
	for (unsigned alw_m = pos_within_r_mask(alw, alw_k, W.me.pos, r); alw_m != 0; alw_m &= alw_m - 1)
	{
		const auto& a = M.altars[alw_k + static_cast<std::size_t>(__builtin_ctz(alw_m))];
		try
		{
			if (!cambc::vision::has_altar_lock(a.pos))
				continue;
			const auto lock = cambc::vision::altar_lock_at(a.pos);
			if (!lock.is_enemy())
			{
				cambc::detail::altar_lock_info lb{};
				if (!enemy_altar_lock_direct(a.pos, lb))
					continue;
				// ours and theirs both stand: hit theirs
				if (refresh)
					refresh_self();
				if (lkr_reset_after_walk())
				{
					cambc::self().attack(cambc::altar_lock{ lb });
					W.attacked = true;
					return true; // v683 LKR bit 1
				}
				if (!W.can_attack() || W.me.channeling() || (W.me.kit->ranged && W.moved))
					return false;
				cancel_spin_before_action();
				cambc::self().attack(cambc::altar_lock{ lb });
				W.attacked = true;
				return true;
			}
			if (refresh)
				refresh_self();
			if (lkr_reset_after_walk())
			{
				cambc::self().attack(lock);
				W.attacked = true;
				return true; // v683 LKR bit 1
			}
			if (!W.can_attack() || W.me.channeling() || (W.me.kit->ranged && W.moved))
				return false;
			cancel_spin_before_action();
			cambc::self().attack(lock);
			W.attacked = true;
			if (((lock.hits_remaining() > 2 && W.me.gems >= 30u)) && W.me.kit->slot_reset >= 0 && !W.cast && combat::ready(W.me.kit->slot_reset))
			{
				bool quiet = true;
				for (const auto& e : W.enemies)
					quiet = quiet && cheb(e.pos, W.me.pos) > 8;
				if (quiet && combat::cast_self(W.me.kit->slot_reset))
				{
					if (!(lock.hits_remaining() > 2 && W.me.gems >= 30u))
						EBK_FIRE(2);
					refresh_self();
					if (W.can_attack())
						cambc::self().attack(lock);
				}
			}
			return true;
		}
		catch (...)
		{
			FXR_PASS();
			return false;
		}
	}
	return false;
}
void drop_stalled_target()
{
	if (T.target < 0 || T.target >= M.ng)
	{
		sd_n = 0;
		return;
	}
	const int gi = T.target;
	const GroupMem& m = mem[static_cast<std::size_t>(gi)];
	const float hv = m.hp_left < 0 ? 1e9f : m.hp_left; // -1 = full
	bool foe = false;
	for (const auto& e : W.enemies)
		foe |= cheb(e.pos, W.me.pos) <= 8;
	const bool same = sd_gi == gi && now() - sd_last <= 3;
	const bool rose = hv > sd_hp; // camps never regenerate, so a rise is a new run (respawn)
	const bool prog = !same || foe || W.me.channeling() || T.capturing || hv < sd_hp || T.progress != sd_prog || m.respawn_at > now() || rose;
	if (!same || hv < sd_hp || rose)
		sd_hp = hv; // the lowest seen HP of the group in this run
	sd_gi = gi;
	sd_last = now();
	sd_prog = T.progress;
	if (prog)
	{
		sd_n = 0;
		return;
	}
	if (++sd_n < SD_TURNS)
		return;
	NLOG("r%d slot %d STALL_DROP %d after %d calm turns\n", now(), P.my_slot, gi, sd_n);
	sd_n = 0;
	drop_target(SD_FAIL);
}
} // namespace nova::econ
