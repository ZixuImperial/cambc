// econ_altar_hold.cc: Holding an altar against foes.
#include "econ_internal.h"
namespace nova::econ {
// The lead-hold test. Known enemy bags are the team table's last-seen bag of each living enemy (a bag tributed since then is counted
// twice, so the rule holds more, never less). A known enemy bag that ends the game turns the hold off, since the bodies must be free
// to act. Callers check the hold switch first.
// v699 R2E bit 1 EH1 (C30): can any known foe kill me and bank my bag by round 2000? Lower bound per foe: the approach to within 5
// (a kill takes the bag from up to 5 tiles, GR:375) at 2 tiles a round (dash), or its own walk to its nearest altar less 6 (any altar
// banks, GR:226), whichever is longer, then the channel with a Tribute emblem.
static bool eh1_foe_can_land(int gems)
{
	int best = BIG;
	const auto one = [&](const Body& e) {
		const int dn = cheb(e.pos, W.me.pos);
		int da = 0;
		if (M.any_altar)
		{
			const std::uint16_t d = field_here(M.f_altar, e.pos); // KTF1: a foe on a camp tile
			da = d == UNREACH ? 0 : static_cast<int>(d);
		}
		best = std::min(best, std::max((std::max(0, dn - 5) + 1) / 2, std::max(0, da - 6)));
	};
	for (const auto& e : W.enemies)
		one(e);
	for (const auto& e : W.enemies_far)
		one(e);
	const int ds = combat::nearest_foe_distance_seen(PC_KNOWN_AGE);
	if (ds < static_cast<int>(BIG))
		best = std::min(best, (std::max(0, ds - 5) + 1) / 2);
	if (best >= static_cast<int>(BIG))
		return false;
	return now() + best + rs::tribute_turns(gems, true) <= GAME_END;
}
bool end_hold_blocks_bank(int gems)
{
	if (gems <= 0 || W.tributed_us <= W.tributed_them || !M.has_altar)
		return false;
	if (W.tributed_us + gems >= rs::WIN_TRIBUTE)
	{
		const std::uint16_t d = bank_dist_here();
		if (winning_bag_walk_safe(d == UNREACH ? 0 : static_cast<int>(d), rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE))))
			return false; // a winning bag that can complete is never held
	}
	if (W.tributed_us + gems >= rs::WIN_TRIBUTE && bb29_not_prism())
	{
		bb29_fc_eg3(); // v663 BB29 EG3: a non-Prism winning bag is never held (bank_winning_bag's guards decide)
		return false;
	}
	if (rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE)) <= END_HOLD_TAB[3])
		return false;
	long mine = gems; // my bag as theirs (a kill takes it)
	if (!eh1_foe_can_land(gems)) // v699 R2E bit 1 EH1 (C30): no killer could bank my bag by round 2000
		mine = 0;
	long them = static_cast<long>(W.tributed_them) + mine;
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size(); ++i)
	{
		if (!tt[i].alive || tt[i].round <= -1000)
			continue;
		const Body* b = intel::team_body(i);
		if (!b)
			continue;
		if (static_cast<long>(W.tributed_them) + static_cast<long>(b->gems) >= rs::WIN_TRIBUTE)
			return false; // an enemy bag ends the game: banking/denying is the question, not the hold
		them += static_cast<long>(b->gems);
	}
	// their projected gain from banking over the rounds left (50-round samples, rate over >= 200 rounds)
	{
		const std::array<int, 3>* old = nullptr;
		for (const auto& h : eg_hist)
			if (now() - h[0] >= 200)
				old = &h;
		if (old && now() > (*old)[0])
			them += static_cast<long>(W.tributed_them - (*old)[2]) * static_cast<long>(GAME_END - now()) * END_HOLD_TAB[4] / (100L * (now() - (*old)[0]));
	}
	if (them - mine >= static_cast<long>(W.tributed_us)) // v699 R2E bit 1 EH1
		return false; // no real lead: they reach us without my bag (the race rules bank it)
	if (them + std::min(static_cast<long>(END_HOLD_TAB[5]), static_cast<long>(END_HOLD_TAB[5]) * std::max(0, GAME_END - now()) / std::max(1, GAME_END - END_HOLD_TAB[1])) < static_cast<long>(W.tributed_us)) // v699 R2E bit 1 EH1: EH_SLACK scales to the rounds left
		return false; // losing my bag cannot flip the lead (with EH_SLACK gems they may still capture)
	const int r = END_HOLD_TAB[2] + (now() - eh_last <= 5 ? 2 : 0);
	return prism::nearest_known_enemy() <= r;
}
namespace {
// v683 ALZ bit 1 (called with the flag read first): one lazily built field per altar entry.
std::vector<std::unique_ptr<distance_field>> alz_f; // built on first use only
const distance_field* alz_field(int ai)
{
	if (ai < 0 || ai >= M.na)
		return nullptr;
	if (alz_f.size() != static_cast<std::size_t>(M.na))
		alz_f.resize(static_cast<std::size_t>(M.na));
	const std::size_t i = static_cast<std::size_t>(ai);
	if (alz_f[i])
		return alz_f[i].get();
	if (fuel() < 3L * M.w * M.h + 4000 + 30000)
		return nullptr;
	bitboard roots{};
	const vec2 ap = M.altars[i].pos;
	bool any = false;
	bbforeach(M.altar_adj,
		[&](vec2 p)
		{
			if (cheb(p, ap) <= 1)
			{
				bbset(roots, p);
				any = true;
			}
		});
	if (!any)
		return nullptr;
	bitboard visited{};
	auto nf = std::make_unique<distance_field>();
	nf->compute(M.block_camps, roots, visited);
	alz_f[i] = std::move(nf);
	return alz_f[i].get();
}
const distance_field* altar_hold_field(int ai)
{
	return alz_field(ai); // v683 ALZ bit 1
}
} // namespace
static int alh_maxbag = 0; // ALC32: the largest live row bag (written only under ALC_ON(32))
void altar_hold_note()
{
	if (!alh_init)
	{
		alh_init = true;
		for (int i = 0; i < ALH_MAXF; ++i)
			alh_round[i] = -1000;
	}
	const auto& tt = intel::team_table();
	static std::uint32_t alhv_v = 0;
	static std::size_t alhv_n = static_cast<std::size_t>(-1);
	if (alhv_v == intel::team_ver() && alhv_n == tt.size())
		return;
	alhv_v = intel::team_ver();
	alhv_n = tt.size();
	for (std::size_t i = 0; i < tt.size() && i < ALH_MAXF; ++i)
	{
		const int rr = tt[i].round; // the row's last update (a mate's EV_SIGHT refreshes it too; BB8 bit 128 not shipped)
		if (rr != alh_round[i])
		{
			alh_round[i] = rr;
			alh_tt[i] = W.tributed_them;
		}
	}
	int mb = 0;
	for (std::size_t i = 0; i < tt.size() && i < ALH_MAXF; ++i)
		if (tt[i].alive && tt[i].round > -1000 && tt[i].src != 4)
			if (const Body* b = intel::team_body(i))
				mb = std::max(mb, static_cast<int>(b->gems));
	alh_maxbag = mb;
}
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
__attribute__((always_inline)) bool altar_hold_turn()
{
	if (W.tributed_them + (alh_maxbag) < rs::WIN_TRIBUTE) // ALC32: the floor is the largest known bag
		return false;
	return altar_hold_turn_slow();
}
__attribute__((noinline)) bool altar_hold_turn_slow()
{
	if (W.tributed_them + (alh_maxbag) < rs::WIN_TRIBUTE) // ALC32: the floor is the largest known bag
		return false;
	if (!W.alive || W.me.channeling() || !M.ready() || M.altars.empty() || W.me.stunned)
		return false;
	const int need = rs::WIN_TRIBUTE - W.tributed_them;
	if (need <= 0)
		return false;
	// known finishing bags
	struct Fin { vec2 pos; int age; int ticks; bool immune; };
	Fin fins[ALH_MAXF];
	int alc2rv[ALH_MAXF]; // ALC2: a seen channel's time left per fin (read only under ALC_ON(2))
	int nf = 0;
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size() && i < ALH_MAXF; ++i)
	{
		if (!tt[i].alive || tt[i].round <= -1000 || tt[i].src == 4)
			continue;
		const Body* b = intel::team_body(i);
		if (!b || b->gems == 0)
			continue;
		const int g = static_cast<int>(b->gems);
		const int age = W.round - (tt[i].round); // age of the row's last update
		const int ticks = rs::tribute_turns_of(g, b->h, now()); // the foe's emblem
		KIT_RULE_FIX_CNT(7, ticks != rs::tribute_turns(g, false));
		if (W.tributed_them != alh_tt[i] && age >= ticks && !(bb29_not_prism() && bb29_rise_short(alh_tt[i], g))) // v678 FX7 bit 64: EG1 not for the Prism
			continue; // they banked since: it may be this bag (v663 BB29 EG1: only if the rise covers it)
		if (g >= need && nf < ALH_MAXF)
			fins[nf++] = Fin{ tt[i].pos, age, ticks, marcella_layer::fight_stun_wasted(*b) };
	}
	if (nf == 0)
		return false;
	bool all_immune = true;
	for (int i = 0; i < nf; ++i)
		all_immune = all_immune && fins[i].immune;
	const auto has_tool = [&](const Body& u, bool self)
	{
		if (u.kit && !all_immune && (u.kit->slot_cc >= 0 || u.kit->aoe_stun || u.kit->dash_stun))
			return true;
		if (self)
			return combat::alh_locks() > 0;
		std::array<std::uint32_t, 4> c{};
		return cambc::detail::sdk_champion_consumables(u.h, c.data()) == 0 && c[2] > 0;
	};
	if (!has_tool(W.me, true))
		return false;
	// altars: the ALH_MAXA nearest the first carrier by Chebyshev, soonest finish first
	int ai[ALH_MAXA], eta[ALH_MAXA], na = 0;
	{
		int order[ALH_MAXA];
		int od[ALH_MAXA];
		int n = 0;
		for (int i = 0; i < M.na; ++i)
		{
			const int d = cheb(M.altars[static_cast<std::size_t>(i)].pos, fins[0].pos);
			int k = n < ALH_MAXA ? n : ALH_MAXA;
			while (k > 0 && od[k - 1] > d)
				--k;
			if (k >= ALH_MAXA)
				continue;
			for (int j = (n < ALH_MAXA ? n : ALH_MAXA - 1); j > k; --j)
			{
				od[j] = od[j - 1];
				order[j] = order[j - 1];
			}
			od[k] = d;
			order[k] = i;
			if (n < ALH_MAXA)
				++n;
		}
		for (int i = 0; i < n; ++i)
		{
			const distance_field* f = altar_hold_field(order[i]);
			if (!f)
				continue;
			int best = 100000;
			for (int q = 0; q < nf; ++q)
			{
				std::uint16_t d = dfget(*f, fins[q].pos); // v695 AHX bit 1
				if (d == UNREACH)
					continue;
				const int arr = std::max(0, static_cast<int>(d) - fins[q].age);
				const int alc2r = -1; // ALC2 (RC C815 A1): only at an altar she can be channelling at
				if (bb29_not_prism() && now() + (alc2r >= 0 ? alc2r : arr + fins[q].ticks) > GAME_END) // v678 FX7 bit 64: EG2 not for the Prism; ALC2: a seen channel's time left
				{
					bb29_fc_eg2(); // v663 BB29 EG2: that bag cannot land by the game end
					continue;
				}
				best = alc2r >= 0 ? std::min(best, alc2r) : std::min(best, arr + fins[q].ticks); // ALC1 (RC C748): the walk the carrier has had also counts against the channel
			}
			if (best >= 100000)
				continue;
			int k = na;
			while (k > 0 && eta[k - 1] > best)
				--k;
			for (int j = na; j > k; --j)
			{
				eta[j] = eta[j - 1];
				ai[j] = ai[j - 1];
			}
			eta[k] = best;
			ai[k] = order[i];
			++na;
		}
	}
	if (na == 0)
		return false;
	// one body per altar: the strongest that can make it, else the nearest; visible mates only
	const Body* cand[9];
	int nc = 0;
	cand[nc++] = &W.me;
	for (const auto& al : W.allies)
		if (nc < 9 && !al.channeling() && has_tool(al, false))
			cand[nc++] = &al;
	bool used[9] = {};
	int mine = -1;
	for (int k = 0; k < na && mine < 0; ++k)
	{
		const distance_field* f = altar_hold_field(ai[k]);
		if (!f)
			continue;
		int pick = -1;
		float bs = -1.0f;
		for (int c = 0; c < nc; ++c)
		{
			if (used[c])
				continue;
			std::uint16_t d = dfget(*f, cand[c]->pos); // v695 AHX bit 1
			if (d == UNREACH)
				continue;
			const bool in_time = std::max(0, static_cast<int>(d) - 1) + 1 <= eta[k];
			const float sc = (in_time ? 1000000000.0f : 0.0f) + (in_time ? cand[c]->hp * std::max(cand[c]->str, cand[c]->foc) : 100000.0f - static_cast<float>(d));
			if (sc > bs)
			{
				bs = sc;
				pick = c;
			}
		}
		if (pick < 0)
			continue;
		used[pick] = true;
		if (pick == 0)
			mine = k;
	}
	if (mine < 0)
		return false;
	const distance_field* f = altar_hold_field(ai[mine]);
	std::uint16_t dme = f ? (dfget_me(*f)) : UNREACH; // v695 AHX bit 1
	if (dme == UNREACH)
		return false;
	const int slack = eta[mine] - (std::max(0, static_cast<int>(dme) - 1) + 1);
	if (alp_probe)
	{
		alp_slack = slack; // probe: report and stop, no side effects
		alp_eta = eta[mine];
		alp_ai = ai[mine];
		return true;
	}
	const int bar = ALH_TAB[2] + ((alh_last_a == ai[mine] && W.round - alh_last_r <= 2) ? 2 : 0);
	if (slack > bar)
		return false;
	if (slack < 0 && cheb(W.me.pos, M.altars[static_cast<std::size_t>(ai[mine])].pos) > 2)
		return false; // no body arrives in time: the walk cannot help
	if (want_bank())
		return false; // never over a bank walk: blocking them loses
	const vec2 ap = M.altars[static_cast<std::size_t>(ai[mine])].pos;
	if (cheb(W.me.pos, ap) > 2 && dme > 0 && !mv::step_field(*f))
		return false; // X02 bit 2: the hold's step failed: the turn is not claimed
	alh_last_a = ai[mine];
	alh_last_r = W.round;
	last_act = ACT_WALK;
	return true;
}
// The hold's own altar picks from current positions, then the pin tests.
bool altar_hold_pinned(bool recall)
{
	if (W.tributed_them + (alh_maxbag) < rs::WIN_TRIBUTE) // ALC32: the floor is the largest known bag
		return false;
	alp_probe = 1;
	alp_ai = -1;
	const bool hold = altar_hold_turn_slow();
	alp_probe = 0;
	if (!hold || alp_ai < 0 || alp_slack < 0 || (alp_eta > ALP_TAB[3]))
		return false; // a far finish is not pinned
	if (!recall)
		return alp_slack <= ALH_TAB[2] + ALP_TAB[2];
	if (!M.has_home)
		return false; // no walk-back field yet: keep live play
	const vec2 ap = M.altars[static_cast<std::size_t>(alp_ai)].pos;
	int back = BIG;
	for (int dy = -2; dy <= 2; ++dy)
		for (int dx = -2; dx <= 2; ++dx)
		{
			const vec2 p{ ap.x + dx, ap.y + dy };
			if (!inb(p))
				continue;
			const std::uint16_t d = dfget(M.f_home, p); // f_home: always built (f_home_cb is skipped when distances are known; it read 0)
			if (d != UNREACH)
				back = std::min(back, static_cast<int>(d));
		}
	const int ticks = rs::recall_rounds(prism::has_family(rs::F_HOME), false);
	const bool pin = back >= BIG || ticks + back > alp_eta;
	NLOG("r%d slot %d ALP pin %d slack %d eta %d back %d\n", W.round, P.my_slot, (int)pin, alp_slack, alp_eta, back);
	return pin;
}
bool end_hold_turn()
{
	if (!W.alive || W.me.channeling() || !end_hold_blocks_bank(static_cast<int>(W.me.gems)))
		return false;
	eh_last = now();
	NLOG("r%d slot %d end-hold gems %u us %d them %d spawn %d\n", now(), P.my_slot, W.me.gems, W.tributed_us, W.tributed_them, (int)W.on_spawn);
	if (W.on_spawn)
		return true; // hold: enemies never enter our spawn (GameRules.md:151) and it heals at turn end
	return go_home();
}
} // namespace nova::econ
