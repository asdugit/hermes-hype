# Showreel

**An engine inside a Hermes plugin: type `/showreel` and the session you just worked in becomes a narrated
launch trailer for the thing you built.**

![Showreel: the product, a red car, flies alongside the camera over a pink meadow while dozens of red cars stream across the sky and a lone figure watches from the flowers](docs/media/hero_v2.webp)

*8 seconds from Showreel's hand-directed hero film: one continuous Blender shot (`blender_kits/meadow/oner.py`)
through the opt-in Blender engine, after a pixel-art boss battle. Rendered by Showreel's own pipeline: Blender
for the 3D, HTML scenes in headless Chromium, original music and SFX, ffmpeg.*

[![CI](https://github.com/asdugit/hermes-showreel/actions/workflows/ci.yml/badge.svg)](https://github.com/asdugit/hermes-showreel/actions/workflows/ci.yml)
License: AGPL-3.0-or-later · Hermes Agent >= 0.22.5 · Windows, macOS, Linux

## Why it's different

- **Zero prompting.** `/showreel` reads the session itself: what you asked for, the files that were written, the
  diffs, the terminal output, the passing tests, the screenshots, the app it built. You don't explain the project
  or paste anything into another AI. The product is the hero (about 70 %); the session is the proof (real diffs,
  real terminal, real numbers, about 30 %). Nothing on screen is made up: code, commands, output and stats are
  verbatim from the session, and the model only picks, orders and narrates them.
- **Presets that are fully customizable.** Seven polished styles, three kinds of film (trailer, lore,
  speedrun), 30/60/90 s, 16:9 or 9:16. Change any preset's colours, fonts, music, energy, voice and words by just
  saying so.
- **A free-roam engine.** Don't want presets? Write a direction in plain words and the Director engine writes a
  treatment, codes the scenes it needs, renders keyframes, has a vision critic score them, and revises before the
  final render. Kits, proven blueprints, schema repair and measured gates carry the craft; smaller models get a
  simpler compose path (pick a blueprint, write the words, the engine assembles and checks the film). The goal is
  that any model can make a cinematic film.

## Quick start

```bash
hermes plugins install asdugit/hermes-showreel
hermes plugins enable showreel        # if the installer did not enable it
```

Then, in any chat where you built something:

```text
/showreel                       a 60 s launch trailer of what this session built (launch style, 16:9)
/showreel lore                  the making-of: the build story is the hero (aliases: bts, process, making-of)
/showreel speedrun              the build as a speedrun: live split timer, real timestamps, a PB card
/showreel pixel 30 vertical     any style, length and aspect, in any order
/showreel comic 90 both mute    16:9 and 9:16 from one storyboard, captions only
```

Arguments are free-order: `[lore|speedrun] [style] [30|60|90] [vertical|both] [mute] [blender]`.
A preset film takes a few minutes: 30 s films took about 4-8 minutes in our end-to-end runs, on a laptop busy
with other renders. In Desktop and the TUI the command answers at once and the
film renders in the background, with progress in the chat. In CLI and messaging sessions it waits and then
sends the video.

`/showreel styles`, `/showreel status`, `/showreel cancel` and `/showreel help` do what they say.
`/showreel revise <notes>` makes a new cut with your notes.

## Presets

| Style | Look |
|---|---|
| `launch` (default) | Premium product-launch motion graphics: graphite stage, UI panels on a lit table, one accent colour |
| `cinematic` | Captures become lit cards in dark 3D space; letterbox, serif titles, a slow camera with weight |
| `pixel` | 16-bit arcade: pixel art, chiptune, quest log, the product as a boss or an item-get |
| `terminal` | Phosphor CRT: box-drawn panes, typed commands, odometer stats, scanlines |
| `blueprint` | Engineering drawing: plotted line art, dimension lines, revision clouds for diffs |
| `comic` | Motion comic: halftone panels, speech balloons, onomatopoeia |
| `ink` | Hand-drawn explainer: warm paper, sketchy ink, sticky notes and a little robot |

Every style has its own original music beds and sound effects, and works in all three kinds of film:
**trailer** (default: the product), **lore** (the making-of) and **speedrun** (the build against the clock).
Lengths: 30, 60 or 90 s (anything from 15 to 180 works). Aspects: 16:9, 9:16 or both (1:1 is experimental).

### Customize any preset

Presets are a starting point, not a cage. Say what you want after the style, or set a knob directly:

```text
/showreel launch pink and playful with a punchier ending
/showreel terminal green phosphor hacker vibe, faster
/showreel cinematic accent=#ff4f8b title="Tally" tagline="Your bank CSV, finally readable"
/showreel pixel 30 energy=high music=pixel_boss cta="Try it today"
/showreel ink language=es voice=warm logo=~/brand/logo.png
```

- **Knobs** (`key=value`) are exact and need no model: accent, palette, background and text colours, font,
  music, energy, narration, voice and pace, title, tagline, call to action, product name, logo, captions,
  transitions, length, aspect and language. Unknown keys get a friendly list of the valid ones.
- **Plain words** after a preset are read by a keyword reader (no model) and one small model call over the
  preset's own film, validated and repaired before anything changes: palette, words, music, pacing, shot order and
  holds. Facts (code, stats, terminal output) are never rewritten, and a weak model or no model still gives a
  customized film.
- **Routing.** A preset plus words customizes that preset. Words without a preset make a Directed film. A preset
  plus something it can't do (another style midway, new scenes, "free roam") goes to the Director, starting from
  that preset.
- The same works in the Desktop studio (Customize preset, with a knobs row), the tool (`customize`, `knobs`) and
  the CLI (`--customize`, `--set KEY=VALUE`). Defaults for every film: the `customize` setting.

Every knob, what it accepts and how the free text is read: [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md).

## Don't want presets? Here's the engine

Free text without a preset (or asking a preset for something it can't do) is a **direction**, and the film
becomes a **Directed** film:

```text
/showreel pixel but transition into a different style mid way through, goal is to sell the product
/showreel a noir detective story where the bug is the culprit and the test suite cracks the case
```

The Director engine runs a production pipeline with your Hermes model:

1. **Treatment**: logline, acts, a style per act, the signature moment, the music plan.
2. **Film script**: shots, transitions, overlays and cues, validated against a typed schema.
3. **Scene code**: where the built-in kits lack a scene, the model writes one against Showreel's scene SDK.
   Generated scenes are linted (no network, no timers, no randomness), dry-run in Chromium and probed for
   determinism before anything is rendered.
4. **Critic**: keyframes go onto contact sheets, and a vision critic scores product clarity, composition, craft,
   story, legibility, style coherence and transitions against an 8/10 bar. It also measures how much of the
   film shows the product.
5. **Revise** until the bar is met or the round budget (`effort`: quick, standard or max) runs out; the best
   version wins.
6. **Final cut**: render, music fitted to the cut, narration, mix, and the same video and audio quality gates
   as presets.

You can watch all of it live in the Desktop studio. Scenes that pass the critic are saved to your library
(`plugin-data/showreel/library/`) and can be reused by name in later films ("use my boss-battle scene").
If the Director fails, you still get a preset film in the style you asked for.

Directed films cost real model usage. In our trials with a frontier model, a standard-effort film took about
25 minutes and about US$7 of model usage, and a quick one about 14 minutes and US$3. Presets make a few model
calls per film.

### Blender (optional 3D engine)

3D shots render in headless Chromium (three.js) by default. Add `blender` to the command
(`/showreel cinematic 60 blender`), say "use blender" in a direction, or set `engine_3d: blender` (or `auto`) to
render them with **your own installed Blender 4.2+**: real 3D products, smooth spline cameras, motion blur.

- Showreel runs your Blender as a headless subprocess with `--factory-startup` (your preferences and add-ons are
  not loaded or changed), on a job file in the film's job folder, and composes the frames with the rest of the
  film. Cancelling stops only the Blender process Showreel started.
- Blender is found through `SHOWREEL_BLENDER`, the `blender_path` setting, `PATH`, then the usual install folders,
  including where the official Hermes `blender` plugin installs it. **Showreel never downloads Blender.** Without
  it, the film falls back to the browser engine and the job log says so.
- Blender is slower (about 0.5-1 s per 1080p frame with EEVEE on a desktop GPU). Showreel times 3 frames first
  and shows the estimate, and caches rendered shots so a revision re-renders only what changed.

## Desktop studio

In Hermes Desktop, Showreel adds a **studio** as a right-side pane and as a full page (sidebar: Showreel),
command-palette entries ("Showreel: make a trailer of this chat", lore, speedrun, open the studio), a status-bar
chip with live progress, and a Showreel card around the video player when the agent's `showreel_render` tool
returns a film.

![The Make page: kind of film, the seven styles with their preview loops, length, aspect, narration, and "Customize this preset" (free text plus accent, energy, music, font and voice knobs) or Free roam for the Director](docs/screenshots/studio-make.png)

![Watching the Director work: treatment, scenes being coded, the critic's round-1 scores against the 8/10 bar and the keyframes it saw](docs/screenshots/studio-director.png)

![The pane while a preset film renders: stages with timings, ETA and a warning from the render](docs/screenshots/pane-live.png)

*These screenshots are the real `desktop/plugin.js` rendered by our test harness (`tests/desktop`: React in
jsdom against a stub of the Desktop SDK, sample data, an approximate dark theme), not captures of the installed
app. Icons show as plain squares because the harness has no icon font. The style previews and the Director
contact sheet are real Showreel output.*

Tabs: **Make** (kind, style gallery, format, then *Customize this preset* with a knobs row or *Free roam* for a
direction) · **Live** (stages, ETA, cancel, the Director at work) ·
**Storyboard** (edit titles and narration, drop or reorder scenes, re-render without a model call) · **Result**
(player, reveal file, render the other aspect, copy post text, revise) · **Library** (saved Director scenes).

## Agent tool and CLI

The agent gets two tools and a bundled skill that tells it when to use them:

- `showreel_render`: makes a film (`mode`, `style`, `seconds`, `aspect`, `voice`, `customize`, `knobs`,
  `direction`, a `product` brief, `preview`, `engine_3d`). It waits up to about 4.5 minutes, then returns
  `MEDIA:<path>`; longer renders keep going and return a `job_id`.
- `showreel_status`: a job's progress or result, or the list of styles.

So "make a 30 second vertical promo of what we built" works in plain chat. From a shell:

```bash
hermes showreel render --session latest --style terminal --seconds 60 --aspect both
hermes showreel render --style terminal --customize "green phosphor, faster" --set accent=#00ff66
hermes showreel render --direction "a heist film where the tests are the vault" --effort quick
hermes showreel styles
hermes showreel doctor          # checks Chromium, ffmpeg, Blender (optional), assets and the runtime
hermes showreel status
```

## Settings

Desktop → Capabilities → Plugins → Showreel, or `plugins.entries.showreel.settings` in `config.yaml`:

| Setting | Default | Meaning |
|---|---|---|
| `default_style` | `launch` | Style when the command names none |
| `default_seconds` | `60` | Length (15-180) |
| `aspect` | `16:9` | `16:9`, `9:16`, `both` or `1:1` (experimental) |
| `narration` | on | Off = captions only; nothing is sent to your TTS provider |
| `narration_speed` | empty | Empty = each style's pace (cinematic 1.13, others 1.0) |
| `redact` | on | Redact secrets, emails and home paths before the model and the render |
| `effort` | `standard` | Directed films: quick, standard or max critique rounds |
| `max_parallel_workers` | `0` | Render workers; 0 = automatic from free RAM |
| `engine_3d` | `browser` | `browser`, `blender` or `auto` |
| `blender_path` | empty | Path to Blender; empty = auto-detect |
| `customize` | empty | Default knobs for every preset film, e.g. `accent=#ff4fa3 energy=high` (lowest priority) |

The storyboard uses the auxiliary task `showreel` (Hermes `auxiliary` settings), so you can point it at a
cheaper model than your main one.

## Requirements

| | Windows | macOS | Linux |
|---|---|---|---|
| Hermes Agent | >= 0.22.5 | >= 0.22.5 | >= 0.22.5 |
| Chromium | Hermes-managed (`hermes pm install chromium`) or installed Chrome / Edge / Chromium | same | same |
| ffmpeg | Hermes-managed (`hermes pm install ffmpeg`), `SHOWREEL_FFMPEG`, or on `PATH` | same (ffprobe not needed) | same |
| Narration | your Hermes TTS (`text_to_speech`; Edge by default) | same | same |
| Blender (optional) | 4.2+, or install it with the official Hermes `blender` plugin | same | same |

No Python packages beyond what Hermes already ships (zero declared dependencies). About 0.5-0.7 GB of RAM per
render worker. A GPU helps but isn't needed: Chromium falls back to software rendering.

## Privacy and what the plugin does on your machine

Read this before installing. Showreel:

- **Reads your session.** It reads the Hermes session it films from the session database (`state.db`),
  **read-only**: your prompts, the agent's messages, tool calls, terminal commands and output, file writes and
  diffs, screenshots and images. That is the chat you are in by default; the CLI and tool can name another
  session. Screenshots and images the session made are copied into the job folder.
- **Reads your project, to film the product.** It opens the product the session built (HTML files it wrote, and
  `localhost`/`127.0.0.1` URLs that appear in the session) in its own headless Chromium and takes screenshots,
  and it reads media and 3D model files the session produced. It never starts servers or runs project commands,
  and it doesn't open public URLs during capture.
- **Reads two sections of `config.yaml`, read-only:** `tts` (to warn when your TTS settings override the
  narration pace) and `plugins.entries.showreel` (its own settings, for the Desktop studio).
- **Sends text to your model.** A redacted digest of the session (secrets, key-shaped tokens, emails and home
  paths removed; `redact` setting) goes to the model you use in Hermes through Hermes' plugin LLM API, as the
  auxiliary task `showreel`. Directed films make many calls and also send keyframe contact sheets (images) to
  that model for the critic. This uses your provider account and costs what your provider charges.
  Redaction is best effort and does not touch pixels: screenshots in the film are shown as they were. Review the
  storyboard and drop scenes before you post.
- **Sends narration text to your TTS provider** through Hermes' `text_to_speech` (Edge, the default, is a
  Microsoft online service). `mute` or `narration: off` sends nothing.
- **Runs subprocesses:** headless Chromium, ffmpeg and, only when you ask for it, your Blender. All with fixed
  argument lists. During a render it also serves the job folder to its own Chromium from a local web server on
  `127.0.0.1` with a random port and path; render pages can't reach the network.
- **Runs in the background.** Films render in background threads (one heavy render at a time) and can take
  minutes; Directed films can take 15-30 minutes. Cancel from the studio or with `/showreel cancel`. Unloading the
  plugin stops its renders.
- **Writes** job folders under `<HERMES_HOME>/plugin-data/showreel/jobs/`, saved Director scenes under
  `plugin-data/showreel/library/`, and finished videos to `<HERMES_HOME>/cache/generated/videos/`.
- **Does not:** send telemetry, update itself, download anything (fonts, music, three.js and Rough.js ship in the
  repo; Blender is never downloaded), read credentials, or need any API key.
- The package also contains developer harnesses (`python -m showreel_core.pipeline`, `...story.try`,
  `...director.try`) that can call `hermes chat` as a subprocess. The plugin's command, tools, CLI and Desktop
  studio never run them.

## Troubleshooting

- **"No Chromium found"**: `hermes pm install chromium`, or set `SHOWREEL_CHROMIUM` to a Chrome/Edge/Chromium
  executable. `hermes showreel doctor` shows what was found.
- **"ffmpeg not found"**: `hermes pm install ffmpeg`, or set `SHOWREEL_FFMPEG`.
- **Captions but no voice**: your TTS provider failed (the job log says which line). With Edge, an outdated
  `edge-tts` package can get HTTP 403 from Microsoft; update Hermes. If narration plays at the wrong pace, remove
  `tts.<provider>.speed` from `config.yaml` (it overrides per-call speed; the job log warns about it).
- **The studio says "The Showreel backend is not running"**: enable the plugin for the agent too
  (`hermes plugins enable showreel`), then restart Hermes.
- **A Directed film fell back to a preset**: the Director hit an error or its budget; the job log says why.
  Try the `quick` effort (`/showreel ... quick` or the `effort` setting), a shorter direction, a stronger model,
  or customize a preset instead.
- **Slow renders**: use `preview` (540p) for a first look, lower `max_parallel_workers` if RAM is tight, and keep
  Blender for when you want it.
- **Blender not found**: set `blender_path` or `SHOWREEL_BLENDER`; Blender 4.2 or newer is required.

## Development

```bash
python -m pytest -q                 # fast suite; slow real-Chromium tests: --runslow
cd tests/desktop && npm ci          # enables the Desktop render check (node >= 22.22)
hermes plugins validate . && hermes plugins doctor --ci .
```

CI runs the fast suite on Windows, macOS and Linux, and `hermes plugins validate --install-deps` against a
pinned Hermes release. Architecture and contracts: `showreel_core/contracts.py`; kits: `kits/<style>/KIT.md`;
Blender scene modules: `blender_kits/`.

## Credits

- Code: © 2026 asdugit and the Showreel contributors, AGPL-3.0-or-later (`LICENSE`).
- Music and sound effects: original, procedurally composed by this repository's own code (`tools/compose`); no
  samples, recordings or AI-generated audio (`assets/audio/LICENSE.md`).
- Fonts: SIL Open Font License 1.1, licence text next to each font in `kits/*/fonts/`.
- three.js r170 (MIT, `vendor/three/LICENSE`) and Rough.js 4.6.6 (MIT, `kits/ink/vendor/LICENSE-roughjs.txt`).

Details: [CREDITS.md](CREDITS.md). Built for the Nous Research Hermes Agent plugin hackathon, largely with Hermes.
