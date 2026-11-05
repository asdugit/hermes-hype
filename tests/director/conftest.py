"""Director test fixtures (fakes live in director_fakes.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from director_fakes import env  # noqa: F401  (pytest fixture)
