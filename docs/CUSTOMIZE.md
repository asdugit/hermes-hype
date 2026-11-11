# Customizing presets

Showreel's presets (launch, cinematic, pixel, terminal, blueprint, comic, ink, plus the lore and speedrun modes)
are starting points, not fixed templates. Any request can reshape them. You get two channels, and they work on
every surface: the `/showreel` slash command, the `showreel_render` tool, the `hermes showreel render` CLI and the
Desktop Make tab.

1. **Knobs.** `key=value` settings. They are deterministic and need no model.
2. **Free text.** Name a preset and add words, for example
   `/showreel pixel make the boss a giant bug and use neon colours`. The engine starts from that preset's Quick film
   and makes one small, validated set of changes to it.

## Routing rule

| You type | Engine |
|---|---|
| `/showreel pixel 60 vertical` (no free text) | **Preset.** Quick film; knobs apply |
| a preset (style, `lore` or `speedrun`) at the start or end, plus free text | **Customize that preset** |
| a preset plus a request it cannot make: another style or world midway ("transition into a different style mid way", "then bloom into anime"), a second preset named, new or invented scenes, "free roam", "the director" | **Directed**, starting from that preset (the existing behaviour) |
| free text without a preset (`/showreel make it feel like a late-night infomercial`) | **Directed** (free roam) |
| `directed` or `customize` as the first or last word | forces that route |

A style word *inside* a sentence ("for launch day", "in pixel art") is a hint for the Director, not a preset pick.
`use blender` / `blender` keeps working on every route. Knobs apply on every route: Quick and customized films use
them directly, and the Director receives them as hints (`options.hints.customize`).

## Knobs

| Knob | Values | What it changes |
|---|---|---|
| `accent=` | `#RRGGBB`, `#RGB` or a name (`pink`, `cyan`, `neon-green`, `phosphor`, `gold`, ...) | the hero colour in every kit (see the theme layer) |
| `palette=` | `neon pastel candy noir sunset ocean night forest phosphor amber mono warm cool`, or a comma list of colours | accent, accent2, accent3, background and text together |
| `bg=` / `text=` | colours | stage background / type colour |
| `font=` | a family from the kits' OFL set: Geist, Instrument Serif, Bangers, Comic Neue, Space Mono, Fraunces, Inter, Caveat, JetBrains Mono, IBM Plex Mono, VT323, Space Grotesk, Cormorant Garamond, Silkscreen; or a mood (`comic`, `handwritten`, `serif`, `retro`, `pixel`) | display type (the font file is loaded from its kit) |
| `music=` | a bed id (`launch_a`, `comic_b`, `pixel_boss_b`, ...), a bed family (`comic`), a title (`Kapow!`) or a mood (`playful warm uplifting dreamy calm dark moody epic tense upbeat hype chiptune synthwave hacker mechanical funk ...`), or `none` | the music bed (any family, bar-fitted to the film) |
| `energy=` | `calm`, `normal` or `high` | narration pace (×0.93 / ×1.08 on top of the style's pace), dead air after the narration (high trims holds longer than 1 s), transition length (high ×0.6, calm ×1.4 and soft cuts), the music tempo (the style family's slowest or fastest bed) and the vignette |
| `narration=` | `on` or `off` | `off` makes the film captions-only |
| `voice=` | `whisper warm deep bright playful serious`, or an Edge voice name | Hermes `text_to_speech` `instructions` on voice-design backends; on Edge, pitch and volume nudges. A voice *name* only works where the provider accepts it. Hermes picks its voice from `tts.<provider>.voice` |
| `voice_speed=` | `0.5` to `2.0` | the narration pace multiplier (wins over energy) |
| `title=` `tagline=` `cta=` | text (quote it: `title="ORBIT QUEST"`) | the on-screen words of the TITLE and END cards (and the storyboard brief) |
| `product=` | text | the product name, in the narration and every on-screen text |
| `logo=` | path to a PNG, SVG, JPG or WebP | a corner bug over the whole film (`kit:brand/logo`) |
| `captions=` | `on off bold minimal boxed` | caption visibility and style |
| `transitions=` | `auto kit cut soft punchy fade` | the transition family (`kit` = the style's own) |
| `length=` / `aspect=` | `15`-`180` / `16:9 9:16 both 1:1` | the same as the length and aspect words |
| `language=` | `es fr de it pt nl ja ko zh hi ur ar ru tr pl sv id`, or the language's name | narration and on-screen words are written in that language. The Edge dev route also picks a native voice; in Hermes, set a Multilingual voice |

- **Aliases.** `color`, `colour`, `background`, `bed`, `mood`, `pace`, `speed`, `lang`, `name` and others map to
  the knobs above.
- **Bad keys and values.** An unknown key gets a friendly message that lists the valid keys. It is ignored on the
  slash command and rejected on the API (HTTP 400). A bad value, such as `accent=blurple`, is dropped with a note.
- **Defaults.** Set them in the plugin setting `customize` (`plugins.entries.showreel.settings.customize`, or
  Desktop → Capabilities → Plugins → Showreel), for example `"accent=#ff4fa3 energy=high"`. They have the lowest
  priority and apply to every preset film: look, sound and words (accent, palette, bg, text, font, music, energy,
  voice, captions, transitions, logo, title, tagline, cta, language). Length, aspect and narration have their own
  settings. A YAML mapping also works, but Hermes warns at load because the setting is declared as a string.

## Free-text customization

`/showreel <preset> <request>` runs the preset's normal Quick pipeline and adds three things:

1. **Before the storyboard.** The request goes to the storyboard writer as a tone and wording note (facts stay
   facts). The *keyword reader* also turns the request's own words into a spec, with no model: colours and
   palettes, faster or slower, music moods, whispered or warm narration, captions, "punchier ending", a quoted
   title. Narration pace and voice come from this reader plus the knobs, because they are recorded before the film
   exists.
2. **On the preset's Quick film.** One small LLM call gets the shot list (ids, types, kit scene and the words on
   screen), the declared params of exactly those kit scenes (from KIT.md and kit.js), and the closed vocabularies.
   It answers with a JSON spec of only what the request needs:
   `theme`, `energy`, `music`, `transitions`, `captions`, `voice`, `text`, `shots`, `order`, `restructure` and
   `summary`. `shots` holds per-shot `params`, on-screen `text`, `hold` ±s, or `remove`.
3. **Validate, repair, apply.**
   - The reply is parsed tolerantly: code fences, prose, trailing commas, single quotes and cut-off JSON are
     handled.
   - It is validated: unknown keys are dropped, colour names become hex, enums get the nearest match, a shot can be
     referenced by its type or by "ending", params must be declared by that scene, and the numbers on STATS, CODE,
     DIFF and TERMINAL shots are never rewritten. TITLE, END and at least 4 shots always stay, END stays last, and a
     hold is at most 2.5 s.
   - The result merges over the keyword spec. A weak model, a broken reply or no model at all still gives a
     customized film.
   - Structural edits run on the Timeline (narration, captions, cues and speedrun splits move with their shot).
     The look is applied to film.json.
   - The spec is cached per job in `customize.json`. The second aspect and re-renders or revisions of the job reuse
     it, with no new model call.

If the model says `restructure: true`, the film still renders as the customized preset. The job warns that a
Directed film can go further.

## The theme layer (every kit honours it)

The knobs and the spec resolve to semantic tokens (`accent accent2 accent3 bg text font body_font`). Quick writes
them into a film.json `theme` block:

```json
"theme": {"tokens": {"accent": "#FF2BD6", "bg": "#0A0614"},
          "vars": {"--sr-accent": "#FF2BD6", "--ph": "#FF2BD6", "--cyan": "#FF2BD6", "--cx-red": "#FF2BD6", ...},
          "palette": {"pixel": {"gold": "#FF2BD6"}, "comic": {"red": "#FF2BD6"}, "ink": {"terra": "#FF2BD6"}}}
```

- **CSS vars.** The runtime injects `vars` with `!important` on the stage and every element in it, so the DOM part
  of every kit re-skins without per-kit code: kits/base `--sr-*` (launch, blueprint, comic, ink, cinematic DOM
  type), terminal `--ph-*`/`--glass`, blueprint `--sheet`/`--cyan`/`--line`, comic `--cx-*`, ink `--ik-*`, and the
  font variables.
- **Kits that draw colours in JS** read `ctx.film.theme.palette`:
  - pixel remaps its palette words (the art stays index-locked);
  - comic and ink override their palette `C`;
  - terminal accepts any hex `phosphor`, near-green → P1 and near-amber → P3;
  - cinematic takes the per-shot `accent`.
- Tests: `tests/customize` (fast), plus `--runslow` checks that read the computed CSS vars in the rendered page of
  6 kits and compare pixel frames.

## Desktop, tool, CLI

- **Desktop Make tab.**
  - *Customize preset* (default) shows **Customize this preset…** plus a knobs row: accent colour, energy, music,
    font and narration voice. Starting a film sends `POST /jobs {session_id, options, customize: {text, knobs}}`,
    and `GET /customize` lists the vocabulary.
  - *Free roam* is the Director's Direction box.
  - Revise on the Result tab keeps working: a revision reuses the parent's customization.
- **Tool.** `showreel_render` takes `customize` (free text) and `knobs` (object) next to `style`.
- **CLI.** `hermes showreel render --style terminal --customize "green phosphor, faster" --set accent=#00ff66 --set energy=high`.
- **Code.** `showreel_core/customize/` (`knobs`, `spec`, `llm`, `route`, `theme`, `apply`, `command`, `hook`,
  `vocab`), the runtime theme block (`runtime/core/runtime.js` `themeOverrideCss`) and `kits/brand`.
