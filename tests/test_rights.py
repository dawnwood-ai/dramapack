"""Rights check: music sources, major labels, fonts, ASS scanning."""
import json

from dramapack import rights as R


def _write(tmp_path, data):
    p = tmp_path / "rights.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _levels(res):
    return {f["item"]: f["level"] for f in res["findings"]}


def test_missing_rights_file_is_red():
    res = R.check_rights(None, check_installed=False)
    assert res["status"] == "red"


def test_empty_music_list_is_a_valid_declaration(tmp_path):
    res = R.check_rights(_write(tmp_path, {"music": []}), check_installed=False)
    assert res["status"] == "green"


def test_music_grades(tmp_path):
    (tmp_path / "lic.pdf").write_bytes(b"%PDF")
    res = R.check_rights(_write(tmp_path, {"music": [
        {"cue": "unknown", "source": "unknown"},
        {"cue": "nosrc"},
        {"cue": "major", "source": "licensed", "publisher": "Sony Music Publishing", "proof": "lic.pdf"},
        {"cue": "warner-imprint", "source": "licensed", "label": "Atlantic Records", "proof": "lic.pdf"},
        {"cue": "noproof", "source": "licensed", "publisher": "Small Artist"},
        {"cue": "missingproof", "source": "licensed", "proof": "nope.pdf"},
        {"cue": "proof", "source": "licensed", "proof": "lic.pdf"},
        {"cue": "url-proof", "source": "licensed", "proof": "https://example.com/licence"},
        {"cue": "pd-old", "source": "public_domain", "year": 1890},
        {"cue": "pd-recent", "source": "public_domain", "year": 2001},
        {"cue": "pd-noyear", "source": "public_domain"},
        {"cue": "ai", "source": "generated", "tool": "x"},
        {"cue": "proc", "source": "procedural"},
        {"cue": "custom-block", "source": "licensed", "publisher": "Bad Catalogue Ltd", "proof": "lic.pdf"},
    ], "blocked_publishers": ["Bad Catalogue"]}), check_installed=False)
    lv = _levels(res)
    assert lv["unknown"] == lv["nosrc"] == lv["major"] == lv["warner-imprint"] == "red"
    assert lv["pd-recent"] == lv["custom-block"] == "red"
    assert lv["noproof"] == lv["missingproof"] == lv["pd-noyear"] == "yellow"
    assert lv["proof"] == lv["url-proof"] == lv["pd-old"] == lv["ai"] == lv["proc"] == "green"
    assert res["status"] == "red"


def test_procedural_bed_is_auto_declared(tmp_path):
    res = R.check_rights(_write(tmp_path, {"music": []}), bed_mood="tension", check_installed=False)
    assert any(f["source"] == "procedural" and f["level"] == "green" for f in res["findings"])


def test_undeclared_external_music_is_red(tmp_path):
    p = _write(tmp_path, {"music": []})
    assert R.check_rights(p, external_music="/x/theme.wav", check_installed=False)["status"] == "red"
    p = _write(tmp_path, {"music": [{"cue": "t", "file": "theme.wav", "source": "generated"}]})
    assert R.check_rights(p, external_music="/x/theme.wav", check_installed=False)["status"] == "green"


def test_fonts(tmp_path):
    (tmp_path / "f.pdf").write_bytes(b"%PDF")
    res = R.check_rights(_write(tmp_path, {"music": [], "fonts": [
        {"name": "Noto Serif CJK TC"},
        {"name": "Source Han Sans SC"},
        {"name": "Arial"},
        {"name": "Some Free Face", "license": "SIL OFL 1.1"},
        {"name": "Bought Face", "license": "commercial video licence", "proof": "f.pdf"},
        {"name": "Mystery Face", "license": "personal use only"},
        {"name": "House Face"},
    ], "font_allowlist": ["House Face"]}), check_installed=False)
    lv = _levels(res)
    assert lv["Noto Serif CJK TC"] == lv["Source Han Sans SC"] == lv["House Face"] == "green"
    assert lv["Some Free Face"] == lv["Bought Face"] == "green"
    assert lv["Arial"] == lv["Mystery Face"] == "red"


def test_mastering_subtitle_font_is_checked(tmp_path):
    res = R.check_rights(_write(tmp_path, {"music": []}), subtitle_font="Arial", check_installed=False)
    assert _levels(res)["Arial"] == "red"
    res = R.check_rights(_write(tmp_path, {"music": []}), subtitle_font="Comic Face",
                         extra_allow_fonts=["Comic Face"], check_installed=False)
    assert res["status"] == "green"


def test_ass_scan(tmp_path):
    (tmp_path / "ep.ass").write_text(
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Default,Noto Sans,52\n"
        "Style: Sign,Impact,40\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,"
        "{\\fnComic Sans MS}hi\n", encoding="utf-8")
    assert R.ass_font_names((tmp_path / "ep.ass").read_text()) == ["Noto Sans", "Impact", "Comic Sans MS"]
    res = R.check_rights(_write(tmp_path, {"music": []}), input_dir=str(tmp_path), check_installed=False)
    lv = _levels(res)
    assert lv["Noto Sans"] == "green" and lv["Impact"] == "red" and lv["Comic Sans MS"] == "red"


def test_font_substitution_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "fc_substitute", lambda fam: "Liberation Sans" if fam == "Noto Sans CJK SC" else None)
    res = R.check_rights(_write(tmp_path, {"music": []}), subtitle_font="Noto Sans CJK SC")
    lv = _levels(res)
    assert lv["Noto Sans CJK SC"] == "yellow" and lv["Liberation Sans"] == "green"
