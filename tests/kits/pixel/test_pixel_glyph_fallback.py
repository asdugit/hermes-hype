"""Pixel bitmap text never prints '?' for typography the baked fonts lack (E4): dashes, curly quotes, accents."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEXT = (ROOT / "kits" / "pixel" / "core" / "text.js").as_uri()

SAMPLES = ["Tempo — focus timer", "it’s ready", "naïve résumé", "Café “Orbit” – v2", "Tempo 🍅 timer", "日本 app",
           "a\u00a0b", "x − y"]


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = (f"import {{ normalize, measure }} from {json.dumps(TEXT)};\n"
          f"const S = {json.dumps(SAMPLES, ensure_ascii=False)};\n"
          "const out = {};\n"
          "for (const f of ['mono', 'caps', 'tiny']) out[f] = S.map((s) => [normalize(s, f), measure(s, f)]);\n"
          "console.log(JSON.stringify(out));\n")
    p = subprocess.run([node, "--input-type=module", "-"], input=js, capture_output=True, text=True,
                       encoding="utf-8", timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_no_question_marks_for_common_typography():
    res = _run()
    for font, rows in res.items():
        got = [r[0] for r in rows]
        assert not any("?" in g for g in got), (font, got)
        assert all(r[1] > 0 for r in rows), (font, rows)
        low = [g.lower() for g in got]
        assert low[0] == "tempo - focus timer", (font, got[0])
        assert low[1] == "it's ready"
        assert low[2] == "naive resume"
        assert low[3] == 'cafe "orbit" - v2'
        assert low[4] == "tempo timer"          # emoji dropped, words kept apart by one space
        assert low[5] == "app"
