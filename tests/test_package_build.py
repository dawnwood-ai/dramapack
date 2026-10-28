"""End-to-end smoke: a full pack from two synthetic episodes."""
import json
import os

from dramapack import PROVENANCE, footer_line
from dramapack import package as P

from conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def test_full_pack(input_dir, tmp_path):
    out = str(tmp_path / "out")
    man = P.build(input_dir, out, platform_pairs=True, log=lambda *_: None)
    for rel in ("episodes/01.mp4", "episodes/01.srt", "episodes/02.mp4", "episodes/02.srt",
                "clean/01.mp4", "clean/02.mp4", "covers/01.jpg", "covers/02.jpg",
                "timeline/01.png", "timeline/01.edl.csv",
                "platform/episodes/01.mp4", "platform/episodes/01.srt", "platform/clean/01.mp4",
                "docs/CHAIN-OF-TITLE.md", "docs/AI-DISCLOSURE.md", "manifest.json", "README.md"):
        assert os.path.exists(os.path.join(out, rel)), rel
    assert not os.path.exists(os.path.join(out, "_work")), "scratch must not ship"

    disk = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    assert disk["generator"] == PROVENANCE
    ep1 = disk["episodes"][0]["files"]
    # 4 s cut + 1.5 s end card; clean and subtitled are the same edit
    assert abs(ep1["episode"]["duration_s"] - 5.5) < 0.3
    assert abs(ep1["clean_master"]["duration_s"] - ep1["episode"]["duration_s"]) < 0.2
    assert ep1["cover"]["source"] == "supplied" and disk["episodes"][1]["files"]["cover"]["source"] == "video frame"
    assert ep1["cover"]["width"] * 4 == ep1["cover"]["height"] * 3
    assert disk["rights"]["status"] in ("green", "yellow")
    assert any(f.get("source") == "procedural" for f in disk["rights"]["findings"])
    assert not [g for g in disk["gaps"] if "do not ship" in g]
    assert disk["platform"][0]["source_episodes"] == [1, 2]

    for doc in ("README.md", "docs/AI-DISCLOSURE.md", "docs/CHAIN-OF-TITLE.md"):
        assert footer_line() in open(os.path.join(out, doc), encoding="utf-8").read(), doc
    cot = open(os.path.join(out, "docs/CHAIN-OF-TITLE.md"), encoding="utf-8").read()
    assert "Do not submit unsigned" in cot and "[FULL LEGAL NAME OR ENTITY]" in cot
    assert man["title"] == "Test Show"


def test_clean_master_is_louder_than_raw_cut(input_dir, tmp_path):
    """Clean master = master minus subtitles, not master minus mastering."""
    from conftest import rms_db
    out = str(tmp_path / "out")
    P.build(input_dir, out, episodes=[2], covers=False, timeline=False, log=lambda *_: None)
    raw = rms_db(os.path.join(input_dir, "02.mp4"), 0.5, 3.5)
    clean = rms_db(os.path.join(out, "clean", "02.mp4"), 0.5, 3.5)
    assert clean > raw + 2


def test_masters_ready_without_cut_reports_gap(input_dir, tmp_path):
    out = str(tmp_path / "out")
    man = P.build(input_dir, out, masters_ready=True, episodes=[1], covers=False,
                  timeline=False, log=lambda *_: None)
    assert any("01.cut.mp4" in g for g in man["gaps"])
    assert man["episodes"][0]["files"]["episode"]["path"] == "episodes/01.mp4"


def test_head_trim_shifts_delivered_srt(input_dir, tmp_path):
    show = P.load_show(input_dir, head_trim=0.3, end_card=None, music_bed=None)
    out = str(tmp_path / "out")
    P.build(input_dir, out, show=show, episodes=[1], clean=False, covers=False,
            timeline=False, log=lambda *_: None)
    txt = open(os.path.join(out, "episodes", "01.srt"), encoding="utf-8").read()
    assert "00:00:00,000 --> 00:00:01,500" in txt
