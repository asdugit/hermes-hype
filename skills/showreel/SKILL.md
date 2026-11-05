---
name: showreel
description: "Use when the user wants a video, trailer, promo, demo reel or showreel of what was built in this session. Make it with the showreel_render tool."
---

# Showreel: a launch trailer of what this session built

`showreel_render` turns this session into a finished, narrated video: the product is the hero (about 70 %:
hook, name and one-liner, 2-4 feature beats) and the session is the proof (about 30 %: real diffs, terminal
output, green tests and computed stats). Everything on screen is verbatim from the session; the model only
picks and orders events and writes narration. It renders locally with headless Chromium and ffmpeg.

## When to use it

- The user asks for a video, trailer, promo, launch clip, demo reel, "showreel" or "something to post" about
  the thing you built together.
- After shipping something visual or demoable, you may offer it once ("Want a 60 s launch trailer of this?").
  Don't render unasked: a film takes minutes of CPU.
- The user typed `/showreel ...` themselves: that command already runs it; don't call the tool as well.

## How to call it

```json
{"mode": "product", "style": "launch", "seconds": 60, "aspect": "16:9"}
```

- `mode`: `product` (launch trailer, default), `lore` (making-of story), `speedrun` (the build as a speedrun
  with a split timer).
- `style`: `launch` (default), `pixel`, `terminal`, `blueprint`, `cinematic`. `showreel_status` with
  `{"styles": true}` lists what this install can render.
- `seconds`: 30, 60 or 90 work best (15-180 accepted). `aspect`: `16:9`, `9:16` (vertical) or `both`.
- `voice`: false for captions only. `preview`: true for a fast 540p draft.
- `direction`: any free-text creative brief ("pixel art that blooms into an anime flower field, sell the
  product") makes a Directed film; keep the user's words.

The result is JSON. When `status` is `done`, put the `media_tag` (`MEDIA:<path>`) on its own line in your
reply so the video is delivered. If `status` is `rendering`, tell the user it is still going and call
`showreel_status` with the `job_id` later (do not start a second render). On `success: false`, relay the
`error.message` and `error.hint` plainly.

## Product brief (when the session alone doesn't say what was built)

Pass `product` so the trailer names and sells the right thing. Use only facts from this session:

```json
{"product": {"name": "Focusfox", "one_liner": "A minimal pomodoro timer for deep work",
             "url": "http://127.0.0.1:5173/", "features": ["25/5 focus timer", "Task list", "Dark mode"],
             "kind": "web_app"}}
```

## Live product capture

Showreel captures the product with its own headless browser when a local URL is reachable, but it never
starts servers or runs commands itself. If the user wants the real app in the film:

1. Start the app first with your normal, approved tools (for example a background terminal running the dev
   server), and wait until it answers on its local URL.
2. Call `showreel_render` with `product.url` set to that local URL.
3. Stop the server afterwards if you started it only for the film.

Public URLs are used only if they already appeared in this session. Without a reachable URL the film uses
the session's own screenshots and artifacts.

## Privacy

Secrets, emails and home paths are redacted before anything goes to the model or onto the screen, but
screenshots cannot be redacted. If the session showed sensitive pages, say so and suggest the Desktop pane's
storyboard editor (drop those scenes, then re-render) before the user posts the film.
