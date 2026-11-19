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
static float emd_jprior = 0; // EMD: Jungle's camp damage per round before hits (map's mean camp Str, tank rank)
static float emd_cgem = 0; // EMD bit 1: the gem-cluster share of reachable camp gems, Prospector's prior band
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
	else strat::policy_of(strat::BASE).item_plan(k, stat, healer); // b1976 SMZ bit 2: a Mode with no item plan keeps BASE's build
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
			// MNR bit 4 IT1 (RC X398): the shop fills a type's entries in order (need[] occurrences), so with k emblems of it owned the
			// part-bought one is occurrence k + 1: move the first k + 1 entries to the front. Fewer entries: as before.
			const int k = static_cast<int>(counts[cambc::item_type(i + 1)]);
			if (k > 0 && static_cast<int>(std::count_if(build.begin(), build.end(), same)) > k)
			{
				int left = k + 1;
				std::size_t w = 0;
				for (std::size_t r = 0; r < build.size(); ++r)
					if (left > 0 && same(build[r]))
						--left;
					else
						build[w++] = build[r];
				build.resize(w);
				build.insert(build.begin(), static_cast<std::size_t>(k + 1), cambc::item_type(i));
				continue;
			}
			const auto it = std::find_if(build.begin(), build.end(), same);
			if (it != build.end())
				build.erase(it);
			itm_insert_at(0, cambc::item_type(i));
		}
	}
	catch (...)
	{
		FXR_PASS();
	}
}
void prism_carrier_shop_build(); // her Health build
// is this kit's Focus worth less than PWL_FMIN % of Strength (its Strength emblems take Power)?
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
		if (itm_family(t) == I_BRUISER && itm_stat(t) == 0)
			t = itm_shard(I_POWER, itm_stat(t));
}
bool vgt_nogreed = false; // VGT bit 1: set only inside vgt_tail_pass (Vesper's own build)
void greed_tail_pass(const Kit& k)
{
	grt_n[0] = grt_n[1] = grt_n[2] = 0;
	if (willow_layer::shop_skip_grt(k) || prism_layer::shop_skip_grt() || tavi_layer::shop_skip_grt())
		return;
	constexpr std::uint32_t POWER = 1, GREED = 12;
	std::vector<cambc::item_type> out;
	out.reserve(build.size());
	std::array<int, 96> run{};
	bool skg_need = false; // SKG: no Skirmish planned, owned or part-bought
	{
		constexpr std::uint32_t SKIRMISH = 11;
		skg_need = std::none_of(build.begin(), build.end(), [](const cambc::item_type& t) { return static_cast<std::uint32_t>(t) / 6u == SKIRMISH; });
		try
		{
			const auto counts = cambc::self().item_count();
			for (std::uint32_t i = SKIRMISH * 6u; i < SKIRMISH * 6u + 6u && skg_need; ++i)
				skg_need = counts[cambc::item_type(i)] == 0;
		}
		catch (...)
		{
			FXR_PASS();
			skg_need = false;
		}
	}
	for (const auto& t : build)
	{
		const std::uint32_t si = static_cast<std::uint32_t>(t), fam = si / 6u, st = (si % 6u) / 2u;
		bool conv = false;
		if (si < 84u && st < 3u)
		{
			if (fam == POWER)
				conv = true;
		}
		if (skg_need && conv && fam == POWER && run[si] == 0 && grt_n[st] < 24)
		{
			out.push_back(cambc::item_type(11u * 6u + st * 2u)); // SKG: this entry is Skirmish, the Greed runs start after it
			skg_need = false;
			continue;
		}
		if (conv && run[si] == 0)
		{
			if (grt_n[st] >= 24 || vgt_nogreed) // VGT bit 1: no Greed entry for her
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
// VGT bit 2: her Bruiser main entries, which bruiser_to_power_emblems turned into Power (so upitm_post's late families and the
// Skirmish slot sit as live), go back to Bruiser. make_build writes no Power main entry of its own for her.
void vgt_keep_bruiser()
{
	for (auto& t : build)
		if (itm_family(t) == I_POWER && itm_stat(t) == 0)
			t = itm_shard(I_BRUISER, 0);
}
// VGT (b1789, spec_vgt_1110): Vesper's tail without Greed (greed_tail_pass with its Skirmish rule only); bit 2 keeps her Bruiser.
void vgt_tail_pass(const Kit& k)
{
	vgt_nogreed = true;
	greed_tail_pass(k);
	vgt_nogreed = false;
	vgt_keep_bruiser();
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
	// Main damage stat: whichever adds more per shard (a heal counts toward Focus through heal_mod).
	const float str_value = k.str_g * (static_cast<float>(rs::slot_cooldown()) + (k.slot_reset >= 0 ? 1.0f : 0.0f)) / static_cast<float>(rs::slot_cooldown()) * (varg_layer::shop_str(k) ? 1.5f : 1.0f);
	const float foc_value = k.foc_g *
		(k.dmg_mod + k.cc_mod + 1.5f * k.aoe_mod + 1.5f * k.dash_mod + 0.6f * k.shield_mod + 1.0f * k.heal_mod) / 8.0f;
	int stat = (foc_value > str_value) ? 1 : 0; // 0 strength, 1 focus
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
	// captures, solo wolves and elks) and kills. Order: Treasure, Bruiser main, Durability Health, Monster main, then Bruiser main,
	// Bruiser main, Power Health repeated (bruiser_to_power_emblems and the passes after it may rewrite the tail).
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
		vgt_tail_pass(k);
		build_ready = true;
		return;
	}
	// Treasure (+10% gold in 2.0.0, GameRules.md:308) first. It pays back after 1,500 gold earned (champions earn ~1,400-1,700 a game)
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
	if (CI2_FARM()) // CI2 decision 8: the pair's own lists
		nova::ci2::build_pass();
	else if (ci_layer::type(W.me.type)) // C&I builds go last, so the emblem rank's pin and the Bruiser tail keep them
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
		FXR_PASS();
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
// v638 EMD bit 1: my own rates for the emblem values, once per alive round (caller reads the flag).
static struct
{
	int last = -1, pgold = 0, pgems = 0, gems = 0, uncov = 0, capg = -1, capr = -1000, recalls = 0, tribs = 0, bags = 0, kills = 0, farm = 0,
		lastfight = -1000, deaths = 0, dbag = 0, nrw = 0;
	float rwv = 0, clu = 0, fdmg = 0, lasthp = 0, lastmax = 1, dshare = 0;
	vec2 ppos{ -1, -1 };
	bool ptri = false;
} emd;
// v663 BB29 DK2 (b1776, called with the bit on): a >= 90 gold gain on a camp tile right after a fight, with no capture of the tile's
// group in the last 2 rounds, is kill gold (100 base) and not a capture reward.
void bb29_fc_dk2()
{
}
void bb29_fc_ev1()
{
}
// EV1 (called with the bit on): a turn at distance 5 is a fight turn too, as emb_hp_ch counts its HP loss.
bool bb29_ev1(int dmin)
{
	if (dmin != 5)
		return false;
	bb29_fc_ev1();
	return true;
}
bool bb29_dk2_kill(int ci, int dg, int since_fight)
{
	if (dg < 90 || since_fight > 3)
		return false;
	const int gi = M.camps[static_cast<std::size_t>(ci)].group;
	if (gi >= 0 && gi < M.ng && static_cast<std::size_t>(gi) < mem.size())
	{
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.status == GS_RESPAWN && m.respawn_at - M.groups[static_cast<std::size_t>(gi)].respawn >= now() - 2)
			return false; // a capture of this group just paid
	}
	bb29_fc_dk2();
	return true;
}
static __attribute__((noinline)) void emd_observe(int dmin)
{
	auto& e = emd;
	const int r = now(), gems = static_cast<int>(W.me.gems);
	if (e.last >= 0 && r - e.last >= 55)
	{
		// a death between my turns (respawn: 60 rounds); in a fight when a foe was within 5 in my last 10 alive rounds
		if (e.lastfight >= e.last - 10)
		{
			++e.deaths;
			e.dshare += (e.fdmg + e.lasthp) / std::max(1.0f, e.lastmax);
			e.dbag += e.pgems;
		}
		e.fdmg = 0;
	}
	else if (e.last >= 0)
	{
		const int dg = emb_gold - e.pgold, dge = std::max(0, gems - e.pgems);
		e.gems += dge;
		const int ci = (XIB_ON(256) && !(dg > 0 || dge > 0)) ? -1 : M.camp_index(e.ppos); // v726 XIB EMC1: read only where the test needs it
		if (ci >= 0 && (dg > 0 || dge > 0) && !(bb29_dk2_kill(ci, dg, r - e.lastfight))) // v663 BB29 DK2
		{
			// a capture reward: the group's cluster share of its value (gem cluster 7 gems, gold cluster 20 gold)
			const int gi = M.camps[static_cast<std::size_t>(ci)].group;
			++e.nrw;
			e.rwv += static_cast<float>(dg + 2 * dge);
			if (gi >= 0 && gi < M.ng)
			{
				const auto& g = M.groups[static_cast<std::size_t>(gi)];
				float cv = 0;
				for (const int m : g.members)
					if (m >= 0 && m < M.nc)
					{
						const auto t = M.camps[static_cast<std::size_t>(m)].type;
						cv += t == cambc::camp_type::gem_cluster ? 14.0f : t == cambc::camp_type::gold_cluster ? 20.0f : 0.0f;
					}
				const float tv = static_cast<float>(g.gold + 2 * g.gems);
				if (cv > 0 && tv > 0)
					e.clu += static_cast<float>(dg + 2 * dge) * std::min(1.0f, cv / tv);
			}
		}
		else if (dg >= 90 && r - e.lastfight <= 3)
			++e.kills; // kill gold (100 base) right after a fight
	}
	if (dmin <= 5)
	{
		if (r - e.lastfight > 10)
			e.fdmg = 0; // a new fight episode
		e.lastfight = r;
	}
	if (emb_php >= 0 && emb_pr == r - 1 && !W.on_spawn && W.me.hp < emb_php && r - e.lastfight <= 10)
		e.fdmg += emb_php - W.me.hp;
	// a recall arrival (a lazy recall start is restarted every turn, so count the jump onto the spawn, not the channel)
	const bool tri = (W.me.state & ST_TRIBUTE) != 0;
	if (e.last >= 0 && r - e.last < 55 && W.on_spawn && cheb(e.ppos, W.me.pos) > 4)
		++e.recalls;
	if (tri && !e.ptri)
	{
		++e.tribs;
		e.bags += e.pgems;
	}
	// a capture I am at from its start with no holder: the engine's timer still above the holder cap of 3
	const int cn = M.camp_index(W.me.pos);
	if (cn >= 0)
	{
		const int gi = M.camps[static_cast<std::size_t>(cn)].group;
		if (gi >= 0 && gi < M.ng && (gi != e.capg || r - e.capr > 8))
		{
			cambc::detail::camp_group_capture_state cs{};
			if (cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs) == 0 && cs.state == 1)
			{
				e.capg = gi;
				e.capr = r;
				if (cs.timer >= 4)
					++e.uncov;
			}
		}
	}
	if (dmin > 4)
		for (const auto& c : W.camps)
			if (c.awake && c.ci >= 0 && c.ci < M.nc && cheb(M.camps[static_cast<std::size_t>(c.ci)].pos, W.me.pos) <= 3)
			{
				++e.farm;
				break;
			}
	e.last = r;
	e.pgold = emb_gold;
	e.pgems = gems;
	e.ppos = W.me.pos;
	e.ptri = tri;
	e.lasthp = W.me.hp;
	e.lastmax = W.me.maxhp;
}
__attribute__((noinline)) void emblem_observe_slow()
{
	int dmin = 1000;
	for (const auto& en : W.enemies)
		dmin = std::min(dmin, cheb(en.pos, W.me.pos));
	emd_observe(dmin);
	++emb_turns;
	if (dmin <= 4 || bb29_ev1(dmin)) // v663 BB29 EV1: fight turns at the HP-loss distance (5)
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
	int gm = 0, cg = 0;
	for (const auto& g : M.groups)
	{
		if (g.d_home == UNREACH)
			continue;
		gm += g.gems;
		for (const int ci : g.members)
			if (ci >= 0 && ci < M.nc && M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gem_cluster)
				cg += 7;
	}
	emd_cgem = gm > 0 ? std::min(1.0f, static_cast<float>(cg) / static_cast<float>(gm)) : 0.0f;
	float s = 0;
	int na = 0;
	for (const auto& c : M.camps)
		if (c.str > 0.0f)
		{
			s += c.str;
			++na;
		}
	const bool tank = P.my_slot >= 0 && P.tank_order[static_cast<std::size_t>(P.my_slot)] == 0;
	emd_jprior = (na > 0 ? s / static_cast<float>(na) : 0.0f) * static_cast<float>(EMD_TAB[2]) / 100.0f * (tank ? static_cast<float>(EMD_TAB[3]) / 100.0f : 1.0f);
}
// EMD bit 1 cold-start priors: the bot's own measured kit rates to r300 (b1745 firing, 298 fresh maps; kits by champion_type id,
// Stellar and Tavi unmeasured: the pooled value). Fight turns per round, kills and deaths per fight turn, uncovered captures at start,
// tribute starts and farm turns per round, champion damage taken per fight turn, gems gained per round.
static constexpr float EMD_FT[13] = { .108f, .102f, .069f, .079f, .070f, .09f, .043f, .089f, .200f, .068f, .053f, .09f, .085f };
static constexpr float EMD_KL[13] = { .0050f, .0082f, .0101f, .0080f, .0030f, .0075f, .0513f, .0065f, .0012f, .0069f, .0066f, .0075f, .0075f };
static constexpr float EMD_DT[13] = { .0124f, .0051f, .0092f, .0225f, .0226f, .010f, .0235f, .0080f, .0163f, .0172f, .0092f, .010f, .0114f };
static constexpr float EMD_UC[13] = { .0123f, .0116f, .0188f, .0098f, .0232f, .014f, .0205f, .0134f, .0026f, .0140f, .0143f, .014f, .0128f };
static constexpr float EMD_TR[13] = { .0022f, .0024f, .0053f, .0055f, .0059f, .003f, .0005f, .0037f, .0002f, .0028f, .0029f, .003f, .0016f };
static constexpr float EMD_FM[13] = { .222f, .193f, .216f, .128f, .210f, .22f, .132f, .227f, .078f, .206f, .270f, .22f, .256f };
static constexpr float EMD_CH[13] = { 35.7f, 22.7f, 34.4f, 14.6f, 33.5f, 32.0f, 36.0f, 31.8f, 15.2f, 35.8f, 25.1f, 32.0f, 32.4f };
static constexpr float EMD_GM[13] = { .084f, .104f, .254f, .351f, .269f, .2f, .964f, .187f, .007f, .095f, .142f, .2f, .082f };
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
	float fc0 = 0, gr0 = 0; // EMD bit 1: the priors before blending
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
		fc0 = EMD_FT[ti]; // fight turns per round: the kit's measured rate (the AF shares run about 2x)
		gr0 = gr;
	}
	const float nt = static_cast<float>(emb_turns), w = nt / (nt + static_cast<float>(std::max(1, static_cast<int>(EMB_TAB[2]))));
	if (emb_turns > 0)
		fc = (1 - w) * fc + w * static_cast<float>(emb_fturns) / nt;
	const float lost = emb_hp_ch + emb_hp_camp;
	if (lost > 0)
		c = (1 - w) * c + w * emb_hp_camp / lost;
	const int r = std::max(1, now());
	gr = (1 - w) * gr + w * static_cast<float>(emb_gold) / static_cast<float>(r);
	auto left = [&](int trib) { return trib <= 0 ? GAME_END_F : static_cast<float>(rs::WIN_TRIBUTE - trib) * static_cast<float>(r) / static_cast<float>(trib); };
	rl = std::max(0.0f, std::min({ static_cast<float>(GAME_END - r), left(W.tributed_us), left(W.tributed_them) }));
	for (std::uint32_t f = 0; f < 14; ++f)
		if (f != COLLECTORS && owned(f))
			++fams;
	const bool coll = owned(COLLECTORS);
	// v638 EMD bit 1 (emblem_plan_1108 S1): rate x rounds left after completion, gold + 2 x gems; fight families on fight rounds
	struct
	{
		float w1 = 0, wf = 0, gr1 = 0, inc = 0, lc = 0, efr = 0, fr = 0, ft = 0, cyc = 25, cdr = 0, rph = 0;
		std::size_t ti = 5;
	} q;
	{
		const int emt = static_cast<int>(W.me.type);
		q.ti = static_cast<std::size_t>(emt >= 0 && emt < 13 ? emt : 5);
		const float rf = static_cast<float>(r), prn = static_cast<float>(std::max(1, static_cast<int>(EMD_TAB[5])));
		q.w1 = nt / (nt + prn);
		q.ft = static_cast<float>(emb_fturns);
		q.wf = q.ft / (q.ft + std::max(1.0f, 0.2f * prn));
		q.gr1 = (1 - q.w1) * gr0 + q.w1 * static_cast<float>(emb_gold) / rf;
		const float gem0 = EMD_GM[q.ti];
		q.inc = q.gr1 + 2.0f * ((1 - q.w1) * gem0 + q.w1 * static_cast<float>(emd.gems) / rf);
		q.lc = std::max(0.0f, rl - std::max(0.0f, 150.0f - static_cast<float>(W.gold)) / std::max(0.3f, q.gr1));
		q.fr = (1 - q.w1) * fc0 + q.w1 * (nt > 0 ? q.ft / nt : 0.0f);
		q.efr = q.fr * q.lc * (r - emd.lastfight <= 50 ? static_cast<float>(EMD_TAB[7]) / 100.0f : 1.0f);
		const float walk = P.s2s > 0 ? std::clamp(static_cast<float>(P.s2s) * static_cast<float>(EMD_TAB[4]) / 100.0f, 6.0f, 40.0f) : 20.0f;
		q.cyc = static_cast<float>(rs::recall_rounds(owned(5), false)) + walk;
		// recall rounds per HP lost: one recall cycle per HP lost per recall (measured ~800 for tanks, b1745), then my own
		const float nrc = static_cast<float>(emd.recalls), hpr = nrc > 0 ? (emb_hp_ch + emb_hp_camp) / nrc : 800.0f;
		q.rph = q.cyc / std::max(200.0f, (3.0f * 800.0f + nrc * hpr) / (3.0f + nrc));
		q.cdr = (1 - q.w1) * emd_jprior + q.w1 * (nt > 0 ? emb_hp_camp / nt : 0.0f);
	}
	auto emd_value = [&](std::uint32_t fam) -> float // gold + 2 x gems over the rounds left (bit 1)
	{
		constexpr std::uint32_t HOME = 5, TRIBUTE = 7, CAPTURE = 8, PROSPECTOR = 9, HUNTER = 10;
		const float rf = static_cast<float>(r), a = 1 - q.w1, b = q.w1, af = 1 - q.wf, bf = q.wf;
		switch (fam)
		{
		case MONSTER: // 15% more camp damage = 13% fewer farm turns, each worth a round of income
			return 0.13f * (a * EMD_FM[q.ti] + b * (nt > 0 ? static_cast<float>(emd.farm) / nt : 0.0f)) * q.inc * q.lc;
		case TREASURE:
			return static_cast<float>(rs::rules().treasure_pct) / static_cast<float>(100 + vesper_layer::gold_pct(&k)) * q.gr1 * q.lc;
		case PROSPECTOR:
		{
			// Econ's realised rows by the map's gem-cluster share (section 8), then 25% of my own reward income's cluster share,
			// weighted by rewards seen (a body with no cluster capture yet keeps the prior)
			const float band = emd_cgem < 0.15f ? 0.10f : emd_cgem < 0.35f ? 0.16f : 0.22f;
			const float kf = W.me.type == cambc::champion_type::vesper_vale ? 1.5f : W.me.type == cambc::champion_type::marcella ? 0.8f : 1.0f;
			const float own = emd.rwv > 0 ? 0.25f * q.inc * emd.clu / emd.rwv : 0.0f, n = static_cast<float>(emd.nrw);
			return (6.0f * band * kf + n * own) / (6.0f + n) * q.lc;
		}
		case CAPTURE: // 2 rounds on captures I am at from the start with no holder, .7 of them turned into work (a flat 2; GR:313 caps the timer at 3, so a join at timer t saves t - 3: CPU1, closed 10 Nov)
			return 1.4f * (a * EMD_UC[q.ti] + b * static_cast<float>(emd.uncov) / rf) * q.inc * q.lc;
		case HOME: // from my own recalls only, once I have made 2 (Planner: no Home from the prior alone)
			return emd.recalls >= 2 ? 2.0f * static_cast<float>(emd.recalls) / rf * q.inc * q.lc : 0.0f;
		case TRIBUTE:
		{
			const float tr = a * EMD_TR[q.ti] + b * static_cast<float>(emd.tribs) / rf;
			const float bag = (80.0f + static_cast<float>(emd.bags)) / (2.0f + static_cast<float>(emd.tribs));
			const int bg = static_cast<int>(bag);
			return static_cast<float>(rs::tribute_turns(bg, false) - rs::tribute_turns(bg, true)) * tr * q.inc * q.lc;
		}
		case DURABILITY:
		{
			const float chf = af * EMD_CH[q.ti] + bf * (q.ft > 0 ? emb_hp_ch / q.ft : 0.0f);
			float v = 0.10f * (q.cdr * q.lc + chf * q.efr) * q.rph * q.inc;
			const float dpf = af * EMD_DT[q.ti] + bf * (q.ft > 0 ? static_cast<float>(emd.deaths) / q.ft : 0.0f);
			const float dn = 2.0f + static_cast<float>(emd.deaths);
			const float dsh = (2.0f + emd.dshare) / dn, bagv = 2.0f * (40.0f + static_cast<float>(emd.dbag)) / dn;
			v += 0.10f * dsh * dpf * (bagv + static_cast<float>(rs::rules().respawn) * q.inc) * q.efr;
			return v;
		}
		case HUNTER:
			return static_cast<float>(rs::rules().hunter_gold) * (af * EMD_KL[q.ti] + bf * (q.ft > 0 ? static_cast<float>(emd.kills) / q.ft : 0.0f)) * q.efr;
		case SKIRMISH: // a share of my champion damage per fight round, at 100 gold per 1,500 HP
			return static_cast<float>(SKV_TAB[1]) / 100.0f * 0.5f * combat::body_dps(W.me) / 1500.0f * 100.0f * q.efr;
		default:
			return 0.0f;
		}
	};
	auto score = [&](std::uint32_t fam) -> float
	{
		float v = static_cast<float>(EMB_TAB[10 + fam]) / 100.0f;
		if (fam != POWER && fam != BRUISER && owned(fam))
			return v - 100.0f; // never a second passive
		if (fam == POWER || fam == BRUISER)
		{
			// stat-only: the fixed weight, scaled by my expected fight rounds against the prior's
			const float base = fam == BRUISER ? static_cast<float>(EMB_TAB[4]) / 100.0f : static_cast<float>(EMB_TAB[(focus_worth_less(k)) ? 4 : 5]) / 100.0f;
			const float f = std::clamp(q.efr / std::max(1.0f, fc0 * q.lc), 0.0f, 2.0f);
			// v7xx MBB11 COL1 (INT:59, BalanceChanges.md:1243): with Collectors owned, a first Power or Bruiser adds a family (+1%).
			if (coll && !owned(fam))
				return v + base * (0.5f + 0.5f * f) + 0.01f * sg;
			return v + base * (0.5f + 0.5f * f);
		}
		if (fam == JUNGLE) // bit 2's absolute camp term in bit 1's units: income and rounds after completion, measured HP per recall
			return v + static_cast<float>(EMD_TAB[6]) / 100.0f * 0.3f * q.cdr * q.lc * q.rph * q.inc / 30.0f + (coll ? 0.01f * sg : 0.0f);
		if (fam != JUNGLE && fam != COLLECTORS)
			return v + static_cast<float>(EMD_TAB[6]) / 100.0f * emd_value(fam) / 30.0f + (coll ? 0.01f * sg : 0.0f);
		if (fam == COLLECTORS) // MONSTER, JUNGLE and DURABILITY returned above (dead branches baked out, spec_mjp_1109)
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
	auto emd_rankable = [&](std::uint32_t fam) // bit 1: every family but Greed; Prospector's map gate holds for 20 turns
	{
		constexpr std::uint32_t TRIBUTE = 7, PROSPECTOR = 9, GREED = 12;
		return fam < 14u && fam != GREED && (fam != PROSPECTOR || nt >= 20.0f) && (fam != TRIBUTE || !prism_layer::shop_wbt());
	};
	std::array<int, 16> pos{};
	std::array<float, 16> sc{};
	std::array<cambc::item_type, 16> it{};
	int m = 0;
	// bit 1: every family but Greed is ranked (the live loop below is skipped)
	for (int j = 0; j < n; ++j)
	{
		const cambc::item_type t = build[static_cast<std::size_t>(idx[static_cast<std::size_t>(j)])];
		const std::uint32_t fam = static_cast<std::uint32_t>(t) / 6u;
		if (!emd_rankable(fam) || counts[t] > 0)
			continue; // fixed slot, or a part-bought emblem
		pos[static_cast<std::size_t>(m)] = idx[static_cast<std::size_t>(j)];
		it[static_cast<std::size_t>(m)] = t;
		sc[static_cast<std::size_t>(m)] = score(fam);
		++m;
	}
	n = 0;
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
	// v698 FUE1: the families in the build (unchanged below) and, after the Skirmish swap, in the ranked entries, as bit masks
	std::uint32_t fue_bm = 0;
	for (const auto& t : build)
		if (static_cast<std::uint32_t>(t) / 6u < 32u)
			fue_bm |= 1u << (static_cast<std::uint32_t>(t) / 6u);
	// bit 1: a passive family the build lacks (never planned, owned or part-bought) replaces the weakest stat-only entry it
	// beats, in that entry's stat; best family first
	constexpr std::uint32_t CAND[6] = { 9, 5, 10, 11, 8, 7 }; // Prospector, Home, Hunter, Skirmish, Capture, Tribute
	std::array<float, 6> cs{};
	std::array<bool, 16> took{};
	std::uint32_t fue_im = 0;
	for (int j = 0; j < m; ++j)
		if (static_cast<std::uint32_t>(it[static_cast<std::size_t>(j)]) / 6u < 32u)
			fue_im |= 1u << (static_cast<std::uint32_t>(it[static_cast<std::size_t>(j)]) / 6u);
	for (std::size_t ci = 0; ci < 6; ++ci)
	{
		const std::uint32_t fam = CAND[ci];
		bool absent = emd_rankable(fam) && !owned(fam);
		for (std::uint32_t st = 0; st < 3u && absent; ++st)
			absent = counts[cambc::item_type(fam * 6u + st * 2u)] == 0;
		if (absent)
			absent = (((fue_bm | fue_im) >> fam) & 1u) == 0; // v698 FUE1
		cs[ci] = absent ? score(fam) : -1000.0f;
	}
	for (int pass = 0; pass < 6; ++pass)
	{
		int bi = -1;
		for (int ci = 0; ci < 6; ++ci)
			if (cs[static_cast<std::size_t>(ci)] > -1000.0f && (bi < 0 || cs[static_cast<std::size_t>(ci)] > cs[static_cast<std::size_t>(bi)]))
				bi = ci;
		if (bi < 0)
			break;
		int wk = -1;
		for (int j = 0; j < m; ++j)
		{
			const std::uint32_t fam = static_cast<std::uint32_t>(it[static_cast<std::size_t>(j)]) / 6u;
			if (!took[static_cast<std::size_t>(j)] && (fam == POWER || fam == BRUISER) && (wk < 0 || sc[static_cast<std::size_t>(j)] < sc[static_cast<std::size_t>(wk)]))
				wk = j;
		}
		if (wk < 0 || cs[static_cast<std::size_t>(bi)] <= sc[static_cast<std::size_t>(wk)])
			break;
		const std::uint32_t st = (static_cast<std::uint32_t>(it[static_cast<std::size_t>(wk)]) % 6u) / 2u;
		it[static_cast<std::size_t>(wk)] = cambc::item_type(CAND[bi] * 6u + st * 2u);
		sc[static_cast<std::size_t>(wk)] = cs[static_cast<std::size_t>(bi)];
		took[static_cast<std::size_t>(wk)] = true;
		cs[static_cast<std::size_t>(bi)] = -1000.0f;
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
// MNR bit 8 GRT1 (RC X399 HZ2): rounds left from the leader's tribute pace, tribute ~ r^1.7 (gems snowball; the straight-line pace runs
// ~2.3x long). The faster side ends the game (GR:29); before any tribute the median 850 rounds left, capped at the r2000 end (GR:31).
static float grt1_rounds_left(int r)
{
	const int t = std::max(W.tributed_us, W.tributed_them);
	const float cap = static_cast<float>(std::max(0, GAME_END - r));
	if (t >= rs::WIN_TRIBUTE)
		return 0.0f;
	if (t <= 0)
		return std::min(cap, 850.0f);
	const float e = static_cast<float>(r) * (std::pow(static_cast<float>(rs::WIN_TRIBUTE) / static_cast<float>(t), 1.0f / 1.7f) - 1.0f);
	return std::max(0.0f, std::min(cap, e));
}
void greed_gate(const decltype(cambc::self().item_count())& counts)
{
	if (grt_n[0] == 0 && grt_n[1] == 0 && grt_n[2] == 0)
		return; // v683 FB27: nothing to turn back (the loop only reads)
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
				auto left = [&](int trib) { return trib <= 0 ? GAME_END_F : static_cast<float>(rs::WIN_TRIBUTE - trib) * static_cast<float>(r) / static_cast<float>(trib); };
				const float rl = grt1_rounds_left(r);
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
