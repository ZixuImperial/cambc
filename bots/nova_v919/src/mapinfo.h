// Static map analysis shared by the draft and the champions. Computed once per bot instance, in fuel-bounded,
// resumable stages (every loop over groups keeps a cursor so a stage can continue on the next turn).
#pragma once
#include "common.h"

namespace nova {

enum Access : std::uint8_t
{
	ACC_WALK = 0,
	ACC_DASH = 1,
	ACC_TP = 2,
};

struct CampI
{
	int group = -1;
	cambc::camp_type type{};
	vec2 pos{};
	float hp = 0, str = 0;
	int reach = 0;
	std::uint32_t handle = 0;
	bool attacks() const { return str > 0; }
};

struct GroupI
{
	int idx = 0;
	std::uint32_t handle = 0;
	std::vector<int> members; // indices into MapInfo::camps
	int nm = 0; // members.size(), set beside its only writer (step_groups_t).
	int gems = 0, gold = 0, respawn = 0;
	float hp = 0, str_sum = 0, str_max = 0;
	int reach_max = 0, n_att = 0, n_clu = 0;
	int bx0 = 1 << 20, by0 = 1 << 20, bx1 = -(1 << 20), by1 = -(1 << 20); // The members' bounding box, set beside members.
	int n_mono = 0, n_golem = 0, n_elk = 0, n_wolf = 0;
	int pack = 1; // most members inside one 3x3 square
	vec2 anchor{};
	std::vector<vec2> approach;               // passable non-camp tiles next to members (capped)
	std::vector<std::pair<float, float>> att; // attackers (hp, strength), lowest hp first
	std::uint16_t d_home = UNREACH, d_enemy = UNREACH, d_altar = UNREACH;
	std::uint8_t access = ACC_WALK;
	float contest = 0.5f; // our distance / (ours + theirs): 0 = ours, 1 = theirs
	bool heavy() const { return str_sum >= 60.0f || hp >= 4000.0f; }
};

struct AltarI
{
	vec2 pos{};
	std::uint16_t d_home = UNREACH, d_enemy = UNREACH;
	bool gated = false; // reachable from our spawn only through camp tiles
	std::uint8_t access = ACC_WALK;
};

class MapInfo
{
public:
	// Run initialisation stages while more than `reserve` fuel would remain. True once the essential stages are done.
	bool init(long reserve);
	bool ready() const { return stage_ >= ST_READY; }
	bool done() const { return stage_ >= ST_DONE; }
	bool groups_ready() const { return stage_ >= ST_GROUPS; } // Camps and groups built (before ready).

	// Distances came from draft memory: skip the stages that compute them.
	void mark_distances_known() { distances_known_ = true; }
	bool distances_known() const { return distances_known_; } // The group distances came from draft memory.
	// v8xx SGPS1: the distance stage's progress (no group's d_home is written before ST_DASH phase 0, cursor order, or draft memory).
	bool dist_before_dash() const { return stage_ < ST_DASH; }
	bool dist_in_dash_scan() const { return stage_ == ST_DASH && phase_ == 0; }
	std::size_t dist_cursor() const { return cursor_; }
	// X2I bit 128 FMP1: a stamp of the group-distance progress (the stage, its cursor and phase, the draft-memory distances, the count).
	std::int64_t dist_stamp() const { return (static_cast<std::int64_t>(stage_) << 44) ^ (static_cast<std::int64_t>(phase_) << 40) ^ (static_cast<std::int64_t>(cursor_) << 12) ^ (distances_known_ ? 1LL << 52 : 0) ^ static_cast<std::int64_t>(ng); }
	// Also compute the dash-augmented field before classifying access (draft).
	bool want_dash = false;
	int ssu_x0 = -1, ssu_x1 = -1, ssu_y0 = -1, ssu_y1 = -1; // My spawn rectangle once checked full, else -1.
	// Skip the enemy-side and gating fields (champions use draft memory for those, or do without).
	bool lean = false;
	// Stop once the essential stages are done (lets the caller decode draft memory before distances).
	bool pause_at_ready = false;

	int w = 0, h = 0;
	bitboard walls, holes, altars_bb, bushes, my_spawn, enemy_spawn;
	bitboard block;       // impassable for us: walls | holes | altars | enemy spawn
	bitboard block_camps; // block | every camp spawn tile
	bitboard camp_tiles;  // every camp spawn tile
	bitboard altar_adj;   // standable tiles within Chebyshev 1 of an altar (camp tiles excluded)
	bitboard thin_holes;  // holes that a two-step dash can cross
	bool has_thin = false; // F4: thin_holes has a tile (set with it: bbany scanned every word per call)
	std::vector<CampI> camps;
	std::vector<GroupI> groups;
	int nc = 0, na = 0; // camps.size(), altars.size(), set beside their only writers.
	int ng = 0; // groups.size(), set beside the only writers of groups (step_groups_t); (end - begin) / sizeof(GroupI) costs ~15 a read.
	std::vector<AltarI> altars;
	std::vector<std::int16_t> camp_at; // tile -> camp index, or -1
	vec2 home_anchor{}, enemy_anchor{};
	distance_field f_home;      // from our spawn, camps passable
	distance_field f_enemy;     // from the enemy spawn, camps passable
	distance_field f_altar;     // to the nearest altar approach tile, camps blocked
	distance_field f_home_cb;   // from our spawn, camps blocked
	distance_field f_home_dash; // from our spawn, thin holes passable (draft)
	bool has_home = false, has_enemy = false, has_altar = false, has_home_cb = false, has_dash = false;
	bool any_altar = false; // some altar is reachable from our spawn with camps blocked
	// Gated altars: altar neighbours that are camp tiles. Their groups must die before tributing there.
	std::vector<int> gate_groups;
	std::vector<std::uint8_t> gate_mask; // b2402 GTM1: gate_groups as a per-group byte (GTM bit 1)
	void gtm_put(int gi) { if (gate_mask.size() <= static_cast<std::size_t>(gi)) gate_mask.resize(static_cast<std::size_t>(gi) + 1, 0); gate_mask[static_cast<std::size_t>(gi)] = 1; }
	bool gtm_has(int gi) const { return static_cast<std::size_t>(gi) < gate_mask.size() && gate_mask[static_cast<std::size_t>(gi)] != 0; }
	std::vector<int> ring_camps; // Camps whose death alone opens a walk from our side to an altar.
	bool ring = false; // The altars are enclosed by camps away from their neighbours.
	bool ring_todo = false, open_todo = false; // Gating work deferred for fuel.
	distance_field ring_fo; // The resumable ring scan: its field and camp cursor.
	bool ring_fo_ok = false;
	std::size_t ring_ci = 0;
	bool gate_step(long reserve); // Run the deferred work; true when none is left.
	bitboard altar_adj_all;      // standable altar neighbours including camp tiles
	distance_field f_altar_open; // to altar_adj_all, camps passable (used once a gate group is dead)
	bool has_altar_open = false;
	float total_gems = 0, total_gold = 0;

	int camp_index(vec2 p) const { return inb(p) ? camp_at[static_cast<std::size_t>(p.y * w + p.x)] : -1; }
	bool passable(vec2 p) const { return inb(p) && !bbget(block, p); }
	// Walking distance from an open field (camps passable) to a group: min over member tiles.
	std::uint16_t group_dist(const distance_field& f, const GroupI& g) const;
	// Fields with camp tiles blocked: min over the group's approach tiles, plus one step.
	std::uint16_t group_dist_blocked(const distance_field& f, const GroupI& g) const;

private:
	enum Stage
	{
		ST_NONE,
		ST_TERRAIN,
		ST_LOADED,   // camp groups fetched from the engine
		ST_GROUPS,   // camps and groups built
		ST_APPROACH, // approach tiles and altar neighbours
		ST_READY,    // altar field computed: champions can act
		ST_HOME,
		ST_ENEMY,
		ST_HOMECB,
		ST_DASH,
		ST_DONE
	};
	int stage_ = ST_NONE;
	std::size_t cursor_ = 0;
	int phase_ = 0;
	std::array<float, 8> t_hp_{}, t_str_{};
	std::array<int, 8> t_reach_{};
	std::array<bool, 8> t_known_{};
	bool distances_known_ = false;
	std::vector<cambc::map::camp_group> raw_;
	// The engine's camp layout words in light records, instead of map::camp_groups()' SDK objects.
	struct FxCamp
	{
		std::uint32_t h = 0, t = 0;
		std::int32_t x = 0, y = 0;
		cambc::camp_type kind() const noexcept { return static_cast<cambc::camp_type>(t); }
		cambc::vec2 spawn_position() const noexcept { return cambc::vec2{ x, y }; }
		explicit operator cambc::handle_camp_t() const noexcept { return static_cast<cambc::handle_camp_t>(h); }
		cambc::camp_stats base_stats() const; // camp::base_stats' engine read (the design of this kind)
	};
	struct FxGroup
	{
		std::uint32_t h = 0, gold = 0, gems = 0;
		std::int32_t respawn = 0;
		std::span<const FxCamp> cs;
		explicit operator cambc::handle_camp_group_t() const noexcept { return static_cast<cambc::handle_camp_group_t>(h); }
		std::uint32_t gem_value() const noexcept { return gems; }
		std::uint32_t gold_value() const noexcept { return gold; }
		std::int32_t max_respawn_timer() const noexcept { return respawn; }
		std::span<const FxCamp> camps() const noexcept { return cs; }
	};
	bool fx_raw_ = false;
	std::vector<FxCamp> fx_camps_;
	std::vector<FxGroup> fx_groups_;
	void load_camp_groups_raw();
	void load_camp_groups_raw_x2i(); // X3I bits 8/16
	long field_cost() const { return 3L * w * h + 4000; }
	void stage_terrain();
	bool step_groups(long reserve);    // returns true when finished
	template <class GV>
	bool step_groups_t(const GV& raw, long reserve); // step_groups over SDK groups or light records.
	bool step_approach(long reserve);  // returns true when finished
	bool step_distances(long reserve); // returns true when finished
};

extern MapInfo M;
// ALC8 / KTW (RC C807, X728): the block_camps fields (M.f_altar, alz_field, safe_altar_field) read UNREACH on a dead, standable camp tile
// (GR:196, INT:143); there the tile takes 1 + the least of its 8 neighbours (UNREACH if all are). Callers read their flag first.
inline std::uint16_t field_here(const distance_field& f, vec2 p)
{
	const std::uint16_t v = dfget(f, p);
	if (v != UNREACH || !bbget(M.camp_tiles, p))
		return v;
	int best = UNREACH;
	for (int dy = -1; dy <= 1; ++dy)
		for (int dx = -1; dx <= 1; ++dx)
		{
			const vec2 q{ p.x + dx, p.y + dy };
			if ((dx | dy) == 0 || !inb(q))
				continue;
			const int u = dfget(f, q);
			if (u != UNREACH && u + 1 < best)
				best = u + 1;
		}
	return static_cast<std::uint16_t>(best);
}
// MSY bits 2/4 (caller read the flag): a before b in a seat-mirrored order: each axis the map's symmetry flips is read from my side
// (my spawn's half), so the mirrored body orders the mirrored tiles the same way.
inline bool msy_before(vec2 a, vec2 b)
{
	const auto sym = cambc::map::symmetry();
	const int sx = (sym != cambc::symmetry::vertical && 2 * M.home_anchor.x > M.w - 1) ? -1 : 1;
	const int sy = (sym != cambc::symmetry::horizontal && 2 * M.home_anchor.y > M.h - 1) ? -1 : 1;
	return sx * a.x != sx * b.x ? sx * a.x < sx * b.x : sy * a.y < sy * b.y;
}

} // namespace nova
