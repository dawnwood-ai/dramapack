"""Loudness must be a **constant gain**, never dynamic pumping.

Symptom it guards against: a clean take that turns hissy once mastered. Measured on a
real master: quiet passages +33 dB, near-silent tail +49 dB, noise floor −76 → −30 dBFS.
Causes: (1) ``loudnorm linear=true`` only *permits* linear mode and silently falls back to
dynamic when source LRA > target LRA (11) or the gain would break TP — dialogue-with-pauses
takes run LRA 15–20; (2) a single-pass dynamic loudnorm in the mastering graph.
Fix: measure integrated LUFS → constant ``volume`` + ``alimiter``; no loudnorm in graphs."""
import os
import re
import subprocess

from dramapack import master as M

from conftest import EXE, needs_ffmpeg, rms_db


def _wide_lra_clip(path):
    """Three steps of pure tone, 4 s each: loud (≈ −18 dBFS, like dialogue) / soft (≈ −26,
    like a hushed line) / faint (≈ −36, like room tone in a pause). input_lra ≈ 18 > 11 —
    exactly the material that makes linear loudnorm fall back to dynamic, where the three
    steps get lifted +5 / +7 / +12 dB (the fainter, the more: the noise-floor mechanism).
    A constant gain lifts all three the same."""
    subprocess.run(
        [EXE, "-y", "-v", "error",
         "-f", "lavfi", "-t", "12", "-i", "testsrc=size=320x568:rate=24",
         "-f", "lavfi", "-t", "4", "-i", "sine=frequency=330:sample_rate=48000",
         "-f", "lavfi", "-t", "4", "-i", "sine=frequency=440:sample_rate=48000",
         "-f", "lavfi", "-t", "4", "-i", "sine=frequency=220:sample_rate=48000",
         "-filter_complex",
         "[1:a]volume=6dB,aformat=channel_layouts=stereo[a1];"
         "[2:a]volume=-2dB,aformat=channel_layouts=stereo[a2];"
         "[3:a]volume=-12dB,aformat=channel_layouts=stereo[a3];"
         "[a1][a2][a3]concat=n=3:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", path],
        check=True, capture_output=True)


@needs_ffmpeg
def test_normalize_loudness_is_constant_gain(tmp_path):
    src, out = str(tmp_path / "src.mp4"), str(tmp_path / "out.mp4")
    _wide_lra_clip(src)
    M.normalize_loudness(src, out, exe=EXE, log=None)
    gains = [rms_db(out, a, b) - rms_db(src, a, b) for a, b in ((0.5, 3.5), (4.5, 7.5), (8.5, 11.5))]
    loud, soft, faint = gains
    assert abs(soft - loud) < 1.5 and abs(faint - loud) < 1.5, (
        f"not a constant gain: loud {loud:+.1f} / soft {soft:+.1f} / faint {faint:+.1f} dB — "
        "lifting the faint step separately is lifting the noise floor")
    assert loud > 0.5, f"source ≈ −18 LUFS should be lifted toward −14, got {loud:+.1f}"


def _code_only(text):
    """Strip docstrings and comments — comments may of course mention loudnorm."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def test_master_graphs_carry_no_dynamic_loudnorm(src_dir):
    assert "loudnorm" not in M.duck_graph(), "bed mix chain grew a single-pass loudnorm"
    src = open(os.path.join(src_dir, "master.py"), encoding="utf-8").read()
    body = _code_only(src[src.index("def master("):src.index("def concat_mp4")])
    assert "loudnorm" not in body.replace("normalize_loudness", ""), \
        "loudnorm in master()'s graph — normalisation must only be normalize_loudness's constant gain"
    nl = _code_only(src[src.index("def normalize_loudness"):src.index("def master(")])
    assert "linear=true" not in nl and "loudnorm" not in nl
    assert "volume=" in nl and "alimiter" in nl


def test_loudness_gain_is_clamped():
    assert M.loudness_gain_db(-20.7) == 6.7          # target −14
    assert M.loudness_gain_db(-40.0) == M.GAIN_MAX_DB
    assert M.loudness_gain_db(20.0) == M.GAIN_MIN_DB
    assert M.loudness_gain_db(-20.0, target=-16) == 4.0


def test_follow_first_gains():
    assert M.loudness_gains([-20.0, -23.0, -19.8, None, -50.0]) == [0.0, 3.0, 0.0, 0.0, 0.0]
    assert M.loudness_gains([-50.0, -20.0]) == [0.0, 0.0]   # near-silent first part: no alignment


def test_match_gains_use_median_not_first_part():
    # A quiet first part must not drag everyone else down.
    g = M.loudness_match_gains([-32.9, -20.4, -22.3])     # median target −22.3
    assert g == [10.6, -1.9, 0.0]
    first = M.loudness_gains([-32.9, -20.4, -22.3])        # follow-first drags others down
    assert first[1] == -12.0, "and hits the clamp without aligning"
    assert M.loudness_match_gains([None, -60.0]) == [0.0, 0.0]
