"""CLI wiring and provenance."""
import json

import pytest

from dramapack import PROVENANCE, cli


def test_provenance_constant():
    assert PROVENANCE["name"] == "dramapack"
    assert PROVENANCE["url"].startswith("https://github.com/dawnwood-ai/")
    assert "dawnwood.ai" in PROVENANCE["by"]


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert PROVENANCE["version"] in capsys.readouterr().out


def test_package_has_no_flag_to_drop_the_credit():
    help_text = cli.build_parser()._subparsers._group_actions[0].choices["package"].format_help()
    assert "generator" not in help_text and "provenance" not in help_text.lower()


def test_check_rights_exit_codes(tmp_path, capsys):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"music": [{"cue": "a", "source": "procedural"}]}))
    assert cli.main(["check-rights", str(ok), "--no-mastering-fonts"]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"music": [{"cue": "a", "source": "unknown"}]}))
    assert cli.main(["check-rights", str(bad), "--no-mastering-fonts", "--json"]) == 1
    out = capsys.readouterr().out
    assert '"status": "red"' in out


def _run_json(capsys, argv):
    rc = cli.main(argv + ["--json"])
    out = capsys.readouterr().out
    return rc, json.loads(out)          # stdout must be exactly one JSON object


def test_exit_codes_usage_and_failure(capsys, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["audit"])                       # missing files → argparse usage error
    assert e.value.code == cli.EXIT_USAGE == 2
    rc, out = _run_json(capsys, ["inspect", str(tmp_path / "missing.mp4")])
    assert rc == cli.EXIT_FAIL == 3 and out["ok"] is False and "missing.mp4" in out["error"]


from conftest import make_clip, needs_ffmpeg  # noqa: E402


@needs_ffmpeg
def test_json_on_every_media_subcommand(capsys, tmp_path, input_dir):
    clip = make_clip(tmp_path / "c.mp4", 3.0)
    rc, out = _run_json(capsys, ["inspect", clip])
    assert rc == 0 and out["width"] == 320 and "integrated_lufs" in out

    rc, out = _run_json(capsys, ["master", clip, str(tmp_path / "m.mp4"), "--no-burn"])
    assert rc == 0 and out["output"].endswith("m.mp4") and out["generator"]["name"] == "dramapack"

    rc, out = _run_json(capsys, ["audit", clip, "--no-speech"])
    assert rc == 1 and out["status"] == "red"     # 3 s clip fails the duration line
    assert out["rows"][0]["grades"]["dur"] == "red" and "thresholds" in out

    rc, out = _run_json(capsys, ["package", input_dir, str(tmp_path / "pack"),
                                 "--episodes", "1", "--no-clean", "--no-timeline"])
    assert rc == 0 and out["status"] in ("green", "yellow")
    assert out["manifest"].endswith("manifest.json")
    assert out["episodes"][0]["files"]["episode"].endswith("episodes/01.mp4")
    assert out["generator"]["by"].startswith("Dawnwood")
