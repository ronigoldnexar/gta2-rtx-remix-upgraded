# Street props are solid (FIX-COLLISION, 9 Nov 2026)

Owner report: "in first-person mode, you were passing through other objects ... either they should get
pushed aside, or you should not be able to pass through them." Defect
`pt-player-walks-through-street-lamps` had been closed with a see-through fade (c2bdb0c): the prop
faded out as the player reached it and he still walked through. This replaces that for the player and
for passers-by.

## How

`dll/src/prop_collision.cpp`. The game does not know the props the renderer places by rule
(`LiveGeometry::DrawProps`: lamp posts, hydrants, bins, benches, mailboxes, parking meters, stop and
one-way signs, bus shelters, park trees, dock containers and cranes, roof units), so it cannot collide
them itself. Each frame in a 3D view:

1. DrawProps publishes the footprint of every prop within 10 blocks of the player, those behind the
   camera too: the model's vertices in the body's band (the bottom 0.5 block; a tree's bottom 0.3,
   its trunk) as a circle for round things (posts, hydrant, bin, meter, signs, trunks) or a box turned
   with the prop (bench, mailbox, container, roof unit); the shelter as its posts, back and end glass
   and seat; the crane as its four legs. `collide: footprint` log lines give the sizes.
   The game's own objects drawn as models that stand in the way (phone box, traffic-light post,
   bench, planters, barriers, sandbags, crates, girder, upright drum) are added from
   `map_objects.cpp`; the ones the game itself knocks about (cones, tyres, boxes, footballs) are left
   to the game.
2. `WorldView::UpdateCamera`, before anything reads where he is: the player's body (radius 0.085
   block, 0.46 tall) is moved out of any footprint it entered, and in first person also his eye
   (0.12 ahead of the body, kept 0.11 clear), never into a map wall. The move is written into the
   game's own ped position (`WritePlayerGroundPosition`, the warp hold's writes), so the game carries on
   from there: he stops against a box, slides round a post he meets off-centre. The figure drawn this
   frame (from the game's sprite, before the move) is moved with him.
3. Bins are light: the body shoves one along at his speed, it slides on and settles in about half a
   second, turning a little when struck off-centre; against a wall or a fixed prop it holds and blocks him.
4. Passers-by on foot drawn round him (within 9 blocks) are moved out the same way (radius 0.07, no eye),
   so the overlap fade now only fires for someone deep inside a prop (beyond the solver's reach).

Not run in the classic view (no 3D props there): its frames stay the game's. GTA2DX9_PROP_COLLIDE=0 turns
it all off (the earlier fade comes back). GTA2DX9_LOG_PROPS_NEAR=1 logs the props near the player for
probes (`collide: scout`, `collide: near`). Every 300 frames with contact: `collide: over 300 frames ...`.

## Verified (private stage, runs cw1..cw4_probe, gamerun/collide_probe.py)

Downtown, each kind walked into from 1.1 block along the pavement, first person (head-on and 0.1 off
the line) and third person (a fixed side camera, GTA2DX9_REGRESS_CAM), positions every 0.4 s:

- No walk ever ended or passed with the body inside a footprint: closest approach to the prop's
  centre is always at least its radius plus the body's (posts 0.17-0.18, sign posts 0.10, trunk 0.14).
- Bench, mailbox, bus shelter, tree: stopped head-on in both views; in first person the prop stands at
  arm's length in mid-view, nothing passes the eye.
- Lamp posts, sign posts, meters, hydrants met slightly off-centre: he slides round them (as round the
  game's own wall corners) and walks on; no frame shows the eye through a post.
- Bins: shoved aside and settle upright (cw4 third person, frames 02-07); 11 shoves logged.
- Passers-by: hydrant and bench stay drawn with people walking round them (cw3 showed them fading out).
- 0 FAULT lines in all runs.

## Still short of the bar

- Thin posts are circles: walking dead on a post he stops, a hand off the line he slides round it at
  once. No brace or shoulder-bump animation plays on contact; the legs keep walking against a bench, as
  against the game's walls.
- Cars still pass through rule-placed props (the old fade hides it); bins are not knocked by cars.
- Passers-by are only kept out within 9 blocks of the player and only on foot.
- The game's own kickable objects (cones, tyres, boxes) keep the game's own behaviour.
- Close up in first person the bench, mailbox and shelter glass textures are low resolution
  (an art limit, not collision).

## Fade, light and scale of the street props (FIX-PROPS-2, 9 Nov 2026)

- **No ghosts** (defect pm16-wil-third-translucent-blue-ghost-mailbox-beside-fallen-ped): the overlap fade
  above only decides *out* or *in* now (overlap alpha under 0.5 is out); each placement keeps its own fade
  state (`s_fadeState` in `DrawProps`) that moves there by 0.17 a frame, so a prop is see-through only for
  the six frames of a fade. Before, a body that stayed in the fade band (a ped knocked into a mailbox, the
  eye 0.4 block from one) held the prop at 40% for as long as it stayed: run `fp2_fade_before2`
  (`GTA2DX9_PROP_COLLIDE=0`, eye 0.43 block from the mailbox at 124.9,138.5) logged "300 prop-frames
  see-through" per 300 frames and showed the blue ghost; the same spot after (`fp2_after1`) shows no prop
  and no ghost.
- **The chase camera's line** (defect pm20): in third person a lamp post, sign or meter that stands
  across the line from the eye to the hero's chest, between them, fades out the same way.
- **Lit** (defect pm20): the props were drawn as bare texels (`D3DTOP_SELECTARG1`), so the dark cast-iron
  lamp was a flat black silhouette and no prop had a sunlit side. `DrawProps` now lights them with the
  sun the world's faces get (world_view.cpp `DrawSkyAndShading`: the sky's sun direction, sun colour times
  `sunLight`, ambient times the daylight), plain renderer only (not under Remix). `GTA2DX9_PROP_LIGHT=0`
  draws them unlit as before. Log line `props: lit by the world's sun`.
- **Mailbox at the figures' scale** (defect pm-mailbox-prop-oversized-blue-box-on-legs, second report): an
  adult is 0.46 block (`kPedHeight`), so a block is about 3.9 m at the figures' scale, not 2 m; the 0.55-block
  box stood 2.2 m. `build_mailbox` is now 0.305 block (1.2 m), 0.134 x 0.136 footprint, with smooth dome
  normals; `DrawProps` turns it back to the wall (front to the pavement, 0.40 block from the cell centre)
  instead of a random yaw. Its body texture is a smooth painted steel (`paint()`), and the material is named
  `steel`: `import_assets.py` copies a material named `body` to a `_paint` TGA once and never again, so the
  mailbox had kept the 6 Nov noisy body texture through every regeneration (`mailbox_0_paint.tga`, removed).
- **Stop sign back** (defect pm17-wil-third-sign-panel-blank-white-slab): dark painted steel (62,65,70) with a
  brighter rolled rim, strap and bolts, instead of light galvanised grey (150) that read as a white slab in
  the sun; an octagonal edge band between face and back, so from an angle behind it the face's red rim no
  longer shows past the back; the back is 0.006 larger than the face.

Still short of the bar: the other rule props were sized at 2 m a block too (parking meter 0.635 block = 2.5 m,
stop/one-way signs 1.0-1.08 block = 4 m, hydrant 0.4 = 1.6 m, bin 0.45 = 1.75 m); the lamp's shaft is the
14-sided lathe of PROPS-SLIM (smooth now that it is lit, faceted at the base up close).

## Second street-prop pass: real sizes, glass, the booth (FIX-PROPS-3, 9 Nov 2026)

- **Every rule prop at the figures' scale** (0.263 block a metre, an adult 0.46 block; the FIX-PROPS-2
  list): `tools/gen_env2.py` authors the stop sign (75 cm octagon, centre 2.1 m, 2.5 m overall), the one-way
  plate (90 x 30 cm at 2.2 m), the parking meter (1.37 m, a 17 x 12 cm head on a 1.0 m post) and the bus
  shelter (3.4 m long, 1.4 m deep, 2.4 m to the roof, seat at 45 cm, BUS plate at 2.6 m) at their real size
  (`MPB = 0.263`); `DrawProps` scales the scanned props to 95 cm (bin, was 1.75 m), 80 cm (hydrant, was
  1.6 m) and a bench 90 cm to the top of its back (was 2.9 m long). Posts have smooth radial normals.
- **Lamp base**: the PROPS-SLIM lathe goes round in 28 steps (was 14; the cross-bar 12, was 6), 2 720
  triangles; the atlas is byte-identical, so its Remix material hash is unchanged.
- **Collision follows the drawn size**: the footprints are still taken from the mesh (scaled), with the
  sign and meter band cut to the bottom 0.25 block (at their real size the plate and the meter's head come
  down into the old 0.5 band: the post alone is solid, r 0.008 / 0.016); the shelter's hand-made pieces in
  `FootprintOf` are the new posts, back and end panes, seat and sign post.
- **Glass** (defects pm6-bus-shelter-glass-opaque-flat-pale-blue-pane, demo-phone-booth-flat-translucent-blue-
  placeholder-box): a rule prop's panes are its `<name>__glass` model (the booth's convention in
  map_objects.cpp), drawn by `DrawProps` after every opaque prop, farthest first, blended by the texture's
  alpha (about 0.13 clear glass with a faint broad sheen and a little grime at the foot: smooth gradients only,
  the booth's one-texel diagonal streaks on a 64 px sheet stair-stepped into a zigzag), no depth writes, and
  with a Blinn sun glint (`PropLightingBegin(device, true)`). `bus_shelter__glass` is new; the booth's
  `code_phone*__glass` texture is the same sheet.
- **The booth** (`tools/gen_code_objects.py`): map objects now take the sun and ambient as the props do
  (`PropLightingBegin` in `MapObjectsDraw`; spinning pickups and the `__lit` companions stay unlit), its
  paint is a shade deeper (36,84,160), and the PHONE sign box's ends are the roof's dark blue (the unlit
  near-white ends read as a floating white tab).
- Shared lighting: `PropLightingBegin/End` (live_geometry.h) replace the inline block of FIX-PROPS-2;
  `GTA2DX9_PROP_LIGHT=0` still draws both unlit.
- **Park-tree leaves** (`tools/gen_trees.py fill_transparent`): the leaf sheet was drawn on (0,0,0,0) and its
  blurred alpha gave the black round every leaf a little coverage; the props are alpha-tested at a low
  reference and model textures have one mip level, so a canopy a few blocks off sampled that black fringe.
  Every texel that is not fully opaque now carries the leaves' own colour (pull-push fill); alpha, meshes and
  bark are unchanged, only `tree_0N_1.tga` differ.
- **Not the props**: the black spiky pyramids of pm8-ste-trees-render-black-spike-shards / pm23 are the
  map's own tree blocks (sloped leaf tiles in the world mesh): runs fp3_ste_after (ste spawn, no tree prop
  within 30 blocks, the pyramids on the ridge) and fp3_hyd_wil (the church park's pyramids, block-aligned).
  The world renderer owns them. The red "flat cutout" of pm6 was the 1.6 m hydrant drawn unlit before
  a062ae0; the "blue rounded slab" of pm-mailbox report3 is the pre-a062ae0 mailbox.

Still short of the bar: the glass is alpha-blended with a fixed-function sun glint, no reflection of the
street; under Remix the new `bus_shelter__glass` and the booth's re-made glass and frame textures have no
material prims until the Remix mod is rebuilt (`linux/docker/build_remix_mod.sh`: `remix_model_pbr.py`
already treats `__glass` models as smooth glass); thin posts are still slid round, not braced against; the
map's own tree blocks are untouched.


## Pickups and covered lamp cells (FIX-FIGURE-4, 9 Nov)

Defect fixhud-street-view-weapon-pickup-solid-cannot-collect: the hero stopped short of the bil spawn's
machine gun in the 3D views. The pickup was never solid; a placed lamp post was. Its cell, the alley mouth
under the LIVE SHOW gantry, is covered, and the lamp rules read the column's top block (level 7, the gantry)
as the floor. So they found no wall beside the cell and left the post in the middle of the one-block alley,
on the only way through. Now the rules read the walkable floor's level under an overhang, and a post in a
one-block alley goes into the corner against a side wall. Separately, the game's pickups drawn each pass are
noted (`PropCollisionNotePickup`), and no prop shape within reach of one is solid: the game collects a
pickup on overlap. `GTA2DX9_LOG_PROPS_NEAR=1` lists the pickups near him (`pickup@x,y,z`) and tags a shape
`(over a pickup)`. Verified out/fig4_pk5 (third) and fig4_pk6f (first): weapon none -> machine_gun(4) on the
walk; vreg classic 0 px.

## The City Bank stair girder (FIX-COLLISION-2, 10 Nov)

Defect mg-wil-bank-stair-girder-collider-blocks-entry: BANK ROBBERY walkers pinned at the foot of the
City Bank flight (wil 191-192,177, rising west), at 193.4,177.2-177.6, beside the game's `obj_girder`
object at 193.20,177.50. The report read the near line's `obj_girder@193.20,177.50/0.28` as a 0.28 circle.
It is not one, and our collider is not what holds them:

- **What the footprint is.** `FootprintOf` gives the girder the bottom-band bounds of its drawn model, an
  oriented box: `collide: footprint obj_girder (scale 1.00, height 0.05): box 0.562x0.188`, turned with
  the object. In the world, a 0.56 x 0.19 steel plate, 0.05 block (19 cm) thick, lying across the foot of
  the flight (its length along y, 177.22-177.78), as drawn. The near line printed only a box's longer half
  side, so `/0.28` looked like a radius. It now prints a box as `/box<length>x<width>h<heading>` (full
  sides, the heading of the length in the game frame, 0 east, 90 along +y) and a circle as `/r<radius>`:
  `obj_girder@193.20,177.50/box0.56x0.19h090`. Probes parse only the `x,y` before the `/`.
- **Who pins them: the game.** Run fcol2_base2 (HEAD DLL, `gamerun/fcol2_girder.py`, walks west from x
  194.7 on fixed lines) gives the same result in classic, where prop_collision never runs, as in third
  person: on y 177.50 and 177.95 he stops at x 193.39 (193.45 in other runs: 0.10-0.16 east of the drawn plate), and on the job's line
  y 178.05 at 193.15,177.89, wedged between the plate's end and the wall that runs along y 178 west of x 193.
  On y 177.20 he climbs the flight in both views. The `collide:` lines show no contact with the girder in
  any of these runs. Of the filer's six pinned runs, only mg_km8 ever touched our box (11 frames, standing
  west of the plate). GTA2's own object collision holds a walker about one ped half-width off the plate.
  That happens in the classic view too, and the renderer cannot change it without changing the game.
- **The way on.** It is the strip between the building face (y 177) and the plate's end (177.22). The game
  lets him through there at y 177.10-177.11; our box leaves y up to 177.135 for the body (r 0.085), so it is
  never the tighter limit. Run fcol2_fix1 (this DLL): the y 177.18 line climbs to the top (z 3.00) 10 of 10
  (5 third, 5 first person), and head-on on y 177.50 he stops at the plate 10 of 10. The frames show him
  passing beside the plate's end along the wall, not on it. The job's route north of the plate (y
  177.85-178.15) is the side the game closes.

Still short of the bar: a 19 cm plate is something a person steps over or onto. Here the game stops him at
it, a hand short of its edge, legs still walking. Making it walkable needs the game's object collision for
that object type, not this file.
