"""Post-render acceptance audit — grade a finished episode against short-drama market
benchmarks: green / yellow / red per metric.

It measures the things a producer or platform reviewer notices first. Thresholds come
from a measured benchmark sample (competing vertical dramas from platforms such as
DramaWave and ReelShort, other AI-produced series, and our own early cuts).

Deterministic metrics (ffmpeg only): duration, average shot length, long-shot share,
mean volume, seam level jumps (when splice points are given), frozen tail, black frames,
dark edge bands.
Optional: speech density and subtitle/speech alignment via faster-whisper
(``pip install dramapack[speech]``); skipped automatically when not installed.
Optional and **off by default**: vision-model checks with your own key or a local model
(``--vlm``, see ``vlm.py``), and a hook-window check through a plugin you supply
(``--hook-plugin module:function``). Without ``--vlm`` and its environment variables
the audit makes no network calls and needs no API key.

**Measure cuts and masters for different things.** The pacing/speech/seam baselines were
calibrated on raw cuts. A master's music bed hides seams and tightens the speech VAD
(the same episode measured speech_share 0.86 on the cut and 0.41 on the master — a false
red). So when both are available, grade the cut on the baseline metrics and the master
only on what exists only in the master: duration (incl. end card), first line (incl. head
trim), frozen tail, hook window.
"""
import importlib
import os
import re
import subprocess
import sys
import tempfile

from .ff import ffmpeg_exe, ffprobe_exe, video_size

# Every subprocess gets a timeout: a truncated mp4 can make ffmpeg read forever and hang
# an unattended acceptance job that otherwise just looks "still running".
FF_TIMEOUT_SHORT = 60     # single-window volumedetect / ffprobe
FF_TIMEOUT_LONG = 900     # whole-file scene scan / whole-file volume

#: Thresholds: (green bound, red bound). Direction is inferred: green < red means lower is
#: better; green > red means higher is better.
T = {
    # Duration. TikTok Creator Rewards requires videos **longer than one minute** — a 59 s
    # episode earns nothing even at a million views, and the algorithm weighs total watch
    # time, not only completion. A sample of 131 same-niche competitors had a median of
    # 85 s (serialized episode posts: 339 s); 55–75 s is on the short side, so there is no
    # reason to cut shorter. Green at ≥ 65 s leaves margin — platforms judge on their own
    # decoded duration. Higher is better.
    "dur": (65.0, 60.0),
    # Pacing. Live-action platform series: ASL 1.08–1.54 s; other AI productions 2.6–3.1;
    # our early AI cuts 3.18. Lower is better.
    "asl": (2.0, 3.0),
    "long_share": (0.30, 0.50),   # share of runtime in shots > 4 s; live-action series 0.23
    # Dialogue density — the biggest gap measured. Competitors' speech_share 0.68–0.98,
    # median 0.90; WPM 67–134. Higher is better (Chinese counted in characters, scaled 3/5).
    "speech_share": (0.80, 0.65),
    "wpm": (90, 70),
    "max_gap": (5.0, 8.0),         # longest stretch without dialogue (s), lower is better
    # Loudness. Competitors' mean_volume −16.0 to −21.5 dB; early masters −24.7 to −27.4.
    "mean_volume": (-20.0, -23.0),  # higher is better
    # Level jump at splice points. Independently rendered clips concatenated directly turn
    # every splice into a room-tone/ambience jump — the ear catches it before any metric
    # (one splice measured 40.8 dB). A continuous bed pulls it down (one episode: mean
    # 11.8 → 8.2 dB). Lower is better.
    "seam_db": (6.0, 15.0),
    # First line of dialogue. The hook line should land immediately — swipe decisions
    # happen in the first 3 seconds. Lower is better.
    "first_speech": (1.5, 3.0),
    # Frozen seconds at the end (end card + any freeze). Retention curves showed a 7.5 s
    # card (12% of a 61 s episode) dropping end retention from r75 = 58% to r100 = 16%;
    # episodes without a card kept 30–43%. Viewers swipe at a static card, logging an
    # incomplete view at 88% for everyone. Green ≤ 5 s fits a 4 s card plus fade; red
    # > 6.5 s catches long cards. Lower is better.
    "tail_static": (5.0, 6.5),
}
# Subtitle <-> speech alignment (needs a transcript; see align.py). All lower is better.
T.update({
    # Median start offset of cues against the speech they caption (s). Viewers notice a
    # line that arrives ~0.3 s late; a whole SRT shifted by a head trim is usually >= 0.5 s.
    "sub_drift": (0.3, 0.8),
    # 90th-percentile per-cue start offset (s): a few badly timed lines inside a good file.
    "sub_offset_p90": (0.5, 1.0),
    # Share of cues with no speech under them (sound-effect cues in brackets are exempt).
    "sub_orphan_share": (0.05, 0.20),
    # Seconds of transcribed speech that no cue covers (missing lines).
    "sub_uncovered_s": (1.5, 4.0),
})
ALIGN_KEYS = {"sub_drift", "sub_offset_p90", "sub_orphan_share", "sub_uncovered_s", "sub_text"}

# Black frames (ffmpeg blackdetect). A black run shorter than BLACK_MIN_S is not reported
# at all (one dropped frame at 24 fps is 0.04 s). Pixel threshold 0.10 counts a very dark
# night shot as black only when ~98% of the picture is below it, so low-key grading does
# not trip it. Head/tail black up to BLACK_EDGE_OK_S is a normal fade in/out (green);
# longer at the edges is yellow (dead air before the hook, or a long fade-out the viewer
# swipes on). Black mid-episode is a render gap or a failed clip in the concat: red at
# BLACK_MID_RED_S and above, yellow below (could be a deliberate dip to black).
BLACK_MIN_S = 0.1
BLACK_PIX_TH = 0.10
BLACK_EDGE_OK_S = 1.0
BLACK_MID_RED_S = 0.5
BLACK_EDGE_TOL_S = 0.15   # blackdetect's last end is the last frame pts, not the duration

# Dark edge bands ("black bars", TikTok Drama Center rejection code 4). Drama Center does
# not flag full-frame black: it flags a dark *band along one side* of the frame. Measured
# on real rejections (2026-10-31): a 20 px band (at 1080 wide) on any one side with mean
# luma < 12 (full range, 0-255) continuously for > 3.5 s was flagged. Drama Center's own
# help says 5 s, but an episode dark for 3.8 s on one edge was rejected too, so red starts
# at 3.5 s. A hard 2 px black column (AI-video sources rendered 1078 wide and padded to
# 1080) also triggers it while the 20 px band around it still averages bright, so each
# side is also measured as a 2 px line; either one dark counts. Sampled at 5 fps from the
# same decode as shot detection. Dark night scenes can trip it legitimately: Drama Center
# rejects them anyway, which is why ``package --target tiktok-dc`` lifts every edge.
EDGE_BAND_PX = 20
EDGE_LINE_PX = 2
EDGE_DARK = 12.0
EDGE_FPS = 5
EDGE_SIDES = ("top", "bottom", "left", "right")
T["edge_dark"] = (2.0, 3.5)   # longest dark run on any one side (s), lower is better

SCENE_TH = 0.15   # low threshold catches in-scene cuts; a high one only sees scene changes
LONG_SHOT = 4.0
MASTER_KEYS = {"dur", "first_speech", "tail_static", "hook", "black", "edge_dark",
               "vlm_visual", "vlm_compliance", "vlm_hook"} | ALIGN_KEYS
_CJK = re.compile(r"[\u3400-\u9fff]")

GREEN, YELLOW, RED = "green", "yellow", "red"


def grade(key: str, val) -> str:
    if val is None:
        return "-"
    green, red = T[key]
    if green < red:   # lower is better
        return GREEN if val <= green else (RED if val > red else YELLOW)
    return GREEN if val >= green else (RED if val < red else YELLOW)


def _rms(exe: str, path: str, a: float, b: float):
    log = subprocess.run([exe, "-nostats", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", path,
                          "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=FF_TIMEOUT_SHORT).stderr
    m = re.search(r"mean_volume: (-?[\d.]+)", log)
    return float(m.group(1)) if m else None


def seam_jump(exe: str, path: str, bounds: list) -> dict:
    """Level difference across each splice point (0.3 s either side) — measures "you can
    hear the seam". ``bounds`` = cumulative seconds of each splice. Without bounds there is
    nothing to measure: guessing splice points from the finished file mistakes normal
    emotional dynamics for seams."""
    jumps = []
    for t in bounds:
        lo = _rms(exe, path, max(0.0, t - 0.35), max(0.05, t - 0.05))
        hi = _rms(exe, path, t + 0.05, t + 0.35)
        if lo is not None and hi is not None:
            jumps.append(abs(lo - hi))
    if not jumps:
        return {}
    return {"seam_db": round(sum(jumps) / len(jumps), 1),
            "seam_max": round(max(jumps), 1), "seams": len(jumps)}


def _edge_crops(w: int, h: int) -> list:
    """``[(side, kind, crop)]``: a 20 px band and a 2 px line per side, scaled to the frame
    (the platform states sizes at 1080 wide)."""
    out = []
    for kind, px in (("band", EDGE_BAND_PX), ("line", EDGE_LINE_PX)):
        b = max(1, round(px * w / 1080))
        out += [("top", kind, f"crop={w}:{b}:0:0"), ("bottom", kind, f"crop={w}:{b}:0:{h - b}"),
                ("left", kind, f"crop={b}:{h}:0:0"), ("right", kind, f"crop={b}:{h}:{w - b}:0")]
    return out


def _read_yavg(path: str) -> list:
    """``metadata=print`` file -> ``[(pts_time, YAVG)]``."""
    out, t = [], None
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return out
    for ln in lines:
        m = re.search(r"pts_time:([\d.]+)", ln)
        if m:
            t = float(m.group(1))
            continue
        m = re.match(r"lavfi\.signalstats\.YAVG=([\d.]+)", ln.strip())
        if m and t is not None:
            out.append((t, float(m.group(1))))
    return out


def edge_runs(series: dict, fps: float = EDGE_FPS, dark: float = EDGE_DARK) -> dict:
    """``{side: [(t, mean_luma), ...]}`` -> ``{side: {"secs", "at"}}``: the longest run of
    consecutive dark samples per side (pure function). Each sample stands for 1/fps s."""
    out = {}
    for side, vals in series.items():
        best, best_at, cur, cur_at = 0, 0.0, 0, 0.0
        for t, v in vals:
            if v < dark:
                if cur == 0:
                    cur_at = t
                cur += 1
                if cur > best:
                    best, best_at = cur, cur_at
            else:
                cur = 0
        out[side] = {"secs": round(best / fps, 1), "at": round(best_at, 1)}
    return out


def edge_metrics(runs: dict) -> dict:
    """Worst side -> ``edge_dark`` (graded), plus every side's run."""
    if not runs:
        return {}
    side = max(runs, key=lambda k: runs[k]["secs"])
    return {"edge_dark": runs[side]["secs"], "edge_dark_side": side,
            "edge_dark_at": runs[side]["at"], "edge_sides": runs}


def cut_metrics(exe: str, path: str) -> dict:
    dur = float(subprocess.run(
        [ffprobe_exe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True,
        timeout=FF_TIMEOUT_SHORT).stdout.strip() or 0)
    w, h = video_size(exe, path)
    crops = _edge_crops(w, h)
    # NB: metadata=print:file=- writes to STDOUT, not stderr. blackdetect rides the same
    # decode (it logs to stderr and passes frames through), so black frames cost no
    # extra pass over the file. The edge bands branch off the same decode too: each band
    # prints its mean luma to its own file (relative names, cwd = a temp dir, so no path
    # escaping inside the filter graph). format=gray gives full-range luma (black = 0),
    # the scale the platform threshold was measured on.
    graph = ["[0:v]split=2[m][e]",
             f"[m]blackdetect=d={BLACK_MIN_S}:pix_th={BLACK_PIX_TH},"
             f"select='gt(scene,{SCENE_TH})',metadata=print:file=-[o0]",
             f"[e]fps={EDGE_FPS},format=gray,split={len(crops)}"
             + "".join(f"[e{i}]" for i in range(len(crops)))]
    outs = ["-map", "[o0]", "-an", "-f", "null", "-"]
    for i, (side, kind, crop) in enumerate(crops):
        graph.append(f"[e{i}]{crop},signalstats,"
                     f"metadata=print:key=lavfi.signalstats.YAVG:file={kind}_{side}.txt[o{i + 1}]")
        outs += ["-map", f"[o{i + 1}]", "-f", "null", "-"]
    with tempfile.TemporaryDirectory(prefix="dramapack-edge-") as td:
        r = subprocess.run([exe, "-nostats", "-i", os.path.abspath(path),
                            "-filter_complex", ";".join(graph)] + outs,
                           capture_output=True, text=True, timeout=FF_TIMEOUT_LONG, cwd=td)
        series = {}
        for side in EDGE_SIDES:
            band = _read_yavg(os.path.join(td, f"band_{side}.txt"))
            line = dict(_read_yavg(os.path.join(td, f"line_{side}.txt")))
            # Dark when the band OR its outermost line is dark (see EDGE_LINE_PX).
            series[side] = [(t, min(v, line.get(t, v))) for t, v in band]
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stdout)
            if 0.2 < float(t) < dur - 0.2]
    black = black_segments_from_log(r.stderr, dur)
    bounds = [0.0] + cuts + [dur]
    shots = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]
    vol = subprocess.run([exe, "-nostats", "-i", path, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True,
                         timeout=FF_TIMEOUT_LONG).stderr
    m = re.search(r"mean_volume: (-?[\d.]+)", vol)
    return {"dur": round(dur, 1), "cuts": len(cuts),
            "asl": round(dur / max(1, len(shots)), 2),
            "cpm": round(len(cuts) / (dur / 60), 1) if dur else 0,
            "long_share": round(sum(s for s in shots if s > LONG_SHOT) / dur, 2) if dur else 0,
            "mean_volume": float(m.group(1)) if m else None,
            **black_metrics(black), **edge_metrics(edge_runs(series)), "_cut_times": cuts}


def black_segments_from_log(log: str, dur: float) -> list:
    """blackdetect log -> ``[{"start", "end", "dur", "where"}]`` (pure function).
    ``where`` is ``head`` / ``tail`` / ``mid``; a run covering the whole file is ``head``."""
    out = []
    for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", log):
        a, b = float(a), float(b)
        if a <= BLACK_EDGE_TOL_S:
            where = "head"
        elif dur and b >= dur - BLACK_EDGE_TOL_S:
            where = "tail"
        else:
            where = "mid"
        out.append({"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2),
                    "where": where})
    return out


def black_level(seg: dict) -> str:
    if seg["where"] == "mid":
        return RED if seg["dur"] >= BLACK_MID_RED_S else YELLOW
    return GREEN if seg["dur"] <= BLACK_EDGE_OK_S else YELLOW


def black_metrics(segs: list) -> dict:
    """Total black seconds plus each run with its own level; ``black_grade`` = worst run."""
    levels = [black_level(s) for s in segs]
    for s, lv in zip(segs, levels):
        s["level"] = lv
    order = {GREEN: 0, YELLOW: 1, RED: 2}
    return {"black": round(sum(s["dur"] for s in segs), 2), "black_segments": segs,
            "black_grade": max(levels, key=order.get) if levels else GREEN}


def tail_static_from_log(log: str, tail: float) -> float:
    """freezedetect log → frozen seconds at the very end (pure function).

    Only a freeze that lasts **until the end** counts; a mid-file freeze that recovers is
    long_share's business. Times are relative to the scan start; ``tail`` is the scan
    window length."""
    starts = [float(t) for t in re.findall(r"freeze_start: ([\d.]+)", log)]
    ends = [float(t) for t in re.findall(r"freeze_end: ([\d.]+)", log)]
    if not starts:
        return 0.0
    # The last freeze has no freeze_end (frozen to EOF), or its end touches the end.
    if len(ends) < len(starts) or (ends and tail - ends[-1] < 0.5):
        return round(tail - starts[-1], 1)
    return 0.0


def tail_static(exe: str, path: str, dur: float) -> dict:
    """Seconds of frozen picture at the end (end card + any freeze). Scans the last ~15 s.
    If the measurement fails the metric is omitted, never failed: a broken checker must not
    block delivery."""
    try:
        seek = max(0.0, dur - 15.0)
        r = subprocess.run([exe, "-nostats", "-ss", f"{seek:.2f}", "-i", path,
                            "-vf", "freezedetect=n=0.003:d=1.5", "-an", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=FF_TIMEOUT_SHORT)
        return {"tail_static": tail_static_from_log(r.stderr, dur - seek)}
    except Exception as e:  # noqa: BLE001
        print(f"tail_static skipped: {str(e)[:120]}", file=sys.stderr)
        return {}


def have_speech() -> bool:
    try:
        import faster_whisper  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


def transcribe(path: str, model_name: str | None = None) -> dict | None:
    """faster-whisper transcript (optional extra) as plain data, or None when not
    installed. Shape: see ``align.py``. Word timestamps feed the subtitle text check."""
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError:
        return None
    import numpy as np  # noqa: PLC0415  (a faster-whisper dependency)
    # Decode with our ffmpeg instead of letting faster-whisper open the file through PyAV:
    # faster-whisper 1.2.1 + av 19 fails on every file (open() lost metadata_errors), and
    # this way speech sees exactly the audio ffmpeg sees everywhere else.
    pcm = subprocess.run([ffmpeg_exe(), "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "f32le", "-"], capture_output=True,
                         timeout=FF_TIMEOUT_LONG, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    model = WhisperModel(model_name or os.environ.get("DRAMAPACK_WHISPER_MODEL", "base"),
                         device="cpu", compute_type="int8")
    segs, info = model.transcribe(audio, vad_filter=True, beam_size=1, word_timestamps=True)
    return {"language": info.language, "duration": info.duration,
            "segments": [{"start": float(s.start), "end": float(s.end), "text": s.text,
                          "words": [{"start": float(w.start), "end": float(w.end),
                                     "word": w.word}
                                    for w in (s.words or [])]} for s in segs]}


def speech_metrics(path: str, model_name: str | None = None, transcript: dict | None = None) -> dict:
    """Dialogue density from a transcript ({} when faster-whisper is not installed)."""
    tr = transcript if transcript is not None else transcribe(path, model_name)
    if not tr:
        return {}
    segs = sorted(tr.get("segments") or [], key=lambda s: s["start"])
    dur = tr.get("duration") or 1
    lang = tr.get("language")
    zh = lang == "zh"
    words = sum(len(_CJK.findall(s["text"])) if zh else len(s["text"].split()) for s in segs)
    gaps, prev = [], 0.0
    for s in segs:
        gaps.append(s["start"] - prev)
        prev = max(prev, s["end"])
    gaps.append(dur - prev)
    rate = words / (dur / 60)
    # VAD segments overlap slightly / carry padding, so the sum can exceed duration -
    # clamp to 1.0 rather than report a 1.1 that looks like a bug.
    return {"lang": lang,
            "speech_share": round(min(1.0, sum(s["end"] - s["start"] for s in segs) / dur), 2),
            # Chinese is counted per character; scale by 3/5 onto the same ruler as WPM.
            "wpm": round(rate / (5 / 3) if zh else rate),
            "wpm_raw": round(rate), "max_gap": round(max(gaps), 1),
            "first_speech": round(segs[0]["start"], 1) if segs else None}


def load_hook_plugin(spec: str):
    """``"package.module:function"`` → callable ``f(path, ffmpeg_exe) -> dict`` returning
    ``{"fails": [str], "warns": [str], "note": str}``. Bring your own model and credentials
    (read them from your environment inside the plugin)."""
    mod, _, fn = spec.partition(":")
    if not mod or not fn:
        raise ValueError("hook plugin must be 'module:function'")
    return getattr(importlib.import_module(mod), fn)


def hook_metrics(exe: str, path: str, plugin) -> dict:
    """Hook window check (first ~3.5 s) through a user plugin. Failures of the plugin
    itself (no network, no key, model error) degrade to "skipped", never to red."""
    try:
        r = plugin(path, exe) or {}
    except Exception as e:  # noqa: BLE001
        print(f"hook check skipped: {str(e)[:120]}", file=sys.stderr)
        return {}
    fails, warns = list(r.get("fails") or []), list(r.get("warns") or [])
    return {"hook": RED if fails else (YELLOW if warns else GREEN),
            "hook_fails": fails, "hook_warns": warns,
            "hook_note": str(r.get("note") or "")[:200]}


def audit(path: str, *, do_speech: bool = True, bounds: list | None = None,
          hook_plugin=None, keys: set | None = None, srt: str | None = None,
          srt_lang: str | None = None, transcriber=None, vlm_cfg: dict | None = None,
          vlm_max_frames: int = 12, log=None) -> dict:
    """Measure one file. ``keys`` restricts which metrics are graded (None = all).

    ``srt`` turns on subtitle/speech alignment (needs a transcript). ``transcriber`` is
    ``f(path) -> transcript | None`` (default: faster-whisper via ``transcribe``);
    inject one to test or to reuse your own ASR. ``vlm_cfg`` (from
    ``vlm.config_from_env``) turns on the vision-model checks."""
    exe = ffmpeg_exe()
    m = cut_metrics(exe, path)
    cut_times = m.pop("_cut_times", [])
    m.update(tail_static(exe, path, m.get("dur") or 0.0))
    if bounds:
        m.update(seam_jump(exe, path, bounds))
    tr = None
    if do_speech or srt:
        try:
            tr = (transcriber or transcribe)(path)
        except Exception as e:  # noqa: BLE001
            print(f"transcription skipped: {str(e)[:120]}", file=sys.stderr)
    if do_speech and tr:
        m.update(speech_metrics(path, transcript=tr))
    if srt and tr:
        from .align import align  # noqa: PLC0415
        from .srt import parse_srt  # noqa: PLC0415
        m["srt"] = os.path.basename(srt)
        m.update(align(parse_srt(srt), tr, srt_lang=srt_lang))
    if hook_plugin:
        m.update(hook_metrics(exe, path, hook_plugin))
    if vlm_cfg:
        from . import vlm  # noqa: PLC0415
        m.update(vlm.run_checks(vlm_cfg, exe, path, m.get("dur") or 0.0, cut_times,
                                max_frames=vlm_max_frames, log=log))
    m["file"] = os.path.basename(path)
    grades = {k: grade(k, m.get(k)) for k in T}
    if m.get("hook"):
        grades["hook"] = m["hook"]
    grades["black"] = m.pop("black_grade", GREEN)
    if "sub_text" in m:
        grades["sub_text"] = YELLOW if m["sub_text"] else GREEN
    for k in ("vlm_visual", "vlm_compliance", "vlm_hook"):
        if m.get(k):
            grades[k] = m[k]
    if keys is not None:
        grades = {k: g for k, g in grades.items() if k in keys}
    m["grades"] = grades
    m["red"] = [k for k, g in grades.items() if g == RED]
    return m


def audit_pair(master_path: str, cut_path: str | None = None, **kw) -> list:
    """Audit a master, optionally with its raw cut: the cut is graded on baseline metrics,
    the master on master-only metrics (see module docstring). Subtitle alignment, the
    hook and the VLM checks run on the master only: that is the picture and the SRT
    timing that get delivered."""
    if not cut_path:
        return [audit(master_path, **kw)]
    master_only = {k: kw.pop(k) for k in ("hook_plugin", "srt", "srt_lang", "vlm_cfg",
                                          "vlm_max_frames") if k in kw}
    bounds = kw.pop("bounds", None)
    cut = audit(cut_path, bounds=bounds,
                keys=(set(T) - MASTER_KEYS) | {"dur", "black", "edge_dark"}, **kw)
    mas = audit(master_path, keys=MASTER_KEYS, **master_only, **kw)
    cut["file"], mas["file"] = f"cut:{cut['file']}", f"master:{mas['file']}"
    return [cut, mas]


ROW = ["dur", "asl", "cpm", "long_share", "speech_share", "wpm", "max_gap", "mean_volume",
       "seam_db", "first_speech", "tail_static", "black", "edge_dark", "hook"]
#: Second table: subtitle alignment + vision checks (only printed when any were measured).
ROW2 = ["sub_drift", "sub_offset_p90", "sub_orphan_share", "sub_uncovered_s", "sub_text",
        "vlm_visual", "vlm_compliance", "vlm_hook"]
_SHORT = {GREEN: "G", YELLOW: "Y", RED: "R"}


def _table(rows: list, cols: list) -> list:
    hdr = ["file"] + cols
    w = {c: max(len(c), *(len(str(r.get(c, "-"))) + 3 for r in rows)) for c in hdr}
    out = ["  ".join(c.ljust(w[c]) for c in hdr)]
    for r in rows:
        cells = []
        for c in hdr:
            v = r.get(c, "-")
            g = r["grades"].get(c)
            if c.startswith("vlm_") and v in _SHORT:
                v = ""               # the level is the value
            mark = f"[{_SHORT[g]}]" if g in _SHORT else ""
            cells.append(f"{v}{mark}".ljust(w[c]))
        out.append("  ".join(cells))
    return out


def format_table(rows: list) -> str:
    out = _table(rows, ROW)
    if any(k in r for r in rows for k in ROW2):
        out += [""] + _table(rows, ROW2)
    out.append("\nthresholds (green/red): " + ", ".join(f"{k} {T[k][0]}/{T[k][1]}" for k in T))
    for r in rows:
        for b in r.get("black_segments") or []:
            if b["level"] != GREEN:
                out.append(f"{r['file']} black {b['where']} {b['start']}-{b['end']}s "
                           f"({b['dur']} s) [{_SHORT[b['level']]}]")
        g = r["grades"].get("edge_dark")
        if g in (YELLOW, RED):
            out.append(f"{r['file']} dark edge {r['edge_dark_side']} from {r['edge_dark_at']}s "
                       f"({r['edge_dark']} s) [{_SHORT[g]}]")
        for o in r.get("sub_orphans") or []:
            out.append(f"{r['file']} cue {o['cue']} at {o['start']}s has no speech: {o['text']}")
        for u in r.get("sub_uncovered") or []:
            out.append(f"{r['file']} speech {u['start']}-{u['end']}s has no cue: {u['heard']}")
        for f in r.get("sub_text_flags") or []:
            typos = ", ".join(f"{x}->{y}?" for x, y in f.get("words") or [])
            out.append(f"{r['file']} cue {f['cue']} text ~{f['similarity']}"
                       f"{' ' + typos if typos else ''}: srt {f['srt']!r} / heard {f['heard']!r}")
        for f in r.get("vlm_findings") or []:
            at = f" at {f['t']}s" if "t" in f else ""
            out.append(f"{r['file']} vlm {f['check']}.{f['item']}={f['answer']}{at} "
                       f"[{_SHORT[f['level']]}] {f.get('note', '')}".rstrip())
        for e in r.get("vlm_errors") or []:
            out.append(f"{r['file']} vlm error: {e}")
    for r in rows:
        if r["red"]:
            out.append(f"\n{r['file']} red: {', '.join(r['red'])}")
        for f in r.get("hook_fails") or []:
            out.append(f"  x {f}")
        for wn in r.get("hook_warns") or []:
            out.append(f"  ~ {wn}")
        if r.get("hook_note"):
            out.append(f"  hook window: {r['hook_note']}")
    return "\n".join(out)
