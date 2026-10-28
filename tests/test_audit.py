"""Acceptance audit: grading direction, frozen-tail parsing, and a real measurement."""
from dramapack import audit as A

from conftest import make_clip, needs_ffmpeg


def test_grade_direction():
    assert A.grade("dur", 70) == "green" and A.grade("dur", 62) == "yellow" and A.grade("dur", 50) == "red"
    assert A.grade("asl", 1.5) == "green" and A.grade("asl", 3.5) == "red"
    assert A.grade("mean_volume", -18) == "green" and A.grade("mean_volume", -25) == "red"
    assert A.grade("tail_static", 4.0) == "green" and A.grade("tail_static", 7.5) == "red"
    assert A.grade("seam_db", None) == "-"


def test_tail_static_only_counts_freezes_reaching_the_end():
    to_eof = "freeze_start: 10.5\n"
    assert A.tail_static_from_log(to_eof, 15.0) == 4.5
    recovered = "freeze_start: 3.0\nfreeze_end: 6.0\n"
    assert A.tail_static_from_log(recovered, 15.0) == 0.0
    touching = "freeze_start: 9.0\nfreeze_end: 14.8\n"
    assert A.tail_static_from_log(touching, 15.0) == 6.0
    assert A.tail_static_from_log("", 15.0) == 0.0


@needs_ffmpeg
def test_audit_measures_a_clip(tmp_path):
    clip = make_clip(tmp_path / "e.mp4", 6.0, scene_change=True)
    r = A.audit(clip, do_speech=False, bounds=[3.0])
    assert abs(r["dur"] - 6.0) < 0.3
    assert r["cuts"] >= 1
    assert r["grades"]["dur"] == "red"          # 6 s is far under the 1-minute line
    assert "seam_db" in r and r["mean_volume"] is not None
    assert "hook" not in r["grades"], "hook check must be off by default"


def _plugin_fail(path, exe):
    return {"fails": ["first frame shows no person"], "warns": [], "note": "empty room"}


def _plugin_crash(path, exe):
    raise RuntimeError("no credentials")


@needs_ffmpeg
def test_hook_plugin_is_pluggable_and_failure_safe(tmp_path):
    clip = make_clip(tmp_path / "e.mp4", 3.0)
    r = A.audit(clip, do_speech=False, hook_plugin=A.load_hook_plugin("test_audit:_plugin_fail"))
    assert r["grades"]["hook"] == "red" and "hook" in r["red"]
    r = A.audit(clip, do_speech=False, hook_plugin=_plugin_crash)
    assert "hook" not in r["grades"], "a broken checker must degrade to skipped, never red"


@needs_ffmpeg
def test_pair_mode_splits_metrics(tmp_path):
    cut = make_clip(tmp_path / "cut.mp4", 3.0)
    mas = make_clip(tmp_path / "master.mp4", 3.0)
    c, m = A.audit_pair(mas, cut, do_speech=False)
    assert set(m["grades"]) <= A.MASTER_KEYS
    assert "asl" in c["grades"] and "tail_static" not in c["grades"]
