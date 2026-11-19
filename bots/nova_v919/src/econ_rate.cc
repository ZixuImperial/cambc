// econ_rate.cc: Rate of a group, part 3: bag and foe limits and the final rate_for.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void foe_arrival_refresh()
{
	if (gpv3_r == now())
		return;
	gpv3_r = now();
	gpv3_n = 0;
	gpv3_me = -1.0f; // read on first need
	gpv3_ss = -1.0f;
	gpv3_age = GPV_TAB[6];
	gpv3_st = static_cast<float>(GPV_TAB[8]) / 100.0f;
	gpv3_w = static_cast<float>(GPV_TAB[5]) / 100.0f;
	gpv3_e = std::clamp(static_cast<int>(GPV_TAB[9]), 1, 12);
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size() && gpv3_n < 8; ++i)
	{
		const auto& e = tt[i];
		if (!e.alive)
			continue; // dead: back no earlier than its respawn (first version: not counted)
		GpvFoe f;
		f.spawn = e.src == 4 || e.round < 0;
		f.pos = e.pos;
		f.age = e.round < 0 ? 1000 : now() - e.round;
		f.slack = 3;
		f.ti = static_cast<int>(i);
		gpv3_f[static_cast<std::size_t>(gpv3_n++)] = f;
	}
	std::stable_partition(gpv3_f.begin(), gpv3_f.begin() + gpv3_n, [](const GpvFoe& f) { return f.age <= gpv3_age; });
	gpv3_nf = 0;
	while (gpv3_nf < gpv3_n && gpv3_f[static_cast<std::size_t>(gpv3_nf)].age <= gpv3_age)
		++gpv3_nf;
}
float my_fight_strength()
{
	if (gpv3_me < 0.0f)
		gpv3_me = std::max(1.0f, combat::eff_hp(W.me) * combat::horizon_dps(W.me, true));
	return gpv3_me;
}
// A foe's strength, computed on first need this round (only foes that can arrive are read).
float foe_strength_lazy(GpvFoe& f)
{
	if (f.sok)
		return f.s;
	f.sok = true;
	const Body* b = intel::team_body(static_cast<std::size_t>(f.ti));
	const bool fgr = mu::bits != 0 && mu::on(mu::B_FGR); // The projection depends on now, so there is no round cache.
	GpvSc* sc = !fgr && f.ti >= 0 && f.ti < 8 ? &gpv3_sc[static_cast<std::size_t>(f.ti)] : nullptr;
	const int sr = now() - f.age;
	const bool healed = f.age > 15;
	if (sc && b && b->kit && sc->round == sr && sc->healed == healed)
	{
		f.s = sc->s;
		return f.s;
	}
	if (b && b->kit && !fgr && !healed)
	{
		const combat::Foe fo = combat::foe_of(*b, -1);
		f.s = std::max(1.0f, fo.ehp * fo.dps);
		if (sc)
		{
			sc->round = sr;
			sc->healed = healed;
			sc->s = f.s;
		}
	}
	else if (b && b->kit)
	{
		Body c = *b;
		if (fgr)
			intel::team_body_pred(static_cast<std::size_t>(f.ti), now(), c);
		if (healed)
		{
			c.hp = c.maxhp; // healed since
			c.shield = 0;
		}
		const combat::Foe fo = combat::foe_of(c, -1);
		f.s = std::max(1.0f, fo.ehp * fo.dps);
		if (sc)
		{
			sc->round = sr;
			sc->healed = healed;
			sc->s = f.s;
		}
	}
	else
		f.s = my_fight_strength(); // never read: as strong as I am
	return f.s;
}
// the rate factor for my trip to g with a crew of `crew` is faf_of(faf_F(g), crew) (callers test the group-value flag, self, opened).
// faf_F: the foes' arrival strength at g (arrival by distance, not by our finish time); the same value all round for one g.
static float faf_F_calc(const GroupI& g);
// FB5 FAF1: faf_F's value per group, stamped with the round (the inputs are per round: foe_arrival_refresh, foe_strength_lazy).
static std::vector<float> fb5_faf_v;
static std::vector<int> fb5_faf_r;
float faf_F(const GroupI& g)
{
	if (g.idx >= 0 && g.idx < M.ng)
	{
		const std::size_t gi = static_cast<std::size_t>(g.idx);
		if (fb5_faf_r.size() != static_cast<std::size_t>(M.ng))
		{
			fb5_faf_r.assign(static_cast<std::size_t>(M.ng), -1000);
			fb5_faf_v.assign(static_cast<std::size_t>(M.ng), 0.0f);
		}
		if (fb5_faf_r[gi] == now())
			return fb5_faf_v[gi];
		const float F = faf_F_calc(g);
		fb5_faf_r[gi] = now();
		fb5_faf_v[gi] = F;
		return F;
	}
	return faf_F_calc(g);
}
static float faf_F_calc(const GroupI& g)
{
	foe_arrival_refresh();
	float F = 0.0f;
	for (int j = 0; j < gpv3_nf; ++j)
	{
		GpvFoe& f = gpv3_f[static_cast<std::size_t>(j)];
		float p = 0.0f;
		{
			// Arrival during a clear is distance-first: <= 6 tiles .71-.78, 7-12 .11-.19, 13-20 .02-.04. Distance = an expected walk now
			// (sighting widened by half its age: an expected value, not the lower bound cheb - age, GR:157-161; spawn: d_enemy less its age).
			int a;
			if (f.spawn)
				a = g.d_enemy == UNREACH ? 1000 : static_cast<int>(g.d_enemy) - f.age;
			else
				a = cheb(f.pos, g.anchor) - f.age / 2 - (f.slack - 3);
			p = a <= 6 ? 0.75f : (a <= 12 ? 0.15f : (a <= 20 ? 0.03f : 0.0f));
		}
		if (p > 0.0f)
			F += p * foe_strength_lazy(f);
	}
	if (gpv3_nf < gpv3_n && g.contest > 0.30f)
	{
		if (gpv3_ss < 0.0f)
		{
			gpv3_ss = 0.0f;
			for (int j = gpv3_nf; j < gpv3_n; ++j)
				gpv3_ss += foe_strength_lazy(gpv3_f[static_cast<std::size_t>(j)]);
			gpv3_ss *= gpv3_st;
		}
		F += clampf((g.contest - 0.30f) / 0.40f, 0.0f, 1.0f) * gpv3_ss;
	}
	return F;
}
float faf_of(float F, int crew)
{
	if (F <= 0.0f)
		return 1.0f;
	if (crew >= 1 && crew <= 4) // FB5 FAF3: the last result per crew size for the same F and strength (same ops)
	{
		static float fb5_f[5] = { -1.0f, -1.0f, -1.0f, -1.0f, -1.0f }, fb5_m[5] = {}, fb5_out[5] = {};
		static int fb5_e[5] = {}, fb5_w[5] = {};
		const float ms = my_fight_strength();
		const std::size_t c = static_cast<std::size_t>(crew);
		const int wbits = __builtin_bit_cast(int, gpv3_w);
		if (fb5_f[c] == F && fb5_m[c] == ms && fb5_e[c] == gpv3_e && fb5_w[c] == wbits)
			return fb5_out[c];
		const float C = static_cast<float>(crew) * ms;
		const float fr = F / C;
		float fe = fr;
		for (int k = 1; k < gpv3_e; ++k)
			fe *= fr;
		const float risk = std::isinf(fe) ? 1.0f : fe / (fe + 1.0f);
		const float out = std::max(0.05f, 1.0f - gpv3_w * risk);
		fb5_f[c] = F;
		fb5_m[c] = ms;
		fb5_e[c] = gpv3_e;
		fb5_w[c] = wbits;
		fb5_out[c] = out;
		return out;
	}
	const float C = static_cast<float>(std::max(1, crew)) * my_fight_strength();
	// amendment: F/C > 2 is the deadly cell (crew deaths x7): risk = F^e / (F^e + C^e), e = [9] (0 reads as 2)
	const float fr = F / C;
	float fe = fr;
	for (int k = 1; k < gpv3_e; ++k)
		fe *= fr; // integer power, no std::pow
	const float risk = std::isinf(fe) ? 1.0f : fe / (fe + 1.0f); // BB8P: inf / inf is NaN
	return std::max(0.05f, 1.0f - gpv3_w * risk);
}
// v702 VTK (spec_vtk_1110.md): Vesper's take-over of a gold group her mates have cleared (bits 1/2) or are clearing (bit 4), rated as a
// capture-only trip; -1 when it does not apply (the usual rating runs). cap_rank and shards_of live in econ_capture.cc (same TU).
int cap_rank(int slot, const GroupI& g, float frac, float shards);
float shards_of(const Body& b);
static bool vtk_foe_near(vec2 a)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, a) <= 8)
			return true;
	for (const auto& s : nova::combat::seen)
		if (s.round != now() && now() - s.round <= 4 && cheb(s.foe.pos, a) <= 8)
			return true;
	return false;
}
// Does my capture rank beat every claimant mate (bit 4) or every mate standing on the region (bits 1/2)? Fills the holder's slot.
static bool vtk_outranks(int gi, const GroupI& g, bool on_region, int* holder)
{
	const int mine = cap_rank(P.my_slot, g, W.me.frac(), shards_of(W.me));
	*holder = -1;
	if (on_region)
	{
		for (const auto& a : W.allies)
		{
			if (a.slot < 0 || a.slot >= 32 || a.slot == P.my_slot)
				continue;
			bool on = false;
			for (int ci : g.members)
				on |= M.camps[static_cast<std::size_t>(ci)].pos == a.pos;
			if (!on)
				continue;
			if (g.gems > 0 && prism_layer::type(a.type))
				return false; // the team's gem carrier keeps a gem group
			const int theirs = cap_rank(a.slot, g, a.frac(), shards_of(a));
			if (theirs < mine || (theirs == mine && a.slot < P.my_slot))
				return false;
			if (*holder < 0)
				*holder = a.slot;
		}
		return *holder >= 0;
	}
	for (int s = 0; s < P.n && s < 8; ++s)
		if (s != P.my_slot && claims(s, gi))
		{
			if (*holder < 0)
				*holder = s;
			if (g.gems > 0 && prism_layer::kit(kit_of(P.type[static_cast<std::size_t>(s)])))
				return false;
			// VTKR1 (RC C45): compare my rank with each claimant's, as the on-region branch does; an unseen claimant keeps it
			const Body* b = W.ally_by_slot(s);
			if (!b)
				return false;
			const int theirs = cap_rank(s, g, b->frac(), shards_of(*b));
			if (theirs < mine || (theirs == mine && s < P.my_slot))
				return false;
		}
	return *holder >= 0;
}
// VTKG1 (RC C46; spec line 20): I am the only body hitting an awake attacker group (my engaged target) and no region tile of gi keeps
// one of its awake camps in my attack range: leaving would leave it on nobody.
static bool vtk_sole_hitter(int gi, const GroupI& g)
{
	if (T.target < 0 || T.target == gi || !T.engaged)
		return false;
	bool awake = false, other = false, kept = false;
	for (const auto& vc : W.camps)
	{
		if (!vc.awake || M.camps[static_cast<std::size_t>(vc.ci)].group != T.target)
			continue;
		const vec2 cp = M.camps[static_cast<std::size_t>(vc.ci)].pos;
		awake = true;
		for (const auto& a : W.allies)
			other |= cheb(a.pos, cp) <= a.range;
		for (int ci : g.members)
			kept |= cheb(M.camps[static_cast<std::size_t>(ci)].pos, cp) <= W.me.range;
	}
	return awake && !other && !kept;
}
static float vtk_take_rate(int gi, std::uint16_t trav, const Claims& cl, int* crew_out)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (g.gold <= 0 || trav == UNREACH || m.fail_until > now() || claimants(gi, my_slot(), cl) == 0)
		return -1;
	if (W.me.frac() < 0.6f || W.me.channeling() || (T.capturing && gi != T.target) || vtk_foe_near(g.anchor))
		return -1;
	if (vtk_sole_hitter(gi, g)) // VTKG1: never leave an awake attacker group I alone engage
		return -1;
	int holder = -1;
	float t = 0;
	if (m.status == GS_CLEARED)
	{
		cambc::detail::camp_group_capture_state cs{};
		if (cambc::detail::sdk_camp_group_capture_state(g.handle, &cs) != 0 || cs.state != 1)
			return -1; // not in sight, or no ally capture running
		if (static_cast<int>(trav) > cs.timer - 1)
			return -1; // on the region before the payment round
		if (!vtk_outranks(gi, g, true, &holder))
			return -1;
		t = static_cast<float>(cs.timer); // VBC 1 / b2392 VTW bit 2 VTKW2: payment comes at now + timer
	}
	else if (m.status == GS_ALIVE || m.status == GS_RESPAWN)
	{
		if (g.access != ACC_WALK || g.contest > 0.55f || siege_group(g) || sg_big(g))
			return -1; // join_gain's other filters
		const ClearEst e0 = estimate_cx(1, g, m, crew_of_claimants(gi, my_slot(), cl));
		if (!e0.feasible)
			return -1;
		const float wr = m.status == GS_RESPAWN ? static_cast<float>(std::max(0, m.respawn_at - now())) : 0.0f;
		const float clear = wr + e0.t;
		bool cap3 = prism::has_family(rs::F_CAPTURE); // VTKP1 (RC C45): an allied Capture holder on the crew caps the timer at 3 too (INT:108)
		for (int s = 0; s < P.n && s < 8 && !cap3; ++s)
			if (s != P.my_slot && claims(s, gi))
				if (const Body* b = W.ally_by_slot(s))
					cap3 = rs::has(rs::families(b->h, now()), rs::F_CAPTURE);
		const float pay = cap3 ? 3.0f : 5.0f;
		const float a = static_cast<float>(trav);
		if (a < clear || a > clear + pay - (0.0f)) // b2392 VTW bit 4 VTKW3: refuse only when a > clear + pay
			return -1; // the crew still clears when I arrive (join_gain's case), or it pays first
		if (!vtk_outranks(gi, g, false, &holder))
			return -1;
		t = clear + pay + (1.0f); // VBC 1 / b2392 VTW bit 1 VTKW1: the capture pays the round after (INT:109)
	}
	else
		return -1;
	const float mine = group_value(g, gi, my_slot());
	float v = mine;
	if (mine > 0.0f)
	{
		// MBB10 VTK2 (GR:196/207): allies on the region at payment split the reward, so the team gets her share x her multipliers plus
		// each mate's share x theirs, not her x1.33 on all of it. Mates: on a spawn tile of a captured group, else the crew claiming it.
		int k = 1;
		float vs = 0;
		if (m.status == GS_CLEARED)
		{
			for (const auto& a : W.allies)
			{
				if (a.slot < 0 || a.slot >= 32 || a.slot == P.my_slot)
					continue;
				bool on = false;
				for (int ci : g.members)
					on |= M.camps[static_cast<std::size_t>(ci)].pos == a.pos;
				if (on)
				{
					++k;
					vs += std::max(0.0f, group_value(g, gi, a.slot));
				}
			}
		}
		else
			for (int s = 0; s < P.n && s < 8; ++s)
				if (s != P.my_slot && claims(s, gi))
				{
					++k;
					vs += std::max(0.0f, group_value(g, gi, s));
				}
		v = (mine + vs) / static_cast<float>(k);
	}
	if (v <= 0.0f)
		return -1;
	if (crew_out)
		*crew_out = 1;
	const float vk = v; // VSP dose: VTK_K percent
	return vk / std::max(1.0f, t);
}
// v7xx MBB5 bit 4 WBW1, caller read the flag and holds a winning bag: group gi has a living monolith, golem or elk and no member is
// awake (seen awake now, or remembered awake): my hit would wake it (GR:192) beside the bank. True = do not rate it.
// Bit 8 WBW2 (Middle): any asleep group, heavy or not (all = true).
__attribute__((noinline)) bool wbw1_asleep_heavy(const GroupI& g, bool all)
{
	bool heavy = all;
	for (const int ci : g.members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (bbget(W.awake, c.pos) || mv::awake_known(ci))
			return false;
		heavy = heavy || ((c.type == cambc::camp_type::monolith || c.type == cambc::camp_type::golem || c.type == cambc::camp_type::elk) && !camp_known_dead(ci));
	}
	return heavy;
}
template <int DM>
float rate_for(int gi, int self, std::uint16_t trav, const Claims& cl, int max_extra, int* crew_out)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (self == my_slot() && W.tributed_us + static_cast<int>(W.me.gems) >= rs::WIN_TRIBUTE && (g.n_mono + g.n_golem + g.n_elk > 0) && wbw1_asleep_heavy(g, false))
		return -1; // v7xx MBB5 bits 4 WBW1 / 8 WBW2: a winning bag does not wake a heavy (bit 8: any) asleep group
	const auto& m = mem[static_cast<std::size_t>(gi)];
	RateJob j{ gi, self, trav, cl, max_extra, g, m, g.access != ACC_WALK };
	if (j.closed())
		return -1;
	if (j.respawn_too_late())
		return -1;
	if (self == my_slot() && opened && vesper_layer::me()) // v702 VTK: Vesper takes a mate's capture
	{
		int vtk_sh_crew = 0; // bit 16 SHADOW: the same work, no action (compute-only twin for the rare read)
		const float vr = vtk_take_rate(gi, trav, cl, crew_out);
		if (vr >= 0.0f)
			return vr;
	}
	if (j.claimed<DM>())
		return -1;
	j.size_crew();
	j.recruit();
	j.chip_trip();
	if (j.no_crew())
		return -1;
	if (j.crew_floor())
		return -1;
	j.crew_walk();
	j.time_and_value();
	j.penalties<DM>();
	j.crew_term<DM>();
	if (j.late_factors())
		return -1;
	if (willow_layer::type(W.me.type) && self == my_slot() && !support::wmc_mate_group(gi))
		return -1; // b2433 WMC bit 1: no lone farming
	if (willow_layer::type(W.me.type) && self == my_slot())
		return support::wl2_pull(gi, j.publish(crew_out)); // WL2 decision 3
	const float jr = j.publish(crew_out);
	return jr;
}
// KCV 8 TCB1: Crew::add's body, always inline, for the team crew build (HE false: KCV 16 TCB2, budget_he not kept).
template <bool HE>
__attribute__((always_inline)) inline void tcb_add(Crew& c, const Member& x)
{
	c.dps1 += x.dps1;
	c.dps3 += x.dps3;
	c.stuns8 += x.stuns;
	c.ko1_area8 += x.ko1_area;
	c.ko1_land8 += x.ko1_land;
	c.ko1_cc8 += x.ko1_cc;
	c.ko1_ccp8 += x.ko1_ccp;
	if (c.n == 0)
		c.heal_first = x.heal;
	else
	{
		c.heal8 += x.heal + c.heal_first;
		c.heal_first = 0;
	}
	if (c.n == 0)
		c.shield8 += x.shield;
	if (c.n == 0)
		c.ret_tank += x.ret;
	else if (x.melee)
		c.ret_hold += x.ret;
	if (x.chain > c.chain)
	{
		c.chain = x.chain;
		c.chain_dps1 = x.dps1;
	}
	if ((x.melee || c.n == 0) && c.n_melee < 6)
	{
		int i = c.n_melee++;
		while (i > 0 && c.budget[static_cast<std::size_t>(i - 1)] < x.budget)
		{
			c.budget[static_cast<std::size_t>(i)] = c.budget[static_cast<std::size_t>(i - 1)];
			if (HE)
				c.budget_he[static_cast<std::size_t>(i)] = c.budget_he[static_cast<std::size_t>(i - 1)];
			--i;
		}
		c.budget[static_cast<std::size_t>(i)] = x.budget;
		if (HE)
			c.budget_he[static_cast<std::size_t>(i)] = x.budget_he;
	}
	++c.n;
}
// KCV 32 TFE1: estimate()'s feasible answer only (econ_clear_estimate.cc estimate, same floats in the same order); e.t and the Vendetta
// chain block are computed only inside the multi-trip branch, their one reader.
__attribute__((always_inline)) inline bool tfe_feasible(const GroupI& g, const GroupMem& m, const Crew& c)
{
	if (m.status == GS_CLEARED)
		return true;
	const float scale = (m.status == GS_ALIVE && m.hp_left >= 0) ? clampf(m.hp_left / std::max(1.0f, g.hp), 0.02f, 1.0f) : 1.0f;
	float dps = c.dps(g.pack) * 0.85f;
	if (!g.att.empty() && (c.ret_tank > 0 || c.ret_hold > 0))
	{
		const int n_att = static_cast<int>(g.att.size());
		const int held = std::min(n_att - 1, std::max(0, c.n_melee - 1));
		dps += 0.6f * (c.ret_tank * static_cast<float>(n_att - held) + (n_att >= 2 ? c.ret_hold : 0.0f));
	}
	dps = std::max(10.0f, dps);
	float tc = 0, dmg = 0;
	int n_att = static_cast<int>(g.att.size());
	if (!g.att.empty() && m.status == GS_ALIVE && m.hp_left >= 0 && static_cast<std::size_t>(g.idx) < bgx_gn.size() && bgx_gn[static_cast<std::size_t>(g.idx)] >= 0)
	{
		const std::size_t bgx_gi = static_cast<std::size_t>(g.idx);
		tc = bgx_s1[bgx_gi] / dps;
		dmg = bgx_s2[bgx_gi] / dps;
		n_att = bgx_gn[bgx_gi];
	}
	else
	{
		tc = 0;
		dmg = 0;
		for (const auto& a : g.att)
		{
			tc += a.first * scale / dps;
			dmg += a.second * tc;
		}
	}
	if (n_att > 0)
	{
		const float swg_d = swg_rim_dmg(g, c, tc); // v8xx SWG bit 1: as estimate()
		if (swg_d >= 0.0f)
			dmg = swg_d;
	}
	if (n_att > 0)
	{
		if (ko1_any(c))
		{
			float ko1_st8 = 0;
			const float ko1_x = stun_soak_cancel(c, g, &ko1_st8);
			dmg -= (std::min(1.0f, ko1_st8 / static_cast<float>(rs::slot_cooldown())) * g.str_max + ko1_x) * tc;
		}
		else
			dmg -= std::min(1.0f, c.stuns8 / static_cast<float>(rs::slot_cooldown())) * tc * g.str_max;
		dmg -= (c.heal8 + c.shield8) / static_cast<float>(rs::slot_cooldown()) * tc;
	}
	float e_dmg = std::max(0.0f, dmg);
	if (g.n_mono + g.n_golem > 0 && g.contest <= 0.45f)
		e_dmg *= static_cast<float>(HVY_TAB[2]) / 100.0f;
	if (SHV_ON(1) && e_dmg > 0.0f && shv_crew_reach(g, c.n, c.n_melee, c.budget[0] / 3.0f)) // the whole-team crew's budgets are x3
		e_dmg = 0.0f; // b2429 SHV bit 1: as estimate()
	const int he_m = HE_TAB[1];
	const bool xic_hcx = XIC_ON(16384);
	const int he = xic_hcx ? 0 : ((n_att > 0 && he_group(g)) ? he_m : 0);
	const auto& cb = (he & 1) ? c.budget_he : c.budget;
	float budget = c.n_melee > 0 ? cb[0] : 0.0f;
	if (n_att >= 2)
		for (int i = 1; i < std::min(n_att, c.n_melee); ++i)
			budget += 0.85f * cb[static_cast<std::size_t>(i)];
	else if (n_att == 1 && c.n_melee >= 2)
	{
		const float w = g.str_max >= 100.0f ? 0.8f : 0.6f;
		const int k = g.str_max >= 100.0f ? c.n_melee : 2;
		for (int i = 1; i < k; ++i)
			budget += w * cb[static_cast<std::size_t>(i)];
	}
	if (c.n >= 2)
		budget *= 1.0f + CREW_RESV * crew_group_k(g);
	bool feasible = n_att == 0 || e_dmg <= budget;
	if ((XIC_ON(16384) ? (!feasible && budget > 0.0f && n_att > 0 && (he_group(g) || swg_pack(g))) : ((he & 2) && !feasible && budget > 0.0f)) && heavy_multi_trip_ok(g, m))
	{
		float e_t = g.hp * scale / dps + 0.4f * static_cast<float>(static_cast<std::size_t>(g.nm));
		if (c.chain > 0 && g.n_att == 0 && !g.members.empty())
		{
			const float hm = g.hp / static_cast<float>(static_cast<std::size_t>(g.nm));
			const float kpt = c.chain >= hm ? 2.0f : (2.0f * c.chain >= hm ? 1.0f : 0.0f);
			if (kpt > 0)
			{
				const float others = std::max(0.0f, dps - 0.85f * c.chain_dps1);
				const float rate = kpt + others / std::max(1.0f, hm);
				const float tcc = static_cast<float>(static_cast<std::size_t>(g.nm)) * scale / rate + 0.4f * static_cast<float>(static_cast<std::size_t>(g.nm));
				e_t = std::min(e_t, tcc);
			}
		}
		const int tmax = OP_PLAY != 0 ? 1 : HE_TAB[2];
		const float cyc = 5.0f + static_cast<float>(g.d_home) + 2.0f;
		const float tr = e_dmg <= budget * static_cast<float>(tmax) ? std::ceil(e_dmg / budget) : 1e9f;
		const float t2 = e_t + (tr - 1.0f) * cyc;
		if (tr <= static_cast<float>(tmax) && static_cast<float>(now()) + t2 + 40.0f <= GAME_END_F)
			feasible = true;
	}
	return feasible;
}
// KCV 2 EWM1: single-camp lone-attacker groups (no heavy term, no he_group) with equal estimate fields share one class (at most 4); at
// scale 1 with no cc stun and no crew-mode term, estimate() reads only the class fields and the crew, fixed per crew_epoch.
std::vector<std::int8_t> ewm_cls;
int ewm_cls_ng = -1;
__attribute__((noinline)) void ewm_build_classes()
{
	ewm_cls.assign(static_cast<std::size_t>(M.ng), -1);
	ewm_cls_ng = M.ng;
	int rep[4] = { -1, -1, -1, -1 };
	int nr = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const GroupI& g = M.groups[static_cast<std::size_t>(gi)];
		if (g.nm != 1 || g.members.size() != 1 || g.n_att != 1 || g.att.size() != 1 || g.n_mono + g.n_golem > 0 || he_group(g))
			continue;
		int k = -1;
		for (int r = 0; r < nr && k < 0; ++r)
		{
			const GroupI& h = M.groups[static_cast<std::size_t>(rep[r])];
			if (h.hp == g.hp && h.str_max == g.str_max && h.pack == g.pack && h.gems == g.gems && h.n_clu == g.n_clu && h.n_elk == g.n_elk &&
				h.att[0].first == g.att[0].first && h.att[0].second == g.att[0].second)
				k = r;
		}
		if (k < 0 && nr < 4)
		{
			k = nr;
			rep[nr++] = gi;
		}
		ewm_cls[static_cast<std::size_t>(gi)] = static_cast<std::int8_t>(k);
	}
}
// team_feasible's refresh of entry i
void team_feasible_refresh(std::size_t i)
{
	++tf_est_n;
	team_ok_round[i] = now();
	const auto& g = M.groups[i];
	if (g.n_att == 0)
		team_ok[i] = 1;
	else
	{
		// Hopeless only: camp damage above three times the whole team's HP budget (current HP varies; bodies heal before they engage, so
		// borderline groups stay candidates and rate_for judges them). The whole-team crew is built once per build of the team view.
		static Crew c;
		static int c_epoch = -1;
		if (c_epoch != crew_epoch)
		{
			c_epoch = crew_epoch;
			c = Crew{};
			for (int k = 0; k < TM.n; ++k)
				tcb_add<false>(c, ECX_TM(static_cast<std::size_t>(TM.by_tank[static_cast<std::size_t>(k)])));
			for (auto& b : c.budget)
				b *= 3.0f;
		}
		if (M.done()) // KCV 2 EWM1: one estimate per class and crew build
		{
			if (ewm_cls_ng != M.ng)
				ewm_build_classes();
			const int k = ewm_cls[i];
			const GroupMem& m = mem[i];
			if (k >= 0 && m.status != GS_CLEARED && !(m.status == GS_ALIVE && m.hp_left >= 0) && (c.n <= 1 || crew_k <= 0 || now() >= CREW_R))
			{
				static int ewm_ep[4] = { -1, -1, -1, -1 };
				static std::int8_t ewm_v[4] = {};
				if (ewm_ep[k] != crew_epoch)
				{
					ewm_ep[k] = crew_epoch;
					ewm_v[k] = (tfe_feasible(g, m, c)) ? 1 : 0;
				}
				team_ok[i] = ewm_v[k];
				return;
			}
		}
		team_ok[i] = tfe_feasible(g, mem[i], c) ? 1 : 0;
		return;
	}
}
bool team_feasible(int gi)
{
	if (team_ok.size() != static_cast<std::size_t>(M.ng))
	{
		team_ok.assign(static_cast<std::size_t>(M.ng), 1);
		team_ok_round.assign(static_cast<std::size_t>(M.ng), -1000);
	}
	const auto i = static_cast<std::size_t>(gi);
	if (TM.n <= 0)
		return true;
	// At most 4 fresh estimates per turn, with fuel to spare; a stale entry keeps its value (unknown counts as
	// feasible).
	if (tf_est_round != now())
	{
		tf_est_round = now();
		tf_est_n = 0;
	}
	if (now() - team_ok_round[i] >= 25 && tf_est_n < 4 && (fuel() > 60000))
		team_feasible_refresh(i);
	return team_ok[i] != 0;
}
// Hold a capture in our territory past capture()'s 16-round limit, up to TERR_HOLD more rounds, while I stand on its region above
// 40% health: a contested timer restarts, and stepping off hands the payout to them.
bool territory_hold(const GroupI& g, int gi)
{
	if (!opened || g.contest > TERR_OWN || now() - T.cap_start > 16 + TERR_HOLD || W.me.frac() < 0.4f)
		return false;
	for (int ci : g.members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == W.me.pos)
		{
			(void)gi;
			return true;
		}
	return false;
}
} // namespace
} // namespace nova::econ
