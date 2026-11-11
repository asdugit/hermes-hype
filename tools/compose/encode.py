"""ffmpeg I/O for the dev composer: encode beds/SFX, decode for verification, render-lock etiquette."""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from collections.abc import Iterator

import numpy as np

from .dsp import SR


def ffmpeg() -> str:
    """Resolve ffmpeg: $HYPE_FFMPEG / $FFMPEG_PATH, the Hermes-managed build, then PATH."""
    for env in ("HYPE_FFMPEG", "FFMPEG_PATH"):
        if os.environ.get(env):
            return os.environ[env]
    homes = [Path(os.environ["HERMES_HOME"])] if os.environ.get("HERMES_HOME") else []
    homes += [Path.home() / "AppData/Local/hermes", Path.home() / ".hermes"]
    for home in homes:
        for cand in sorted((home / "tools").glob("ffmpeg-*/bin/ffmpeg*"), reverse=True):
            if cand.stem == "ffmpeg":
                return str(cand)
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found (set HYPE_FFMPEG)")
    return found


def encode(x: np.ndarray, path: Path, codec: str = "opus", bitrate: str = "96k") -> None:
    """Encode float audio (mono or stereo) to OGG (Opus by default) at 48 kHz."""
    xs = np.atleast_2d(x).astype("<f4")
    ch = xs.shape[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", str(ch),
            "-i", "-"]
    if codec == "opus":
        args += ["-c:a", "libopus", "-b:a", bitrate, "-vbr", "on", "-application", "audio"]
    elif codec == "vorbis":
        args += ["-c:a", "libvorbis", "-q:a", bitrate]
    elif codec == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", bitrate]
    elif codec == "wav":
        args += ["-c:a", "pcm_s24le"]
    args += ["-map_metadata", "-1", str(path)]
    subprocess.run(args, input=xs.T.tobytes(), check=True)


def decode(path: Path, channels: int = 2) -> np.ndarray:
    """Decode any file to float (channels, n) at 48 kHz."""
    out = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac",
                          str(channels), "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, "<f4").reshape(-1, channels).T.astype(np.float64)


WORK = Path(__file__).resolve().parents[3]
SLOTS = [WORK / f"render.slot{k}" for k in (1, 2, 3)]


@contextlib.contextmanager
def render_lock(name: str = "wp-c-audio composer", wait_s: float = 1800.0) -> Iterator[None]:
    """Shared-machine etiquette (``render.lock.README``): hold one of the 3 render slots while rendering.

    A slot is taken atomically (O_CREAT|O_EXCL); slots older than 15 min are stale and may be removed.
    Waits (5 s polls) up to ``wait_s`` and then raises instead of taking over a live slot.
    """
    if not (WORK / "render.lock.README").is_file():
        yield
        return
    t0 = time.time()
    mine: Path | None = None
    while mine is None:
        for slot in SLOTS:
            with contextlib.suppress(OSError):
                if slot.exists() and time.time() - slot.stat().st_mtime >= 900:
                    slot.unlink()
            try:
                fd = os.open(slot, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except OSError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{name} {os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
            mine = slot
            break
        if mine is None:
            if time.time() - t0 > wait_s:
                raise TimeoutError("all render slots busy: " + ", ".join(
                    s.read_text(encoding="utf-8", errors="replace").strip() for s in SLOTS if s.exists()))
            time.sleep(5)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


def spectrogram_png(x: np.ndarray, path: Path, fmax: float = 8000.0, px_per_s: int = 12) -> None:
    """Debug spectrogram (log magnitude, linear frequency) for visual checks of structure."""
    from PIL import Image
    from scipy import signal

    m = x.mean(axis=0) if x.ndim == 2 else x
    f, _t, S = signal.spectrogram(m, SR, nperseg=2048, noverlap=2048 - SR // px_per_s, scaling="spectrum")
    S = S[f <= fmax]
    L = 10 * np.log10(S + 1e-12)
    L = np.clip((L - (L.max() - 80)) / 80, 0, 1)
    img = (255 * L[::-1]).astype(np.uint8)
    im = Image.fromarray(img).resize((img.shape[1], 300))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
