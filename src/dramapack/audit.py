"""Post-render acceptance audit — grade a finished episode against short-drama market
benchmarks: green / yellow / red per metric.

It measures the things a producer or platform reviewer notices first. Thresholds come
from a measured benchmark sample (competing vertical dramas from platforms such as
DramaWave and ReelShort, other AI-produced series, and our own early cuts).

Deterministic metrics (ffmpeg only): duration, average shot length, long-shot share,
mean volume, seam level jumps (when splice points are given), frozen tail.
Optional: speech density via faster-whisper (``pip install dramapack[speech]``);
skipped automatically when not installed.
Optional and **off by default**: a hook-window check through a plugin you supply
(``--hook-plugin module:function``), e.g. a vision model that verifies the first frame
shows a person. No model, network access or API key is required by this package.

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

from .ff import ffmpeg_exe, ffprobe_exe

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
SCENE_TH = 0.15   # low threshold catches in-scene cuts; a high one only sees scene changes
LONG_SHOT = 4.0
MASTER_KEYS = {"dur", "first_speech", "tail_static", "hook"}
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


def cut_metrics(exe: str, path: str) -> dict:
    dur = float(subprocess.run(
        [ffprobe_exe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True,
        timeout=FF_TIMEOUT_SHORT).stdout.strip() or 0)
    # NB: metadata=print:file=- writes to STDOUT, not stderr.
    r = subprocess.run([exe, "-nostats", "-i", path, "-filter:v",
                        f"select='gt(scene,{SCENE_TH})',metadata=print:file=-",
                        "-an", "-f", "null", "-"], capture_output=True, text=True,
                       timeout=FF_TIMEOUT_LONG)
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stdout)
            if 0.2 < float(t) < dur - 0.2]
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
            "mean_volume": float(m.group(1)) if m else None}


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


def speech_metrics(path: str, model_name: str | None = None) -> dict:
    """Dialogue density via faster-whisper (optional extra). {} when not installed."""
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError:
        return {}
    model = WhisperModel(model_name or os.environ.get("DRAMAPACK_WHISPER_MODEL", "base"),
                         device="cpu", compute_type="int8")
    segs, info = model.transcribe(path, vad_filter=True, beam_size=1)
    segs = sorted(segs, key=lambda s: s.start)
    dur = info.duration or 1
    zh = info.language == "zh"
    words = sum(len(_CJK.findall(s.text)) if zh else len(s.text.split()) for s in segs)
    gaps, prev = [], 0.0
    for s in segs:
        gaps.append(s.start - prev)
        prev = max(prev, s.end)
    gaps.append(dur - prev)
    rate = words / (dur / 60)
    # VAD segments overlap slightly / carry padding, so the sum can exceed duration —
    # clamp to 1.0 rather than report a 1.1 that looks like a bug.
    return {"lang": info.language,
            "speech_share": round(min(1.0, sum(s.end - s.start for s in segs) / dur), 2),
            # Chinese is counted per character; scale by 3/5 onto the same ruler as WPM.
            "wpm": round(rate / (5 / 3) if zh else rate),
            "wpm_raw": round(rate), "max_gap": round(max(gaps), 1),
            "first_speech": round(segs[0].start, 1) if segs else None}


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
          hook_plugin=None, keys: set | None = None) -> dict:
    """Measure one file. ``keys`` restricts which metrics are graded (None = all)."""
    exe = ffmpeg_exe()
    m = cut_metrics(exe, path)
    m.update(tail_static(exe, path, m.get("dur") or 0.0))
    if bounds:
        m.update(seam_jump(exe, path, bounds))
    if do_speech:
        m.update(speech_metrics(path))
    if hook_plugin:
        m.update(hook_metrics(exe, path, hook_plugin))
    m["file"] = os.path.basename(path)
    grades = {k: grade(k, m.get(k)) for k in T}
    if m.get("hook"):
        grades["hook"] = m["hook"]
    if keys is not None:
        grades = {k: g for k, g in grades.items() if k in keys}
    m["grades"] = grades
    m["red"] = [k for k, g in grades.items() if g == RED]
    return m


def audit_pair(master_path: str, cut_path: str | None = None, **kw) -> list:
    """Audit a master, optionally with its raw cut: the cut is graded on baseline metrics,
    the master on master-only metrics (see module docstring)."""
    if not cut_path:
        return [audit(master_path, **kw)]
    hook = kw.pop("hook_plugin", None)
    bounds = kw.pop("bounds", None)
    cut = audit(cut_path, bounds=bounds, keys=(set(T) - MASTER_KEYS) | {"dur"}, **kw)
    mas = audit(master_path, hook_plugin=hook, keys=MASTER_KEYS, **kw)
    cut["file"], mas["file"] = f"cut:{cut['file']}", f"master:{mas['file']}"
    return [cut, mas]


ROW = ["dur", "asl", "cpm", "long_share", "speech_share", "wpm", "max_gap", "mean_volume",
       "seam_db", "first_speech", "tail_static", "hook"]
_SHORT = {GREEN: "G", YELLOW: "Y", RED: "R"}


def format_table(rows: list) -> str:
    hdr = ["file"] + ROW
    w = {c: max(len(c), *(len(str(r.get(c, "-"))) + 3 for r in rows)) for c in hdr}
    out = ["  ".join(c.ljust(w[c]) for c in hdr)]
    for r in rows:
        cells = []
        for c in hdr:
            v = r.get(c, "-")
            g = r["grades"].get(c)
            mark = f"[{_SHORT[g]}]" if g in _SHORT else ""
            cells.append(f"{v}{mark}".ljust(w[c]))
        out.append("  ".join(cells))
    out.append("\nthresholds (green/red): " + ", ".join(f"{k} {T[k][0]}/{T[k][1]}" for k in T))
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
