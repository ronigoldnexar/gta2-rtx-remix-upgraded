// QB-17/18: the framed beats (WASTED, BUSTED, JOB COMPLETE). See beats.h.

#include "beats.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <string>

#include "compat.h"
#include "hud3d.h"
#include "log.h"
#include "view_modes.h"

namespace gta2dx9 {
namespace {

// The game's big message (see beats.h): [kHudObject] + kBigMessage, its countdown byte
// at +0 (90 when set, 0 when gone), the text a UTF-16 copy at +2 (wcscpy, up to 0xC8 bytes
// before the wrapped copy at +0xCA).
constexpr uintptr_t kHudObject = 0x00672F40;
constexpr uintptr_t kBigMessage = 0x2854;
constexpr int kBigTextChars = 0x60;
// The text lookup (FUN_004C23A0, __thiscall on [0x671550], key -> UTF-16) and the big
// message's setter (FUN_004C6060, __thiscall, text and priority): the devtools trigger
// puts up a message the way the scripts do (0x479478: "push 3; push 0x5E9808").
constexpr uintptr_t kTextObject = 0x00671550;
constexpr uintptr_t kTextLookup = 0x004C23A0;
constexpr uintptr_t kBigMessageSet = 0x004C6060;

struct Config {
    bool loaded = false;
    bool enabled = true;          // [beats] enabled
    float completeSecs = 4.2f;    // [beats] complete_ms / 1000
    float fadeAfter = 1.6f;       // [beats] fade_after_ms / 1000: WASTED/BUSTED go to black from here
    bool anchorDeath = true;      // [beats] anchor_death (FIX-CAMERA-21): frame the death place the game moved him from
    float maxSecs = 12.0f;        // the longest a death/arrest beat waits for the respawn
    char sting[3][260] = {};      // [beats] sting_wasted, sting_busted, sting_complete
};
Config g_cfg;
BeatState g_beat;
BeatStingHook g_hook = nullptr;
float g_respawnAt = -1.0f;   // the beat's time when the game put him back; < 0 not yet
int g_farFrames = 0;         // consecutive frames he has been found far from the beat's spot
// Where he was last frame, when found: on the message's own frame the locator can report
// the new body the game has already placed at the hospital or the station (seen in
// qb17_beats3: "WASTED start at 50.50,2.00,77.50 yaw 180", the body at 134.2,153.4), so a
// beat is anchored on the frame before.
struct Seen { bool valid = false; float x = 0, y = 0, z = 0, yaw = 0; bool inVehicle = false; };
Seen g_prev;
// FIX-CAMERA-21 (qaf91/qaf92): the last place that did not jump, and how long ago it was
// seen. A car that blows up under him loses him for a frame and the next frame the game's
// player object is already the new body at the hospital, on the very frame of the WASTED
// message: g_prev then holds nothing (lost) or the jump, and the beat used to frame the
// bare hospital bay. g_last keeps the death place through that.
Seen g_last;
float g_lastAge = 1e9f;
bool g_heldDeath = false;    // this beat frames a place the game had already moved him from

// The keys' texts, letters only, upper case, from data\e.gxt.
struct KeySet { BeatKind kind; const char* keys[4]; };
const KeySet kKeys[] = {
    {BeatKind::Wasted, {"wasted", "fried", "shocked", nullptr}},
    {BeatKind::Busted, {"nicked", nullptr, nullptr, nullptr}},
    {BeatKind::Complete, {"1124", "3100", "2999", nullptr}},
};
std::u16string g_texts[3][4];
bool g_textsLoaded = false;

std::u16string Letters(const char16_t* s, size_t n) {
    std::u16string out;
    for (size_t i = 0; i < n && s[i]; ++i) {
        char16_t c = s[i];
        if (c >= u'a' && c <= u'z') c = static_cast<char16_t>(c - 32);
        if ((c >= u'A' && c <= u'Z') || (c >= 0xC0 && c <= 0x24F)) out.push_back(c);
    }
    return out;
}

void LoadConfig() {
    if (g_cfg.loaded) return;
    g_cfg.loaded = true;
    const char* ini = ViewModes().devIniPath;
    if (ini && ini[0]) {
        g_cfg.enabled = GetPrivateProfileIntA("beats", "enabled", 1, ini) != 0;
        g_cfg.completeSecs = (std::max)(1500, (std::min)(10000, static_cast<int>(GetPrivateProfileIntA("beats", "complete_ms", 4200, ini)))) / 1000.0f;
        g_cfg.anchorDeath = GetPrivateProfileIntA("beats", "anchor_death", 1, ini) != 0;
        if (const char* e = getenv("GTA2DX9_BEAT_ANCHOR_DEATH")) g_cfg.anchorDeath = atoi(e) != 0;
        g_cfg.fadeAfter = (std::max)(500, (std::min)(9000, static_cast<int>(GetPrivateProfileIntA("beats", "fade_after_ms", 1600, ini)))) / 1000.0f;
        GetPrivateProfileStringA("beats", "sting_wasted", "", g_cfg.sting[0], sizeof g_cfg.sting[0], ini);
        GetPrivateProfileStringA("beats", "sting_busted", "", g_cfg.sting[1], sizeof g_cfg.sting[1], ini);
        GetPrivateProfileStringA("beats", "sting_complete", "", g_cfg.sting[2], sizeof g_cfg.sting[2], ini);
    }
    Log("beats: framed WASTED/BUSTED/JOB COMPLETE %s (complete %.1f s, fade after %.1f s, stings %s/%s/%s)",
        g_cfg.enabled ? "on" : "off", g_cfg.completeSecs, g_cfg.fadeAfter, g_cfg.sting[0][0] ? g_cfg.sting[0] : "-",
        g_cfg.sting[1][0] ? g_cfg.sting[1] : "-", g_cfg.sting[2][0] ? g_cfg.sting[2] : "-");
}

void LoadTexts() {
    if (g_textsLoaded) return;
    g_textsLoaded = true;
    int found = 0;
    for (int k = 0; k < 3; ++k)
        for (int i = 0; i < 4 && kKeys[k].keys[i]; ++i) {
            std::u16string s;
            if (Hud3dGameText(kKeys[k].keys[i], &s)) {
                g_texts[k][i] = Letters(s.c_str(), s.size());
                ++found;
            }
        }
    Log("beats: %d of the beats' message texts found in data\\e.gxt", found);
}

BeatKind Classify(const std::u16string& letters) {
    if (letters.empty()) return BeatKind::None;
    for (int k = 0; k < 3; ++k)
        for (int i = 0; i < 4; ++i)
            if (!g_texts[k][i].empty() && g_texts[k][i] == letters) return kKeys[k].kind;
    return BeatKind::None;
}

std::string Utf8(const char16_t* s, size_t n) {
    std::string out;
    for (size_t i = 0; i < n && s[i]; ++i) {
        const unsigned c = s[i];
        if (c < 0x80) out.push_back(static_cast<char>(c));
        else if (c < 0x800) { out.push_back(static_cast<char>(0xC0 | (c >> 6))); out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
        else { out.push_back(static_cast<char>(0xE0 | (c >> 12))); out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F))); out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
    }
    return out;
}

void Sting(BeatKind kind, const char* title) {
    const int slot = kind == BeatKind::Wasted ? 0 : kind == BeatKind::Busted ? 1 : 2;
    if (g_hook) {
        g_hook(kind, title);
        Log("beat: sting %s: hook called", BeatName(kind));
    } else if (g_cfg.sting[slot][0]) {
        const BOOL ok = PlaySoundA(g_cfg.sting[slot], nullptr, SND_ASYNC | SND_FILENAME | SND_NODEFAULT);
        Log("beat: sting %s: %s %s", BeatName(kind), g_cfg.sting[slot], ok ? "playing" : "not played");
    } else {
        Log("beat: sting %s: hook point (no hook, no [beats] sting file set)", BeatName(kind));
    }
}

float Smooth(float a, float b, float x) {
    const float t = (std::max)(0.0f, (std::min)(1.0f, (x - a) / (b - a)));
    return t * t * (3.0f - 2.0f * t);
}

// [devtools] force_big_message=<gxt key>: put that message up through the game's own
// calls (the beats' check without a mission, a death or an arrest), once per change.
void DevtoolsTrigger() {
    const char* ini = ViewModes().devIniPath;
    if (!ini || !ini[0]) return;
    static int clock = 0;
    static char last[16] = {};
    if (++clock % 15) return;
    char key[16] = {};
    GetPrivateProfileStringA("devtools", "force_big_message", "", key, sizeof key, ini);
    if (!strcmp(key, last)) return;
    strcpy(last, key);
    if (!key[0]) return;
    bool ok = false;
    GTA2_TRY {
        const uintptr_t text = *reinterpret_cast<const uintptr_t*>(kTextObject);
        const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(kHudObject);
        if (text > 0x10000 && hud > 0x10000) {
            typedef const char16_t*(__attribute__((thiscall)) * Lookup)(void* self, const char* key);
            typedef void(__attribute__((thiscall)) * Set)(void* self, const char16_t* text, int priority);
            const char16_t* s = reinterpret_cast<Lookup>(kTextLookup)(reinterpret_cast<void*>(text), key);
            if (s) {
                reinterpret_cast<Set>(kBigMessageSet)(reinterpret_cast<void*>(hud + kBigMessage), s, 3);
                ok = true;
            }
        }
    } GTA2_EXCEPT { ok = false; }
    Log("devtools: force_big_message %s (%s)", key, ok ? "shown through the game's own call" : "failed");
}

}  // namespace

const BeatState& Beat() { return g_beat; }

const char* BeatName(BeatKind kind) {
    switch (kind) {
        case BeatKind::Wasted: return "WASTED";
        case BeatKind::Busted: return "BUSTED";
        case BeatKind::Complete: return "JOB COMPLETE";
        default: return "none";
    }
}

void BeatsSetStingHook(BeatStingHook hook) { g_hook = hook; }

void BeatsUpdate(const PlayerState& player, bool street, float px, float py, float pz, float yaw, float dt) {
    LoadConfig();
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    if (street) DevtoolsTrigger();

    // The big message this frame.
    int count = 0;
    char16_t text[kBigTextChars + 1] = {};
    GTA2_TRY {
        const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(kHudObject);
        if (hud > 0x10000) {
            const uint8_t* b = reinterpret_cast<const uint8_t*>(hud + kBigMessage);
            count = b[0];
            if (count) memcpy(text, b + 2, kBigTextChars * sizeof(char16_t));
        }
    } GTA2_EXCEPT { count = 0; }
    text[kBigTextChars] = 0;
    static int lastCount = 0;
    static std::u16string lastLetters;
    const std::u16string letters = count ? Letters(text, kBigTextChars) : std::u16string();
    // Fresh: it was not up last frame, or its words changed, and its countdown has barely
    // started (a view switch in the middle of one does not start a beat late).
    const bool fresh = count >= 75 && (lastCount == 0 || letters != lastLetters);
    lastCount = count;
    lastLetters = letters;

    BeatState& b = g_beat;
    if (fresh && street && g_cfg.enabled) {
        LoadTexts();
        const BeatKind kind = Classify(letters);
        const std::string words = Utf8(text, kBigTextChars);
        if (kind == BeatKind::None) {
            Log("beat: big message \"%s\" (count %d): no beat", words.c_str(), count);
        } else if (b.kind == BeatKind::None || kind != b.kind) {
            b = BeatState{};
            b.kind = kind;
            static uint32_t serial = 0;
            b.serial = ++serial;
            g_respawnAt = -1.0f;
            b.titleText = words;
            g_farFrames = 0;
            if (g_prev.valid) {
                b.x = g_prev.x; b.y = g_prev.y; b.z = g_prev.z; b.yaw = g_prev.yaw; b.inVehicle = g_prev.inVehicle;
            } else if (player.valid) {
                b.x = px; b.y = py; b.z = pz; b.yaw = yaw; b.inVehicle = player.inVehicle;
            } else {
                // Lost already (a car that blew up under him): where he was last seen.
                b.x = g_prev.x; b.y = g_prev.y; b.z = g_prev.z; b.yaw = g_prev.yaw; b.inVehicle = g_prev.inVehicle;
            }
            // The game moved him before its message (seated blast: the hospital body is found on
            // the message's frame): frame the place he died, as classic does, not the new body.
            g_heldDeath = false;
            const bool anchorHeld = g_cfg.anchorDeath && kind != BeatKind::Complete;
            if (anchorHeld && g_last.valid && g_lastAge < 1.5f && std::hypot(b.x - g_last.x, b.z - g_last.z) > 6.0f) {
                Log("beat: %s anchor at %.2f,%.2f,%.2f would be %.1f blocks from where he was %.2f s ago: held there (death place)",
                    BeatName(kind), b.x, b.y, b.z, std::hypot(b.x - g_last.x, b.z - g_last.z), g_lastAge);
                b.x = g_last.x; b.y = g_last.y; b.z = g_last.z; b.yaw = g_last.yaw; b.inVehicle = g_last.inVehicle;
                g_heldDeath = true;
            }
            Log("beat: %s start \"%s\" at %.2f,%.2f,%.2f yaw %.0f%s%s%s", BeatName(kind), words.c_str(), b.x, b.y, b.z,
                b.yaw * 57.29578f, b.inVehicle ? ", in a car" : "", player.valid ? "" : ", player not found",
                g_heldDeath ? ", the death place (already moved)" : "");
            Sting(kind, words.c_str());
        }
    }
    // Last frame's place for the next beat's anchor: only a place that did not jump.
    {
        const bool jump = g_prev.valid && player.valid && std::hypot(px - g_prev.x, pz - g_prev.z) > 3.0f;
        // A jump leaves no anchor for one frame; the frame after, the new place counts.
        g_lastAge += dt;
        if (player.valid && !jump) { g_last = Seen{true, px, py, pz, yaw, player.inVehicle}; g_lastAge = 0.0f; }
        if (player.valid && !jump) g_prev = Seen{true, px, py, pz, yaw, player.inVehicle};
        else if (player.valid) g_prev = Seen{false, px, py, pz, yaw, player.inVehicle};
        else g_prev.valid = false;   // (the last place is kept for a lost start)
    }
    if (b.kind == BeatKind::None) return;
    if (!street) {   // back to the classic view: the beat ends at once
        Log("beat: %s ended by the classic view", BeatName(b.kind));
        b = BeatState{};
        return;
    }
    b.t += dt;
    const float t = b.t;
    if (b.kind == BeatKind::Complete) {
        const float T = g_cfg.completeSecs;
        const float in = Smooth(0.0f, 0.9f, t), out = 1.0f - Smooth(T - 1.0f, T, t);
        b.camera = (std::min)(in, out);
        b.letterbox = (std::min)(Smooth(0.0f, 0.45f, t), 1.0f - Smooth(T - 0.6f, T, t));
        b.tint = 0.6f * b.letterbox;
        b.title = (std::min)(Smooth(0.25f, 0.6f, t), 1.0f - Smooth(T - 0.9f, T - 0.3f, t));
        b.black = 0.0f;
        b.hudHide = 0.65f * b.letterbox;
        if (t >= T) {
            Log("beat: %s end after %.1f s", BeatName(b.kind), t);
            b = BeatState{};
        }
        return;
    }
    // WASTED / BUSTED: framed on the body (or the arrest) until the game moves him, under
    // a fade to black from fadeAfter; found again far away (hospital, station) or lost for
    // good: fade in from black over 0.7 s, back on the chase camera.
    const float moved = player.valid ? std::hypot(px - b.x, pz - b.z) : 0.0f;
    // The body may slide or be thrown a little after the message: followed while close.
    if (player.valid && moved < 2.5f && g_respawnAt < 0.0f) {
        const float k = 1.0f - std::exp(-dt / 0.3f);
        b.x += (px - b.x) * k; b.y += (py - b.y) * k; b.z += (pz - b.z) * k;
    }
    // Put back: found far away for a third of a second running (one far frame is the
    // locator glancing at the new body before the game uses it).
    g_farFrames = player.valid && moved > 6.0f ? g_farFrames + 1 : 0;
    // A held death place: he is far from the start, so the cut waits for the black.
    const bool respawned = g_farFrames >= 10 && t > (g_heldDeath ? g_cfg.fadeAfter + 0.5f : 1.0f);
    if (g_respawnAt < 0.0f && (respawned || t > g_cfg.maxSecs)) {
        g_respawnAt = t;
        Log("beat: %s: %s after %.1f s (moved %.1f blocks)", BeatName(b.kind), respawned ? "respawned" : "no respawn seen",
            t, moved);
    }
    // The game moves him about 70 frames after its message (run qb17_beats6: BUSTED at the
    // kerb, the new body found 2.7 game seconds later), so the screen is black by then.
    const float toBlack = Smooth(g_cfg.fadeAfter, g_cfg.fadeAfter + 0.5f, t);
    if (g_respawnAt < 0.0f) {
        b.camera = Smooth(0.0f, 0.7f, t);
        b.letterbox = Smooth(0.0f, 0.45f, t);
        b.tint = Smooth(0.0f, 0.8f, t);
        // FIX-HUD-3 (pmq10): the title is up at once (0.12 s, under its scale-in) and stays through
        // the fade to black (hud3d draws it over the black); it leaves with the cut below.
        b.title = Smooth(0.0f, 0.12f, t);
        b.black = toBlack;
        b.hudHide = b.letterbox;
    } else {
        // The cut has happened under the black (or happens now, if it came first).
        const float since = t - g_respawnAt;
        const float from = (std::max)(b.black, 0.0f);
        b.camera = 0.0f;
        b.black = from * (1.0f - Smooth(0.15f, 0.85f, since));
        b.letterbox = 1.0f - Smooth(0.2f, 0.9f, since);
        b.tint = b.letterbox * 0.6f;
        b.title = (std::min)(Smooth(0.0f, 0.12f, t), 1.0f - Smooth(0.0f, 0.3f, since));
        b.hudHide = b.letterbox;
        if (since >= 0.9f) {
            Log("beat: %s end after %.1f s", BeatName(b.kind), t);
            b = BeatState{};
        }
    }
}

}  // namespace gta2dx9
