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
