// econ_rate_crew.cc: Rate of a group, part 1: crew timing and waiting modifiers.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// v661 BB27 (b1776): firing markers (the diag copy counts their entries; empty in release).
void bb27_fc_rt1()
{
}
void bb27_fc_rt2()
{
}
void bb27_fc_flip()
{
}
// BB27 (called with bit 1 or 2 on): the pair's penalty: pen_crew times prism_mate_factor (RT1, my own row) and with the solo
// foe-arrival factor swapped for the pair's (RT2, as penalties applies it). k = the rest of the pair rate, r = the solo rate (marks a
// changed lone-v-pair choice).
float bb27_pair_pen(const GroupI& g, int gi, int self, bool dg, float F, float pc, float k, float r)
{
	float p = pc;
	if (self == my_slot())
	{
		const float f = prism_mate_factor(g, gi);
		if (f != 1.0f)
			bb27_fc_rt1();
		p *= f;
	}
	if (self == my_slot() && opened && !dg)
	{
		const float m1 = faf_of(F, 1);
		const float m2 = faf_of(F, 2);
		if (m1 > 0.0f && m1 != m2)
		{
			bb27_fc_rt2();
			p *= m2 / m1;
		}
	}
	if ((pc * k > r) != (p * k > r))
		bb27_fc_flip();
	return p;
}
bool help_mode = false; // second pass for a body with no target of its own
// Cap for the wait-map rule (the map's median gap between neighbouring walkable groups, Chebyshev x 4/3, 3-15 rounds), computed from
// static map data over a few turns (about 60 fuel per group pair; at most 20 x 60 pairs).
std::vector<vec2> wm_an; // walkable groups' anchors
std::vector<int> wm_gaps; // nearest-neighbour gaps measured so far
std::size_t wm_i = 0; // next sampled group
int hc_state = 0; // 0 undecided, 1 off, 2 on
int ir_near_round = -1000; // the round of ir_near, the IR_K groups a due idle round may rate
std::array<int, IR_K> ir_near{};
struct GpvFoe
{
	vec2 pos{};
	int age = 0, slack = 0;
	bool spawn = false, sok = false; // sok: strength read (lazily, first need this round)
	int ti = -1; // team_table index
	float s = 1.0f;
};
std::array<GpvFoe, 8> gpv3_f{};
int gpv3_n = 0, gpv3_r = -1, gpv3_age = 30, gpv3_e = 2;
float gpv3_w = 1.0f, gpv3_st = 0.25f; // The table's slots are read once a round.
int gpv3_nf = 0; // Fresh sightings come first in gpv3_f, stale ones after.
std::vector<std::int8_t> blf_zc; // zone per group, once
// An unseen foe's HP reads full once a recall could have finished since its HP was read (recall + 1 rounds) or it could have walked
// home (Chebyshev distance from where it was read to its spawn rectangle < rounds since), or it was last placed on its spawn (src 4:
// round 1 or a respawn). Else the HP last read.
struct BlfRect { int x0 = 1 << 20, y0 = 1 << 20, x1 = -(1 << 20), y1 = -(1 << 20); };
BlfRect blf_esp;
struct GpvSc
{
	int round = -2000; // the sighting round the strength was read for
	bool healed = false;
	float s = 1.0f;
};
std::array<GpvSc, 8> gpv3_sc{}; // A foe's strength per team_table slot, kept while its sighting is unchanged.
float gpv3_ss = -1.0f; // gpv3_st x the stale foes' strengths, read on first need
float gpv3_me = 1.0f, gpv3_k = 1.0f; // gpv3_k: the last call's G3 factor on the rate
// One rating of a group for a body: rate_for's steps in order, sharing what each settles. Every step is inlined, so the fields stay in registers.
struct RateJob
{
	const int gi, self;
	std::uint16_t trav; // the walk; a crew's own walk replaces it
	const Claims& cl;
	int max_extra;
	const GroupI& g;
	const GroupMem& m;
	const bool dg; // a dash-only group (mine to take alone, see dash_group)
	float wait = 0;
	int others = 0, top = 0;
	bool gn = false, oe = false;
	int crew = 0, recruits = 0;
	ClearEst e;
	float cr_k = 1.0f; // the share of the group's remaining health this trip takes off (1: the whole clear)
	float altar_d = 0, t = 0, value = 0, blf_k = 1.0f, pen = 1.0f, pen_crew = 1.0f, r = 0;
	float peg_chan = -1.0f; // v683 PEG1: the end test's channel (its bankable test runs only where the time test holds)
	float faf_f = 0; // penalties' faf_F(g) (self, opened, !dg), reused by the pair

	// This body may not take the group at all.
	__attribute__((always_inline)) bool closed()
	{
		if (m.fail_until > now() || (dg && !dash_group(gi, self)) || trav == UNREACH)
			return true;
		if (g.gems == 0 && g.gold == 0)
			return true;
		if (sg_big(g) && !(big_group_nearly_dead(gi)))
			return true; // big groups are team operations (siege_turn), never a body's own choice
		if (M.ring && is_gate(gi) && static_cast<std::size_t>(g.nm) <= 1)
			return true; // a one-camp gate group, once captured, respawns and shuts the gap. Bigger ring
			           // groups are farmed as usual (held-out gold-ring maps: excluding them cut our gold from ~25k to ~1-2k a game)
		if (dg)
			max_extra = 0; // only dashers get there: no crew
		// Gems only a dasher can bank: a walker leaves gem-only groups to the dashers.
		if (!M.any_altar && g.gold == 0 && dash_only_bank() && !slot_dasher(self) && team_dasher())
			return true;
		return false;
	}
	// The wait for a respawn at my arrival.
	__attribute__((always_inline)) bool respawn_too_late()
	{
		if (m.status == GS_RESPAWN)
		{
			wait = static_cast<float>(std::max(0, m.respawn_at - now() - static_cast<int>(trav))); // alive at my arrival
			if (RTE_ON(1) && self == my_slot() && gi == T.target && gi == rte_pick_g && m.respawn_at == rte_pick_ra && static_cast<int>(trav) < rte_pick_trav)
				return false; // v712 RTE bit 1: my own target, same respawn, only my walk got shorter
			if (wait > (crew_wait_limit(g)) && !respawn_wait_lifted(gi, self, wait)) // MCK bit 1
				return true;
			// A trip the travel recall will take arrives at 7 + d_home, not at the walk.
			if (self == my_slot() && opened && g.d_home != UNREACH && static_cast<int>(trav) >= CSX_RCT() + static_cast<int>(g.d_home) + RECALL_TRAVEL && (now() - S.recall_round >= RT_GAP))
			{
				const int rct = 7; // The gate's own recall price.
				const float wr = static_cast<float>(std::max(0, m.respawn_at - now() - rct - static_cast<int>(g.d_home)));
				if (wr > (crew_wait_limit(g)) && !respawn_wait_lifted(gi, self, wr)) // MCK bit 1
					return true;
			}
		}
		return false;
	}
	template <int DM>
	__attribute__((always_inline)) bool claimed()
	{
		others = claimants(gi, self, cl);
		if (dg && others > 0)
			return true; // one dasher per dash-only group
		if (m.status == GS_CLEARED && others > 0 && gi != T.target && gi != ci_adopt_g) // Cassi joins Issac's capture
			return true; // a crew mate is capturing it
		// Solo by default: a group its claimants can already clear without me is theirs. Joining would only split the
		// reward and stack bodies on one group (four bodies on one elk in the opening). Sieges recruit on purpose. WL2_ON(2048): Willow may
		// join a mate's group (her heal and damage; bit 4 leaves the capture to the mate).
		gn = !dg && gem_need_crew_group(gi); // a contested gem group while gems are what the team lacks
		oe = !dg && opening_elk_target(gi, self, cl); // the opening crew's own-side elk group
		if (others > 0 && !(self == my_slot() && willow_layer::type(W.me.type)) && !(self == my_slot() && gi == T.target) && gi != ci_adopt_g && !siege_group(g) && !help_mode && !(others == 1 && !dg && crew_bonus(g) > 1.0f) && !gn && !(oe && others < opening_elk_crew_floor()) && !(self == my_slot() && opened && others == 1 && !dg && g.contest > SQ_OUT) && !(!dg && g.n_elk > 0 && others < 3 && g.contest <= 0.60f) && !(!dg && others < 3 && gem_need_join_group(g)) && !((DM & 1) && dc_is(gi)) && !((DM & 2) && !dg && others < HC_JOIN && hc_group(gi)) && estimate_cx(1, g, m, crew_of_claimants(gi, self, cl)).feasible)
			return true;
		return false;
	}
	// The smallest crew of free bodies that clears it.
	__attribute__((always_inline)) void size_crew()
	{
		top = std::min(others + 1 + max_extra, std::max(TM.n, others + 1));
		for (int k = others + 1; k <= top; ++k)
		{
			const Crew& c = crew_for_ref(gi, self, k - others - 1, cl);
			e = estimate_cx(1, g, m, c);
			if (e.feasible)
			{
				crew = c.n;
				break;
			}
			if (c.n < k)
				break; // no more free bodies
		}
	}
	__attribute__((always_inline)) void recruit()
	{
		bool irb = false; // the idle branch opened the recruit loop
		if (crew == 0 && !dg &&
			((siege_map() && siege_group(g) && g.n_att == 1 && siege_allowed(gi, self, cl)) ||
			 (gn && gem_need_allowed(gi, self, cl)) ||
			 (irb = self == my_slot() && idle_recruit_open(gi)) // an idle body recruits for a group no free crew can clear
			 )) // a contested gem camp no crew of free bodies can clear recruits like a siege
		{
			// A lone monolith or golem needs most of the team: count on bodies leaving their own (not yet engaged)
			// targets. They see the claims and join when the siege beats their own task.
			const int nfree = std::max(0, top - others - 1);
			const bool irf = irb; // free mates at any distance are idle recruits
			const int ir_rmax = irf && IRF_MODE >= 2 ? IRF_RMAX : IR_RMAX;
			for (int r = 1; others + 1 + nfree + r <= TM.n && !(irb && r > ir_rmax); ++r) // idle branch capped
			{
				const Crew& c = crew_for_ref(gi, self, nfree, cl, nullptr, r, irf);
				if (c.n < others + 1 + nfree + r)
					break;
				e = estimate_cx(1, g, m, c);
				if (e.feasible)
				{
					crew = c.n;
					recruits = r;
					break;
				}
			}
			if (irb && recruits > 0)
			{
				// set_target keeps ir_tgt when the choice takes one of these groups
				if (ir_ok_round != now())
				{
					ir_ok_round = now();
					ir_ok.clear();
				}
				ir_ok.push_back(int{ gi }); // a copy: the address of a field would keep the whole job in memory
			}
		}
	}
	__attribute__((always_inline)) void chip_trip()
	{
		if ((crew == 0) && self == my_slot() && opened && others == 0 && !dg && !gn && chip_candidate_group(g) && m.status != GS_CLEARED && !((prism_layer::cr_rich() || static_cast<int>(W.me.gems) >= CR_BAG)) && m.status != GS_RESPAWN && chip_group_is_quiet(gi))
		{
			// No crew of free bodies clears it: a lone trip that takes CR_MIN_PCT % of what is left off before my bail line, while the whole
			// job (this walk, the walk back, the whole clear, the altar and its channel) fits the game.
			static Crew fb10_s1;
			const Crew& c1 = crew_for_ref(gi, self, 0, cl);
			const float sh = chip_clear_share(g, m, c1);
			if (sh * 100.0f >= static_cast<float>(CR_MIN_PCT)) // a chip no worse per body than the crew job
			{
				const ClearEst ef = estimate_cx(1, g, m, c1);
				const float alt = altar_walk(g);
				const float ch = static_cast<float>(rs::tribute_rounds(static_cast<int>(W.me.gems) + g.gems, static_cast<bool>(prism::has_family(rs::F_TRIBUTE)))); // CBN bit 2 R10: rule-correct tribute rounds; with the bit off, ceil(G/10).
				if (static_cast<float>(now()) + 2.0f * static_cast<float>(trav) + ef.t + alt + 12.0f + ch <= GAME_END_F)
				{
					cr_k = std::min(1.0f, sh);
					e = ef;
					e.t = ef.t * cr_k;
					crew = 1;
				}
			}
		}
	}
	__attribute__((always_inline)) bool no_crew()
	{
		if (crew == 0)
			return true;
		return false;
	}
	__attribute__((always_inline)) bool crew_floor()
	{
		if (oe && crew < opening_elk_crew_floor())
		{
			// the opening crew floor from free bodies (the opening simulation drafts them).
			const int nfree = std::max(0, std::min(max_extra, opening_elk_crew_floor() - others - 1));
			static Crew fb10_s2;
			const Crew& c = crew_for_ref(gi, self, nfree, cl);
			const ClearEst e3 = estimate_cx(1, g, m, c);
			if (c.n > crew && e3.feasible)
			{
				e = e3;
				crew = c.n;
			}
		}
		if (gn && crew == 1 && others == 0 && !(crew_ally_near(gi, self, cl)))
		{
			// no lone trips into the contested band: draft a free body, else recruit one (as sieges do).
			Crew c2 = crew_for(gi, self, std::min(1, max_extra), cl);
			int rec = 0;
			if (c2.n < 2)
			{
				c2 = crew_for(gi, self, 0, cl, nullptr, 1);
				rec = 1;
			}
			if (c2.n < 2)
				return true;
			e = estimate_cx(1, g, m, c2);
			crew = c2.n;
			recruits = rec;
		}
		return false;
	}
	__attribute__((always_inline)) void crew_walk()
	{
		if (crew > 1 && self == my_slot())
		{
			std::uint16_t wt = spawn_crystal_crew_trav(gi, trav); // a crew walks; my hop would only wait for it
			if (wt != trav && sc_trip_live(0) && SC.gi == gi)
				wt = crystal_crew_travel(gi, self, trav, wt, cl);
			if (wt != trav)
			{
				trav = wt;
				if (m.status == GS_RESPAWN)
					wait = static_cast<float>(std::max(0, m.respawn_at - now() - static_cast<int>(trav))); // alive at my arrival
			}
		}
	}
	// The trip's time and my share of the reward.
	__attribute__((always_inline)) void time_and_value()
	{
		altar_d = altar_walk(g);
		t = static_cast<float>(trav) + wait + e.t + cap_term(self) / static_cast<float>(crew);
		if (dg)
			t += 8.0f; // the recall home afterwards
		if (recruits > 0)
			t += 20.0f + 4.0f * static_cast<float>(crew - others - 2); // bodies leaving other targets gather later
		else if (crew > others + 1)
			t += (static_cast<float>(B467_GATHER_X100) / 100.0f) * static_cast<float>(crew - others - 1) * (opened ? 1.0f : 1.0f - crew_group_k(g)); // the crew still has to gather; an opening crew leaves the spawn together
		const bool ro4_fin = FB6_ON(8) && self == my_slot() && finish_progress_mode(); // FB6 RO4: one value, after the endgame test
		value = FB6_ON(8) ? 0.0f : group_value(g, gi, self) / static_cast<float>(crew);
		if (!FB6_ON(8) && self == my_slot() && finish_progress_mode())
			value = finish_group_value(g, gi, self, 1.0f / static_cast<float>(crew)); // progress toward the win
		float chan = static_cast<float>(rs::tribute_rounds(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, false)); // my bag and my share of the reward; the capturer carries it all
		// v683 EGA: any bankable map; bankable() is pure, so it is tested only once a late-game time test holds
		if (chan > 0.0f && static_cast<float>(now()) + t + altar_d + 12.0f + chan > GAME_END_F && (M.any_altar || M.ring || bankable()) && slot_holds_tribute(self))
		{
			chan = static_cast<float>(cbn_tt(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, true)); // only a holder's shorter channel can change the test
		}
		peg_chan = chan;
		if (static_cast<float>(now()) + t + altar_d + 12.0f + chan > GAME_END_F && (M.any_altar || M.ring || bankable()))
		{
			value = xgv_gold_value(g, gi, self) / static_cast<float>(crew);
		}
		else if (FB6_ON(8))
			value = ro4_fin ? finish_group_value(g, gi, self, 1.0f / static_cast<float>(crew)) : group_value(g, gi, self) / static_cast<float>(crew);
		value *= cr_k; // a chip earns its share of the group (1 otherwise)
		blf_k = 1.0f;
		value *= blf_k;
		if (g.gems > 0)
			t += static_cast<float>(B438_ALTW_X100) / 100.0f * altar_d;
	}
	// Everything that scales the rate for risk and position.
	template <int DM>
	__attribute__((always_inline)) void penalties()
	{
		pen *= territory_factor(g, gi, self, cl, m, false); // finish chipped groups in our territory
		// Once value and time are final, the deep-lone reject (below) can be decided early: crew 1 and no crew switch can follow (no
		// gem-need, open-elk or hoard switch, no pair bonus); later factors at most: contest <= 1, seen <= max(1, seen factor,
		// mid-presence), kill window, pack and back factors exact, crew guard <= 1, pair-deep, squad, PHM and RD_TRAVEL at their largest;
		// opportunity_factor is 1 whenever the deep-lone reject's !foes_accounted_for_and_far holds (contest > .45: its free-camp test
		// fails); no ECL / MF / G3. The same answer as the full computation, decided earlier. Ward: contested groups cost less while
		// enemies are dead (deaths are known map-wide).
		const float ctw_c0 = ES_CONT0F;
		if (g.contest > (ctw_c0) && !(dg && (EXPV & 2) && ((starved_map_bits() & 16) == 0 || pocket_on_own_side(gi))) && !(g.access == ACC_TP)) // EXPLORE bit 2: a dash-only group's contest reads 1 (no walk from home): no penalty. OWR bit 2: the same for crystal-only groups.
		{
			pen *= contest_walk_factor(1.0f - static_cast<float>(B438_CONT_X100) / 100.0f * (g.contest - ctw_c0) / 0.45f, trav, self);
		}
		// RD_TRAVEL: a home-side group so far from me that the trip is a travel recall (lands on the spawn, farms nothing on the way)
		// keeps a set percent of its rate. Enemies known near the group (sightings by anyone on the team, wards included) replace the flat
		// enemy_seen penalty; other bodies' choices (opening simulation) keep the old rule. The opening simulation rates every body's row
		// alike: 1 = no pack factor in it, 2 = every row gets the pack factor of a body standing at the spawn with its team
		// (combat::group_pack_factor at the opening, without claims). A loose pack on fight maps.
		const float pf = (self == my_slot() && opened) ? combat::group_pack_factor(gi) : ((!opened) ? opening_pack_factor(gi) : 1.0f);
		// a centre group on a many-altar map with a mate near it (decided only on those maps)
		const bool mp = !dg && M.na >= MP_ALTARS && g.contest * 100.0f >= static_cast<float>(MP_LO) && g.contest * 100.0f <= static_cast<float>(MP_HI);
		if (now() - m.enemy_seen < static_cast<int>(ES_TAB[4])) // kill window: the marks of a fight we won do not count while they are down
		{
			float sp = ((pf > 1.0f) || ((DM & 1) && dc_is(gi))) ? 0.85f : static_cast<float>(SEEN_PEN_X100) / 100.0f; // the pack contests what a lone body would leave; so does a crew on a contested gem group
			if (mp)
				sp = std::max(sp, static_cast<float>(MP_SEEN_X100) / 100.0f);
			if (self == my_slot() && opened && !dg) // G3 prices the sighting
			{
				((void)0);
			}
			else
				pen *= sp;
		}
		if (self == my_slot() && now() - m.kill_round < 20)
			pen *= (static_cast<float>(B467_KILLW_X100) / 100.0f); // The victim's respawn window next to our kill, no other enemy near.
		pen *= (self == my_slot() && opened && !dg && pf > 1.0f) ? 1.0f + (pf - 1.0f) * static_cast<float>(PCAL_TAB[6]) / 100.0f : pf;
		if (self == my_slot() && opened && !dg)
		{
			faf_f = faf_F(g);
			const float m3 = faf_of(faf_f, crew);
			pen *= m3;
			(void)0;
		}
		pen_crew = pen; // the penalty without the lone-trip guard
		if (crew == 1 && others == 0 && !dg && g.contest > 0.40f && !mp) // mid presence: no lone-trip guard.
		{
			// No lone trips into the middle or the enemy third early on compact contact maps.
			const float ke = crew_keff() * clampf((g.contest - 0.40f) / 0.10f, 0.0f, 1.0f);
			if (ke > 0 && !crew_ally_near(gi, self, cl))
				pen *= 1.0f - CREW_GUARD * ke;
		}
		// (review: not the current target, so a trip under way is not dropped when an exemption lapses; not in the opening
		// simulation, whose rows must match on every body)
		if (self == my_slot() && opened && gi != T.target && crew == 1 && others == 0 && !dg && g.contest > 0.60f && foes_down_count(KW_AHEAD) < 2 && !crew_ally_near(gi, self, cl))
			pen *= PD_PEN; // no lone trip deep into their half unless two of them are down
		if (self == my_slot())
			pen *= prism_mate_factor(g, gi);
	}
	// The rate, with the crew bonus; a lone body also compares a pair.
	template <int DM>
	__attribute__((always_inline)) void crew_term()
	{
		r = pen * value / std::max(1.0f, t);
		float cb = (dg || recruits > 0 || siege_group(g)) ? 1.0f : crew_bonus(g);
		if ((DM & 2) && !(dg || recruits > 0 || siege_group(g)) && hc_group(gi))
			cb = std::max(cb, static_cast<float>(HC_BONUS_X100) / 100.0f); // a crew of 2+ on a gem hoard
		if ((DM & 2) && !(dg || recruits > 0 || siege_group(g)) && crew < 2 && region_mate_claims(gi, self, cl))
		{
			r *= static_cast<float>(HC_BONUS_X100) / 100.0f; // a solo body on a region group with a mate in the region
			pen *= static_cast<float>(HC_BONUS_X100) / 100.0f;
		}
		if (gn)
			cb = std::max(cb, gn_bonus()); // a crew on a contested gem group is worth more per body
		if (oe && crew >= 2)
			cb = std::max(cb, OE_BONUS); // the opening crew on an own-side elk group is worth more per body
		if (cb > 1.0f)
		{
			// Opening crews. A crew of 2+ is worth more per body in the mode (safety, gem tempo); a lone body compares its solo rate with a
			// pair (one free body drafted, only the capturer waits for the capture).
			if (crew >= 2)
			{
				r *= cb;
				pen *= cb;
			}
			else if (others == 0 && max_extra >= 1)
			{
				static Crew fb10_s3;
				const Crew& c2 = crew_for_ref(gi, self, 1, cl);
				if (c2.n >= 2)
				{
					const ClearEst e2 = estimate_cx(1, g, m, c2);
					float t2 = static_cast<float>(trav) + wait + e2.t + 0.5f * cap_term(self) + (static_cast<float>(B467_GATHER_X100) / 100.0f) * (opened ? 1.0f : 1.0f - crew_group_k(g));
					if (g.gems > 0)
						t2 += static_cast<float>(B438_ALTW_X100) / 100.0f * altar_d;
					float v2 = (self == my_slot() && finish_progress_mode()) ? finish_group_value(g, gi, self, 0.5f) : group_value(g, gi, self) / 2.0f;
					if (peg_chan >= 0.0f && static_cast<float>(now()) + t2 + altar_d + 12.0f + peg_chan > GAME_END_F && (M.any_altar || M.ring || bankable()))
					{
						v2 = xgv_gold_value(g, gi, self) / 2.0f; // v683 PEG1: the pair trip cannot bank its gems by 2000
					}
					const float pc2 = bb27_pair_pen(g, gi, self, dg, faf_f, pen_crew, cb * v2 * blf_k / std::max(1.0f, t2), r); // v661 BB27 RT1/RT2
					const float r2 = cb * (pc2) * v2 * blf_k / std::max(1.0f, t2);
					if (e2.feasible && r2 > r)
					{
						r = r2;
						crew = 2;
						value = v2 * blf_k;
						t = t2;
						pen = cb * (pc2);
					}
				}
			}
		}
	}
	__attribute__((always_inline)) bool late_factors()
	{
		{
			float of = opportunity_factor(g, m);
			r *= of;
			pen *= of;
		}
		if (!mcl_off(MCL_TAB[4]) && self == my_slot() && opened && !dg && crew == 1 && others == 0 && g.contest * 100.0f > static_cast<float>(DLT_TAB[3]) && r * 1000.0f < static_cast<float>(DLT_TAB[2]) && foes_down_count(KW_AHEAD) < 2 && !crew_ally_near(gi, self, cl) && !foes_accounted_for_and_far(g))
			return true;
		// The rate's parts, for re-ranking near-best targets by the route that starts there.
		if (self == my_slot() && opened && ((map_class() & 1) != 0))
		{
			const int wb = trav <= 6 ? 0 : (trav <= 12 ? 1 : (trav <= 20 ? 2 : (trav <= 35 ? 3 : 4)));
			const float gv = static_cast<float>(g.gems) + 0.35f * static_cast<float>(g.gold);
			const int sb = gv < 15.0f ? 0 : (gv < 40.0f ? 1 : (gv < 100.0f ? 2 : 3));
			const int cbk = g.contest <= 0.30f ? 0 : (g.contest <= 0.60f ? 1 : 2);
			float ef = static_cast<float>(ECL_CELL[12 * wb + 3 * sb + cbk]) / 1000.0f;
			ef = std::sqrt(ef);
			r *= ef;
			pen *= ef;
		}
		return false;
	}
	__attribute__((always_inline)) float publish(int* crew_out)
	{
		nova::econ::linear_score::note(gi, g.gems > 0 ? static_cast<float>(B438_ALTW_X100) / 100.0f * altar_d : 0.0f, e.t, e.dmg, wait, static_cast<int>(trav), crew, others, recruits);
		rf_value = value;
		rf_time = t;
		rf_pen = pen;
		if (crew_out)
			*crew_out = crew;
		return r;
	}
};
void crew_init()
{
	crew_k = 0;
	if (!P.from_memory || M.groups.empty())
		return; // no spawn distances: the mode stays off
	float num = 0, den = 0;
	int est = BIG; // spawn-to-spawn walk through the nearest group or altar between the spawns (from draft memory)
	for (const auto& g : M.groups)
	{
		if (g.d_home != UNREACH && g.d_enemy != UNREACH)
			est = std::min(est, static_cast<int>(g.d_home) + static_cast<int>(g.d_enemy));
		if (g.access != ACC_WALK || g.d_home == UNREACH || g.gems <= 0 || g.contest > 0.55f)
			continue;
		num += static_cast<float>(g.d_home) * static_cast<float>(g.gems);
		den += static_cast<float>(g.gems);
	}
	for (const auto& a : M.altars)
		if (a.d_home != UNREACH && a.d_enemy != UNREACH)
			est = std::min(est, static_cast<int>(a.d_home) + static_cast<int>(a.d_enemy));
	const float near = den > 0 ? num / den : 1e9f;
	const float s2s = P.s2s >= 0 ? static_cast<float>(P.s2s) : (est < BIG ? static_cast<float>(est) : 1e9f);
	crew_k = 0.5f * clampf((40.0f - near) / 25.0f, 0.0f, 1.0f) + 0.5f * clampf((60.0f - s2s) / 40.0f, 0.0f, 1.0f);
	NLOG("CREW k %.2f near %.1f s2s %.0f (memory %d, est %d)\n", crew_k, near, s2s, P.s2s, est);
}
float crew_keff()
{
	if (crew_k <= 0)
		return 0;
	return crew_k * clampf(static_cast<float>(CREW_R - now()) / (0.5f * static_cast<float>(CREW_R)), 0.0f, 1.0f);
}
// An ally's claim (a group whose anchor is within 8 tiles of gi's) or, for my own choices after the opening, a visible ally within 8
// tiles of gi's anchor. The opening simulation uses claims only (positions are all the spawn). foes_down_count: enemy bodies that cannot be
// back on their spawn within `ahead` rounds (once per round).
int foes_down_count(int ahead)
{
	static int r = -1, a = -1, v = 0;
	if (r != now() || a != ahead)
	{
		r = now();
		a = ahead;
		v = intel::enemies_total() - intel::possible_at(now() + ahead, 0);
	}
	return v;
}
bool crew_ally_near(int gi, int self, const std::array<int, 8>& cl)
{
	const vec2 at = M.groups[static_cast<std::size_t>(gi)].anchor;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		const int c = cl[static_cast<std::size_t>(s)];
		if (s == self || c < 0 || c >= M.ng)
			continue;
		if (cheb(M.groups[static_cast<std::size_t>(c)].anchor, at) <= 8)
			return true;
	}
	if (self == my_slot() && opened)
		for (const auto& al : W.allies)
			if (!al.channeling() && cheb(al.pos, at) <= 8)
				return true;
	return false;
}
// The share of an alive group's health already gone (>= 10%, else 0), for a walkable non-siege group in our territory (contest <=
// TERR_OWN) after the opening. Camps never regenerate, so the share lasts.
float chipped_share(const GroupI& g, const GroupMem& m)
{
	if (!opened || g.access != ACC_WALK || g.contest > TERR_OWN || m.status != GS_ALIVE || m.hp_left < 0 || g.hp <= 0 || siege_group(g))
		return 0.0f;
	const float done = 1.0f - clampf(m.hp_left / std::max(1.0f, g.hp), 0.0f, 1.0f); // BB8P: max(1, hp)
	return done >= 0.1f ? done : 0.0f;
}
// The rate multiplier of group gi for body `self`: finish chipped groups in our territory. After the opening only. bound: the upper
// bound for the group bounds (section ignored, so bound >= exact).
float territory_factor(const GroupI& g, int gi, int self, const std::array<int, 8>& cl, const GroupMem& m, bool bound)
{
	if (!opened || g.access != ACC_WALK || siege_group(g))
		return 1.0f;
	float f = 1.0f;
	f *= 1.0f + TERR_FIN * chipped_share(g, m);
	return f;
}
int wait_cap_i()
{
	return std::max(1, (wm_cap >= 0 ? wm_cap : WAIT_MAX) * static_cast<int>(ES_TAB[9]) / 100); // The wait cap scaled by ES_TAB slot 9 (percent).
}
void wait_cap_compute()
{
	if (wm_cap >= 0 || M.groups.empty())
		return;
	if (wm_an.empty())
	{
		for (const auto& g : M.groups)
			if (g.access == ACC_WALK && !g.members.empty())
				wm_an.push_back(g.anchor);
		if (wm_an.size() < 2)
		{
			wm_cap = WAIT_MAX;
			return;
		}
		wm_i = 0;
	}
	// A few sampled groups per turn (each row costs about 60 fuel per group compared), while the turn has fuel to spare.
	const std::size_t n = wm_an.size(), sa = std::max<std::size_t>(1, n / 20), sb = std::max<std::size_t>(1, n / 60);
	while (wm_i < n && fuel() > 78000)
	{
		int best = 1000;
		for (std::size_t j = 0; j < n; j += sb)
			if (j != wm_i)
				best = std::min(best, cheb(wm_an[wm_i], wm_an[j]));
		wm_gaps.push_back(best * 4 / 3);
		wm_i += sa;
	}
	if (wm_i < n)
		return; // not done yet: the next turn goes on
	std::nth_element(wm_gaps.begin(), wm_gaps.begin() + static_cast<std::ptrdiff_t>(wm_gaps.size() / 2), wm_gaps.end());
	wm_cap = std::clamp(wm_gaps[wm_gaps.size() / 2], 3, 15);
	wm_an.clear();
	wm_gaps.clear();
}
float crew_wait_limit(const GroupI& g)
{
	// Wait-less rule: a respawning group is a target only when it is back within the wait cap of my arrival; longer waits go to free
	// groups.
	(void)g;
	return static_cast<float>(wait_cap_i());
}
// The mode's weight on a gem camp: walkable gems with attackers (no monolith or golem), on our side or in the centre (full at
// contest 0.50, gone at 0.60). 0 for every other group.
float crew_group_k(const GroupI& g)
{
	if (g.gems <= 0 || g.n_att <= 0 || g.access != ACC_WALK || g.n_mono + g.n_golem > 0)
		return 0.0f;
	return crew_keff() * clampf((0.60f - g.contest) / 0.10f, 0.0f, 1.0f);
}
// The per-body rate multiplier of a crew of 2+ on such a camp (1 elsewhere and outside the mode).
float crew_bonus(const GroupI& g)
{
	const float ke = crew_group_k(g);
	const float cb = (ke > 0) ? 1.0f / (1.0f - CREW_PAIR * ke) : 1.0f;
	return cb;
}
// per-group hoard flags, decided once by the free-slot pass from static map data; read only in mode 2/3.
std::vector<std::uint8_t>& hoard_flags() // function-local: no global constructor, so start-up costs no fuel
{
	static std::vector<std::uint8_t> v;
	return v;
}
bool hc_group(int gi) { return hc_state == 2 && gi >= 0 && static_cast<std::size_t>(gi) < hoard_flags().size() && hoard_flags()[static_cast<std::size_t>(gi)] != 0; }
// regions = false (the opening simulation): region groups keep their plain bound (the opening places the first bodies there; doubled
// bounds on 10-20 region groups would make every body's simulation rate them all). Outside the opening only the best few region
// groups (plain bound, cand comes best first) carry the boost, for the same reason: every re-choice would rate all of them.
__attribute__((noinline)) void hoard_crew_bounds(std::vector<std::pair<float, int>>& cand, bool regions = true)
{
	bool any = false;
	int nb = regions ? HR_NB : 0;
	for (auto& c : cand)
		if (hc_group(c.second) && (hoard_region_id(c.second) < 0 || (nb > 0 && nb-- > 0)))
		{
			c.first *= static_cast<float>(HC_BONUS_X100) / 100.0f;
			any = true;
		}
	if (any)
		std::stable_sort(cand.begin(), cand.end(), [](const std::pair<float, int>& a, const std::pair<float, int>& b) { return a.first > b.first; });
}
// region sums by region id (table value - 2); single hoards keep table value 1.
std::vector<int>& hoard_region_sums() // function-local: no global constructor
{
	static std::vector<int> v;
	return v;
}
int hoard_region_id(int gi)
{
	if (!hc_group(gi))
		return -1;
	const int t = hoard_flags()[static_cast<std::size_t>(gi)];
	return t >= 2 ? t - 2 : -1;
}
// The hoard's gems: a region's sum, else the group's own.
int hoard_gems(int gi)
{
	const int r = hoard_region_id(gi);
	if (r >= 0 && static_cast<std::size_t>(r) < hoard_region_sums().size())
		return hoard_region_sums()[static_cast<std::size_t>(r)];
	return gi >= 0 && static_cast<std::size_t>(gi) < static_cast<std::size_t>(M.ng) ? M.groups[static_cast<std::size_t>(gi)].gems : 0;
}
// A mate (not `self`) claims a group of gi's region.
bool region_mate_claims(int gi, int self, const Claims& cl)
{
	const int r = hoard_region_id(gi);
	if (r < 0)
		return false;
	for (int s = 0; s < TM.n && s < 8; ++s)
		if (s != self)
		{
			const int c = cl[static_cast<std::size_t>(s)];
			if (c >= 0 && hoard_region_id(c) == r)
				return true;
		}
	return false;
}
} // namespace
} // namespace nova::econ
