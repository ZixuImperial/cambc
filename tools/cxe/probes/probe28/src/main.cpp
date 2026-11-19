// probe 28 (10 Nov, Builder: cxe lacked board_vision_mask, the SDK's hypothetical champion vision). Raw import calls with every champion
// type (and bad ones) at the body's tile, the corners, off-board and absurd tiles, plus a null out pointer. Each call's rc, mask hash and
// fuel charge feed an accumulator that decides whether the body plays this turn, so a wrong mask, rc or charge changes the replay and
// the per-turn fuel log against the CLI (its stdout capture is unreliable, so nothing here relies on prints).
#include <cambc.h>
#include <cstdint>
#include <cstring>
#include "bot.h"
#include "draft.h"
namespace d = cambc::detail;
static std::uint64_t mask[128];
static unsigned H(const unsigned char* p, int n) { unsigned h = 2166136261u; for (int i = 0; i < n; i++) h = (h ^ p[i]) * 16777619u; return h; }
int main() {
    int turn = 0;
    Bot bot;
    unsigned long long acc = 1469598103934665603ull;
    while (true) {
        if (cambc::is_draft()) { play_draft(); cambc::end_turn(); continue; }
        ++turn;
        if (turn % 3 == 1) {
            const int W = d::layout().width, Hh = d::layout().height;
            cambc::vec2 me{0, 0};
            try { me = cambc::self().position(); } catch (...) {}
            const int xs[] = {me.x, 0, W - 1, -1, 5, W, 100000, me.x + 3};
            const int ys[] = {me.y, 0, Hh - 1, 5, -1, 3, 100000, me.y - 2};
            for (int k = -1; k <= 12; k++) {
                for (int p = 0; p < 8; p++) {
                    memset(mask, 0xA5, sizeof mask);
                    long f0 = (long)cambc::fuel_remaining();
                    int rc = d::sdk_hypothetical_vision(k, xs[p], ys[p], mask);
                    long c = f0 - (long)cambc::fuel_remaining();
                    acc = (acc ^ (unsigned)rc) * 1099511628211ull;
                    acc = (acc ^ H((const unsigned char*)mask, sizeof mask)) * 1099511628211ull;
                    acc = (acc ^ (unsigned long long)c) * 1099511628211ull;
                }
            }
            long f0 = (long)cambc::fuel_remaining();
            int rc = d::sdk_hypothetical_vision(0, me.x, me.y, nullptr);
            acc = (acc ^ (unsigned)rc ^ (unsigned long long)(f0 - (long)cambc::fuel_remaining())) * 1099511628211ull;
        }
        if (((acc >> 11) & 3) != 0) {
            try { bot.play_turn(); } catch (...) {}
        }
        cambc::end_turn();
    }
}
