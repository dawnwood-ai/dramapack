"""ffmpeg / ffprobe discovery and measured file specs.

Binaries come from ``$DRAMAPACK_FFMPEG`` / ``$DRAMAPACK_FFPROBE`` when set, otherwise from
``PATH``. Every subprocess here has a timeout: a truncated or corrupt mp4 can make ffmpeg
read forever, and an unattended batch job that hangs silently is worse than one that fails.
"""
import os
import re
import shutil
import subprocess
import sys

TIMEOUT_SHORT = 120   # probes, single-window measurements
TIMEOUT_LONG = 1800   # full encodes / whole-file scans


def log_stderr(*args) -> None:
    """Default logger. Progress goes to stderr so stdout stays clean for ``--json``
    output and for the MCP stdio protocol."""
    print(*args, file=sys.stderr, flush=True)


def ffmpeg_exe() -> str:
    return os.environ.get("DRAMAPACK_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_exe() -> str:
    return os.environ.get("DRAMAPACK_FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def have_ffmpeg() -> bool:
    exe = ffmpeg_exe()
    return bool(shutil.which(exe) or os.path.isfile(exe))


def _info(exe: str, path: str) -> str:
    return subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True,
                          text=True, timeout=TIMEOUT_SHORT).stderr


def probe_duration(exe: str, path: str) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", _info(exe, path))
    if not m:
        return 0.0
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


def video_size(exe: str, path: str) -> tuple:
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", _info(exe, path))
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


def video_fps(exe: str, path: str, default: float = 30.0) -> float:
    m = re.search(r"Video:.*?(\d+(?:\.\d+)?)\s*fps", _info(exe, path))
    return float(m.group(1)) if m else default


def has_audio(exe: str, path: str) -> bool:
    return bool(re.search(r"Stream #.*Audio:", _info(exe, path)))


def probe_spec(exe: str, path: str) -> dict:
    """Measured specs. Numbers in a manifest must come from the file itself, never from
    a database or a config — a recipient will check them."""
    out = _info(exe, path)
    spec: dict = {"bytes": os.path.getsize(path)}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        h, mm, s = m.groups()
        spec["duration_s"] = round(int(h) * 3600 + int(mm) * 60 + float(s), 2)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if m:
        spec["width"], spec["height"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"Video:.*?,\s*(\d+)\s*kb/s", out)
    if m:
        spec["video_kbps"] = int(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", out)
    if m:
        spec["fps"] = float(m.group(1))
    m = re.search(r"Audio:\s*(\w+).*?(\d+)\s*Hz", out)
    if m:
        spec["audio"] = f"{m.group(1)} {m.group(2)}Hz"
    return spec
