// draft_state.cc: Draft tunables and state.
#include "draft_internal.h"
namespace nova::drafting {

namespace {

using cambc::champion_draft;

constexpr int NC = 12; // draft choices (Cassi & Issac are one)
enum Champ : int
{
	RY,
	VV,
	VE,
	CI,
	ST,
	PR,
	MA,
	WI,
	RE,
	VA,
	TA,
	HR
};
[[maybe_unused]] constexpr const char* SHORT[NC] = { "Ry", "VV", "Ve", "CI", "St", "Pr", "Ma", "Wi", "Re", "Va", "Ta", "HoR" };
constexpr std::uint16_t bit(int c) { return static_cast<std::uint16_t>(1u << c); }
// Champion knowledge (kits), not map knowledge.
constexpr std::uint16_t DASHERS = bit(HR) | bit(VV) | bit(VE) | bit(RE) | bit(CI);
int team_size();
// WGL bit 1 (b1769): a golem group on the map (draft-time map data).
bool wgl_golem_map()
{
	if (!M.done())
		return false;
	for (const auto& g : M.groups)
		if (g.n_golem > 0)
			return true;
	return false;
}
// Map features only: a team of 5 and >= 70% of the camp gems in groups whose strongest camp has Strength >= 60 (elk, golem,
// monolith), as tools/lab/mapfeat.py's heavy (rounded to 2 decimals).
bool marcella_for_ryth_band()
{
	if (team_size() != 5 || !M.done())
		return false;
	long tot = 0, heavy = 0;
	for (const auto& g : M.groups)
	{
		float smax = 0;
		for (int ci : g.members)
			smax = std::max(smax, M.camps[static_cast<std::size_t>(ci)].str);
		tot += g.gems;
		if (smax >= 60.0f)
			heavy += g.gems;
	}
	return tot > 0 && 200 * heavy + tot >= 140 * tot; // round(100 x heavy / tot) >= 70
}
constexpr std::uint16_t TANKS = bit(RY) | bit(MA) | bit(VA) | bit(HR);
constexpr std::uint16_t ECON = bit(VV) | bit(PR) | bit(MA);
constexpr std::uint16_t VAHR = bit(VA) | bit(HR), VEVV = bit(VE) | bit(VV), WIHR = bit(WI) | bit(HR);
// Kits with an ally heal follow a partner in play (champ_willow.cc), also into dash routes they cannot cross.
constexpr std::uint16_t FOLLOWERS = bit(WI);
constexpr float REACH_EPS = 0.1f; // Walkers realising less than this share of the dasher value reach nothing.
// The hand-set terms as the switches leave them. DF_VV_PP is in champ_vesper.h, DF_CI_PP in champ_ci.h.
constexpr float DF_DASH_PP = DRAFT_DASH_PP;
constexpr float DF_VE_PP = DRAFT_VE_PP;

inline int popc(unsigned m) { return __builtin_popcount(m); }

struct State
{
	int turn = 0;
	int k = 0, ki = 2;
	bool analysed = false;   // M.done()
	bool feat_tried = false; // fitfeat + mapfeat ran (or were skipped for good).
	fitfeat::Result fr{};
	mapfeat::Feats mf{};
	bool map_term = false; // values include this map's features; false = team-size values (z = 0)
	int tier = 0;          // Marcella's splash tier of the values
	std::array<float, dv3::NF> z{};
	bool no_walk_altar = false;
	bool pz_viable = false; // Prism's carry plan is viable here (set_values); sits in the padding before min_dash.
	int min_dash = 0;
	int max_dash = 5; // At most this many dash kits (k unless null mode).
	float reach_s = 0.0f; // Share of the realisable value only dashers reach.
	bool reach_null = false; // Non-dashers reach nothing (null picks).
	std::uint16_t live = 0xFFF; // Champions whose roles and composition terms count (all but null picks).
	std::array<unsigned, NC> roles{}; // Role masks (0 for null picks).
	bool values = false;
	std::array<float, NC> base{}; // u_c
	std::array<float, NC> mt{};   // map term of u_c
	float cov = 0.0f;             // value of one more role covered on this map (5v5)
	// Map features for Cassi & Issac (centrality) and Vendetta (chain share); centrality_chain_features() on turn 1.
	bool dr_ok = false;
	float dr_cen = 0.0f, dr_ve = 0.0f;
	float dr_dash = 0.0f; // Dash advantage in profit per round (dasher / walker - 1).
	bool dtm_ok = false; // dash_walk_times finished.
	float dtm_aw = 0.0f, dtm_ad = 0.0f, dtm_gw = 0.0f, dtm_gd = 0.0f; // Walk and dash turns, nearest altar and value-weighted groups.
	float dtm_x = 0.0f; // 0-1, how slow walking is times how much the dash saves.
	float dtm_h = 0.0f; // Heavy gem share, groups with a camp of Strength >= 60 (DTM bit 16).
	int dr_ncon = 0;
	long dr_fuel = 0;
	// Draft memory: encoded once, picks patched in on later turns.
	std::vector<std::uint8_t> mem;
	long cost_encode = 0, cost_submit = 0, cost_enum = 0, cost_plan = 0;
	std::uint8_t flags = 0;
};
State S;

// Every k-lineup's mask and value, computed once (turn 1).
constexpr int MAXL = 792; // C(12, 5), the largest for k <= 5
std::array<std::uint16_t, MAXL> LM{};
std::array<float, MAXL> LV{};
int NL = 0;
bool cached = false;

int idx_of(champion_draft d) { return static_cast<int>(d); }

std::uint16_t lineup_mask(const std::vector<champion_draft>& v)
{
	std::uint16_t m = 0;
	for (auto d : v)
		if (idx_of(d) >= 0 && idx_of(d) < NC)
			m = static_cast<std::uint16_t>(m | bit(idx_of(d)));
	return m;
}

int team_size()
{
	if (S.k <= 0)
	{
		int k = 5;
		try
		{
			k = static_cast<int>(cambc::draft::team_size());
		}
		catch (...)
		{
		}
		S.k = std::clamp(k, 1, 5);
		S.ki = std::clamp(S.k, 3, 5) - 3;
	}
	return S.k;
}

long choose(int n, int r)
{
	if (r < 0 || r > n)
		return 0;
	long t = 1;
	for (int i = 0; i < r; ++i)
		t = t * (n - i) / (i + 1);
	return t;
}
} // namespace
} // namespace nova::drafting
