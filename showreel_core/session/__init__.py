"""Session pipeline: state.db → events → assets → stats → redaction → digest (SPEC 2, 3.1, 3.2).

Typical use (never raises)::

    from showreel_core.session import analyze_session
    bundle = analyze_session(session_id, assets_dir=job_dir / "assets")
    bundle.events, bundle.stats, bundle.digest
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Event, Product, Stats
from .assets import AssetReport, collect_assets
from .digest import build_digest, estimate_tokens
from .extract import ExtractResult, extract_events
from .mediarank import VISUAL_KINDS, name_signals, rank_media
from .product import ProductReport, infer_product, link_previews
from .reader import SessionData, list_recent_sessions, load_transcript, read_session, resolve_session_ref
from .redact import Redactor, redact_events
from .stats import compute_stats, parse_test_summary

__all__ = [
    "SessionBundle", "analyze_session", "analyze_rows", "load_transcript", "read_session", "list_recent_sessions",
    "resolve_session_ref", "extract_events", "collect_assets", "compute_stats", "parse_test_summary",
    "Redactor", "redact_events", "build_digest", "estimate_tokens", "ExtractResult", "AssetReport", "SessionData",
    "infer_product", "ProductReport",
]


@dataclass
class SessionBundle:
    """Everything later stages need from one session."""
    session_id: str
    events: list[Event] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    digest: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    product: Product = field(default_factory=Product)
    product_detected: bool = False
    product_confidence: float = 0.0
    product_evidence: dict[str, Any] = field(default_factory=dict)
    rows: int = 0
    backend: str = ""
    assets: AssetReport = field(default_factory=AssetReport)
    redactions: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.events)


def analyze_rows(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None, *, session_id: str = "",
                 assets_dir: str | Path | None = None, redact: bool = True, redactor: Redactor | None = None,
                 max_tokens: int = 8000) -> SessionBundle:
    """Run extraction → product → assets → stats → redaction → digest on loaded rows (never raises)."""
    meta = meta or {}
    bundle = SessionBundle(session_id=session_id, meta=dict(meta), rows=len(rows))
    try:
        res = extract_events(rows, meta)
        bundle.events = res.events
        bundle.warnings += res.warnings
        if res.unanswered_calls:
            bundle.warnings.append(f"{res.unanswered_calls} tool call(s) without a result row")
        report = infer_product(bundle.events, meta)          # inserts artifact events, renumbers ids
        if "error" in report.evidence:
            bundle.warnings.append(f"product inference failed: {report.evidence['error']}")
        for ev in bundle.events:                            # working files never use up the copy budget
            if ev.kind in VISUAL_KINDS and name_signals(str((ev.data or {}).get("src") or "")
                                                        or str((ev.data or {}).get("path") or ""))[0]:
                ev.weight = min(ev.weight, 0.02)
        stamps = [float(r["timestamp"]) for r in rows if isinstance(r.get("timestamp"), (int, float))]
        t0 = min(stamps) if stamps else float(meta.get("started_at") or 0.0)
        bundle.assets = collect_assets(bundle.events, assets_dir, base_dir=meta.get("cwd") or None,
                                       session_t0=t0 or None)
        link_previews(bundle.events)
        bundle.warnings += bundle.assets.errors
        try:                                                # debug renders / contact sheets never reach a film
            ranked = rank_media(bundle.events)
            by_id = {e.id: e for e in bundle.events}
            junk = {i for i, e in by_id.items() if ((e.data or {}).get("media_rank") or {}).get("junk")}
            # best real pictures first (ranked: detail, colour, presented to the user), then the old picks
            n = max(4, len(report.product.hero_event_ids))
            heroes = list(ranked["kept"][:n])
            heroes += [i for i in report.product.hero_event_ids if i not in junk and i not in heroes]
            report.product.hero_event_ids = heroes[:n]
            if ranked["junk"]:
                report.evidence["media_set_aside"] = ranked["junk"]
        except Exception as exc:  # noqa: BLE001 - ranking is an improvement, never a failure
            bundle.warnings.append(f"media ranking failed: {type(exc).__name__}: {exc}")
        bundle.stats = compute_stats(bundle.events, rows, meta)
        red = redactor or Redactor()
        if redact:
            redact_events(bundle.events, red)
            bundle.meta = red.value(bundle.meta)
            report.product = Product(**red.value(asdict(report.product)))
            report.evidence = red.value(report.evidence)
            bundle.redactions = dict(red.counts)
        bundle.product, bundle.product_evidence = report.product, report.evidence
        bundle.product_detected, bundle.product_confidence = report.detected, report.confidence
        bundle.digest = build_digest(bundle.events, bundle.stats, bundle.meta, max_tokens=max_tokens,
                                     redact=red.text if redact else None, product=report)
    except Exception as exc:  # pragma: no cover - defensive: public entry point never raises
        bundle.warnings.append(f"analysis failed: {type(exc).__name__}: {exc}")
    return bundle


def analyze_session(session_id: str, *, db_path: str | Path | None = None, assets_dir: str | Path | None = None,
                    redact: bool = True, redactor: Redactor | None = None, max_tokens: int = 8000) -> SessionBundle:
    """Read a session from state.db (read-only) and analyze it. Never raises; check ``bundle.ok``."""
    data = read_session(session_id, db_path)
    bundle = analyze_rows(data.rows, data.meta, session_id=session_id, assets_dir=assets_dir, redact=redact,
                          redactor=redactor, max_tokens=max_tokens)
    bundle.backend = data.backend
    bundle.warnings = data.warnings + bundle.warnings
    return bundle
