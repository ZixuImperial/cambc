// probe 21: C++ exceptions (wasm try_table / throw / rethrow) every turn: throw across frames, catch by type, rethrow,
// nested try, catch(...) - the values printed each turn must match the CLI exactly (cxe __builtin_setjmp frames)
#include <cambc.h>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <unistd.h>
#include "draft.h"
struct E1 { int v; };
__attribute__((noinline)) int deep(int n, int k) {
    if (n == 0) {
        if (k % 3 == 0) throw E1{k};
        if (k % 3 == 1) throw std::runtime_error("r");
        return k;
    }
    return deep(n - 1, k) + 1;
}
__attribute__((noinline)) int mid(int k) {
    int local = k * 3;
    try { return deep(5, k); }
    catch (E1& e) { if (e.v % 2) throw; return -e.v + local; }
}
__attribute__((noinline)) int exercise(int k, int& caught) {
    int s = 0;
    for (int i = 0; i < 9; i++) {
        int before = s;
        try { s += mid(k + i); }
        catch (const std::exception&) { caught += 1; s = before + 100; }
        catch (E1& e) { caught += 10; s = before + e.v; }
        try {
            try { if ((k + i) % 5 == 0) throw 7; s += 1; }
            catch (int x) { s += x; if (i % 4 == 3) throw std::logic_error("y"); }
        } catch (std::logic_error&) { caught += 100; }
        try { if ((k ^ i) % 7 == 0) throw 3.5; } catch (...) { caught += 1000; }
    }
    return s;
}
int main() {
    int turn = 0, caught = 0;
    long total = 0;
    while (true) {
        if (cambc::is_draft()) { play_draft(); cambc::end_turn(); continue; }
        ++turn;
        total += exercise(turn * 7 + (int)cambc::round_number(), caught);
        if (turn % 50 == 1) {
            char out[120]; int m = snprintf(out, sizeof out, "T %d total %ld caught %d\n", turn, total, caught);
            write(1, out, m);
        }
        cambc::end_turn();
    }
}
