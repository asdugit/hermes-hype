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

LOCK = Path(__file__).resolve().parents[3] / "render.lock"


def ffmpeg() -> str:
    """Resolve ffmpeg: $SHOWREEL_FFMPEG / $FFMPEG_PATH, the Hermes-managed build, then PATH."""
    for env in ("SHOWREEL_FFMPEG", "FFMPEG_PATH"):
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
        raise RuntimeError("ffmpeg not found (set SHOWREEL_FFMPEG)")
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


@contextlib.contextmanager
def render_lock(name: str = "wp-c-audio composer", wait_s: float = 1800.0) -> Iterator[None]:
    """Shared-machine etiquette: hold C:/Users/2/showreel-work/render.lock while rendering."""
    if not (LOCK.parent / "render.lock.README").is_file():
        yield
        return
    t0 = time.time()
    while LOCK.exists() and time.time() - LOCK.stat().st_mtime < 900:
        if time.time() - t0 > wait_s:
            raise TimeoutError(f"render.lock held by: {LOCK.read_text(encoding='utf-8').strip()}")
        time.sleep(20)
    LOCK.write_text(f"{name} pid={os.getpid()}\n", encoding="utf-8")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            if LOCK.read_text(encoding="utf-8").startswith(name):
                LOCK.unlink()


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
