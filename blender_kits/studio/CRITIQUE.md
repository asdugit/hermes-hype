# Studio kit — keyframe critique log (preview tier)

Test product until B1's car lands: self-made CC0 coupe (`tests/blender_kits/studio/make_testcar.py`), crude on
purpose (boxy body, simple wheels) — judge the stage/camera/light, not the model.

## ph1 (product_hero 16:9, orbit, reveal) — 4/10
- Framing and the eased orbit are right; car grounded (wheels on the floor, soft contact shadow under the body);
  rims draw the silhouette out of darkness at t=0 (nice).
- t=1.6 s completely blown out: the sweep strip ran at 2200 W × r² scaling = ~15× the key; the sweep must be a
  specular streak, not a flood → diffuse_factor 0.12 and ~700.
- Same rear-rim floor blob as the device kit (bright white pool front-right); black void backdrop (cyc glow
  missing); tyres read grey under AgX (rubber ok up close).

## W5 (2026-11-11, B1's test car `testmedia/car3d/car.glb`, preview + final)
- The glb's body paint imports WHITE (the exporter drops a node-driven base colour) -> `paint` param (hex) recolours
  the largest non-glass material, drops node-driven roughness (crisp candy coat). Default yaw showed the REAR: this
  car faces +Y (glTF-conformant models face -Y) -> the sample passes `yaw: 118`.
- Final at full light: the red washed to salmon, sweep blew the flank white (5/10) -> `exposure` -0.6 EV default,
  AgX Punchy look, sweep 700 -> 420, reveal starts at 12 % (dim silhouette on frame 1, the film never opens black).
  After: deep red, crisp highlights, no blown areas (7/10). Backdrop stays near-black (car floats a little; the
  floor reflection is faint) - next: a brighter cyc glow for large products.
