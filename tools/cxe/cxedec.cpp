// cxedec.cpp - native port of condor-work/tools/rdec.js (the replay decoder every reader uses through tools/lab/replay.py)
// for engine 2.0.0 replays. It drives the translated engine's visualiser timeline exactly as rdec.js does (same exports,
// same snapshot offsets, same diffs) and writes the same JSON, byte for byte apart from decoder.ms (checked by
// tools/cxe/cxedec.py --verify). Used two ways:
//   cxe --decode REPLAY OUT.json      decode an existing replay (exit 3: not a 2.0.0 replay, use rdec.js)
//   cxe A.so B.so MAP OUT --record    play, then write OUT.json (the decode of the game just played, plus "cxe" extras)
// Summary/meta handling (match, check) stays in Python (replay.py): this writes rdec.js's no-summary defaults.
#define W2C_HOST_ONLY 1
extern "C" {
#include "w2c_rt.h"
extern const w2c_module engine_module;
void w2c_mem_free(w2c_inst *I);
}
#include <algorithm>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {
const uint32_t NONE = 4294967295u;
const char *BODY_TYPES[] = {"ryth", "vesper_vale", "vendetta", "cassi", "issac", "stellar", "prism", "marcella", "willow", "ren", "varg", "tavi", "heart_of_ruin"};
const char *STEP_KINDS[] = {"phase", "respawn", "capture", "tick", "move", "attack", "cast", "input", "end_turn", "set_priority", "k10", "recall", "submit_gems", "shop", "place_ward", "consumable", "cancel_channel", "sandbox", "gems_submitted", "draft_champion", "place_altar_lock", "teleport_channel", "teleport_complete", "movement_blocked", "resign", "sell_item", "turn_rollover", "bot_error"};
const int NKIND = 28;
#ifndef CXE_ENGINE_NAME
#define CXE_ENGINE_NAME "v2_0_0"  // the engine this host translates (cxebuild sets it for other engines)
#endif
// engine 2.0.0 layouts (rdec.js TS2/FS2; engine 3.0.0 keeps them)
const uint32_t TS_size = 42840, TS_nCh = 172, TS_ch = 196, TS_chStride = 420, TS_nCamp = 176, TS_camp = 6916, TS_campStride = 28, TS_nGrp = 180, TS_grp = 20916, TS_grpStride = 8, TS_draft = 120;
const uint32_t FS_size = 189768, FS_ch = 140, FS_chStride = 624, FS_nCh = 120, FS_nCamp = 124, FS_camp = 10124, FS_campStride = 232, FS_nGrp = 128, FS_earned = 188936, FS_kda = 189192;
const int NI = 84, NIC = 88, CONS = 384, FSD = 168, MAXC = 16, MAXK = 512;

w2c_inst DI;
template <class R, class... A> R dc(const char *n, A... a) {
  static std::unordered_map<std::string, void *> fns;
  void *&f = fns[n];
  if (!f) f = engine_module.export_fn(n);
  return ((R(*)(w2c_inst *, A...))f)(&DI, a...);
}
#define D(name, ...) dc<uint32_t>(#name, ##__VA_ARGS__)
inline uint32_t u32(uint32_t p) { return ld_u32(DI.mem, p); }
inline int32_t i32(uint32_t p) { return (int32_t)ld_u32(DI.mem, p); }
inline double f32(uint32_t p) { return (double)ld_f32(DI.mem, p); }
inline uint8_t u8(uint32_t p) { return DI.mem[p]; }
inline uint64_t u64(uint32_t p) { return ld_u64(DI.mem, p); }
inline double u64n(uint32_t p) { return (double)u32(p) + (double)u32(p + 4) * 4294967296.0; }

double jround(double x) {  // Math.round: ties toward +infinity
  double r = std::floor(x);
  return x - r >= 0.5 ? r + 1 : r;
}
double r1(double v) { return jround(v * 10) / 10; }

// JSON numbers as JSON.stringify writes them (integral values as integers, -0 as 0, others shortest round-trip)
void num(std::string &s, double v) {
  char b[64];
  if (v == 0) { s += '0'; return; }
  if (v == std::floor(v) && std::fabs(v) < 9e15) {
    auto r = std::to_chars(b, b + 64, (long long)v);
    s.append(b, r.ptr);
    return;
  }
  auto r = std::to_chars(b, b + 64, v, std::chars_format::fixed);
  s.append(b, r.ptr);
}
void num(std::string &s, long long v) { char b[32]; auto r = std::to_chars(b, b + 32, v); s.append(b, r.ptr); }
void num(std::string &s, int v) { num(s, (long long)v); }
void num(std::string &s, uint32_t v) { num(s, (long long)v); }
void str(std::string &s, const char *t) {
  s += '"';
  for (; *t; t++) {
    if (*t == '"' || *t == '\\') s += '\\';
    s += *t;
  }
  s += '"';
}
// a JSON array from mixed values: A(s) << 1 << "m" << 2.5 ... ; strings are quoted
struct A {
  std::string &s;
  bool first = true;
  explicit A(std::string &o) : s(o) { s += '['; }
  ~A() { s += ']'; }
  void sep() { if (!first) s += ','; first = false; }
  A &operator<<(const char *t) { sep(); str(s, t); return *this; }
  A &operator<<(double v) { sep(); num(s, v); return *this; }
  A &operator<<(long long v) { sep(); num(s, v); return *this; }
  A &operator<<(int v) { sep(); num(s, v); return *this; }
  A &operator<<(uint32_t v) { sep(); num(s, v); return *this; }
  A &raw(const std::string &t) { sep(); s += t; return *this; }
};

struct State {
  int32_t x[MAXC], y[MAXC], gold[MAXC], gems[MAXC], kills[MAXC];
  double hp[MAXC], mhp[MAXC];
  uint8_t alive[MAXC];
  double campHp[MAXK];
  uint8_t ra[MAXK];
  uint32_t ct[MAXK];
  double sub[2];
};
struct Body { uint32_t id, team, type; std::string name; };
struct Turn { std::string head; int end; std::string acts; uint32_t cur; };
struct FB {  // fullBodyAt
  double earned, kills, deaths, assists, shield, foc, str;
  int32_t cd0, cd1, chTimer, respawn, wardCharges, priority;
  uint32_t chType, stunned, enhanced, crystal, lock;
};
}  // namespace

// -> 0 ok, 3 replay does not load with engine 2.0.0, 1 other failure. extra: appended as the last key (",\"cxe\":{...}")
int cxe_decode(const uint8_t *bytes, size_t n, const char *outPath, const std::string &extra) {
  auto t0 = std::chrono::steady_clock::now();
  memset(&DI, 0, sizeof DI);
  if (engine_module.init(&DI)) return 1;
  ((void (*)(w2c_inst *))engine_module.export_fn("_initialize"))(&DI);
  uint32_t OUT = D(Engine_Malloc, 64u);
  uint32_t p = D(Engine_Malloc, (uint32_t)n);
  memcpy(DI.mem + p, bytes, n);
  if (D(Game_FromReplayFileBytes, p, (uint32_t)n, OUT)) return 3;
  uint64_t g = u64(OUT);
  auto chk = [&](uint32_t rc, const char *what) {
    if (rc) { fprintf(stderr, "cxedec: %s failed: code %u\n", what, rc); exit(1); }
  };
  chk(D(Game_Visualiser_Timeline_GetMain, g, OUT), "Timeline_GetMain");
  uint64_t tl = u64(OUT);
  uint32_t info = D(Engine_Malloc, 64u);
  chk(D(Game_Visualiser_Timeline_Info, g, tl, info, info + 8, info + 16), "Timeline_Info");
  uint32_t size = u32(info);
  uint32_t fsSize = D(Game_Visualiser_SnapshotSize), tsSize = D(Game_Visualiser_TimelineSnapshotSize);
  if (tsSize != TS_size || fsSize != FS_size) { fprintf(stderr, "cxedec: unsupported snapshot layout %u/%u\n", tsSize, fsSize); return 3; }
  uint32_t ts = D(Engine_Malloc, TS_size), full = D(Engine_Malloc, fsSize);
  uint32_t persp = D(Engine_Malloc, 16u);
  memset(DI.mem + persp, 0, 16);
  st_u32(DI.mem, persp, 2);
  st_u32(DI.mem, persp + 4, NONE);
  chk(D(Game_Visualiser_Timeline_Seek, g, tl, 0u, 0u), "Timeline_Seek");
  auto readFull = [&]() { chk(D(Game_Visualiser_ReadState, g, persp, full), "ReadState"); };

  // ---------- static map
  chk(D(Game_GetNumChampsPerTeam, g, OUT), "numChamps");
  uint32_t teamSize = u32(OUT);
  readFull();
  uint32_t meta = D(Engine_Malloc, 64u);
  chk(D(Game_GetBitboardMetadata, g, meta), "bitboard metadata");
  int32_t width = i32(meta), height = i32(meta + 4);
  int32_t spawn[2][4];
  for (uint32_t t = 0; t < 2; t++) {
    chk(D(Game_API_GetSpawnRegion, g, t, OUT), "spawn");
    for (int k = 0; k < 4; k++) spawn[t][k] = i32(OUT + 4 * k);
  }
  std::vector<std::string> rows;
  std::vector<std::pair<int, int>> altars;
  std::unordered_set<int> altarSet;
  for (int32_t y = 0; y < height; y++) {
    std::string row;
    for (int32_t x = 0; x < width; x++) {
      char ch = '.';
      chk(D(Game_GetWall, g, x, y, OUT), "wall"); if (u8(OUT)) ch = '#';
      chk(D(Game_GetHole, g, x, y, OUT), "hole"); if (u8(OUT)) ch = 'o';
      chk(D(Game_GetBush, g, x, y, OUT), "bush"); if (u8(OUT)) ch = '"';
      chk(D(Game_GetAltar, g, x, y, OUT), "altar"); if (u8(OUT)) { ch = 'A'; altars.push_back({x, y}); altarSet.insert(y * 1000 + x); }
      if (ch == '.')
        for (int t = 0; t < 2; t++) { const int32_t *s = spawn[t]; if (x >= s[0] && x < s[2] && y >= s[1] && y < s[3]) ch = t ? 'b' : 'a'; }
      row += ch;
    }
    rows.push_back(row);
  }
  chk(D(Game_GetSymmetry, g, OUT), "symmetry");
  int32_t symmetry = i32(OUT);
  struct Camp { uint32_t id, type, group; int32_t x, y; double hp; };
  std::vector<Camp> camps;
  std::unordered_map<int, uint32_t> campAt;
  uint32_t nCampF = u32(full + FS_nCamp);
  for (uint32_t k = 0; k < nCampF; k++) {
    uint32_t c = full + FS_camp + k * FS_campStride;
    Camp cp{u32(c + 4), u32(c + 12), u32(c + 224), i32(c + 20), i32(c + 24), jround(f32(c + 32))};
    camps.push_back(cp);
    campAt[cp.y * 1000 + cp.x] = cp.id;
  }
  struct Grp { double gems = 0, gold = 0; int32_t respawn = 0; std::vector<uint32_t> camps; };
  uint32_t nGrpF = u32(full + FS_nGrp);
  std::vector<Grp> groups(nGrpF);
  for (uint32_t k = 0; k < nGrpF; k++) {
    if (D(Game_API_Map_CampGroup_Get, g, k, OUT) == 0) { groups[k].gems = u32(OUT); groups[k].gold = u32(OUT + 4); }
    if (D(Game_API_Map_CampGroup_GetRespawnTime, g, k, OUT) == 0) groups[k].respawn = i32(OUT);
  }
  for (auto &c : camps) if (c.group < groups.size()) groups[c.group].camps.push_back(c.id);

  // ---------- per-step state
  static State SA, SB;
  memset(&SA, 0, sizeof SA);
  memset(&SB, 0, sizeof SB);
  State *P = &SA, *C = &SB;
  std::vector<int32_t> items(MAXC * NIC, 0);
  uint32_t nCh = 0, nCamp = 0, nGrp = 0;
  bool haveBodies = false;
  std::vector<Body> bodies;

  auto readTS = [&](State &S) {
    chk(D(Game_Visualiser_ReadTimelineState, g, ts), "ReadTimelineState");
    nCh = u32(ts + TS_nCh); nCamp = u32(ts + TS_nCamp); nGrp = u32(ts + TS_nGrp);
    for (uint32_t k = 0; k < nCh; k++) {
      uint32_t b = ts + TS_ch + k * TS_chStride, id = u32(b + 4);
      if (id >= (uint32_t)MAXC) continue;
      S.x[id] = i32(b + 16); S.y[id] = i32(b + 20); S.hp[id] = f32(b + 24); S.mhp[id] = f32(b + 28);
      S.alive[id] = (uint8_t)u32(b + 32); S.gold[id] = (int32_t)u32(b + 36); S.gems[id] = (int32_t)u32(b + 40); S.kills[id] = (int32_t)u32(b + 44);
    }
    for (uint32_t k = 0; k < nCamp; k++) { uint32_t b = ts + TS_camp + k * TS_campStride, id = u32(b + 4); if (id < (uint32_t)MAXK) S.campHp[id] = f32(b + 24); }
    for (uint32_t k = 0; k < nGrp && k < (uint32_t)MAXK; k++) { uint32_t b = ts + TS_grp + k * TS_grpStride; S.ra[k] = (uint8_t)u32(b); S.ct[k] = u32(b + 4); }
    S.sub[0] = u64n(ts + 32); S.sub[1] = u64n(ts + 40);
  };
  auto readItems = [&](uint32_t id, int32_t *a) -> bool {
    for (uint32_t k = 0; k < nCh; k++) {
      uint32_t b = ts + TS_ch + k * TS_chStride;
      if (u32(b + 4) != id) continue;
      for (int t = 0; t < NI; t++) a[t] = (int32_t)u32(b + 48 + t * 4);
      for (int t = 0; t < 4; t++) a[NI + t] = (int32_t)u32(b + CONS + t * 4);
      return true;
    }
    return false;
  };
  // entity at a tile from the state before the step: kind (1 champion, 2 camp, 6 altar, 0 none), index
  auto resolve = [&](int32_t x, int32_t y, int &k, int &i) {
    for (uint32_t c = 0; c < nCh; c++) if (c < (uint32_t)MAXC && P->alive[c] && P->x[c] == x && P->y[c] == y) { k = 1; i = (int)c; return; }
    auto it = campAt.find(y * 1000 + x);
    if (it != campAt.end() && it->second < (uint32_t)MAXK && P->campHp[it->second] > 0) { k = 2; i = (int)it->second; return; }
    if (altarSet.count(y * 1000 + x)) { k = 6; i = -1; return; }
    if (it != campAt.end()) { k = 2; i = (int)it->second; return; }
    k = 0; i = -1;
  };
  struct Fx { int k, i; double d; };
  auto effects = [&](std::vector<Fx> &v) {
    v.clear();
    for (uint32_t c = 0; c < nCh && c < (uint32_t)MAXC; c++) { double d = C->hp[c] - P->hp[c]; if (std::fabs(d) > 1e-3 && (P->alive[c] || C->alive[c])) v.push_back({1, (int)c, r1(d)}); }
    for (uint32_t k = 0; k < nCamp && k < (uint32_t)MAXK; k++) { double d = C->campHp[k] - P->campHp[k]; if (std::fabs(d) > 1e-3) v.push_back({2, (int)k, r1(d)}); }
  };
  auto fxJson = [](const std::vector<Fx> &v) {
    std::string s;
    A a(s);
    for (auto &f : v) { std::string t; { A b(t); b << f.k << f.i << f.d; } a.raw(t); }
    return s;
  };
  auto fullBodyAt = [&](uint32_t n, uint32_t id) {
    FB f;
    uint32_t mask = u32(n + 40);
    f.earned = u64n(full + FS_earned + id * 16);
    f.kills = u32(full + FS_kda + id * 12); f.deaths = u32(full + FS_kda + id * 12 + 4); f.assists = u32(full + FS_kda + id * 12 + 8);
    f.cd0 = i32(n + 92); f.cd1 = i32(n + 96); f.chType = u32(n + 440 + FSD); f.chTimer = i32(n + 436 + FSD);
    f.shield = (mask & 1) ? r1(f32(n + 48)) : 0; f.stunned = (mask & 2) ? 1 : 0; f.enhanced = (mask & 4) ? 1 : 0;
    f.foc = r1(f32(n + 132)); f.str = r1(f32(n + 148)); f.respawn = i32(n + 228);
    f.crystal = u32(n + 412 + FSD); f.lock = u32(n + 420 + FSD); f.wardCharges = u32(n + 408 + FSD) ? (int32_t)u32(n + 428 + FSD) : -1;
    f.priority = i32(n + 444 + FSD);
    return f;
  };
  auto fullBody = [&](uint32_t id, FB &f) -> bool {
    uint32_t n = full + FS_ch + id * FS_chStride;
    if (u32(n + 4) != id) {
      uint32_t cnt = u32(full + FS_nCh);
      for (uint32_t k = 0; k < cnt; k++) { uint32_t m = full + FS_ch + k * FS_chStride; if (u32(m + 4) == id) { f = fullBodyAt(m, id); return true; } }
      return false;
    }
    f = fullBodyAt(n, id);
    return true;
  };

  // ---------- outputs
  std::vector<Turn> turns;
  std::string rounds, events, draft = "null";
  long turnIdx = -1;  // the open turn row (rdec.js `turn`): never closed, only replaced by the next one
  long long turnKey = -1;
  long lastRoundRow = -1;
  std::vector<double> rowCampHp(MAXK, 0);
  std::vector<uint8_t> rowRa(MAXK, 0);
  std::vector<uint32_t> rowCt(MAXK, 2);
  for (auto &c : camps) if (c.id < (uint32_t)MAXK) rowCampHp[c.id] = c.hp;
  bool first = true;
  long steps = 0;
  long kindCount[NKIND] = {0};
  std::string finalHdr = "null";
  std::vector<int32_t> capturing(MAXK, 2);
  std::vector<Fx> E;
  auto ev = [&](const std::string &e) { if (!events.empty()) events += ','; events += e; };
  auto act = [&](const std::string &a) {
    Turn &t = turns[turnIdx];
    if (!t.acts.empty()) t.acts += ',';
    t.acts += a;
  };
  int32_t a_items[NIC];

  for (;;) {
    readTS(*C);
    steps++;
    uint32_t round = u32(ts + 8), tIdx = u32(ts + 12), awaitIn = u32(ts + 20), phase = u32(ts + 24), outcome = u32(ts + 28);
    uint32_t inPos = u32(ts + 56), cur = u32(ts + 60);
    uint32_t sph = u32(ts + 64), kind = u32(ts + 68), ak = u32(ts + 72), ai = u32(ts + 76);
    int32_t fx = i32(ts + 80), fy = i32(ts + 84), tx = i32(ts + 88), ty = i32(ts + 92);
    uint32_t slot = u32(ts + 108), atype = u32(ts + 112);
    int32_t prio = i32(ts + 116);
    if (kind < (uint32_t)NKIND) kindCount[kind]++;
    if (first) { *P = *C; first = false; }

    if (!haveBodies && nCh > 0 && round >= 1 && phase != 12) {
      haveBodies = true;
      for (uint32_t k = 0; k < nCh; k++) {
        uint32_t b = ts + TS_ch + k * TS_chStride;
        uint32_t id = u32(b + 4), type = u32(b + 12);
        bodies.push_back({id, u32(b + 8), type, type < 13 ? BODY_TYPES[type] : std::to_string(type)});
        if (readItems(id, a_items) && id < (uint32_t)MAXC) memcpy(&items[id * NIC], a_items, sizeof a_items);
      }
      std::stable_sort(bodies.begin(), bodies.end(), [](const Body &a, const Body &b) { return a.id < b.id; });
      uint32_t d = ts + TS_draft;
      draft.clear();
      A dr(draft);
      for (uint32_t t = 0; t < 2; t++) {
        std::string s;
        { A x(s); for (uint32_t k = 0; k < u32(d + 4 + t * 4); k++) x << i32(d + 12 + t * 20 + k * 4); }
        dr.raw(s);
      }
    }

    // round row at the round's phase-0 step (state before the step: P)
    if (kind == 0 && sph == 0 && round >= 1 && (long)round != lastRoundRow && haveBodies) {
      lastRoundRow = round;
      readFull();
      double v[8] = {0};
      for (auto &b : bodies) {
        uint32_t t = b.team;
        FB f;
        bool ok = fullBody(b.id, f);
        if (t > 1) continue;
        v[t] += P->gems[b.id]; v[2 + t] += ok ? f.earned : 0; v[4 + t] += ok ? f.kills : 0; v[6 + t] += P->alive[b.id];
      }
      std::string cs, gs;
      { A c(cs);
        for (uint32_t k = 0; k < nCamp && k < (uint32_t)MAXK; k++) { double h = jround(P->campHp[k]); if (h != rowCampHp[k]) { std::string e; { A x(e); x << (int)k << h; } c.raw(e); rowCampHp[k] = h; } } }
      { A c(gs);
        for (uint32_t q = 0; q < nGrp && q < (uint32_t)MAXK; q++)
          if (P->ra[q] != rowRa[q] || P->ct[q] != rowCt[q]) { std::string e; { A x(e); x << (int)q << (int)P->ra[q] << P->ct[q]; } c.raw(e); rowRa[q] = P->ra[q]; rowCt[q] = P->ct[q]; } }
      std::string row;
      { A r(row); r << round << P->sub[0] << P->sub[1]; for (int k = 0; k < 8; k++) r << v[k]; r.raw(cs).raw(gs); }
      if (!rounds.empty()) rounds += ',';
      rounds += row;
    }

    // ---------- step effects
    std::string e;
    bool inTurn = turnIdx >= 0;
    switch (kind) {
      case 4:
        if (ak == 1 && sph == 10 && inTurn) { A(e) << "m" << tx << ty; act(e); }
        else if (ak == 1 && sph == 14) { A(e) << (int)round << "recall_arrive" << ai << fx << fy << tx << ty; ev(e); }
        break;
      case 23: if (inTurn) { A(e) << "b" << tx << ty; act(e); } break;
      case 5: {
        int k, i;
        resolve(tx, ty, k, i);
        if (ak == 1) { if (inTurn) { effects(E); A(e) << "a" << k << i << tx << ty; e.pop_back(); e += ',' + fxJson(E) + ']'; act(e); } }
        else if (ak == 2) {
          effects(E);
          double hit = 0;
          for (auto &f : E) if (f.k == 1) { hit = -f.d; break; }
          A(e) << (int)round << "camp_attack" << ai << (k == 1 ? i : -1) << hit;
          ev(e);
        }
        break;
      }
      case 6: {
        int k = 0, i = -1;
        if (atype == 2 || atype == 4 || atype == 5) resolve(tx, ty, k, i);
        if (inTurn) {
          effects(E);
          { A a(e); a << "c" << slot << atype << tx << ty << k << i; a.raw(fxJson(E)); a << fx << fy; }
          act(e);
        }
        break;
      }
      case 14: if (inTurn) { A(e) << "w" << tx << ty; act(e); } break;
      case 20: if (inTurn) { A(e) << "l" << tx << ty; act(e); } break;
      case 11: if (inTurn) { A(e) << "rc"; act(e); } break;
      case 16: if (inTurn) { A(e) << "x"; act(e); } break;
      case 12: if (inTurn) { A(e) << "t" << tx << ty << (ai < (uint32_t)MAXC ? C->gems[ai] : 0); act(e); } break;
      case 21: if (inTurn) { A(e) << "tp" << tx << ty; act(e); } break;
      case 9: if (inTurn) { A(e) << "p" << prio; act(e); } break;
      case 13: case 25: {
        if (readItems(ai, a_items) && ai < (uint32_t)MAXC) {
          int base = ai * NIC;
          std::string bought, cons;
          { A b(bought);
            for (int t = 0; t < NI; t += 2) {
              long long per = (t / 6) == 12 ? 25 : 5;
              long long nb = (long long)(a_items[t] - (long long)items[base + t]) + per * ((long long)a_items[t + 1] - items[base + t + 1]);
              if (nb) { std::string x; { A y(x); y << t << nb; } b.raw(x); }
            } }
          { A c(cons);
            for (int t = 0; t < 4; t++) { long long d = (long long)a_items[NI + t] - items[base + NI + t]; if (d) { std::string x; { A y(x); y << t << d; } c.raw(x); } } }
          memcpy(&items[base], a_items, sizeof a_items);
          long long spent = (long long)P->gold[ai] - C->gold[ai];
          if (inTurn) { { A a(e); a << (kind == 13 ? "s" : "sell"); a.raw(bought).raw(cons) << spent; } act(e); }
          else { { A a(e); a << (int)round << (kind == 13 ? "shop_outside_turn" : "sell_outside_turn") << ai; a.raw(bought).raw(cons) << spent; } ev(e); }
        }
        break;
      }
      case 18: {
        uint32_t team = haveBodies && ai < bodies.size() ? bodies[ai].team : 0;
        A(e) << (int)round << "tribute" << ai << team << (C->sub[team & 1] - P->sub[team & 1]) << tx << ty << (long long)((long long)C->gold[ai] - P->gold[ai]);
        ev(e);
        break;
      }
      case 22: { A(e) << (int)round << "teleport" << ai << fx << fy << tx << ty; ev(e); break; }
      case 1:
        if (ak == 1) { A(e) << (int)round << "respawn" << ai << C->x[ai] << C->y[ai]; ev(e); }
        else {
          std::vector<long long> gs;
          for (uint32_t c = 0; c < nCamp && c < (uint32_t)MAXK; c++)
            if (P->campHp[c] <= 0 && C->campHp[c] > 0) {
              long long gid = c < camps.size() ? (long long)camps[c].group : -1;
              bool seen = false;
              for (auto q : gs) seen |= q == gid;
              if (!seen) gs.push_back(gid);
            }
          for (auto gid : gs) { std::string x; A(x) << (int)round << "group_respawn" << gid; ev(x); }
        }
        break;
      case 2: {
        std::vector<uint32_t> gs;
        for (uint32_t q = 0; q < nGrp && q < (uint32_t)MAXK; q++) if (P->ra[q] && !C->ra[q]) gs.push_back(q);
        std::string gain;
        long long g0 = -1;
        { A ga(gain);
          for (uint32_t c = 0; c < nCh && c < (uint32_t)MAXC; c++) {
            long long dg = (long long)C->gold[c] - P->gold[c], dm = (long long)C->gems[c] - P->gems[c];
            if (dg || dm) { if (g0 < 0) g0 = c; std::string x; { A y(x); y << (int)c << dg << dm; } ga.raw(x); }
          } }
        long long team = (g0 >= 0 && haveBodies) ? (long long)bodies[g0].team : (gs.size() ? (long long)P->ct[gs[0]] : -1);
        { A a(e); a << (int)round << "capture";
          if (gs.size() == 1) a << gs[0];
          else { std::string x; { A y(x); for (auto q : gs) y << q; } a.raw(x); }
          a << team; a.raw(gain); }
        ev(e);
        for (auto q : gs) capturing[q] = 2;
        break;
      }
      case 24: { A(e) << (int)round << "resign" << ak << ai; ev(e); break; }
      case 8: case 26: case 27:
        if (ak == 1 && inTurn && turns[turnIdx].cur == ai) turns[turnIdx].end = kind == 8 ? 0 : kind == 26 ? 1 : 2;
        break;
    }

    // ---------- generic diffs: deaths, camp deaths, capture starts/resets
    if (haveBodies) {
      for (uint32_t c = 0; c < nCh && c < (uint32_t)MAXC; c++) {
        if (P->alive[c] && !C->alive[c]) {
          int killer = -1;
          for (uint32_t d = 0; d < nCh && d < (uint32_t)MAXC; d++) if (C->kills[d] > P->kills[d]) killer = (int)d;
          long long kk = killer >= 0 ? 1 : ak, ki = killer >= 0 ? killer : ai;
          std::string x;
          { A a(x); a << (int)round << "death" << (int)c << kk << ki << P->gems[c] << P->x[c] << P->y[c];
            if (kind < (uint32_t)NKIND) a << STEP_KINDS[kind]; else a << kind; }
          ev(x);
        }
      }
      for (uint32_t k = 0; k < nCamp && k < (uint32_t)MAXK; k++)
        if (P->campHp[k] > 0 && C->campHp[k] <= 0) { std::string x; A(x) << (int)round << "camp_death" << (int)k << ak << (ak == 1 ? (long long)ai : -1LL); ev(x); }
      for (uint32_t q = 0; q < nGrp && q < (uint32_t)MAXK; q++) {
        if ((int64_t)C->ct[q] != capturing[q] && kind != 2) {
          std::string x;
          if (C->ct[q] <= 1) { A(x) << (int)round << "capture_start" << (int)q << C->ct[q]; ev(x); }
          else if (C->ra[q]) { A(x) << (int)round << "capture_reset" << (int)q << capturing[q]; ev(x); }
          capturing[q] = (int32_t)C->ct[q];
        }
      }
    }

    // ---------- open a turn record at the first input point of a champion turn
    if (phase == 10 && awaitIn == 1 && cur != NONE && haveBodies) {
      long long key = (long long)round * 64 + tIdx;
      if (key != turnKey) {
        turnKey = key;
        readFull();
        FB f;
        bool ok = fullBody(cur, f);
        Turn t;
        t.cur = cur;
        t.end = -1;
        uint32_t c = cur < (uint32_t)MAXC ? cur : 0;
        {
          A a(t.head);
          a << (int)round << cur << C->x[c] << C->y[c] << jround(C->hp[c]) << jround(C->mhp[c]) << (int)C->alive[c] << C->gold[c] << C->gems[c];
          if (ok) a << f.earned << f.kills << f.deaths << f.cd0 << f.cd1 << f.chType << f.chTimer << f.shield << (int)f.stunned << f.foc << f.str << f.respawn << f.crystal << f.lock << f.wardCharges;
          else for (int k = 0; k < 15; k++) a.raw("null");
        }
        t.head.pop_back();  // leave the row open: end and acts follow
        turns.push_back(std::move(t));
        turnIdx = (long)turns.size() - 1;
      }
    }

    std::swap(P, C);
    auto hdr = [&](const char *err) {
      finalHdr.clear();
      finalHdr += "{\"round\":"; num(finalHdr, round);
      finalHdr += ",\"outcome\":"; num(finalHdr, outcome);
      finalHdr += ",\"submitted\":["; num(finalHdr, P->sub[0]); finalHdr += ','; num(finalHdr, P->sub[1]);
      finalHdr += "],\"inputPosition\":"; num(finalHdr, inPos);
      finalHdr += ",\"timelineSize\":"; num(finalHdr, size);
      if (err) { finalHdr += ",\"error\":"; str(finalHdr, err); }
      finalHdr += '}';
    };
    if (outcome || (awaitIn && inPos >= size)) { hdr(nullptr); break; }
    uint32_t rc = D(Game_Visualiser_Timeline_ReplayNext, g, 1u);
    if (rc) {
      uint32_t m = D(GetLastErrorMsg);
      std::string err = "ReplayNext " + std::to_string(rc) + " " + std::string((const char *)DI.mem + m);
      hdr(err.c_str());
      break;
    }
  }

  // ---------- final statistics
  std::string stats = "{\"summary\":";
  {
    uint32_t b = D(Engine_Malloc, 1024u);
    memset(DI.mem + b, 0, 1024);
    std::string sb;
    if (D(Game_Statistics_GetSummary, g, b) == 0) {
      stats += "{\"outcome\":"; num(stats, u32(b + 4)); stats += ",\"rounds\":"; num(stats, u32(b + 8));
      uint32_t nb = u32(b + 12);
      stats += ",\"bodies\":"; num(stats, nb); stats += ",\"submitted\":["; num(stats, u64n(b + 16)); stats += ','; num(stats, u64n(b + 24)); stats += "]}";
      for (uint32_t id = 0; id < nb; id++) {
        memset(DI.mem + b, 0, 1024);
        if (D(Game_Statistics_GetChampion, g, id, b) != 0) break;
        if (!sb.empty()) sb += ',';
        sb += "{\"id\":"; num(sb, u32(b)); sb += ",\"team\":"; num(sb, u32(b + 4)); sb += ",\"type\":"; num(sb, u32(b + 8));
        sb += ",\"kills\":"; num(sb, u32(b + 12)); sb += ",\"deaths\":"; num(sb, u32(b + 16)); sb += ",\"assists\":"; num(sb, u32(b + 20));
        sb += ",\"earnedGold\":"; num(sb, u64n(b + 24)); sb += ",\"gemsGained\":"; num(sb, u64n(b + 32)); sb += ",\"gemsTributed\":"; num(sb, u64n(b + 40));
        sb += ",\"goldSpent\":"; num(sb, u64n(b + 48)); sb += ",\"gold\":"; num(sb, u32(b + 56)); sb += ",\"gems\":"; num(sb, u32(b + 60));
        sb += ",\"bought\":{";
        bool f1 = true;
        for (int t = 0; t < NI; t++) { double v = u64n(b + 64 + t * 8); if (v) { if (!f1) sb += ','; f1 = false; sb += '"' + std::to_string(t) + "\":"; num(sb, v); } }
        sb += "}}";
      }
    } else stats += "null";
    stats += ",\"bodies\":[" + sb + "]}";
  }
  D(Game_Destroy, g);
  long ms = (long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();

  // ---------- write (rdec.js decodeFile key order: match, check, ...decode, schema)
  FILE *f = fopen(outPath, "w");
  if (!f) return 1;
  std::string o = "{\"match\":{\"matchId\":null,\"map\":null,\"createdAt\":null,\"endReason\":null,\"engineVersion\":null,\"teams\":[]},\"check\":{\"ok\":null,\"diffs\":[\"no summary\"]}";
  o += ",\"decoder\":{\"wasm\":\"" CXE_ENGINE_NAME ".wasm\",\"steps\":"; num(o, (long long)steps); o += ",\"ms\":"; num(o, (long long)ms); o += ",\"stepKinds\":{";
  bool f1 = true;
  for (int k = 0; k < NKIND; k++) if (kindCount[k]) { if (!f1) o += ','; f1 = false; str(o, STEP_KINDS[k]); o += ':'; num(o, (long long)kindCount[k]); }
  o += "}},\"map\":{\"width\":"; num(o, width); o += ",\"height\":"; num(o, height); o += ",\"symmetry\":"; num(o, symmetry); o += ",\"teamSize\":"; num(o, teamSize);
  o += ",\"spawn\":";
  { A s(o); for (int t = 0; t < 2; t++) { std::string x; { A y(x); for (int k = 0; k < 4; k++) y << spawn[t][k]; } s.raw(x); } }
  o += ",\"altars\":";
  { A s(o); for (auto &q : altars) { std::string x; A(x) << q.first << q.second; s.raw(x); } }
  o += ",\"rows\":";
  { A s(o); for (auto &r : rows) s << r.c_str(); }
  o += ",\"camps\":";
  { A s(o); for (auto &c : camps) { std::string x; A(x) << c.id << c.type << c.x << c.y << c.group << c.hp; s.raw(x); } }
  o += ",\"groups\":";
  { A s(o);
    for (uint32_t k = 0; k < groups.size(); k++) {
      std::string x;
      { A y(x); y << k << groups[k].gems << groups[k].gold << groups[k].respawn; std::string cs; { A z(cs); for (auto c : groups[k].camps) z << c; } y.raw(cs); }
      s.raw(x);
    } }
  o += "},\"bodies\":[";
  for (size_t k = 0; k < bodies.size(); k++) {
    if (k) o += ',';
    o += "{\"id\":"; num(o, bodies[k].id); o += ",\"team\":"; num(o, bodies[k].team); o += ",\"type\":"; num(o, bodies[k].type);
    o += ",\"name\":"; str(o, bodies[k].name.c_str()); o += '}';
  }
  o += "],\"draft\":" + draft + ",\"final\":" + finalHdr + ",\"stats\":" + stats;
  o += ",\"turnCols\":[\"r\",\"c\",\"x\",\"y\",\"hp\",\"maxHp\",\"alive\",\"gold\",\"gems\",\"earned\",\"kills\",\"deaths\",\"cd0\",\"cd1\",\"chType\",\"chTimer\",\"shield\",\"stunned\",\"focus\",\"strength\",\"respawnTimer\",\"crystals\",\"locks\",\"wardCharges\",\"end\",\"acts\"]";
  o += ",\"roundCols\":[\"r\",\"subA\",\"subB\",\"carriedA\",\"carriedB\",\"earnedA\",\"earnedB\",\"killsA\",\"killsB\",\"aliveA\",\"aliveB\",\"campHp\",\"groupState\"]";
  fwrite(o.data(), 1, o.size(), f);
  fputs(",\"turns\":[", f);
  for (size_t k = 0; k < turns.size(); k++) {
    Turn &t = turns[k];
    if (k) fputc(',', f);
    fwrite(t.head.data(), 1, t.head.size(), f);
    fprintf(f, ",%d,[", t.end);
    fwrite(t.acts.data(), 1, t.acts.size(), f);
    fputs("]]", f);
  }
  fputs("],\"rounds\":[", f);
  fwrite(rounds.data(), 1, rounds.size(), f);
  fputs("],\"events\":[", f);
  fwrite(events.data(), 1, events.size(), f);
  fputs("],\"schema\":\"rdec/1\"", f);
  fwrite(extra.data(), 1, extra.size(), f);
  fputs("}", f);
  fclose(f);
  w2c_mem_free(&DI);
  return 0;
}
