"""Video poster frames via ffmpeg, used when Telegram's own thumbnail is black."""

import logging
import shutil
import subprocess
from functools import cache
from pathlib import Path

log = logging.getLogger("tgblog")

# An image counts as blank when even its brightest spot (0-255, on a 32×32 downscale) stays below this.
DARK_LEVEL = 40


@cache
def ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = None
    if not exe:
        log.warning("ffmpeg not found; skipping video poster frames (pip install imageio-ffmpeg)")
    return exe


def brightness(path: Path) -> int | None:
    exe = ffmpeg()
    if not exe:
        return None
    out = subprocess.run(
        [exe, "-v", "error", "-i", str(path), "-vf", "scale=32:32:flags=area,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=60,
    ).stdout
    return max(out) if out else None


def seconds(duration: str | None) -> int:
    total = 0
    for part in (duration or "").split(":"):
        if not part.isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def grab_poster(url: str, dest: Path, duration: str | None) -> bool:
    """Save the first non-black frame of a remote video to dest, sampling a few points in time."""
    exe = ffmpeg()
    if not exe:
        return False
    length = seconds(duration)
    stamps = [1] + [round(length * f, 2) for f in (0.2, 0.4, 0.6)] if length > 2 else [1, 2, 3, 5, 8]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.jpg")
    try:
        for ts in stamps:
            result = subprocess.run(
                [exe, "-v", "error", "-y", "-ss", str(ts), "-i", url, "-frames:v", "1",
                 "-vf", "scale='min(960,iw)':-2", "-q:v", "3", str(tmp)],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0 and tmp.exists() and (brightness(tmp) or 0) >= DARK_LEVEL:
                tmp.replace(dest)
                return True
    except subprocess.TimeoutExpired:
        log.warning("poster frame timed out for %s", dest.name)
    finally:
        tmp.unlink(missing_ok=True)
    return False
