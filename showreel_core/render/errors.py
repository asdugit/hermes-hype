"""Structured render errors.

Low-level helpers raise :class:`RenderError`; public entry points (``render_video``,
``check_video``, the selftest) catch it and return its ``to_dict()`` instead of raising.
"""
from __future__ import annotations

from typing import Any


class RenderError(Exception):
    """A failure with a stable machine-readable ``code`` and a human ``hint``.

    Codes in use: ``no_browser``, ``bad_env_browser``, ``browser_launch``, ``no_ffmpeg``,
    ``bad_env_ffmpeg``, ``no_encoder``, ``ffmpeg``, ``page_load``, ``page_contract``,
    ``cdp_timeout``, ``cdp_closed``, ``cdp``, ``chunk_failed``, ``cancelled``, ``io``.
    """

    def __init__(self, code: str, message: str, hint: str = "", **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form used in results and job logs."""
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.details:
            out["details"] = {k: (v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v))
                              for k, v in self.details.items()}
        return out

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.code}] {self.message}" + (f" (hint: {self.hint})" if self.hint else "")
