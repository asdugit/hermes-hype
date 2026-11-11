# Device kit — keyframe critique log (preview tier, 960×540 / 540×960, Orbit Notes captures)

Notes written right after each look (vision on contact sheets). Scores are my honest read vs an Apple launch film.

## dh1 (device_hero 16:9, first pass) — 3/10
- Geometry right: lid opens on the hinge, screen upright, not mirrored, slim bezels, keyboard + trackpad.
- Screen WRONG: hot pink rings + diagonal shape over the UI = glossy coat reflecting lights; values >1 clip to
  magenta in the Standard view. → screens get no coat by default (`glare` 0).
- Floor/backdrop: huge white blobs (light reflections in the glossy floor), floor reads mid-grey, not premium.

## dh2 — 4/10
- Screen now saturated violet with banding rings: the screen was built BEFORE the view switched to Standard, so the
  texture kept the inverse-AgX colourspace (oversaturates + amplifies 8-bit steps). → `studio.finalize()` re-syncs
  every screen to the final view (`materials.sync_screens`).

## dh3 / dh5 — 5/10
- Screen faithful: sampled (162,133,243) vs source (166,137,249) at a slightly different spot; nav bar + hero
  readable, correct orientation.
- Remaining: big soft white blobs bottom-left/right = REAR RIM lights' grazing glossy reflection on the floor in
  front of the device (not the cards: moving the cards changed nothing). Black void above the horizon (the bg spot
  on a near-black cyc does nothing). Keycaps read light grey (rough plastic integrating the big front card),
  aluminium deck reads dark (reflects the dark world), base front bevel highlight thick/glowy.
- → rims at subject height aimed slightly UP (cones never pool in front), emissive radial glow on the cyc (art-
  directable gradient backdrop), low front card behind the lens for the deck, keys darker/less rough, thinner bevels.

## dh5v (9:16 phone hero) — 5/10
- Phone right: screen faces camera, rounded display corners, bezel, punch-hole camera; mobile capture readable.
- Same floor glare problem; white speckle along the phone's right edge mid-turn (preview ray-tracing noise on the
  bevel highlight); the punch-hole sits on the UI header (realistic, but shrink it).

## df1 (device_feature 16:9, bbox = hero headline + CTA, click on "Start free") — 7/10
- The push lands exactly on the rect, centred; cursor arrow correct orientation and size, glides in and presses
  on the button. Strong, readable, premium-ish.
- Issues: 14° oblique + f/2.8 at 0.2 m → "Your" (left end of the headline) defocused → fixed f/7 for the push.
  Ripple not visible in the sampled frames (fades in 0.55 s after the click; sample closer to the click to verify).
  First frame shares the floor-glare blob.

## W5 round 1 (2026-11-11, preview 960x540, real Orbit Notes captures from session B, Blender 5.2.3)
- b1 (B2's last state): every scene had a huge white vertical streak on the floor beside the device = the REAR RIM
  strips' specular reflection in the glossy cyc floor (rims aimed up did not help). Hero 4/10, END 4/10, FEATURE 5/10
  (push lands on the rect but ends as a flat full-frame screenshot, 3D lost), SCROLL 5/10 (fill 0.78 = screen only,
  top bezel cropped, reads flat).
- Fix: light linking (`studio.exclude_receivers`): rims + sweep EXCLUDE the cyc (EEVEE 5.2 honours it). b2: streaks
  gone, floor clean with a soft device reflection. Hero 6/10, END 6/10.
- Remaining (b2 full frame): deck/keyboard read dark grey (metal sees only the dark world behind the lid; top
  softbox has spec 0), thin noisy highlight speckles on the lid's left edge (preview RT), device centred in HOOK/TITLE
  while the kit:type title sits left (needs `space`).
- b3-b4: `space` left honoured (device right, left third dark: the kit:type title sits there) 7/10; FEATURE push now
  stops with the whole screen at ~1.15 frame widths and a 20 deg angle: the bezel edge stays in frame, reads 3D
  6/10; SCROLL fill 0.55 shows the device (keyboard + bezel) and the page stays readable 6/10. Deck now silver
  (bead-blasted alu 0.42 + top softbox specular, light-linked off the floor).
- First real Quick x Blender film (preview, Orbit Notes session B, launch style, 30 s): HOOK/TITLE text left +
  device right works; FEATURE lower-third fine; END: the centred kit:type/end-lockup sat on top of the laptop
  (device_end space left) = collision; film frame 0 black (HOOK reveal from darkness; video QA thumbnail warning).
  -> HOOK mapping `reveal: false` (lit from frame 1); END mapping `space: none, size 0.6, defocus 0.85`: the device
  starts sharp and melts into a soft bokeh glow behind the centred lockup + scrim (6/10, reads as an end card).
- 9:16: phone hero/END showed the DESKTOP capture cover-fitted into the phone (text cut mid-word: "ur ideas, in o")
  because the mapping passes the desktop image as media -> `phone_media()`: a phone always prefers the mobile
  capture unless the given media is portrait; pipeline asset names (`m3_mobile_390x844`) now match by token.
  END 9:16 size formula fixed (phone filled the frame). Decks blew out white in 9:16 close-ups -> top softbox
  specular 0.5 -> 0.25.
