// ward_spots.cc: Candidate ward spots and their weights.
#include "ward_internal.h"
namespace nova::ward {
namespace {
void read_consts()
{
	if (consts_read)
		return;
	consts_read = true;
	try
	{
		vision_r = std::clamp(static_cast<int>(cambc::constants::ward_vision_radius), 1, 12);
		reach_r = std::clamp(static_cast<int>(cambc::constants::ward_placement_radius), 0, 4);
		recharge = std::clamp(static_cast<int>(cambc::constants::ward_cooldown), 1, 100);
	}
	catch (...)
	{
		FXR_PASS();
	}
}

// 1 for central groups, falling toward each spawn (our side keeps more: enemies raiding it matter to us).
float contest_factor(float c)
{
	if (c >= 0.38f && c <= 0.62f)
		return 1.0f;
	if (c < 0.38f)
		return 0.35f + 0.65f * c / 0.38f;
	return 0.2f + 0.8f * (1.0f - c) / 0.38f;
}
// Centre and up to four key tiles spread over pts (greedy farthest point). Cost O(|pts| * keys^2): callers pass at most KEY_SAMPLE
// points.
void pick_keys(Spot& s, const std::vector<vec2>& pts)
{
	s.nk = 0;
	if (pts.empty())
		return;
	long sum_x = 0, sum_y = 0;
	for (const vec2 p : pts)
	{
		sum_x += p.x;
		sum_y += p.y;
	}
	const long n = static_cast<long>(pts.size());
	const vec2 mean{ static_cast<int>(sum_x / n), static_cast<int>(sum_y / n) };
	vec2 c = pts[0];
	int bd = BIG;
	for (const vec2 p : pts)
	{
		const int d = cheb(p, mean);
		if (d < bd)
		{
			bd = d;
			c = p;
		}
	}
	s.c = c;
	s.key[s.nk++] = c;
	const std::size_t max_keys = s.kind == K_GROUP ? 3 : 4;
	while (s.nk < max_keys && s.nk < pts.size())
	{
		vec2 far = c;
		int fd = 0;
		for (const vec2 p : pts)
		{
			int dmin = BIG;
			for (int i = 0; i < s.nk; ++i)
				dmin = std::min(dmin, cheb(p, s.key[static_cast<std::size_t>(i)]));
			if (dmin > fd)
			{
				fd = dmin;
				far = p;
			}
		}
		if (fd <= 0)
			break;
		s.key[s.nk++] = far;
	}
	s.ext = 0;
	for (int i = 0; i < s.nk; ++i)
		s.ext = std::max(s.ext, cheb(s.c, s.key[static_cast<std::size_t>(i)]));
}

// Every `stride`-th point of pts, at most KEY_SAMPLE of them.
void sample(const std::vector<vec2>& pts, std::vector<vec2>& out)
{
	out.clear();
	const std::size_t step = std::max<std::size_t>(1, (pts.size() + KEY_SAMPLE - 1) / KEY_SAMPLE);
	for (std::size_t i = 0; i < pts.size(); i += step)
		out.push_back(pts[i]);
}

// One group's spot (A_BASIC step).
void add_group_spot(const GroupI& g, std::vector<vec2>& pts)
{
	const float gold_w = M.any_altar ? 0.1f : 1.0f;
	const float value = static_cast<float>(g.gems) + gold_w * static_cast<float>(g.gold);
	if (value <= 0)
		return;
	const float af = g.access == ACC_WALK ? 1.0f : (g.access == ACC_DASH ? 0.7f : 0.5f);
	Spot s;
	s.kind = K_GROUP;
	s.ref = static_cast<std::int16_t>(g.idx);
	s.w0 = value * contest_factor(g.contest) * af;
	std::vector<vec2> all;
	for (int ci : g.members)
		all.push_back(M.camps[static_cast<std::size_t>(ci)].pos);
	sample(all, pts);
	pick_keys(s, pts);
	spots.push_back(s);
}

// Altars: how likely each team banks there (near its nearest altar, fading over 24 more tiles).
void add_altar_spots()
{
	std::uint16_t near_us = UNREACH, near_them = UNREACH;
	for (const auto& a : M.altars)
	{
		near_us = std::min(near_us, a.d_home);
		near_them = std::min(near_them, a.d_enemy);
	}
	auto usage = [](std::uint16_t d, std::uint16_t nearest)
	{
		if (d == UNREACH || nearest == UNREACH)
			return 0.25f;
		const float extra = static_cast<float>(d) - static_cast<float>(nearest);
		return extra <= 8.0f ? 1.0f : std::max(0.0f, 1.0f - (extra - 8.0f) / 24.0f);
	};
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.na); ++i)
	{
		const auto& a = M.altars[i];
		Spot s;
		s.kind = K_ALTAR;
		s.ref = static_cast<std::int16_t>(i);
		s.c = a.pos;
		s.key[0] = a.pos;
		s.nk = 1;
		s.w0 = 15.0f * usage(a.d_home, near_us) + 20.0f * usage(a.d_enemy, near_them);
		if (s.w0 > 1.0f)
			spots.push_back(s);
	}
}

// Corridor levels narrow enough to watch: runs of levels with 1-3 corridor tiles, one spot per 12 levels of a run.
void build_chokes()
{
	if (S <= 0 || width.empty())
		return;
	struct C
	{
		int L;
		float w;
	};
	std::vector<C> cands;
	const int lo = std::max(2, S / 8), hi = std::min(S - lo, static_cast<int>(width.size()) - 1);
	auto narrow = [&](int L) { return width[static_cast<std::size_t>(L)] >= 1 && width[static_cast<std::size_t>(L)] <= 3; };
	int L = lo;
	while (L <= hi)
	{
		if (!narrow(L))
		{
			++L;
			continue;
		}
		int end = L;
		while (end + 1 <= hi && narrow(end + 1) && end + 1 - L < 12)
			++end;
		int best = (L + end) / 2;
		for (int k = L; k <= end; ++k)
			if (width[static_cast<std::size_t>(k)] < width[static_cast<std::size_t>(best)])
				best = k;
		const int wd = width[static_cast<std::size_t>(best)];
		const float nf = wd == 1 ? 1.0f : (wd == 2 ? 0.85f : 0.65f);
		const float pf = 0.6f + 0.4f * (1.0f - std::fabs(2.0f * static_cast<float>(best) / static_cast<float>(S) - 1.0f));
		cands.push_back({ best, 30.0f * nf * pf });
		L = end + 1;
	}
	std::sort(cands.begin(), cands.end(), [](const C& a, const C& b) { return a.w > b.w; });
	std::vector<int> chosen;
	std::vector<vec2> pts;
	for (const auto& c : cands)
	{
		bool ok = true;
		for (int l : chosen)
			if (std::abs(l - c.L) < 8)
				ok = false;
		if (!ok)
			continue;
		chosen.push_back(c.L);
		Spot s;
		s.kind = K_CHOKE;
		s.ref = static_cast<std::int16_t>(c.L);
		s.w0 = c.w;
		pts.clear();
		const int n = std::min<int>(4, width[static_cast<std::size_t>(c.L)]);
		for (int i = 0; i < n; ++i)
			pts.push_back(lvl_tiles[static_cast<std::size_t>(c.L)][static_cast<std::size_t>(i)]);
		pick_keys(s, pts);
		spots.push_back(s);
		NLOG("ward choke L%d/%d width %d at %d,%d w %.1f\n", c.L, S, width[static_cast<std::size_t>(c.L)], s.c.x, s.c.y, s.w0);
		if (static_cast<int>(chosen.size()) >= MAX_CHOKE)
			break;
	}
}

// Scoring one bush cluster: next to the route corridor, to valuable groups or to altars. Distance tests use at most KEY_SAMPLE tiles
// of the cluster and run spot by spot with fuel checks (one test costs ~30 fuel per sample).
struct BushScore
{
	bool active = false;
	int id = 0;
	std::size_t size = 0, si = 0;
	std::vector<vec2> smp;
	int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
	bool near_corr = false;
	float gpart = 0, apart = 0;
};
BushScore bs;

void bush_score_begin(int id, const std::vector<vec2>& tiles)
{
	bs.active = tiles.size() >= 2;
	if (!bs.active)
		return;
	bs.id = id;
	bs.size = tiles.size();
	bs.si = 0;
	sample(tiles, bs.smp);
	bs.x0 = bs.y0 = BIG;
	bs.x1 = bs.y1 = -BIG;
	for (const vec2 p : tiles)
	{
		bs.x0 = std::min(bs.x0, p.x);
		bs.y0 = std::min(bs.y0, p.y);
		bs.x1 = std::max(bs.x1, p.x);
		bs.y1 = std::max(bs.y1, p.y);
	}
	bs.near_corr = false;
	if (have_corridor)
		for (std::size_t i = 0; i < bs.smp.size() && !bs.near_corr; ++i)
			for (int d = 0; d < 8 && !bs.near_corr; d += 2)
			{
				const vec2 q = bs.smp[i] + DIRS[static_cast<std::size_t>(d)];
				bs.near_corr = inb(q) && bbget(corridor, q);
			}
	bs.gpart = bs.apart = 0;
}

// Continue scoring; true when the cluster is done (kept among the best MAX_BUSH if it is worth a ward).
bool bush_score_step(long reserve, std::size_t n_basic)
{
	while (bs.si < n_basic && bs.si < spots.size())
	{
		if (fuel() < reserve + 4000)
			return false;
		const Spot& s = spots[bs.si++];
		const int reach = 3 + s.ext;
		const int dx = std::max({ 0, bs.x0 - s.c.x, s.c.x - bs.x1 }), dy = std::max({ 0, bs.y0 - s.c.y, s.c.y - bs.y1 });
		if (std::max(dx, dy) > reach)
			continue;
		bool close = false;
		for (std::size_t i = 0; i < bs.smp.size() && !close; ++i)
			close = cheb(bs.smp[i], s.c) <= reach;
		if (!close)
			continue;
		if (s.kind == K_GROUP)
			bs.gpart += 0.3f * s.w0;
		else
			bs.apart += 0.3f * s.w0;
	}
	if (fuel() < reserve + 10000)
		return false;
	bs.active = false;
	float w = (bs.near_corr ? 10.0f : 0.0f) + bs.gpart + bs.apart;
	w = std::min(w, 35.0f) * (bs.size >= 3 ? 1.0f : 0.7f);
	if (w < 5.0f)
		return true;
	std::size_t slot = bush_spots.size();
	if (bush_spots.size() >= static_cast<std::size_t>(MAX_BUSH))
	{
		slot = 0;
		for (std::size_t i = 1; i < bush_spots.size(); ++i)
			if (bush_spots[i].w0 < bush_spots[slot].w0)
				slot = i;
		if (bush_spots[slot].w0 >= w)
			return true;
	}
	Spot s;
	s.kind = K_BUSH;
	s.ref = static_cast<std::int16_t>(bs.id);
	s.w0 = w;
	pick_keys(s, bs.smp);
	if (slot == bush_spots.size())
		bush_spots.push_back(s);
	else
		bush_spots[slot] = s;
	return true;
}

// Groups claimed by allies or me this turn (read once per turn).
std::vector<std::uint8_t> claimed;
int claimed_round = -1;
void refresh_claims()
{
	if (claimed_round == now() && claimed.size() == static_cast<std::size_t>(M.ng))
		return;
	claimed.assign(static_cast<std::size_t>(M.ng), 0);
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
	{
		const int g = s == P.my_slot ? econ::claim_target() : comms::cgroup(s);
		if (g >= 0 && static_cast<std::size_t>(g) < claimed.size())
			claimed[static_cast<std::size_t>(g)] = 1;
	}
	claimed_round = now();
}
bool claimed_by_team(int gi)
{
	refresh_claims();
	return gi >= 0 && static_cast<std::size_t>(gi) < claimed.size() && claimed[static_cast<std::size_t>(gi)] != 0;
}

// Current weight of a spot.
float weight(const Spot& s)
{
	float w = s.w0;
	if (s.kind == K_GROUP)
	{
		const std::vector<econ::GroupMem>& mem = econ::memory();
		if (s.ref >= 0 && static_cast<std::size_t>(s.ref) < mem.size())
		{
			const auto& m = mem[static_cast<std::size_t>(s.ref)];
			if (m.status == econ::GS_RESPAWN)
			{
				const int t = m.respawn_at - now();
				w *= t > 60 ? 0.5f : (t < 25 ? 1.4f : 1.0f);
			}
			else if (now() - m.seen > 80)
				w *= 1.2f;
		}
		if (claimed_by_team(s.ref))
			w *= 1.3f;
	}
	else if (s.kind == K_ALTAR && W.me.gems >= 10)
		w *= 1.3f;
	// Where enemies were seen lately, they tend to come back.
	w *= 1.0f + 0.4f * std::min(3.0f, intel::danger(s.c, 6 + s.ext, 40));
	return w;
}

// Spot weights change slowly (respawn timers, claims, sightings): reuse them for a few turns. A recomputation costs ~1k (the
// sightings scan), so each act() call refreshes at most WEIGHT_BUDGET of them; the rest stay a little stale.
std::vector<float> w_cache;
std::vector<int> w_round;
int weight_budget = 0;
float weight_cached(std::size_t i)
{
	if (w_cache.size() != spots.size())
	{
		w_cache.assign(spots.size(), 0.0f);
		w_round.assign(spots.size(), -1000);
	}
	if (now() - w_round[i] >= 8)
	{
		if (weight_budget > 0 && fuel() > ACT_FLOOR)
		{
			--weight_budget;
			w_cache[i] = weight(spots[i]);
			w_round[i] = now();
		}
		else if (w_round[i] < 0)
			return spots[i].w0; // never computed: the static weight for now
	}
	return w_cache[i];
}

NOVA_INLINE float cover(const Spot& s, const bitboard& V) // Inline at both scan sites.
{
	int n = 0;
	for (int i = 0; i < s.nk; ++i)
		if (bbget(V, s.key[static_cast<std::size_t>(i)]))
			++n;
	if (n == 0)
		return 0;
	const float f = static_cast<float>(n) / static_cast<float>(s.nk);
	return s.kind == K_GROUP ? 0.6f + 0.4f * f : f;
}
// Rebuild the coverage cache for the current spot list: O(map) + O(spots).
void ward_coverage_cache_reset()
{
	cov_ref.reset();
	cov_pool.clear();
	// Growing a vector copies it (about one fuel per byte): reserve the whole pool once, uninitialised.
	if (cov_pool.capacity() < POOL_MAX + 256)
		cov_pool.reserve(POOL_MAX + 256);
	sx.resize(spots.size());
	sy.resize(spots.size());
	srad.resize(spots.size());
	for (std::size_t i = 0; i < spots.size(); ++i)
	{
		sx[i] = spots[i].c.x;
		sy[i] = spots[i].c.y;
		srad[i] = vision_r + spots[i].ext;
	}
	acov_dirty = true;
}

bool cache_ready() { return sx.size() == spots.size() && cov_ref.ready(); }

struct CovList
{
	const CovEntry* e;
	int n; // -1: not cached and no budget left this call
};
} // namespace
} // namespace nova::ward
