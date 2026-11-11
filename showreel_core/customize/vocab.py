"""Vocabulary of preset customization: colours, palettes, fonts, music moods, energies, voices, languages.

Everything here is data + tiny pure helpers (stdlib only). The kit facts (fonts, beds) are read from the
repo on demand so new kits/beds join without code changes.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
KITS_ROOT = REPO_ROOT / "kits"
BEDS_ROOT = REPO_ROOT / "assets" / "audio" / "beds"

#: The preset styles (kits with Quick types). lore/speedrun are modes on top of any of them.
PRESETS = ("launch", "cinematic", "pixel", "terminal", "blueprint", "comic", "ink")

# ------------------------------------------------------------------------------------------- colours

#: Named colours a user may type (``accent=pink``). Lower-case, ``-``/``_``/space-insensitive.
COLOURS: dict[str, str] = {
    "pink": "#FF5FA2", "hotpink": "#FF2E8B", "neonpink": "#FF2BD6", "magenta": "#FF2BD6", "fuchsia": "#E040FB",
    "rose": "#F2789F", "bubblegum": "#FF8AC8", "red": "#E5484D", "crimson": "#D7263D", "scarlet": "#FF3B30",
    "coral": "#FF6F59", "salmon": "#FA8072", "orange": "#FF8A1F", "amber": "#FFB13B", "gold": "#FFC533",
    "yellow": "#FFE14D", "lemon": "#FFF35C", "lime": "#B6F23A", "green": "#3DDC84", "neongreen": "#39FF14",
    "phosphor": "#4BFF86", "phosphorgreen": "#4BFF86", "matrix": "#00FF66", "mint": "#5CF2B8", "emerald": "#2ECC71",
    "teal": "#2FD3C0", "cyan": "#00E5FF", "neoncyan": "#00F0FF", "aqua": "#4DF3FF", "turquoise": "#40E0D0",
    "sky": "#79B8EF", "skyblue": "#79B8EF", "blue": "#4A8BFF", "electricblue": "#2D7BFF", "cobalt": "#2F5BEA",
    "navy": "#1B2A5E", "midnight": "#0E1530", "indigo": "#5B5BF0", "violet": "#8B5CF6", "purple": "#A35BFF",
    "neonpurple": "#B026FF", "lilac": "#C8A2FF", "lavender": "#B9A7FF", "plum": "#8E4585", "white": "#FFFFFF",
    "cream": "#FFF3D6", "ivory": "#FFFDF2", "silver": "#C0C6D4", "grey": "#8A8F9C", "gray": "#8A8F9C",
    "charcoal": "#2B2D33", "black": "#000000", "brown": "#8B5A2B", "tan": "#D2A26A", "peach": "#FFB38A",
    "sand": "#E8D3A8", "olive": "#8A9A3B", "forest": "#2E6B3F", "ocean": "#1E6FBF", "night": "#0B1026",
}

_HEX_RE = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _key(s: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(s or "").strip().lower())


def colour(value: Any) -> str:
    """``#RRGGBB`` from a hex (``#f0a``, ``FF00AA``) or a colour name; ``""`` when it is neither."""
    s = str(value or "").strip()
    m = _HEX_RE.fullmatch(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h.upper()
    return COLOURS.get(_key(s), "")


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hexof(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in (r, g, b))


def mix(a: str, b: str, t: float) -> str:
    """``a`` blended toward ``b`` by ``t`` (0..1)."""
    ra, rb = rgb(a), rgb(b)
    return hexof(*(x + (y - x) * t for x, y in zip(ra, rb)))


def lum(hex6: str) -> float:
    """WCAG relative luminance (0 black .. 1 white)."""
    lin = [c / 255 for c in rgb(hex6)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in lin]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ink_on(hex6: str) -> str:
    """Readable text colour on top of ``hex6`` (near-black or near-white)."""
    return "#0B0C10" if lum(hex6) > 0.32 else "#FFFFFF"


def hue(hex6: str) -> float:
    """Hue in degrees (0..360)."""
    r, g, b = (c / 255 for c in rgb(hex6))
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        return 0.0
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60.0


def rgba(hex6: str, a: float) -> str:
    r, g, b = rgb(hex6)
    return f"rgba({r},{g},{b},{a:g})"


# ------------------------------------------------------------------------------------------- palettes

#: Named palettes: semantic colours every kit maps onto its own tokens (customize/theme.py).
#: accent = the one hero colour; accent2/accent3 = supporting; bg = stage; text = type on the stage.
PALETTES: dict[str, dict[str, str]] = {
    "neon": {"accent": "#FF2BD6", "accent2": "#00F0FF", "accent3": "#B6FF3A", "bg": "#0A0614", "text": "#F7F1FF"},
    "pastel": {"accent": "#FF9EC7", "accent2": "#9ED8FF", "accent3": "#FFE29A", "bg": "#FFF6FA", "text": "#3B2F45"},
    "candy": {"accent": "#FF4FA3", "accent2": "#FFD23A", "accent3": "#5CE1E6", "bg": "#2A0E2E", "text": "#FFF4FB"},
    "noir": {"accent": "#E8E8E8", "accent2": "#9A9A9A", "accent3": "#D7263D", "bg": "#050505", "text": "#F2F2F2"},
    "sunset": {"accent": "#FF7A45", "accent2": "#FFC145", "accent3": "#C04CFD", "bg": "#1C0B19", "text": "#FFF1E6"},
    "ocean": {"accent": "#3FA7FF", "accent2": "#2FD3C0", "accent3": "#B8E7FF", "bg": "#06162B", "text": "#EAF6FF"},
    "night": {"accent": "#6FA8FF", "accent2": "#9C8CFF", "accent3": "#CFE3FF", "bg": "#060A18", "text": "#E6EEFF"},
    "forest": {"accent": "#7BD389", "accent2": "#E9C46A", "accent3": "#2A9D8F", "bg": "#0C1A12", "text": "#F1F7EC"},
    "phosphor": {"accent": "#4BFF86", "accent2": "#35C268", "accent3": "#D9FFE6", "bg": "#040905", "text": "#D9FFE6"},
    "amber": {"accent": "#FFB13B", "accent2": "#C98A2C", "accent3": "#FFE6B8", "bg": "#0C0805", "text": "#FFE6B8"},
    "mono": {"accent": "#FFFFFF", "accent2": "#A0A0A0", "accent3": "#5A5A5A", "bg": "#0B0B0B", "text": "#F5F5F5"},
    "warm": {"accent": "#FF8A3D", "accent2": "#FFC857", "accent3": "#E94F37", "bg": "#1A120C", "text": "#FFF5EA"},
    "cool": {"accent": "#58A6FF", "accent2": "#7EE0D6", "accent3": "#C3B5FF", "bg": "#0A0F1C", "text": "#EEF3FF"},
}
PALETTE_ALIASES = {"neons": "neon", "cyberpunk": "neon", "synthwave": "neon", "vaporwave": "neon", "pastels": "pastel",
                   "soft": "pastel", "bw": "noir", "blackandwhite": "noir", "monochrome": "mono", "greenphosphor": "phosphor",
                   "hacker": "phosphor", "matrix": "phosphor", "sea": "ocean", "midnight": "night", "nature": "forest"}


def palette(value: Any) -> dict[str, str]:
    """Semantic palette from a name (``neon``) or a comma list of colours (accent, accent2, accent3, bg, text)."""
    k = _key(value)
    k = PALETTE_ALIASES.get(k, k)
    if k in PALETTES:
        return dict(PALETTES[k])
    parts = [colour(p) for p in re.split(r"[,/+]", str(value or "")) if p.strip()]
    parts = [p for p in parts if p]
    if not parts:
        return {}
    keys = ("accent", "accent2", "accent3", "bg", "text")
    return {keys[i]: c for i, c in enumerate(parts[:5])}


def palette_name(value: Any) -> str:
    k = _key(value)
    k = PALETTE_ALIASES.get(k, k)
    return k if k in PALETTES else ""


# ------------------------------------------------------------------------------------------- fonts

@lru_cache(maxsize=4)
def _font_table(kits_root: str) -> dict[str, dict[str, Any]]:
    """family (lower-case) -> {family, files: [{family, src (repo-relative 'kits/<kit>/<file>'), weight, style}]}."""
    out: dict[str, dict[str, Any]] = {}
    root = Path(kits_root)
    extra = {"pixel": [{"family": "Silkscreen", "src": "fonts/Silkscreen-Regular.ttf", "weight": 400}]}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        try:
            meta = json.loads((d / "kit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        for f in list(meta.get("fonts") or []) + extra.get(d.name, []):
            if not isinstance(f, dict) or not f.get("family") or not f.get("src"):
                continue
            if not (d / str(f["src"])).is_file():
                continue
            fam = str(f["family"])
            row = out.setdefault(fam.lower(), {"family": fam, "files": [], "kit": d.name})
            src = f"kits/{d.name}/{f['src']}"
            if all(x["src"] != src for x in row["files"]):
                row["files"].append({"family": fam, "src": src, "weight": f.get("weight", 400),
                                     "style": f.get("style", "normal")})
    return out


def fonts(kits_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Every OFL font family the kits ship (``fonts()['bangers']['files']``)."""
    return _font_table(str(kits_root or KITS_ROOT))


def font(value: Any, kits_root: Path | None = None) -> str:
    """Canonical family name for a typed font (``bangers`` -> ``Bangers``, ``plex`` -> ``IBM Plex Mono``)."""
    table = fonts(kits_root)
    k = str(value or "").strip().strip("\"'").lower()
    if not k:
        return ""
    if k in table:
        return table[k]["family"]
    squash = _key(k)
    for fam, row in table.items():
        if _key(fam) == squash:
            return row["family"]
    hits = [row["family"] for fam, row in table.items() if squash and squash in _key(fam)]
    return sorted(hits, key=len)[0] if hits else ""


#: Font "moods" a request may name (keywords -> family).
FONT_MOODS = {"comic": "Bangers", "playful": "Comic Neue", "handwritten": "Caveat", "hand": "Caveat",
              "serif": "Fraunces", "elegant": "Cormorant Garamond", "classy": "Cormorant Garamond",
              "mono": "IBM Plex Mono", "code": "JetBrains Mono", "retro": "VT323", "crt": "VT323",
              "pixel": "Silkscreen", "8bit": "Silkscreen", "techy": "Space Grotesk", "geometric": "Space Grotesk",
              "clean": "Inter", "modern": "Geist"}

# ------------------------------------------------------------------------------------------- music

#: Mood -> bed ids, best first (beds live in assets/audio/beds/<family>/bars.json).
MOODS: dict[str, list[str]] = {
    "playful": ["comic_b", "comic_a", "ink_b"], "fun": ["comic_b", "ink_b", "pixel_a"],
    "warm": ["ink_a", "cinematic_b", "dream_b"], "friendly": ["ink_a", "ink_b"],
    "uplifting": ["dream_b", "dream_a", "launch_b"], "dreamy": ["dream_a", "dream_b"],
    "calm": ["cinematic_b", "dream_a", "ink_a"], "ambient": ["cinematic_b"], "chill": ["cinematic_b", "ink_a"],
    "dark": ["terminal_a", "cinematic_a"], "moody": ["cinematic_a", "terminal_b"], "cinematic": ["cinematic_a"],
    "epic": ["pixel_boss_b", "cinematic_a"], "tense": ["pixel_boss_a", "pixel_boss_b"], "boss": ["pixel_boss_b"],
    "upbeat": ["launch_a", "comic_b", "pixel_a"], "energetic": ["launch_a", "pixel_boss_b"],
    "hype": ["launch_a", "pixel_boss_b"], "house": ["launch_a", "launch_b"], "pop": ["launch_b"],
    "chiptune": ["pixel_a", "pixel_b"], "8bit": ["pixel_a", "pixel_b"], "retro": ["terminal_b", "pixel_a"],
    "synthwave": ["terminal_b", "terminal_a"], "darksynth": ["terminal_a"], "hacker": ["terminal_a"],
    "mechanical": ["blueprint_a", "blueprint_b"], "techy": ["blueprint_b", "terminal_b"],
    "funk": ["comic_a", "comic_b"], "jazzy": ["comic_a"],
}
MUSIC_OFF = {"none", "off", "no", "silent", "nomusic"}


@lru_cache(maxsize=4)
def _beds(beds_root: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    root = Path(beds_root)
    for f in sorted(root.glob("*/bars.json")) if root.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data if isinstance(data, list) else data.get("beds") if isinstance(data.get("beds"), list) else [data]
        for b in rows:
            if isinstance(b, dict) and b.get("id"):
                out[str(b["id"])] = {"id": str(b["id"]), "family": f.parent.name, "bpm": float(b.get("bpm") or 120),
                                     "title": str(b.get("title") or ""), "mood": str(b.get("mood") or ""),
                                     "notes": str(b.get("notes") or "")[:160]}
    return out


def beds(beds_root: Path | None = None) -> dict[str, dict[str, Any]]:
    return _beds(str(beds_root or BEDS_ROOT))


def music(value: Any, *, style: str = "", beds_root: Path | None = None) -> str:
    """A bed id from a bed id, a bed family (``comic``), a bed title or a mood; ``"none"`` = no music; ``""`` = unknown."""
    k = _key(value)
    if not k:
        return ""
    if k in MUSIC_OFF:
        return "none"
    table = beds(beds_root)
    for bid in table:
        if _key(bid) == k:
            return bid
    fam = [bid for bid, b in table.items() if _key(b["family"]) == k]
    if fam:
        return sorted(fam)[0]
    for bid, b in table.items():
        if _key(b["title"]) == k:
            return bid
    for mood, ids in MOODS.items():
        if _key(mood) == k:
            ids = [i for i in ids if i in table] or ids
            fam_first = [i for i in ids if table.get(i, {}).get("family") == style]
            return (fam_first or ids)[0]
    return ""


def bed_for_energy(style: str, energy: str, beds_root: Path | None = None) -> str:
    """The style family's slowest (calm) or fastest (high) bed; ``""`` for normal / no beds."""
    table = beds(beds_root)
    fam = sorted((b for b in table.values() if b["family"] == style), key=lambda b: b["bpm"])
    if not fam or energy not in ("calm", "high"):
        return ""
    return fam[0]["id"] if energy == "calm" else fam[-1]["id"]


# ------------------------------------------------------------------------------------------- energy / misc

ENERGIES = ("calm", "normal", "high")
ENERGY_ALIASES = {"low": "calm", "chill": "calm", "slow": "calm", "slower": "calm", "relaxed": "calm", "gentle": "calm",
                  "medium": "normal", "default": "normal", "mid": "normal", "fast": "high", "faster": "high",
                  "hype": "high", "punchy": "high", "energetic": "high", "intense": "high", "max": "high"}
#: Narration pace multiplier per energy (on top of the style's voice_speed; an explicit voice_speed wins).
ENERGY_VOICE = {"calm": 0.93, "normal": 1.0, "high": 1.0}   # high: shorter lines + more cuts, never a faster voice

TRANSITION_FAMILIES = ("auto", "kit", "cut", "soft", "punchy", "fade")
TRANSITION_ALIASES = {"default": "auto", "style": "kit", "native": "kit", "hard": "cut", "cuts": "cut", "none": "cut",
                      "crossfade": "soft", "dissolve": "soft", "smooth": "soft", "gentle": "soft", "whip": "punchy",
                      "fast": "punchy", "snappy": "punchy", "dip": "fade", "black": "fade", "dipblack": "fade"}
CAPTION_STYLES = ("on", "off", "bold", "minimal", "boxed")
CAPTION_ALIASES = {"yes": "on", "true": "on", "1": "on", "no": "off", "false": "off", "0": "off", "none": "off",
                   "big": "bold", "loud": "bold", "subtle": "minimal", "clean": "minimal", "box": "boxed", "plate": "boxed"}

#: Voice "styles" a request may name: Hermes ``text_to_speech`` ``instructions`` (voice-design backends) and, on
#: the Edge dev route, rate/pitch/volume nudges (edge-tts has no SSML styles).
VOICE_STYLES: dict[str, dict[str, Any]] = {
    "whisper": {"instructions": "Speak in a soft, intimate, breathy whisper, close to the microphone.",
                "edge": {"pitch": "-6Hz", "volume": "-18%"}, "speed": 0.94},
    "warm": {"instructions": "Speak warmly and friendly, smiling, unhurried.", "edge": {"pitch": "-2Hz"}},
    "deep": {"instructions": "Speak in a low, deep, cinematic trailer voice.", "edge": {"pitch": "-12Hz"}, "speed": 0.96},
    "bright": {"instructions": "Speak brightly and energetically, upbeat.", "edge": {"pitch": "+4Hz"}, "speed": 1.04},
    "playful": {"instructions": "Speak playfully, with a grin, bouncy delivery.", "edge": {"pitch": "+6Hz"}},
    "serious": {"instructions": "Speak calmly and seriously, documentary narrator.", "edge": {"pitch": "-4Hz"}},
}
VOICE_STYLE_ALIASES = {"whispered": "whisper", "whispering": "whisper", "hushed": "whisper", "soft": "whisper",
                       "friendly": "warm", "trailer": "deep", "low": "deep", "upbeat": "bright", "energetic": "bright",
                       "fun": "playful", "calm": "serious", "documentary": "serious"}

#: language -> (code, display name, a multilingual Edge voice that speaks it natively).
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "en": ("en", "English", "en-US-AndrewMultilingualNeural"), "es": ("es", "Spanish", "es-ES-AlvaroNeural"),
    "fr": ("fr", "French", "fr-FR-RemyMultilingualNeural"), "de": ("de", "German", "de-DE-FlorianMultilingualNeural"),
    "it": ("it", "Italian", "it-IT-GiuseppeMultilingualNeural"), "pt": ("pt", "Portuguese", "pt-BR-AntonioNeural"),
    "nl": ("nl", "Dutch", "nl-NL-MaartenNeural"), "ja": ("ja", "Japanese", "ja-JP-KeitaNeural"),
    "ko": ("ko", "Korean", "ko-KR-HyunsuMultilingualNeural"), "zh": ("zh", "Chinese", "zh-CN-YunxiNeural"),
    "hi": ("hi", "Hindi", "hi-IN-MadhurNeural"), "ur": ("ur", "Urdu", "ur-PK-AsadNeural"),
    "ar": ("ar", "Arabic", "ar-SA-HamedNeural"), "ru": ("ru", "Russian", "ru-RU-DmitryNeural"),
    "tr": ("tr", "Turkish", "tr-TR-AhmetNeural"), "pl": ("pl", "Polish", "pl-PL-MarekNeural"),
    "sv": ("sv", "Swedish", "sv-SE-MattiasNeural"), "id": ("id", "Indonesian", "id-ID-ArdiNeural"),
}
_LANG_NAMES = {v[1].lower(): k for k, v in LANGUAGES.items()}
_LANG_NAMES.update({"espanol": "es", "español": "es", "francais": "fr", "français": "fr", "deutsch": "de",
                    "japanese": "ja", "nihongo": "ja", "mandarin": "zh", "brazilian": "pt", "portugues": "pt"})


def language(value: Any) -> str:
    """ISO code (``es``) from a code, a locale (``es-MX``) or a name (``Spanish``); ``""`` when unknown."""
    s = str(value or "").strip().lower()
    if not s:
        return ""
    if s in LANGUAGES:
        return s
    base = s.split("-")[0].split("_")[0]
    if base in LANGUAGES:
        return base
    return _LANG_NAMES.get(s, "")


def choice(value: Any, allowed: tuple[str, ...], aliases: dict[str, str]) -> str:
    k = _key(value)
    k = aliases.get(k, k)
    return k if k in allowed else ""
