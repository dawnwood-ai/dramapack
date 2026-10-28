"""0.2 QC checks: black frames, subtitle/speech alignment, optional VLM checks.

No network: the VLM path runs against a stub OpenAI-compatible server on 127.0.0.1, and
alignment uses injected transcripts instead of faster-whisper."""
import http.server
import json
import subprocess
import threading

import pytest

from dramapack import align as AL
from dramapack import api, cli
from dramapack import audit as A
from dramapack import vlm as V
from dramapack.srt import _fmt

from conftest import EXE, needs_ffmpeg


# ---------------------------------------------------------------- black frames

def make_black_clip(path, parts):
    """``parts`` = [("src"|"black", secs), ...] concatenated, with a tone track."""
    cmd, labels = [EXE, "-y", "-v", "error"], []
    for kind, secs in parts:
        src = "testsrc=size=320x568:rate=24" if kind == "src" else "color=black:size=320x568:rate=24"
        cmd += ["-f", "lavfi", "-t", str(secs), "-i", src]
    total = sum(s for _, s in parts)
    cmd += ["-f", "lavfi", "-t", str(total), "-i", "sine=frequency=440:sample_rate=48000"]
    n = len(parts)
    labels = "".join(f"[{i}:v]" for i in range(n))
    cmd += ["-filter_complex", f"{labels}concat=n={n}:v=1:a=0[v]", "-map", "[v]",
            "-map", f"{n}:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def test_black_segments_classification():
    log = ("[blackdetect] black_start:0 black_end:0.5 black_duration:0.5\n"
           "[blackdetect] black_start:3 black_end:3.3 black_duration:0.3\n"
           "[blackdetect] black_start:6 black_end:7 black_duration:1\n"
           "[blackdetect] black_start:9.5 black_end:9.96 black_duration:0.46\n")
    segs = A.black_segments_from_log(log, 10.0)
    assert [s["where"] for s in segs] == ["head", "mid", "mid", "tail"]
    m = A.black_metrics(segs)
    assert [s["level"] for s in m["black_segments"]] == ["green", "yellow", "red", "green"]
    assert m["black_grade"] == "red" and m["black"] == pytest.approx(2.26)
    # A long fade at the edges is yellow, never red.
    m = A.black_metrics(A.black_segments_from_log("black_start:0 black_end:2.5", 10.0))
    assert m["black_grade"] == "yellow"
    assert A.black_metrics([])["black_grade"] == "green"


@needs_ffmpeg
def test_black_mid_episode_is_red(tmp_path):
    clip = make_black_clip(tmp_path / "b.mp4",
                           [("src", 2.0), ("black", 1.0), ("src", 2.0), ("black", 0.5)])
    r = A.audit(clip, do_speech=False)
    mids = [s for s in r["black_segments"] if s["where"] == "mid"]
    assert len(mids) == 1 and abs(mids[0]["start"] - 2.0) < 0.1 and abs(mids[0]["dur"] - 1.0) < 0.1
    assert mids[0]["level"] == "red"
    tails = [s for s in r["black_segments"] if s["where"] == "tail"]
    assert tails and tails[0]["level"] == "green"
    assert r["grades"]["black"] == "red" and "black" in r["red"]
    assert "black" in A.format_table([r])


@needs_ffmpeg
def test_no_black_is_green(tmp_path):
    clip = make_black_clip(tmp_path / "c.mp4", [("src", 3.0)])
    r = A.audit(clip, do_speech=False)
    assert r["black"] == 0 and r["grades"]["black"] == "green"


# ---------------------------------------------------------------- alignment

LINES = ["You're in the wrong room.", "Then show me the right one.",
         "Nobody leaves until we know.", "Open the door now."]
SPEECH = [(0.5, 2.0), (3.0, 4.6), (6.0, 7.8), (9.0, 10.2)]


def _transcript(lines=LINES, spans=SPEECH, lang="en"):
    segs = []
    for text, (a, b) in zip(lines, spans):
        ws = text.split()
        step = (b - a) / len(ws)
        segs.append({"start": a, "end": b, "text": text,
                     "words": [{"start": a + i * step, "end": a + (i + 1) * step, "word": w}
                               for i, w in enumerate(ws)]})
    return {"language": lang, "duration": 12.0, "segments": segs}


def _cues(shift=0.0, lines=LINES, spans=SPEECH):
    return [(a + shift, b + shift, t) for t, (a, b) in zip(lines, spans)]


def _graded(m):
    return {k: A.grade(k, m.get(k)) for k in ("sub_drift", "sub_offset_p90",
                                              "sub_orphan_share", "sub_uncovered_s")}


def test_alignment_good():
    m = AL.align(_cues(0.05), _transcript())
    assert m["sub_drift"] == pytest.approx(0.05) and m["sub_orphan_share"] == 0
    assert m["sub_uncovered_s"] == 0 and m["sub_text"] == 0
    assert set(_graded(m).values()) == {"green"}


def test_alignment_shifted():
    m = AL.align(_cues(0.9), _transcript())
    assert m["sub_drift_signed"] == pytest.approx(0.9)      # subtitles late
    g = _graded(m)
    assert g["sub_drift"] == "red" and g["sub_offset_p90"] in ("yellow", "red")
    # The text check undoes the drift before comparing, so a shift is not a typo.
    assert m["sub_text"] == 0
    m = AL.align(_cues(-0.5), _transcript())
    assert m["sub_drift_signed"] == pytest.approx(-0.5) and _graded(m)["sub_drift"] == "yellow"


def test_alignment_missing_and_orphan_cues():
    cues = _cues()[:2] + [(11.0, 11.8, "A line that was cut."), (5.0, 5.5, "[door slams]")]
    m = AL.align(cues, _transcript())
    # Two spoken lines have no cue; one cue has no speech; the SFX cue is exempt.
    assert m["sub_uncovered_s"] == pytest.approx(3.0, abs=0.1)
    assert [o["text"] for o in m["sub_orphans"]] == ["A line that was cut."]
    assert m["sub_orphan_share"] == pytest.approx(1 / 3, abs=0.01)
    g = _graded(m)
    assert g["sub_uncovered_s"] == "yellow" and g["sub_orphan_share"] == "red"


def test_alignment_text_typo_and_translation():
    typo = list(LINES)
    typo[2] = "Nobody believes the snow is gone."
    m = AL.align(_cues(lines=typo), _transcript())
    assert m["sub_text"] == 1 and m["sub_text_flags"][0]["cue"] == 3
    # A one-letter typo barely moves the line similarity; the word check catches it.
    typo = list(LINES)
    typo[1] = "Then show me the rihgt one."
    m = AL.align(_cues(lines=typo), _transcript())
    assert m["sub_text"] == 1 and m["sub_text_flags"][0]["words"] == [["rihgt", "right"]]
    assert m["sub_text_flags"][0]["similarity"] > AL.TEXT_SIM_FLAG
    # Subtitles in another language: the check steps aside instead of flagging every cue.
    es = ["Estas en la sala equivocada.", "Entonces ensename la correcta.",
          "Nadie se va hasta saberlo.", "Abre la puerta ahora."]
    m = AL.align(_cues(lines=es), _transcript())
    assert "sub_text" not in m and "translation" in m["sub_text_note"]
    m = AL.align(_cues(lines=es), _transcript(), srt_lang="es")
    assert "sub_text" not in m and "skipped" in m["sub_text_note"]


def test_alignment_cjk_normalisation():
    a = "\u4f60\u597d\uff0c\u4e16\u754c\uff01"      # "hello, world!" with full-width punctuation
    b = "\u4f60\u597d \u4e16\u754c"
    assert AL.normalize(a) == AL.normalize(b) and AL.similarity(a, b) == 1.0
    assert AL.guess_lang(a) == "zh"
    assert AL.is_annotation("[MUSIC]") and AL.is_annotation("\u266a") and not AL.is_annotation("Hi")


def test_alignment_segment_spanning_two_cues():
    # One whisper segment covers two cues: the second cue has no onset of its own and
    # must not be reported as 1.5 s late.
    tr = {"language": "en", "duration": 5, "segments": [
        {"start": 0.5, "end": 4.0, "text": "First half. Second half."}]}
    m = AL.align([(0.5, 2.0, "First half."), (2.0, 4.0, "Second half.")], tr)
    assert m["sub_drift"] == 0 and m["sub_offset_p90"] == 0


@needs_ffmpeg
def test_audit_alignment_with_injected_transcriber(tmp_path, capsys):
    clip = make_black_clip(tmp_path / "e.mp4", [("src", 12.0)])
    srt = tmp_path / "e.srt"
    srt.write_text("".join(f"{i}\n{_fmt(a)} --> {_fmt(b)}\n{t}\n\n"
                           for i, (a, b, t) in enumerate(_cues(1.0), 1)))
    res = api.audit_files([clip], speech=True, transcriber=lambda p: _transcript())
    row = res["rows"][0]
    assert row["srt"] == "e.srt" and row["sub_drift"] == pytest.approx(1.0)
    assert row["grades"]["sub_drift"] == "red"
    assert row["speech_share"] > 0 and row["first_speech"] == 0.5
    # No transcriber and no faster-whisper -> skipped with a reason, never a crash.
    if not A.have_speech():
        res = api.audit_files([clip], speech=True)
        assert any("alignment" in s for s in res["skipped"])


# ---------------------------------------------------------------- VLM

SECRET = "sk-test-SECRET-0123456789abcdef"
GOOD = {
    "visual": {"anatomy": "yes", "garbled_text": "no", "artifacts": "unsure",
               "identity_drift": "no",
               "evidence": [{"check": "anatomy", "frame": 2, "note": "six fingers, left hand"}]},
    "compliance": {"sexual": "none", "violence": "mild", "minors": "none", "self_harm": "none",
                   "evidence": [{"check": "violence", "frame": 1, "note": "a slap"}]},
    "hook": {"person_visible": "no", "text": "none", "note": "an empty corridor"},
}


class _Stub(http.server.BaseHTTPRequestHandler):
    mode = "good"
    calls: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = body["messages"][0]["content"]
        check = ("hook" if "FIRST frame" in system else
                 "compliance" if "platform policies" in system else "visual")
        images = [p for p in body["messages"][1]["content"] if p["type"] == "image_url"]
        type(self).calls.append({"path": self.path, "check": check, "images": len(images),
                                 "auth": self.headers.get("Authorization"),
                                 "data_uri": images[0]["image_url"]["url"][:23]})
        if self.mode == "unauthorized":
            # A careless server that echoes the credential back in its error body.
            self._send(401, {"error": f"bad key {self.headers.get('Authorization')}"})
            return
        if self.mode == "malformed" and check == "visual":
            content = "Sure! Here is my review: the frames look fine"
        elif self.mode == "malformed" and check == "compliance":
            content = json.dumps({"sexual": "maybe", "violence": "none"})
        else:
            content = "```json\n" + json.dumps(GOOD[check]) + "\n```"
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def stub(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    _Stub.calls, _Stub.mode = [], "good"
    monkeypatch.setenv(V.ENV_BASE, f"http://127.0.0.1:{srv.server_address[1]}/v1/")
    monkeypatch.setenv(V.ENV_KEY, SECRET)
    monkeypatch.setenv(V.ENV_MODEL, "stub-vision")
    monkeypatch.setenv("DRAMAPACK_VLM_RETRIES", "0")
    yield _Stub
    srv.shutdown()


def test_sample_times():
    ts = V.sample_times(60.0, [5.0, 5.2, 12.0, 30.0, 45.0], max_frames=12)
    assert ts[0] == 0.0 and ts == sorted(ts) and len(ts) <= 12
    assert 5.3 in ts and 12.3 in ts                      # just after cuts
    assert all(b - a >= V.MIN_GAP_S - 1e-9 for a, b in zip(ts, ts[1:]))
    assert V.sample_times(60.0, list(range(1, 59)), max_frames=4)[0] == 0.0
    assert len(V.sample_times(60.0, list(range(1, 59)), max_frames=4)) == 4


def test_parse_and_validate():
    assert V.parse_json('noise {"a": 1} trailing') == {"a": 1}
    with pytest.raises(V.ReplyError):
        V.parse_json("no json here")
    with pytest.raises(V.ReplyError):
        V.validate("hook", {"person_visible": "probably", "text": "none"})
    ok = V.validate("hook", {"person_visible": "YES", "text": "legible"})
    assert ok["answers"] == {"person_visible": "yes", "text": "legible"}
    # unsure never raises the level
    assert V.grade_check("visual", {"anatomy": "unsure", "garbled_text": "no",
                                    "artifacts": "unsure", "identity_drift": "unsure"})[0] == "green"


def test_config_requires_all_env_vars():
    cfg, msg = V.config_from_env({V.ENV_BASE: "http://x/v1", V.ENV_KEY: SECRET})
    assert cfg is None and V.ENV_MODEL in msg and SECRET not in msg
    cfg, msg = V.config_from_env({V.ENV_BASE: "http://x/v1/", V.ENV_KEY: SECRET, V.ENV_MODEL: "m"})
    assert cfg["base_url"] == "http://x/v1" and SECRET not in msg


@needs_ffmpeg
def test_vlm_checks_against_stub(tmp_path, stub, capsys):
    clip = make_black_clip(tmp_path / "v.mp4", [("src", 3.0)])
    rc = cli.main(["audit", clip, "--no-speech", "--vlm", "--vlm-max-frames", "4", "--json"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert {c["check"] for c in stub.calls} == {"visual", "compliance", "hook"}
    assert all(c["path"] == "/v1/chat/completions" for c in stub.calls)
    assert all(c["auth"] == f"Bearer {SECRET}" for c in stub.calls)
    assert all(c["data_uri"] == "data:image/jpeg;base64," for c in stub.calls)
    vis = next(c for c in stub.calls if c["check"] == "visual")
    hook = next(c for c in stub.calls if c["check"] == "hook")
    assert 1 <= vis["images"] <= 4 and hook["images"] == 1
    row = out["rows"][0]
    assert row["grades"]["vlm_visual"] == "red" and row["grades"]["vlm_compliance"] == "yellow"
    assert row["grades"]["vlm_hook"] == "yellow" and row["vlm_hook_note"] == "an empty corridor"
    f = next(f for f in row["vlm_findings"] if f["item"] == "anatomy")
    assert f["note"] == "six fingers, left hand" and f["level"] == "red"
    assert out["vlm"]["requests"] == 3 and out["vlm"]["model"] == "stub-vision"
    assert "3 requests" in cap.err                      # estimate printed before calling
    assert rc == 1                                      # red finding -> exit 1
    assert SECRET not in cap.out and SECRET not in cap.err


@needs_ffmpeg
def test_vlm_malformed_reply_is_skipped_not_red(tmp_path, stub, capsys):
    stub.mode = "malformed"
    clip = make_black_clip(tmp_path / "v.mp4", [("src", 3.0)])
    res = api.audit_files([clip], speech=False, vlm=True, vlm_max_frames=3)
    row = res["rows"][0]
    assert "vlm_visual" not in row["grades"] and "vlm_compliance" not in row["grades"]
    assert row["grades"]["vlm_hook"] == "yellow"        # the valid check still counts
    errs = " ".join(row["vlm_errors"])
    assert "visual" in errs and "compliance" in errs
    # Malformed replies are re-asked once each.
    assert sum(c["check"] == "visual" for c in stub.calls) == 2


@needs_ffmpeg
def test_vlm_key_never_leaks(tmp_path, stub, capsys):
    stub.mode = "unauthorized"
    clip = make_black_clip(tmp_path / "v.mp4", [("src", 3.0)])
    rc = cli.main(["audit", clip, "--no-speech", "--vlm", "--vlm-max-frames", "2", "--json"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["ok"] and "vlm_visual" not in out["rows"][0]["grades"]   # never blocks
    assert any("HTTP 401" in e for e in out["rows"][0]["vlm_errors"])
    assert SECRET not in cap.out and SECRET not in cap.err
    # 401 is not retried.
    assert sum(c["check"] == "visual" for c in stub.calls) == 1
    rc = cli.main(["audit", clip, "--no-speech", "--vlm", "--vlm-max-frames", "2"])
    cap = capsys.readouterr()
    assert SECRET not in cap.out and SECRET not in cap.err


@needs_ffmpeg
def test_vlm_disabled_without_env(tmp_path, monkeypatch, capsys):
    for k in (V.ENV_BASE, V.ENV_KEY, V.ENV_MODEL):
        monkeypatch.delenv(k, raising=False)
    clip = make_black_clip(tmp_path / "v.mp4", [("src", 3.0)])
    rc = cli.main(["audit", clip, "--no-speech", "--vlm", "--json"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    msg = " ".join(out["skipped"])
    assert "VLM checks skipped" in msg and V.ENV_BASE in msg and V.ENV_MODEL in msg
    assert "VLM checks skipped" in cap.err
    assert "vlm" not in out and not any(k.startswith("vlm") for k in out["rows"][0]["grades"])
    # And without --vlm, configured env vars are ignored: nothing is sent.
    monkeypatch.setenv(V.ENV_BASE, "http://127.0.0.1:9/v1")
    monkeypatch.setenv(V.ENV_KEY, SECRET)
    monkeypatch.setenv(V.ENV_MODEL, "m")
    out = api.audit_files([clip], speech=False)
    assert "vlm" not in out and not any("vlm" in s for s in out["skipped"])


def test_mcp_audit_exposes_qc_params():
    import asyncio

    from dramapack.mcp_server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "audit")
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    props = set(schema["properties"])
    assert {"vlm", "speech", "align", "srt", "vlm_max_frames"} <= props
    assert "hook_plugin" not in props                    # arbitrary imports stay CLI-only
    assert "black" in tool.description and "DRAMAPACK_VLM_BASE_URL" in tool.description
    assert "Lip-sync is not checked" in tool.description


def test_source_has_no_cjk_literals(src_dir):
    import pathlib
    import re
    cjk = re.compile("[぀-ヿ㐀-鿿가-힯！-～]")
    for f in pathlib.Path(src_dir).glob("*.py"):
        assert not cjk.search(f.read_text(encoding="utf-8")), f"{f.name}: use \\u escapes"


@needs_ffmpeg
def test_no_speech_disables_alignment(tmp_path):
    clip = make_black_clip(tmp_path / "n.mp4", [("src", 3.0)])
    (tmp_path / "n.srt").write_text("1\n00:00:00,500 --> 00:00:02,000\nHi there.\n")
    called = []
    res = api.audit_files([clip], speech=False, transcriber=lambda p: called.append(p))
    assert not called and "sub_drift" not in res["rows"][0]
