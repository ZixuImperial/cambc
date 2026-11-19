// combat_state.cc: Combat tunables and the shared types and state of the fight modules.
#include "combat_internal.h"
namespace nova::combat {

// ======== Tunables: numbers more than one module reads; each module holds its own in `namespace tune` at its top ========
namespace tune_shared
{
inline constexpr int DPS_BODY = 10;                // PASS counts are x10: one body at full damage
}

// ======== Shared types and state: what more than one module reads ========
namespace {
constexpr std::uint32_t KIND_CHAMPION = 1, KIND_CAMP = 2;
// The camp groups one no-wake test weighs, each once.
struct NwGroups
{
	static constexpr int MAX = 6; // tunable: groups one test weighs
	std::array<int, MAX> gs{};
	int ng = 0;
	bool has(int g) const
	{
		bool dup = false;
		for (int i = 0; i < ng; ++i)
			dup |= gs[static_cast<std::size_t>(i)] == g;
		return dup;
	}
	bool full() const { return ng >= MAX; }
	void push(int g) { gs[static_cast<std::size_t>(ng++)] = g; }
	void add(int g) // past the cap a group drops
	{
		if (!has(g) && !full())
			push(g);
	}
};
} // namespace
namespace camps
{
bool wakes_other_group(vec2 c, int r, vec2 me_after, int skip_g, float kill_dmg);
} // namespace camps
namespace {
// Living visible camps of one group counted per tile within radius r (area spells and landings hit a square of radius r), over the
// group's bounding box. Built in O(camps x (2r+1)^2) instead of scanning tiles x camps. AreaGrid::best's no-wake test (PASSIVE
// Stellar) over a short list of the camps that can matter, with each group's wakes_other_group verdict kept per call; same answers as
// AreaGrid::wakes_other.
struct NwkList
{
	static constexpr int CAP = 32;
	int n = 0, ng = 0;
	std::array<vec2, CAP> p;
	std::array<std::uint8_t, CAP> kind;
	std::array<int, CAP> grp;
	std::array<int, CAP> gid;       // groups seen with a verdict slot
	std::array<std::int8_t, CAP> gv; // -1 unknown, 0 not bad, 1 bad
	// With 3+ waking camps (kind 2) listed, the tiles of the search rectangle within r of one are marked once
	// (a +1/-1 pair per row, then a prefix sum along each row), those camps leave the list, and wakes() reads the mark first.
	bool bm_on = false;
	int bm_x0 = 0, bm_y0 = 0, bm_w = 0;
	std::array<std::uint8_t, 40 * 40> bm;
	void board(int ax, int ay, int bx, int by, int r)
	{
		int k2 = 0;
		for (int i = 0; i < n; ++i)
			k2 += kind[static_cast<std::size_t>(i)] == 2;
		const int w = bx - ax + 1, h = by - ay + 1;
		if (k2 < 3 || w <= 0 || h <= 0 || w > 40 || h > 40)
			return;
		std::array<std::int16_t, 40 * 41> d;
		const int ws = w + 1;
		std::fill(d.begin(), d.begin() + ws * h, static_cast<std::int16_t>(0));
		int m = 0;
		for (int i = 0; i < n; ++i)
		{
			const std::size_t si = static_cast<std::size_t>(i);
			if (kind[si] != 2)
			{
				const std::size_t sm = static_cast<std::size_t>(m++);
				p[sm] = p[si];
				kind[sm] = kind[si];
				grp[sm] = grp[si];
				continue;
			}
			const int xa = std::max(0, p[si].x - r - ax), xb = std::min(w - 1, p[si].x + r - ax);
			const int ya = std::max(0, p[si].y - r - ay), yb = std::min(h - 1, p[si].y + r - ay);
			if (xa > xb)
				continue;
			for (int y = ya; y <= yb; ++y)
			{
				++d[static_cast<std::size_t>(y * ws + xa)];
				--d[static_cast<std::size_t>(y * ws + xb + 1)];
			}
		}
		for (int y = 0; y < h; ++y)
		{
			int run = 0;
			for (int x = 0; x < w; ++x)
			{
				run += d[static_cast<std::size_t>(y * ws + x)];
				bm[static_cast<std::size_t>(y * w + x)] = static_cast<std::uint8_t>(run > 0);
			}
		}
		n = m;
		bm_on = true;
		bm_x0 = ax;
		bm_y0 = ay;
		bm_w = w;
	}
	bool nwu = false; // read once per call
	bool build(int ax, int ay, int bx, int by, int r, int gi)
	{
		nwu = true;
		for (const auto& vc : W.camps)
		{
			if (vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
				continue;
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group == gi || cp.pos.x < ax - r || cp.pos.x > bx + r || cp.pos.y < ay - r || cp.pos.y > by + r)
				continue;
			const bool gok = cp.group >= 0 && cp.group < M.ng && M.groups[static_cast<std::size_t>(cp.group)].n_att > 0;
			int kd;
			if (!vc.awake && cp.attacks())
				kd = 2;
			else if (!gok)
				continue;
			else
				kd = vc.awake ? 0 : 1;
			if (kd == 1 && nwu && gsleep(cp.group) == 2)
				kd = 2; // damage wakes the whole group, and an unseen member of it is a sleeping attacker
			if (n >= CAP)
				return false; // a crowded view: the plain per-tile test
			p[static_cast<std::size_t>(n)] = cp.pos;
			kind[static_cast<std::size_t>(n)] = static_cast<std::uint8_t>(kd);
			grp[static_cast<std::size_t>(n++)] = cp.group;
		}
		if (nwu) // camps out of sight now, from the static map and the last-known state
		{
			const int qx0 = ax - r, qx1 = bx + r, qy0 = ay - r, qy1 = by + r;
			// Only the groups whose box (mapinfo step_groups_t) meets the window; every camp in M.camps is a member
			// of exactly one built group, so these are the same camps as a loop over M.camps
			{
				for (int g = 0; g < M.ng; ++g)
				{
					const GroupI& bb = M.groups[static_cast<std::size_t>(g)];
					if (g == gi || bb.bx1 < qx0 || bb.bx0 > qx1 || bb.by1 < qy0 || bb.by0 > qy1)
						continue;
					for (const int ci : M.groups[static_cast<std::size_t>(g)].members)
					{
						const auto& cp = M.camps[static_cast<std::size_t>(ci)];
						if (cp.pos.x < qx0 || cp.pos.x > qx1 || cp.pos.y < qy0 || cp.pos.y > qy1 || vis_k(ci) >= 0)
							continue;
						if (econ::camp_known_dead(ci) || mv::awake_known(ci))
							continue;
						int kd = -1;
						if (cp.attacks())
							kd = gsleep(cp.group) == 0 && cp.group >= 0 && cp.group < M.ng ? -1 : 2; // a sleeping attacker unless its group is awake
						else if (cp.group >= 0 && cp.group < M.ng && M.groups[static_cast<std::size_t>(cp.group)].n_att > 0 && gsleep(cp.group) > 0)
							kd = 2; // the group's sleeping attackers wake with it
						if (kd < 0)
							continue;
						if (n >= CAP)
							return false;
						p[static_cast<std::size_t>(n)] = cp.pos;
						kind[static_cast<std::size_t>(n)] = static_cast<std::uint8_t>(kd);
						grp[static_cast<std::size_t>(n++)] = cp.group;
					}
				}
			}
		}
		return true;
	}
	// W.camps position of visible camp ci, or -1
	static int vis_k(int ci)
	{
		if (ci < 0 || static_cast<std::size_t>(ci) >= W.camp_slot.size())
			return -1;
		const int k = W.camp_slot[static_cast<std::size_t>(ci)];
		return (k >= 0 && static_cast<std::size_t>(k) < W.camps.size() && W.camps[static_cast<std::size_t>(k)].ci == ci) ? k : -1;
	}
	// group g's sleep state: 0 awake (a member seen or remembered awake) or no living sleeping attacker known, 1 sleeping
	// attackers all in sight (wakes_other_group's case), 2 a living sleeping attacker out of sight. Kept per call.
	std::array<int, 16> sgid;
	std::array<std::int8_t, 16> sgv;
	int nsg = 0;
	int gsleep(int g)
	{
		if (g < 0 || g >= M.ng)
			return 0;
		for (int i = 0; i < nsg; ++i)
			if (sgid[static_cast<std::size_t>(i)] == g)
				return sgv[static_cast<std::size_t>(i)];
		int st = 0;
		bool awake = false;
		for (const int m : M.groups[static_cast<std::size_t>(g)].members)
		{
			const int k = vis_k(m);
			if (k >= 0 ? W.camps[static_cast<std::size_t>(k)].awake : mv::awake_known(m))
			{
				awake = true;
				break;
			}
			if (!M.camps[static_cast<std::size_t>(m)].attacks())
				continue;
			if (k >= 0)
				st = std::max(st, 1);
			else if (!econ::camp_known_dead(m))
				st = 2;
		}
		if (awake)
			st = 0;
		if (nsg < 16)
		{
			sgid[static_cast<std::size_t>(nsg)] = g;
			sgv[static_cast<std::size_t>(nsg++)] = static_cast<std::int8_t>(st);
		}
		return st;
	}
	int slot(int g)
	{
		for (int i = 0; i < ng; ++i)
			if (gid[static_cast<std::size_t>(i)] == g)
				return i;
		gid[static_cast<std::size_t>(ng)] = g;
		gv[static_cast<std::size_t>(ng)] = -1;
		return ng++;
	}
	bool wakes(vec2 t, int r, int gi)
	{
		std::array<int, 7> gs; // distinct groups within r (kind 0 and 1), at most 7 kept
		std::array<std::uint8_t, 7> gk{};
		int m = 0;
		if (bm_on && bm[static_cast<std::size_t>((t.y - bm_y0) * bm_w + (t.x - bm_x0))])
			return true; // a waking camp within r
		for (int i = 0; i < n; ++i)
		{
			if (cheb(p[static_cast<std::size_t>(i)], t) > r)
				continue;
			const int kd = kind[static_cast<std::size_t>(i)];
			if (kd == 2)
				return true; // wakes_other's first part
			const int g = grp[static_cast<std::size_t>(i)];
			int j = 0;
			while (j < m && gs[static_cast<std::size_t>(j)] != g)
				++j;
			if (j == m)
			{
				if (m >= 7)
					continue;
				gs[static_cast<std::size_t>(m++)] = g;
			}
			gk[static_cast<std::size_t>(j)] |= static_cast<std::uint8_t>(kd);
		}
		bool any1 = false;
		for (int j = 0; j < m; ++j)
			any1 |= gk[static_cast<std::size_t>(j)] != 0;
		if (!any1)
			return false; // only awake groups near t: wakes_other_group is false
		if (m >= 7)
			return camps::wakes_other_group(t, r, W.me.pos, gi, 0.0f); // past wakes_other_group's six-group cap: its own answer
		int unk = 0, last = -1;
		for (int j = 0; j < m; ++j)
		{
			if (!gk[static_cast<std::size_t>(j)])
				continue;
			const int s = slot(gs[static_cast<std::size_t>(j)]);
			const int v = gv[static_cast<std::size_t>(s)];
			if (v == 1)
				return true;
			if (v < 0)
			{
				++unk;
				last = s;
			}
		}
		if (!unk)
			return false;
		const bool b = camps::wakes_other_group(t, r, W.me.pos, gi, 0.0f);
		for (int j = 0; j < m; ++j)
			if (gk[static_cast<std::size_t>(j)])
			{
				const int s = slot(gs[static_cast<std::size_t>(j)]);
				if (!b)
					gv[static_cast<std::size_t>(s)] = 0;
			}
		if (b && unk == 1)
			gv[static_cast<std::size_t>(last)] = 1;
		return b;
	}
};
struct AreaGrid
{
	static constexpr int N = 40;
	int x0 = 0, y0 = 0, w = 0, h = 0, any = 0;
	std::array<std::uint8_t, N * N> c; // FB5 ARG1: zeroed only with the bit off (build writes the window before best reads it)
	AreaGrid()
	{
	}
	void build(int gi, int r)
	{
		int minx = BIG, miny = BIG, maxx = -BIG, maxy = -BIG;
		any = 0;
		for (const auto& vc : W.camps)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group != gi)
				continue;
			minx = std::min(minx, cp.pos.x);
			miny = std::min(miny, cp.pos.y);
			maxx = std::max(maxx, cp.pos.x);
			maxy = std::max(maxy, cp.pos.y);
			++any;
		}
		if (!any)
			return;
		x0 = minx - r;
		y0 = miny - r;
		w = std::min(N, maxx + r - x0 + 1);
		h = std::min(N, maxy + r - y0 + 1);
		{
			// Each camp adds 1 on rows ya..yb, columns xa..xb (its radius-r square clipped to the window);
			// a +1 / -1 pair per row, then a prefix sum along each row. Counts wrap mod 256.
			static std::array<std::int16_t, N * (N + 1)> d;
			const int ws = w + 1;
			std::fill(d.begin(), d.begin() + ws * h, static_cast<std::int16_t>(0));
			for (const auto& vc : W.camps)
			{
				const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
				if (cp.group != gi)
					continue;
				const int xa = std::max(0, cp.pos.x - r - x0), xb = std::min(w - 1, cp.pos.x + r - x0);
				const int ya = std::max(0, cp.pos.y - r - y0), yb = std::min(h - 1, cp.pos.y + r - y0);
				if (xa > xb)
					continue;
				for (int y = ya; y <= yb; ++y)
				{
					++d[static_cast<std::size_t>(y * ws + xa)];
					--d[static_cast<std::size_t>(y * ws + xb + 1)];
				}
			}
			for (int y = 0; y < h; ++y)
			{
				int run = 0;
				for (int x = 0; x < w; ++x)
				{
					run += d[static_cast<std::size_t>(y * ws + x)];
					c[static_cast<std::size_t>(y * w + x)] = static_cast<std::uint8_t>(run);
				}
			}
			return;
		}
		std::fill(c.begin(), c.begin() + w * h, 0);
		for (const auto& vc : W.camps)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group != gi)
				continue;
			for (int dy = -r; dy <= r; ++dy)
				for (int dx = -r; dx <= r; ++dx)
				{
					const int x = cp.pos.x + dx - x0, y = cp.pos.y + dy - y0;
					if (x >= 0 && y >= 0 && x < w && y < h)
						++c[static_cast<std::size_t>(y * w + x)];
				}
		}
	}
	// Best tile within `reach` of `from` (landing: a free tile other than `from`); *n receives its count.
	// PASSIVE Stellar: with no_wake_gi >= 0, tiles whose radius-r square holds a sleeping attacker of another group
	// are skipped (damage wakes a whole group).
	vec2 best(vec2 from, int reach, bool landing, int* n, int no_wake_gi = -1, int r = 0) const
	{
		vec2 out{ -1, -1 };
		*n = 0;
		if (!any)
			return out;
		const int ax = std::max(x0, from.x - reach), bx = std::min(x0 + w - 1, from.x + reach);
		const int ay = std::max(y0, from.y - reach), by = std::min(y0 + h - 1, from.y + reach);
		// The camps that can wake within r of the rectangle (kind 2 a sleeping attacker: the answer is true;
		// 1 a sleeping camp of a group with attackers: wakes_other_group decides; 0 an awake camp of such a group: counted toward wakes_other_group's
		// six-group cap only). A group's wakes_other_group verdict does not depend on t (me_after = my tile, kill_dmg 0), so it is kept
		// per group for this call.
		NwkList nk;
		const bool nkf = no_wake_gi >= 0 && ax <= bx && ay <= by && nk.build(ax, ay, bx, by, r, no_wake_gi);
		if (nkf && nk.nwu && r >= 0)
			nk.board(ax, ay, bx, by, r);
		for (int y = ay; y <= by; ++y)
			for (int x = ax; x <= bx; ++x)
			{
				const int v = c[static_cast<std::size_t>((y - y0) * w + (x - x0))];
				if (v <= *n)
					continue;
				const vec2 t{ x, y };
				if (!inb(t) || (landing && (t == from || !mv::free_tile(t))))
					continue;
				if (no_wake_gi >= 0 && (nkf ? nk.wakes(t, r, no_wake_gi) : wakes_other(t, r, no_wake_gi)))
					continue;
				*n = v;
				out = t;
			}
		return out;
	}
	// A living, sleeping attacker of a group other than gi within r of t (visible camps).
	static bool wakes_other(vec2 t, int r, int gi)
	{
		if (r >= 0 && r <= 3 && !M.camp_at.empty()) // the same test over the (2r+1)^2 tiles
		{
			for (int y = t.y - r; y <= t.y + r; ++y)
				for (int x = t.x - r; x <= t.x + r; ++x)
				{
					const int ci = M.camp_index(vec2{ x, y });
					if (ci < 0 || static_cast<std::size_t>(ci) >= W.camp_slot.size() || static_cast<std::size_t>(ci) >= static_cast<std::size_t>(M.nc))
						continue;
					const int k = W.camp_slot[static_cast<std::size_t>(ci)];
					if (k < 0 || static_cast<std::size_t>(k) >= W.camps.size() || W.camps[static_cast<std::size_t>(k)].ci != ci)
						continue;
					const auto& cp = M.camps[static_cast<std::size_t>(ci)];
					if (cp.group != gi && !W.camps[static_cast<std::size_t>(k)].awake && cp.attacks())
						return true;
				}
			return static_cast<bool>(camps::wakes_other_group(t, r, W.me.pos, gi, 0.0f));
		}
		for (const auto& vc : W.camps)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group != gi && !vc.awake && cp.attacks() && cheb(cp.pos, t) <= r)
				return true;
		}
		return static_cast<bool>(camps::wakes_other_group(t, r, W.me.pos, gi, 0.0f)); // a cluster of a sleeping attacker group wakes it too
	}
};
// Enemies seen recently (positions persist a few rounds after they leave vision, e.g. into a bush).
struct Seen
{
	std::uint32_t h = 0;
	int round = -1000;
	Foe foe;
	bool rec = false; // it was channelling a recall at this sighting
};
std::vector<Seen> seen;
// Runtime data flag DPS_TAB, 0 = no work. bit 1 STEPS: the basic part counts only the turns left after closing to the nearest
// opposing body (d - range, capped at the horizon; no visible opposing body: unchanged). bit 2 VALUE: the kit (fight-value) factor
// exp(.25 kit_fight_value) only on fight-value calls (horizon_dps: who wins); damage calls (horizon_dps1: team focus, ttk) drop it
// (x1.43 on Heart of Ruin). bit 4 TARGETS: the 1.3 multi-target factor only when a second opposing body stands within 2 of the
// nearest one. bit 8 RAW: the damage part from the rules: a basic Str a turn, each slot on its own cooldown (ready now, or cd k
// fires at turn k; the 8-turn cooldown puts a second cast past the horizon), one cast a turn (a tie moves the smaller cast a turn
// on), reset = one extra basic; bits 1/4 apply on top (a spell waits until its own reach). FSPLIT: a body near the focus puts only
// part of what it deals on that one target. bit 16 OURS: the single-target team sums (team_dps_on, the hd race tdps) weight me by
// DPS_FS_ME and a mate by DPS_FS_M1 (d1 to the target) / DPS_FS_M2 (d2+). bit 32 FOES: the hd race's incoming damage weights each
// foe's dps by its share on me, DPS_FS_F1..F6 by d(foe, me) (6 = 6+). Shares x100: me .80, mates .60/.55; foes .72 .65 .60 .53 .45
// .34.
inline constexpr int DPS_TAB[12] = { 0x44505331, DPS_BITS, DPS_FS_ME, DPS_FS_M1, DPS_FS_M2, DPS_FS_F1, DPS_FS_F2, DPS_FS_F3,
	DPS_FS_F4, DPS_FS_F5, DPS_FS_F6, 0x31535044 };
struct DpsPass
{
	int ns = 0, na = tune_shared::DPS_BODY, nd = tune_shared::DPS_BODY, nr = 0;
	bool kill = false, tdur = false;
	float inc = 0.0f;
	int pack() const { return ns | (na << 7) | (nd << 14) | (nr << 21) | (kill ? 1 << 25 : 0) | (tdur ? 1 << 26 : 0); }
};
// THE kill check. kill_dmg(f, d, mode): the most I deal f this turn from my tile (d = the real distance; KQ_DASH: the distance from
// the dash's landing), one cast (OCB rule), x passive_mult. kills(f, d, mode): eff_hp(f) <= that; mode 0 adds
// kill_now's reach, the dash landing test and KRS's spell-alone kill, so no caller can forget them. Callers test KQ_ON first
// (KQ_SITE); with KQ_BITS 0 none of this runs.
enum : unsigned
{
	KQ_RAW = 1u, // my_burst alone: no reach, landing or KRS (react / kite compares)
	KQ_BASIC = 2u, // my basic hit alone, d <= range, with the attack allowance (GameRules.md:99-101)
	KQ_STEP = 4u, // my basic hit alone at d <= range + 1 (kill_needs_dash's 'a basic alone kills', no allowance test)
	KQ_DASH = 8u, // the dash is the turn's one cast: one basic hit from the landing + the dash's own damage within its radius
};
#define KQ_SITE(B, NEW, OLD) (KQ_ON(B) ? (NEW) : (OLD)) // the diag copy records where the two answers differ
} // namespace
vec2 lb_tile{ -1, -1 };      // the non-lethal tile it found
vec2 lb_step{ -1, -1 };      // the step after the dash to lb_tile; set only with the bit
namespace {
} // namespace
bool bh57_noreset = false; // set only with the bit on, around a hit that must leave the cast for a dash
// this body's locked target
vec2 hd_lock_pos{ -1, -1 };
// my focus this round (assess fills it, flag on only), the share, the nearest visible foe, and the scaling of one body's damage.
namespace {
constexpr std::uint32_t RAW_LOCK = 2; // engine consumable id of the altar lock
} // namespace
std::array<int, 8> ft_seen{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
std::array<int, 8> peel_seen{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
std::array<int, 8> peel_hit{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
std::array<int, 8> ct_back{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 }; // round a foe within that mate's range lost HP
struct CtHp
{
	std::uint32_t h = 0;
	float hp = 0;
	int round = -1000;
	int mate_hit = -1000; // round its HP + shield fell (since my last sighting) with an ally within 2 of it
};
std::vector<CtHp> ct_hp; // last seen enemy HP + shield
vec2 bkc_pos{ -1, -1 };
// a remembered foe (seen, out of my sight this turn) would keep the foe_of numbers of its last sighting, so a dash or nuke on
// cooldown stayed 'on cooldown' for the 8 rounds of memory. Its cooldown-derived numbers (reach, burst, dps) are recomputed from the
// remembered Body with the estimated cooldowns; position, health and bag stay those of the sighting. Recomputed on change only: per
// handle (direct-mapped), the sighting round, tile, health and estimated cooldowns it last used.
struct CdmRk
{
	std::uint32_t h = 0;
	int round = -1000, x = -1, y = -1, cd0 = -2, cd1 = -2;
	float hp = -1.0f;
};
bool sf_hf[4] = { false, false, false, false };
int sf_latched = -1;
namespace {
// What the fight logic remembers between turns.
struct TurnMemory
{
	float hp_lost_at_dmg_round = 0.0f; // health + shield lost at dmg_round
	int retreat_until = -1; // committed retreat: keep away from retreat_from until this round
	int last_flee_round = -1000;
	int last_fight_round = -1000;
	std::vector<mv::Threat> retreat_from;
	int help_round = -1000; // assess held a fight on the strength of idle mates (brain posts HELP)
};
TurnMemory turn_memory;
// The lethal spot assess() found this round.
struct LethalSpot
{
	int round = -1;       // the round assess() turned a lethal spot into a FLEE
	bool by_dash = false; // reached by my dash (no walk tile was safe)
};
LethalSpot lethal_spot;
// The hold decision (hunt_leash_assess, heart_dash_try): the locked foe and this turn's memo.
struct HoldState
{
	int lock_handle = -1, lock_seen = -99, active_round = -99;
	std::array<float, 8> memo;
	int memo_round = -99;
};
static HoldState hold_state;
// The focus share read this round.
struct FocusShare
{
	int focus_handle = -1, round = -99;
};
static FocusShare focus_share;
} // namespace
// foes12 = enemy champions visible or seen <= 4 rounds ago (not visible now) within EF_FOE_R of me;
// near5 / burst5 = the assessed foes within 5 and their summed one-turn bursts; allies4 = visible allies within 4.
struct EfCounts
{
	int foes12 = 0, near5 = 0, allies4 = 0;
	int fade5 = 0; // foes12 in fifths: a sighting 5, a memory 5 - age, so the bar does not jump when a memory expires
	float burst5 = 0;
};
vec2 pra_walk_to{ -1, -1 };
// no known enemy champion can reach my spell range (4) within two rounds.
static std::vector<std::pair<std::uint32_t, bool>> b971_dash; // enemy handle -> its kit dashes (learnt when seen)
} // namespace nova::combat
