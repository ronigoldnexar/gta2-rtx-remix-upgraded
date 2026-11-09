// City life in the street views (AI-TRAFFIC-PEDS): how pedestrians react to
// gunfire, to cars coming at them and to burning cars, sized for a camera that
// stands in the street instead of looking down on a 12 x 9 block window; and a
// census of what the peds and the traffic round the player are doing, logged as
// `ai:` lines for docs/city-ai.md and tools/ai_census.py.
//
// gta2.exe's own AI runs unchanged; this moves three of its distances and calls
// its own objective routine. Everything it writes into the game's code goes back
// as shipped in the classic view.
//
// [city_ai] in gta2dx9.ini (all documented there); GTA2DX9_CITY_AI=0 in the
// environment turns the behaviour off and keeps the census, for before/after runs.
#pragma once

namespace gta2dx9 {

void CityAiInstall(const char* iniPath);

// Once a frame from WorldView::MatchGameViewToFrame, on the game's thread.
// groundView: a chase or first-person view is up. player: the player's ped
// (nullptr when not found), x/y in tiles.
void CityAiUpdate(bool groundView, const void* playerPed, bool playerValid, float playerX, float playerY);

}  // namespace gta2dx9
