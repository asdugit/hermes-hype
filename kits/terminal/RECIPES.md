# Terminal — recipes (for the Director)

1. **Test-run film (bug fix, 25 s).** HOOK(hero = terminal with the passing run) → TITLE → CODE(focus on the fix) →
   DIFF → TERMINAL(the run; `persist` cut in) → STATS(tests passing, files changed) → END. `channel-switch` only at
   HOOK→TITLE and STATS→END; everything else `persist` or hard cuts.
2. **Product film (web app).** HOOK(image hero, `product_scale` 1.2) → TITLE → FEATURE ×2 (one per feature, click
   points from the capture) → SCROLL(full page) → STATS → END. Captures resolve ASCII → dither → real, so give
   SCREEN/FEATURE ≥ 3.5 s or the real image barely lands.
3. **Agent-at-work montage.** PROBLEM(the prompt typed) → PLAN → MONTAGE(tool calls) → TERMINAL → CALLOUT(the
   user's reaction) — the typing cadence carries the rhythm; put the `type` cues on the bed's 16ths.
4. **Vertical (9:16).** Same scenes; panes stack (BEFORE_AFTER top/bottom), captions sit above the status line.
   Prefer short commands and ≤ 8 output lines per TERMINAL.

Rules: one phosphor per film (`p3` default; `p1` for a "hacker green" brief); no dissolves; never more than one
`channel-switch` per act; let END run ≥ 4 s so the tube-off lands after the CTA has been read.
