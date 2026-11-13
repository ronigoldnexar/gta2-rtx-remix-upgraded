# City map and GPS navigation (CITYMAP-1)

A full-screen map of the level with a waypoint and a GPS route, in every view (classic, third
person, first person, on foot and in a car) under the plain renderer and RTX Remix. The game is
not changed: the map is drawn by the DLL, the route is computed from the level's own `.gmp`, and the
game only ever sees fewer key presses while the map is open.

Code: `dll/src/city_map.cpp` (input, route state, the map, the chevrons), `dll/src/city_route.cpp`
(surfaces, graphs, search, route lines, the map picture), the mini-map and classic disc in
`dll/src/hud3d.cpp` (`DrawGpsOnDisc`, `DrawGpsChip`, `DrawClassicGps`), the key hold in
`dll/src/view_modes.cpp` (`ViewSetMapHold`). Offline reference and route test: `tools/citymap/`
(Python; `routetest.py` checks every step against the arrows). Settings: `[citymap]` in
`package/gta2dx9.ini`.

## Using it

| Key | Map closed | Map open |
|---|---|---|
| M (`[citymap] key`) | open the map | close it |
| Esc | (the game's quit prompt) | close the map (the press never reaches the game) |
| arrows | (the game's) | move the cursor; at the map's edge the view follows |
| mouse | - | the cursor; drag pans; the wheel zooms at the cursor |
| + / - / Page Up / Page Down | - | zoom at the cursor |
| click, Enter, Space | - | set the waypoint at the cursor (snapped to the nearest road of the main network) |
| right click, Del, Backspace | - | clear the waypoint |
| Home | - | back to you |

The waypoint clears itself 3.5 s after you arrive (within 2.5 blocks of it).

## Decisions

- **No pause.** GTA2 has no single-player pause the DLL could trigger: measured (`out/cm_pause1`,
  two frames 2 s apart under each key), the world runs on under the Esc quit prompt, P and Pause;
  the only freeze is the minimised-window pump the DLL deliberately keeps from starting
  (FIX-STABILITY-2), and patching the game loop is out of bounds. So the map is drawn over the
  running game, under an 86 % scrim, and while it is open every game control key is withheld
  through the DirectInput filter the camera-relative controls and the knock-down hold already use
  (arrows, fire, enter and jump through the hold's reconcile, so a key held as the map opens is
  released for the game; any other key's press is dropped, its release passes). He stands still, or
  his car rolls to a stop. The V, C and mouse-look keys of the DLL are ignored while it is open. If
  he is hurt (health drops) or wanted, a red chip in the map's header says UNDER ATTACK / WANTED
  with the stars and the M key, so he can close it at once.
- **Units.** One block is 4 m (`kCityMapMetresPerBlock`, the Remix scene's scale: sceneScale
  0.0025); every distance on the map, the mini-map chip and the classic disc uses it.
- **On foot** the route uses roads, pavements and parks, either way, pavements preferred (cost 1.0,
  park 1.15, road 1.35) and walls respected; **in a car** only roads, following the lane arrows.
  Getting in or out of a car re-searches in the other mode (a few ms).
- **Classic view**: nothing is drawn while no waypoint is set (the classic view stays the game's,
  pixel for pixel: vreg spawn_classic). With a waypoint, a north-up GPS disc bottom left in the
  classic HUD's style (a black rim and GTA2's yellow ring, yellow read-out on a dark plate).
- **3D guidance**: magenta chevrons flat on the route's lane for about the next 36 m (1.25 blocks
  apart, fading in from 1 block and out from 6.5 to 9.5 blocks), 55 % opacity, pulsing gently only
  within the 3 blocks before a turn. They are drawn in the HUD's screen-space pass, projected with the
  street view's own camera (`MapObjectsProject`), so plain and Remix show the same thing and Remix's
  denoiser never sees them. Left out where they would be hidden: behind a wall (the camera's own map
  sight line, `ViewLineWalled`), and inside the projected box of a nearer car (his own too in third
  person, not from the driver's seat) or person.

## The road graph

Built once per level from the map the world was drawn from (`CityMapSetLevel`, ~35 ms), the picture
baked on a worker thread (~0.8 s) into one 2048x2048 DXT1 texture with mips (2.7 MB), put on the
device (MANAGED) only while the map is open and released 10 s after it closes.

## Drawing (and the 2560x1440 finding)

The map, the chevrons and the danger chip are Dear ImGui draw lists rendered by `RenderUi` in
`city_map.cpp`, not by `imgui_impl_dx9`: the vertices go up with `DrawIndexedPrimitiveUP` from system
memory and the font and map textures are MANAGED, with `imgui_impl_dx9`'s states (an orthographic
projection, Z writes off: RTX Remix takes the draws as UI and rasterises them over the traced frame).
Reason (CITYMAP-1 gate 2, from a trailer dry run): under Wine at 2560x1440 the device reports **0 MB
of texture memory left** (the post-FX targets, the HD tiles and the model textures spend Wine's
emulated budget), `CreateVertexBuffer` in D3DPOOL_DEFAULT fails with D3DERR_OUTOFVIDEOMEMORY and
`imgui_impl_dx9` silently draws nothing. That also hides the **modern HUD** at 2560x1440 (hud3d's
"render" time 0.002-0.004 ms in those runs, without any city-map code: tr_chase2/3), so it is not the
map's alone. Even our textures cannot be paged in with 0 MB left; the prefix needs a larger budget:
`[HKEY_CURRENT_USER\Software\Wine\Direct3D] "VideoMemorySize"="4096"` (measured: 2.8 GB left at
1440, the map and the modern HUD both drawn, out/cm_probe1440v with an install.reg override).

- **Nodes**: the lid of every block whose ground type is road, pavement or field, not water, not
  built over; its height at each edge from the slope tables (block z spans z..z+1, a flat lid is at
  z+1, the game's z of a man standing on it; "up" ramps rise to the north - checked on every
  7-degree ramp chain: the low piece meets level z-1, the high piece level z).
- **Car edges** from the lane arrows: bits 1 west, 2 east, 4 north (-y), 8 south, the red arrows
  the same four bits up by 4 and treated as roads (bil's flyovers carry them). Right-hand traffic:
  1392 "north lane east of south lane" pairs against 0 in wil (1327/0 ste, 1220/0 bil). A road
  cell with no arrows (car parks, yards) goes any way at a higher cost (1.4); a lane change onto a
  lane running the same way costs 1.6. Neighbours connect only where their edge heights meet, so a
  deck and the road under it never touch: bridges and tunnels are routed on their own level.
- **Walk edges** as above (undirected, symmetric costs).
- **Main network**: the largest strongly connected set (Kosaraju), per mode; waypoints are snapped
  onto it (within 40 cells), so a waypoint is always reachable from the network.
- **Search**: one backward Dijkstra from the waypoint gives every node's cost to it and its next hop
  (2-9 ms in game). A route from anywhere is a walk down the next hops, so a wrong turn costs no new
  search: the route is re-picked from where he is when he has been more than 2.6 blocks (car; 2.2
  on foot) off it for 0.6 s, at most every 0.5 s (logged `citymap: route (off the route by ...)`).
  The start is chosen near him (within 4, then 8, 16, 24 cells) by its cost plus twice the distance
  plus a penalty for a lane running against his heading (about a block's loop to turn round).
- **Unreachable**: if nothing near him reaches the waypoint (a closed yard, an island) the route
  starts at the nearest node that does, with a dashed hop from him to it.
- **Lines**: the map and mini-maps draw the road's middle (runs of one direction moved onto the middle
  of their cross-section, lane changes folded away, corners rounded); the chevrons follow the lane.

## Verification

See the CITYMAP-1 gate reports (sheets under the agent's scratchpad) for frames; the log says it all:
`citymap: level ...` (graph), `citymap: waypoint ...`, `citymap: route ...` and `citymap: route lane
...` (the lane's corners, which the scripted driver `gamerun/citymap_drive.py` drives), `citymap:
guide ...` every 2 s (where he is on the route, distance left, next turn, chevrons drawn / walled /
covered), `citymap: map opened/closed`, `citymap: the game's control keys withheld/back`.
Probes: `gamerun/keys_citymap_probe1.sh` (classic map, a click, the disc, third/first on foot),
`gamerun/keys_citymap_drive.sh` (CM_LEVEL, CM_START, CM_DEST: a car, the click, the drive).
[devtools] `citymap_waypoint=x,y` / `clear`, `citymap_open=1/0`, `citymap_view=x,y,pixels-a-cell`
(at 720 lines) are re-read twice a second for scripted tests.
