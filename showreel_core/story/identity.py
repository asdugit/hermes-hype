"""Product identity: a film is about the product the SESSION built, named from session facts.

The session stage detects the product name from its README title, package/manifest name, page
``<title>``, repo or project directory (or takes it from the user's / agent's brief). The storyboard model
may tidy that name ("Tempo — focus timer" -> "Tempo") but must not rename the product after a tool, a
Auteur stage, an event kind or a capture label. Real E2E: a customized comic film of an Orbit Notes session
called the product "Auteur Product Capture" (the capture stage that photographed it) and "WEBPRODUCT".

:func:`same_product` compares names token-wise; :func:`toolish_words` finds tool / stage / event words
that are not part of the reference name; :func:`replace_name` swaps a wrong name in narration and labels.
"""
from __future__ import annotations

import re

#: Words that name Auteur/Hermes machinery (tools, stages, event kinds, capture labels), not a product.
TOOL_WORDS = frozenset({
    "auteur", "hermes", "capture", "captures", "screenshot", "screenshots", "webproduct", "product_capture",
    "file_write", "file_patch", "write_file", "read_file", "browser_nav", "browser_navigate", "execute_code",
    "delegate_task", "vision_analyze", "web_search", "web_extract", "text_to_speech", "final_answer",
    "user_prompt", "assistant_note", "image_generated", "artifact", "artifacts", "highlights", "storyboard",
})
#: Multi-word labels Auteur itself prints (capture labels, stage names, the generic fallback title).
TOOL_PHRASES = ("product capture", "web product", "capture stage", "session highlights", "desktop 1440x900",
                "mobile 390x844", "full page", "made with hermes")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def tokens(name: str) -> list[str]:
    """Lower-case word tokens (underscored identifiers stay one token)."""
    return _TOKEN_RE.findall(str(name or "").lower().replace("'s ", " "))


def same_product(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` name the same product: equal, or one is a whole-word run inside the other
    ("Tempo" vs "Tempo — focus timer", "orbit-notes" vs "Orbit Notes")."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    if ta == tb or "".join(ta) == "".join(tb):
        return True
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    n = len(short)
    return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))


def toolish_words(name: str, reference: str = "") -> list[str]:
    """Tool / stage / capture words in ``name`` that ``reference`` (the detected name) does not contain."""
    ref = set(tokens(reference))
    ref_text = " ".join(tokens(reference))
    low = " ".join(tokens(name))
    hits = [w for w in tokens(name) if w in TOOL_WORDS and w not in ref]
    hits += [p for p in TOOL_PHRASES if re.search(rf"\b{re.escape(p)}\b", low) and p not in ref_text]
    return list(dict.fromkeys(hits))


def name_pattern(name: str) -> re.Pattern[str] | None:
    """Case-insensitive pattern for ``name`` in prose, tolerant of a possessive and of space/dash/underscore
    separators ("Auteur's product capture" matches "Auteur Product Capture")."""
    toks = tokens(name)
    if not toks:
        return None
    sep = r"(?:'s|\u2019s)?[\s_\-]+"
    return re.compile(r"(?<![\w])" + sep.join(re.escape(t) for t in toks) + r"(?:'s|\u2019s)?(?![\w])", re.IGNORECASE)


def replace_name(text: str, wrong: str, right: str) -> str:
    """``text`` with every mention of ``wrong`` replaced by ``right`` (unchanged when there is none)."""
    pat = name_pattern(wrong)
    if not text or pat is None or not right:
        return text
    return pat.sub(right, text)
