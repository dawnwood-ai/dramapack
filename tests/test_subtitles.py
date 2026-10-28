"""ASS style slots pinned: an off-by-one once wrote MarginV into Encoding and subtitles
sat under the player's hover controls."""
import pytest

from dramapack import master as M

from conftest import EXE, needs_ffmpeg

pytestmark = needs_ffmpeg


def _style_fields(tmp_path, w, h):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")
    ass = M.ass_from_srt(EXE, str(srt), str(tmp_path), (w, h))
    txt = open(ass, encoding="utf-8").read()
    fmt = next(ln for ln in txt.splitlines() if ln.startswith("Format: Name"))
    sty = next(ln for ln in txt.splitlines() if ln.startswith("Style:"))
    names = [x.strip() for x in fmt[len("Format:"):].split(",")]
    vals = sty[len("Style:"):].strip().split(",")
    assert len(names) == len(vals) == 23
    return dict(zip(names, vals)), txt


def test_margins_are_proportional_and_fields_land_in_their_own_slots(tmp_path):
    st, txt = _style_fields(tmp_path, 1080, 1920)
    assert st["MarginV"] == str(round(1920 * M.SUB_MARGINV_FRAC))       # 346
    # 173 px each side → text box ≤ 70% of width (TikTok Drama Center safe area)
    assert st["MarginL"] == st["MarginR"] == str(round(1080 * M.SUB_MARGINLR_FRAC))
    assert 1 - 2 * M.SUB_MARGINLR_FRAC <= 0.70
    assert st["Alignment"] == "2" and st["BorderStyle"] == "1"
    assert st["Outline"] == str(M.SUB_PX["Outline"]) and st["Shadow"] == str(M.SUB_PX["Shadow"])
    assert st["Fontsize"] == str(M.SUB_PX["FontSize"]) and st["Bold"] == "-1"
    assert st["Fontname"] == M.SUB_FONT
    assert st["Encoding"] == "1"      # not overwritten by MarginV
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt


def test_margin_v_floor_on_short_frames(tmp_path):
    st, _ = _style_fields(tmp_path, 1920, 720)   # 720 × 0.18 = 130 < 150 → floor 150
    assert st["MarginV"] == "150"


def test_custom_font_is_written(tmp_path):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    txt = open(M.ass_from_srt(EXE, str(srt), str(tmp_path), (1080, 1920), font="Source Han Sans SC"),
               encoding="utf-8").read()
    assert "Style: Default,Source Han Sans SC," in txt


def test_cjk_subtitles_burn(tmp_path):
    """CJK glyphs must render (missing fonts burn in as boxes). This fixture is the one
    place CJK text is allowed in the test suite."""
    from conftest import make_clip
    clip = make_clip(tmp_path / "v.mp4", 2.0)
    srt = tmp_path / "zh.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,800\n渡轮午夜开走。\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")
    M.master(clip, str(srt), out, exe=EXE, normalize=False, log=None)
    import os
    assert os.path.getsize(out) > 0
