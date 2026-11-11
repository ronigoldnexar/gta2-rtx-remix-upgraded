// FIX-COCKPIT-BODY (owner items 2 and 3, 10 Nov 2026): the two looks of the first-person view at the wheel.
//
//   cockpit (default): the cab (cab_interior) with the wheel turning the car's way and the driver's own
//                      seated body (live_geometry: torso, lap, legs to the pedals, arms from the shoulders to
//                      the hands on the rim, in his identity record's clothes; [camera] fp_driver_body);
//   dashcam:           a clean forward view from a camera on the windscreen: no wheel, column, hands or body,
//                      the eye a little higher, forward and toward the car's middle, no head lean or body roll
//                      (a level horizon). The HUD stays.
//
// The dashcam is a choice the player makes with [camera] dashcam_key (default C) while at the wheel in first
// person; it stays chosen through a view cycle (V) and a get-out/get-in, and only shows in first person in a
// car ([camera] dashcam=1 starts with it chosen). Neither look changes the other: each is gated on its own flag.
#pragma once

namespace gta2dx9 {

// dllmain: reads [camera] dashcam, dashcam_key, dashcam_up, dashcam_ahead, dashcam_centre, fp_driver_body.
void CockpitModeLoad(const char* iniPath);
// view_modes, once a frame: polls the dashcam key (a press toggles; `allowed` = the game window has the keys,
// no menu, Alt up) and whether the player is at the wheel in first person now (`atWheelFirst`).
void CockpitModePoll(bool allowed, bool atWheelFirst);
// Whether the dashcam is chosen (whatever the view).
bool DashcamChosen();
// 0 (cockpit) .. 1 (dashcam), eased over 0.4 s from each press; 0 out of first person or out of a car.
float DashcamBlend();
// The cab's wheel, hands and body give way from the switch's midpoint (blend >= 0.5).
bool DashcamHidesCockpit();
// The dashcam eye against the driver's: up and ahead (blocks), and the share of the way to the car's middle.
void DashcamOffsets(float* up, float* ahead, float* centre);
// [camera] fp_driver_body (default 1): the driver's body in the cockpit view.
bool DriverBodyEnabled();
// FIX-COCKPIT-CAB-7 (qaexp77): [camera] dashcam_cowl (1: the seat bonnet runs to the eye in the dashcam, no dash top)
bool DashcamCowl();

}  // namespace gta2dx9
