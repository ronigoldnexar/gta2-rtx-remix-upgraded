// Proves the GCC stand-in for __try/__except (compat.h) catches a fault and
// carries on: reads through a null pointer and a wild pointer inside GTA2_TRY,
// then does real work after. Exit code 0 when both faults were caught.
#include <cstdio>
#include "compat.h"

static volatile int* g_null = nullptr;
static volatile int* g_wild = reinterpret_cast<volatile int*>(0x7FFE5000);

static bool ReadGuarded(volatile int* p, int* out) {
    GTA2_TRY {
        *out = *p;
        return true;
    } GTA2_EXCEPT {
        return false;
    }
    return false;
}

int main() {
    gta2dx9::SehCompatInstall();
    int value = 42;
    const bool nullCaught = !ReadGuarded(g_null, &value);
    const bool wildCaught = !ReadGuarded(g_wild, &value);
    int fine = 7;
    const bool fineRead = ReadGuarded(&fine, &value) && value == 7;
    // Twice more in a row, to show the handler re-arms.
    const bool again = !ReadGuarded(g_null, &value) && !ReadGuarded(g_null, &value);
    printf("null fault caught: %s, wild fault caught: %s, good read: %s, re-armed: %s\n",
           nullCaught ? "yes" : "NO", wildCaught ? "yes" : "NO", fineRead ? "yes" : "NO", again ? "yes" : "NO");
    return (nullCaught && wildCaught && fineRead && again) ? 0 : 1;
}
