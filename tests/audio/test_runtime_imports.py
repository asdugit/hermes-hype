"""Runtime audio modules must import with the stdlib only (no numpy/scipy at runtime)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_audio_imports_without_numpy():
    code = ("import sys\n"
            "import showreel_core.audio.tts, showreel_core.audio.captions, showreel_core.audio.music\n"
            "import showreel_core.audio.sfx, showreel_core.audio.mix, showreel_core.qa.audio\n"
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('numpy', 'scipy', 'tools'))\n"
            "assert not bad, bad\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
