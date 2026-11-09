// Positional sound for the street views (quality bar row 13).
//
// GTA2 places every sound it plays in the world (cars, gunfire, sirens,
// explosions, peds) by one routine: the source's position minus the listener's
// (the top-down camera), in the game's fixed-point units. The 2D mixer pans by
// the x of that offset and the Miles 3D path (do_3d_sound=1) places the voice
// at (x, 0, -y): both assume north is "ahead" and east is "right", which is
// what the screen shows from above. From behind the player that is wrong: a car
// behind the chase camera was heard as if it were on screen.
//
// Both callers of that routine are routed through us. In the third- and
// first-person views the offset is turned into the camera's frame (right is
// the camera's right, ahead is where it looks) and measured from the player
// rather than from the game's camera, which leads a fast car by several blocks.
// The classic view is left exactly as the game had it.
//
// [audio] in gta2dx9.ini: positional=1 (default) / 0; listener=player|game;
// log_every=N writes one `audio3d:` line every N positioned sounds (0 off).
#pragma once

namespace gta2dx9 {

void Audio3DInstall(const char* iniPath);
bool Audio3DAvailable();

}  // namespace gta2dx9
