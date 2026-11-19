// intel.cc: Team intelligence: enemy sightings and camp-group news, from this champion's own vision (which includes its ward, also while the
#include "intel.h"
#include <wasm_simd128.h>

#include "comms.h"
#include "econ.h"
#include "mapinfo.h"
#include "plan.h"
#include "world.h"
#include "rules.h"
#include "champ_prism.h"

namespace nova::intel {

namespace {

constexpr int HOLD = 2;         // rounds before any ally may overwrite an event (every ally has read it by then)
constexpr int HELP_HOLD = 6; // rounds a HELP call (comms types 4-7, backup module) is protected from intel news
constexpr int REPOST = 8;       // rounds before a sighting at the same subject is reported again
constexpr int NEWS_TTL = INTEL_NEWS_TTL; // rounds a group news item waits for the slot
constexpr int SUBJECT_MAX = 254;

struct Seen
{
	std::uint32_t h = 0;
	vec2 pos{};
	int round = -1000;
};
std::vector<Seen> own; // last own sighting of each enemy body

// Enemy bodies. Their alive state is readable out of vision, so deaths (and respawns 60 rounds later) are known.
struct Foe
{
	std::uint32_t h = 0;
	bool alive = true;
	int died = -1000;
};
std::vector<Foe> foes;
bool foes_read = false;
int foes_alive = 0;

struct Report
{
	vec2 pos{};
	int round = -1000;
	std::uint8_t n = 0;
};
std::array<Report, 12> reports{};
std::size_t rep_next = 0;
std::array<Report, 12> shared_rep{}; // reports every body holds (received events + my own posts)
std::size_t shr_next = 0;
void add_shared(vec2 p, int round, std::uint8_t n)
{
	shared_rep[shr_next] = { p, round, n };
	shr_next = (shr_next + 1) % shared_rep.size();
}
int latest = -1000; // round of the most recent sighting of any kind
constexpr int MAX_AGE = 30; // oldest sighting any query uses

struct Active
{
	vec2 pos;
	int round;
	std::uint8_t n;
	bool own;
};
std::vector<Active> active;
int active_round = -1;
// The active list as columns for danger()'s 4-wide test (padding never matches: round far in the past).
struct ActiveSoA
{
	std::vector<std::int32_t> x, y, r, own, n;
	std::size_t len = 0;
} act4;

struct News
{
	int gi;
	int type;
	int round;
};
std::vector<News> news;
std::vector<int> last_ev; // per subject: last round an event about it was posted or seen
std::vector<int> last_taken; // per group: capture round last announced or heard
std::uint16_t last_raw = 0;
Stats S;

// TEAM INTEL: the team table (roster order) and the last body read per enemy.
std::vector<TeamSeen> tk_tab;
std::vector<Body> team_bodies;
std::vector<char> team_has_body;
std::vector<int> team_body_r; // the round of team_bodies[i] (my sight or ward); -1000 after a death
// MUL bit 2048: each foe's first own sighting and the round of its last, for team_body_pred.
struct FgFirst
{
	int r0 = -1, r1 = -1;
	float str = 0, foc = 0, mh = 0;
};
std::vector<FgFirst> fg_first;

int team_index(std::uint32_t h)
{
	for (std::size_t i = 0; i < tk_tab.size(); ++i)
		if (tk_tab[i].h == h)
			return static_cast<int>(i);
	return -1;
}

int now() { return W.round; }
int n_groups() { return M.ng; }
int n_subjects() { return std::min<int>(SUBJECT_MAX, n_groups() + M.na); }

void size_event_tables()
{
	const auto ns = static_cast<std::size_t>(n_subjects());
	if (last_ev.size() != ns)
		last_ev.assign(ns, -1000);
	if (last_taken.size() != static_cast<std::size_t>(M.ng))
		last_taken.assign(static_cast<std::size_t>(M.ng), -1000);
}

int priority(int type)
{
	switch (type)
	{
	case EV_ENEMIES: return 3;
	case EV_CLEARED: return 2;
	default: return 1;
	}
}

bool claimed_by_team(int gi)
{
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		if (comms::cgroup(s) == gi)
			return true;
	return false;
}

// How much the team cares about news at a subject: 3 = someone's target, 2 = our side or central, 1 = their side.
int relevance(int subject)
{
	const int ng = n_groups();
	if (subject < ng)
	{
		if (claimed_by_team(subject))
			return 3;
		return M.groups[static_cast<std::size_t>(subject)].contest <= 0.62f ? 2 : 1;
	}
	const auto& a = M.altars[static_cast<std::size_t>(subject - ng)];
	if (a.d_home == UNREACH)
		return 1;
	return a.d_enemy == UNREACH || a.d_home <= a.d_enemy + 6 ? 2 : 1;
}

void add_report(vec2 p, int round, std::uint8_t n)
{
	reports[rep_next] = { p, round, n };
	rep_next = (rep_next + 1) % reports.size();
	latest = std::max(latest, round);
	add_shared(p, round, n);
}

void handle(int subject, int type, int round)
{
	if (subject < 0 || subject >= n_subjects())
		return;
	const int ng = n_groups();
	last_ev[static_cast<std::size_t>(subject)] = std::max(last_ev[static_cast<std::size_t>(subject)], round);
	(void)0;
	const vec2 p = subject_pos(subject);
	switch (type)
	{
	case EV_ENEMY:
	case EV_ENEMIES:
		add_report(p, round, type == EV_ENEMIES ? 2 : 1);
		break;
	case EV_TAKEN:
		if (subject < ng)
		{
			last_taken[static_cast<std::size_t>(subject)] = round;
			econ::intel_taken(subject, round);
		}
		break;
	case EV_CLEARED:
		if (!(subject < ng && econ::mate_claims_group_recently(subject, round))) // old news of a group already taken
			add_report(p, round, 1);
		if (subject < ng)
			econ::intel_cleared(subject, round);
		break;
	default: break;
	}
	NLOG("r%d slot %d intel rx type %d subject %d round %d\n", now(), P.my_slot, type, subject, round);
}

// Tile -> nearest subject: a group anchor within 7, or an altar within 5 counted one tile farther. Painted in the
// background one subject per step (analyse); until then subject_of scans the subjects. Both maps store value + 1.
TileMap<std::int16_t> subj_map;
TileMap<std::uint8_t> subj_dist;
std::size_t subj_cursor = 0;
int subj_row = -1; // next row of the subject being painted
bool subj_started = false, subj_done = false;

int subject_slow(vec2 p)
{
	int best = -1, bd = BIG;
	const int ng = n_groups(), ns = n_subjects();
	for (int gi = 0; gi < ng && gi < ns; ++gi)
	{
		const int d = cheb(p, M.groups[static_cast<std::size_t>(gi)].anchor);
		if (d <= 7 && d < bd)
		{
			bd = d;
			best = gi;
		}
	}
	for (int i = ng; i < ns; ++i)
	{
		const int d = cheb(p, M.altars[static_cast<std::size_t>(i - ng)].pos);
		if (d <= 5 && d + 1 < bd)
		{
			bd = d + 1;
			best = i;
		}
	}
	return best;
}
int subject_of(vec2 p)
{
	if (subj_done && inb(p))
		return subj_map.get(p) - 1;
	return subject_slow(p);
}

struct Cand
{
	int subject = -1, type = 0, round = 0, score = -1;
	std::size_t news_idx = SIZE_MAX;
};

} // namespace


const std::vector<TeamSeen>& team_table() { return tk_tab; }
const Body* team_body(std::size_t i) { return i < team_bodies.size() && team_has_body[i] ? &team_bodies[i] : nullptr; }
int team_body_round(std::size_t i) { return i < team_body_r.size() ? team_body_r[i] : -1000; }
void team_body_pred(std::size_t i, int now, Body& b)
{
	if (i >= fg_first.size())
		return;
	const FgFirst& g = fg_first[i];
	const int span = g.r1 - g.r0;
	if (g.r0 < 0 || span < 20 || now <= g.r1)
		return;
	const float k = static_cast<float>(now - g.r1) / static_cast<float>(span);
	const float ds = std::max(0.0f, b.str - g.str) * k, df = std::max(0.0f, b.foc - g.foc) * k, dh = std::max(0.0f, b.maxhp - g.mh) * k;
	if (ds > 0 || df > 0 || dh > 0)
	{
		((void)0);
	}
	b.str += ds;
	b.foc += df;
	b.hp += dh;
	b.maxhp += dh;
}

vec2 subject_pos(int subject)
{
	const int ng = n_groups();
	if (subject >= 0 && subject < ng)
		return M.groups[static_cast<std::size_t>(subject)].anchor;
	if (subject >= ng && subject - ng < M.na)
		return M.altars[static_cast<std::size_t>(subject - ng)].pos;
	return { -1, -1 };
}
__attribute__((always_inline)) void analyse(long reserve)
{
	if (subj_done || !M.ready())
		return;
	try
	{
		if (!subj_started)
		{
			subj_map.reset();
			subj_dist.reset();
			subj_cursor = 0;
			subj_row = -1;
			subj_started = true;
		}
		const int ng = n_groups(), ns = n_subjects();
		while (static_cast<int>(subj_cursor) < ns)
		{
			// Paint the subject's square two rows per fuel check (~80 fuel per tile).
			const int s = static_cast<int>(subj_cursor);
			const vec2 c = subject_pos(s);
			const int r = s < ng ? 7 : 5, extra = s < ng ? 1 : 2;
			const int y_end = std::min(G.h - 1, c.y + r);
			if (subj_row < std::max(0, c.y - r))
				subj_row = std::max(0, c.y - r);
			while (subj_row <= y_end)
			{
				if (fuel() < reserve + 6000)
					return;
				const int x_lo = std::max(0, c.x - r), x_hi = std::min(G.w - 1, c.x + r);
				for (int y = subj_row; y <= std::min(y_end, subj_row + 1); ++y)
				{
					const int dy = iabs(y - c.y);
					for (int x0 = x_lo; x0 <= x_hi; x0 = (x0 | 7) + 1) // one 8-tile cell span at a time
					{
						std::uint8_t* dp = subj_dist.row8(vec2{ x0, y });
						std::int16_t* mp = subj_map.row8(vec2{ x0, y });
						const int x1 = std::min(x_hi, x0 | 7);
						// The cell row's 8 tiles at once (i16x8): d = max(|x - c.x|, dy) + extra, kept where the tile is in [x0, x1] and (cur == 0 ||
						// d < cur); other lanes are written back unchanged.
						{
							const int bx = x0 & ~7;
							const v128_t lane = wasm_i16x8_make(0, 1, 2, 3, 4, 5, 6, 7);
							const v128_t xs = wasm_i16x8_add(wasm_i16x8_splat(static_cast<std::int16_t>(bx)), lane);
							const v128_t act = wasm_v128_and(wasm_i16x8_ge(lane, wasm_i16x8_splat(static_cast<std::int16_t>(x0 - bx))),
								wasm_i16x8_le(lane, wasm_i16x8_splat(static_cast<std::int16_t>(x1 - bx))));
							const v128_t d = wasm_i16x8_add(wasm_i16x8_max(wasm_i16x8_abs(wasm_i16x8_sub(xs, wasm_i16x8_splat(static_cast<std::int16_t>(c.x)))),
								wasm_i16x8_splat(static_cast<std::int16_t>(dy))), wasm_i16x8_splat(static_cast<std::int16_t>(extra)));
							const v128_t cur = wasm_u16x8_load8x8(dp);
							const v128_t take = wasm_v128_and(act, wasm_v128_or(wasm_i16x8_eq(cur, wasm_i16x8_splat(0)), wasm_i16x8_lt(d, cur)));
							if (wasm_v128_any_true(take))
							{
								const v128_t nd = wasm_v128_bitselect(d, cur, take);
								wasm_v128_store64_lane(dp, wasm_u8x16_narrow_i16x8(nd, nd), 0);
								wasm_v128_store(mp, wasm_v128_bitselect(wasm_i16x8_splat(static_cast<std::int16_t>(s + 1)), wasm_v128_load(mp), take));
							}
						}
					}
				}
				subj_row += 2;
			}
			subj_row = -1;
			++subj_cursor;
		}
		subj_done = true;
	}
	catch (...)
	{
		FXR_PASS();
		subj_done = false;
		subj_started = false;
	}
}
void record_group_taken(int gi, int capture_round)
{
	size_event_tables();
	if (gi < 0 || gi >= n_groups() || gi >= n_subjects())
		return;
	if (std::abs(last_taken[static_cast<std::size_t>(gi)] - capture_round) <= 3 || now() - capture_round > 40)
		return;
	last_taken[static_cast<std::size_t>(gi)] = capture_round;
	if (now() - capture_round > NEWS_TTL)
		return; // end_turn would drop it unread
	news.push_back({ gi, EV_TAKEN, capture_round });
}
void record_group_cleared(int gi)
{
	size_event_tables();
	if (gi < 0 || gi >= n_groups() || gi >= n_subjects())
		return;
	news.push_back({ gi, EV_CLEARED, now() });
}

// danger_shared(p, radius, max_age) >= 1 (any kept report has n >= 1): stops at the first match.
bool danger_shared_any(vec2 p, int radius, int max_age)
{
	const int t = now();
	if (foes_read && foes_alive == 0)
		return false;
	const int lim = std::min(max_age, MAX_AGE);
	for (const auto& r : shared_rep)
	{
		const int age = t - r.round;
		if (r.n == 0 || age > lim)
			continue;
		if (cheb(r.pos, p) <= radius + std::min(6, age / 2) + 3)
			return true;
	}
	return false;
}
float danger(vec2 p, int radius, int max_age)
{
	const int t = now();
	if (t - latest > max_age || (foes_read && foes_alive == 0))
		return 0;
	// Sightings still worth counting, gathered once per turn (target choice asks for every group).
	if (active_round != t)
	{
		active.clear();
		for (const auto& s : own)
			if (t - s.round <= MAX_AGE)
				active.push_back({ s.pos, s.round, 1, true });
		for (const auto& r : reports)
			if (r.n > 0 && t - r.round <= MAX_AGE)
				active.push_back({ r.pos, r.round, r.n, false });
		active_round = t;
		const std::size_t m = (active.size() + 3) & ~std::size_t{ 3 };
		act4.len = m;
		act4.x.assign(m, 0);
		act4.y.assign(m, 0);
		act4.r.assign(m, -1000000000);
		act4.own.assign(m, 0);
		act4.n.assign(m, 0);
		for (std::size_t i = 0; i < active.size(); ++i)
		{
			act4.x[i] = active[i].pos.x;
			act4.y[i] = active[i].pos.y;
			act4.r[i] = active[i].round;
			act4.own[i] = active[i].own ? -1 : 0;
			act4.n[i] = active[i].n;
		}
	}
	// The same test 4 sightings at a time. Teammates report a subject's anchor, not the enemy's tile: allow 3 more tiles. reach =
	// radius + min(6, age / 2) + (own ? 0 : 3) with C's truncating age / 2; own_n counts own sightings (a float sum of 1s is exact),
	// team_n is the largest report count (max does not depend on order).
	float own_n = 0, team_n = 0;
	{
		const v128_t vt = wasm_i32x4_splat(t), vmax = wasm_i32x4_splat(max_age), vrad = wasm_i32x4_splat(radius);
		const v128_t vpx = wasm_i32x4_splat(p.x), vpy = wasm_i32x4_splat(p.y), v6 = wasm_i32x4_splat(6), v3 = wasm_i32x4_splat(3);
		int own_c = 0;
		v128_t tn = wasm_i32x4_splat(0);
		for (std::size_t k = 0; k < act4.len; k += 4)
		{
			const v128_t age = wasm_i32x4_sub(vt, wasm_v128_load(act4.r.data() + k));
			const v128_t half = wasm_i32x4_shr(wasm_i32x4_add(age, wasm_u32x4_shr(age, 31)), 1);
			const v128_t own = wasm_v128_load(act4.own.data() + k);
			const v128_t reach = wasm_i32x4_add(wasm_i32x4_add(vrad, wasm_i32x4_min(v6, half)), wasm_v128_andnot(v3, own));
			const v128_t dx = wasm_i32x4_abs(wasm_i32x4_sub(wasm_v128_load(act4.x.data() + k), vpx));
			const v128_t dy = wasm_i32x4_abs(wasm_i32x4_sub(wasm_v128_load(act4.y.data() + k), vpy));
			const v128_t sel = wasm_v128_and(wasm_i32x4_le(age, vmax), wasm_i32x4_le(wasm_i32x4_max(dx, dy), reach));
			if (!wasm_v128_any_true(sel))
				continue;
			own_c += __builtin_popcount(wasm_i32x4_bitmask(wasm_v128_and(sel, own)));
			tn = wasm_i32x4_max(tn, wasm_v128_and(wasm_v128_andnot(sel, own), wasm_v128_load(act4.n.data() + k)));
		}
		own_n = static_cast<float>(own_c);
		const int tmax = std::max(std::max(wasm_i32x4_extract_lane(tn, 0), wasm_i32x4_extract_lane(tn, 1)),
			std::max(wasm_i32x4_extract_lane(tn, 2), wasm_i32x4_extract_lane(tn, 3)));
		team_n = static_cast<float>(tmax);
	}
	return std::max(own_n, team_n);
}


namespace {
void begin_turn_body();
void end_turn_body_qct();
// Alive state of every enemy body (one host call each). A death invalidates its last sighting: it respawns at home.
void read_foes(int t)
{
	if (!foes_read)
	{
		foes_read = true;
		{
			const auto ro = roster(team::enemy);
			for (const auto& r : ro)
				foes.push_back({ r.h, true, -1000 });
			tk_tab.assign(foes.size(), TeamSeen{});
			for (std::size_t i = 0; i < foes.size(); ++i)
			{
				tk_tab[i].h = foes[i].h;
				tk_tab[i].type = i < ro.size() ? ro[i].type : cambc::champion_type{};
				tk_tab[i].pos = M.enemy_anchor;
				tk_tab[i].round = 1;
				tk_tab[i].src = 4;
			}
		}
		team_bodies.assign(foes.size(), Body{});
		team_has_body.assign(foes.size(), 0);
		team_body_r.assign(foes.size(), -1000);
		fg_first.assign(foes.size(), FgFirst{});
	}
	foes_alive = 0;
	// Sizes and data are read once; the engine call in the loop would make every pass reload them. Nothing in the loop resizes foes
	// or tk_tab (the own loop only writes rounds).
	const std::size_t nf = foes.size(), ntk = tk_tab.size();
	auto* const fp = foes.data();
	auto* const tkp = tk_tab.data();
	int na = 0;
	for (std::size_t fi = 0; fi < nf; ++fi)
	{
		auto& f = fp[fi];
		std::int32_t alive = 1;
		if (cambc::detail::sdk_champion_is_alive(f.h, &alive) != 0)
			alive = 1;
		if ((alive != 0) == f.alive) // No change (the common case): only the two writes the full path makes.
		{
			if (fi < ntk)
				tkp[fi].alive = f.alive;
			na += f.alive ? 1 : 0;
			continue;
		}
		if (f.alive && alive == 0)
		{
			f.died = t;
			for (auto& s : own)
				if (s.h == f.h)
					s.round = -1000;
			if (fi < ntk)
			{
				tkp[fi].round = -1000; // it respawns at home
				if (fi < team_bodies.size()) // the killer took the bag
				{
					if (team_bodies[fi].kit && team_bodies[fi].kit->gem_focus) // PFD1: and its Focus
						team_bodies[fi].foc = std::max(0.0f, team_bodies[fi].foc - 1.5f * static_cast<float>(team_bodies[fi].gems));
					team_bodies[fi].gems = 0;
					Body& pb = team_bodies[fi];
					pb.hp = pb.maxhp;
					pb.shield = 0;
					pb.shield_turns = 0;
					pb.stunned = false;
					pb.cd = { 0, 0 };
					pb.state &= ~(ST_RECALL | ST_TRIBUTE | ST_TELEPORT); // no channel survives the death (RC C390)
				}
				if (fi < team_body_r.size()) // a death voids the last-seen bag
					team_body_r[fi] = -1000;
			}
		}
		if (fi < ntk)
		{
			if (!f.alive && alive != 0 && f.died > -1000)
			{
				tkp[fi].pos = M.enemy_anchor; // back on its spawn
				tkp[fi].round = t;
				tkp[fi].src = 4;
			}
			tkp[fi].alive = alive != 0;
		}
		f.alive = alive != 0;
		na += f.alive ? 1 : 0;
	}
	foes_alive = na;
}

} // namespace

int enemies_alive() { return foes_read ? foes_alive : static_cast<int>(foes.size()); }
void init()
{
	if (!M.ready())
		return;
	try
	{
		size_event_tables();
		read_foes(W.round);
	}
	catch (...)
	{
		FXR_PASS();
	}
}
int enemies_total() { return static_cast<int>(foes.size()); }
// Kill window: the round the first dead enemy body can stand on its spawn again (a death keeps it out 60 rounds), or a far round
// when none is dead.
int earliest_respawn()
{
	int r = 1000000;
	for (const auto& f : foes)
		if (!f.alive)
		{
			r = std::min(r, f.died + (rs::rules().respawn) - (0)); // BB8 bit 64's off-by-one fix not shipped
		}
	return r;
}
int latest_sighting() { return latest; }

// CONTEST: distinct living enemies whose own or ward sighting (at most `age` rounds old) is within r of c.
int recent_own(vec2* out, int cap, int age)
{
	const int t = now();
	int n = 0;
	for (const auto& s : own)
		if (s.round >= t - age)
		{
			if (n < cap)
				out[n] = s.pos;
			++n;
		}
	return n;
}
int count_near(vec2 c, int r, int age)
{
	const int t = now();
	int n = 0;
	for (const auto& s : own)
		if (s.round >= t - age && cheb(s.pos, c) <= r)
			++n;
	return n;
}

// CONTEST: enemies that can stand at a tile `walk` rounds from their spawn by round t: the living ones plus the dead ones whose
// respawn (death + 60) and walk end by t.
int possible_at(int t, int walk)
{
	if (!foes_read)
		return static_cast<int>(foes.size());
	int n = 0;
	for (const auto& f : foes)
	{
		if (f.alive || (f.died + (rs::rules().respawn) + walk) <= t) // BB8 bit 64's off-by-one fix not shipped
			++n;
	}
	return n;
}

// WINBANK: rounds until any enemy body can stand within `reach` of p: a living one from its last own sighting (else its spawn since
// its respawn, or since round 0), walking `spd_x100`/100 tiles a round since then; a dead one from its spawn after its respawn
// round. BIG with no roster.
int reach_rounds(vec2 p, int reach, vec2 spawn, int spd_x100)
{
	const int t = now();
	const int resp = rs::rules().respawn;
	int best = BIG;
	for (const auto& f : foes)
	{
		vec2 from = spawn;
		int since = 0, wait = 0;
		if (!f.alive)
		{
			wait = std::max(0, f.died + resp - t);
			since = t;
		}
		else
		{
			const Seen* s = nullptr;
			for (const auto& x : own)
				if (x.h == f.h)
					s = &x;
			if (s && s->round > -1000 && s->round >= f.died)
			{
				from = s->pos;
				since = s->round;
			}
			else
				since = f.died > -1000 ? std::min(t, f.died + resp) : 0;
		}
		const int walked = (std::max(0, t - since) * spd_x100) / 100;
		const int r = wait + std::max(0, cheb(from, p) - reach - walked) * 100 / std::max(1, spd_x100);
		best = std::min(best, r);
	}
	return best;
}
int foe_died_round(std::uint32_t h)
{
	for (const auto& f : foes)
		if (f.h == h)
			return f.died;
	return -1000;
}
int last_death()
{
	int r = -1000;
	for (const auto& f : foes)
		r = std::max(r, f.died);
	return r;
}
void begin_turn()
{
	if (!M.ready())
		return;
	try
	{
		begin_turn_body();
	}
	catch (...)
	{
		FXR_PASS();
	}
}
void end_turn()
{
	if (!M.ready() || now() < 2 || P.my_slot < 0)
		return;
	VB3_CNT(2, [&] { int n = 0; for (const auto& e : W.enemies) { const int ti = team_index(e.h); n += (ti >= 0 && tk_tab[static_cast<std::size_t>(ti)].round != now()) ? 1 : 0; } return n > 0; }()); // VB3 IRP1: a foe first seen mid-turn
	try
	{
		end_turn_body_qct();
	}
	catch (...)
	{
		FXR_PASS();
	}
}

namespace {
void begin_turn_body()
{
	size_event_tables();
	const int t = now();
	read_foes(t);
	auto note = [&](const Body& e, bool ward, bool far)
	{
		if (const int ti = team_index(e.h); ti >= 0) // my own sight or ward
		{
			auto& ts = tk_tab[static_cast<std::size_t>(ti)];
			ts.pos = e.pos;
			ts.round = t;
			ts.src = ward ? 2 : 1;
			if (const int wbg = WBG_TAB[1]; (wbg & 1) && (far || cheb(e.pos, W.me.pos) > 9))
			{
				Body& tb = team_bodies[static_cast<std::size_t>(ti)];
				const std::uint32_t old = team_has_body[static_cast<std::size_t>(ti)] ? tb.gems : 0u;
				vcopy(tb, e);
				std::uint32_t g = 0;
				tb.gems = cambc::detail::sdk_champion_gems(e.h, &g) == 0 ? g : old;
			}
			else
				vcopy(team_bodies[static_cast<std::size_t>(ti)], e);
			team_has_body[static_cast<std::size_t>(ti)] = 1;
			team_body_r[static_cast<std::size_t>(ti)] = t;
			if (mu::bits != 0 && (mu::bits & 2048) != 0 && static_cast<std::size_t>(ti) < fg_first.size())
			{
				FgFirst& g = fg_first[static_cast<std::size_t>(ti)];
				if (g.r0 < 0)
				{
					g.r0 = t;
					g.str = e.str;
					g.foc = e.foc;
					g.mh = e.maxhp;
				}
				g.r1 = t;
			}
		}
		Seen* slot = nullptr;
		for (auto& s : own)
			if (s.h == e.h)
			{
				slot = &s;
				break;
			}
		if (!slot)
		{
			own.push_back({ e.h, e.pos, t });
			slot = &own.back();
		}
		slot->pos = e.pos;
		slot->round = t;
		latest = t;
		if (!W.alive)
		{
			((void)0);
		}
		else if (cheb(e.pos, W.me.pos) > 8)
		{
			((void)0);
		}
	};
	for (const auto& e : W.enemies)
		note(e, !W.alive, false);
	for (const auto& e : W.enemies_far)
		note(e, true, true);
	const comms::Event ev = comms::ev();
	if (ev.subject >= 0 && ev.raw != last_raw)
	{
		last_raw = ev.raw;
		const int age = (t - ev.stamp) & comms::STAMP_MASK;
		if (ev.type < comms::EV_TYPE_HELP) // HELP calls belong to the backup module
			handle(ev.subject, ev.type, t - age);
	}
}

int qct_pend = -1000, qct_n = 0; // QCT: the contact waiting to be posted (round, foes within 6)
// the quiet-channel-table version of end_turn's body; end_turn calls it only when that table's flag is non-zero.
void end_turn_body_qct()
{
	size_event_tables();
	const int t = now();
	news.erase(std::remove_if(news.begin(), news.end(), [&](const News& n) { return t - n.round > NEWS_TTL; }), news.end());
	if (news.empty() && W.enemies.empty() && W.enemies_far.empty())
		return; // v683 FB23: nothing to post (best stays empty)
	Cand best;
	// Group news first (captures and enemy clears seen by us, usually through the ward).
	for (std::size_t i = 0; i < news.size(); ++i)
	{
		const auto& n = news[i];
		const int rel = relevance(n.gi);
		if (rel < 2)
			continue;
		const int sc = priority(n.type) * 10 + rel * 3;
		if (sc > best.score)
			best = { n.gi, n.type, n.round, sc, i };
	}
	const comms::Event cur = comms::ev();
	const bool cur_sight = comms::is_sight(cur); // no stamp; intel news may overwrite it
	const int cur_age0 = cur.subject >= 0 && !cur_sight ? (comms::event_age_rounds(cur, t)) : 99;
	const bool qct_chan = econ::tm2_channel_on(); // QCT bits 8/16
	const bool qct_nohold = qct_chan;
	if (cur.subject >= 0 && !cur_sight && cur.type >= comms::EV_TYPE_HELP && cur_age0 < HELP_HOLD && !qct_nohold)
		return; // a fresh HELP call outranks any news
	// the HOLD protects a post for HOLD rounds after it was written (first seen), whatever round it reports
	const int cur_age = (cur.subject >= 0 && !cur_sight) ? comms::rounds_since_event_slot_changed(t) : cur_age0;
	const bool slot_locked = cur.subject >= 0 && cur_age < HOLD && cur.type == EV_ENEMIES;
	// Enemy sightings near subjects the team cares about (counted per subject). A dead champion's come from its ward.
	if ((!W.enemies.empty() || !W.enemies_far.empty()) && !slot_locked)
	{
		std::array<int, 6> subj{};
		std::array<int, 6> cnt{};
		int k = 0;
		const std::size_t ne = W.enemies.size();
		for (std::size_t ei = 0; ei < ne + W.enemies_far.size(); ++ei)
		{
			const Body& e = ei < ne ? W.enemies[ei] : W.enemies_far[ei - ne];
			const int s = subject_of(e.pos);
			if (s < 0)
				continue;
			int j = 0;
			while (j < k && subj[static_cast<std::size_t>(j)] != s)
				++j;
			if (j == k)
			{
				if (k >= 6)
					continue;
				subj[static_cast<std::size_t>(k)] = s;
				cnt[static_cast<std::size_t>(k)] = 0;
				++k;
			}
			++cnt[static_cast<std::size_t>(j)];
		}
		for (int j = 0; j < k; ++j)
		{
			const int s = subj[static_cast<std::size_t>(j)];
			if (t - last_ev[static_cast<std::size_t>(s)] < (REPOST)) // TM2 bit 256
				continue;
			const int type = cnt[static_cast<std::size_t>(j)] >= 2 ? EV_ENEMIES : EV_ENEMY;
			const int rel = relevance(s);
			if (rel < 2 && type == EV_ENEMY)
				continue;
			const int sc = priority(type) * 10 + rel * 3;
			if (sc > best.score)
				best = { s, type, t, sc, SIZE_MAX };
		}
	}
	// A fresh TAKEN / CLEARED post stands against any news (it is never re-sent)
	const bool nh_keep = cur.subject >= 0 && !cur_sight && cur_age < HOLD && (cur.type == EV_TAKEN || cur.type == EV_CLEARED);
	if (best.subject < 0 || (((cur.subject >= 0 && cur_age < HOLD && priority(best.type) <= priority(cur.type)) || nh_keep)))
	{
 // no intel news this turn
		return;
	}
	econ::bhf_lp = 2; // BHF bit 128
	comms::write_event(best.subject, best.type, best.round);
	last_raw = comms::ev().raw;
	if (best.type != EV_TAKEN && !(best.type == EV_CLEARED && best.subject < n_groups() && econ::group_is_ours_to_post(best.subject)) && !(econ::bhf_lp == 0)) // BHF bit 128: TM2 dropped or blocked my post, so no mate adds it
		add_shared(subject_pos(best.subject), best.round, best.type == EV_ENEMIES ? 2 : 1);
	last_ev[static_cast<std::size_t>(best.subject)] = t;
	(void)0;
	if (best.type == EV_ENEMY || best.type == EV_ENEMIES)
	{
		((void)0); // QCT bit 2
	}
	if (best.news_idx < news.size())
		news.erase(news.begin() + static_cast<std::ptrdiff_t>(best.news_idx));
	NLOG("r%d slot %d intel post type %d subject %d round %d\n", t, P.my_slot, best.type, best.subject, best.round);
}

} // namespace

} // namespace nova::intel
