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
