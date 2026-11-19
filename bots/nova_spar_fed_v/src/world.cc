// world.cc: Per-turn perception snapshot shared by brain, econ, combat and move.
#include "world.h"
#include "multipliers.h"

#include "mapinfo.h"
#include "plan.h"
#include "champions.h"

namespace nova {

World W;

namespace {
struct Handle
{
	std::uint32_t h;
	cambc::champion_type type;
	int slot;
};
std::vector<Handle> ally_h, enemy_h;
std::array<int, 16> cr_last{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 }; // last round each enemy was seen recalling
std::array<int, 16> cr_left{}; // the recall time left I saw then
std::array<bool, 16> cr_real{}; // and my verdict then
std::array<int, 16> rc9_al_last{}; // RC9 bit 16: last round I saw each ally slot in a recall channel
std::array<int, 16> rc9_al_left{}; // RC9 bit 16: the recall time left I read then
std::array<bool, 16> rc9_al_real{}; // RC9 bit 16: its timer fell between two of my turns in a row
std::uint32_t my_h = 0;
// per enemy roster index, the recall streak I am watching and the aborts counted.
std::array<int, 16> sr_r0{}; // round its current recall streak was first seen (0 = none)
std::array<int, 16> sr_l0{};   // the timer then (-1 = unknown)
std::array<int, 16> sr_rl{};   // last round seen recalling
std::array<float, 16> sr_hp{}; // HP at the streak start
std::array<vec2, 16> sr_pos{}; // tile at the streak start
std::array<int, 16> sr_n{};    // recalls it aborted with no damage

// rec = the engine's recall bit (before the real-channel check), left = its timer (-1 unknown). Clears b's recall bit for a known
// spinner unless the timer reads 0.
__attribute__((noinline)) void track_spinner_recall_bit(std::size_t i, Body& b, bool rec, int left)
{
	if (i >= sr_n.size())
		return;
	if (rec)
	{
		const bool live = sr_r0[i] > 0 && sr_rl[i] >= W.round - 3;
		if (!live)
		{
			sr_r0[i] = W.round;
			sr_l0[i] = left;
			sr_hp[i] = b.hp;
			sr_pos[i] = b.pos;
		}
		else if (left >= 0 && sr_l0[i] >= 0 && left > sr_l0[i] - std::max(0, W.round - sr_r0[i] - 1))
		{
			// restarted since the streak began (the timer falls by >= 1 per foe turn end, and it had >= rounds - 1 of them)
			if (b.hp >= sr_hp[i] - 0.5f)
				++sr_n[i];
			sr_r0[i] = W.round;
			sr_l0[i] = left;
			sr_hp[i] = b.hp;
			sr_pos[i] = b.pos;
		}
		sr_rl[i] = W.round;
		if (sr_n[i] >= SR_MIN && left != 0)
			b.state &= ~ST_RECALL;
	}
	else if (sr_r0[i] > 0)
	{
		// not recalling now, near where it recalled, no damage taken: it cancelled (a teleport puts it on its spawn)
		if (sr_rl[i] >= W.round - 2 && b.hp >= sr_hp[i] - 0.5f && cheb(b.pos, sr_pos[i]) <= 2)
			++sr_n[i];
		sr_r0[i] = 0;
	}
}

bool read_body(std::uint32_t h, Body& b)
{
	cambc::detail::champion_info ci{};
	if (cambc::detail::sdk_champion(h, &ci) != 0)
		return false;
	if (ci.x < 0 || ci.y < 0)
		return false;
	b.h = h;
	b.pos = { ci.x, ci.y };
	b.hp = ci.health;
	b.maxhp = ci.max_health > 0 ? ci.max_health : 1.0f;
	b.str = ci.strength;
	b.foc = ci.focus;
	b.range = ci.attack_range;
	b.state = static_cast<std::uint32_t>(ci.state);
	b.type = static_cast<cambc::champion_type>(ci.type);
	return (b.state & ST_ALIVE) != 0;
}

// The same read in two parts, so a body out of sight costs no Body and a live one no copy. True: ci is a living body. An engine read
// that returns 0 writes the whole struct, and ci is not read otherwise: no zero fill.
NOVA_INLINE bool read_ci(std::uint32_t h, cambc::detail::champion_info& ci)
{
	if (cambc::detail::sdk_champion(h, &ci) != 0)
		return false;
	if (ci.x < 0 || ci.y < 0)
		return false;
	return (static_cast<std::uint32_t>(ci.state) & ST_ALIVE) != 0;
}
NOVA_INLINE void fill_body_from_champion_info(Body& b, std::uint32_t h, const cambc::detail::champion_info& ci)
{
	b.h = h;
	b.pos = { ci.x, ci.y };
	b.hp = ci.health;
	b.maxhp = ci.max_health > 0 ? ci.max_health : 1.0f;
	b.str = ci.strength;
	b.foc = ci.focus;
	b.range = ci.attack_range;
	b.state = static_cast<std::uint32_t>(ci.state);
	b.type = static_cast<cambc::champion_type>(ci.type);
}
// F3: kit_of's result per type (kit_of is a cross-file call with its own checks; its cache never moves).
NOVA_INLINE const Kit* kit_fast(cambc::champion_type t)
{
	static std::array<const Kit*, 13> tab{};
	const auto i = static_cast<std::size_t>(t);
	if (i >= tab.size())
		return &kit_of(t);
	const Kit*& k = tab[i];
	if (!k)
		k = &kit_of(t);
	return k;
}

void read_buffs(Body& b)
{
	std::array<cambc::detail::buff_data, 3> raw{};
	std::uint32_t count = 0;
	if (cambc::detail::sdk_champion_buff_data(b.h, raw.data(), static_cast<std::uint32_t>(raw.size()), &count) != 0)
		return;
	for (std::uint32_t i = 0; i < count && i < raw.size(); ++i)
	{
		if (raw[i].type == 0)
		{
			b.shield += raw[i].data.shield.value;
			b.shield_turns = std::max(b.shield_turns, static_cast<int>(raw[i].data.shield.duration));
		}
		else if (raw[i].type == 1)
		{
			if (raw[i].data.stun.duration > 0) // a stun buff counts only while its duration is > 0
				b.stunned = true;
		}
	}
}
} // namespace


bool enemy_starts(int round)
{
	static int we_a = -1; // the rosters are fixed after world_init: decided once (fuel: camp ties ask per camp and body)
	if (we_a < 0 && !ally_h.empty() && !enemy_h.empty())
	{
		std::uint32_t ma = 0xffffffffu, me = 0xffffffffu;
		for (const auto& a : ally_h)
			ma = std::min(ma, a.h);
		for (const auto& e : enemy_h)
			me = std::min(me, e.h);
		we_a = ma < me ? 1 : 0;
	}
	const bool a_starts = (round & 1) != 0;
	return (we_a == 1) != a_starts;
}
// CDM bits 2/4: per foe handle, the last engine-read cooldown of each slot, the round of that read and the last Body.
namespace cdm
{
struct Ent
{
	std::uint32_t h = 0;
	std::array<int, 2> cd{ -1, -1 }, rr{ -1000, -1000 };
	int br = -1000; // round of b
	bool dead = false; // bit 32 VKE: dead at my last look (alive state is readable out of vision)
	Body b;
};
static std::array<Ent, 12> tab{};
static int ntab = 0;
static Ent* find(std::uint32_t h)
{
	for (int i = 0; i < ntab; ++i)
		if (tab[static_cast<std::size_t>(i)].h == h)
			return &tab[static_cast<std::size_t>(i)];
	return nullptr;
}
// Slot s of t at my turn in round now. Its turn ends since my read at round r: dr - 1 rounds between, plus one if it acted after me
// at r, plus one if it acts before me now, so at most dr + 1 whatever the priorities (they change in escapes). Counted at that
// bound, the estimate is never later than the engine (dr + (dr & 1) assumes stable priorities and reads 1 high on some re-reads); a
// cast while unseen only makes the real cooldown longer. Vendetta: a kill out of sight resets both slots, so unknown (ready).
static int est(const Ent& t, int s, int now)
{
	const auto us = static_cast<std::size_t>(s);
	if (t.cd[us] < 0)
		return -1;
	if (vendetta_layer::intel_cd_reset(t.b) && t.rr[us] < now)
		return -1; // a Vendetta out of sight (VKE: while one of us died): a kill may have reset both slots
	const int dr = now - t.rr[us];
	return std::max(0, t.cd[us] - (dr + 1));
}
// Diagnostic (probe copies only): where b's slot s cooldown came from this turn: 0 unknown (-1), 1 the engine's read, 2 CDM's
// estimate (MEM+USE, or a ghost's remembered Body).
int src(const Body& b, int s)
{
	if (b.cd[static_cast<std::size_t>(s)] < 0)
		return 0;
	const Ent* t = find(b.h);
	return (!t || t->rr[static_cast<std::size_t>(s)] == W.round) ? 1 : 2;
}
} // namespace cdm
void world_init()
{
	ally_h.clear();
	enemy_h.clear();
	my_h = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	for (int i = 0; i < P.n; ++i)
		ally_h.push_back({ P.handle[static_cast<std::size_t>(i)], P.type[static_cast<std::size_t>(i)], i });
	for (const auto& c : roster(team::enemy))
		enemy_h.push_back({ c.h, c.type, -1 });
	W.me.h = my_h;
	W.me.ally = true;
	W.me.slot = P.my_slot;
	W.me.type = P.my_slot >= 0 ? P.type[static_cast<std::size_t>(P.my_slot)] : cambc::self().champion_name();
	W.me.kit = &kit_of(W.me.type);
}
void refresh_self()
{
	cambc::detail::champion_info ci; // fills W.me in place (a copy in and out would keep every field the read does not set)
	if (read_ci(my_h, ci))
	{
		fill_body_from_champion_info(W.me, my_h, ci);
		W.me.ally = true;
		if (sps_pending && (W.me.state & ST_RECALL) && !(W.me.state & (ST_TRIBUTE | ST_TELEPORT)))
			W.me.state = (W.me.state & ~ST_RECALL) | ST_CAN_MOVE | ST_CAN_ATTACK | ST_CAN_CAST; // as after the cancel
	}
}
void reread_units()
{
	static bitboard ru_foes{ cambc::uninitialized };
	nchk(cambc::detail::sdk_ally_occupancy(W.occ_units.ptr()));
	nchk(cambc::detail::sdk_enemy_occupancy(ru_foes.ptr()));
	bb3_or(W.occ_units, ru_foes, W.occ_units);
}
bool foe_read_at(vec2 p)
{
	for (const auto& e : enemy_h)
	{
		cambc::detail::champion_info ci;
		if (read_ci(e.h, ci) && ci.x == p.x && ci.y == p.y)
			return true;
	}
	return false;
}
// BSF bit 2: the living foe the engine shows me on tile p (a refused step revealed it), as a Body.
bool foe_body_at(vec2 p, Body& b)
{
	for (const auto& e : enemy_h)
	{
		cambc::detail::champion_info ci;
		if (read_ci(e.h, ci) && ci.x == p.x && ci.y == p.y && read_body(e.h, b))
		{
			b.ally = false;
			b.kit = &kit_of(b.type);
			return true;
		}
	}
	return false;
}

// The tributed totals of both teams (perceive; BH67 bit 2 also on dead turns).
NOVA_INLINE void read_tributes()
{
	std::uint32_t t = 0;
	if (cambc::detail::sdk_bc_submitted_gems(cambc::detail::absolute_team(team::ally), &t) == 0)
		W.tributed_us = static_cast<int>(t);
	if (cambc::detail::sdk_bc_submitted_gems(cambc::detail::absolute_team(team::enemy), &t) == 0)
		W.tributed_them = static_cast<int>(t);
}
// Clear the per-turn lists and camp slots, and read the gold.
static __attribute__((always_inline)) inline void reset_turn_lists()
{
	++fg::pstamp; // W's bodies, camps and vision change here only
	W.round = static_cast<int>(round_number_nc());
	W.moved = W.attacked = W.cast = W.no_move = false;
	std::int32_t alive = 0;
	cambc::detail::sdk_champion_is_alive(my_h, &alive);
	W.alive = alive != 0;
	W.enemies.clear();
	W.enemies_far.clear(); // clear the far-enemy list (ward-seen enemies are re-added below)
	W.allies.clear();
	{
		// The same reset with the slot table's size and data read once (stores do not reload them).
		const std::size_t ns = W.camp_slot.size();
		auto* const sl = W.camp_slot.data();
		for (const auto& c : W.camps) // WARD: O(1) camp_by_index
			if (static_cast<std::size_t>(c.ci) < ns)
				sl[static_cast<std::size_t>(c.ci)] = -1;
	}
	W.camps.clear();
	if (W.camp_slot.size() != static_cast<std::size_t>(M.nc))
		W.camp_slot.assign(static_cast<std::size_t>(M.nc), -1);
	std::uint32_t gold = 0;
	cambc::detail::sdk_champion_gold(my_h, &gold);
	W.gold = gold;
}

// A dead champion still sees through its ward: note the enemies there for team intel, and the gems.
static __attribute__((always_inline)) inline void read_dead_turn()
{
		// WARD: a dead champion still sees through its ward: note the enemies there for team intel.
		for (const auto& e : enemy_h)
		{
			Body b;
			if (!read_body(e.h, b))
				continue;
			b.ally = false;
			b.kit = &kit_of(b.type);
			(W.enemies_far).push_back(b);
		}
		std::uint32_t g = 0;
		W.me.gems = cambc::detail::sdk_champion_gems(my_h, &g) == 0 ? g : 0u;
		read_tributes();
}

// The champion's own position, buffs, gems, cooldowns and spawn flag.
static __attribute__((always_inline)) inline void read_own_state()
{
	refresh_self();
	// My own shield counts for damage tracking (damage a shield absorbs still cancels a recall).
	W.me.shield = 0;
	W.me.shield_turns = 0;
	W.me.stunned = false;
	read_buffs(W.me);
	std::uint32_t gems = 0;
	cambc::detail::sdk_champion_gems(my_h, &gems);
	W.me.gems = gems;
	for (int s = 0; s < 2; ++s)
	{
		std::int32_t cd = 0;
		cambc::detail::sdk_champion_cooldown(my_h, static_cast<std::uint32_t>(s), &cd);
		W.cd[static_cast<std::size_t>(s)] = cd;
	}
	W.on_spawn = M.ready() && bbget(M.my_spawn, W.me.pos);
}

// Read every visible enemy champion into enemies or enemies_far; true when one is within reach of a fight.
static __attribute__((always_inline)) inline bool read_enemies()
{
	bool enemy_near = false;
	// WARD: own_vis (bc_champion_vision) includes my ward's tiles, so a foe my ward sees is in enemies (measured rz641w); enemies_far
	// holds foes outside own_vis beyond WARD_NEAR (empty while I am alive).
	const bool own_ok = cambc::detail::sdk_bc_champion_vision(my_h, W.own_vis.ptr()) == 0; // F3: self().visible_tiles_into without the wrappers
	const std::size_t ne_h = enemy_h.size(), ne_cr = cr_last.size(); // Read once; the engine calls below would otherwise make the loop reload them.
	for (std::size_t ei = 0; ei < ne_h; ++ei)                         // every pass reload them (nothing here resizes either)
	{
		const auto& e = enemy_h[ei];
		cambc::detail::champion_info ci; // F3: no Body for a foe out of sight, none copied for one in sight
		if (!read_ci(e.h, ci))
			continue;
		// An enemy hidden from me but within WARD_NEAR tiles (in a bush by my farm, say) is an immediate threat: the fight logic sees it.
		const vec2 epos{ ci.x, ci.y };
		const bool hidden = own_ok && !bbget(W.own_vis, epos) && cheb(epos, W.me.pos) > (WARD_NEAR); // ward-hidden-hit bit 8
		std::vector<Body>& dst = hidden ? W.enemies_far : W.enemies;
		dst.emplace_back();
		Body& b = dst.back();
		fill_body_from_champion_info(b, e.h, ci);
		b.ally = false;
		b.kit = kit_fast(b.type);
		if (ei < ne_cr)
		{
			const bool rec = (b.state & ST_RECALL) != 0;
			// Teams alternate and the starting team swaps each round, so an enemy gets 0, 1 or 2 turns between two of mine, and the timer
			// only falls at its own turn end. First sighting: real only at <= 1 left (a Home restart reads 2); fallen since my last turn:
			// real at <= CR2_REAL_T; unchanged (no turn of its own in between): the last verdict; risen: a restart.
			std::int32_t left = -1;
			const bool timed = rec && cambc::detail::sdk_champion_channel_time(e.h, &left) == 0 && left >= 0;
			bool real = false;
			if (timed)
			{
				const bool hist = cr_last[ei] == W.round - 1;
				real = !hist ? left <= 1 : left < cr_left[ei] ? left <= CR2_REAL_T : left == cr_left[ei] ? cr_real[ei] : false;
			}
			else
				real = rec && cr_last[ei] == W.round - 1;
			if (RGB_ON(1) && rec && cr_last[ei] == W.round) // RGB bit 1: a re-perceive this round keeps the turn's verdict
				real = cr_real[ei];
			cr_left[ei] = timed ? left : 0;
			cr_real[ei] = real;
			cr_last[ei] = rec ? W.round : -1000;
			if (rec && !real)
				b.state &= ~ST_RECALL; // a fresh recall start may be cancelled next turn
			track_spinner_recall_bit(ei, b, rec, timed ? static_cast<int>(left) : -1); // track the recall bit of a known spinner
		}
		if (hidden)
			continue;
		const bool cdm_near = cheb(b.pos, W.me.pos) <= 9;
		if (cdm_near)
		{
			enemy_near = true;
			std::uint32_t g = 0;
			if (cambc::detail::sdk_champion_gems(e.h, &g) == 0)
				b.gems = g;
			read_buffs(b);
			for (int s = 0; s < 2; ++s)
			{
				std::int32_t cd = -1;
				if (cambc::detail::sdk_champion_cooldown(e.h, static_cast<std::uint32_t>(s), &cd) == 0)
					b.cd[static_cast<std::size_t>(s)] = cd;
			}
		}
		if (!cdm_near) // bit 1 READALL: foe cooldowns are readable whenever it is visible (rules Q40)
			for (int s = 0; s < 2; ++s)
			{
				std::int32_t cd = -1;
				if (cambc::detail::sdk_champion_cooldown(e.h, static_cast<std::uint32_t>(s), &cd) == 0)
					b.cd[static_cast<std::size_t>(s)] = cd;
			}
	}
	return enemy_near;
}

// Read every ally champion; nearby allies get their bags and cooldowns when a fight may start.
static __attribute__((always_inline)) inline void read_allies(bool enemy_near)
{
	for (const auto& a : ally_h)
	{
		if (a.h == my_h)
			continue;
		cambc::detail::champion_info ci; // F3: as for the enemies
		if (!read_ci(a.h, ci))
			continue;
		W.allies.emplace_back();
		Body& b = W.allies.back();
		fill_body_from_champion_info(b, a.h, ci);
		b.ally = true;
		b.slot = a.slot;
		b.kit = kit_fast(b.type);
		if ((b.state & ST_RECALL) && !(b.state & ST_TRIBUTE))
		{
			// a mate's spin reads 4 left (a real recall only on the round after its start): no channel
			std::int32_t left = -1;
			if (cambc::detail::sdk_champion_channel_time(a.h, &left) == 0 && left >= 4)
				b.state &= ~ST_RECALL;
		}
		if (enemy_near && cheb(b.pos, W.me.pos) <= 8)
		{
			read_buffs(b);
			// A fight may start: the bags of nearby allies tell which ones to protect.
			std::uint32_t g = 0;
			if (cambc::detail::sdk_champion_gems(a.h, &g) == 0)
				b.gems = g;
			for (int s = 0; s < 2; ++s)
			{
				std::int32_t cd = -1;
				if (cambc::detail::sdk_champion_cooldown(a.h, static_cast<std::uint32_t>(s), &cd) == 0)
					b.cd[static_cast<std::size_t>(s)] = cd;
			}
		}
	}
}

// The unit, camp and vision boards of this turn.
static __attribute__((always_inline)) inline void read_occupancy_boards()
{
	// F3: no new board per read (operator new + delete ~400 fuel a board, 2 boards a turn).
	static bitboard occ_foes{ cambc::uninitialized };
	// The same six engine reads without the SDK wrappers' out-of-line check calls.
	nchk(cambc::detail::sdk_ally_occupancy(W.occ_units.ptr()));
	nchk(cambc::detail::sdk_enemy_occupancy(occ_foes.ptr()));
	bb3_or(W.occ_units, occ_foes, W.occ_units);
	nchk(cambc::detail::sdk_camp_occupancy(W.occ_camps.ptr()));
	nchk(cambc::detail::sdk_awake_camp_occupancy(W.awake.ptr()));
	nchk(cambc::detail::sdk_vision(W.vis.ptr()));
	bh67_vpos = W.me.pos;
}

// The camps within 9 tiles, with their health and awake state.
static __attribute__((always_inline)) inline void read_visible_camps()
{
	// WARD: living camps within my own sight (8) and a step: camps seen only through the ward stay in occ_camps for group bookkeeping,
	// without the per-camp reads.
	{
		// The near-camp loop over W.occ_camps within 9 of W.me.pos, inline, the same tiles in the same order; the radius-9 box board is
		// kept from the last call and redrawn only when my tile changed (it is this loop's own board); the slot table, camp lists and the
		// awake board's words are read once (nothing here moves them).
		static bitboard hb{ cambc::uninitialized }, hs{ cambc::uninitialized };
		static std::vector<vec2> hp;
		static vec2 hb_c{ -100000, -100000 };
		constexpr std::size_t cap = static_cast<std::size_t>(2 * 9 + 1) * static_cast<std::size_t>(2 * 9 + 1);
		if (hp.size() < cap)
			hp.resize(cap);
		const vec2 c = W.me.pos;
		if (!(c == hb_c))
		{
			hb_c = vec2{ -100000, -100000 };
			nchk(cambc::detail::sdk_Bitboard_Zero(hb.ptr()));
			hb.draw_chebyshev(c, 9.0f);
			hb_c = c;
		}
		bb3_and(W.occ_camps, hb, hs);
		const std::uint32_t n = hs.positions_into(std::span<vec2>(hp.data(), cap));
		const vec2* q = hp.data();
		std::int16_t* const slot = W.camp_slot.data();
		const std::size_t nslot = W.camp_slot.size();
		const auto* const camps = M.camps.data();
		const std::int16_t* const cat = M.camp_at.data(); // M.camp_index(p) and bbget(W.awake, p) with their tables read once
		const int gw = G.w, gh = G.h, mw = M.w, gs = G.stride;
		const std::uint64_t* const aw = W.awake.ptr();
		for (std::uint32_t i = 0; i < n; ++i)
		{
			const vec2 p = q[i];
			const int ci = ((static_cast<unsigned>(p.x) < static_cast<unsigned>(gw)) & (static_cast<unsigned>(p.y) < static_cast<unsigned>(gh))) ? cat[static_cast<std::size_t>(p.y * mw + p.x)] : -1; // as inb()
			if (ci < 0)
				continue;
			VisCamp v;
			v.ci = ci;
			const auto& cc = camps[static_cast<std::size_t>(ci)];
			cambc::detail::camp_state cs; // F3: read only when the engine wrote it
			if (cambc::detail::sdk_camp(cc.handle, &cs) == 0)
			{
				v.hp = cs.health;
				v.maxhp = cs.max_health;
			}
			else
			{
				v.hp = cc.hp;
				v.maxhp = cc.hp;
			}
			v.awake = NOVA_GDIRECT ? ((reinterpret_cast<const std::uint8_t*>(aw)[(p.y & ~7) * gs + (p.x & ~7) + (p.y & 7)] >> (p.x & 7)) & 1u) != 0 : bbget(W.awake, p); // the byte read of bbget
			if (static_cast<std::size_t>(ci) < nslot)
				slot[static_cast<std::size_t>(ci)] = static_cast<std::int16_t>(W.camps.size());
			W.camps.push_back(v);
		}
	}
}

__attribute__((always_inline)) void perceive()
{
	reset_turn_lists();
	if (!W.alive)
	{
		read_dead_turn();
		return;
	}
	read_own_state();
	const bool enemy_near = read_enemies();
	read_allies(enemy_near);
	read_occupancy_boards();
	read_visible_camps();
	read_tributes();
	mu::perceive_fill(W.round); // reads MUL_TAB once; bits 1|2 write each body's multipliers
}


// Slot readiness and a kit's next-turn reach: reads of W and the kit only, so move, squad and ward can use them without the combat
// files. Declared in combat.h and combat_forward.h.
namespace combat {
namespace kit_rules {
bool slot_excl(int slot)
{
	const Kit& k = *W.me.kit;
	if (slot < 0)
		return false;
	if (slot == k.slot_dmg)
		return k.dmg_excl;
	if (slot == k.slot_aoe)
		return k.aoe_excl;
	if (slot == k.slot_cc)
		return k.cc_excl;
	return false;
}
// Is ability slot s of a visible body ready (unknown counts as ready)?
bool slot_ready(const Body& b, int s)
{
	if (s < 0 || s > 1)
		return false;
	if (b.ally && b.h == W.me.h)
		return W.cd[static_cast<std::size_t>(s)] <= 0;
	return foe_ready(b, s); // the single cooldown source
}
} // namespace kit_rules
bool ready(int slot)
{
	if (slot < 0 || slot > 1)
		return false;
	if (W.cd[static_cast<std::size_t>(slot)] > 0 || W.cast || !W.can_cast())
		return false;
	if (kit_rules::slot_excl(slot) && W.moved)
		return false;
	return true;
}
// Each visible foe whose next-turn damage alone kills me gets a walk-guard zone of its lethal distance + LB_MARGIN (a foe I kill
// from a step away is left out); bit 2 enables it in CALM, bit 16 in FIGHT. foe_of's next-turn reach alone (no dps or burst work):
// the basic hit (melee a step and a hit, ranged its range, +1 with a ready reset), a ready dash (+ a step for melee), every ready
// spell at range + area radius (+1 when it allows the walk).
int foe_next_turn_reach(const Body& e, bool no_dash)
{
	const Kit* kp = e.kit;
	if (!kp || !kp->valid)
		return std::max(2, e.range + 1);
	const Kit& k = *kp;
	int reach = k.ranged ? e.range + (kit_rules::slot_ready(e, k.slot_reset) ? 1 : 0) : 2;
	if (!no_dash && k.slot_dash >= 0 && kit_rules::slot_ready(e, k.slot_dash))
		reach = std::max(reach, (k.ranged ? e.range : 1) + 2 + (k.ranged ? 0 : 1));
	auto sp = [&](int s, float range, bool excl, float radius)
	{
		if (s >= 0 && kit_rules::slot_ready(e, s))
			reach = std::max(reach, static_cast<int>(range + radius) + (excl ? 0 : 1));
	};
	sp(k.slot_dmg, k.dmg_range, k.dmg_excl, 0.0f);
	sp(k.slot_cc, k.cc_range, k.cc_excl, 0.0f);
	sp(k.slot_aoe, k.aoe_range, k.aoe_excl, k.aoe_radius);
	if (e.stunned && !e.ally)
		return burst::stunned_foe_reach(e, reach);
	return e.stunned ? (std::max(0, reach - 1)) : reach;
}
namespace memory {
int dmg_round = -1000; // last round my health + shield dropped
} // namespace memory
bool took_damage(int rounds) { return W.round - memory::dmg_round < rounds; }
} // namespace combat

} // namespace nova
