"""Shared fixtures: tiny synthetic media generated with ffmpeg lavfi."""
import os
import subprocess

import pytest

from dramapack.ff import ffmpeg_exe, have_ffmpeg

EXE = ffmpeg_exe()
needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg not available")


def make_clip(path, secs=4.0, *, size="320x568", tone=440, scene_change=False):
    """A small 9:16 test clip with a tone. ``scene_change`` splices two different
    sources so the scene detector sees a cut halfway."""
    if scene_change:
        half = secs / 2
        vf = (f"[0:v][1:v]concat=n=2:v=1:a=0[v]")
        cmd = [EXE, "-y", "-v", "error",
               "-f", "lavfi", "-t", f"{half}", "-i", f"testsrc=size={size}:rate=24",
               "-f", "lavfi", "-t", f"{half}", "-i", f"smptebars=size={size}:rate=24",
               "-f", "lavfi", "-t", f"{secs}", "-i", f"sine=frequency={tone}:sample_rate=48000",
               "-filter_complex", vf, "-map", "[v]", "-map", "2:a"]
    else:
        cmd = [EXE, "-y", "-v", "error",
               "-f", "lavfi", "-t", f"{secs}", "-i", f"testsrc=size={size}:rate=24",
               "-f", "lavfi", "-t", f"{secs}", "-i", f"sine=frequency={tone}:sample_rate=48000",
               "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


SRT = """1
00:00:00,300 --> 00:00:01,800
You're in the wrong room.

2
00:00:02,000 --> 00:00:03,500
Then show me the right one.
"""


@pytest.fixture
def input_dir(tmp_path):
    """Two-episode input folder: clips, SRTs, a cover, a timeline, show + rights."""
    d = tmp_path / "input"
    d.mkdir()
    make_clip(d / "01.mp4", 4.0, tone=440)
    make_clip(d / "02.mp4", 4.0, tone=330)
    (d / "01.srt").write_text(SRT, encoding="utf-8")
    (d / "02.srt").write_text(SRT, encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (540, 960), (200, 40, 40)).save(d / "01.jpg")
    (d / "01.timeline.json").write_text(
        '{"fps": 24, "tracks": {"video": [{"id": "c1", "source": "a.mp4", "in": 0, "out": 2},'
        ' {"id": "c2", "source": "b.mp4", "in": 0, "out": 2}]}}', encoding="utf-8")
    (d / "show.json").write_text(
        '{"title": "Test Show", "studio": "Test Studio", "music_bed": "tension",'
        ' "end_card": {"title": "TEST SHOW", "lines": ["EP.{next} TOMORROW"], "secs": 1.5}}',
        encoding="utf-8")
    (d / "rights.json").write_text(
        '{"music": [], "fonts": [{"name": "Noto Sans CJK SC", "license": "OFL-1.1"}]}',
        encoding="utf-8")
    return str(d)


def rms_db(path, ss, to, band=None):
    """Mean level in a window; ``band`` band-passes first (to isolate the bed)."""
    import re
    af = "volumedetect"
    if band:
        af = f"highpass=f={band[0]},lowpass=f={band[1]},volumedetect"
    log = subprocess.run([EXE, "-nostats", "-ss", str(ss), "-to", str(to), "-i", path,
                          "-af", af, "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+)", log)
    assert m, log[-400:]
    return float(m.group(1))


@pytest.fixture
def src_dir():
    return os.path.join(os.path.dirname(__file__), "..", "src", "dramapack")
