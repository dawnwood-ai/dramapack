"""SRT invariants.

1. **A head trim must shift the subtitles.** ``-ss`` as an input option resets timestamps
   while the ass filter's times are absolute — trim the picture only and every line is
   late by the trim.
2. Joining episodes offsets by the measured file duration, not the last cue.
3. Merged cues never overlap (two lines burned on top of each other).
"""
from dramapack import srt as S

SRT = """1
00:00:00,780 --> 00:00:02,940
You're in the wrong room.

2
00:00:02,940 --> 00:00:04,710
Spell it correctly.

3
00:00:10,000 --> 00:00:12,000
Family sits here.
"""


def _shift(tmp_path, delta, text=SRT):
    src = tmp_path / "in.srt"
    src.write_text(text, encoding="utf-8")
    return open(S.shift_srt(str(src), str(tmp_path / "out.srt"), delta), encoding="utf-8").read()


def test_head_trim_shifts_every_cue_earlier(tmp_path):
    out = _shift(tmp_path, -0.95)
    assert "00:00:00,000 --> 00:00:01,990" in out       # 0.78 clamps to 0 / 2.94 → 1.99
    assert "00:00:01,990 --> 00:00:03,760" in out
    assert "00:00:09,050 --> 00:00:11,050" in out
    assert "00:00:00,780" not in out


def test_cue_entirely_inside_the_trimmed_head_is_dropped(tmp_path):
    text = ("1\n00:00:00,100 --> 00:00:00,400\ngone\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nkept\n")
    out = _shift(tmp_path, -1.0, text)
    assert "gone" not in out and "kept" in out
    assert out.lstrip().startswith("1"), "renumber after dropping — no holes"


def test_no_shift_is_a_no_op_on_timings(tmp_path):
    out = _shift(tmp_path, 0.0)
    assert "00:00:00,780 --> 00:00:02,940" in out
    assert out.count("-->") == 3


def test_merge_shifts_by_measured_duration_not_last_cue(tmp_path):
    """Second episode offset = first episode's *file* duration. End cards carry no
    subtitles; using the subtitle length would pull the second half early."""
    pa, pb, out = tmp_path / "a.srt", tmp_path / "b.srt", tmp_path / "m.srt"
    pa.write_text("1\n00:00:01,000 --> 00:00:03,000\nfirst line\n\n")
    pb.write_text("1\n00:00:00,500 --> 00:00:02,500\nsecond line\n\n")
    n = S.merge_srt(str(pa), str(pb), 57.83, str(out))
    text = out.read_text()
    assert n == 2
    assert "00:00:01,000 --> 00:00:03,000" in text
    assert "00:00:58,330 --> 00:01:00,330" in text, text
    assert text.strip().startswith("1\n") and "\n2\n" in text


def test_merge_srts_never_overlaps():
    a = "1\n00:00:01,000 --> 00:00:05,500\nheld past the part end\n"
    b = "1\n00:00:00,200 --> 00:00:02,000\nnext part first line\n"
    out = S.merge_srts([(a, 0.0), (b, 5.0)])
    assert "00:00:01,000 --> 00:00:05,140" in out      # clamped to next start − 60 ms
    assert "00:00:05,200 --> 00:00:07,000" in out
    assert out.count("-->") == 2


def test_merge_srts_skips_broken_blocks():
    out = S.merge_srts([("garbage\n\n1\n00:00:01,000 --> 00:00:02,000\nok\n", 0.0), ("", 3.0)])
    assert out.count("-->") == 1 and "ok" in out
