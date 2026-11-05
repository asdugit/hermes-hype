"""Showreel audio stage (runtime: stdlib + ffmpeg subprocess only; no numpy).

Modules:
  tts       synthesize(dispatch, text, out_path) -> VoiceClip | None   (Hermes text_to_speech via ctx.dispatch_tool)
  captions  phrase_timing / fallback_timing                           (<= 6-word caption phrases)
  music     pick_bed / plan_bars / fit_bed -> FittedMusic              (bar-fit of the shipped beds)
  sfx       load_kit / place_cues -> PlacedSfx                         (cue list -> aligned, levelled SFX)
  mix       mix(...) -> MixResult                                      (one filtergraph + two-pass loudness)
QA lives in ``showreel_core.qa.audio`` (audio_report).
"""
