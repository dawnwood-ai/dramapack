"""Programmatic entry points that return JSON-ready dicts.

Shared by the CLI (``--json``) and the MCP server, so humans, scripts and agents all get
the same result shape. Every result has ``"ok"`` and, where grading applies, a
``"status"`` of ``"green" | "yellow" | "red"``. Paths in results are absolute.
"""
import os
import shutil
import tempfile

from . import master as M
from .ff import ffmpeg_exe, have_ffmpeg, probe_duration, probe_spec
from .provenance import PROVENANCE

_ORDER = {"green": 0, "yellow": 1, "red": 2}


def worst(levels) -> str:
    levels = [x for x in levels if x in _ORDER]
    return max(levels, key=_ORDER.get) if levels else "green"


def _abs(p):
    return os.path.abspath(os.path.expanduser(p)) if p else p


def _require_ffmpeg():
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg not found: install ffmpeg (with libass + libx264) or set "
                           "DRAMAPACK_FFMPEG / DRAMAPACK_FFPROBE")


def inspect_file(path: str) -> dict:
    """Measured specs of a media file plus integrated loudness and true peak."""
    _require_ffmpeg()
    path = _abs(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    exe = ffmpeg_exe()
    spec = probe_spec(exe, path)
    loud = M.measure_loudness(exe, path) or {}

    def num(k):
        try:
            v = float(loud[k])
        except (KeyError, TypeError, ValueError):
            return None
        return v if v > -70 else None

    lufs = num("input_i")
    return {"ok": True, "path": path, **spec,
            "integrated_lufs": lufs, "true_peak_dbtp": num("input_tp"),
            "loudness_range_lu": num("input_lra"),
            "loudness_target_lufs": float(M.TARGET_LUFS),
            "loudness_gain_to_target_db": M.loudness_gain_db(lufs) if lufs is not None else None}


def master_episode(input: str, output: str, *, srt: str | None = None, burn: bool = True,
                   bed: str | None = None, music: str | None = None,
                   music_db: float = M.MUSIC_DB, head_trim: float = 0.0,
                   end_card: dict | None = None, card_secs: float = M.CARD_SECS,
                   cover_band: float = 0.0, subtitle_font: str = M.SUB_FONT,
                   normalize: bool = True) -> dict:
    """Master one episode; returns the output path and its measured specs."""
    _require_ffmpeg()
    input, output, srt, music = _abs(input), _abs(output), _abs(srt), _abs(music)
    if bed and bed not in M.BED_PRESETS:
        raise ValueError(f"unknown bed mood {bed!r}; choose from {', '.join(M.BED_MOODS)}")
    exe = ffmpeg_exe()
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dramapack-") as tmp:
        if bed:
            total = probe_duration(exe, input) - head_trim + (card_secs if end_card else 0.0)
            music = M.render_bed(exe, max(1.0, total), os.path.join(tmp, "bed.wav"), bed)
        staged = os.path.join(tmp, "out" + os.path.splitext(output)[1])
        M.master(input, srt, staged, burn=burn, music=music, music_db=music_db, exe=exe,
                 head_trim=head_trim, end_card=end_card, card_secs=card_secs,
                 normalize=normalize, cover_band=cover_band, subtitle_font=subtitle_font)
        shutil.move(staged, output)
    return {"ok": True, "output": output, "subtitles": "burned" if burn and srt else "none",
            "music_bed": bed, "music_file": music if music and not bed else None,
            "spec": probe_spec(exe, output), "generator": dict(PROVENANCE)}


def build_package(input_dir: str, output_dir: str, *, show: str | None = None,
                  rights: str | None = None, title: str | None = None,
                  studio: str | None = None, language: str | None = None,
                  bed: str | None = None, music: str | None = None,
                  masters_ready: bool = False, episodes=None, platform_pairs: bool = False,
                  clean: bool = True, covers: bool = True, timeline: bool = True,
                  keep_work: bool = False) -> dict:
    """Build a delivery pack; returns a summary plus the path to the full manifest."""
    _require_ffmpeg()
    from .package import build, load_show
    input_dir, output_dir = _abs(input_dir), _abs(output_dir)
    shw = load_show(input_dir, _abs(show), title=title, studio=studio, language=language,
                    music_bed=bed, music=_abs(music))
    man = build(input_dir, output_dir, show=shw, rights_path=_abs(rights),
                masters_ready=masters_ready, clean=clean, covers=covers, timeline=timeline,
                platform_pairs=platform_pairs, episodes=episodes, keep_work=keep_work)
    blocking = [g for g in man["gaps"] if "do not ship" in g or "failed" in g]
    status = worst([man["rights"]["status"], "red" if blocking else
                    ("yellow" if man["gaps"] else "green")])
    eps = [{"episode": e["episode"],
            "files": {k: os.path.join(output_dir, v["path"]) for k, v in e["files"].items()
                      if isinstance(v, dict) and v.get("path")}}
           for e in man["episodes"]]
    return {"ok": True, "status": status, "output_dir": output_dir,
            "manifest": os.path.join(output_dir, "manifest.json"),
            "rights_status": man["rights"]["status"], "rights_summary": man["rights"]["summary"],
            "gaps": man["gaps"], "notes": man["notes"], "episodes": eps,
            "platform": [p["files"]["episode"]["path"] for p in man["platform"]],
            "generator": man["generator"]}


def audit_files(files, *, cut: str | None = None, bounds=None, speech: bool = True,
                hook_plugin: str | None = None) -> dict:
    """Grade files against short-drama benchmarks."""
    _require_ffmpeg()
    from . import audit as A
    files = [_abs(f) for f in ([files] if isinstance(files, str) else files)]
    hook = A.load_hook_plugin(hook_plugin) if hook_plugin else None
    skipped = []
    if speech and not A.have_speech():
        speech = False
        skipped.append("speech metrics (pip install 'dramapack[speech]')")
    if cut:
        if len(files) != 1:
            raise ValueError("cut pairs with exactly one master file")
        rows = A.audit_pair(files[0], _abs(cut), do_speech=speech, bounds=bounds, hook_plugin=hook)
    else:
        rows = [A.audit(p, do_speech=speech, bounds=bounds, hook_plugin=hook) for p in files]
    status = worst(g for r in rows for g in r["grades"].values())
    return {"ok": True, "status": status, "rows": rows, "skipped": skipped,
            "thresholds": {k: {"green": v[0], "red": v[1]} for k, v in A.T.items()}}


def check_rights(rights: str | None = None, *, input_dir: str | None = None,
                 bed: str | None = None, music: str | None = None,
                 subtitle_font: str | None = M.SUB_FONT, end_card: bool = False,
                 allow_fonts=()) -> dict:
    """Grade declared music and burned-in fonts."""
    from .rights import check_rights as _check
    input_dir = _abs(input_dir)
    rights = _abs(rights)
    if not rights and input_dir and os.path.exists(os.path.join(input_dir, "rights.json")):
        rights = os.path.join(input_dir, "rights.json")
    res = _check(rights, input_dir=input_dir, bed_mood=bed, external_music=_abs(music),
                 subtitle_font=subtitle_font,
                 card_font_path=M.card_font_path() if end_card else None,
                 extra_allow_fonts=allow_fonts or ())
    return {"ok": True, "rights_path": rights, **res}
