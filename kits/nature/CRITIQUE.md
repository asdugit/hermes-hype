# Nature kit — visual critique log (vision reviews of keyframes vs research/ref-flowerfield.md)

## v1 (ff1, flower-field sunset, GPU 1080p, t=2/8)
Reads: promising — anime meadow mood, pink/cream gradient, layered purple ridges, dense white-daisy foreground with
convincing DOF blur on pink blossoms, glossy red cars clean.
Problems:
1. Clouds almost absent (only thin wisps) — sky is an empty gradient; need big painterly masses lit from below.
2. Sun hidden behind the drive-slope hill (right); no disc, rays invisible. Move sun left/centre.
3. Hill too big/steep/close, dull olive-brown, sparse flowers; drive-slope car tilted ~25° at the far edge.
4. Meadow too white (daisy carpet), little colour variety, grass tufts sparse/dark — needs yellow/lilac/lupine + lush green.
5. Mountains = flat stripes; need peaks / more ridge amplitude; a pale flat "lake" band at the left horizon
   (far terrain fogged to haze) — cover with a near hazy hill layer.
6. Cars feel pasted: add warm sun rim + stronger grade; two cars clustered top-left at t=2 (descend + float entering).
7. Whole frame washed pink (mist + haze too strong), top of frame still pink: lavender/indigo should arrive by ~20°.

## v2 (ff2, t=9)
Better: clouds now present with lit edges; peaked mountain layers; meadow colour variety (pink/white/yellow + grass);
4 cars at different depths/sizes. Still wrong:
1. Clouds swirly/smeared (too much domain warp + streak texture), dark saturated purple streaks — want soft
   horizontal cumulus banks, lavender tops, warm undersides.
2. Sun still hidden (low band + ridges reach above el 3°). Raise sun to ~5.5°, lower far ridge.
3. Mountains: too many sharp regular triangle peaks, too contrasty — softer, hazier, fewer peaks.
4. Bottom 30% is a wall of blurred pink blossoms across the whole width — corners should frame, centre more open.
5. Drive-slope car rolls ~20° on screen (looks like it is crashing) — clamp roll ±8°.
6. Descend + float cars both in the top band (symmetric); hero car too crisp/saturated vs the soft plate,
   rim light not visible.
7. Pale flat "lake" band still at far left horizon.

## v3 (ff3, t=10)
Sun now visible at the horizon with a lovely halo; clouds read as soft anime masses (pink undersides, lavender tops);
mountains soft. Remaining:
1. Bottom 35% still a wall of blurred pink (near field 6.5–12 m: tall cosmos ~230 px, mildly defocused) — reads as
   haze, not flowers. Anime BG: mid meadow crisp, only the extreme corners defocused.
2. Cars pasted: hero car crisp, saturated, studio-lit, no rim; too big and jammed into the top-left corner.
3. Cloud edges a touch too soft/blobby.
Fixes: sparser near rows + grass-first foreground, shorter cosmos, cocK 92→64; heavier grade + whole-silhouette
backlight rim + warmer halo on cars; hero car smaller/inward; crisper cloud edges.

## v4 (ff4, t=5/11)
t=5 composition is good (hero car upper-left of centre, float car mid-right, sun halo between them). Remaining:
1. Near grass renders as pale yellow vertical streaks (tip tint + backlight too strong) — needs green blades.
2. Car "rimAll" outline reads as a white sticker border — remove; keep only the warm sun-side rim.
3. Petals barely visible (tiny specks) — refs have petals drifting across the whole sky at many depths.
4. Only one framing blossom visible (bottom-left); they sit below the frame edge — raise them, bring inward.
5. Rise car passes right next to the hero car (cluster) — route it up past the sun instead.
6. Flat pale band at the far-left horizon = fogged far terrain — lighter terrain fog.

## v5 (ff5 + low-DOF debug)
Composition now good: 4 cars at 4 depths/sides (hero upper-left, float upper-right, rise passing the sun, one on the
slope). Debug render (dof 0.15) revealed:
1. The pale "yellow streaks" are `seedhead` sprites (dense wheat ears read as yellow bars) + blurred sprites clipped
   by their atlas cell edges (hard vertical edges). → fewer/smaller seedheads, edge-fade in the sprite shader.
2. Framing blossoms + foreground band are passed by the camera dolly (placed at 1.4–2.5 m from the start pose,
   the drift moves 4 m forward) → move them to a camera-following "near" mesh with 0.75 follow (slow parallax).
3. Petals are visible when sharp but DOF spreads near petals into invisibility → petal CoC ×0.35, max level 3.

## v6 (ff6, t=1/7.5/14)
No more streaks; green grass; petals visible in the sky; a big blurred blossom now frames the bottom; at t=14 the
slope car has driven down into the meadow under the sun (lovely), hero upper-left, float upper-right.
Remaining: framing blossoms drift toward the centre (follow 0.75 + 4.5 m lateral drift) → follow 0.9, corners only;
hero car gets cropped by the end of the drift → lateral drift 4.5 → 3 m.

## v7 (CPU low tier, sky-reveal, product-hero)
- CPU low tier (960×540 internal, 3.6k field sprites) holds the look: framing blossoms in both corners, meadow a bit
  sparser on the hill. A thin light outline around cars at low res = the all-round rim → removed (sun-side rim only).
- product-hero v1: car small and the sun beside it → v2: camera yawed to the sun, car at 19 m directly under the sun:
  warm backlit halo around the car on the hilltop, framing blossoms — reads as a hero shot.
- sky-reveal: the plane-projected cloud field degenerates overhead (empty lavender, then swirls/mirrored blobs when
  hacked) → cross-fade to an angular-space cloud field above ~20°. Overhead clouds now soft cumulus with some
  ring-shaped holes (acceptable; could be improved with a dedicated high-altitude layer).

## v8 (real runtime, 15 s 1080p video, frames 0.5/5/10/14.7)
Shot progresses well: cars enter at different times on different paths (hero descends top-left, float drifts in,
rise passes the sun, slope car drives down into the meadow), camera drift gives parallax, framing blossoms hold
the corners. Runtime seed gives a lupine/yellow meadow variant — also lovely.
Fixes: no product in frame 0 (descend starts too high → y0 1.5 → 1.15 so it is in by ~0.5 s); bare near ground
with dark lupine dabs visible at bottom-centre at t≈0.5 (field started at 6.5 m, ground enters frame at 5.6 m)
→ field from 5 m and terrain dabs fade out within 9 m.
