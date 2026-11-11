"""END CTAs: a shell prompt ('$') only in front of a command, never in front of words (W5 polish-2).

The kits decide in JS; this reads each kit's command test (the regex literal on its ``isCmd`` line) and checks it
against commands and word CTAs, so a kit that prompts 'Read the code on GitHub' (a real Tempo END) fails here."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = ["kits/base/type.js", "kits/comic/scenes-story.js", "kits/terminal/scenes-type.js"]
COMMANDS = ["npm start", "python -m http.server 8765", "./tempo start", "pip install tempo-timer", "tally"]
WORDS = ["Read the code and run it locally", "Read the code on GitHub", "Try it now", "Built with Hermes Agent"]


def _cmd_regex(rel: str) -> re.Pattern[str]:
    src = (ROOT / rel).read_text(encoding="utf-8")
    at = src.index("const isCmd")
    lit = re.search(r"/(\^\[a-z0-9[^\]]*\][^/]*?)/\.test", src[at:at + 400])
    assert lit is not None, rel
    return re.compile(lit.group(1).replace("\\/", "/"))


@pytest.mark.parametrize("rel", FILES)
def test_prompt_only_for_commands(rel):
    rx = _cmd_regex(rel)
    for c in COMMANDS:
        assert rx.match(c), (rel, c)
    for w in WORDS:
        assert not rx.match(w), (rel, w)
