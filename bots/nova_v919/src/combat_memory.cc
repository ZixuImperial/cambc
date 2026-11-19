// combat_memory.cc: Observe and the per-round combat trackers.
#include "combat_internal.h"
namespace nova::combat {
namespace memory
{
namespace tune
{
// Constants for observing foes each turn (sightings, forgetting, deaths).
inline constexpr float OBS_HP_EPS = 0.5f; // a change of health or shield smaller than this is noise
inline constexpr int OBS_SIGHT_D = 10; // an enemy this near goes into the sightings
inline constexpr int OBS_FORGET_ROUNDS = 8; // a sighting older than this is dropped
inline constexpr int OBS_DEAD_NEAR_D = 8; // an enemy this near a death keeps the blacklists up
inline constexpr int OBS_DEAD_RECENT_ROUNDS = 4; // a sighting counts for that if no older than this
}
namespace {
// ---------------------------------------------------------------- survival memory

float last_eff = -1.0f;   // my health + shield at my previous turn start
int last_eff_round = -10;
bool was_recalling = false;
// ---------------------------------------------------------------- memory

// A dead team mate counts only if I saw it within FULL_TEAM_NEAR tiles of me in the FULL_TEAM_RECENT rounds before (one that would
// have been in this fight); counting a dead mate anywhere on the map would stop every body from starting or joining a fight against
// 2+ enemies below 1.5 long after a death. Positions come from my sight each turn.
std::array<vec2, 8> ft_pos{};
// An ally under fire: its HP fell since my last turn while a visible enemy champion stood within that foe's range + 1 of it.
// peel_hit[slot] is the round I saw that.
std::array<float, 8> peel_hp{};
// The chased low foe I last saw, kept while it is out of sight.
std::uint32_t bkc_h = 0;
int bkc_r = -1000;
int bkc_foc_h = -1, bkc_foc_r = -1000; // my last fight focus
static int bkc_bushy = -1; // 1 = the map has a bush tile, 0 = none, -1 = not read yet
// The raw stance of the last 4 turns; after CALM FLEE CALM a soft flee stays CALM (latch FLC_HOLD rounds).
int sf_hr[4] = { -9, -9, -9, -9 };
int sf_until = -1;
int bc_until = -1;
void team_track()
{
	for (const auto& al : W.allies)
		if (al.slot >= 0 && al.slot < 8)
		{
			ft_pos[static_cast<std::size_t>(al.slot)] = al.pos;
			ft_seen[static_cast<std::size_t>(al.slot)] = W.round;
		}
}
void track_foe_hp_drops()
{
	for (const auto& e : W.enemies)
	{
		CtHp* m = nullptr;
		for (auto& c : ct_hp)
			if (c.h == e.h)
			{
				m = &c;
				break;
			}
		const float hp = eff_hp(e);
		if (m && W.round - m->round <= 2 && hp < m->hp - 1.0f)
			for (const auto& al : W.allies)
			{
				if (al.slot >= 0 && al.slot < 8 && cheb(al.pos, e.pos) <= al.range)
					ct_back[static_cast<std::size_t>(al.slot)] = W.round;
				if (cheb(al.pos, e.pos) <= 2)
					m->mate_hit = W.round;
			}
		if (m)
		{
			m->hp = hp;
			m->round = W.round;
		}
		else if (ct_hp.size() < 16)
			ct_hp.push_back({ e.h, hp, W.round });
	}
}
void track_ally_hits_for_peel()
{
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= 8)
			continue;
		const auto i = static_cast<std::size_t>(al.slot);
		const float eh = eff_hp(al);
		if (W.round - peel_seen[i] <= 2 && eh < peel_hp[i] - 1.0f)
			for (const auto& e : W.enemies)
				if (cheb(e.pos, al.pos) <= e.range + 1)
				{
					peel_hit[i] = W.round;
					break;
				}
		peel_hp[i] = eh;
		peel_seen[i] = W.round;
	}
}
static bool bush_chase_near_spawn(vec2 p)
{
	const int R = BKC_TAB[5];
	for (int dx = -R; dx <= R; ++dx)
		for (int dy = -R; dy <= R; ++dy)
		{
			const vec2 q{ p.x + dx, p.y + dy };
			if (inb(q) && bbget(M.enemy_spawn, q))
				return true;
		}
	return false;
}
void bush_chase_track()
{
	if (!bush_chase_active())
	{
		bkc_r = -1000; // nothing to chase into on this map
		return;
	}
	if (!W.alive)
	{
		bkc_r = -1000;
		return;
	}
	const int now = W.round;
	const vec2 me = W.me.pos;
	const float hp = static_cast<float>(BKC_TAB[2]) / 100.0f;
	if (bkc_r > -1000 && intel::foe_died_round(bkc_h) >= bkc_r)
		bkc_r = -1000; // it died
	int bi = -1;
	float bf = hp;
	const bool xic_bct = XIC_ON(1024);
	const bool foc_fresh = xic_bct && now - bkc_foc_r <= 2; // only with XIC bit 1024
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		if (bkc_r > -1000 && e.h == bkc_h)
		{
			if (e.frac() >= hp)
				bkc_r = -1000; // The chased foe is seen again and no longer low: forget it.
			else
			{
				bkc_r = now; // seen again: refresh
				bkc_pos = e.pos;
			}
		}
		if (xic_bct && !(static_cast<int>(e.h) == bkc_foc_h && foc_fresh))
			continue; // v723 XIC bit 1024 BCT1: the focus match first (all five tests are pure reads)
		if (cheb(e.pos, me) > 6 || e.frac() >= bf || bbget(M.enemy_spawn, e.pos))
			continue;
		if (!(static_cast<int>(e.h) == bkc_foc_h && now - bkc_foc_r <= 2))
			continue;
		bf = e.frac();
		bi = static_cast<int>(i);
	}
	if (bi >= 0)
	{
		const auto& e = W.enemies[static_cast<std::size_t>(bi)];
		bkc_h = e.h;
		bkc_r = now;
		bkc_pos = e.pos;
	}
}
// My health against last turn: a loss that is not a shield running out marks the round as damaged.
static __attribute__((always_inline)) inline void observe_damage(int now)
{
	const float eff = W.me.hp + W.me.shield;
	static float se_hp = 0.0f, se_sh = 0.0f; // my HP and shield last turn
	static int se_turns = 0;
	const bool se_expired = se_sh > tune::OBS_HP_EPS && se_turns <= 1 && W.me.shield <= tune::OBS_HP_EPS && W.me.hp >= se_hp - tune::OBS_HP_EPS;
	se_hp = W.me.hp;
	se_sh = W.me.shield;
	se_turns = W.me.shield_turns;
	if (!se_expired && last_eff >= 0 && last_eff_round >= now - 1 && eff < last_eff - tune::OBS_HP_EPS)
	{
		dmg_round = now;
		turn_memory.hp_lost_at_dmg_round = last_eff - eff;
	}
	last_eff = eff;
	last_eff_round = now;
}
// A recall that stopped away from my spawn was cancelled.
static __attribute__((always_inline)) inline void observe_recall(int now)
{
	const bool recalling = (W.me.state & ST_RECALL) != 0;
	if (was_recalling && !recalling && !W.on_spawn)
	{
		NLOG("r%d slot? recall cancelled hp %.0f\n", now, W.me.hp);
	}
	was_recalling = recalling;
}
// v7xx MBB7 bit 2 RHS1 (caller reads the flag): e's effective HP at full health with no shield (eff_hp's units).
static __attribute__((noinline)) float rhs1_full_ehp(const Body& e)
{
	Body c = e;
	c.hp = c.maxhp;
	c.shield = 0;
	return eff_hp(c);
}
static void rfv_note(std::uint32_t h, int now); // RFV bit 1 (below)
// Enemy sightings: refresh the visible ones, forget old ones.
static __attribute__((always_inline)) inline void observe_sightings(int now)
{
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		if (cheb(e.pos, W.me.pos) > tune::OBS_SIGHT_D)
			continue;
		Seen* s = nullptr;
		for (auto& x : seen)
			if (x.h == e.h)
			{
				s = &x;
				break; // handles are unique in seen (pushed only when missing)
			}
		if (!s)
		{
			seen.push_back({});
			s = &seen.back();
			s->h = e.h;
		}
		s->round = now;
		s->rec = (e.state & ST_RECALL) != 0;
		if (s->rec)
			rfv_note(e.h, now); // RFV bit 1 (RFE1): the round its recall can land
		s->foe = (e.stunned) ? foe_of_unstunned(e, -1) : foe_of(e, -1); // CB3 bit 32 R1
		s->ehp_full = rhs1_full_ehp(e);
		s->body = e; // b2387 TTCX bit 1
	}
	seen.erase(std::remove_if(seen.begin(), seen.end(), [&](const Seen& s) { return now - s.round > tune::OBS_FORGET_ROUNDS; }), seen.end());
}
// RFV bit 1 RFE1 (callers read the flag): the round a foe seen recalling can land at the earliest (now + ticks left + 1: it may act after
// me this round). A recaller whose tile empties before that cancelled (by hand, damage or stun) and walked off: it is still near.
static std::uint32_t rfv_h[16] = { 0 };
static int rfv_land[16] = { 0 };
static void rfv_note(std::uint32_t h, int now)
{
	std::int32_t left = 0;
	if (cambc::detail::sdk_champion_channel_time(h, &left) != 0 || left < 0)
		left = 0;
	int slot = -1;
	for (int i = 0; i < 16 && slot < 0; ++i)
		if (rfv_h[i] == h)
			slot = i;
	for (int i = 0; i < 16 && slot < 0; ++i)
		if (rfv_h[i] == 0 || rfv_land[i] < now - 20)
			slot = i;
	if (slot < 0)
		slot = static_cast<int>(h % 16u);
	rfv_h[slot] = h;
	rfv_land[slot] = now + static_cast<int>(left) + 1;
}
static __attribute__((noinline)) int rfv_land_of(std::uint32_t h)
{
	for (int i = 0; i < 16; ++i)
		if (rfv_h[i] == h)
			return rfv_land[i];
	return -1000;
}
static __attribute__((noinline)) void rfv_forget(int now)
{
	auto gone = [&](const Seen& s) { return s.rec && s.round < now && now >= rfv_land_of(s.h) && bbget(W.vis, s.foe.pos) && !bbget(W.occ_units, s.foe.pos); };
	bool any = false;
	for (const auto& s : seen)
		any |= gone(s);
	if (any)
		seen.erase(std::remove_if(seen.begin(), seen.end(), gone), seen.end());
}
// a recaller whose last tile I see empty has gone home.
static __attribute__((always_inline)) inline void observe_forget_recalled(int now)
{
	rfv_forget(now); // RFV bit 1 (RFE1): only once its recall could have landed
	return;
}
// Its blacklists are lifted when no other living enemy I know of is within OBS_DEAD_NEAR_D of where it died.
static __attribute__((always_inline)) inline void observe_death_at(vec2 p, int now)
{
	bool other = false;
	for (const auto& e : W.enemies)
		other |= cheb(e.pos, p) <= tune::OBS_DEAD_NEAR_D;
	for (const auto& s : seen)
		other |= now - s.round <= tune::OBS_DEAD_RECENT_ROUNDS && cheb(s.foe.pos, p) <= tune::OBS_DEAD_NEAR_D;
	if (!other)
		econ::lift_flee_blacklist(p);
	// only with no other enemy near, my ward's sightings included.
	for (const auto& e : W.enemies_far)
		other |= cheb(e.pos, p) <= tune::OBS_DEAD_NEAR_D;
	if (!other)
		econ::mark_groups_near_kill(p);
}
// a foe that died after my last sighting is no threat (it respawns at its home): left in this memory it adds to n_foes,
// incoming and the strength sums (FLEE), to threat_seen's blacklists and to hold_capture's test.
static __attribute__((always_inline)) inline void observe_forget_dead(int now)
{
	if (seen.empty())
		return;
	std::vector<vec2> dead_at;
	for (const auto& s : seen)
		if (intel::foe_died_round(s.h) >= s.round)
			dead_at.push_back(s.foe.pos);
	if (dead_at.empty())
		return;
	seen.erase(std::remove_if(seen.begin(), seen.end(), [&](const Seen& s) { return intel::foe_died_round(s.h) >= s.round; }),
		seen.end());
	for (const vec2 p : dead_at)
		observe_death_at(p, now);
}
// NO_WAKE's test for a walk dash's landing (me after the dash = L).
// NO_WAKE over the camps of groups that have a fogged camp tile within rad of L.
static bool fogged_camp_group_near_landing(vec2 L, int rad, int skip_g)
{
	if (M.camp_at.empty() || M.groups.empty())
		return false;
	const auto& mem = econ::memory();
	NwGroups gl;
	for (int y = L.y - rad; y <= L.y + rad; ++y)
		for (int x = L.x - rad; x <= L.x + rad; ++x)
		{
			const vec2 p{ x, y };
			const int ci = M.camp_index(p);
			if (!camps::nw_ci_ok(ci) || bbget(W.vis, p))
				continue;
			const int g = M.camps[static_cast<std::size_t>(ci)].group;
			if (!camps::group_has_attackers(g, skip_g))
				continue;
			if (static_cast<std::size_t>(g) < mem.size())
			{
				const auto& gm = mem[static_cast<std::size_t>(g)];
				if (gm.status == econ::GS_CLEARED || (gm.status == econ::GS_RESPAWN && gm.respawn_at > W.round))
					continue; // known dead
			}
			gl.add(g);
		}
	for (int i = 0; i < gl.ng; ++i)
	{
		const GroupI& gr = M.groups[static_cast<std::size_t>(gl.gs[static_cast<std::size_t>(i)])];
		bool awake = false;
		float str = 0;
		for (const int ci : gr.members)
		{
			if (!camps::nw_ci_ok(ci))
				continue;
			const auto& cp = M.camps[static_cast<std::size_t>(ci)];
			if (bbget(W.vis, cp.pos))
			{
				if (!bbget(W.occ_camps, cp.pos))
					continue; // seen empty: dead
				if (bbget(W.awake, cp.pos))
				{
					awake = true;
					break;
				}
			}
			if (cp.attacks() && camps::sleeping_attacker_counts(cp, L))
				str += cp.str;
		}
		if (!awake && camps::nw_wakes_at(str))
			return true;
	}
	return false;
}
} // namespace
bool ally_in_contact(const Assessment& a) { return mates::ally_in_contact_within(a, 5); }
// team mates dead right now (respawning), checked once a round (visible allies are alive).
int team_dead()
{
	static int r = -1, n = 0;
	if (r == W.round)
		return n;
	r = W.round;
	n = 0;
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == P.my_slot || W.ally_by_slot(s))
			continue;
		std::int32_t alive = 1;
		if (cambc::detail::sdk_champion_is_alive(P.handle[static_cast<std::size_t>(s)], &alive) == 0 && alive == 0)
		{
			const auto i = static_cast<std::size_t>(s);
			if (W.round - ft_seen[i] > FULL_TEAM_RECENT || cheb(ft_pos[i], W.me.pos) > FULL_TEAM_NEAR)
				continue; // died away from this fight
			++n;
		}
	}
	return n;
}
bool squad_mate_covers_focus(vec2 focus)
{
	// The near-me test first; squad::mates() (pure) only when a fit ally is not near me.
	bool any = false;
	for (const auto& al : W.allies)
	{
		if (al.channeling() || al.frac() < 0.3f)
			continue;
		if (cheb(al.pos, W.me.pos) <= 3)
			return true;
		any = true;
	}
	if (!any)
		return false;
	const unsigned mm = squad::mates(P.my_slot);
	for (const auto& al : W.allies)
	{
		if (al.channeling() || al.frac() < 0.3f)
			continue;
		if (al.slot >= 0 && al.slot < 8 && (mm & (1u << al.slot)) && cheb(al.pos, focus) <= al.range + 1)
			return true;
	}
	return false;
}
// Indices into W.camps of the awake camps, in W.camps order, once per perceive.
const std::vector<int>& awake_slots()
{
	static std::vector<int> k;
	static int st = -1;
	if (st != fg::pstamp)
	{
		st = fg::pstamp;
		k.clear();
		for (std::size_t i = 0; i < W.camps.size(); ++i)
			if (W.camps[i].awake)
				k.push_back(static_cast<int>(i));
	}
	return k;
}
} // namespace memory
void hunt_observe()
{
	return;
}
bool bush_chase_active()
{
	if (memory::bkc_bushy < 0)
	{
		if (!M.groups_ready())
			return true; // map not set up yet: decide later
		memory::bkc_bushy = bbany(M.bushes) ? 1 : 0;
	}
	return memory::bkc_bushy != 0;
}
void bush_chase_note_focus(int h)
{
	if (!bush_chase_active())
		return;
	memory::bkc_foc_h = h;
	memory::bkc_foc_r = W.round;
}
// v699 HPR bit 1 (spec_hpr_1110): the champions my attacks and casts hit this turn, re-read at turn end (only with HPR_ON(1)).
namespace memory
{
namespace
{
int hpr_r = -1000, hpr_nh = 0, hpr_np = 0;
std::array<std::uint32_t, 4> hpr_h{};
std::array<vec2, 4> hpr_p{};
}
} // namespace memory
void hpr_note(std::uint32_t h, vec2 p)
{
	if (memory::hpr_r != W.round)
	{
		memory::hpr_r = W.round;
		memory::hpr_nh = memory::hpr_np = 0;
	}
	if (h != 0 && memory::hpr_nh < 4)
		memory::hpr_h[static_cast<std::size_t>(memory::hpr_nh++)] = h;
	if (p.x >= 0 && memory::hpr_np < 4)
		memory::hpr_p[static_cast<std::size_t>(memory::hpr_np++)] = p;
}
bool hpr_pending() { return memory::hpr_r == W.round && (memory::hpr_nh > 0 || memory::hpr_np > 0) && W.alive; }
// HPU bit 1 HPRU1: a read HP in eff_hp's units (mu::ehp: x mi_inv under B_FULL), as combat_foes.cc stores it.
void hpu_flip()
{
}
float hpu_ehp(const Body& e, float raw)
{
	const float v = ((mu::bits & mu::B_FULL) != 0) ? raw * mu::mi_inv(e) : raw;
	if (v != raw)
		hpu_flip(); // a Durability foe: live stored this read ~10% low
	return v;
}
void hpr_refresh()
{
	const int now = W.round;
	// The hit targets' tiles join the area points (splash and radius-one spells reach the bodies next to a target).
	std::array<vec2, 8> pts{};
	int np = 0;
	for (int k = 0; k < memory::hpr_np; ++k)
		pts[static_cast<std::size_t>(np++)] = memory::hpr_p[static_cast<std::size_t>(k)];
	for (int k = 0; k < memory::hpr_nh; ++k)
		for (const auto& e : W.enemies)
			if (e.h == memory::hpr_h[static_cast<std::size_t>(k)] && np < 8)
				pts[static_cast<std::size_t>(np++)] = e.pos;
	memory::hpr_nh = memory::hpr_np = 0;
	const float bkc_hp = static_cast<float>(BKC_TAB[2]) / 100.0f;
	for (const auto& e : W.enemies)
	{
		bool hit = false;
		for (int k = 0; k < np && !hit; ++k)
			hit = cheb(e.pos, pts[static_cast<std::size_t>(k)]) <= 1;
		if (!hit)
			continue;
		cambc::detail::champion_info ci{};
		if (cambc::detail::sdk_champion(e.h, &ci) != 0 || ci.x < 0 || ci.y < 0 || (static_cast<std::uint32_t>(ci.state) & ST_ALIVE) == 0)
			continue; // dead (observe_forget_dead drops it) or out of sight: keep the entry
		float sh = 0.0f;
		if (e.shield > 0.0f)
		{
			std::array<cambc::detail::buff_data, 3> raw{};
			std::uint32_t cnt = 0;
			if (cambc::detail::sdk_champion_buff_data(e.h, raw.data(), static_cast<std::uint32_t>(raw.size()), &cnt) == 0)
				for (std::uint32_t i = 0; i < cnt && i < raw.size(); ++i)
					if (raw[i].type == 0)
						sh += raw[i].data.shield.value;
		}
		const float ehp = hpu_ehp(e, ci.health + sh); // HPU HPRU1: Durability-scaled
		if (ehp >= eff_hp(e) - memory::tune::OBS_HP_EPS)
			continue; // my hits did not lower it
		for (auto& s : seen)
			if (s.h == e.h && s.round == now)
			{
				s.foe.ehp = ehp;
				break;
			}
		const float fr = ci.health / (ci.max_health > 0 ? ci.max_health : 1.0f);
		if (static_cast<int>(e.h) == memory::bkc_foc_h && now - memory::bkc_foc_r <= 2 && fr < bkc_hp && cheb(e.pos, W.me.pos) <= 6
			&& !bbget(M.enemy_spawn, e.pos) && !(memory::bkc_r == now && memory::bkc_h != e.h) && bush_chase_active())
		{
			memory::bkc_h = e.h; // the chase BKC's turn-start test would have armed on the true HP
			memory::bkc_r = now;
			bkc_pos = e.pos;
		}
	}
}
vec2 bush_chase_target(const Assessment& a)
{
	vec2 none{ -1, -1 };
	if (!bush_chase_active())
		return none;
	const int now = W.round;
	const int age = now - memory::bkc_r;
	if (memory::bkc_r <= -1000 || age < 1 || age > BKC_TAB[3])
		return none;
	if (W.me.frac() * 100.0f < static_cast<float>(BKC_TAB[4]) || W.me.gems >= 40 || W.me.channeling() || !W.can_move())
		return none;
	if (intel::foe_died_round(memory::bkc_h) >= memory::bkc_r)
	{
		memory::bkc_r = -1000;
		return none;
	}
	const vec2 me = W.me.pos;
	bool near_foe = false;
	for (const auto& e : W.enemies)
	{
		if (e.h == memory::bkc_h)
			return none; // in sight: the fight code has it
		near_foe |= cheb(e.pos, me) <= 6;
	}
	if (near_foe)
		return none;
	if (memory::bush_chase_near_spawn(bkc_pos))
		return none;
	const int R = std::min(4, age + 1);
	vec2 best = none;
	int bd = BIG;
	bool any_bush = false;
	for (int dx = -R; dx <= R; ++dx)
		for (int dy = -R; dy <= R; ++dy)
		{
			const vec2 q{ bkc_pos.x + dx, bkc_pos.y + dy };
			if (!inb(q) || !bbget(M.bushes, q))
				continue;
			any_bush = true;
			if (bbget(CCX_ON(1) ? W.vis : W.own_vis, q) || bbget(M.enemy_spawn, q))
				continue;
			const int d = cheb(q, me);
			if (d < bd || (d == bd && cheb(q, bkc_pos) < cheb(best, bkc_pos)))
			{
				bd = d;
				best = q;
			}
		}
	if (!any_bush || best.x < 0 || bd > 7)
	{
		if (best.x < 0)
			memory::bkc_r = -1000; // every bush tile it could be in is in my sight: it is not there
		return none;
	}
	return best;
}
void observe()
{
	memory::track_ally_hits_for_peel(); // allies' HP each turn
	memory::track_foe_hp_drops();
	memory::team_track(); // where each team mate was last seen
	const int now = W.round;
	if (!W.alive)
	{
		memory::last_eff = -1.0f;
		memory::was_recalling = false;
		turn_memory.retreat_until = -1;
		return;
	}
	memory::observe_damage(now);
	memory::observe_recall(now);
	memory::observe_sightings(now);
	memory::observe_forget_recalled(now);
	memory::observe_forget_dead(now);
	hunt_observe();
	memory::bush_chase_track();
}
void fc_background(long) {}
bool hit_explained_by_camp()
{
	if (!took_damage(1))
		return true;
	const float ct = mv::camp_threat(W.me.pos);
	const bool ok = ct > 0 && turn_memory.hp_lost_at_dmg_round <= ct + 1.0f;
	return ok;
}
bool lw_bad(vec2 L, int rad, int skip_g) { return camps::wakes_other_group(L, rad, L, skip_g, 0.0f) || memory::fogged_camp_group_near_landing(L, rad, skip_g); }
void apply_flee_latch_and_history(Assessment& a)
{
	const int now = W.round;
	const bool raw = a.stance == FLEE;
	memory::sf_hr[now & 3] = now;
	sf_hf[now & 3] = raw;
	if (!raw && now <= memory::bc_until && a.stance == CALM && W.alive && static_cast<int>(W.me.gems) >= FLC_BAG && !a.foes.empty() && !W.me.channeling())
	{
		a.stance = FLEE; // A big bag keeps leaving instead of stepping back in.
		return;
	}
	if (!raw || !W.alive)
		return;
	auto was = [&](int r, bool f) { return memory::sf_hr[r & 3] == r && sf_hf[r & 3] == f; };
	if (static_cast<int>(W.me.gems) >= FLC_BAG && memory::bc_until < now && was(now - 1, false) && was(now - 2, true) && was(now - 3, false))
		memory::bc_until = now + BC_HOLD;
	int n8 = 0;
	for (const auto& f : a.foes)
		n8 += cheb(f.pos, W.me.pos) <= 8 ? 1 : 0;
	const bool soft0 = !a.caught && !a.in_reach && !W.me.channeling() && n8 <= 2 && static_cast<int>(W.me.gems) < FLC_BAG;
	bool soft = soft0 && W.me.frac() >= 0.75f && !took_damage(3) && a.nearest >= 4;
	if (!soft && soft0 && W.me.frac() >= 0.50f && !took_damage(2) && a.nearest >= 3)
		soft = true;
	if (!soft)
	{
		memory::sf_until = -1;
		return;
	}
	if (memory::sf_until < now && was(now - 1, false) && was(now - 2, true) && was(now - 3, false))
		memory::sf_until = now + FLC_HOLD;
	if (now <= memory::sf_until)
	{
		a.stance = CALM;
		sf_latched = now;
	}
}
namespace {
// b2387 TTCX bit 1 (caller read the flag): the remembered foe with every slot whose cooldown ran out since the sighting ready.
Foe ttc_remembered(const Seen& s, int age)
{
	if (age <= 0 || !s.body.kit)
		return s.foe;
	Body b = s.body;
	bool any = false;
	for (int k = 0; k < 2; ++k)
	{
		const int cd = b.cd[static_cast<std::size_t>(k)];
		if (cd > 0 && cd <= age)
		{
			b.cd[static_cast<std::size_t>(k)] = cd - age;
			any = true;
		}
	}
	if (!any)
		return s.foe;
	b.stunned = false;
	Foe f = foe_of(b, -1);
	f.ehp = s.foe.ehp;
	return f;
}
} // namespace
} // namespace nova::combat
