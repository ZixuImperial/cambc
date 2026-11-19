// combat_cast.cc: Spells and raw attacks in a fight.
#include "combat_internal.h"
namespace nova::combat {
namespace cast
{
namespace tune
{
inline constexpr int HD_MIN_FUEL = 20000;      // no landing search below this
inline constexpr int HD_TESTS_PER_TURN = 3;    // landing searches a turn
inline constexpr int HD_DASH_REACH_MAX = 2;    // the farthest a landing is from me, whatever the kit says
inline constexpr int HD_FOE_LIST_MAX = 12;     // enemies kept for the safety count
inline constexpr int HD_FOE_LIST_SLACK = 2;    // kept when within the dash reach + this
inline constexpr int HD_CAMP_LIST_MAX = 49;    // A-CB-66: a 7x7 box holds up to 49 camps (26-28 seen)
inline constexpr int HD_LANDINGS_MAX = 24;     // landings kept for the ranking
inline constexpr int HD_CROWD_R = 2;           // enemies this near a landing count against it
inline constexpr int HD_MATE_R = 3;            // mates this near a landing count for it
inline constexpr int HD_CROWD_OVER_MATES = 1;  // a landing may have this many more enemies than mates
inline constexpr int HD_FOE_CLEAR_R = 6;       // no camp-only landing with an enemy this near
inline constexpr int HD_FOE_CROWD_R = 7;       // nor with HD_FOE_CROWD_N enemies (my sight or my ward's) this near
inline constexpr int HD_FOE_CROWD_N = 3;
inline constexpr int HD_SEEN_AGE = 4;          // remembered foes up to this old can walk into a camp-only landing
inline constexpr int HD_FOE_SCORE = 3;         // a landing's score: an enemy under it is worth this many camps
inline constexpr int HD_THREAT_TESTS = 3;      // ranked landings given the costly camp threat test
inline constexpr float HD_THREAT_SLACK = 0.5f; // a landing may raise the camp threat by this
inline constexpr float HD_STUN_CREDIT = 0.5f;  // share of the stunned camps' strength a camp-only landing may raise it by more
}
namespace {
int hd_round = -1;
bool hd_holdf = false;
struct HdCamp
{
	vec2 p;
	int g;
	float str;
	bool awake;
};
struct HdLanding
{
	vec2 L;
	int sc, ch;
	float stun;
};
// One landing search. The lists are the caller's raw buffers: no zeroing, only [0, n) is written and read.
struct HdScan
{
	vec2 me;
	int rad, dr, near;
	vec2* en; // enemies within dr + HD_FOE_LIST_SLACK (the safety count)
	HdCamp* cs; // camps within dr + rad (the landing's reach)
	HdLanding* cand;
	int ne = 0, nc = 0, nca = 0;
	int n_awake = 0;
	bool any = false; // an enemy within the landing's reach
	bool foe6 = false; // an enemy within HD_FOE_CLEAR_R of me
};
} // namespace
// GDN bit 1 GDV1: a game-ending deny cast goes ahead past veto `which` (0 Ren retaliation, 1 latch guard, 2 lethal landing, 3 spawn pin).
bool gdn_gdv_flip(int which)
{
	(void)which;
	return true;
}
bool cast_via_sdk(int slot, std::uint32_t kind, std::uint32_t handle, vec2 p)
{
	if (!ready(slot))
		return false;
	if (W.me.kit && kit_rules::ren_retaliation_of_cast(slot, kind, handle, p) >= eff_hp(W.me) && !(gdn_end_cast && gdn_gdv_flip(0)))
		return false; // the Rens it hits retaliate me dead
	if (W.me.kit && slot == W.me.kit->slot_dash && mv::foe_guarded(p) && !(gdn_end_cast && gdn_gdv_flip(1)))
		return false; // no dash landing inside a latch guard's foe reach
	if (W.me.kit && slot == W.me.kit->slot_dash && p.x >= 0 && burst::lethal_burst_landing_bad(p) && !(gdn_end_cast && gdn_gdv_flip(2)))
		return false; // no dash landing where the foes' next-turn burst kills me
	if (sph_pin && W.me.kit && slot == W.me.kit->slot_dash && p.x >= 0 && !bbget(M.my_spawn, p) && !(gdn_end_cast && gdn_gdv_flip(3)))
	{
		SPH_CNT(7, true);
		return false; // a hurt body on its spawn lands only on a spawn tile (the heal comes at turn end)
	}
	std::int32_t ok = 0;
	cancel_spin_before_action();
	const auto code = cambc::detail::sdk_cast(static_cast<std::uint32_t>(slot), kind, handle, p.x, p.y, &ok);
	if (code != 0)
	{
		NLOG("r%d cast slot %d failed code %d\n", W.round, slot, code);
		if (code == static_cast<std::int32_t>(cambc::error_code::invalid_action_spell_cast_bad_destination) && p.x >= 0 && W.me.kit && slot == W.me.kit->slot_dash)
		{
			DASH_MIDDLE_CNT(3, false);
			mv::note_teleport_reservation(p);
		}
		return false;
	}
	if (!ok)
	{
		if (p.x >= 0 && W.me.kit && slot == W.me.kit->slot_dash)
			mv::refuse_landing(p);
		return false;
	}
	W.cast = true;
	hpr_note(kind == KIND_CHAMPION ? handle : 0u, p); // v699 HPR bit 1
	if (kit_rules::slot_excl(slot))
		W.no_move = true;
	W.cd[static_cast<std::size_t>(slot)] = rs::slot_cooldown();
	refresh_self();
	if (W.me.kit && slot == W.me.kit->slot_dash)
	{
		reread_units();
		mv::occ_changed();
	}
	return true;
}
bool attack_via_sdk(std::uint32_t kind, std::uint32_t handle)
{
	if (!W.can_attack())
		return false;
	cancel_spin_before_action();
	const auto code = cambc::detail::sdk_attack(kind, handle);
	if (code != 0)
	{
		NLOG("r%d attack failed code %d\n", W.round, code);
		return false;
	}
	W.attacked = true;
	if (kind == KIND_CHAMPION)
		hpr_note(handle, vec2{ -1, -1 }); // v699 HPR bit 1
	refresh_self();
	return true;
}
// A camp index that names a real camp of the map.
static __attribute__((always_inline)) inline bool camp_ci_ok(int ci)
{
	return ci >= 0 && static_cast<std::size_t>(ci) < static_cast<std::size_t>(M.nc);
}
// The farthest tile the Heart of Ruin dash reaches from me.
static __attribute__((always_inline)) inline int heart_dash_reach(const Kit& k)
{
	return std::min(tune::HD_DASH_REACH_MAX, std::max(1, static_cast<int>(k.dash_range)));
}
namespace {
// Fuel: at most HD_TESTS_PER_TURN searches a turn, and the same keep tile is never searched twice from the same tile (camp_abilities,
// then the hit on the same camp).
static __attribute__((always_inline)) inline bool heart_dash_try_budget(vec2 keep)
{
	static int t_round = -1, t_n = 0;
	static vec2 t_keep{ -9, -9 };
	static vec2 t_me{ -9, -9 }; // my tile at that test
	if (t_round != W.round)
	{
		t_round = W.round;
		t_n = 0;
		t_keep = { -9, -9 };
	}
	if (t_n >= tune::HD_TESTS_PER_TURN || (keep == t_keep))
		return false;
	++t_n;
	t_keep = keep;
	t_me = W.me.pos;
	return true;
}
static __attribute__((always_inline)) inline void heart_dash_list_foes(HdScan& s)
{
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, s.me);
		s.any |= d <= s.near;
		s.foe6 |= d <= tune::HD_FOE_CLEAR_R;
		if (d <= s.dr + tune::HD_FOE_LIST_SLACK && s.ne < tune::HD_FOE_LIST_MAX)
			s.en[static_cast<std::size_t>(s.ne++)] = e.pos;
	}
}
static __attribute__((always_inline)) inline void heart_dash_list_camps(HdScan& s)
{
	for (const auto& vc : W.camps)
	{
		if (!camp_ci_ok(vc.ci))
			continue;
		const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cheb(cp.pos, s.me) > s.near || s.nc >= tune::HD_CAMP_LIST_MAX)
			continue;
		s.cs[static_cast<std::size_t>(s.nc++)] = { cp.pos, cp.group, cp.attacks() ? cp.str : 0.0f, vc.awake };
		s.n_awake += vc.awake ? 1 : 0;
	}
}
// A landing must not wake a sleeping group: a sleeping attacker whose group shows no awake camp in sight.
static __attribute__((always_inline)) inline bool heart_dash_landing_wakes_group(int g)
{
	for (const auto& vc : W.camps)
		if (vc.awake && camp_ci_ok(vc.ci) && M.camps[static_cast<std::size_t>(vc.ci)].group == g)
			return true;
	return false;
}
// A camp dash with 5 enemies 3-7 away got stunned and killed: a landing with no enemy under it needs them all well away, seen or remembered.
static __attribute__((always_inline)) inline bool heart_dash_camp_landing_safe(vec2 L)
{
	int n7 = 0;
	bool e6 = false;
	for (const auto& e : W.enemies)
	{
		const int dl = cheb(e.pos, L);
		n7 += dl <= tune::HD_FOE_CROWD_R ? 1 : 0;
		e6 |= dl <= tune::HD_FOE_CLEAR_R;
	}
	for (const auto& e : W.enemies_far)
		n7 += cheb(e.pos, L) <= tune::HD_FOE_CROWD_R ? 1 : 0;
	if (e6 || n7 >= tune::HD_FOE_CROWD_N)
		return false;
	for (const auto& m : seen)
	{
		const int age = W.round - m.round;
		if (age >= 0 && age <= tune::HD_SEEN_AGE && cheb(m.foe.pos, L) <= std::max(0, m.foe.reach) + 1 + age)
			return false;
	}
	return true;
}
// Tests the landing L and keeps it when it is legal, worth a dash and safe. keep: the landing stays in reach of this tile (x < 0: none).
static __attribute__((always_inline)) inline void heart_dash_try_add_landing(HdScan& s, vec2 keep, vec2 L)
{
	if (L == s.me || !mv::free_tile(L))
		return;
	if (keep.x >= 0 && cheb(L, keep) > W.me.range)
		return;
	if (cheb(s.me, L) == 2 && !geom::dash_middle_tile_ok(s.me, L))
		return;
	int ch = 0, e2 = 0;
	for (int i = 0; i < s.ne; ++i)
	{
		const int dl = cheb(s.en[static_cast<std::size_t>(i)], L);
		ch += dl <= s.rad ? 1 : 0;
		e2 += dl <= tune::HD_CROWD_R ? 1 : 0;
	}
	int cm = 0;
	bool wake = false;
	float stun_str = 0;
	for (int i = 0; i < s.nc; ++i)
	{
		const HdCamp& c = s.cs[static_cast<std::size_t>(i)];
		if (cheb(c.p, L) > s.rad)
			continue;
		if (c.awake)
		{
			++cm;
			stun_str += c.str;
		}
		else if (c.str > 0 && !heart_dash_landing_wakes_group(c.g))
			wake = true;
	}
	if (wake || (ch == 0 && (cm == 0 || s.foe6)))
		return;
	int al = 0;
	for (const auto& o : W.allies)
		al += (!o.channeling() && cheb(o.pos, L) <= tune::HD_MATE_R) ? 1 : 0;
	if (e2 > al + tune::HD_CROWD_OVER_MATES)
		return;
	if (ch == 0 && !heart_dash_camp_landing_safe(L))
		return;
	if (s.nca < tune::HD_LANDINGS_MAX)
		s.cand[static_cast<std::size_t>(s.nca++)] = { L, tune::HD_FOE_SCORE * ch + cm, ch, stun_str };
}
// Camp threat (the costly test) only on the best few: not raised, net of the camps the landing stuns. The first that passes is cast.
static __attribute__((always_inline)) inline bool heart_dash_cast_best_landing(const Kit& k, const HdScan& s)
{
	const float thr_me = mv::camp_threat(s.me);
	const float hck = 1.0f; // camp_threat's unit
	for (int i = 0; i < s.nca && i < tune::HD_THREAT_TESTS; ++i)
	{
		const HdLanding& c = s.cand[static_cast<std::size_t>(i)];
		const float thr_l = mv::camp_threat(c.L);
		if (c.ch > 0 ? thr_l - c.stun * hck > thr_me + tune::HD_THREAT_SLACK :
			thr_l > thr_me + tune::HD_STUN_CREDIT * c.stun * hck + tune::HD_THREAT_SLACK)
			continue;
		if (camps::wakes_other_group(c.L, s.rad, c.L, -1, c.ch > 0 ? (k.dash_mod * W.me.foc * kit_rules::camp_damage_factor()) : 0.0f)) // KTB16: champion pricing
			continue; // a cluster of a sleeping attacker group (the attacker test above misses it)
		if (cast_at(k.slot_dash, c.L))
		{
			return true;
		}
		if (!ready(k.slot_dash))
		{
			return false; // RFA bit 4: else the next landing
		}
	}
	return false;
}
__attribute__((noinline)) bool heart_dash_try_slow(vec2 keep)
{
	const Kit& k = *W.me.kit;
	if (k.dash_mod <= 0 || !k.dash_stun || !slot_up(k.slot_dash) || fuel() < tune::HD_MIN_FUEL)
		return false;
	if (!heart_dash_try_budget(keep))
		return false;
	const int rad = std::max(1, static_cast<int>(k.dash_radius));
	const int dr = heart_dash_reach(k);
	alignas(vec2) unsigned char en_raw[tune::HD_FOE_LIST_MAX * sizeof(vec2)];
	alignas(HdCamp) unsigned char cs_raw[tune::HD_CAMP_LIST_MAX * sizeof(HdCamp)];
	alignas(HdLanding) unsigned char cand_raw[tune::HD_LANDINGS_MAX * sizeof(HdLanding)];
	HdScan s{ W.me.pos, rad, dr, dr + rad, reinterpret_cast<vec2*>(en_raw), reinterpret_cast<HdCamp*>(cs_raw),
		reinterpret_cast<HdLanding*>(cand_raw) };
	heart_dash_list_foes(s);
	heart_dash_list_camps(s);
	if (!(s.any || (s.n_awake > 0 && !s.foe6)) || econ::busy_capturing())
		return false;
	for (int dx = -dr; dx <= dr; ++dx)
		for (int dy = -dr; dy <= dr; ++dy)
			heart_dash_try_add_landing(s, keep, { s.me.x + dx, s.me.y + dy });
	if (s.nca == 0)
		return false;
	std::sort(s.cand, s.cand + s.nca, [](const HdLanding& x, const HdLanding& y) { return x.sc > y.sc; });
	return heart_dash_cast_best_landing(k, s);
}
__attribute__((noinline)) bool heart_dash_end_slow()
{
	if (!W.can_attack())
		return true;
	const Body* t = nullptr;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit) && (!t || eff_hp(e) < eff_hp(*t)))
			t = &e;
	if (t)
	{
		const Body target = *t;
		attack_champion(target);
		return true;
	}
	int bc = -1;
	float bh = 1e9f;
	for (const auto& vc : W.camps)
	{
		if (vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
			continue;
		// Every camp in my basic reach stands inside the landing's radius (melee range 1 = radius 1), so the landing just hit and woke it:
		// the turn-start awake flag (gem and gold clusters the landing cleared) does not gate the hit; a living one only.
		if (cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, W.me.pos) <= W.me.range && !(vc.awake || cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, W.me.pos) <= static_cast<int>(W.me.kit->dash_radius)))
			continue;
		if (cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, W.me.pos) <= W.me.range && vc.hp < bh && camps::camp_alive_in_engine(vc.ci))
		{
			bh = vc.hp;
			bc = vc.ci;
		}
	}
	if (bc >= 0)
		attack_camp(bc);
	return true;
}
__attribute__((noinline)) bool linked_pair_cast_kill_slow(int site)
{
	const Body* t = nullptr;
	vec2 c{ -1, -1 };
	const int s = pair::pick_spell_kill_foe(site, t, c);
	if (s < 0 || !t)
		return false;
	return s == W.me.kit->slot_aoe ? cast_at(s, c) : cast_on_champion(s, *t);
}
// v699 R2G bit 1 ESL1 (X134): I carry a lock and the carrier's altar is within one step of lock range (2, GR:328): game_deny steps and
// locks (the lock blocks the restart, GR:240), so end_stun's stun yields to it.
static bool esl_lock_way_near(const Body& e)
{
	if (deny::locks_carried() <= 0)
		return false;
	for (const auto& al : M.altars)
		if (cheb(al.pos, e.pos) <= 1 && cheb(al.pos, W.me.pos) <= 3)
			return true;
	return false;
}
// v703 R3G bit 1 (GDP1/ESL1 re-arm, C33/X144). RGA1: our lock cancels a mate's running tribute at that altar (INT:120, GR:240), so
// neither lock route fires there.
static bool rga_ally_tributing(vec2 alt)
{
	for (const auto& al : W.allies)
		if ((al.state & ST_TRIBUTE) && cheb(al.pos, alt) <= 1)
			return true;
	return false;
}
// v703 R3G bit 1 ESL1 + RGY1: end_stun's game-ending stun yields to game_deny's lock way only when that way will act: I carry a lock,
// can still walk this turn, fewer than GD_BODIES mates go ahead, the carrier's nearest altar is within 3 of me and no mate tributes
// there; else end_stun stuns as before.
static bool esl2_lock_way_near(const Body& e)
{
	if (deny::locks_carried() <= 0 || !W.can_move() || W.moved)
		return false;
	const AltarI* best = nullptr;
	for (const auto& al : M.altars)
		if (!best || cheb(al.pos, e.pos) < cheb(best->pos, e.pos))
			best = &al;
	if (!best || cheb(best->pos, e.pos) > 1 || cheb(best->pos, W.me.pos) > 3 || rga_ally_tributing(best->pos))
		return false;
	std::int32_t left = 0;
	if (cambc::detail::sdk_champion_channel_time(e.h, &left) != 0 || left < 0)
		left = 1;
	return deny::game_deny_mates_ahead(e.pos, best->pos, cheb(e.pos, W.me.pos), std::max(1, static_cast<int>(left)), true) < GD_BODIES;
}
__attribute__((noinline)) bool end_stun_slow()
{
	const Body* st = nullptr;
	bool rich = false;
	for (const auto& e : W.enemies)
		if ((e.state & ST_TRIBUTE) && !e.stunned && marcella_layer::fight_stun_holds(e))
		{
			if (W.tributed_them + static_cast<int>(e.gems) >= rs::WIN_TRIBUTE)
			{
				st = &e;
				break;
			}
			if (e.gems >= CS_BAG)
				rich = true;
		}
	bool cs = false;
	if (rich && !W.me.channeling() && W.me.gems < CS_MYBAG)
	{
		cs = true;
		if (W.me.frac() * 100.0f < CS_HP_X100)
			for (const auto& e : W.enemies)
				if (!e.channeling() && cheb(e.pos, W.me.pos) <= 2)
				{
					cs = false;
					break;
				}
	}
	if (!st && !cs)
		return false;
	const Kit& k = *W.me.kit;
	if (k.slot_cc < 0 || !ready(k.slot_cc))
		return false;
	if (st)
		for (const auto& e : W.enemies)
			if ((e.state & ST_TRIBUTE) && W.tributed_them + static_cast<int>(e.gems) >= rs::WIN_TRIBUTE && !e.stunned && marcella_layer::fight_stun_holds(e) &&
				cheb(e.pos, W.me.pos) <= static_cast<int>(k.cc_range) && !(R2G_ON(1) && esl_lock_way_near(e)) && !(R3G_ON(1) && esl2_lock_way_near(e)) && cast_on_champion(k.slot_cc, e)) // v699 R2G bit 1 ESL1; v703 R3G bit 1
			{
				if (R2G_ON(1) || R3G_ON(1)) // v703 R3G bit 1
				{
					r2g_stun_h = e.h; // v699 R2G bit 1 ESL1: game_deny reads this carrier's dropped channel as cancelled
					r2g_stun_r = W.round;
				}
				NLOG("r%d slot %d end-stun gems %u tt %d\n", W.round, P.my_slot, e.gems, W.tributed_them);
				return true;
			}
	if (cs)
	{
		const Body* best = nullptr;
		for (const auto& e : W.enemies)
			if ((e.state & ST_TRIBUTE) && e.gems >= CS_BAG && !e.stunned && marcella_layer::fight_stun_holds(e) &&
				cheb(e.pos, W.me.pos) <= static_cast<int>(k.cc_range) && (!best || e.gems > best->gems))
				best = &e;
		if (best && cast_on_champion(k.slot_cc, *best))
		{
			NLOG("r%d slot %d chan-stun gems %u\n", W.round, P.my_slot, best->gems);
			return true;
		}
	}
	return false;
}
__attribute__((noinline)) bool support_move_slow(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	const int hr = static_cast<int>(k.heal_range);
	const Body* best = nullptr;
	float best_v = 0;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (d > 10 || d <= hr || al.channeling() || al.frac() > 0.6f)
			continue;
		bool busy = mv::camp_threat(al.pos) > 0;
		for (const auto& e : W.enemies)
			if (cheb(e.pos, al.pos) <= 6)
				busy = true;
		if (!busy)
			continue;
		float v = (1.0f - al.frac()) * al.maxhp / static_cast<float>(d);
		if (al.kit && (heart_layer::kit(*al.kit) || prism_layer::kit(*al.kit)))
			v *= 1.5f; // the carries: Heart of Ruin at its sweet spot, a loaded Prism
		if (v > best_v)
		{
			best_v = v;
			best = &al;
		}
	}
	if (!best)
		return false;
	// Do not walk into a foe's burst on the way.
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!mv::free_tile(t) || cheb(t, best->pos) >= cheb(W.me.pos, best->pos))
			continue;
		if (geom::danger_veto(a, t) >= 0.2f * eff_hp(W.me)) // a veto
			continue;
		if (mv::try_move(t))
			return true;
	}
	return false;
}
} // namespace
// r3: a support stepping from distance d to d-1 of focus f would be the front line unless an ally stands at least a
// tile nearer to f than that. True: hold back (heal and shoot from where it is).
bool support_hold_back(const Body& f, int d)
{
	if (stance::kill_window(f) && f.frac() < 0.3f)
		return false; // a free finishing shot
	for (const auto& al : W.allies)
		if (!al.channeling() && al.hp > 0 && cheb(al.pos, f.pos) <= d - 2)
			return false;
	return true;
}
// Spells on champions in every stance.
bool xc_stunnable(const Body& e) { return !e.stunned && marcella_layer::fight_stun_holds(e); }
// An area-spell target tile within `range` of me that tile_ok passes and whose `rad` covers the most foes (one at least) not on
// their own spawn, never next to a sleeping attacker of a camp group (it would wake the group). {-1,-1} if none covers an enemy;
// bn: foes covered. Only tiles within `rad` of a foe seed_ok passes are tried (cheap: at most enemies x 9 tiles for radius 1).
template <class SeedOk, class TileOk>
static __attribute__((always_inline)) inline vec2 aoe_best_tile(int range, int rad, int& bn, SeedOk&& seed_ok, TileOk&& tile_ok)
{
	vec2 bt{ -1, -1 };
	bn = 0;
	const vec2 me = W.me.pos;
	for (const auto& c : W.enemies)
	{
		if (!seed_ok(c))
			continue;
		for (int dx = -rad; dx <= rad; ++dx)
			for (int dy = -rad; dy <= rad; ++dy)
			{
				const vec2 t{ c.pos.x + dx, c.pos.y + dy };
				if (!inb(t) || cheb(t, me) > range)
					continue;
				int n = 0;
				for (const auto& o : W.enemies)
					n += cheb(o.pos, t) <= rad && !bbget(M.enemy_spawn, o.pos) ? 1 : 0;
				if (n > bn && tile_ok(t) && !AreaGrid::wakes_other(t, rad, -1) && !(W.me.kit && kit_rules::ren_retaliation_of_cast(W.me.kit->slot_aoe, 0u, 0u, t) >= eff_hp(W.me))) // the wake test only for a better tile; BB12 RENT
				{
					bn = n;
					bt = t;
				}
			}
	}
	return bt;
}
vec2 area_tile_covering_all(const std::vector<const Body*>& must, int range, int radius)
{
	const vec2 me = W.me.pos;
	int bn = 0;
	return aoe_best_tile(range, radius, bn, [&](const Body& c) { return cheb(c.pos, me) <= range + radius; }, [&](vec2 t)
	{
		for (const Body* b : must)
			if (cheb(b->pos, t) > radius)
				return false;
		return true;
	});
}
// THR bit 1 (Rule Checker THR1): a melee foe reaches range + 1 this turn (step and hit, GR:161); true when one of our bodies is there.
bool thr_melee_threat(const Body& e)
{
	if (!e.kit || e.kit->ranged)
		return false;
	const int r = std::max(1, e.range) + 1;
	if (cheb(e.pos, W.me.pos) <= r)
		return true;
	for (const auto& al : W.allies)
		if (cheb(e.pos, al.pos) <= r)
			return true;
	return false;
}
namespace {
// f dies to my burst this turn, and not to the basic hit alone: the burst needs the turn's one cast.
// a stunnable foe in my stun's range has a body of ours in its reach (it keeps the stun).
static bool stunnable_foe_has_ally_in_reach()
{
	const Kit& k = *W.me.kit;
	for (const auto& e : W.enemies)
	{
		if (e.stunned || marcella_layer::fight_stun_wasted(e) || foe_model::unreachable(e) || cheb(e.pos, W.me.pos) > static_cast<int>(k.cc_range))
			continue;
		bool threat = cheb(e.pos, W.me.pos) <= std::max(1, e.range);
		for (const auto& al : W.allies)
			threat |= cheb(e.pos, al.pos) <= std::max(1, e.range);
		if (!threat && cast::thr_melee_threat(e)) // THR bit 1: a melee foe's step + hit
			threat = true;
		if (threat)
			return true;
	}
	return false;
}
} // namespace
// melee damaging stun on a stun-immune focus, for the damage only: a lethal cast, or from where I already hit it (the cast excludes
// the walk) when no stunnable foe in range has a body of ours in its reach (that foe keeps the stun; the cast goes on it below).
static bool stun_cast_for_damage_only(const Body& f, int d)
{
	const Kit& k = *W.me.kit;
	if (k.cc_mod <= 0 || !marcella_layer::fight_stun_wasted(f) || d > static_cast<int>(k.cc_range))
		return false;
	if (eff_hp(f) <= k.cc_mod * burst::spell_on(burst::spell_base(), f))
		return true;
	return d <= W.me.range && !stunnable_foe_has_ally_in_reach();
}
// a ranged damaging stun on a non-lethal immune focus does the same damage on the stunnable threat, and the stun lands.
static bool stun_threat_instead_of_focus(const Body& f)
{
	const Kit& k = *W.me.kit;
	return marcella_layer::fight_stun_wasted(f) && eff_hp(f) > k.cc_mod * burst::spell_on(burst::spell_base(), f) && stunnable_foe_has_ally_in_reach();
}
static bool kill_needs_dash(const Body& f, int d)
{
	const float h = eff_hp(f);
	return burst::kills(f, d, KQ_RAW) && !burst::kills(f, d, KQ_STEP) && burst::dash_kill_reachable(f, d);
}
// The kill dash's crowd bar: my own tile's crowd.
static int kill_dash_crowd_bar(const Body& f, bool fr, vec2 best, int best_s)
{
	int kdg_here = 1;
	if (fr && best.x >= 0 && best_s > 1)
	{
		kdg_here = 0;
		for (const auto& e : W.enemies)
			if (e.h != f.h && cheb(e.pos, W.me.pos) <= 2)
				++kdg_here;
		kdg_here = std::max(1, kdg_here);
	}
	return kdg_here;
}
// a ranged body that cannot leave every reach this turn is hit next turn whatever it does, so it hits
// the weakest foe in its range instead of a step (a ranged attack excludes walking). True if it hit.
// the damage spell on top of a hit that did not walk (true if cast).
// the area spell on the tile covering the most foes (one at least) not on their own spawn; never wakes a
// sleeping camp. True if cast.
bool free_aoe()
{
	const Kit& k = *W.me.kit;
	if (W.cast || W.me.channeling() || k.slot_aoe < 0 || k.aoe_mod <= 0 || !ready(k.slot_aoe) || (k.aoe_excl && W.moved))
		return false;
	int bn = 0;
	const vec2 bt = aoe_best_tile(static_cast<int>(k.aoe_range), std::max(0, static_cast<int>(k.aoe_radius)), bn, [](const Body&) { return true; }, [](vec2) { return true; });
	return bn >= 1 && bt.x >= 0 && cast_at(k.slot_aoe, bt);
}
bool free_cast()
{
	const Kit& k = *W.me.kit;
	if (W.cast || W.me.channeling())
		return false;
	if (k.slot_dmg < 0 || k.dmg_mod <= 0 || !ready(k.slot_dmg) || (k.dmg_excl && W.moved))
	{
		if (k.slot_dmg < 0 && k.slot_cc >= 0 && k.cc_mod > 0 && ready(k.slot_cc) && !(k.cc_excl && W.moved))
		{
			const Body* c = nullptr;
			for (const auto& e : W.enemies)
			{
				if (cheb(e.pos, W.me.pos) > static_cast<int>(k.cc_range) || foe_model::unreachable(e) || bbget(M.enemy_spawn, e.pos))
					continue;
				if (ren_layer::kills_me(e))
					continue;
				if (!c || eff_hp(e) < eff_hp(*c))
					c = &e;
			}
			if (c && cast_on_champion(k.slot_cc, *c))
				return true;
		}
		return free_aoe();
	}
	const Body* t = nullptr;
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > static_cast<int>(k.dmg_range) || foe_model::unreachable(e) || bbget(M.enemy_spawn, e.pos))
			continue;
		if (ren_layer::kills_me(e))
			continue;
		if (!t || eff_hp(e) < eff_hp(*t))
			t = &e;
	}
	return (t && cast_on_champion(k.slot_dmg, *t)) || free_aoe();
}
// the basic attack on top of a cast that stays (true if hit).
bool free_attack()
{
	if (W.attacked || !W.can_attack() || W.me.channeling())
		return false;
	const Body* t = nullptr;
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > W.me.range || foe_model::unreachable(e) || bbget(M.enemy_spawn, e.pos))
			continue;
		if (ren_layer::kills_me(e))
			continue;
		if (!t || eff_hp(e) < eff_hp(*t))
			t = &e;
	}
	return t && attack_champion(*t);
}
} // namespace cast
void heart_dash_arm(bool on)
{
	cast::hd_round = on ? W.round : -1;
	cast::hd_holdf = false;
}
void hd_hold(bool h) { cast::hd_holdf = h; }
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool heart_dash_try(vec2 keep)
{
	if (cast::hd_round != W.round || cast::hd_holdf || !W.alive || !W.me.kit || W.me.channeling() || bh57_noreset) // BB14 HDE: the turn's cast is held
		return false;
	return cast::heart_dash_try_slow(keep);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool heart_dash_end()
{
	if (!heart_dash_try({ -1, -1 }))
		return false;
	return cast::heart_dash_end_slow();
}
// A foe other than b that a hit can land on now.
static __attribute__((always_inline)) inline bool other_foe_in_reach(const Body& e, const Body& b)
{
	return e.h != b.h && cheb(e.pos, W.me.pos) <= W.me.range && !foe_model::unreachable(e) && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit) && !(ren_layer::kills_me(e));
}
// The lowest-HP such foe still alive, or null.
static __attribute__((always_inline)) inline const Body* weakest_other_foe_in_reach(const Body& b)
{
	const Body* alt = nullptr;
	for (const auto& e : W.enemies)
	{
		if (!other_foe_in_reach(e, b) || (alt && eff_hp(e) >= eff_hp(*alt)))
			continue;
		std::int32_t al = 1;
		if (cambc::detail::sdk_champion_is_alive(e.h, &al) == 0 && al != 0)
			alt = &e;
	}
	return alt;
}
// CBH 32 VAK1 (caller read the flag): Varg's no-wake side-hit choice with the engine's alive read, as weakest_other_foe_in_reach does.
static __attribute__((noinline)) const Body* cbh_vak_alt(const Body& b)
{
	const Body* alt = nullptr;
	for (const auto& e : W.enemies)
	{
		if (e.h == b.h || e.hp <= 0 || cheb(W.me.pos, e.pos) > W.me.range || camps::wakes_other_group(e.pos, 1, W.me.pos, -1, 0.0f) || (alt && eff_hp(e) >= eff_hp(*alt)))
			continue;
		std::int32_t al = 1;
		if (cambc::detail::sdk_champion_is_alive(e.h, &al) == 0 && al != 0)
			alt = &e;
	}
	return alt;
}
bool attack_champion(const Body& b)
{
	if (cheb(W.me.pos, b.pos) > W.me.range)
		return false;
	if (ren_layer::kills_me(b))
		return false; // its retaliation would kill me
	if (W.cast && W.can_attack())
	{
		// my cast this turn may have killed the target. No other foe to hit, or none alive: no read and no change.
		bool dfo_any = false;
		for (const auto& e : W.enemies)
			if (other_foe_in_reach(e, b))
			{
				dfo_any = true;
				break;
			}
		std::int32_t alive = 1;
		if (dfo_any && cambc::detail::sdk_champion_is_alive(b.h, &alive) == 0 && alive == 0)
		{
			const Body* alt = weakest_other_foe_in_reach(b);
			if (alt)
				return attack_champion(*alt); // alt lives, so this call goes on to the normal hit
		}
	}
	const bool hd = heart_dash_try(b.pos); // the landing first (it keeps b in range)
	if (cheb(W.me.pos, b.pos) > W.me.range)
		return hd;
	if (varg_layer::fight_nowake())
	{
		// The splash must not wake a dangerous sleeping group onto us.
		const bool rs = W.me.kit->slot_reset >= 0 && !W.cast && ready(W.me.kit->slot_reset);
		const float kd = W.me.str * (kit_rules::camp_damage_factor()) * (rs ? 2.0f : 1.0f); // KTB16: champion damage
		if (camps::wakes_other_group(b.pos, 1, W.me.pos, -1, 0.0f))
		{
			const Body* alt = nullptr;
			for (const auto& e : W.enemies)
				if (e.h != b.h && e.hp > 0 && cheb(W.me.pos, e.pos) <= W.me.range && !camps::wakes_other_group(e.pos, 1, W.me.pos, -1, 0.0f) &&
					(!alt || eff_hp(e) < eff_hp(*alt)))
					alt = &e;
			if (alt)
				alt = cbh_vak_alt(b); // CBH 32 VAK1: a foe my hit or cast killed this turn reads hp > 0 in the turn-start list
			if (alt)
			{
				if (!cast::attack_via_sdk(KIND_CHAMPION, alt->h))
					return hd;
				if (rs && ((alt->hp + alt->shield > 2.0f * W.me.str || rgf_alive(alt->h))) && !(ren_layer::kills_me_twice(*alt)) &&
				    cast_self(W.me.kit->slot_reset))
					cast::attack_via_sdk(KIND_CHAMPION, alt->h);
				return true;
			}
			if (camps::wakes_other_group(b.pos, 1, W.me.pos, -1, kd))
				return hd;
		}
	}
	// Every champion hit is attack, reset, attack while the target survives the first (a ready reset left unused loses a hit).
	if (!cast::attack_via_sdk(KIND_CHAMPION, b.h))
	{
		static bool kca_busy = false; // one retry: a live foe refusing the hit must not start a chain
		static int kca_round = -1;    // FXR bits 1/2: kca_busy left set by an unwound retry (AfBail, RestartTurn) clears once a turn
		if (kca_round != W.round)
		{
			if (kca_busy)
			{
				++fxr_kca_stuck; // FXR-DG-KCA
			}
			kca_busy = false;
			kca_round = W.round;
		}
		if (!kca_busy && W.can_attack()) // v705 AFR bit 1: any refusal (rc 42 too) retries once on another foe
			if (const Body* alt = weakest_other_foe_in_reach(b))
			{
				kca_busy = true;
				const bool kca_hit = attack_champion(*alt);
				kca_busy = false;
				return kca_hit || hd;
			}
		return hd;
	}
	if (W.me.kit && W.me.kit->slot_reset >= 0 && !W.cast && !bh57_noreset && ready(W.me.kit->slot_reset) && ((eff_hp(b) > 2.0f * W.me.str || rgf_alive(b.h))) &&
	    !(ren_layer::kills_me_twice(b)) && // two retaliations
		cast_self(W.me.kit->slot_reset))
		cast::attack_via_sdk(KIND_CHAMPION, b.h);
	if (vendetta_layer::fight_kill_refresh())
		camps::refresh_cooldowns(); // a kill refunded her cooldowns
	return true;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool linked_pair_cast(int site)
{
	if (!W.alive || !W.me.kit || W.cast || W.me.channeling() || W.enemies.empty()) // FB5 LPE1
		return false;
	return cast::linked_pair_cast_kill_slow(site);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool end_stun()
{
	if (W.enemies.empty() || !W.alive)
		return false;
	return cast::end_stun_slow();
}
bool fight_map()
{
	static int cached = -1;
	if (cached >= 0)
		return cached == 1;
	if (!M.ready() || M.groups.empty())
		return false;
	static std::int64_t fmp_no = -1; // X2I bit 128 FMP1: the distance stamp of the last no-result scan
	if (fmp_no == M.dist_stamp())
		return false;
	// Spawn-to-spawn walk (through the nearest group between them) and the gem share of central groups.
	int walk = BIG;
	float central = 0, total = 0;
	for (const auto& g : M.groups)
	{
		if (g.d_home == UNREACH || g.d_enemy == UNREACH)
			continue;
		walk = std::min(walk, static_cast<int>(g.d_home) + static_cast<int>(g.d_enemy));
		total += static_cast<float>(g.gems);
		if (g.contest >= 0.38f && g.contest <= 0.62f)
			central += static_cast<float>(g.gems);
	}
	if (total <= 0)
	{
		fmp_no = M.dist_stamp();
		return false;
	}
	const float share = central / total;
	cached = ((walk <= 40 && share >= 0.25f) || (walk <= 60 && share >= 0.5f)) ? 1 : 0;
	NLOG("fight_map walk %d central %.2f -> %d\n", walk, share, cached);
	return cached == 1;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool support_move(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	if (!willow_layer::move_support(k) || !W.can_move() || W.cd[static_cast<std::size_t>(k.slot_heal)] > 2 || W.me.frac() < 0.5f)
		return false;
	return cast::support_move_slow(a);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool try_heal()
{
	const Kit& k = *W.me.kit;
	if (k.slot_heal < 0 || !ready(k.slot_heal))
		return false;
	return support::wl2_heal(); // WL2: one heal rule
}
} // namespace nova::combat
