// contest_play.cc: Contested zone: how bodies play it. CONTEST: the zone plan, play side (see contest_play.h).
#include "contest_play.h"
#include <cmath>

#include <algorithm>

#include "combat.h"
#include "champions.h" // Kit layers.
#include "comms.h"
#include "econ.h"
#include "intel.h"
#include "mapinfo.h"
#include "move.h"
#include "plan.h"
#include "champ_willow.h"
#include "world.h"

namespace nova::zc {

// Runtime gate: the compiler cannot fold it, so builds with the plan flag 0 and 1 run the same instructions until the plan is on.
volatile int ct_plan_rt = CT_PLAN;
bool active_ = false; // ON or YIELDED (econ's fast path)

namespace {

enum Phase : int
{
	PH_OFF,
	PH_ON,
	PH_YIELDED,
	PH_DONE
};
enum ActT : int
{
	A_SEEN = 0,
	A_CALL = 1,
	A_YIELD = 2
};
constexpr int EV_CONTEST = 7;

zone::Block B;
bool ok = false;
int ph = PH_OFF;
int t_y = -1000, last_ev = -1000, seen_n = 0, seen_round = -1000, t_arrive = 0;
int t_done = -1000; // Round of the last hand-off.
int on_way_gi = -1; // My camp on the way to the first contest (-1: none).
bool on_way_tried = false; // The slack was checked once.
int race_checked = -1000; // Last round the race was computed for my detour.
int wave_at = -1; // The zone wave I left to farm until (-1: none).
int hold_rounds = 90; // Rounds the plan holds the zone after the arrival (from the map).
int last_threat = -1000, t_entered = -1000; // Last round enemies were counted at the zone; my first entry.
std::uint16_t last_raw = 0xFFFF;
std::array<bool, 8> crew{};
int crew_n = 0, lead = -1, second = -1;
bool willow_in = false;
std::vector<std::uint8_t> zmask; // per group: 1 zone member, 2 near the hold (crew candidates)
// Local (this body).
bool entered = false, first_entry_done = false, was_alive = true;
bool released = false; // Nothing to work in the zone: this body plays normally until the hand-off.
int idle_since = -1;
int at_S_since = -1, out_rounds = 0, my_last_post = -1000, my_post_n = 0;
bool ward_h = false, ward_e = false, pin_fail = false;

// The tile within 2 of me (a ward's reach) nearest to `to`, passable and not a camp tile.
vec2 reach_tile_toward(vec2 to)
{
	vec2 best = W.me.pos;
	int bd = cheb(best, to);
	for (int dy = -2; dy <= 2; ++dy)
		for (int dx = -2; dx <= 2; ++dx)
		{
			const vec2 p{ W.me.pos.x + dx, W.me.pos.y + dy };
			if (!M.passable(p) || bbget(M.camp_tiles, p))
				continue;
			const int d = cheb(p, to);
			if (d < bd)
			{
				bd = d;
				best = p;
			}
		}
	return best;
}
std::unique_ptr<distance_field> fS;
int alive_round = -1;
std::array<std::int8_t, 8> alive_c{};

int now_r() { return W.round; }
int my_slot() { return P.my_slot; }

bool alive_slot(int s)
{
	if (s < 0 || s >= P.n || s >= 8)
		return false;
	if (s == P.my_slot)
		return W.alive;
	if (alive_round != W.round)
	{
		alive_round = W.round;
		alive_c.fill(-1);
	}
	auto& c = alive_c[static_cast<std::size_t>(s)];
	if (c < 0)
	{
		if (W.ally_by_slot(s))
			c = 1;
		else
		{
			std::int32_t a = 1;
			if (cambc::detail::sdk_champion_is_alive(P.handle[static_cast<std::size_t>(s)], &a) != 0)
				a = 1;
			c = a != 0 ? 1 : 0;
		}
	}
	return c > 0;
}

bool zone_group(int gi) { return gi >= 0 && static_cast<std::size_t>(gi) < zmask.size() && zmask[static_cast<std::size_t>(gi)] != 0; }

void set_phase(int p)
{
	if (p == ph)
		return;
	ph = p;
	active_ = ph == PH_ON || ph == PH_YIELDED;
}

int crew_alive()
{
	int n = 0;
	for (int s = 0; s < P.n && s < 8; ++s)
		if (crew[static_cast<std::size_t>(s)] && alive_slot(s))
			++n;
	return n;
}

// Willow with a crew partner: she follows him, so she counts with him.
bool willow_with(int s)
{
	const int h = support::healer_slot();
	return willow_in && h >= 0 && support::partner_slot() == s && alive_slot(h);
}

// The enemy count at the zone is scaled by the line-ups' fight strength, exp((their mean kit value - ours) / 2): strength goes as
// n^2 x quality, so a count scales by the square root of the quality ratio. Computed once per game, from the rosters.
float enemy_q()
{
	static float q = -1.0f;
	if (q > 0.0f)
		return q;
	// Fight values from 3v3 fight simulations (log-odds beyond stats): champion knowledge, not map knowledge.
	auto kfv = [](cambc::champion_type t) {
		using C = cambc::champion_type;
		switch (t)
		{
		case C::heart_of_ruin: return 1.43f;
		case C::ryth: return 0.39f;
		case C::stellar: return 0.28f;
		case C::marcella: return -0.14f;
		case C::willow: return -0.13f;
		case C::ren: return -0.32f;
		case C::prism: return -0.32f;
		case C::tavi: return -0.34f;
		case C::cassi:
		case C::issac: return -0.46f;
		case C::varg: return -0.70f;
		case C::vesper_vale: return -0.72f;
		case C::vendetta: return -1.16f;
		default: return 0.0f;
		}
	};
	float se = 0.0f, su = 0.0f;
	int ne = 0, nu = 0;
	for (const auto& r : roster(team::enemy))
	{
		se += kfv(r.type);
		++ne;
	}
	for (const auto& r : roster(team::ally))
	{
		su += kfv(r.type);
		++nu;
	}
	if (ne == 0 || nu == 0)
		return 1.0f;
	q = std::clamp(std::exp((se / static_cast<float>(ne) - su / static_cast<float>(nu)) / 2.0f), 0.6f, 1.6f);
	return q;
}

// Enemies at the zone: own and ward sight (3 rounds), the last SEEN count (6 rounds), capped by who can be there.
int enemies_at_zone()
{
	const int t = now_r();
	int n = intel::count_near(B.z.hold, B.z.R + 6, 3);
	if (t - seen_round < 6)
		n = std::max(n, seen_n);
	n = std::min(n, intel::possible_at(t, B.z.dB));
	n = static_cast<int>(std::lround(static_cast<float>(n) * enemy_q())); // Scale by the line-up strength ratio.
	return n;
}

// Our bodies at the zone: me and crew mates within R+4 of the hold (sight), mates out of sight that claim a zone group
// with the engaged bit, and Willow with a counted partner.
int allies_inside_zone(bool count_me)
{
	const vec2 H = B.z.hold;
	const int r = B.z.R + 4;
	int n = 0;
	bool partner_counted = false;
	const int ps = support::partner_slot();
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (!crew[static_cast<std::size_t>(s)])
			continue;
		bool in = false;
		if (s == my_slot())
			in = count_me && W.alive && cheb(W.me.pos, H) <= r;
		else if (const Body* b = W.ally_by_slot(s))
			in = cheb(b->pos, H) <= r;
		else if (alive_slot(s))
		{
			in = zone_group(comms::cgroup(s)) && comms::cengaged(s);
		}
		if (in)
		{
			++n;
			if (s == ps)
				partner_counted = true;
		}
	}
	if (partner_counted && willow_with(ps) && support::healer_slot() != my_slot())
		++n;
	return n;
}

// The crew at the zone as the team knows it, for the yield test. The enemy count is pooled over the team's sight (own + ward sight,
// SEEN posts), but allies_inside_zone() is one body's view: a body at the zone's edge could see one mate and yield for the whole crew. Here
// a mate counts unless it is known to be away: seen beyond R+6 of the hold (the enemy count's radius), dead, respawned within dA+5
// rounds (walking back), or claiming a group outside the zone (released to normal play).
std::array<int, 8> last_dead{ { -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 } };
int crew_at_zone()
{
	const vec2 H = B.z.hold;
	const int r = B.z.R + 6, t = now_r();
	int n = 0;
	bool partner_counted = false;
	const int ps = support::partner_slot();
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (!crew[static_cast<std::size_t>(s)])
			continue;
		bool in = false;
		if (s == my_slot())
			in = W.alive && cheb(W.me.pos, H) <= r;
		else if (const Body* b = W.ally_by_slot(s))
			in = cheb(b->pos, H) <= r;
		else if (alive_slot(s) && t - last_dead[static_cast<std::size_t>(s)] > B.z.dA + 5)
		{
			const int g = comms::cgroup(s);
			in = g < 0 || zone_group(g);
		}
		if (in)
		{
			++n;
			if (s == ps)
				partner_counted = true;
		}
	}
	if (partner_counted && willow_with(ps) && support::healer_slot() != my_slot())
		++n;
	return n;
}

// Crew bodies gathered around me at S (sight), me included, plus Willow with a gathered partner.
int allies_near_me()
{
	int n = 1;
	bool partner = my_slot() == support::partner_slot();
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < 8 && crew[static_cast<std::size_t>(a.slot)] && cheb(a.pos, W.me.pos) <= 3)
		{
			++n;
			if (a.slot == support::partner_slot())
				partner = true;
		}
	const int h = support::healer_slot();
	if (partner && willow_in && h >= 0 && h != my_slot() && alive_slot(h))
		++n;
	return n;
}

// A crew mate is inside the zone (seen within R+2 of the hold, or claiming a zone group with the engaged bit).
bool mate_inside()
{
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == my_slot() || !crew[static_cast<std::size_t>(s)] || !alive_slot(s))
			continue;
		if (const Body* b = W.ally_by_slot(s))
		{
			if (cheb(b->pos, B.z.hold) <= B.z.R + 2)
				return true;
		}
		else
		{
			if (zone_group(comms::cgroup(s)) && comms::cengaged(s))
				return true;
		}
	}
	return false;
}

int decode_round(int stamp)
{
	const int t = now_r();
	return t - ((t - stamp) & comms::STAMP_MASK);
}

int subject_of(int act, int arg) { return 0 + 2 * act + 16 * std::clamp(arg, 0, 14); }

void apply(int act, int arg, int r)
{
	if (act == A_SEEN)
	{
		last_ev = std::max(last_ev, r);
		seen_n = arg;
		seen_round = r;
	}
	else if (act == A_YIELD)
	{
		last_ev = std::max(last_ev, r);
		seen_n = arg;
		seen_round = r;
		if (ph == PH_ON)
		{
			t_y = r;
			set_phase(PH_YIELDED);
		}
	}
}

// Post a type-7 event under the posting rules: fresh calls of other lines (types 4-6) are kept unless this is a YIELD; a fresh
// type-7 event is kept against a lower action, and a SEEN only replaces a smaller count.
bool post(int act, int arg)
{
	const int t = now_r();
	const comms::Event cur = comms::ev();
	const int age = (t - cur.stamp) & comms::STAMP_MASK;
	const bool fresh = cur.subject >= 0 && age < 6;
	if (fresh && cur.type >= comms::EV_TYPE_HELP && cur.type < EV_CONTEST && act != A_YIELD && !comms::is_sight(cur)) // Team intel: a sighting gives way.
		return false;
	if (fresh && cur.type == EV_CONTEST)
	{
		const int ca = (cur.subject >> 1) & 7, cg = cur.subject >> 4;
		if (ca > act || (ca == act && arg <= cg))
			return false;
	}
	comms::write_event(subject_of(act, arg), EV_CONTEST, t);
	apply(act, arg, t);
	my_last_post = t;
	my_post_n = arg;
	return true;
}

// Walk toward S: its own field (camps blocked) once affordable, else a short search.
bool walk_to_S()
{
	const vec2 S = B.z.S;
	if (!fS && fuel() > 3L * G.w * G.h + 45000)
	{
		auto f = std::make_unique<distance_field>();
		bitboard visited, root;
		bbset(root, S);
		f->compute(M.block_camps & ~root, root, visited);
		fS = std::move(f);
	}
	if (fS && dfget_me(*fS) != UNREACH && dfget_me(*fS) > 0)
		return mv::step_field(*fS);
	if (fuel() > 30000)
		return mv::step_to(S, 0, 40);
	return mv::step_greedy(S);
}

} // namespace


void init()
{
	ok = false;
	active_ = false;
	ph = PH_OFF;
	return; // No zone plan.
}

void begin_turn()
{
	track_respawn_round(); // Before the OFF return: the plan may have handed off.
	if (!ok || ph == PH_OFF)
		return;
	const int t = now_r();
	const comms::Event ev = comms::ev();
	if (ev.subject >= 0 && ev.raw != last_raw)
	{
		last_raw = ev.raw;
		if (ev.type == EV_CONTEST && (ev.subject & 1) == 0)
		{
			const int act = (ev.subject >> 1) & 7, arg = ev.subject >> 4;
			apply(act, arg, decode_round(ev.stamp));
		}
	}
	if (ph == PH_ON && t >= t_arrive + hold_rounds)
	{
		set_phase(PH_DONE); // first contest settled: normal play
		t_done = t;
	}
	if (ph == PH_YIELDED && t >= t_y + CT_YIELD_HOLD)
	{
		set_phase(PH_DONE);
		t_done = t;
	}
	if (released && wave_at >= 0 && W.alive && wave_at - t <= cheb(W.me.pos, B.z.hold) + 3)
	{
		released = false; // Back for the wave.
		wave_at = -1;
		idle_since = -1;
	}
	if (ph != PH_ON || my_slot() < 0 || !crew[static_cast<std::size_t>(my_slot())])
		return;
	for (int s = 0; s < P.n && s < 8; ++s)
		if (crew[static_cast<std::size_t>(s)] && !alive_slot(s))
			last_dead[static_cast<std::size_t>(s)] = t;
	// Crew body: death resets my entry; the ward owners report the counts at the zone (their wards see while dead).
	if (!W.alive)
	{
		entered = false;
		at_S_since = -1;
		out_rounds = 0;
	}
	const int them = enemies_at_zone();
	if (them > 0)
		last_threat = t; // Enemies were counted at the zone this round.
	if ((my_slot() == lead || my_slot() == second))
	{
		const int seen = intel::count_near(B.z.hold, B.z.R + 6, 3);
		// Rarely: a rising count (within 12 rounds of my last post) or a 12-round refresh; intel news keeps the slot
		// otherwise.
		if (seen >= 1 && t - my_last_post >= 2 && (seen > my_post_n || t - my_last_post >= 12))
			post(A_SEEN, seen);
	}
	// Inside: outnumbered by two at once, or by one for CT_OUT_ROUNDS rounds -> the crew yields together.
	if (W.alive && entered && cheb(W.me.pos, B.z.hold) <= B.z.R + 4)
	{
		const int us = std::max(allies_inside_zone(true), crew_at_zone());
		if (them >= us + 1)
			++out_rounds;
		else
			out_rounds = 0;
		if (them >= us + 2 || out_rounds >= CT_OUT_ROUNDS)
			post(A_YIELD, them);
	}
}

bool on() { return ok && ph == PH_ON; }

// For CT_BACK_ROUNDS after my respawn, the zone's groups are worth CT_BACK_BONUS more, unless the zone count (own and ward sight,
// the wards' SEEN posts) shows more enemies there than our bodies near it + 1. Respawned bodies go back to contested areas, and
// wards tell how many to bring.
namespace {
int last_respawn = -1000;
bool back_alive = true;
}
void track_respawn_round()
{
	if (W.alive && !back_alive)
		last_respawn = now_r();
	back_alive = W.alive;
}
bool death_window(); // See death_window below.
bool back_live() { return ok && B.gate; }
float respawn_return_factor(int gi)
{
	if (ok && B.gate && zone_group(gi) && death_window())
		return CT_BACK_BONUS;
	if (!ok || !B.gate || now_r() - last_respawn > CT_BACK_ROUNDS || !zone_group(gi))
		return 1.0f;
	int us = 1;
	for (const auto& al : W.allies)
		if (cheb(al.pos, B.z.hold) <= B.z.R + 6)
			++us;
	return enemies_at_zone() > us + 1 ? 1.0f : CT_BACK_BONUS;
}

// When the enemy can first stand at group gi, and when it can have it captured, from what we know now. Each living enemy body walks
// from its last known tile (own or ward sighting; else its spawn, from its respawn round or round 0) to the group; the bodies that
// have arrived add their kits' camp damage (base stats, the group's pack), the group's known HP drains, and the capture takes 6 more
// rounds. With 3+ bodies the last to arrive is left out (the whole team rarely comes). Once per round (the entry group of the zone
// only).
struct Race
{
	int round = -1000, first = BIG, claim = BIG;
};
Race count_contest_numbers()
{
	static Race rc;
	const int t = now_r();
	if (rc.round == t || !ok || B.z.entry < 0)
		return rc;
	rc = Race{};
	rc.round = t;
	const int gi = B.z.entry;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	static std::vector<intel::Known> kn;
	intel::living_known(kn, M.enemy_anchor);
	const auto ros = roster(team::enemy);
	const distance_field* gf = mv::group_field_ready(gi);
	struct Arr
	{
		int t;
		float dps;
	};
	std::vector<Arr> arr;
	for (const auto& k : kn)
	{
		const int walk = k.at_spawn ? static_cast<int>(g.d_enemy) : (gf ? static_cast<int>(dfget(*gf, k.pos)) : cheb(k.pos, g.anchor));
		if (walk >= static_cast<int>(UNREACH))
			continue;
		float dps = 55.0f;
		for (const auto& r : ros)
			if (r.h == k.h)
			{
				const Kit& kt = kit_of(r.type);
				if (kt.valid)
				{
					float kd = kit_dps(kt, kt.str, kt.foc, std::max(1, g.pack));
					if (kt.missing_hp_bonus)
						kd *= heart_layer::rule_over_clear_of_foe(k.h);
					dps = std::max(10.0f, kd);
				}
			}
		arr.push_back({ std::max(t, k.round + walk), dps });
	}
	if (arr.empty())
		return rc;
	std::sort(arr.begin(), arr.end(), [](const Arr& a, const Arr& b) { return a.t < b.t; });
	if (arr.size() >= 3)
		arr.pop_back();
	rc.first = arr[0].t;
	const auto& m = econ::memory()[static_cast<std::size_t>(gi)];
	float hp = m.hp_left >= 0 ? m.hp_left : g.hp;
	float rate = 0;
	for (std::size_t i = 0; i < arr.size(); ++i)
	{
		rate += arr[i].dps;
		const int next = i + 1 < arr.size() ? arr[i + 1].t : BIG;
		const float need = hp / std::max(1.0f, rate);
		if (static_cast<float>(arr[i].t) + need <= static_cast<float>(next))
		{
			rc.claim = arr[i].t + static_cast<int>(need) + 6;
			break;
		}
		hp -= rate * static_cast<float>(next - arr[i].t);
	}
	return rc;
}

// Before the first contest is decided, a crew body does not start a zone group that fights back (attackers) when its clear and
// capture would run past the enemy's expected arrival at the zone (their walk to the hold). Clusters stay open, so the crew meets
// them at full health.
bool avoid_heavy(int gi, float clear_t)
{
	if (!on() || first_contest_over() || !zone_group(gi))
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.n_att == 0)
		return false;
	const int t = now_r();
	const int arrive = std::min(B.z.dB + 40, count_contest_numbers().first); // Their first body, from what we know.
	return t < arrive + CT_FRESH_AFTER && static_cast<float>(t) + clear_t + 6.0f > static_cast<float>(arrive - 2);
}
bool first_contest_over() { return now_r() > B.z.dB + CT_FRESH_AFTER; }

bool is_crew(int s) { return on() && s >= 0 && s < 8 && crew[static_cast<std::size_t>(s)] && !(s == P.my_slot && released); }

// While at least CT_PUSH_DEAD enemy bodies will still be dead CT_PUSH_AHEAD rounds from now (respawns are known map-wide), the
// zone's groups are open to every body and worth CT_BACK_BONUS more.
bool death_window()
{
	if (!ok || !B.gate)
		return false;
	return intel::enemies_total() - intel::possible_at(now_r() + CT_PUSH_AHEAD, 0) >= CT_PUSH_DEAD;
}

bool allow(int gi, int self)
{
	if (!active_)
		return true;
	const bool zg = zone_group(gi);
	if (zg && ph != PH_YIELDED && death_window())
		return true; // Anyone works the zone while they are down.
	if (ph == PH_YIELDED)
		return !(zg && zmask[static_cast<std::size_t>(gi)] == 1);
	if (self >= 0 && self < 8 && crew[static_cast<std::size_t>(self)] && !(self == P.my_slot && released))
		return zg;
	return !(zg && zmask[static_cast<std::size_t>(gi)] == 1); // R1: members only (near-hold groups stay open)
}

int opening_target()
{
	if (!is_crew(my_slot()))
		return -1;
	return B.z.entry;
}

bool keep_group(int gi) { return is_crew(my_slot()) && zone_group(gi); }

int unseen_mates_near()
{
	if (!on() || !W.alive || my_slot() < 0 || !crew[static_cast<std::size_t>(my_slot())] || !entered || cheb(W.me.pos, B.z.hold) > B.z.R + 4)
		return 0;
	int n = 0;
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == my_slot() || !crew[static_cast<std::size_t>(s)] || W.ally_by_slot(s) || !alive_slot(s))
			continue;
		if (zone_group(comms::cgroup(s)) && comms::cengaged(s))
			++n;
	}
	return n;
}

bool crew_turn(const combat::Assessment& a)
{
	(void)a;
	if (!on() || !W.alive || my_slot() < 0 || !crew[static_cast<std::size_t>(my_slot())] || released)
		return false;
	if (support::me_active())
		return false;
	{
		// An econ target on our side (contest < 0.4) outside the zone is econ's to work; otherwise crew bodies would alternate between the
		// crew walk toward the zone and econ's farm walk to the same own-side group. The crew walk resumes once the target changes.
		const int tg = econ::claim_target();
		if (tg >= 0 && static_cast<std::size_t>(tg) < static_cast<std::size_t>(M.ng) && !zone_group(tg) &&
			M.groups[static_cast<std::size_t>(tg)].contest < 0.40f)
			return false;
	}
	const int t = now_r();
	if (entered && zone_group(econ::claim_target()))
		idle_since = -1; // working the zone
	if (entered)
	{
		// Pulled out (a flee, a recall, a bank trip) beyond the leash: walk back in through S.
		if (cheb(W.me.pos, B.z.hold) > B.z.R + 8 && !econ::busy_capturing() && !econ::engaged_now())
		{
			entered = false;
			at_S_since = -1;
		}
		else
			return false; // econ works the zone (its targets are zone groups only)
	}
	if (W.me.channeling() || !W.can_move())
		return false;
	// The first contest is a race. The enemy claims the entry group at about their walk + its clear by 3 bodies + the capture. With
	// CT_ON_WAY_MIN+ rounds of slack over my direct arrival I take one camp that fits the slack (walk, clear, capture, on to the zone);
	// otherwise I take the shortest path straight there.
	if (!first_entry_done)
	{
		const int tg = econ::claim_target();
		const bool working = on_way_gi >= 0 && tg == on_way_gi && econ::memory()[static_cast<std::size_t>(on_way_gi)].status != econ::GS_RESPAWN;
		// The race is recomputed every CT_RACE_EVERY rounds from the enemy's known bodies (count_contest_numbers): a camp on the way not started yet is
		// dropped once they could claim the zone before I arrive straight. After one is done (or while none fits) the next camp that fits
		// is looked for, so a crew body keeps taking camps on the way.
		const int to_S = fS ? static_cast<int>(dfget_me(*fS)) : cheb(W.me.pos, B.z.S);
		if (working)
		{
			if (econ::engaged_now() || econ::busy_capturing() || t - race_checked < CT_RACE_EVERY)
				return false; // working my camp on the way
			race_checked = t;
			if (count_contest_numbers().claim - (t + to_S + B.z.dSH) >= 0)
				return false;
			on_way_gi = -1; // the race is lost: straight to the zone
		}
		else
		{
			if (on_way_gi >= 0)
			{
				on_way_gi = -1; // done (respawning) or taken over: look again
				on_way_tried = false;
			}
			if (!on_way_tried || t - race_checked >= CT_RACE_EVERY)
			{
				on_way_tried = true;
				race_checked = t;
				const int slack = count_contest_numbers().claim - (t + to_S + B.z.dSH);
				if (slack >= CT_ON_WAY_MIN)
				{
					const int f = econ::on_way_target(B.z.entry, std::min(slack, CT_RACE_MAX_SLACK));
					if (f >= 0 && !zone_group(f))
					{
						on_way_gi = f;
						econ::force_target(f);
						return false;
					}
				}
			}
		}
	}
	econ::force_target(B.z.entry);
	// At S: on or next to it (by S's walk field when built: walls between a tile and S do not count as near).
	const bool at_S = fS ? (dfget_me(*fS) <= 2) : cheb(W.me.pos, B.z.S) <= 1;
	if (!at_S)
	{
		at_S_since = -1;
		if (walk_to_S())
			return true;
		return false;
	}
	if (at_S_since < 0)
		at_S_since = t;
	const int waited = t - at_S_since;
	const int them = enemies_at_zone();
	const int here = allies_near_me();
	int need = crew_alive() + (willow_in && alive_slot(support::healer_slot()) ? 1 : 0);
	if (waited >= CT_GATHER)
		need = std::min(need, 2);
	bool enter = false;
	const bool inside = mate_inside();
	if (inside || first_entry_done)
		enter = them == 0 || them <= allies_inside_zone(false) + here - 1; // join (or rejoin) mates inside
	else if (here >= need && (them == 0 || here >= them + 1))
		enter = true;
	else if (them == 0)
		enter = true; // No enemy at the zone: no wait at S.
	else if ((them >= here + 2 || (waited >= CT_GATHER_MAX && them >= here)))
	{
		post(A_YIELD, them);
		return false;
	}
	if (crew_alive() <= 1 && waited >= CT_GATHER_MAX)
		enter = them == 0; // the last living crew body: only into an empty zone
	if (enter)
	{
		if (!entered)
			t_entered = t; // Entered the zone this round.
		entered = true;
		first_entry_done = true;
		out_rounds = 0;
		return false; // econ takes over this turn
	}
	// Wait at S (step onto it when a neighbour), never on a camp tile.
	if (cheb(W.me.pos, B.z.S) >= 1 && cheb(W.me.pos, B.z.S) <= 2 && fuel() > 30000 && mv::step_to(B.z.S, 0, 12))
		return true;
	return true;
}

bool idle_turn()
{
	if (!on() || !W.alive || my_slot() < 0 || !crew[static_cast<std::size_t>(my_slot())] || !entered || released)
		return false;
	const int t = now_r();
	// Once no enemy has been counted at the zone for CT_SECURE_ROUNDS since my entry, the bodies other than the lead and the second
	// (they keep the zone and its wards) go back to normal play.
	if (my_slot() != lead && my_slot() != second && t - t_entered >= CT_SECURE_ROUNDS && t - last_threat >= CT_SECURE_ROUNDS)
	{
		released = true;
		return false;
	}
	// With the zone's next group back later than the map's wait cap (and my walk back), I farm elsewhere and rejoin the crew when the
	// wave is my walk back + 3 rounds away (begin_turn).
	{
		const auto& gm = econ::memory();
		int wave = 1 << 20;
		for (int i = 0; i < B.z.n; ++i)
		{
			const auto gi = static_cast<std::size_t>(B.z.members[i]);
			if (gi >= gm.size())
				continue;
			wave = std::min(wave, gm[gi].status == econ::GS_RESPAWN ? gm[gi].respawn_at : t);
		}
		const int back = cheb(W.me.pos, B.z.hold) + 3;
		if (wave - t > std::max(econ::wait_cap(), back))
		{
			released = true;
			wave_at = wave;
			return false;
		}
	}
	if (idle_since < 0)
		idle_since = t;
	if (t - idle_since >= CT_IDLE_MAX)
	{
		released = true; // nothing to work in the zone: normal play (R1 still keeps me off zone members)
		return false;
	}
	if (W.moved || W.me.channeling() || !W.can_move())
		return false;
	// No zone group to work now (respawning, claimed by mates): wait on the hold, ready for the wave; with more enemies
	// known at the zone than mates in it, wait at S instead (never walk alone into them).
	const vec2 to = enemies_at_zone() > allies_inside_zone(false) ? B.z.S : B.z.hold;
	if (cheb(W.me.pos, to) <= 1)
		return true;
	if (fuel() > 30000 && mv::step_to(to, 1, 30))
		return true;
	return mv::step_greedy(to);
}

int ward_pin(vec2* out)
{
	if (!on() || !W.alive || my_slot() < 0 || pin_fail)
		return 0;
	const int s = my_slot();
	if (s == lead)
	{
		if (ward_h)
			return 2; // pinned on the hold while the plan runs
		if (cheb(W.me.pos, B.z.hold) <= 4)
		{
			*out = reach_tile_toward(B.z.hold);
			ward_h = true;
			return 1;
		}
		// Keep the charge for the hold while walking in (not past the expected arrival + 30).
		return (entered || cheb(W.me.pos, B.z.hold) <= B.z.R + 8) && now_r() < t_arrive + 30 ? 2 : 0;
	}
	if (s == second)
	{
		if (ward_e)
			return 2;
		if (entered && cheb(W.me.pos, B.z.hold) <= B.z.R + 2 && enemies_at_zone() == 0)
		{
			*out = reach_tile_toward(B.z.E); // the ward looks down the enemy's approach
			ward_e = true;
			return 1;
		}
	}
	return 0;
}

void ward_result(bool placed)
{
	if (!placed)
		pin_fail = true; // a refused tile ends the pin: the normal ward logic takes over
}

} // namespace nova::zc
