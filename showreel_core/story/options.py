"""Options for the story stage (storyboard generation)."""
from __future__ import annotations

from dataclasses import dataclass

#: Styles the prompt knows a tone for (others fall back to "launch").
KNOWN_STYLES = ("launch", "pixel", "terminal", "blueprint", "cinematic", "comic", "ink", "newspaper")


@dataclass
class StoryOptions:
    """How the storyboard should be written.

    ``seconds`` is the target film length (30/60/90 typical, 15..180 accepted),
    ``style`` a style-pack id, ``aspect`` "16:9" or "9:16", ``mode`` "product" (launch
    trailer for what was built; default), "making_of" (``/hype lore``: the build story
    is the hero) or "speedrun" (the build as a speedrun with milestone splits); command
    aliases like "lore" are accepted. ``voice`` says whether narration will be spoken
    (captions-only films still get narration text for captions); ``brief`` is an
    optional user/agent note about the product. ``product_name_locked`` says the session stage's product
    name is strong (the brief, a README title, a package/manifest name or the page ``<title>``): the film
    keeps it and the model may only shorten or tidy it.
    """
    seconds: float = 60.0
    style: str = "launch"
    aspect: str = "16:9"
    mode: str = "product"
    voice: bool = True
    brief: str = ""
    product_name_locked: bool = False
    temperature: float = 0.4
    max_tokens: int = 4096
    timeout: float = 120.0

    def clamped_seconds(self) -> float:
        """Target length clamped to the supported 15..180 s range."""
        try:
            secs = float(self.seconds)
        except (TypeError, ValueError):
            secs = 60.0
        return min(180.0, max(15.0, secs))
