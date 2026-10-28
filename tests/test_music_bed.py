"""The continuous music bed must **duck under dialogue** and never cover it, while
staying audible in the band phone speakers actually reproduce (300–3000 Hz)."""
import os
import subprocess

from dramapack import master as M

from conftest import EXE, needs_ffmpeg, rms_db

pytestmark = needs_ffmpeg


def test_music_bed_ducks_under_dialogue(tmp_path):
    vid, bed, out = (str(tmp_path / n) for n in ("v.mp4", "bed.mp3", "out.mp4"))
    # Dialogue = high-passed pink noise only between 3–6 s. High-passed above 1 kHz so the
    # 180–280 Hz window below sees only the 220 Hz bed (broadband noise has its own energy
    # in that band and would mask whether the bed was pushed down).
    subprocess.run(
        [EXE, "-y", "-v", "error",
         "-f", "lavfi", "-t", "9", "-i", "testsrc=size=320x568:rate=24",
         "-f", "lavfi", "-t", "9", "-i", "anoisesrc=amplitude=0.5:color=pink",
         "-filter_complex", "[1:a]highpass=f=1000,volume=enable='between(t,3,6)':volume=1,"
                            "volume=enable='not(between(t,3,6))':volume=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", vid], check=True, capture_output=True)
    subprocess.run([EXE, "-y", "-v", "error", "-f", "lavfi", "-t", "9",
                    "-i", "sine=frequency=220", "-c:a", "libmp3lame", bed],
                   check=True, capture_output=True)
    M.master(vid, None, out, burn=False, music=bed, exe=EXE, log=None)
    bed_quiet = rms_db(out, 0.5, 2.5, band=(180, 280))
    bed_talk = rms_db(out, 3.5, 5.5, band=(180, 280))
    assert bed_quiet > -60, f"bed should be audible in quiet passages, got {bed_quiet} dB"
    assert bed_talk < bed_quiet - 3, (
        f"bed not ducked under dialogue: quiet {bed_quiet:.1f} dB / talk {bed_talk:.1f} dB")
    assert rms_db(out, 3.5, 5.5) > rms_db(out, 0.5, 2.5), "dialogue passage must be louder overall"


def test_no_music_leaves_audio_path_untouched(tmp_path):
    from conftest import make_clip
    vid, out = make_clip(tmp_path / "v.mp4", 3.0), str(tmp_path / "out.mp4")
    M.master(vid, None, out, burn=False, exe=EXE, log=None)
    assert os.path.getsize(out) > 0


def test_bed_stays_subordinate_and_rolls_off_above_the_voice(tmp_path):
    """Energy centred low (doesn't fight the lines) and rolled off above ~2.6 kHz (no
    harshness) — but see the next test: not so low it's inaudible on phones."""
    out = str(tmp_path / "bed.wav")
    M.render_bed(EXE, 8, out)
    low = rms_db(out, 0, 8, band=(20, 300))
    mid = rms_db(out, 0, 8, band=(300, 3000))
    top = rms_db(out, 0, 8, band=(4000, 12000))
    assert low > mid
    assert top < mid - 15, f"should roll off above 2.6 kHz: top {top:.1f} vs mid {mid:.1f}"


def test_bed_is_audible_in_the_band_phones_can_actually_reproduce(tmp_path):
    """A bed with all its energy under 300 Hz measured great on full-band seam metrics and
    was inaudible on phones (−58 dBFS in 300–3000 Hz, 42 dB under dialogue)."""
    out = str(tmp_path / "bed.wav")
    M.render_bed(EXE, 8, out)
    low = rms_db(out, 0, 8, band=(20, 300))
    mid = rms_db(out, 0, 8, band=(300, 3000))
    assert mid > low - 10, f"bed is almost all sub-300 Hz: low {low:.1f} / mid {mid:.1f}"
    assert M.BED_TILT_DB >= 8, "the midrange lift is where this property comes from"


def test_bed_does_not_eat_the_dialogue_band(tmp_path):
    """Red line: background level, never covering the dialogue. Under lines the bed's
    contribution to the speech band must be negligible (measured +0.1 dB) — via ducking,
    not by making the bed inaudible. normalize=False: this measures a ratio, and the final
    gain/limiter pass would muddy absolute levels."""
    vid, out_b, out_n = (str(tmp_path / n) for n in ("v.mp4", "b.mp4", "n.mp4"))
    subprocess.run(
        [EXE, "-y", "-v", "error",
         "-f", "lavfi", "-t", "6", "-i", "testsrc=size=320x568:rate=24",
         "-f", "lavfi", "-t", "6", "-i", "anoisesrc=amplitude=0.5:color=pink",
         "-filter_complex", "[1:a]volume=enable='between(t,2,4)':volume=1,"
                            "volume=enable='not(between(t,2,4))':volume=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", vid], check=True, capture_output=True)
    bed = M.render_bed(EXE, 8, str(tmp_path / "bed.wav"))
    M.master(vid, None, out_n, burn=False, exe=EXE, normalize=False, log=None)
    M.master(vid, None, out_b, burn=False, music=bed, exe=EXE, normalize=False, log=None)
    talk_n = rms_db(out_n, 2.3, 3.7, band=(300, 3000))
    talk_b = rms_db(out_b, 2.3, 3.7, band=(300, 3000))
    full_n = rms_db(out_n, 2.3, 3.7, band=(20, 20000))
    full_b = rms_db(out_b, 2.3, 3.7, band=(20, 20000))
    # Compare the in-band *ratio*, not absolute levels: if the bed leaked into the speech
    # band under dialogue, the ratio would move.
    bed_leak = (talk_b - full_b) - (talk_n - full_n)
    assert bed_leak < 1.0, f"bed adds {bed_leak:+.1f} dB to the speech band under dialogue"


def test_bed_level_and_fades_are_the_measured_ones(src_dir):
    """−6 dB was measured in the band phones play — and measured wrong once. Changing it
    means re-measuring the quiet-passage 300–3000 Hz level, not just the seams."""
    assert M.MUSIC_DB == -6.0
    src = open(os.path.join(src_dir, "master.py"), encoding="utf-8").read()
    assert "\u221240.2" in src and "people don't listen full-band" in src
    # A 2 s fade-in made every cold open sound empty.
    assert M.BED_FADE_IN <= 0.6 and M.BED_FADE_OUT >= 1.0


def test_bed_graph_uses_the_fade_constants():
    import inspect
    src = inspect.getsource(M.render_bed)
    assert "BED_FADE_IN" in src and "BED_FADE_OUT" in src


def test_every_preset_renders_and_sections_join(tmp_path):
    for mood in M.BED_MOODS:
        assert os.path.getsize(M.render_bed(EXE, 2.5, str(tmp_path / f"{mood}.wav"), mood)) > 0
    out = M.render_bed_sections(EXE, [{"secs": 3, "mood": "warm"}, {"secs": 3, "mood": "dread"}],
                                str(tmp_path / "sec.wav"), xf=1.0)
    from dramapack.ff import probe_duration
    assert abs(probe_duration(EXE, out) - 6.0) < 0.3
