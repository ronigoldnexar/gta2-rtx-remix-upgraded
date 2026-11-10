#pragma once
// FIX-COCKPIT-CAB-6 (qav51): the driver's seat of an open-top car body that names none, found in its own
// mesh: the cockpit well (the cushions seen from above, well under the body's beltline, just behind the
// windscreen). Used when the manifest has no "driver_seat" and car_glass found no cabin behind glass (an
// open top has none): the sprite's window rows put the 031 Jefferson's driver on its long bonnet.
namespace gta2dx9 { struct Model; }

// out: hip distance from the centre line, cushion top (from the model's lowest point), hip along the
// car, headliner (the body's height: open): model frame, as Model::driverSeat. Cached per model.
// False when the body has no well (a closed roof covers the cabin) or the seat is turned off
// ([devtools] seat_well=0 / GTA2DX9_SEAT_WELL=0: the sprite's seat, as before).
bool SeatWellFor(const gta2dx9::Model& model, float out[4]);
