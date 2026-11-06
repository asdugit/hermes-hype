"""Showreel audio stage (runtime: stdlib + ffmpeg subprocess only; no numpy).

Modules:
  tts         synthesize(dispatch, text, out_path) -> VoiceClip | None   (Hermes text_to_speech via ctx.dispatch_tool)
  captions    phrase_timing / fallback_timing                           (<= 6-word caption phrases)
  music       pick_bed / resolve_bed / plan_bars / fit_bed -> FittedMusic   (bar-fit of the shipped beds)
  cuesheet    fit_cue_sheet / fit_film_music -> FittedCueSheet          (multi-bed film.json ``music``: designed
                                                                         joins, stings on their impact)
  sfx         load_kit / place_cues -> PlacedSfx                         (cue list -> aligned, levelled SFX)
  mix         mix(...) -> MixResult                                      (one filtergraph + two-pass loudness)
  film_audio  render_film_audio(film, out, voices=...) -> FilmAudio      (cue sheet + SFX + narration, never raises)
QA lives in ``showreel_core.qa.audio`` (audio_report).
"""
