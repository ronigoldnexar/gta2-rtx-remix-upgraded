// QB-17/18: the framed beats of the street views - WASTED, BUSTED and JOB COMPLETE.
//
// The game says all three the same way: its "big message" (the HUD object at
// [0x672F40]+0x2854, drawn by HUD part 15; FUN_004C6060 sets it from a text key and
// starts its countdown byte at +0 from 90, the text itself a UTF-16 copy at +2). The
// death and arrest keys come from the player's death kind (FUN_004A4E10: "wasted",
// "fried", "nicked" - BUSTED!, "shocked"); JOB COMPLETE is a script message ("1124",
// "3100", "2999"). So a beat starts the frame a fresh big message appears whose text
// is one of those keys' texts in the game's own data\e.gxt.
//
// A beat is: the camera leaves the chase and frames the player (view_modes.cpp, an
// orbit and push-in around where he stood when it began), the screen gets letterbox
// bars, a tint and the title in the HUD's face (hud3d.cpp, which then drops the game's
// own part 15 draw), and a music sting hook fires. WASTED and BUSTED end by fading to
// black until the game has put him back (hospital, police station), then fade in; JOB
// COMPLETE swings the camera back behind him and hands over.
//
// Classic view: nothing (the top-down view stays byte-for-byte the game's).
// Settings: [beats] in gta2dx9.ini (documented there).
#pragma once

#include <cstdint>
#include <string>

namespace gta2dx9 {

struct PlayerState;

enum class BeatKind { None = 0, Wasted, Busted, Complete };

struct BeatState {
    BeatKind kind = BeatKind::None;
    uint32_t serial = 0;        // bumped at each beat's start
    float t = 0.0f;             // seconds since it began
    float camera = 0.0f;        // the camera's share (0 the chase, 1 the beat's framing)
    float letterbox = 0.0f;     // 0..1 of the bars' full height
    float tint = 0.0f;          // 0..1 of the colour wash
    float title = 0.0f;         // 0..1 of the title's opacity
    float black = 0.0f;         // 0..1 fade to black (the respawn cut hides under it)
    float hudHide = 0.0f;       // how much of the modern HUD steps aside
    // Where he was when it began (renderer frame: x east, y up, z north), his facing
    // (renderer yaw) and whether he sat in a car.
    float x = 0.0f, y = 0.0f, z = 0.0f, yaw = 0.0f;
    bool inVehicle = false;
    std::string titleText;      // the game's own words for it, UTF-8 ("WASTED!")
};

// Once a frame from the camera solver, before it places the camera. `street` false in
// the classic view (no beat starts there). `px/py/pz` and `yaw` the player in the
// renderer frame when `player.valid`.
void BeatsUpdate(const PlayerState& player, bool street, float px, float py, float pz, float yaw, float dt);

const BeatState& Beat();
inline bool BeatActive() { return Beat().kind != BeatKind::None; }
const char* BeatName(BeatKind kind);

// The music sting hook: called once at each beat's start (on the render thread). One
// hook; nullptr clears it. Without one, [beats] sting_wasted / sting_busted /
// sting_complete name a .wav played asynchronously (PlaySound), if set.
typedef void (*BeatStingHook)(BeatKind kind, const char* title);
void BeatsSetStingHook(BeatStingHook hook);

}  // namespace gta2dx9
