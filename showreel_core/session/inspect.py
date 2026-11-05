"""Dev CLI: ``python -m showreel_core.session.inspect <session_id|prefix|latest> [--db PATH] [--assets DIR]``.

Prints the LLM digest, the computed stats, an event-kind histogram, asset/redaction counts and
warnings. ``--list N`` shows recent sessions instead. ``--json FILE`` dumps the events.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import analyze_session, estimate_tokens, list_recent_sessions, resolve_session_ref


def _print(text: str) -> None:
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(enc, "replace").decode(enc) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="showreel_core.session.inspect", description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?", default="latest", help="session id, unique prefix, or 'latest'")
    ap.add_argument("--db", help="path to state.db (default: <hermes home>/state.db)")
    ap.add_argument("--assets", help="copy screenshots/images into this directory")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--no-redact", action="store_true", help="skip redaction (local debugging only)")
    ap.add_argument("--no-digest", action="store_true", help="print stats/histogram only")
    ap.add_argument("--json", help="write events + stats as JSON to this file")
    ap.add_argument("--list", type=int, metavar="N", help="list the N most recent sessions and exit")
    args = ap.parse_args(argv)

    if args.list:
        for s in list_recent_sessions(args.list, args.db):
            _print(f"{s.get('id')}  {s.get('source') or '?':9} msgs={s.get('message_count')} "
                   f"tools={s.get('tool_call_count')}")
        return 0
    sid = resolve_session_ref(args.session, args.db)
    if not sid:
        _print(f"error: no session matches {args.session!r}")
        return 2
    b = analyze_session(sid, db_path=args.db, assets_dir=args.assets, redact=not args.no_redact,
                        max_tokens=args.max_tokens)
    if not args.no_digest:
        _print(b.digest)
    _print("=" * 72)
    _print(f"session {sid} | backend={b.backend} | rows={b.rows} | events={len(b.events)} | "
           f"digest≈{estimate_tokens(b.digest)} tokens (estimate) / {len(b.digest)} chars")
    _print("stats: " + json.dumps(b.stats.to_dict(), ensure_ascii=False))
    kinds = Counter(e.kind for e in b.events)
    _print("kinds: " + ", ".join(f"{k}={v}" for k, v in kinds.most_common()))
    stubs = sum(1 for e in b.events if e.data.get("stub"))
    failed = sum(1 for e in b.events if not e.ok)
    _print(f"stubs={stubs} failed={failed} | assets: copied={b.assets.copied} reused={b.assets.reused} "
           f"inline={b.assets.inline} missing={b.assets.missing} skipped={b.assets.skipped}")
    _print("redactions: " + (", ".join(f"{k}={v}" for k, v in sorted(b.redactions.items())) or "none"))
    p = b.product
    _print(f"product: detected={b.product_detected} confidence={b.product_confidence} kind={p.kind or '?'} "
           f"name={p.name!r} urls={len(p.urls)} run_cmds={len(p.run_commands)} entry={len(p.entry_files)} "
           f"features={len(p.features)} heroes={p.hero_event_ids} "
           f"artifacts={b.product_evidence.get('artifact_counts', {})}")
    for w in b.warnings[:20]:
        _print(f"warning: {w}")
    if args.json:
        out = {"session_id": sid, "stats": b.stats.to_dict(), "product": b.product.__dict__,
               "product_evidence": b.product_evidence, "events": [e.to_dict() for e in b.events]}
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if b.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
