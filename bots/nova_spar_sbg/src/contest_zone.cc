// contest_zone.cc: Contested zone: computed in the draft from the map layout; memory block. CONTEST: contested zone, swing gate and
// the draft-memory block (see contest_zone.h). Draft side: bounded walk fields per contested group (tier 2), complete-linkage
// clusters of walk diameter 10, minimax-walk hold, plus the swing gate. Play side: decode.
#include "contest_zone.h"

#include <algorithm>
#include <array>
#include <climits>
#include <memory>

#include "mapinfo.h"
#include "plan.h"

namespace nova::zone {

namespace {

constexpr int CONT_M = 8;  // contested: |d_enemy - d_home| <= 8
constexpr int ZONE_D = 10; // complete-linkage walk diameter
constexpr int MAXC = 32;   // contested groups considered (by value)
constexpr int MAXZ = 4;    // zones kept
constexpr float GMIN = 0.5f, BODY_DPS = 55.0f, CAPT = 6.0f, WORK_O = 0.5f, WORK_Z = 0.7f;
constexpr int MARGIN_MIN = -5, REACH = 45; // Zones up to 5 steps closer to them still count.

struct Zone
{
	int n = 0;
	int members[MAXM]{};
	vec2 hold{};
	int radius = -1;
	float orate = 0, grate = 0;
	int cycle = 0;
};

Block B;
int stage = 0;
std::size_t cur = 0;
std::vector<int> C;                              // contested groups, most valuable first
std::vector<std::array<int, 4>> box;             // member bounding boxes of C
std::vector<std::uint8_t> dm; // Pairwise walk over C (255 = beyond ZONE_D).
std::vector<std::vector<int>> zs;                // kept zones: indices into C
std::vector<std::unique_ptr<distance_field>> fld; // bounded member fields
long fc_seen = 0;
Zone Zn[MAXZ];
int nz = 0;

bool mono(const GroupI& g) { return g.n_mono > 0; }
bool wide(const GroupI& g)
{
	int x0 = G.w, y0 = G.h, x1 = -1, y1 = -1;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		x0 = std::min(x0, p.x); y0 = std::min(y0, p.y); x1 = std::max(x1, p.x); y1 = std::max(y1, p.y);
	}
	return x1 >= 0 && std::max(x1 - x0, y1 - y0) > ZG_SPAN_MAX;
}
float resp(const GroupI& g) { return static_cast<float>(g.respawn > 0 ? g.respawn : 50); }
float valz(const GroupI& g) { return mono(g) ? 0.0f : (static_cast<float>(g.gems) + 0.3f * static_cast<float>(g.gold)) / resp(g); }
float valg(const GroupI& g) { return (static_cast<float>(g.gems) + CT_WG * static_cast<float>(g.gold)) / resp(g); }
void features()
{
	C.clear();
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
	{
		const auto& g = M.groups[i];
		if (g.access != ACC_WALK || mono(g) || g.d_home == UNREACH || g.d_enemy == UNREACH)
			continue;
		if (wide(g))
			continue; // Wider than a zone.
		const int m = static_cast<int>(g.d_enemy) - static_cast<int>(g.d_home);
		if (m >= -CONT_M && m <= CONT_M && valz(g) > 0)
			C.push_back(static_cast<int>(i));
	}
	std::sort(C.begin(), C.end(), [](int a, int b) {
		const float va = valz(M.groups[static_cast<std::size_t>(a)]), vb = valz(M.groups[static_cast<std::size_t>(b)]);
		return va != vb ? va > vb : a < b;
	});
	if (C.size() > static_cast<std::size_t>(MAXC))
		C.resize(MAXC);
	box.assign(C.size(), { G.w, G.h, -1, -1 });
	for (std::size_t a = 0; a < C.size(); ++a)
		for (int ci : M.groups[static_cast<std::size_t>(C[a])].members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			box[a][0] = std::min(box[a][0], p.x);
			box[a][1] = std::min(box[a][1], p.y);
			box[a][2] = std::max(box[a][2], p.x);
			box[a][3] = std::max(box[a][3], p.y);
		}
	dm.assign(C.size() * C.size(), 255);
}
void cluster()
{
	const std::size_t n = C.size();
	std::vector<int> zid(n, -1);
	std::vector<std::vector<int>> all;
	for (std::size_t a = 0; a < n; ++a)
	{
		if (zid[a] >= 0)
			continue;
		std::vector<int> mem{ static_cast<int>(a) };
		zid[a] = static_cast<int>(all.size());
		std::vector<std::pair<int, int>> cand;
		for (std::size_t b = 0; b < n; ++b)
			if (zid[b] < 0 && dm[a * n + b] <= ZONE_D)
				cand.emplace_back(dm[a * n + b], static_cast<int>(b));
		std::sort(cand.begin(), cand.end());
		for (const auto& [d, b] : cand)
		{
			bool ok = true;
			for (int m : mem)
				if (dm[static_cast<std::size_t>(m) * n + static_cast<std::size_t>(b)] > ZONE_D)
				{
					ok = false;
					break;
				}
			if (ok)
			{
				mem.push_back(b);
				zid[static_cast<std::size_t>(b)] = static_cast<int>(all.size());
			}
		}
		all.push_back(std::move(mem));
	}
	std::vector<std::pair<float, int>> order;
	for (std::size_t z = 0; z < all.size(); ++z)
	{
		float v = 0;
		for (int m : all[z])
			v += valz(M.groups[static_cast<std::size_t>(C[static_cast<std::size_t>(m)])]);
		order.emplace_back(-v, static_cast<int>(z));
	}
	std::sort(order.begin(), order.end());
	nz = 0;
	zs.clear();
	for (const auto& [v, z] : order)
	{
		if (nz >= MAXZ)
			break;
		Zone& Z = Zn[nz];
		Z = Zone{};
		for (int m : all[static_cast<std::size_t>(z)])
		{
			const int gi = C[static_cast<std::size_t>(m)];
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			if (Z.n < MAXM)
				Z.members[Z.n++] = gi;
			Z.orate += static_cast<float>(g.gems) / resp(g);
			Z.grate += static_cast<float>(g.gold) / resp(g);
			Z.cycle = std::max(Z.cycle, g.respawn);
		}
		zs.push_back(all[static_cast<std::size_t>(z)]);
		++nz;
	}
}

bitboard tiles_of(int gi)
{
	bitboard t;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		bbset(t, M.camps[static_cast<std::size_t>(ci)].pos);
	return t;
}

bool hold_walk(int z, long reserve)
{
	Zone& Z = Zn[z];
	const auto& mem = zs[static_cast<std::size_t>(z)];
	int x0 = G.w, y0 = G.h, x1 = -1, y1 = -1;
	for (int m : mem)
	{
		const auto& b = box[static_cast<std::size_t>(m)];
		x0 = std::min(x0, b[0]);
		y0 = std::min(y0, b[1]);
		x1 = std::max(x1, b[2]);
		y1 = std::max(y1, b[3]);
	}
	x0 = std::max(0, x0 - 3);
	y0 = std::max(0, y0 - 3);
	x1 = std::min(G.w - 1, x1 + 3);
	y1 = std::min(G.h - 1, y1 + 3);
	std::vector<FView> vs;
	for (int m : mem)
		if (fld[static_cast<std::size_t>(m)] && static_cast<int>(vs.size()) < MAXM) // the members the block keeps
			vs.push_back(fview(*fld[static_cast<std::size_t>(m)]));
	const BView vb = bview(M.block), vc = bview(M.camp_tiles), vs1 = bview(M.my_spawn);
	// Resumable by rows over draft turns (a large zone's scan can cost more than one later turn's spare fuel).
	static int hw_z = -1, hw_y = 0, best = BIG, bsum = BIG;
	if (hw_z != z)
	{
		hw_z = z;
		hw_y = y0;
		best = BIG;
		bsum = BIG;
	}
	for (int y = hw_y; y <= y1; ++y)
	{
		if (fuel() < reserve + 4000)
		{
			hw_y = y;
			return false; // continued next draft turn
		}
		for (int x = x0; x <= x1; ++x)
		{
			const vec2 p{ x, y };
			if (vb(p) || vc(p) || vs1(p))
				continue;
			int mx = 0, sm = 0;
			for (const auto& v : vs)
			{
				const int d = v(p);
				if (d > mx)
					mx = d;
				sm += d;
				if (mx > best)
					break;
			}
			if (mx < best || (mx == best && sm < bsum))
			{
				best = mx;
				bsum = sm;
				Z.hold = p;
			}
		}
	}
	Z.radius = best >= static_cast<int>(UNREACH) || best == BIG ? -1 : best;
	hw_z = -1;
	return true;
}

struct HG
{
	float val, w, need; // gem units per round, body-rounds per capture, body-rounds per round
};

// Greedy by value per body-round of work, filling bodies x work body-rounds per round.
float harvest(const std::vector<HG>& gs, float bodies, float work)
{
	const float cap = std::max(0.0f, bodies) * work;
	float used = 0, v = 0;
	for (const auto& g : gs)
	{
		if (g.need <= 0)
			continue;
		if (used + g.need <= cap)
		{
			used += g.need;
			v += g.val;
		}
		else
		{
			v += g.val * std::max(0.0f, cap - used) / g.need;
			break;
		}
	}
	return v;
}
std::vector<HG> harvest_groups_of(const std::vector<int>& gis)
{
	std::vector<HG> out;
	for (int gi : gis)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const float w = g.hp / BODY_DPS + CAPT;
		out.push_back({ valg(g), w, w / resp(g) });
	}
	std::sort(out.begin(), out.end(), [](const HG& a, const HG& b) { return a.val / a.w > b.val / b.w; });
	return out;
}

// Inputs for the gate, computed before it in their own resumable pass: inside gate() they could empty a draft turn's fuel, so the
// engine randomized our remaining picks, and on later draft turns the gate might never finish. The pass computes the spawn-to-spawn
// walk, then each zone's own-side cost with our-half contested groups nearer than its hold, never below the safe-only cost (harvest
// is not concave, so a superset could cost less).
int zg_s2s = BIG;
bool zg_s2s_done = false;
int zg_cur = 0;
float zg_cost[MAXZ]{};
std::vector<int> safe_groups()
{
	std::vector<int> safe;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
	{
		const auto& g = M.groups[i];
		if (g.access != ACC_WALK || mono(g) || g.d_home == UNREACH || g.d_enemy == UNREACH || valg(g) <= 0)
			continue;
		if (static_cast<int>(g.d_enemy) - static_cast<int>(g.d_home) > CONT_M)
			safe.push_back(static_cast<int>(i));
	}
	return safe;
}
bool prepare_contest_zone_gate(int T, long reserve)
{
	if (!M.has_home || !M.has_enemy)
		return true;
	const FView fh = fview(M.f_home);
	if (!zg_s2s_done)
	{
		if (fuel() < reserve + 30000)
			return false;
		bbforeach(M.enemy_spawn,
			[&](vec2 p)
			{
				for (const vec2 d : DIRS)
				{
					const vec2 q = p + d;
					if (inb(q) && !bbget(M.enemy_spawn, q))
						zg_s2s = std::min(zg_s2s, static_cast<int>(fh(q)));
				}
			});
		zg_s2s_done = true;
	}
	if (zg_cur >= nz)
		return true;
	const int K0 = std::min(T, 3);
	const std::vector<int> safe = safe_groups();
	const auto hs = harvest_groups_of(safe);
	const float cost0 = harvest(hs, static_cast<float>(T), WORK_O) - harvest(hs, static_cast<float>(std::max(0, T - K0)), WORK_O);
	while (zg_cur < nz)
	{
		if (fuel() < reserve + 20000)
			return false;
		const Zone& Z = Zn[zg_cur];
		float c = cost0;
		if (Z.radius >= 0 && Z.n > 0)
		{
			const int dA = fh(Z.hold);
			std::vector<int> alt = safe;
			for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
			{
				const auto& g = M.groups[i];
				if (g.access != ACC_WALK || mono(g) || g.d_home == UNREACH || g.d_enemy == UNREACH || valg(g) <= 0)
					continue;
				const int m = static_cast<int>(g.d_enemy) - static_cast<int>(g.d_home);
				if (m < 0 || m > CONT_M || static_cast<int>(g.d_home) >= dA ||
					std::find(Z.members, Z.members + Z.n, static_cast<int>(i)) != Z.members + Z.n)
					continue;
				alt.push_back(static_cast<int>(i));
			}
			const auto ha = harvest_groups_of(alt);
			c = std::max(cost0, harvest(ha, static_cast<float>(T), WORK_O) - harvest(ha, static_cast<float>(std::max(0, T - K0)), WORK_O));
		}
		zg_cost[zg_cur] = c;
		++zg_cur;
	}
	return true;
}
// The gate over the zones, then S, E and the block of the best one. Needs M.f_home and M.f_enemy (draft).
bool gate(int T, long reserve)
{
	B = Block{};
	B.T = T;
	B.nz = nz;
	B.K0 = std::min(T, 3);
	std::vector<int> safe;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
	{
		const auto& g = M.groups[i];
		if (g.access != ACC_WALK || mono(g) || g.d_home == UNREACH || g.d_enemy == UNREACH || valg(g) <= 0)
			continue;
		if (static_cast<int>(g.d_enemy) - static_cast<int>(g.d_home) > CONT_M)
			safe.push_back(static_cast<int>(i));
	}
	const auto hs = harvest_groups_of(safe);
	auto own = [&](int n) { return harvest(hs, static_cast<float>(std::max(0, n)), WORK_O); };
	float cost = own(T) - own(T - B.K0);
	if (!M.has_home || !M.has_enemy)
		return true;
	const FView fh = fview(M.f_home), fe = fview(M.f_enemy);
	const int s2s = zg_s2s; // Spawn-to-spawn walk, prepared by prepare_contest_zone_gate (also stored in draft memory byte 14).
	const float cost_safe = cost;
	float bcost = cost;
	int bz = -1, bmargin = 0;
	float bnet = -1e9f, bsw = 0;
	for (int z = 0; z < nz; ++z)
	{
		const Zone& Z = Zn[z];
		if (Z.radius < 0 || Z.n <= 0)
			continue;
		const int dA = fh(Z.hold), dB = fe(Z.hold);
		if (dA >= static_cast<int>(UNREACH) || dB >= static_cast<int>(UNREACH))
			continue;
		const int margin = dB - dA;
		if (margin < MARGIN_MIN || dA > REACH)
			continue;
		if (s2s < BIG && dA > s2s + ZG_REACH_S2S)
			continue; // A zone farther than the enemy spawn + ZG_REACH_S2S is skipped.
		cost = z < zg_cur ? zg_cost[z] : cost_safe; // Prepared per zone by prepare_contest_zone_gate.
		++B.ncand;
		std::vector<int> ms(Z.members, Z.members + Z.n);
		const float sw = 2.0f * CT_DS * harvest(harvest_groups_of(ms), static_cast<float>(B.K0), WORK_Z);
		const float net = sw - (1.0f + CT_RHO) * cost;
		if (net > bnet || (net == bnet && margin > bmargin))
		{
			bnet = net;
			bz = z;
			bmargin = margin;
			bsw = sw;
			bcost = cost;
		}
	}
	cost = bcost;
	if (bz < 0)
		return true;
	const Zone& Z = Zn[bz];
	ZoneB& zb = B.z;
	zb.hold = Z.hold;
	zb.R = Z.radius;
	zb.n = Z.n;
	for (int i = 0; i < Z.n; ++i)
		zb.members[i] = Z.members[i];
	zb.dA = fh(Z.hold);
	zb.dB = fe(Z.hold);
	zb.margin = zb.dB - zb.dA;
	zb.swing = bsw;
	zb.cost = cost;
	zb.orate = Z.orate;
	zb.cycle = Z.cycle;
	int best_d = BIG;
	for (int i = 0; i < Z.n; ++i)
	{
		const auto& g = M.groups[static_cast<std::size_t>(Z.members[i])];
		if (static_cast<int>(g.d_home) < best_d)
		{
			best_d = g.d_home;
			zb.entry = Z.members[i];
		}
	}
	// S and E: the tiles within R+3 of the hold (walk) that each spawn reaches first.
	distance_field hf;
	bitboard visited, root;
	bbset(root, Z.hold);
	hf.compute(M.block, root, visited, static_cast<std::uint16_t>(Z.radius + 4)); // bounded: only the ring matters
	const FView vh = fview(hf);
	const BView vb = bview(M.block), vc = bview(M.camp_tiles);
	const int ring = Z.radius + 3;
	int bs = BIG, be = BIG;
	zb.S = Z.hold;
	zb.E = Z.hold;
	for (int y = std::max(0, Z.hold.y - ring); y <= std::min(G.h - 1, Z.hold.y + ring); ++y)
	{
		if (fuel() < reserve + 3000)
			return false; // retried next draft turn
		for (int x = std::max(0, Z.hold.x - ring); x <= std::min(G.w - 1, Z.hold.x + ring); ++x)
		{
			const vec2 p{ x, y };
			if (vb(p) || vc(p) || vh(p) > ring)
				continue;
			const int a = fh(p), b = fe(p);
			if (a < bs || (a == bs && b > fe(zb.S)))
			{
				bs = a;
				zb.S = p;
			}
			if (b < be || (b == be && a > fh(zb.E)))
			{
				be = b;
				zb.E = p;
			}
		}
	}
	zb.dSH = vh(zb.S);
	zb.dHS = fh(zb.S);
	zb.valid = zb.entry >= 0 && bs < BIG;
	// The full send runs wherever contesting roughly pays: zone rate >= 0.25 gems a round and swing >= 0.85 x the own-side cost.
	B.gate = zb.valid && ((Z.orate >= 0.25f && bsw >= 0.85f * cost));
	// Contesting must be worth it: net > 0. No plan where the spawns are close (no first contest to win).
	B.gate = B.gate && bsw > (1.0f + CT_RHO) * cost && !(s2s < ZG_S2S_MIN);
	// Where the zone passes the swing gate the whole team goes to the first contest.
	B.Kf = (B.gate) ? T : ((B.gate && T >= 5 && zb.margin <= 4) ? std::min(T - 1, B.K0 + 1) : B.K0);
	B.Kmax = std::max(B.Kf, B.K0);
	B.ok = zb.valid;
	return true;
}

void write_u16_le(std::vector<std::uint8_t>& m, std::size_t o, int v)
{
	v = std::clamp(v, 0, 65535);
	m[o] = static_cast<std::uint8_t>(v & 255);
	m[o + 1] = static_cast<std::uint8_t>(v >> 8);
}

} // namespace

bool ready() { return stage >= 4; }
bool draft_step(long reserve, int T)
{
	if (stage >= 4)
		return true;
	if (!M.done() || static_cast<std::size_t>(M.ng) > 200 || static_cast<std::size_t>(M.na) > 40)
		return false;
	if (stage == 0)
	{
		if (fuel() < reserve + 20000)
			return false;
		features();
		fld.clear();
		fld.resize(C.size());
		stage = 1;
		cur = 0;
	}
	const std::size_t n = C.size();
	if (stage == 1)
	{
		// fc_seen: measured cost of one bounded field and its row (the first one is guessed high)
		while (cur < n)
		{
			const long fc = fc_seen > 0 ? fc_seen + 3000 : 1L * G.w * G.h + 6000;
			if (fuel() < reserve + fc + 6000)
				return false;
			const long f0 = fuel();
			auto f = std::make_unique<distance_field>();
			bitboard visited;
			f->compute(M.block, tiles_of(C[cur]), visited, static_cast<std::uint16_t>(ZONE_D));
			const FView v = fview(*f);
			dm[cur * n + cur] = 0;
			for (std::size_t b = 0; b < n; ++b)
			{
				if (b == cur)
					continue;
				int d = UNREACH;
				for (int ci : M.groups[static_cast<std::size_t>(C[b])].members)
					d = std::min<int>(d, v(M.camps[static_cast<std::size_t>(ci)].pos));
				if (d <= ZONE_D)
				{
					dm[cur * n + b] = std::min<std::uint8_t>(dm[cur * n + b], static_cast<std::uint8_t>(d));
					dm[b * n + cur] = std::min<std::uint8_t>(dm[b * n + cur], static_cast<std::uint8_t>(d));
				}
			}
			fld[cur] = std::move(f);
			++cur;
			fc_seen = std::max(fc_seen, f0 - fuel());
		}
		if (fuel() < reserve + 10000)
			return false;
		cluster();
		stage = 2;
		cur = 0;
	}
	if (stage == 2)
	{
		while (cur < static_cast<std::size_t>(nz))
		{
			if (fuel() < reserve + 15000 || !hold_walk(static_cast<int>(cur), reserve))
				return false;
			++cur;
		}
		fld.clear();
		stage = 3;
	}
	if (stage == 3)
	{
		if (!prepare_contest_zone_gate(T, reserve))
			return false; // Resumable over draft turns.
		if (fuel() < reserve + (fc_seen > 0 ? 2 * fc_seen : 3L * G.w * G.h) + 12000 || !gate(T, reserve))
			return false;
		stage = 4;
	}
	return true;
}
bool write_block(std::vector<std::uint8_t>& mem)
{
	if (!ready() || !B.ok)
		return false;
	if (mem.size() < BLOCK_END)
		mem.resize(BLOCK_END, 0);
	std::fill(mem.begin() + static_cast<std::ptrdiff_t>(BLOCK_AT), mem.begin() + static_cast<std::ptrdiff_t>(BLOCK_END), 0);
	const ZoneB& z = B.z;
	mem[BLOCK_AT] = BLOCK_MAGIC;
	mem[BLOCK_AT + 1] = BLOCK_VERSION;
	mem[BLOCK_AT + 2] = static_cast<std::uint8_t>((B.gate ? 1 : 0) | 4);
	mem[BLOCK_AT + 3] = static_cast<std::uint8_t>(B.T);
	mem[BLOCK_AT + 4] = static_cast<std::uint8_t>(B.K0);
	mem[BLOCK_AT + 5] = static_cast<std::uint8_t>(B.Kf);
	mem[BLOCK_AT + 6] = static_cast<std::uint8_t>(B.Kmax);
	std::size_t o = 840;
	mem[o + 0] = static_cast<std::uint8_t>(z.hold.x);
	mem[o + 1] = static_cast<std::uint8_t>(z.hold.y);
	mem[o + 2] = static_cast<std::uint8_t>(std::clamp(z.R, 0, 255));
	mem[o + 3] = static_cast<std::uint8_t>(z.S.x);
	mem[o + 4] = static_cast<std::uint8_t>(z.S.y);
	mem[o + 5] = static_cast<std::uint8_t>(z.E.x);
	mem[o + 6] = static_cast<std::uint8_t>(z.E.y);
	mem[o + 7] = static_cast<std::uint8_t>(z.entry);
	mem[o + 8] = 255; // zone altar: not used
	mem[o + 9] = static_cast<std::uint8_t>(std::clamp(z.dA, 0, 254));
	mem[o + 10] = static_cast<std::uint8_t>(std::clamp(z.dB, 0, 254));
	mem[o + 11] = static_cast<std::uint8_t>(std::clamp(z.margin + 128, 0, 255));
	write_u16_le(mem, o + 12, static_cast<int>(z.swing * 100.0f));
	write_u16_le(mem, o + 14, static_cast<int>(z.cost * 100.0f));
	write_u16_le(mem, o + 16, static_cast<int>(z.orate * 100.0f));
	mem[o + 18] = static_cast<std::uint8_t>(std::clamp(z.cycle, 0, 255));
	mem[o + 19] = static_cast<std::uint8_t>(z.n);
	for (int i = 0; i < MAXM; ++i)
		mem[o + 20 + static_cast<std::size_t>(i)] = i < z.n ? static_cast<std::uint8_t>(z.members[i]) : 255;
	mem[o + 32] = static_cast<std::uint8_t>(std::clamp(z.dSH, 0, 254));
	mem[o + 33] = static_cast<std::uint8_t>(std::clamp(z.dHS, 0, 254));
	unsigned sum = 0;
	for (std::size_t i = 840; i < BLOCK_END; ++i)
		sum += mem[i];
	mem[BLOCK_AT + 7] = static_cast<std::uint8_t>(sum & 255);
	return true;
}



} // namespace nova::zone
