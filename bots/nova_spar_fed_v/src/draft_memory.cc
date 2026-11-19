// draft_memory.cc: What the draft stores for the game.
#include "draft_internal.h"
#include "econ_linear_score.h"
namespace nova::drafting {
namespace {

// The stream is rebuilt only when the old image changes in a way that shows: its size, the EXACT_TRAVEL block, or a new extra. Picks
// and flags aren't stored; the other writers repeat the same bytes at every handoff. No fuel for a rebuild: the old image this turn,
// retried at the next.
std::vector<std::uint8_t> pk_out;
long pk_key = -1, pk_cost = 0;
void pack_and_submit_draft_memory()
{
	const std::size_t E = S.mem.size() > 13 ? 16 + 3 * (static_cast<std::size_t>(S.mem[10]) + S.mem[11]) : 0;
	const long key = static_cast<long>(S.mem.size()) * 64 + dmem::extras_count() * 2 + ((E && E < S.mem.size() && S.mem[E] == XT_MAGIC) ? 1 : 0);
	if (key != pk_key)
	{
		const long est = pk_cost > 0 ? 2 * pk_cost : 8000L + 40L * static_cast<long>(S.mem.size());
		if (fuel() >= est + 15000)
		{
			const long f0 = fuel();
			if (!dmem::pack(S.mem, pk_out))
			{
				if (dmem::blob_pending()) // The tail blob does not fit: pack without it.
				{
					dmem::plan_memory_blob_clear();
					if (!dmem::pack(S.mem, pk_out))
						pk_out.clear();
				}
				else
					pk_out.clear();
			}
			pk_key = key;
			pk_cost = std::max(pk_cost, f0 - fuel() - dmem::compact_encode_cost(false)); // The one-time encode is not a repack's cost.
		}
		else
			pk_out.clear(); // No fuel to rebuild: the old image holds everything (readers take it as version 1); retry next handoff.
	}
	if (pk_out.empty() && S.mem.size() < 1024) // BB8P: a short submit leaves the old bytes in place, so pad with zeros
	{
		std::vector<std::uint8_t> pad = S.mem;
		pad.resize(1024, 0);
		cambc::draft_memory = pad;
	}
	else if (pk_out.empty())
		cambc::draft_memory = S.mem;
	else
		cambc::draft_memory = pk_out;
}

// Frozen class; base stats per body 60 dps, 1000 HP, attackers killed by Str/HP, all living ones hitting. No heap.
int op_v = -1;
float op_load(const GroupI& g, int t)
{
	std::array<std::pair<float, float>, 48> a;
	const int n = static_cast<int>(g.att.size());
	if (n > 48)
		return 99.0f; // a bigger pack is a lock whatever the order
	float out = 0, dmg = 0;
	for (int i = 0; i < n; ++i)
	{
		a[static_cast<std::size_t>(i)] = g.att[static_cast<std::size_t>(i)];
		out += a[static_cast<std::size_t>(i)].second;
	}
	std::sort(a.begin(), a.begin() + n, [](const auto& x, const auto& y) { return x.second * y.first > y.second * x.first; });
	for (int i = 0; i < n; ++i)
	{
		dmg += out * a[static_cast<std::size_t>(i)].first / (static_cast<float>(t) * 60.0f);
		out -= a[static_cast<std::size_t>(i)].second;
	}
	return dmg / (static_cast<float>(t) * 1000.0f);
}
bool one_pack()
{
	if (op_v >= 0)
		return op_v != 0;
	if (!M.done())
		return false;
	const int t = team_size();
	long tot = 0, lock = 0, cheap = 0;
	int nlock = 0, dl = UNREACH, dc = UNREACH;
	bool boss = false;
	for (const auto& g : M.groups)
	{
		tot += g.gems;
		const float ld = op_load(g, t);
		if (ld >= 1.0f && g.gems > 0)
		{
			++nlock;
			lock += g.gems;
			dl = g.d_home;
			boss = g.n_mono + g.n_golem > 0;
		}
		else if (ld < 0.25f)
		{
			cheap += g.gold;
			if (g.gold > 0)
				dc = std::min<int>(dc, g.d_home);
		}
	}
	op_v = (nlock == 1 && !boss && 100 * lock >= 95 * tot && dl != UNREACH && dl >= 30 && cheap >= 400 && dc < dl) ? 1 : 0;
	return op_v != 0;
}
bool fxdr_hand_written = false; // The first handoff wrote bytes 736-766.
void handoff(const std::vector<champion_draft>& after)
{
	if (!M.done())
		return; // the champions compute the distances themselves
	if (S.mem.empty())
	{
		const long est = S.cost_encode > 0 ? S.cost_encode : 6000L + 220L * static_cast<long>(static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na));
		if (fuel() < est + 25000)
			return;
		const long f0 = fuel();
		S.mem = encode_draft_memory(after, S.flags);
		S.cost_encode = f0 - fuel();
	}
	else
	{
		S.mem[2] = static_cast<std::uint8_t>(after.size());
		for (std::size_t i = 0; i < 5; ++i)
			S.mem[4 + i] = i < after.size() ? static_cast<std::uint8_t>(after[i]) : 0xFF;
	}
	// The zone block (bytes 832-1023) once the draft has computed it (zone::draft_step after the pick).
	if (zone::ready() && (S.mem.size() < zone::BLOCK_END || S.mem[zone::BLOCK_AT] != zone::BLOCK_MAGIC))
		zone::write_block(S.mem);
	// The mode in byte 15 and the schedule block (bytes 800-831), current at every handoff.
	if (S.mem.size() > 15)
		S.mem[15] = strat::draft_choice();
	strat::write_block(S.mem);
	// write_plan's and om_write's bytes depend on M only (static once M.done()); S.mem keeps them from the first handoff, and no other
	// writer touches 736-766, so later handoffs skip both.
	const bool fxdr_l = fxdr_hand_written;
	if (!fxdr_l)
		prism::write_plan(S.mem); // Prism carry plan: bytes 736-759.
	travel_write(S.mem); // Exact travel: after the group/altar data, before 736.
	if (!fxdr_l)
		nova::econ::om_write(S.mem); // Bytes 760-766.
	fxdr_hand_written = true;
	{
		const bool on = one_pack();
		if (S.mem.size() > OP_MEM)
			S.mem[OP_MEM] = on ? 1 : 0;
		dmem::extra_put(OP_XID, on ? 1u : 0u, 1);
	}
	if (M.done())
	{
		static int fxdr_mcl = -1; // Depends on M only.
		if (fxdr_mcl < 0)
			fxdr_mcl = static_cast<int>(map_class_compute());
		dmem::extra_put(MCL_XID, static_cast<std::uint32_t>(fxdr_mcl), 8);
	}
	if (M.done()) // Computed once (camp pairs), kept for later handoffs.
	{
		static int mcl2 = -1;
		if (mcl2 < 0 && fuel() > 4500000) // the 10M first draft turn only (camp windows: 0.02-0.5M measured)
			mcl2 = static_cast<int>(compute_map_class_bits(team_size()));
		if (mcl2 >= 0)
			dmem::extra_put(DMF_MCL2_XID, static_cast<std::uint32_t>(mcl2), 16);
	}
	if (M.done()) // v642 LSP: the map features of the map-aware LNR constants (depend on M only)
	{
		static std::uint32_t lsp_v = 0;
		static bool lsp_have = false;
		if (!lsp_have)
		{
			lsp_v = lsp_map_pack(team_size());
			lsp_have = true;
		}
		dmem::extra_put(LSP_XID, lsp_v, 32);
	}
	dmem::build_tail_blob(4500000); // Keeps >= 4.5M of the 10M turn (the draft itself uses p99 4.04M).
	const long est = S.cost_submit > 0 ? S.cost_submit : 4000L + 16L * static_cast<long>(S.mem.size());
	if (fuel() < est + 15000)
		return;
	const long f0 = fuel();
	pack_and_submit_draft_memory();
	S.cost_submit = std::max(S.cost_submit, f0 - fuel() - dmem::compact_encode_cost(true)); // Nor the handoff's.
}


// Totals over the map's groups, camps and tiles; they depend on M only.
struct MapTotals
{
	long tot = 0, gold = 0, clu = 0, heavy = 0, nwall = 0, nhole = 0;
};
static __attribute__((always_inline)) inline MapTotals map_totals()
{
	MapTotals m;
	long& tot = m.tot;
	long& gold = m.gold;
	long& clu = m.clu;
	long& heavy = m.heavy;
	long& nwall = m.nwall;
	long& nhole = m.nhole;
	static bool fxdr_dsc_ok = false; // The totals below depend on M only.
	static long fxdr_dsc[6] = {};
	if (fxdr_dsc_ok)
	{
		tot = fxdr_dsc[0];
		gold = fxdr_dsc[1];
		clu = fxdr_dsc[2];
		heavy = fxdr_dsc[3];
		nwall = fxdr_dsc[4];
		nhole = fxdr_dsc[5];
	}
	else
	{
		for (const auto& g : M.groups)
		{
			float smax = 0;
			for (int ci : g.members)
				smax = std::max(smax, M.camps[static_cast<std::size_t>(ci)].str);
			tot += g.gems;
			gold += g.gold;
			if (smax >= 60.0f)
				heavy += g.gems;
		}
		for (const auto& cp : M.camps)
			if (cp.type == cambc::camp_type::gem_cluster)
				clu += 7;
		// the in-board set tiles of each chunk word, as bbforeach visits them
		const std::uint64_t* ww = M.walls.ptr();
		const std::uint64_t* hw = M.holes.ptr();
		for (int cy = 0; cy < G.ch; ++cy)
		{
			const int rows = std::min(8, G.h - cy * 8);
			const std::uint64_t rm = rows >= 8 ? ~0ull : ((1ull << (8 * rows)) - 1ull);
			for (int cx = 0; cx < G.cw; ++cx)
			{
				const int cols = std::min(8, G.w - cx * 8);
				const std::uint64_t cm = (cols >= 8 ? 0xFFull : ((1ull << cols) - 1ull)) * 0x0101010101010101ull;
				const std::uint64_t m = rm & cm;
				nwall += __builtin_popcountll(ww[cy * G.stride + cx] & m);
				nhole += __builtin_popcountll(hw[cy * G.stride + cx] & m);
			}
		}
		fxdr_dsc[0] = tot;
		fxdr_dsc[1] = gold;
		fxdr_dsc[2] = clu;
		fxdr_dsc[3] = heavy;
		fxdr_dsc[4] = nwall;
		fxdr_dsc[5] = nhole;
		fxdr_dsc_ok = true;
	}
	return m;
}

// Map feature f of a DSW / DXC cell band.
static __attribute__((always_inline)) inline long swap_feature(int f, const MapTotals& m, long area)
{
	const long tot = m.tot, gold = m.gold, clu = m.clu, heavy = m.heavy, nwall = m.nwall, nhole = m.nhole;
	auto pct = [](long a, long b) { return b > 0 ? static_cast<int>((200 * a + b) / (2 * b)) : 0; }; // round(100 a / b)
	switch (f)
	{
	case 1:
		return team_size();
	case 2:
		return area;
	case 3:
	{
		int s2s = UNREACH;
		if (M.has_home)
			bbforeach(M.enemy_spawn,
				[&](vec2 p)
				{
					for (const vec2 d : DIRS)
					{
						const vec2 q = p + d;
						if (inb(q) && !bbget(M.enemy_spawn, q))
							s2s = std::min(s2s, static_cast<int>(dfget(M.f_home, q)));
					}
				});
		return s2s == UNREACH ? 9999 : s2s + 1;
	}
	case 4:
		return static_cast<long>(static_cast<std::size_t>(M.na));
	case 5:
	{
		int altd = UNREACH;
		for (const auto& a : M.altars)
			if (a.d_home != UNREACH)
				altd = std::min(altd, static_cast<int>(a.d_home));
		return altd == UNREACH ? 9999 : altd;
	}
	case 6:
		return gold;
	case 7:
		return tot > 0 ? (100 * gold) / tot : 99999;
	case 8:
		return pct(clu, std::max(1L, tot));
	case 9:
		return pct(heavy, std::max(1L, tot));
	case 10:
		return static_cast<long>(static_cast<std::size_t>(M.ng));
	case 11:
		return pct(nhole, area);
	case 12:
		return pct(nwall, area);
	case 13:
		return tot;
	case 14:
	case 16:
	case 17:
	case 18:
	{
		int s2s = 2 * std::max(G.w, G.h);
		if (M.has_home)
			bbforeach(M.enemy_spawn,
				[&](vec2 p)
				{
					for (const vec2 d : DIRS)
					{
						const vec2 q = p + d;
						if (inb(q) && !bbget(M.enemy_spawn, q))
							s2s = std::min(s2s, static_cast<int>(dfget(M.f_home, q)));
					}
				});
		const float mt = std::max(4.0f, 0.12f * static_cast<float>(s2s));
		float own = 0.0f, mid = 0.0f;
		long gmid = 0;
		for (const auto& g : M.groups)
		{
			if (g.respawn <= 0 || (g.d_home == UNREACH && g.d_enemy == UNREACH))
				continue;
			const float rate = static_cast<float>(g.gems) / static_cast<float>(g.respawn);
			if (g.d_home == UNREACH)
				continue;
			if (g.d_enemy == UNREACH || static_cast<float>(g.d_enemy) - static_cast<float>(g.d_home) > mt)
				own += rate;
			else if (static_cast<float>(g.d_home) - static_cast<float>(g.d_enemy) <= mt)
			{
				mid += rate;
				gmid += g.gems;
			}
		}
		if (f == 16)
			return pct(gmid, std::max(1L, tot));
		if (f == 18)
		{
			for (const auto& a : M.altars)
				if (a.d_home != UNREACH && (a.d_enemy == UNREACH || static_cast<float>(a.d_enemy) - static_cast<float>(a.d_home) > mt))
					return 0;
			return 1;
		}
		const float r = f == 14 ? own + 0.5f * mid : own;
		return r > 0.25f ? static_cast<long>(1000.0f / r) : 4000;
	}
	case 15:
	{
		long hg = 0;
		for (const auto& g : M.groups)
			if (g.n_mono > 0 || g.n_golem > 0)
				hg += g.gems;
		return pct(hg, std::max(1L, tot));
	}
	default:
		return 0;
	}
}

// The first enabled cell k in [k0, k1) of tab whose band holds and whose FROM is fielded while its TO is not; its code, else 0.
static __attribute__((always_inline)) inline int first_applicable_cell(std::uint16_t eff, bool pzv, int k0, int k1, const volatile int* tab, const MapTotals& m, long area)
{
	const int mask = tab[1];
	for (int k = k0; k < k1; ++k)
	{
		if (!(mask >> k & 1))
			continue;
		if (k >= 2 && k <= 5 && one_pack())
			continue; // Keep Vesper.
		const volatile int* c = &tab[2 + 7 * k];
		bool ok = c[0] != 0;
		for (int j = 0; j < 2 && ok; ++j)
		{
			const int f = c[1 + 3 * j];
			if (f <= 0)
				continue;
			const long v = swap_feature(f, m, area);
			ok = v >= c[2 + 3 * j] && v <= c[3 + 3 * j];
		}
		if (ok)
		{
			// The cell applies only where the fielded lineup holds FROM and lacks TO; else the next cell is tried.
			int code = c[0];
			if (tab == DSW_TAB && k == 3 && team_size() == 3) // Cell 3 retargets on 3-body maps.
			{ // kept as is where the new TO is already fielded (else the cascade falls through to the next cell)
				const int t2 = (D3T_TAB[1] >> 4 & 15) - 1;
				if (!((eff >> t2 & 1)))
					code = D3T_TAB[1];
			}
			const int from = (code & 15) - 1, to = (code >> 4 & 15) - 1;
			const bool hf = from >= 0 && from < NC && ((eff >> from & 1) || (from == PR && pzv));
			const bool ht = to >= 0 && to < NC && ((eff >> to & 1) || (to == PR && pzv));
			if (hf && !ht && !dash_term_keeps(from, to))
				return code;
		}
	}
	return 0;
}
} // namespace
// The swap code of the first enabled DSW cell whose band holds on this map and whose FROM is in the lineup we would field (eff; pzv:
// Prism viable) while its TO is not, else 0. Map features only, enemy picks never read.
int draft_swap_cell_code(std::uint16_t eff, bool pzv, int k0 = 0, int k1 = DSW_N, const volatile int* tab = DSW_TAB)
{
	if (!M.done())
		return 0;
	const MapTotals m = map_totals();
	const long area = static_cast<long>(G.w) * G.h;
	return first_applicable_cell(eff, pzv, k0, k1, tab, m, area);
}

// DXS (draft_flags.h): does Prism stay against the DXC cell 0 swap to Ryth? Called only behind DXS_ON(1).
bool dxs_keep_prism(std::uint16_t eff)
{
	const long f16 = swap_feature(16, map_totals(), static_cast<long>(G.w) * G.h);
	const float p = std::min(1.0f, std::max(0.0f, static_cast<float>(f16 - DXS_TAB[4]) / static_cast<float>(std::max(1, DXS_TAB[5] - DXS_TAB[4]))));
	return lineup_value(eff) + 0.1f * static_cast<float>(DXS_TAB[2]) - 0.1f * static_cast<float>(DXS_TAB[3]) * p >= lineup_value((eff & ~bit(PR)) | bit(RY));
}
} // namespace nova::drafting
