// econ_items.cc: Build order and emblem ranking.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int emb_mstat = 0; // make_build's main stat (0 Strength, 1 Focus, 2 Health)
// ---------------------------------------------------------------- builds and shopping

// the shop plan per strategy mode.
int itm_mode = -1; // the plan the current build was made for (-1: none yet)
constexpr int I_MONSTER = 0, I_POWER = 1, I_DURABILITY = 2, I_TREASURE = 3, I_JUNGLE = 4, I_BRUISER = 6, I_CAPTURE = 8,
			  I_PROSPECTOR = 9, I_HUNTER = 10, I_SKIRMISH = 11, I_COLLECTORS = 13, I_TRIBUTE = 7;
// the tail's 5-entry runs of one family and stat -> one Greed entry; grt_orig keeps each Greed entry's source (per stat, in build
// order) so greed_gate can turn it back.
cambc::item_type grt_orig[3][24];
int grt_n[3] = { 0, 0, 0 };
// KBD (item_upgrades.h): the kit's fixed head, the entries at the front of build that emblem_rank must not touch.
int kbd_pin = 0; // entries at the front of build that emblem_rank must not touch
} // namespace
float emb_hp_ch = 0, emb_hp_camp = 0, emb_php = -1;
// the map's FIGHT index (log area per body, log gems per body, top group gem share, log spawn walk) and the gold-to-gem ratio (log
// camp gold / gems), once.
static float emb_fight = 0, emb_gg = 1.25f;
static bool emb_fdone = false;
namespace {
cambc::item_type itm_shard(int family, int st) { return cambc::item_type(static_cast<std::uint32_t>(family * 6 + st * 2)); }
int itm_family(cambc::item_type t) { return static_cast<int>(static_cast<std::uint32_t>(t) / 6); }
int itm_stat(cambc::item_type t) { return static_cast<int>(static_cast<std::uint32_t>(t) % 6) / 2; }
int item_plan_mode()
{
	return ITM_FORCE_PLAN >= 0 ? ITM_FORCE_PLAN : static_cast<int>(strat::mode());
}
bool upitm_stale() { return itm_mode >= 0 && item_plan_mode() != itm_mode; }
// Holder preference (lower = better; 9 = never). From the income model over 500 base team-games: the best cluster farmer is
// Marcella, Vendetta or Vesper Vale in 357 of 500; the best killer Marcella, Vesper Vale, HoR, Vendetta.
int item_rank_cluster(cambc::champion_type t)
{
	switch (t)
	{
	case cambc::champion_type::marcella: return 0;
	case cambc::champion_type::vendetta: return 1;
	case cambc::champion_type::vesper_vale: return 2;
	case cambc::champion_type::heart_of_ruin: return 3;
	case cambc::champion_type::ryth: return 4;
	default: return 5; // every other non-healer farms clusters too (Cassi, Issac, Varg: 42-63 cluster gems a game)
	}
}
int item_rank_killer(cambc::champion_type t)
{
	switch (t)
	{
	case cambc::champion_type::marcella: return 0;
	case cambc::champion_type::vesper_vale: return 1;
	case cambc::champion_type::heart_of_ruin: return 2;
	case cambc::champion_type::vendetta: return 3;
	default: return 9;
	}
}
// Am I among my team's best n holders by rank? (ties: lower slot first)
bool item_in_top_holders(int (*rank)(cambc::champion_type), int n)
{
	const int me = P.my_slot;
	if (me < 0 || me >= P.n)
		return false;
	const int r = rank(P.type[static_cast<std::size_t>(me)]);
	if (r >= 9)
		return false;
	int better = 0;
	for (int i = 0; i < P.n; ++i)
	{
		if (i == me)
			continue;
		const int ri = rank(P.type[static_cast<std::size_t>(i)]);
		if (ri < r || (ri == r && i < me))
			++better;
	}
	return better < n;
}
// Prospector's map gate: clusters hold ITM_CLU_MIN100 % or more of the camp gems on our half and the centre (contest <= 0.6, walk
// reachable), and those groups hold ITM_GOLD_MIN gold or more (so the emblem can be bought early).
bool item_cluster_map()
{
	int gems = 0, clu = 0, gold = 0;
	for (const auto& g : M.groups)
	{
		if (g.d_home == UNREACH || g.contest > 0.6f || g.n_mono > 0)
			continue;
		gems += g.gems;
		gold += g.gold;
		int n_gem = 0, n_other = 0; // a gem cluster is 7 gems (engine design); an all-cluster group's gems count exactly
		for (const int ci : g.members)
			if (ci >= 0 && ci < M.nc)
			{
				const auto t = M.camps[static_cast<std::size_t>(ci)].type;
				if (t == cambc::camp_type::gem_cluster)
					++n_gem;
				else if (t != cambc::camp_type::gold_cluster)
					++n_other;
			}
		clu += n_other == 0 ? (n_gem > 0 ? g.gems : 0) : std::min(g.gems, 7 * n_gem);
	}
	return gems > 0 && 100 * clu >= ITM_CLU_MIN100 * gems && gold >= ITM_GOLD_MIN;
}
// Index just after the first Treasure entry (0 when there is none).
std::size_t item_index_after_treasure()
{
	for (std::size_t i = 0; i < build.size(); ++i)
		if (itm_family(build[i]) == I_TREASURE)
			return i + 1;
	return 0;
}
// Index of the first entry whose family already appeared earlier (the start of the repeating tail), or build.size().
std::size_t item_tail_start()
{
	std::array<bool, 16> seen{};
	for (std::size_t i = 0; i < build.size(); ++i)
	{
		const int f = itm_family(build[i]);
		if (f >= 0 && f < 16 && seen[static_cast<std::size_t>(f)])
			return i;
		if (f >= 0 && f < 16)
			seen[static_cast<std::size_t>(f)] = true;
	}
	return build.size();
}
void itm_insert_at(std::size_t at, cambc::item_type t) { build.insert(build.begin() + static_cast<std::ptrdiff_t>(std::min(at, build.size())), t); }
// Called at the end of make_build: top build, then the mode's plan, then Collectors, then partial shards first.
void upitm_post(const Kit& k, int stat, bool caster)
{
	constexpr int HEALTH = 2;
	const int mode = item_plan_mode();
	itm_mode = mode;
	const bool healer = willow_layer::kit(k);
	(void)caster;
	if (const auto plan = strat::policy_of(static_cast<strat::Mode>(mode)).item_plan) // the strategy's changes to the build
		plan(k, stat, healer);
	// On a gold-free map (every camp a gem cluster, draft_prism.cc's test) Treasure only touches kill gold, so it becomes Hunter for
	// every non-healer (a family never twice; Prospector is untouched).
	{
		bool gold_free = !M.camps.empty();
		for (const auto& c : M.camps)
			if (c.type != cambc::camp_type::gem_cluster)
			{
				gold_free = false;
				break;
			}
		if (gold_free && !healer)
		{
			const int to = I_HUNTER;
			bool have = false;
			for (const auto& t : build)
				if (itm_family(t) == to)
					have = true;
			for (std::size_t i = 0; i < build.size();)
			{
				if (itm_family(build[i]) != I_TREASURE)
					++i;
				else if (!have)
				{
					build[i] = itm_shard(to, itm_stat(build[i]));
					have = true;
					++i;
				}
				else
					build.erase(build.begin() + static_cast<std::ptrdiff_t>(i));
			}
		}
	}
	// the late families, before the first Power emblem (the passive-less tail).
	if (!healer)
	{
		std::size_t at = build.size();
		for (std::size_t i = 0; i < build.size(); ++i)
			if (itm_family(build[i]) == I_POWER)
			{
				at = i;
				break;
			}
		auto has = [](int fam) { return std::any_of(build.begin(), build.end(), [fam](const cambc::item_type& t) { return itm_family(t) == fam; }); };
		if (!has(I_COLLECTORS))
			itm_insert_at(at, itm_shard(I_COLLECTORS, stat));
		if (!has(I_TRIBUTE))
			itm_insert_at(at, itm_shard(I_TRIBUTE, stat));
		if (!has(I_CAPTURE))
			itm_insert_at(at, itm_shard(I_CAPTURE, stat));
	}
	// move an entry the build already holds; families and counts are unchanged.
	auto move_to = [](int fam, std::size_t pos) {
		for (std::size_t i = 0; i < build.size(); ++i)
			if (itm_family(build[i]) == fam)
			{
				if (i > pos)
				{
					const cambc::item_type t = build[i];
					build.erase(build.begin() + static_cast<std::ptrdiff_t>(i));
					build.insert(build.begin() + static_cast<std::ptrdiff_t>(std::min(pos, build.size())), t);
				}
				return;
			}
	};
	if (!healer && (vesper_layer::shop_capture_first(k) || marcella_layer::shop_capture_item()))
		move_to(I_CAPTURE, 3);
	// Heart's first Health emblem(s) move forward (before the partial-shard fix below, so a half-bought emblem is still finished
	// first). Read only for a Heart. A mode change must not strand loose shards: finish any partial emblem first. Move the list's own
	// entry of that shard to the front, and add one only when the new list lacks it, so a family never gets a second emblem by accident
	// (a duplicate entry made need[] reach 2 and bought a second, passive-less emblem).
	try
	{
		const auto counts = cambc::self().item_count();
		for (std::uint32_t i = 0; i < 84u; i += 2)
		{
			const int n = static_cast<int>(counts[cambc::item_type(i)]);
			if (n <= 0 || n >= 5 || i / 6 == 12u)
				continue;
			const auto same = [i](const cambc::item_type& t) { return static_cast<std::uint32_t>(t) == i; };
			const auto it = std::find_if(build.begin(), build.end(), same);
			if (it != build.end())
				build.erase(it);
			itm_insert_at(0, cambc::item_type(i));
		}
	}
	catch (...)
	{
	}
}
void prism_carrier_shop_build(); // her Health build
// is this kit's Focus worth less than PWL_FMIN % of Strength (bits 1/4 apply)?
bool focus_worth_less(const Kit& k)
{
	const int t = static_cast<int>(W.me.type);
	return !willow_layer::shop_skip_pwl(k) && t >= 0 && t < 13 && PWL_FV[t] < PWL_TAB[2];
}
// Bruiser stat emblems -> Power on a kit whose Focus is worth ~0 (before upitm_post: its partial-shard fix still runs).
void bruiser_to_power_emblems(const Kit& k)
{
	if (!focus_worth_less(k))
		return;
	for (auto& t : build)
		if (itm_family(t) == I_BRUISER && ((itm_stat(t) == 0) || (itm_stat(t) == 2 && false)))
			t = itm_shard(I_POWER, itm_stat(t));
}
void greed_tail_pass(const Kit& k)
{
	grt_n[0] = grt_n[1] = grt_n[2] = 0;
	if (willow_layer::shop_skip_grt(k) || prism_layer::shop_skip_grt() || tavi_layer::shop_skip_grt())
		return;
	constexpr std::uint32_t POWER = 1, BRUISER = 6, GREED = 12;
	std::vector<cambc::item_type> out;
	out.reserve(build.size());
	std::array<int, 96> run{};
	int bru_seen[3] = { 0, 0, 0 };
	for (const auto& t : build)
	{
		const std::uint32_t si = static_cast<std::uint32_t>(t), fam = si / 6u, st = (si % 6u) / 2u;
		bool conv = false;
		if (si < 84u && st < 3u)
		{
			if (fam == POWER)
				conv = true;
			else if (fam == BRUISER && bru_seen[st]++ > 0)
				conv = st == 2u ? false : false;
		}
		if (conv && run[si] == 0)
		{
			if (grt_n[st] >= 24)
				conv = false;
			else
			{
				grt_orig[st][grt_n[st]++] = t;
				out.push_back(cambc::item_type(GREED * 6u + st * 2u));
			}
		}
		if (!conv)
		{
			out.push_back(t);
			continue;
		}
		if (++run[si] == 5)
			run[si] = 0;
	}
	build.swap(out);
}
void kit_head_pass()
{
	const int bit = willow_layer::type(W.me.type) ? 1 : ren_layer::type(W.me.type) ? 2 : 0;
	if ((KBD_TAB[1] & bit) == 0)
		return;
	const int row = bit == 1 ? 2 : 8;
	int n = 0;
	for (int i = 0; i < 6; ++i)
	{
		const int v = KBD_TAB[row + i];
		if (v <= 0)
			break;
		const cambc::item_type e = cambc::item_type(static_cast<std::uint32_t>(v - 1));
		const int fam = itm_family(e);
		for (std::size_t j = static_cast<std::size_t>(n); j < build.size();)
		{
			if (fam == I_BRUISER || fam == I_POWER)
			{
				if (build[j] == e)
				{
					build.erase(build.begin() + static_cast<std::ptrdiff_t>(j));
					break;
				}
				++j;
			}
			else if (itm_family(build[j]) == fam)
				build.erase(build.begin() + static_cast<std::ptrdiff_t>(j));
			else
				++j;
		}
		build.insert(build.begin() + n, e);
		++n;
	}
	kbd_pin = n;
}
void make_build()
{
	build.clear();
	const Kit& k = *W.me.kit;
	if (prism_layer::shop_health_build(k))
	{
		prism_carrier_shop_build(); // the carrier's Health build
		build_ready = true;
		return;
	}
	// Main damage stat: whichever adds more per shard. A healer's heal is its job, so healers take Focus.
	const float str_value = k.str_g * (static_cast<float>(rs::slot_cooldown()) + (k.slot_reset >= 0 ? 1.0f : 0.0f)) / static_cast<float>(rs::slot_cooldown()) * (varg_layer::shop_str(k) ? 1.5f : 1.0f);
	const float foc_value = k.foc_g *
		(k.dmg_mod + k.cc_mod + 1.5f * k.aoe_mod + 1.5f * k.dash_mod + 0.6f * k.shield_mod + 1.0f * k.heal_mod) / 8.0f;
	int stat = ((willow_layer::shop_focus_stat(k) && !true) || foc_value > str_value) ? 1 : 0; // 0 strength, 1 focus
	if (k.dmg_mod >= 2.0f)
		stat = 1; // a 2 x Focus burst spell (Marcella; Cassi and Stellar already take Focus)
	constexpr int HEALTH = 2;
	if (prism_layer::shop_health_stat(k))
		stat = HEALTH;
	emb_mstat = stat;
	auto emblem = [](int family, int st) { return cambc::item_type(static_cast<std::uint32_t>(family * 6 + st * 2)); };
	constexpr int MONSTER = 0, POWER = 1, DURABILITY = 2, TREASURE = 3, JUNGLE = 4;
	// Ryth's passive families take Health; `stat` (Strength) stays for Bruiser main and the tail. Heart's passive families take Health
	// as well (read only for a Heart).
	const int fstat = (ryth_layer::shop_health_families(k)) ? HEALTH : stat;
	// Bodies that hold camps take Jungle (camp damage -30%) first; then damage and Health emblems alternate (mixed builds win 3v3
	// fights 92-99% against pure damage at 600-1,200 gold). Ranged damage dealers rarely hold a camp: Monster (+15% camp damage in
	// 2.0.0) first, Jungle later.
	const bool caster = k.ranged && !willow_layer::kit(k);
	// Vesper Vale farms alone and earns a third more from her own captures and kills, so her Strength pays twice: faster clears (more
	// captures, solo wolves and elks) and kills. Order: Treasure, Monster, Durability Health, Bruiser main, then Power main, main,
	// Health. Build 2: the same opening, then Power main only. Build 3: Treasure, Bruiser main, Durability Health, then Monster main
	// and Power main, main, Health.
	if (vesper_layer::shop_build(k) && !willow_layer::kit(k))
	{
		constexpr int VV_BRUISER = 6;
		build.push_back(emblem(TREASURE, stat));
		build.push_back(emblem(VV_BRUISER, stat));
		build.push_back(emblem(DURABILITY, HEALTH));
		build.push_back(emblem(MONSTER, stat));
		for (int i = 0; i < SHOP_TAIL; ++i)
		{
			bool hp = i % 3 == 2;
			build.push_back(emblem((!hp) ? VV_BRUISER : POWER, hp ? HEALTH : stat));
		}
		bruiser_to_power_emblems(k);
		upitm_post(k, stat, caster);
		greed_tail_pass(k);
		build_ready = true;
		return;
	}
	// Treasure (+10% gold in 2.0.0, GameRules.md:306) first. It pays back after 1,500 gold earned (champions earn ~1,400-1,700 a game)
	// and lifts kill gold to 110 (BalanceChanges.md :1207) and lifetime gold (the second tiebreak). Healers support, so they skip it.
	// On gold-free maps it changes (see above).
	if (!willow_layer::shop_skip_treasure(k))
		build.push_back(emblem(TREASURE, fstat));
	// Tung's order after the first two: Bruiser Health, Durability Health, Bruiser main (Bruiser: 5 of the stat plus
	// one of each other, 7 stat units against Power's 6). Local A/B against the Power order: 48-36, gems +9%.
	constexpr int BRUISER = 6;
	// Bodies that front fights (not casters) take Bruiser Health before Jungle, to keep up with the max HP of opposing champions.
	if (!caster)
		build.push_back(emblem(BRUISER, HEALTH));
	const int rcb_j = caster ? fstat : ((heart_layer::shop_rcb_health(k)) ? HEALTH : fstat); // rb1
	build.push_back(emblem(caster ? MONSTER : JUNGLE, rcb_j));
	if (caster)
		build.push_back(emblem(BRUISER, HEALTH));
	build.push_back(emblem(DURABILITY, HEALTH));
	build.push_back(emblem(BRUISER, stat));
	build.push_back(emblem(caster ? JUNGLE : MONSTER, fstat));
	for (int i = 0; i < SHOP_TAIL; ++i)
	{
		// Ryth: each Health shard also adds 1 Strength (1% of bonus health). By the late emblems (Str ~150, HP ~2,300) a Health shard adds
		// 100/HP + 1/Str = 5.0% to the health x damage product against 3.1% for a Strength shard: Health, Health, Strength.
		if (ryth_layer::shop_tail_hhs(k))
		{
			build.push_back(emblem(POWER, (i % 3 != 2) ? HEALTH : stat));
			continue;
		}
		const bool hp = (i & 1) != 0;
		build.push_back(emblem((!hp) ? BRUISER : POWER, hp ? HEALTH : stat)); // main-stat emblems are Bruiser
	}
	bruiser_to_power_emblems(k);
	upitm_post(k, fstat, caster);
	if (!willow_layer::shop_skip_tb(k) && 100.0f * std::min(str_value, foc_value) >= static_cast<float>(TB_MIN_PCT) * std::max(str_value, foc_value))
		for (auto& t : build)
			if (static_cast<int>(static_cast<std::uint32_t>(t) / 6u) == POWER)
				t = emblem(BRUISER, static_cast<int>(static_cast<std::uint32_t>(t) % 6u) / 2);
	greed_tail_pass(k);
	kit_head_pass();
	if (ci_layer::type(W.me.type)) // C&I builds go last, so the emblem rank's pin and the Bruiser tail keep them
		nova::ci::builds::build_pass();
	build_ready = true;
}
int next_emblem_cost()
{
	if (build_ready && upitm_stale())
		build_ready = false; // the strategy mode changed: remake the build
	if (!build_ready)
		make_build();
	try
	{
		FxmItems counts; // item_count() without its 336-byte zero fill
		my_item_counts(counts);
		std::array<int, 96> need; // item ids reach 83 in engine 2.0.0 and later
		vzero(need); // zero the array with vector stores
		for (const auto& sh : build)
		{
			const auto si = static_cast<std::size_t>(static_cast<std::uint32_t>(sh));
			++need[si];
			if (static_cast<int>(counts[cambc::item_type(static_cast<std::uint32_t>(si + 1))]) >= need[si])
				continue;
			if (static_cast<int>(si) / 6 == 12)
				return 150; // a Greed entry is bought in 5-shard steps, so the shop cadence stays that of a 5-shard emblem
			return 30 * std::max(1, 5 - static_cast<int>(counts[sh]));
		}
		return 1 << 24; // the whole list is owned: nothing to buy (want_shop stays false)
	}
	catch (...)
	{
	}
	return 150;
}
} // namespace
// inlined: the gold bookkeeping and the first early-out test run at the call site, the rest out of line
__attribute__((always_inline)) void emblem_observe()
{
	const int g = static_cast<int>(W.gold);
	if (emb_pgold >= 0 && g > emb_pgold)
		emb_gold += g - emb_pgold;
	emb_pgold = g;
	if (!W.alive || emb_pr == now())
		return;
	emblem_observe_slow();
}
__attribute__((noinline)) void emblem_observe_slow()
{
	int dmin = 1000;
	for (const auto& en : W.enemies)
		dmin = std::min(dmin, cheb(en.pos, W.me.pos));
	++emb_turns;
	if (dmin <= 4)
		++emb_fturns;
	if (emb_php >= 0 && emb_pr == now() - 1 && !W.on_spawn && W.me.hp < emb_php)
		(dmin <= 5 ? emb_hp_ch : emb_hp_camp) += emb_php - W.me.hp;
	emb_php = W.me.hp;
	emb_pr = now();
}
static void emblem_map_features()
{
	if (emb_fdone)
		return;
	emb_fdone = true;
	const float T = static_cast<float>(std::max(1, P.n));
	float gems = 0, gold = 0, top = 0;
	for (const auto& g : M.groups)
	{
		gems += static_cast<float>(g.gems);
		gold += static_cast<float>(g.gold);
		top = std::max(top, static_cast<float>(g.gems));
	}
	const float apb = std::log1p(static_cast<float>(M.w * M.h) / (2.0f * T)), gpb = std::log1p(gems / (2.0f * T));
	const float top1 = gems > 0 ? top / gems : 0.0f, s2s = std::log1p(P.s2s > 0 ? static_cast<float>(P.s2s) : 200.0f);
	emb_fight = -4.8249f * (apb - 5.6879f) / 0.6777f - 6.7749f * (gpb - 4.0217f) / 1.0192f + 5.7862f * (top1 - 0.2422f) / 0.1890f -
		3.9131f * (s2s - 3.4376f) / 1.0522f;
	emb_gg = std::log(std::max(1.0f, gold) / std::max(1.0f, gems));
}
// re-order the next EMB_WIN incomplete entries' rankable ones by value.
void emblem_rank(const decltype(cambc::self().item_count())& counts)
{
	constexpr std::uint32_t MONSTER = 0, POWER = 1, DURABILITY = 2, TREASURE = 3, JUNGLE = 4, BRUISER = 6, SKIRMISH = 11, COLLECTORS = 13;
	if (!W.me.kit || !build_ready || now() < EMB_TAB[8])
		return;
	const Kit& k = *W.me.kit;
	if (willow_layer::shop_skip_emb(k) || (prism_layer::shop_skip_emb(k)))
		return;
	const int win = std::max(1, std::min(16, static_cast<int>(EMB_TAB[7])));
	std::array<int, 96> need;
	vzero(need); // zero the array with vector stores
	std::array<int, 16> idx{};
	int n = 0;
	for (std::size_t i = 0; i < build.size() && n < win; ++i)
	{
		const auto si = static_cast<std::size_t>(static_cast<std::uint32_t>(build[i]));
		if (si + 1 >= need.size())
			continue;
		++need[si];
		if (static_cast<int>(counts[cambc::item_type(static_cast<std::uint32_t>(si + 1))]) >= need[si])
			continue;
		if (static_cast<int>(i) < kbd_pin)
			continue; // the fixed head of the build stays as it is
		idx[static_cast<std::size_t>(n++)] = static_cast<int>(i);
	}
	if (n < 2)
		return;
	auto owned = [&](std::uint32_t fam)
	{
		for (std::uint32_t s = 0; s < 3; ++s)
			if (counts[cambc::item_type(fam * 6u + s * 2u + 1u)] > 0)
				return true;
		return false;
	};
	auto rankable = [&](std::uint32_t fam)
	{
		return fam == MONSTER || fam == POWER || fam == DURABILITY || fam == JUNGLE || fam == BRUISER || fam == COLLECTORS || (fam == TREASURE) || (fam == SKIRMISH);
	};
	// rate inputs for the value estimate
	float sg = 1, fc = 0.177f, c = 0.505f, gr = static_cast<float>(EMB_TAB[9]) / 100.0f, rl = 0;
	int fams = 0;
	const float S = emb_mstat == 0 ? W.me.str : emb_mstat == 1 ? W.me.foc : W.me.maxhp;
	const float g = emb_mstat == 0 ? k.str_g : emb_mstat == 1 ? k.foc_g : k.hp_g;
	sg = g > 0 ? S / g : 1.0f;
	{
		emblem_map_features();
		// per-kit intercepts; kits without a fitted value use the pan-kit value
		static constexpr float AF[13] = { .198f, .133f, .143f, .152f, .095f, .177f, .354f, .261f, .177f, .177f, .102f, .177f, .177f };
		static constexpr float AC[13] = { .558f, .647f, .549f, .371f, .537f, .505f, .358f, .541f, .505f, .505f, .648f, .505f, .505f };
		const int t = static_cast<int>(W.me.type);
		const std::size_t ti = static_cast<std::size_t>(t >= 0 && t < 13 ? t : 5);
		fc = std::clamp(AF[ti] + 0.0088f * emb_fight, 0.02f, 0.8f);
		c = std::clamp(AC[ti] - 0.0148f * emb_fight, 0.05f, 0.95f);
		gr *= std::clamp(std::exp(0.5f * (emb_gg - 1.25f)), 0.6f, 1.6f) * mu::gold_mult(0, vesper_layer::gold_pct(&k)); // single-source maps: scale the Vesper gold rate
	}
	const float nt = static_cast<float>(emb_turns), w = nt / (nt + static_cast<float>(std::max(1, static_cast<int>(EMB_TAB[2]))));
	if (emb_turns > 0)
		fc = (1 - w) * fc + w * static_cast<float>(emb_fturns) / nt;
	const float lost = emb_hp_ch + emb_hp_camp;
	if (lost > 0)
		c = (1 - w) * c + w * emb_hp_camp / lost;
	const int r = std::max(1, now());
	gr = (1 - w) * gr + w * static_cast<float>(emb_gold) / static_cast<float>(r);
	auto left = [&](int trib) { return trib <= 0 ? GAME_END_F : static_cast<float>(1000 - trib) * static_cast<float>(r) / static_cast<float>(trib); };
	rl = std::max(0.0f, std::min({ static_cast<float>(GAME_END - r), left(W.tributed_us), left(W.tributed_them) }));
	for (std::uint32_t f = 0; f < 14; ++f)
		if (f != COLLECTORS && owned(f))
			++fams;
	const bool coll = owned(COLLECTORS);
	auto score = [&](std::uint32_t fam) -> float
	{
		float v = static_cast<float>(EMB_TAB[10 + fam]) / 100.0f;
		if (fam != POWER && fam != BRUISER && owned(fam))
			return v - 100.0f; // never a second passive
		if (fam == MONSTER)
			v += 0.15f * (1.0f - fc) * sg;
		else if (fam == JUNGLE)
			v += 0.3f * c / std::max(0.1f, 1.0f - 0.3f * c) * sg;
		else if (fam == DURABILITY)
			v += 0.111f * sg;
		else if (fam == COLLECTORS)
			v += fams >= EMB_TAB[6] ? 0.01f * static_cast<float>(fams + 1) * sg : -50.0f;
		else if (fam == SKIRMISH)
			v += 0.01f * static_cast<float>(SKV_TAB[1]) * fc * sg; // Skirmish adds a percentage of champion damage: 5 on engine 2.0.0, 10 on 3.0.0
		else if (fam == TREASURE)
			v += 0.5f * static_cast<float>(EMB_TAB[3]) / 100.0f *
			     (static_cast<float>(rs::rules().treasure_pct) / static_cast<float>(100 + vesper_layer::gold_pct(&k))) * gr * rl / 30.0f;
		else if (fam == BRUISER)
			v += static_cast<float>(EMB_TAB[4]) / 100.0f;
		else if (fam == POWER)
			v += static_cast<float>(EMB_TAB[(focus_worth_less(k)) ? 4 : 5]) / 100.0f; // a converted Bruiser keeps its score
		if (coll && fam != COLLECTORS && fam != POWER && fam != BRUISER)
			v += 0.01f * sg;
		return v;
	};
	std::array<int, 16> pos{};
	std::array<float, 16> sc{};
	std::array<cambc::item_type, 16> it{};
	int m = 0;
	for (int j = 0; j < n; ++j)
	{
		const cambc::item_type t = build[static_cast<std::size_t>(idx[static_cast<std::size_t>(j)])];
		const std::uint32_t fam = static_cast<std::uint32_t>(t) / 6u;
		if (!rankable(fam) || counts[t] > 0)
			continue; // fixed slot, or a part-bought emblem
		pos[static_cast<std::size_t>(m)] = idx[static_cast<std::size_t>(j)];
		it[static_cast<std::size_t>(m)] = t;
		sc[static_cast<std::size_t>(m)] = score(fam);
		++m;
	}
	// Skirmish of the main stat replaces the weakest stat-only entry when it beats it (never planned or owned)
	if (emb_mstat < 2 && !owned(SKIRMISH) && std::none_of(build.begin(), build.end(), [](const cambc::item_type& t) { return static_cast<std::uint32_t>(t) / 6u == SKIRMISH; }))
	{
		int wk = -1;
		for (int j = 0; j < m; ++j)
		{
			const std::uint32_t fam = static_cast<std::uint32_t>(it[static_cast<std::size_t>(j)]) / 6u;
			if ((fam == POWER || fam == BRUISER) && (wk < 0 || sc[static_cast<std::size_t>(j)] < sc[static_cast<std::size_t>(wk)]))
				wk = j;
		}
		const float s = score(SKIRMISH);
		if (wk >= 0 && s > sc[static_cast<std::size_t>(wk)])
		{
			it[static_cast<std::size_t>(wk)] = cambc::item_type(SKIRMISH * 6u + static_cast<std::uint32_t>(emb_mstat) * 2u);
			sc[static_cast<std::size_t>(wk)] = s;
		}
	}
	if (m < 1)
		return;
	// stable selection sort by score, written back into the rankable slots
	std::array<int, 16> ord{};
	for (int j = 0; j < m; ++j)
		ord[static_cast<std::size_t>(j)] = j;
	std::stable_sort(ord.begin(), ord.begin() + m, [&](int x, int y) { return sc[static_cast<std::size_t>(x)] > sc[static_cast<std::size_t>(y)]; });
	for (int j = 0; j < m; ++j)
	{
		const cambc::item_type t = it[static_cast<std::size_t>(ord[static_cast<std::size_t>(j)])];
		const auto p = static_cast<std::size_t>(pos[static_cast<std::size_t>(j)]);
		if (build[p] != t)
			NLOG("r%d slot %d EMB slot %zu fam %u\n", now(), P.my_slot, p, static_cast<std::uint32_t>(t) / 6u);
		build[p] = t;
	}
}
// the first build entry of the Tribute family (7) whose emblem is not owned moves to the front.
template <class C>
static void tribute_emblem_to_front(const C& counts)
{
	for (std::size_t i = 0; i < build.size(); ++i)
	{
		const auto si = static_cast<std::uint32_t>(build[i]);
		if (si / 6 != 7)
			continue;
		if (static_cast<int>(counts[cambc::item_type(si + 1)]) >= 1 || i == 0)
			return;
		std::rotate(build.begin(), build.begin() + static_cast<std::ptrdiff_t>(i), build.begin() + static_cast<std::ptrdiff_t>(i) + 1);
		return;
	}
}
// walk the entries this visit can reach; a Greed entry about to get its first shard needs gold in hand + GRT_PCT % x gold rate x
// race rounds left >= 750, else it turns back into its 5 source entries (grt_orig).
void greed_gate(const decltype(cambc::self().item_count())& counts)
{
	std::array<int, 96> need{};
	int ord[3] = { 0, 0, 0 };
	int g = static_cast<int>(W.gold);
	for (int i = 0; i < static_cast<int>(build.size()) && g >= 30; ++i)
	{
		const std::uint32_t si = static_cast<std::uint32_t>(build[static_cast<std::size_t>(i)]);
		if (si + 1 >= need.size())
			continue;
		const bool gr = si / 6u == 12u;
		const std::uint32_t st = (si % 6u) / 2u;
		++need[si];
		if (static_cast<int>(counts[cambc::item_type(si + 1u)]) >= need[si])
		{
			if (gr && st < 3u)
				++ord[st];
			continue;
		}
		const int have = static_cast<int>(counts[cambc::item_type(si)]);
		if (gr && st < 3u)
		{
			if (have == 0)
			{
				const int r = std::max(1, now());
				auto left = [&](int trib) { return trib <= 0 ? GAME_END_F : static_cast<float>(1000 - trib) * static_cast<float>(r) / static_cast<float>(trib); };
				const float rl = std::max(0.0f, std::min({ static_cast<float>(GAME_END - r), left(W.tributed_us), left(W.tributed_them) }));
				const float proj = static_cast<float>(g) + static_cast<float>(GRT_TAB[2]) / 100.0f * static_cast<float>(emb_gold) / static_cast<float>(r) * rl;
				if (proj < 750.0f && ord[st] < grt_n[st])
				{
					const cambc::item_type src = grt_orig[st][ord[st]];
					for (int j = ord[st]; j + 1 < grt_n[st]; ++j)
						grt_orig[st][j] = grt_orig[st][j + 1];
					--grt_n[st];
					build[static_cast<std::size_t>(i)] = src;
					build.insert(build.begin() + i + 1, 4, src);
					--need[si];
					--i; // this slot again, as its source entry
					continue;
				}
			}
			++ord[st];
		}
		g -= 30 * std::max(0, (gr ? 25 : 5) - have);
	}
}
} // namespace nova::econ

// passive emblems before Greed: reached only when the late-Greed bit is set at the shop hook.
namespace nova::econ::emblem_order
{
static void fire_glate()
{
}
void passive_first(std::vector<cambc::item_type>& build, const decltype(cambc::self().item_count())& counts)
{
	constexpr std::uint32_t F_POWER = 1, F_BRUISER = 6, F_GREED = 12;
	auto passive = [](std::uint32_t fam) { return fam < 14u && fam != F_POWER && fam != F_BRUISER && fam != F_GREED; };
	auto fam_owned = [&](std::uint32_t fam)
	{
		for (std::uint32_t st = 0; st < 3u; ++st)
			if (counts[cambc::item_type(fam * 6u + st * 2u + 1u)] > 0)
				return true;
		return false;
	};
	const int n = static_cast<int>(build.size());
	for (int i = 0; i < n; ++i)
	{
		const std::uint32_t si = static_cast<std::uint32_t>(build[static_cast<std::size_t>(i)]);
		if (si / 6u != F_GREED || counts[cambc::item_type(si)] > 0 || counts[cambc::item_type(si + 1u)] > 0)
			continue;
		int at = i;
		for (int j = i + 1; j < n; ++j)
		{
			const cambc::item_type t = build[static_cast<std::size_t>(j)];
			const std::uint32_t fam = static_cast<std::uint32_t>(t) / 6u;
			if (!passive(fam) || fam_owned(fam))
				continue;
			build.erase(build.begin() + j);
			build.insert(build.begin() + at, t);
			++at;
			fire_glate();
		}
		return;
	}
}
} // namespace nova::econ::emblem_order
