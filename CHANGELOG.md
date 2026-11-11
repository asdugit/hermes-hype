# Changelog

## 1.0.0 (2026-11-11)

First public release, built for the Nous Research Hermes Agent plugin hackathon.

**Zero prompting**
- `/auteur` reads the current session read-only (prompts, tool calls, diffs, terminal output, tests,
  screenshots) and finds the product it built. Nothing to explain, nothing to paste into another AI.
- Product capture: Auteur screenshots the app the session built (HTML files and `localhost` URLs from the
  session) in its own headless Chromium. It never starts servers.
- Truth on screen: code, commands, output and stats are verbatim from the session; the model picks, orders and
  narrates them. Redaction of secrets, emails and home paths runs before the model and the render.
- Earlier Auteur films of the same session (their tool calls, MP4s and contact sheets) are left out of the
  evidence, so a second film is about the product, not about the first film.

**Presets, fully customizable**
- 7 styles: launch, cinematic, pixel, terminal, blueprint, comic, ink. Each has its own scene kit, fonts,
  original music beds and sound effects.
- 3 kinds of film: trailer (the product is the hero), `lore` (the making-of) and `speedrun` (a split timer
  running on the session's real timestamps).
- 30/60/90 s (15-180), 16:9, 9:16 or both from one storyboard (1:1 experimental), narrated with your Hermes TTS
  or captions only.
- Knobs on every preset, with no model call: accent, palette, bg, text, font, music, energy, narration, voice,
  voice_speed, title, tagline, cta, product, logo (a corner bug), captions, transitions, length, aspect and
  language. They work as `key=value` in `/auteur`, as the tool's `knobs`, as `hermes auteur render --set`,
  from the Desktop knobs row, and as defaults in the `customize` setting. Unknown keys get a friendly list.
- `energy=high` keeps the requested length: it cuts the dead air after each line and spends it on more shots
  (cut-ins of the product) and product holds; the narration is never sped up. *Playful* requests spring the type
  (theme `motion: bouncy`) and bring the candy palette.
- Free-text customization of a named preset (`/auteur launch pink and playful with a punchier ending`): a
  keyword reader (no model) plus one small model call over the preset's own film. The reply is parsed tolerantly,
  validated and repaired: params must be declared by the scene, facts are never rewritten, TITLE and END stay.
  Edits run on the timeline, so narration, captions and cues move with their shot. Cached per job, so the second
  aspect and revisions make no new call.
- Routing rule: preset + words customizes the preset; words without a preset make a Directed film; a preset plus
  a restructuring ask (another style midway, new scenes, "free roam") goes to the Director, starting from that
  preset.
- A theme layer every kit honours: CSS variables injected page-wide, plus the colours kits draw in JS (pixel
  palette words, comic and ink palettes, any hex terminal phosphor, captions, the cinematic three.js room).
- Full reference: `docs/CUSTOMIZE.md`.

**Free-roam engine**
- Any free-text direction makes a Directed film. The Director engine writes a treatment and a film script, codes
  the missing scenes against the scene SDK (linted, dry-run, determinism-probed), has a vision critic score the
  keyframes against a rubric, revises, then renders. Effort sets the number of critique rounds: quick, standard
  or max.
- Model tiers: strong models may write custom scenes; other models stay on the kit and library scenes; small
  models (haiku/flash/mini class) take a compose path: pick a proven blueprint, write the words, and the engine
  assembles the film. Every reply is auto-repaired (lenient JSON, schema coercion, misspelt scene ids snapped to
  the catalog). Without vision, a measured review (product size and visibility, layout QA, frozen frames, story
  timing) stands in for the critic.
- Fallbacks: free path → compose path → an engine-built film with no model → a preset film. Browser stalls and
  Blender memory waits are retried instead of being treated as a bad film.
- A library of scenes that passed the critic, reusable by name in later films.

**Blender (opt-in)**
- `blender` in the command, "use blender" in a direction, or `engine_3d: blender|auto` renders 3D shots with your
  own Blender 4.2+, headless with `--factory-startup`, on files in the job folder. Never downloaded; without it
  the film falls back to the browser engine and says so.
- Preset films map their product shots to Blender scenes (`device/*` for screens, `studio/*` for 3D models);
  Directed films can use those plus the meadow oner. Rendered shots are cached by content, so a revision
  re-renders only what changed. In 9:16 the devices are phones showing the phone capture, and the title words sit
  in the top band above the device.

**Everywhere in Hermes**
- `/auteur` in Desktop, the TUI, the CLI and messaging. In messaging the finished video is sent back to the
  chat.
- Agent tools `auteur_render` and `auteur_status`, with a bundled skill.
- `hermes auteur render|styles|doctor|status`.
- Desktop studio (pane and page): style gallery with preview loops, *Customize this preset* or *Free roam*, live
  progress with a calibrated ETA, watch the Director work, storyboard editing with re-render and no model call,
  result player, revise, library. Also palette commands, a status-bar chip and a tool-media card.

**Quality gates on every film**: layout QA (clipped text, safe areas, minimum glyph size), a determinism probe,
decoded-frame and black-frame checks, loudness at -14 LUFS with a true-peak ceiling, and a speech-band SNR check.
Fallbacks at every stage, so a render always finishes.

**Found in real end-to-end runs and fixed**: structured output on Anthropic models (Hermes JSON mode is refused
there; the storyboard now asks for plain-text JSON after a refusal, so it comes from the model, not the
heuristic); a single screenshot stall no longer fails a film; the tool waits through the last seconds of mixing
instead of returning "rendering"; Windows clock ties, ffmpeg < 7 progress lines and `MEDIA:` paths on
macOS/Linux.
