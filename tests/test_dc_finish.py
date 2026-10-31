"""TikTok Drama Center: dark edge bands (audit) and the tiktok-dc finishing (package)."""
import json
import os
import subprocess

from dramapack import audit as A
from dramapack import master as M
from dramapack import package as P

from conftest import EXE, needs_ffmpeg


def make_band_clip(path, secs=5.0, *, side_px=12, audio=True):
    """testsrc with a black band ``side_px`` wide down the left edge."""
    cmd = [EXE, "-y", "-v", "error", "-f", "lavfi", "-t", str(secs),
           "-i", "testsrc=size=320x568:rate=24"]
    if audio:
        cmd += ["-f", "lavfi", "-t", str(secs), "-i", "sine=frequency=440:sample_rate=48000"]
    cmd += ["-vf", f"drawbox=x=0:y=0:w={side_px}:h=ih:color=black:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [str(path)], check=True, capture_output=True)
    return str(path)


def frame0_rgb(path, x, y):
    """RGB of one pixel of frame 0."""
    raw = subprocess.run([EXE, "-v", "error", "-i", path, "-frames:v", "1",
                          "-vf", f"format=rgb24,crop=2:2:{x}:{y}", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return tuple(raw[:3])


def test_edge_runs_longest_dark_run_per_side():
    dark, lit = 3.0, 80.0
    series = {"left": [(i / 5, dark if 5 <= i < 25 else lit) for i in range(40)],
              "right": [(i / 5, lit) for i in range(40)]}
    runs = A.edge_runs(series)
    assert runs["left"] == {"secs": 4.0, "at": 1.0}
    assert runs["right"]["secs"] == 0.0
    m = A.edge_metrics(runs)
    assert m["edge_dark_side"] == "left" and A.grade("edge_dark", m["edge_dark"]) == "red"
    assert A.grade("edge_dark", 3.0) == "yellow" and A.grade("edge_dark", 1.0) == "green"


@needs_ffmpeg
def test_audit_flags_black_side_band(tmp_path):
    r = A.audit(make_band_clip(tmp_path / "b.mp4"), do_speech=False)
    assert r["edge_dark_side"] == "left" and r["edge_dark"] >= 4.5
    assert r["grades"]["edge_dark"] == "red" and "edge_dark" in r["red"]
    assert r["edge_sides"]["right"]["secs"] == 0.0
    assert "dark edge left" in A.format_table([r])


@needs_ffmpeg
def test_audit_flags_thin_padded_column(tmp_path):
    """A 1078-wide render padded to 1080 (here at half size): a black column the 20 px band
    averages away."""
    clip = str(tmp_path / "p.mp4")
    subprocess.run([EXE, "-y", "-v", "error", "-f", "lavfi", "-t", "5",
                    "-i", "testsrc=size=538x960:rate=24", "-vf", "pad=540:960:0:0:black",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", clip],
                   check=True, capture_output=True)
    r = A.audit(clip, do_speech=False)
    assert r["edge_dark_side"] == "right" and r["grades"]["edge_dark"] == "red"


@needs_ffmpeg
def test_edge_lift_removes_the_band(tmp_path):
    src = make_band_clip(tmp_path / "b.mp4")
    out = str(tmp_path / "lifted.mp4")
    info = M.dc_finish(src, out, lift=True, exe=EXE, log=None)
    assert info["edge_lift"] and info["cover_head_s"] == 0.0
    r = A.audit(out, do_speech=False)
    assert r["grades"]["edge_dark"] == "green" and r["edge_dark"] == 0.0
    assert abs(r["dur"] - 5.0) < 0.2
    # Lighten only lifts dark pixels: the middle of the picture is unchanged.
    a, b = frame0_rgb(src, 160, 284), frame0_rgb(out, 160, 284)
    assert max(abs(x - y) for x, y in zip(a, b)) < 24
    assert not os.path.exists(os.path.splitext(out)[0] + ".mask.png")


@needs_ffmpeg
def test_cover_head_makes_frame0_the_cover(tmp_path):
    from PIL import Image
    cover = str(tmp_path / "cover.jpg")
    Image.new("RGB", (540, 960), (200, 40, 40)).save(cover)
    src = make_band_clip(tmp_path / "b.mp4", 4.0)
    out = str(tmp_path / "dc.mp4")
    M.dc_finish(src, out, cover=cover, exe=EXE, log=None)
    r, g, b = frame0_rgb(out, 160, 284)
    assert r > 170 and g < 70 and b < 70, (r, g, b)
    from dramapack.ff import probe_spec
    spec = probe_spec(EXE, out)
    assert abs(spec["duration_s"] - 5.0) < 0.2 and spec["width"] == 320 and "audio" in spec
    # Without audio in the source the head is video-only.
    silent = make_band_clip(tmp_path / "s.mp4", 2.0, audio=False)
    M.dc_finish(silent, str(tmp_path / "s_dc.mp4"), cover=cover, lift=False, exe=EXE, log=None)
    assert frame0_rgb(str(tmp_path / "s_dc.mp4"), 160, 284)[0] > 170


@needs_ffmpeg
def test_package_tiktok_dc_target(input_dir, tmp_path):
    out = str(tmp_path / "out")
    man = P.build(input_dir, out, episodes=[1], timeline=False, target="tiktok-dc",
                  log=lambda *_: None)
    assert man["target"] == "tiktok-dc" and man["dc_finish"]["cover_head_s"] == 1.0
    ep = man["episodes"][0]
    f = ep["files"]
    # 4 s cut + 1.5 s end card + 1 s cover head, both versions
    assert abs(f["episode"]["duration_s"] - 6.5) < 0.3
    assert abs(f["clean_master"]["duration_s"] - f["episode"]["duration_s"]) < 0.2
    assert f["episode"]["cover_head_s"] == 1.0 and f["episode"]["edge_lift"] is True
    assert ep["thumbnail"] == {"frame0": "cover"}
    assert f["srt"]["shifted_s"] == 1.0
    srt = open(os.path.join(out, "episodes", "01.srt"), encoding="utf-8").read()
    assert "00:00:01,300 --> 00:00:02,800" in srt
    r, g, b = frame0_rgb(os.path.join(out, "episodes", "01.mp4"), 160, 284)
    assert r > 170 and g < 70, (r, g, b)
    disk = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    assert disk["episodes"][0]["thumbnail"]["frame0"] == "cover"
    assert "Drama Center" in open(os.path.join(out, "README.md"), encoding="utf-8").read()


@needs_ffmpeg
def test_package_tiktok_dc_opt_outs(input_dir, tmp_path):
    out = str(tmp_path / "out")
    man = P.build(input_dir, out, episodes=[1], clean=False, covers=False, timeline=False,
                  target="tiktok-dc", cover_head=False, log=lambda *_: None)
    f = man["episodes"][0]["files"]
    assert abs(f["episode"]["duration_s"] - 5.5) < 0.3 and f["episode"]["edge_lift"] is True
    assert "shifted_s" not in f["srt"]
    assert man["episodes"][0]["thumbnail"] == {"frame0": "picture"}
    man = P.build(input_dir, str(tmp_path / "out2"), episodes=[1], clean=False, covers=False,
                  timeline=False, target="tiktok-dc", cover_head=False, edge_lift=False,
                  log=lambda *_: None)
    assert man["dc_finish"] is None and "thumbnail" not in man["episodes"][0]
