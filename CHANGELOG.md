# Changelog

## 1.0.0 (2026-11-11)

First public release, built for the Nous Research Hermes Agent plugin hackathon.

**Zero prompting**
- `/showreel` reads the current session read-only (prompts, tool calls, diffs, terminal output, tests,
  screenshots) and finds the product it built. Nothing to explain, nothing to paste into another AI.
- Product capture: Showreel screenshots the app the session built (HTML files and `localhost` URLs from the
  session) in its own headless Chromium. It never starts servers.
- Truth on screen: code, commands, output and stats are verbatim from the session; the model picks, orders and
  narrates them. Redaction of secrets, emails and home paths runs before the model and the render.

**Presets, fully customizable**
- 7 styles: launch, cinematic, pixel, terminal, blueprint, comic, ink. Each has its own scene kit, fonts,
  original music beds and sound effects.
- 3 kinds of film: trailer (the product is the hero), `lore` (the making-of) and `speedrun` (a split timer
  running on the session's real timestamps).
- 30/60/90 s (15-180), 16:9, 9:16 or both from one storyboard (1:1 experimental), narrated with your Hermes TTS
  or captions only.
- Customize any preset with knobs (accent, font, music, energy, voice, title, tagline, CTA, logo, language) or in
  plain words (`/showreel launch pink and playful`). See `docs/CUSTOMIZE.md`.

**Free-roam engine**
- Any free-text direction makes a Directed film. The Director engine writes a treatment and a film script, codes
  the missing scenes against the scene SDK (linted, dry-run, determinism-probed), has a vision critic score the
  keyframes against a rubric, revises, then renders. Effort sets the number of critique rounds: quick, standard
  or max.
- A library of scenes that passed the critic, reusable by name in later films.
- Optional Blender engine for 3D shots (`blender`, "use blender" or `engine_3d`). It uses your own Blender 4.2+
  and never downloads one.

**Everywhere in Hermes**
- `/showreel` in Desktop, the TUI, the CLI and messaging. In messaging the finished video is sent back to the
  chat.
- Agent tools `showreel_render` and `showreel_status`, with a bundled skill.
- `hermes showreel render|styles|doctor|status`.
- Desktop studio (pane and page): style gallery with preview loops, live progress, watch the Director work,
  storyboard editing with re-render and no model call, result player, revise, library. Also palette commands, a
  status-bar chip and a tool-media card.

**Quality gates on every film**: layout QA (clipped text, safe areas, minimum glyph size), a determinism probe,
decoded-frame and black-frame checks, loudness at -14 LUFS with a true-peak ceiling, and a speech-band SNR check.
Fallbacks at every stage, so a render always finishes.
