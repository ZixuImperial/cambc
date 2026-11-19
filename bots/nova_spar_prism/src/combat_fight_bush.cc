// combat_fight_bush.cc: Bush tiles in a fight.
#include "combat_internal.h"
namespace nova::combat {
namespace fight_turn
{
namespace tune
{
// Tile tie-break: a free bush tile one step away with the focus in my range from it (a ranged walk-in: nearer to it). Bush tiles are
// looked at first, so a turn with none next to me costs eight bit reads. No tile with a foe I see on a bush within 8, or a foe ward
// I see on a bush within 8: they may see into that cluster.
inline constexpr int BUSH_SEE_R = 8;        // a foe or foe ward on a bush this near may see into the cluster
// The retreat a flee leaves for continue_retreat.
inline constexpr int RETREAT_ROUNDS = 5; // rounds a flee keeps it going
// retreat_to_spawn_to_heal: SP_TAB bit 1 asks for a foe this near, bit 4 for a farther one.
inline constexpr int SP_NEAR_D = 8;
// lethal_burst_flee_turn: the lethal flee's tile is at most this far (a walk or a dash).
inline constexpr int LB_TILE_MAX_D = 2;
inline constexpr int SHIELD_FOE_DIST = 2;         // shield with the focus this near, in reach or not
inline constexpr int LINK_STUN_BOUND = 4;         // linked Cassi: her stun goes to a foe nearer than this to Issac (his dash reach 3)
inline constexpr float WEAK_FOCUS_FRAC = 0.5f;    // Vendetta and Vesper Vale dash at a focus below this health
// VV_LANDING_CROWD (champ_vesper.h): Vesper Vale's landing: at most this many other enemies can reach it
inline constexpr int AREA_WEIGHT_FRESH = 2; // area pick: what a fresh body under the spell counts for
inline constexpr int AREA_WEIGHT_STUNNED = 1;     // the same for a stunned one under an area stun (half wasted)
inline constexpr float NO_TARGET_HP = 1e9f;       // above any body's effective health
inline constexpr float STUNNED_LAST = 1e6f;       // health added to a stunned foe so an unstunned one goes first
inline constexpr float WALK_IN_VETO_FRAC = 0.25f; // a walk-in step may enter danger up to this share of my effective health
inline constexpr int WALK_IN_SEARCH = 20;         // step_to's search budget for the walk to the focus
inline constexpr int ED_WORST_FOE_TURNS = 2;   // every foe's turns before my next one, the worst case of turn order
inline constexpr int ED_MIN_FUEL = 20000; // below this the turn-order answer is not worked on
inline constexpr int ED_SEARCH_MIN_FUEL = 60000; // the search and the flee that may follow it must both fit
inline constexpr int ED_TRY_MIN_FUEL = 15000;  // a further try of the search
inline constexpr int ED_TRIES = 3;             // end tiles tried
inline constexpr int ED_HIT_DISTS = 12; // number of distances a foe's hit is cached for
inline constexpr int ED_FOE_R = 9;             // foes farther from me than this do not count
inline constexpr int ED_RETREAT_ROUNDS = 5;    // the retreat the dash starts
inline constexpr int ED_END_MIN_R = 2;         // a dash + step ends at least this far from me
inline constexpr int CRX_NEAR_N = 3;              // near foes whose walk is worked out (one host field each)
inline constexpr int CRX_NEAR_R = 8;              // foes farther than this are not near
inline constexpr int CRX_CAUGHT_R = 3;            // the escape needs a foe this near
inline constexpr int CRX_BUS_TICKS = 4;           // channel_safe's channel length
inline constexpr long CRX_FUEL_PER_TILE = 2L;     // fuel of a field, per map tile
inline constexpr long CRX_FUEL_FLOOR = 20000L;
inline constexpr int CRX_DASH_READY_TURNS = 3;    // a foe's dash ready within this many turns crosses holes
inline constexpr int CRX_UNREACHED = 999;         // a tile a foe's field does not reach
inline constexpr int CRX_CAMP_R = 7; // camps this near may cover a landing
inline constexpr int CRX_JUMP_R = 3;              // the crystal's landing box
inline constexpr int CRX_LANDINGS_MAX = (2 * CRX_JUMP_R + 1) * (2 * CRX_JUMP_R + 1) - 1;
inline constexpr int CRX_TRIES = 3;               // landings tried (a hidden body refuses one)
inline constexpr int CRX_RETREAT_ROUNDS = 8;      // the channel's 3 turns + the 5 of a retreat from the landing
// A landing's score:
inline constexpr int CRX_SCORE_PER_STEP = 2;      // per extra step a foe needs, up to CRX_SCORE_STEPS_MAX
inline constexpr int CRX_SCORE_STEPS_MAX = 10;
inline constexpr int CRX_SCORE_IN_REACH = 20;     // lost per known foe with the landing in reach
inline constexpr int CRX_SCORE_HOME_MAX = 5;      // one per step toward home, up to this either way
inline constexpr int CRX_SCORE_MY_SPAWN = 10;
inline constexpr int CRX_SCORE_MATE = 3;          // a healthy mate near the landing
inline constexpr int CRX_MATE_R = 3;
inline constexpr float CRX_MATE_FRAC = 0.5f;
}
namespace {
// One fight() call: the focus, my distance to it and what the steps have done so far.
struct FightCtx
{
	const Assessment& a;
	const Kit& k;
	const Body& f; // fight()'s own copy of the focus
	int d;
	const int cc_r, dash_r, dmg_r; // the kit's ranges in tiles
	bool acted = false;
	bool hold = false; // no walk toward the focus this turn
	bool path_failed = false;
	int d_before_walk = 0;
};
using EdHits = std::array<std::array<float, tune::ED_HIT_DISTS>, 12>;
// One dash escape: the worst-case damage a tile takes, computed lazily.
struct EdCtx
{
	const Assessment& a;
	const Kit& k;
	vec2 me;
	float cap;
	const std::array<int, 12>& nn;
	EdHits& hit; // a foe's hit depends only on the distance: each pair is computed once
};
// The foes nearest me, up to CRX_NEAR_N within CRX_NEAR_R.
struct CrxNear
{
	std::array<const Body*, tune::CRX_NEAR_N> near{};
	int nn = 0;
	int d_min = BIG; // the nearest enemy
};
struct CrxLand
{
	vec2 t;
	int score;
};
using CrxFields = std::array<std::unique_ptr<distance_field>, tune::CRX_NEAR_N>;
// Out in the open and free to step: the gate of every step onto a bush.
static inline bool bush_step_open() { return W.can_move() && !W.on_spawn && !W.me.channeling() && !bbget(M.bushes, W.me.pos); }
// The foe wards I see on bushes.
static const bitboard& bush_foe_wards()
{
	static bitboard fw{ cambc::uninitialized };
	cambc::vision::ward_tiles_into(team::enemy, fw);
	fw &= M.bushes;
	return fw;
}
// v715 FWB bit 1: a foe ward on a bush (fw) within its sight range of t whose vision mask holds t. One mask per ward tile a round.
static __attribute__((noinline)) bool fwb_ward_sees(const bitboard& fw, vec2 t)
{
	static std::array<vec2, 6> wp{};
	static std::array<bitboard, 6> wm{};
	static int wn = 0, wr = -1000;
	if (wr != W.round)
	{
		wr = W.round;
		wn = 0;
	}
	bool sees = false;
	bbforeach_near(fw, t, 6, [&](vec2 w) {
		if (sees)
			return;
		int k = -1;
		for (int i = 0; i < wn && k < 0; ++i)
			if (wp[static_cast<std::size_t>(i)] == w)
				k = i;
		if (k < 0)
		{
			if (wn >= 6)
			{
				sees = true; // more wards than slots: keep live's caution
				return;
			}
			k = wn++;
			wp[static_cast<std::size_t>(k)] = w;
			cambc::ward::visible_tiles_from_into(w, wm[static_cast<std::size_t>(k)]);
		}
		sees = bbget(wm[static_cast<std::size_t>(k)], t);
	});
	return sees;
}
// A foe or foe ward I see on a bush near t may see into its cluster.
static bool bush_watched(vec2 t, const bitboard& fw)
{
	bool seen_in = false;
	for (const auto& e : W.enemies)
		seen_in = seen_in || (cheb(e.pos, t) <= tune::BUSH_SEE_R && bbget(M.bushes, e.pos));
	if (!seen_in)
		return fwb_ward_sees(fw, t); // v715 FWB bit 1: the ward's own vision
	if (!seen_in)
		bbforeach_near(fw, t, tune::BUSH_SEE_R, [&](vec2) { seen_in = true; });
	return seen_in;
}
// The lowest score(tile, camp threat) of the n bush tiles in c that are free, unwatched and no more camp threat than here; the first on a tie.
template <class Score>
static vec2 bush_best_tile(const vec2* c, int n, Score&& score)
{
	const bitboard& fw = bush_foe_wards();
	const float here_threat = mv::camp_threat(W.me.pos);
	vec2 best{ -1, -1 };
	float best_s = 0.0f;
	for (int i = 0; i < n; ++i)
	{
		const vec2 t = c[i];
		if (!mv::free_tile(t))
			continue;
		const float th = mv::camp_threat(t);
		if (th > here_threat || bush_watched(t, fw))
			continue;
		const float s = score(t, th);
		if (best.x < 0 || s < best_s)
		{
			best = t;
			best_s = s;
		}
	}
	return best;
}
bool bush_perch_step(const Assessment& a, const Body& f, int d)
{
	if (!bush_step_open())
		return false;
	vec2 c[8];
	int n = 0;
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!inb(t) || !bbget(M.bushes, t))
			continue;
		const int nd = cheb(t, f.pos);
		if (W.me.kit->ranged ? nd < d : nd <= W.me.range)
			c[n++] = t;
	}
	if (n == 0 || econ::capture_pay_in() >= 0)
		return false;
	const vec2 best = bush_best_tile(c, n, [&](vec2 t, float) { return geom::danger_at(a, t); });
	return best.x >= 0 && mv::try_move(best);
}
} // namespace
} // namespace fight_turn
} // namespace nova::combat
