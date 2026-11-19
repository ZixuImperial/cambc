// probe 27 (7 Nov, owner: "make sure the engine is correct: the priority channel, draft memory and shared memory"). Raw imports
// (no SDK bounds checks) with edge cases, every rc, every byte read back (as a hash) and every call's fuel, printed as 'T' lines that
// ehtest.py --probe probe27 compares with the CLI line for line (and the replay byte for byte):
//   draft turns: draft_memory_size; read_draft_memory at in-range, boundary, out-of-range, negative and zero-length spans; submits
//     of 2000 bytes (over the size), then 10 bytes, then 0 bytes; shared memory reads/writes during the draft
//   champion turns: an 'O' line per body per turn (the execution order: priority, then draft order); on probe turns the draft
//     memory again (what play sees), a submit in play (frozen), shared memory writes/reads at every edge, set_priority with
//     0, 5, -3, 1e6, INT_MAX, INT_MIN, and every champion's priority (next and this round) incl. dead and unseen ones, plus bad handles.
// The bodies also play (probe24's farming bot) so deaths, dead turns and vision changes happen.
#include <cambc.h>
#include <climits>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include "bot.h"
#include "draft.h"
namespace d = cambc::detail;
static void P(const char* fmt, ...) {  // every line ends with the fuel left before it was formatted: where cxe and the CLI part
    const long f = (long)cambc::fuel_remaining();
    char b[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(b, sizeof b - 24, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (n > (int)sizeof b - 25) n = (int)sizeof b - 25;
    if (b[n - 1] == '\n') --n;
    n += snprintf(b + n, 24, " f %ld\n", f);
    write(1, b, n);
}
static unsigned H(const unsigned char* p, int n) { unsigned h = 2166136261u; for (int i = 0; i < n; i++) h = (h ^ p[i]) * 16777619u; return h; }
static long F() { return (long)cambc::fuel_remaining(); }
static unsigned char buf[4096];

static void draft_reads(const char* tag, int t) {
    std::uint32_t sz = 0;
    long f0 = F();
    int rc = d::sdk_draft_memory_size(&sz);
    P("T %s %d dsize rc %d sz %u c %ld\n", tag, t, rc, sz, f0 - F());
    const long spans[][2] = { {0, 16}, {0, (long)sz}, {(long)sz - 1, 1}, {(long)sz, 1}, {(long)sz - 4, 8}, {-1, 1}, {0, 0}, {5, 3000} };
    for (auto& s : spans) {
        memset(buf, 0xAA, sizeof buf);
        long g0 = F();
        int r = d::sdk_read_draft_memory((std::int32_t)s[0], buf, (std::uint32_t)s[1]);
        long c = g0 - F();
        int n = s[1] > 0 && s[1] <= (long)sizeof buf ? (int)s[1] : 16;
        P("T %s %d dread off %ld len %ld rc %d h %08x c %ld\n", tag, t, s[0], s[1], r, H(buf, n), c);
    }
}
static void shared_ops(const char* tag, int t, unsigned me) {
    const long sz = (long)cambc::shared_memory_buffer::size();
    P("T %s %d ssize %ld\n", tag, t, sz);
    const long w[][2] = { {(long)((t * 7 + me) % (sz > 0 ? sz : 1)), 1}, {0, 4}, {sz - 1, 1}, {sz - 1, 2}, {sz, 1}, {-1, 1}, {0, 0}, {0, sz}, {2, sz} };
    for (auto& s : w) {
        for (int i = 0; i < (int)sizeof buf; i++) buf[i] = (unsigned char)(i * 31 + t * 7 + me);
        long g0 = F();
        int r = d::sdk_write_shared_memory((std::int32_t)s[0], buf, (std::uint32_t)(s[1] > 0 ? s[1] : 0));
        P("T %s %d swrite off %ld len %ld rc %d c %ld\n", tag, t, s[0], s[1], r, g0 - F());
    }
    const long rd[][2] = { {0, sz}, {sz - 1, 1}, {sz, 1}, {-1, 1}, {0, 0}, {1, sz} };
    for (auto& s : rd) {
        memset(buf, 0xAA, sizeof buf);
        long g0 = F();
        int r = d::sdk_read_shared_memory((std::int32_t)s[0], buf, (std::uint32_t)(s[1] > 0 ? s[1] : 0));
        long c = g0 - F();
        int n = s[1] > 0 && s[1] <= (long)sizeof buf ? (int)s[1] : 16;
        P("T %s %d sread off %ld len %ld rc %d h %08x c %ld\n", tag, t, s[0], s[1], r, H(buf, n), c);
    }
}
static void priority_ops(int t, unsigned me) {
    static const std::int32_t vals[] = { 0, 5, -3, 1000000, INT_MAX, INT_MIN, 7, 7 };
    const std::int32_t p = vals[(t + me) % 8];
    long g0 = F();
    int rc = d::sdk_set_priority(p);
    P("T play %d setprio %d rc %d c %ld\n", t, p, rc, g0 - F());
    for (int side = 0; side < 2; side++) {
        const auto cs = cambc::champions(side ? cambc::team::enemy : cambc::team::ally);
        for (const auto& c : cs) {
            for (int nx = 0; nx < 2; nx++) {
                std::int32_t v = -12345;
                long h0 = F();
                int r = d::sdk_bc_champion_priority((std::uint32_t)(cambc::handle_champion_t)c, nx, &v);
                P("T play %d prio side %d h %u nx %d rc %d v %d c %ld\n", t, side, (unsigned)(cambc::handle_champion_t)c, nx, r, v, h0 - F());
            }
        }
    }
    for (std::uint32_t bad : { 999u, 0xFFFFFFFFu }) {
        std::int32_t v = -12345;
        int r = d::sdk_bc_champion_priority(bad, 1, &v);
        P("T play %d prio bad %u rc %d v %d\n", t, bad, r, v);
    }
}
int main() {
    int turn = 0, dturn = 0;
    Bot bot;
    while (true) {
        if (cambc::is_draft()) {
            ++dturn;
            // a line costs ~12k fuel (vsnprintf): later draft turns (100k) submit and pick BEFORE printing, so no draft turn ends
            // without a pick (GameRules :88: the CLI would then pick at random with its host RNG, which cxe cannot copy)
            if (dturn == 1) draft_reads("draft", dturn);
            for (int i = 0; i < 2000; i++) buf[i] = (unsigned char)(i * 7 + dturn);
            const int len = dturn == 1 ? 2000 : dturn == 2 ? 10 : 0;
            long g0 = F();
            int rc = d::sdk_bc_submit_draft_memory(buf, (std::size_t)len);
            long sc = g0 - F();
            if (dturn == 1) {
                P("T draft %d submit len %d rc %d c %ld\n", dturn, len, rc, sc);
                draft_reads("draftafter", dturn);
                shared_ops("draft", dturn, 0);
            }
            try { play_draft(); } catch (...) { P("T draft %d pick threw\n", dturn); }
            if (dturn > 1) {
                P("T draft %d submit len %d rc %d c %ld\n", dturn, len, rc, sc);
                memset(buf, 0xAA, 64);
                int r = d::sdk_read_draft_memory(0, buf, 16);
                P("T draft %d after pick dread rc %d h %08x\n", dturn, r, H(buf, 16));
            }
            cambc::end_turn();
            continue;
        }
        ++turn;
        unsigned me = 0;
        bool alive = false;
        try { me = (unsigned)(cambc::handle_champion_t)cambc::self(); alive = cambc::self().is_alive(); } catch (...) { me = 777; }
        P("O %d %u %d\n", turn, me, alive ? 1 : 0);
        if (turn <= 12 || turn % 150 == 0) {
            draft_reads("play", turn);
            for (int i = 0; i < 8; i++) buf[i] = 0x33;
            int rc = d::sdk_bc_submit_draft_memory(buf, 8);
            P("T play %d submit rc %d\n", turn, rc);
            shared_ops("play", turn, me);
            priority_ops(turn, me);
        } else if (turn % 10 == 0) {
            priority_ops(turn, me);
        }
        try { bot.play_turn(); } catch (...) { P("T play %d bot threw\n", turn); }
        cambc::end_turn();
    }
}
