"""Delivery-pack unit invariants (no full build)."""
from dramapack import package as P


def _match(monkeypatch, cut_dur, master_dur, head_trim, card_secs):
    monkeypatch.setattr(P, "probe_duration", lambda _e, _p: cut_dur)
    return P.match_master_params("ffmpeg", "cut.mp4", master_dur, head_trim, card_secs)


def test_clean_master_params_follow_the_delivered_master_not_the_config(monkeypatch):
    # cut 57.90 s, master 57.83 s: that master had neither trim nor card, even though the
    # show config now has head_trim=0.95 + a 7.5 s card.
    assert _match(monkeypatch, 57.90, 57.83, 0.95, 7.5) == (0.0, 0.0)
    assert _match(monkeypatch, 57.90, 64.45, 0.95, 7.5) == (0.95, 7.5)   # trim + card
    assert _match(monkeypatch, 57.90, 56.95, 0.95, 7.5) == (0.95, 0.0)   # trim only


def test_unrecognisable_master_falls_back_to_no_trim_no_card(monkeypatch):
    assert _match(monkeypatch, 57.90, 120.0, 0.95, 7.5) == (0.0, 0.0)


def test_cover_is_three_by_four_and_cropped_from_the_top(tmp_path):
    from PIL import Image
    src = tmp_path / "src.jpg"
    im = Image.new("RGB", (1080, 1920), (0, 0, 0))
    im.paste(Image.new("RGB", (1080, 960), (255, 255, 255)), (0, 0))   # white top half
    im.save(src)
    dest = tmp_path / "out.jpg"
    info = P.make_cover(str(src), str(dest))
    assert (info["width"], info["height"]) == (1080, 1440)
    out = Image.open(dest).convert("L")
    top = out.crop((0, 0, out.width, 100)).tobytes()
    assert sum(top) / len(top) > 200, "top anchor lost — cropped from the bottom half"


def test_small_cover_is_upscaled_to_platform_minimum(tmp_path):
    from PIL import Image
    src = tmp_path / "s.png"
    Image.new("RGB", (180, 320), (9, 9, 9)).save(src)
    info = P.make_cover(str(src), str(tmp_path / "o.jpg"))
    assert info["width"] >= P.MIN_COVER[0] and info["height"] >= P.MIN_COVER[1]


def test_timeline_render_writes_png_and_edl_with_every_cut(tmp_path):
    project = {
        "fps": 30, "ratio": "9:16",
        "tracks": {
            "video": [{"id": "c1", "source": "a1.mp4", "in": 0, "out": 9.0},
                      {"id": "c2", "source": "a2.mp4", "in": 0, "out": 6.0}],
            "audio": [],
            "overlay": [{"id": "o1", "start": 0.5, "end": 3.0, "text": "line one"}],
        },
    }
    png, edl = tmp_path / "01.png", tmp_path / "01.edl.csv"
    info = P.render_timeline(project, str(png), str(edl), title="EP1")
    assert png.stat().st_size > 0
    assert info["clips"] == 3 and info["total_s"] == 15.0
    rows = edl.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 4
    assert "0.0,9.0" in rows[1] and "9.0,15.0" in rows[2]       # contiguous cuts
    assert "a1.mp4" in rows[1]


def test_timeline_accepts_media_id_mapping(tmp_path):
    project = {"media": [{"id": "m1", "src_ref": "shot7"}],
               "tracks": {"video": [{"id": "c1", "media_id": "m1", "in": 0, "out": 2}]}}
    P.render_timeline(project, str(tmp_path / "t.png"), str(tmp_path / "t.csv"))
    assert "shot7" in (tmp_path / "t.csv").read_text()


def test_discover_and_show_loading(tmp_path):
    for n in ("1.mp4", "02.mp4", "02.srt", "02.cut.mp4", "02.timeline.json", "02.ui.png",
              "1.cover.png", "notes.mp4"):
        (tmp_path / n).write_bytes(b"x")
    found = P.discover(str(tmp_path))
    assert sorted(found) == [1, 2]
    assert found[1]["cover"].endswith("1.cover.png")
    assert found[2]["srt"] and found[2]["cut"] and found[2]["timeline"] and found[2]["ui"]
    (tmp_path / "show.json").write_text('{"title": "X", "music_bed": true, "episodes": {"01": {"title": "P"}}}')
    show = P.load_show(str(tmp_path), studio="S")
    assert show["music_bed"] == "tension" and show["studio"] == "S" and show["episodes"][1]["title"] == "P"
