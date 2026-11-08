#include "game_save.h"

#include "compat.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "log.h"

namespace gta2dx9 {
namespace {

// From gta2.exe, the build the rest of the mod is written against.
constexpr uintptr_t kScriptManagerPtr = 0x006644BC;   // the script manager (the save's "this")
constexpr uintptr_t kPlayerPtr = 0x005EB4FC;          // -> object whose +0x38 is the player's score keeper
constexpr uintptr_t kProfileObject = 0x005EC070;      // the profile; +0x300 holds the save's name ("" = slot default)
constexpr uintptr_t kSaveFunction = 0x0047EF40;       // void __thiscall Save(manager, const char* name)
constexpr uintptr_t kGetMoney = 0x00421980;           // int __thiscall (scoreKeeper)
constexpr uintptr_t kMessageUi = 0x00672F40;          // -> UI object; +0xE4 shows a message
constexpr uintptr_t kShowMessage = 0x004C6750;        // void __thiscall (ui+0xE4, int, const char* key)
constexpr uintptr_t kMessageBuffer = 0x005E9808;      // where the game puts the message key

GameSaveSettings g_settings;
std::string g_status = "not saved yet";
DWORD g_lastSaveTick = 0;
bool g_everSaved = false;

typedef void(__thiscall* SaveFn)(void* manager, const char* name);
typedef int(__thiscall* MoneyFn)(void* scoreKeeper);
typedef void(__thiscall* ShowFn)(void* ui, int a, const char* key);

// Reads of the game's memory, every frame (the score keeper and its money). They were
// ReadProcessMemory, a wineserver round trip each under Wine: four a frame, 15-30 ms
// together whenever the server was busy with input (PERF-3, `pre_menu` in the frame
// log). As in view_modes.cpp: the region is checked once with VirtualQuery and
// remembered, and the read is a plain load under the fault guard.
struct ReadableRange { uintptr_t lo, hi; };
ReadableRange g_readable[16];
int g_readableCount = 0, g_readableNext = 0;
unsigned g_readableCalls = 0;
bool KnownReadable(uintptr_t address, size_t bytes) {
    if (++g_readableCalls >= 65536) { g_readableCalls = 0; g_readableCount = 0; g_readableNext = 0; }   // look again now and then
    for (int i = 0; i < g_readableCount; ++i) {
        if (address >= g_readable[i].lo && address + bytes <= g_readable[i].hi) return true;
    }
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(reinterpret_cast<LPCVOID>(address), &mbi, sizeof mbi)) return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                           PAGE_EXECUTE_WRITECOPY;
    if (mbi.State != MEM_COMMIT || !(mbi.Protect & readable) || (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
    const uintptr_t lo = reinterpret_cast<uintptr_t>(mbi.BaseAddress), hi = lo + mbi.RegionSize;
    if (address + bytes > hi) return false;
    g_readable[g_readableNext] = {lo, hi};
    g_readableNext = (g_readableNext + 1) % 16;
    if (g_readableCount < 16) ++g_readableCount;
    return true;
}
template <typename T>
bool Read(uintptr_t address, T* out) {
    if (address < 0x10000 || address >= 0x7FFE0000) return false;
    if (!KnownReadable(address, sizeof(T))) return false;
    bool ok = true;
    GTA2_TRY { memcpy(out, reinterpret_cast<const void*>(address), sizeof(T)); } GTA2_EXCEPT { ok = false; }
    return ok;
}

void* ScoreKeeper() {
    uintptr_t player = 0, keeper = 0;
    if (!Read(kPlayerPtr, &player) || player < 0x10000) return nullptr;
    if (!Read(player + 0x38, &keeper) || keeper < 0x10000) return nullptr;
    return reinterpret_cast<void*>(keeper);
}

int ReadMoney() {
    void* keeper = ScoreKeeper();
    if (!keeper) return -1;
    int money = -1;
    GTA2_TRY {
        money = reinterpret_cast<MoneyFn>(kGetMoney)(keeper);
    } GTA2_EXCEPT {
        money = -1;
    }
    return money;
}

std::string SettingsPath() {
    char path[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    std::string p = path;
    const size_t slash = p.find_last_of("\\/");
    return (slash == std::string::npos ? std::string() : p.substr(0, slash + 1)) + "gta2dx9_settings.ini";
}

int g_prevMoney = -1;
uintptr_t g_prevKeeper = 0;
double g_pendingSince = -1.0;
int g_pendingGain = 0;

double Now() {
    static LARGE_INTEGER freq = {};
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return static_cast<double>(t.QuadPart) / static_cast<double>(freq.QuadPart);
}

}  // namespace

GameSaveSettings& GameSave() { return g_settings; }

int GameSaveMoney() { return ReadMoney(); }

const char* GameSaveStatus() { return g_status.c_str(); }

double GameSaveAgeSeconds() {
    return g_everSaved ? static_cast<double>(GetTickCount() - g_lastSaveTick) / 1000.0 : -1.0;
}

bool SaveGameNow() {
    uintptr_t manager = 0;
    if (!Read(kScriptManagerPtr, &manager) || manager < 0x10000) {
        g_status = "no game running to save";
        return false;
    }
    const char* name = reinterpret_cast<const char*>(kProfileObject + 0x300);
    bool ok = true;
    GTA2_TRY {
        reinterpret_cast<SaveFn>(kSaveFunction)(reinterpret_cast<void*>(manager), name);
    } GTA2_EXCEPT {
        ok = false;
    }
    if (!ok) {
        g_status = "the game refused the save";
        Log("game save: the save function faulted");
        return false;
    }
    if (g_settings.message) {
        uintptr_t ui = 0;
        if (Read(kMessageUi, &ui) && ui > 0x10000) {
            GTA2_TRY {
                memcpy(reinterpret_cast<void*>(kMessageBuffer), "svdone", 7);
                reinterpret_cast<ShowFn>(kShowMessage)(reinterpret_cast<void*>(ui + 0xE4), 1,
                                                       reinterpret_cast<const char*>(kMessageBuffer));
            } GTA2_EXCEPT {
            }
        }
    }
    g_lastSaveTick = GetTickCount();
    g_everSaved = true;
    g_status = "game saved";
    Log("game save: saved (money %d)", ReadMoney());
    return true;
}

void GameSaveTick() {
    static bool loaded = false;
    if (!loaded) {
        loaded = true;
        GameSaveLoadSettings();
    }
    const void* keeper = ScoreKeeper();
    const uintptr_t keeperAt = reinterpret_cast<uintptr_t>(keeper);
    if (keeperAt != g_prevKeeper) {
        // A new level or a load: the first reading is not a payout.
        g_prevKeeper = keeperAt;
        g_prevMoney = -1;
        g_pendingSince = -1.0;
    }
    if (!keeper) return;
    const int money = ReadMoney();
    if (money < 0) return;
    if (g_prevMoney >= 0 && g_settings.autoSave && money - g_prevMoney >= g_settings.minPayout) {
        g_pendingSince = Now();
        g_pendingGain += money - g_prevMoney;
        Log("game save: payout of %d seen, saving in %.1f s", money - g_prevMoney, g_settings.delay);
    }
    g_prevMoney = money;
    if (g_pendingSince >= 0.0 && Now() - g_pendingSince >= g_settings.delay) {
        g_pendingSince = -1.0;
        g_pendingGain = 0;
        SaveGameNow();
    }
}

void GameSaveLoadSettings() {
    const std::string ini = SettingsPath();
    g_settings.autoSave = GetPrivateProfileIntA("save", "auto_save", 1, ini.c_str()) != 0;
    g_settings.minPayout = static_cast<int>(GetPrivateProfileIntA("save", "min_payout", 3000, ini.c_str()));
    g_settings.delay = static_cast<float>(GetPrivateProfileIntA("save", "delay_ms", 2000, ini.c_str())) / 1000.0f;
    g_settings.message = GetPrivateProfileIntA("save", "message", 1, ini.c_str()) != 0;
}

bool GameSaveSaveSettings() {
    const std::string ini = SettingsPath();
    auto put = [&](const char* key, int value) {
        char text[24];
        snprintf(text, sizeof(text), "%d", value);
        return WritePrivateProfileStringA("save", key, text, ini.c_str()) != 0;
    };
    bool ok = put("auto_save", g_settings.autoSave ? 1 : 0);
    ok &= put("min_payout", g_settings.minPayout);
    ok &= put("delay_ms", static_cast<int>(g_settings.delay * 1000.0f + 0.5f));
    ok &= put("message", g_settings.message ? 1 : 0);
    return ok;
}

}  // namespace gta2dx9
