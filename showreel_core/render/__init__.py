"""Hype renderer core: HTML page implementing ``window.__sr`` -> MP4 via headless Chromium + ffmpeg.

Entry points (all in :mod:`showreel_core.render.workers`, never raise):
  ``render_video(RenderSpec, progress=, cancel=) -> RenderResult``
  ``capture_stills(page_dir, page, times, w=, h=) -> StillsResult``
  ``page_session(...)`` async context manager yielding a ready :class:`page.RenderPage` (layout QA, thumbnails)

Modules: ``chromium`` (resolve, flags, launch, own-tree shutdown), ``cdp`` (asyncio CDP client),
``serve`` (loopback page server), ``page`` (one render tab), ``probe`` (GPU probe), ``workers``
(chunked parallel capture), ``ffmpeg`` (resolve, capabilities, builders, ffprobe-free probes),
``post`` (ffmpeg post chains), ``testpage`` + ``selftest`` (``python -m showreel_core.render.selftest``).
Kept import-light on purpose: importing this package does not import the submodules.
"""
