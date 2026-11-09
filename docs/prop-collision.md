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
