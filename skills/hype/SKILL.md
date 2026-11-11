---
name: hype
description: "Use when the user wants a video, trailer, promo, demo reel or showreel of what was built in this session. Make it with the hype_render tool."
---

# Hype: a launch trailer of what this session built

`hype_render` turns this session into a finished, narrated video. It reads the session itself, so don't ask
the user to explain the project. The product is the hero (about 70 %: hook, name and one-liner, 2-4 feature beats)
and the session is the proof (about 30 %: real diffs, terminal output, green tests, computed stats). Code,
commands, output and numbers on screen are verbatim from the session; the model only picks, orders and narrates.
It renders locally with headless Chromium and ffmpeg and narrates with Hermes `text_to_speech`.

## When to use it

- The user asks for a video, trailer, promo, launch clip, demo reel, "showreel" or "something to post" about
  what you built together.
- After shipping something visual or demoable you may offer it once. Don't render unasked: a film takes minutes.
- The user typed `/hype ...` themselves: that command already runs it; don't call the tool as well.

## Pick the route (keep the user's words verbatim)

| The user asks for | Call with |
|---|---|
| a preset, maybe a length or aspect ("a 30 s pixel trailer, vertical") | `style`, `seconds`, `aspect` |
| a preset **plus changes** ("the launch one, but pink and playful with a punchier ending") | `style` + `customize: "<their words>"` |
| exact values ("accent #00e5ff, title ORBIT QUEST, high energy") | `style` + `knobs: {"accent": "#00e5ff", "title": "ORBIT QUEST", "energy": "high"}` |
| something no preset is ("a noir detective story where the tests crack the case") | `direction: "<their words>"` (a Directed film) |
| a preset that turns into another style or world midway | `style` + `direction` (the Director starts from that preset) |
| Blender, "real 3D", "use blender" | add `engine_3d: "blender"` (or keep "use blender" in the direction) |

Customizing keeps the preset and changes its look, words, music and pacing with one validated change set; a
request that needs new scenes or another style midway is routed to the Director automatically. Directed films are
one-offs: the Director writes, renders, critiques and revises, which takes about 15-30 minutes and real model
usage, so say so before you start one.

## Parameters

- `mode`: `product` (launch trailer, default), `lore` (the making-of), `speedrun` (the build as a speedrun with a
  live split timer from the session's real timestamps).
- `style`: `launch` (default), `cinematic`, `pixel`, `terminal`, `blueprint`, `comic`, `ink`.
  `hype_status` with `{"styles": true}` lists what this install can render.
- `seconds`: 30, 60 or 90 work best (15-180). `aspect`: `16:9`, `9:16`, `both` (`1:1` is experimental).
- `voice`: false = captions only. `preview`: true = a fast 540p draft.
- `customize`: a free-text change to the chosen preset.
- `knobs`: exact values, no model needed: `accent`, `palette`, `bg`, `text`, `font`, `music`, `energy`
  (calm, normal, high), `narration`, `voice` (whisper, warm, deep, bright, playful, serious), `voice_speed`,
  `title`, `tagline`, `cta`, `product`, `logo` (an image path), `captions`, `transitions`, `length`, `aspect`,
  `language` (es, fr, de, ja, ...). Values and aliases are in `docs/CUSTOMIZE.md` in the plugin folder.
- `direction`: a free-text creative brief for a Directed film.
- `product`: a brief for when the session alone doesn't say what was built (below).
- `engine_3d`: `browser` (default, three.js), `blender` (the user's own Blender 4.2+; slower, nicer 3D) or `auto`.
- `wait_seconds`: how long to wait before returning a job id (default 270).

```json
{"mode": "product", "style": "launch", "seconds": 30, "aspect": "both",
 "customize": "pink and playful with a punchier ending"}
```

## Reading the result

The result is JSON. When `status` is `done`, put the `media_tag` (`MEDIA:<path>`) on its own line in your reply so
the video is delivered (`outputs` has one file per aspect). If `status` is still a working stage (`storyboard`,
`render`, `mix`, ...), tell the user it is going and call `hype_status` with the `job_id` later; don't start a
second render. On `success: false`, relay `error.message` and `error.hint` plainly. Pass on `warnings` that matter,
such as an ignored knob or a Blender fallback.

## Product brief (only facts from this session)

```json
{"product": {"name": "Focusfox", "one_liner": "A minimal pomodoro timer for deep work",
             "url": "http://127.0.0.1:5173/", "features": ["25/5 focus timer", "Task list", "Dark mode"],
             "kind": "web_app"}}
```

Hype screenshots the product with its own headless browser when a local URL is reachable, but it never
starts servers or runs commands. To film the live app, start it first with your normal, approved tools and wait
until it answers. Then pass `product.url`, and stop the server afterwards if you started it only for the film.
Public URLs are used only if they already appeared in this session.

## Troubleshooting

- "No Chromium" or "ffmpeg not found": `hermes pm install chromium` or `hermes pm install ffmpeg`;
  `hermes hype doctor` shows what was found.
- Captions but no voice: the TTS provider failed (the job log names the line). Narration at the wrong pace:
  `tts.<provider>.speed` in config.yaml overrides the per-call speed.
- A Directed film fell back to a preset: the Director hit an error or its budget, and the job log says why.
  Suggest the `quick` effort (`/hype ... quick` or the `effort` setting), a shorter direction, or
  customizing a preset instead.
- Blender asked for but not found: the film uses the browser engine and warns. Set `blender_path` or
  `HYPE_BLENDER`.

## Privacy

Secrets, emails and home paths are redacted before anything goes to the model or onto the screen, but
screenshots are not redacted. If the session showed sensitive pages, say so, and suggest the Desktop studio's
storyboard editor (drop those scenes, re-render) before the user posts the film.
