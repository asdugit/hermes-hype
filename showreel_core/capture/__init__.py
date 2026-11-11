"""Product capture stage (SPEC §1, WP-J): Hype photographs the product the session built.

* :mod:`.targets` decides what can be captured (reachable loopback/LAN/allowed public URLs, local
  HTML entry files, images, videos, PDFs). It never starts servers or runs commands.
* :mod:`.web` drives its own headless Chromium (raw CDP) with a strict network policy: desktop,
  mobile, full-page, feature-element and interaction captures plus page title/accent/favicon.
* :mod:`.media` turns image/video/PDF artifacts into capture-ready assets (posters, size info,
  optional alpha cutouts when the background is near-uniform).
* :mod:`.capture` ties it together: :func:`capture_product` returns ``product_capture`` events.

Import-light: submodules load on first use.
"""
from __future__ import annotations

from typing import Any

__all__ = ["CaptureReport", "capture_product", "capture_product_report"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import capture

        return getattr(capture, name)
    raise AttributeError(name)
