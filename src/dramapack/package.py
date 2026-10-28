"""B2B delivery pack — turn a folder of episodes into the stack of files a short-drama
platform asks for.

**Why this exists.** Platforms (DramaWave, ReelShort, DramaBox, GoodShort, TikTok Drama
Center, …) phrase their submission requirements differently, but the intersection is
remarkably stable: numbered episode files + same-name subtitles + vertical covers + **a
clean master without subtitles** + chain of title + edit-project evidence. Assembling it by
hand is dozens of steps per series; this makes it one command with one consistent shape.

Input folder (see README for the full schema)::

    input/
      01.mp4 02.mp4 …          episodes (default: un-subtitled cuts; see masters_ready)
      01.srt …                 optional subtitles, same number
      01.jpg | 01.png …        optional per-episode cover; cover.jpg = series fallback
      01.timeline.json …       optional edit timeline (simple JSON schema)
      01.ui.png …              optional real screenshots of the editing session
      01.cut.mp4 …             masters_ready mode only: raw cut for the clean master
      show.json                title / studio / language / mastering options
      rights.json              music + font declarations (check-rights)

Output pack::

    <out>/
      episodes/01.mp4 …      subtitled master (burned subtitles, -14 LUFS)
      episodes/01.srt …      same-name subtitles (**same name** is a hard requirement —
                             platforms pair files by name)
      clean/01.mp4 …         clean master: the same mastering chain with burn=False
      covers/01.jpg …        3:4 covers (≥ 350×500), cropped from the top
      timeline/01.png …      **rendered** edit timeline + 01.edl.csv cut list
      timeline/ui/01.png …   **real** editor screenshots, when supplied
      platform/…             optional two-episodes-per-file cut (--platform-pairs)
      docs/CHAIN-OF-TITLE.md left blank to be signed by a person
      docs/AI-DISCLOSURE.md  AI production disclosure
      manifest.json          measured specs of every file + rights check + generator
      README.md              one page for the recipient

**Why the clean master is re-mastered rather than the raw cut handed over**: the raw cut has
no subtitles, but it also has no loudness normalisation and no bed — it would ship
5–11 dB quieter than the competition with every seam exposed. Clean master = master minus
subtitles, not master minus mastering.

**Two kinds of edit evidence, deliberately kept apart.** ``timeline/NN.png`` is
**rendered** from timeline data and says so on the image; its strength is the
machine-readable ``.edl.csv``. ``timeline/ui/NN.png`` are **actual screenshots** of the
editing session — when a platform asks for "an NLE project screenshot showing tracks and
cut points" (the requirement exists to filter out single-shot AI output), give those.
**Never present one as the other.** The label on the rendered image is a contract;
removing it turns a rendering into a fake screenshot.
"""
import csv
import datetime
import json
import os
import re
import shutil
import subprocess

from . import master as M
from .ff import TIMEOUT_SHORT, ffmpeg_exe, log_stderr, probe_duration, probe_spec
from .provenance import PROVENANCE, footer_line
from .rights import check_rights
from .srt import merge_srt, shift_srt

#: Minimum cover size most platforms list (3:4 portrait). No upper bound.
MIN_COVER = (350, 500)
COVER_RATIO = 3 / 4             # w:h
TIMELINE_W = 1600
TRACK_COLORS = {"video": (86, 132, 214), "audio": (92, 176, 128),
                "overlay": (212, 164, 84)}
EPISODE_RE = re.compile(r"^(\d{1,4})\.(mp4|mov|m4v|mkv)$", re.I)
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")

SHOW_DEFAULTS = {
    "title": "", "studio": "", "language": "en", "tagline": "", "aspect": "9:16",
    "production_year": None, "rights_holder": "", "subtitle_font": M.SUB_FONT,
    "music_bed": None, "music": None, "music_db": M.MUSIC_DB, "head_trim": 0.0,
    "end_card": None, "episodes": {}, "ai_disclosure": {}, "existing_exploitation": [],
}


# --- inputs ------------------------------------------------------------------------

def load_show(input_dir: str, show_path: str | None = None, **overrides) -> dict:
    path = show_path or os.path.join(input_dir, "show.json")
    show = dict(SHOW_DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            show.update(json.load(f))
    show.update({k: v for k, v in overrides.items() if v is not None})
    show["episodes"] = {int(k): v for k, v in (show.get("episodes") or {}).items()}
    if not show.get("title"):
        show["title"] = os.path.basename(os.path.abspath(input_dir))
    if show.get("music_bed") is True:
        show["music_bed"] = "tension"
    if show.get("music_bed") and show["music_bed"] not in M.BED_PRESETS:
        raise ValueError(f"unknown music_bed mood {show['music_bed']!r}; "
                         f"choose from {', '.join(M.BED_MOODS)}")
    if show.get("music") and not os.path.isabs(show["music"]):
        show["music"] = os.path.join(input_dir, show["music"])
    return show


def _first(input_dir: str, stems, exts) -> str | None:
    for s in stems:
        for e in exts:
            p = os.path.join(input_dir, s + e)
            if os.path.exists(p):
                return p
    return None


def discover(input_dir: str) -> dict:
    """``{num: {"video", "srt", "cover", "timeline", "ui", "cut"}}`` from an input folder."""
    eps: dict = {}
    for fn in sorted(os.listdir(input_dir)):
        m = EPISODE_RE.match(fn)
        if not m:
            continue
        num, stem = int(m.group(1)), fn.rsplit(".", 1)[0]
        stems = [stem] if stem == f"{num:02d}" else [stem, f"{num:02d}"]
        eps[num] = {
            "video": os.path.join(input_dir, fn),
            "srt": _first(input_dir, stems, (".srt",)),
            "cover": _first(input_dir, stems + [s + ".cover" for s in stems], IMAGE_EXT),
            "timeline": _first(input_dir, [s + ".timeline" for s in stems], (".json",)),
            "ui": _first(input_dir, [s + ".ui" for s in stems], (".png", ".jpg", ".jpeg")),
            "cut": _first(input_dir, [s + ".cut" for s in stems], (".mp4", ".mov", ".m4v", ".mkv")),
        }
    return eps


# --- covers ------------------------------------------------------------------------

def make_cover(src: str, dest: str, ratio: float = COVER_RATIO) -> dict:
    """Any cover (typically 9:16) → 3:4 portrait cover.

    Cropped from a **top** anchor, not the centre: faces and titles in vertical-drama key
    art sit in the upper half and a centre crop cuts off chins. 8% headroom keeps the crop
    off the top of heads. Upscaled to the platform minimum when smaller."""
    from PIL import Image  # noqa: PLC0415

    im = Image.open(src).convert("RGB")
    w, h = im.size
    target_h = int(round(w / ratio))
    if target_h <= h:
        top = int((h - target_h) * 0.08)
        im = im.crop((0, top, w, top + target_h))
    else:                                   # wider than 3:4: crop width instead
        target_w = int(round(h * ratio))
        left = (w - target_w) // 2
        im = im.crop((left, 0, left + target_w, h))
    if im.size[0] < MIN_COVER[0] or im.size[1] < MIN_COVER[1]:
        im = im.resize(MIN_COVER, Image.Resampling.LANCZOS)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    im.save(dest, "JPEG", quality=92, optimize=True)
    return {"width": im.size[0], "height": im.size[1], "bytes": os.path.getsize(dest)}


def grab_frame(exe: str, video: str, dest: str) -> str | None:
    """Fallback cover source: a frame ~20% in (capped at 3 s), avoiding fade-in black."""
    t = min(3.0, max(0.0, probe_duration(exe, video) * 0.2))
    r = subprocess.run([exe, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video,
                        "-frames:v", "1", "-q:v", "2", dest], capture_output=True,
                       timeout=TIMEOUT_SHORT)
    return dest if r.returncode == 0 and os.path.exists(dest) else None


# --- timeline ----------------------------------------------------------------------

def render_timeline(project: dict, png: str, edl: str, *, title: str = "") -> dict:
    """Draw an edit timeline as a track diagram + write a per-clip cut list (CSV).

    ``project`` (``NN.timeline.json``)::

        {"name": "...", "fps": 30, "ratio": "9:16",
         "tracks": {"video":   [{"id": "c1", "source": "shot_01.mp4", "in": 0.0, "out": 3.2}],
                    "audio":   [{"id": "a1", "source": "vo_01.wav",  "in": 0.0, "out": 3.2}],
                    "overlay": [{"id": "t1", "start": 0.5, "end": 2.0, "text": "..."}]}}

    video/audio clips are laid end to end by ``out - in``; overlays use absolute
    ``start``/``end``. (``media_id`` + a top-level ``media: [{id, src_ref}]`` list is also
    accepted in place of ``source``.) The image states that it is rendered from data."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    tracks = project.get("tracks") or {}
    media = {m.get("id"): m for m in (project.get("media") or [])}
    order = [t for t in ("video", "audio", "overlay") if tracks.get(t)]

    vtotal = sum(max(0.0, float(c.get("out", 0)) - float(c.get("in", 0)))
                 for c in tracks.get("video") or [])
    ototal = max([float(c.get("end", 0)) for c in tracks.get("overlay") or []] or [0.0])
    total = max(vtotal, ototal) or 1.0

    pad, row_h, gap, head, ruler_h = 60, 54, 34, 104, 44
    height = head + ruler_h + len(order) * (row_h + gap) + 46
    im = Image.new("RGB", (TIMELINE_W, height), (24, 25, 29))
    d = ImageDraw.Draw(im)
    font, small, tiny = M._card_font(21), M._card_font(14), M._card_font(12)

    d.text((pad, 26), (title or project.get("name", ""))[:80], font=font, fill=(232, 226, 216))
    d.text((pad, 58), f"{project.get('ratio', '9:16')} · {project.get('fps', 30)}fps · "
                      f"{total:.1f}s · {sum(len(v) for v in tracks.values())} clips",
           font=small, fill=(150, 150, 158))

    span = TIMELINE_W - pad * 2
    # Ruler: without ticks you can't tell "which second this cut is at".
    step = 5 if total <= 90 else 10
    d.line([pad, head + ruler_h - 8, pad + span, head + ruler_h - 8], fill=(70, 72, 80))
    t = 0.0
    while t <= total:
        x = pad + span * (t / total)
        d.line([x, head + ruler_h - 13, x, head + ruler_h - 3], fill=(110, 112, 120))
        d.text((x + 3, head + 1), f"{int(t)}s", font=tiny, fill=(120, 122, 130))
        t += step

    rows = []
    for i, tname in enumerate(order):
        y = head + ruler_h + i * (row_h + gap)
        clips = tracks[tname]
        d.text((pad, y - 20), f"{tname.upper()}  ({len(clips)})", font=small, fill=(170, 172, 180))
        d.rectangle([pad, y, pad + span, y + row_h], fill=(32, 34, 39))
        color = TRACK_COLORS.get(tname, (128, 128, 128))
        cursor = 0.0
        for n, c in enumerate(clips, 1):
            if tname == "overlay":
                start, end = float(c.get("start", 0)), float(c.get("end", 0))
            else:
                dur = max(0.0, float(c.get("out", 0)) - float(c.get("in", 0)))
                start, end = cursor, cursor + dur
                cursor = end
            x0 = pad + span * (start / total)
            x1 = pad + span * (end / total)
            # Inset each clip 1.5 px so adjacent clips show a visible dark gap: the cut
            # point is a visible shape, not a white line drawn over a colour block.
            d.rectangle([x0 + 1.5, y + 3, max(x0 + 3, x1 - 1.5), y + row_h - 3], fill=color)
            d.line([x1, y - 4, x1, y + row_h + 4], fill=(236, 238, 242), width=1)
            if x1 - x0 > 26 and tname != "overlay":
                d.text((x0 + 6, y + 6), str(n), font=tiny, fill=(18, 20, 24))
            source = c.get("source") or (media.get(c.get("media_id")) or {}).get("src_ref", "")
            rows.append({"track": tname, "clip_id": c.get("id", ""),
                         "start_s": round(start, 3), "end_s": round(end, 3),
                         "duration_s": round(end - start, 3),
                         "source": source, "in_s": c.get("in", ""), "out_s": c.get("out", ""),
                         "text": (c.get("text") or "")[:120]})

    # This label is a contract: a pack may contain both this rendering and real UI
    # screenshots (timeline/ui/). Removing it turns a rendering into a fake screenshot.
    d.text((pad, height - 30), "Rendered from edit timeline data — not a UI screenshot. "
                               "Cut list: same-numbered .edl.csv",
           font=small, fill=(118, 120, 128))
    os.makedirs(os.path.dirname(png) or ".", exist_ok=True)
    im.save(png, "PNG", optimize=True)

    with open(edl, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["track", "clip_id", "start_s", "end_s", "duration_s",
                                          "source", "in_s", "out_s", "text"])
        w.writeheader()
        w.writerows(rows)
    return {"clips": len(rows), "tracks": order, "total_s": round(total, 2)}


# --- clean master for pre-mastered input --------------------------------------------

def match_master_params(exe: str, cut: str, master_dur: float,
                        head_trim: float, card_secs: float) -> tuple:
    """Infer which (head_trim, card_secs) a delivered master was made with, from its
    **measured duration**.

    Why not read the current config: options like head trim and end card get added to a
    show after early episodes were already mastered. Re-mastering a clean version with
    today's config yields a file seconds longer than the subtitled one — two versions that
    don't match, and a platform comparing them concludes they're different edits. So pick
    whichever of the four combinations matches the measured length."""
    cut_dur = probe_duration(exe, cut)
    best, err = (0.0, 0.0), 1e9
    for ht in {0.0, head_trim}:
        for cs in {0.0, card_secs}:
            d = abs((cut_dur - ht + cs) - master_dur)
            if d < err:
                best, err = (ht, cs), d
    # Way off means the master has another origin (hand-made / swapped footage): fall back
    # to no trim / no card. Better a clean master with the same programme than a new edit
    # built from guessed parameters.
    return best if err <= 0.75 else (0.0, 0.0)


# --- build -------------------------------------------------------------------------

def _ep_cfg(show: dict, num: int) -> dict:
    cfg = {"head_trim": show.get("head_trim"), "end_card": show.get("end_card"), "title": ""}
    cfg.update(show["episodes"].get(num) or {})
    return cfg


def _end_card(cfg: dict, show: dict, num: int):
    ec = cfg.get("end_card")
    if not ec:
        return None, 0.0
    sub = {"num": num, "next": num + 1, "title": show["title"]}
    card = {"title": ec.get("title") or show["title"],
            "lines": [str(x).format(**sub) for x in (ec.get("lines") or [])],
            "site": ec.get("site") or ""}
    return card, float(ec.get("secs") or M.CARD_SECS)


def build(input_dir: str, outdir: str, *, show: dict | None = None,
          rights_path: str | None = None, masters_ready: bool = False,
          clean: bool = True, covers: bool = True, timeline: bool = True,
          platform_pairs: bool = False, episodes=None, keep_work: bool = False,
          log=log_stderr) -> dict:
    """Build a delivery pack. Returns the manifest (also written to ``manifest.json``).

    Default mode: ``NN.mp4`` are un-subtitled cuts; both the subtitled master and the clean
    master are produced here from the same chain and the same parameters, so they are
    guaranteed to be the same edit.

    ``masters_ready=True``: ``NN.mp4`` are finished subtitled masters and are copied as-is;
    a clean master is produced only when ``NN.cut.mp4`` is present, with head trim / end
    card inferred from the master's measured duration (:func:`match_master_params`)."""
    exe = ffmpeg_exe()
    show = show or load_show(input_dir)
    found = discover(input_dir)
    nums = sorted(n for n in found if not episodes or n in set(episodes))
    if not nums:
        raise RuntimeError(f"no episodes found in {input_dir} (expected 01.mp4, 02.mp4, …)")
    rights_path = rights_path or (os.path.join(input_dir, "rights.json")
                                  if os.path.exists(os.path.join(input_dir, "rights.json")) else None)

    os.makedirs(outdir, exist_ok=True)
    work = os.path.join(outdir, "_work")
    os.makedirs(work, exist_ok=True)
    mood = show.get("music_bed")
    ext_music = show.get("music")
    man = {"generator": dict(PROVENANCE),
           "title": show["title"], "studio": show.get("studio") or "",
           "tagline": show.get("tagline") or "", "language": show.get("language") or "en",
           "aspect": show.get("aspect") or "9:16",
           "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "mode": "masters_ready" if masters_ready else "mastered",
           "mastering": None if masters_ready else {
               "loudness_lufs": float(M.TARGET_LUFS), "peak_ceiling_dbfs": M.TRUE_PEAK_DB,
               "normalisation": "constant gain + peak limiter (no dynamic loudnorm)",
               "subtitle_font": show.get("subtitle_font"),
               "subtitle_safe_area": {"bottom_margin_frac": M.SUB_MARGINV_FRAC,
                                      "side_margin_frac": M.SUB_MARGINLR_FRAC},
               "music_bed": mood, "music_file": os.path.basename(ext_music) if ext_music else None},
           "episodes": [], "platform": [], "gaps": [], "notes": []}
    used_card = False
    used_subs = False

    for num in nums:
        src = found[num]
        cfg = _ep_cfg(show, num)
        tag = f"{num:02d}"
        ep: dict = {"episode": num, "title": cfg.get("title") or "", "files": {}}
        log(f"[{tag}] {os.path.basename(src['video'])}")
        wd = os.path.join(work, tag)
        os.makedirs(wd, exist_ok=True)
        ep_mp4 = os.path.join(outdir, "episodes", f"{tag}.mp4")
        ep_srt = os.path.join(outdir, "episodes", f"{tag}.srt")
        clean_mp4 = os.path.join(outdir, "clean", f"{tag}.mp4")
        os.makedirs(os.path.dirname(ep_mp4), exist_ok=True)

        head_trim = float(cfg.get("head_trim") or 0.0)
        card, card_secs = _end_card(cfg, show, num)
        cut_src = src["video"]

        if masters_ready:
            shutil.copy2(src["video"], ep_mp4)
            if src["srt"]:
                shutil.copy2(src["srt"], ep_srt)
            cut_src = src["cut"]
        else:
            bed = None
            total = probe_duration(exe, src["video"]) - head_trim + (card_secs if card else 0.0)
            if mood:
                bed = M.render_bed(exe, max(1.0, total), os.path.join(wd, "bed.wav"), mood)
            kw = dict(music=bed or ext_music, music_db=float(show.get("music_db") or M.MUSIC_DB),
                      exe=exe, head_trim=head_trim, subtitle_font=show.get("subtitle_font") or M.SUB_FONT,
                      log=log)
            if card:
                kw.update(end_card=card, card_secs=card_secs)
                used_card = True
            # Stage in a scratch dir: master() writes intermediates next to its output.
            sb, sc = os.path.join(wd, "burn"), os.path.join(wd, "clean")
            os.makedirs(sb, exist_ok=True)
            os.makedirs(sc, exist_ok=True)
            try:
                staged_clean = None
                if clean or not src["srt"]:
                    staged_clean = M.master(src["video"], None, os.path.join(sc, "out.mp4"),
                                            burn=False, **kw)
                if src["srt"]:
                    staged = M.master(src["video"], src["srt"], os.path.join(sb, "out.mp4"),
                                      burn=True, **kw)
                    shutil.move(staged, ep_mp4)
                    used_subs = True
                else:
                    shutil.copy2(staged_clean, ep_mp4)
                if clean and staged_clean:
                    os.makedirs(os.path.dirname(clean_mp4), exist_ok=True)
                    shutil.move(staged_clean, clean_mp4)
            except Exception as e:  # noqa: BLE001
                man["gaps"].append(f"ep{tag}: mastering failed: {str(e)[:300]}")
            if src["srt"]:
                # Delivered SRT must match the delivered master: shift it by the head trim.
                if head_trim:
                    shift_srt(src["srt"], ep_srt, -head_trim)
                else:
                    shutil.copy2(src["srt"], ep_srt)

        if os.path.exists(ep_mp4):
            ep["files"]["episode"] = {"path": f"episodes/{tag}.mp4",
                                      "subtitles": "burned" if src["srt"] or masters_ready else "none",
                                      **probe_spec(exe, ep_mp4)}
        else:
            man["gaps"].append(f"ep{tag}: episode master missing")
        if src["srt"] and os.path.exists(ep_srt):
            ep["files"]["srt"] = {"path": f"episodes/{tag}.srt", "bytes": os.path.getsize(ep_srt),
                                  "cues": open(ep_srt, encoding="utf-8", errors="replace").read().count("-->")}
        else:
            man["gaps"].append(f"ep{tag}: no subtitles ({tag}.srt missing)")

        # Clean master.
        if clean and masters_ready:
            if cut_src:
                mdur = (ep["files"].get("episode") or {}).get("duration_s")
                ht, cs = match_master_params(exe, cut_src, mdur or 0.0, head_trim,
                                             card_secs if card else 0.0)
                kw = dict(exe=exe, head_trim=ht, log=log)
                if card and cs:
                    kw.update(end_card=card, card_secs=cs)
                    used_card = True
                if mood:
                    total = probe_duration(exe, cut_src) - ht + cs
                    kw["music"] = M.render_bed(exe, max(1.0, total), os.path.join(wd, "bed.wav"), mood)
                elif ext_music:
                    kw["music"] = ext_music
                try:
                    staged = M.master(cut_src, None, os.path.join(wd, "clean.mp4"), burn=False, **kw)
                    os.makedirs(os.path.dirname(clean_mp4), exist_ok=True)
                    shutil.move(staged, clean_mp4)
                except Exception as e:  # noqa: BLE001
                    man["gaps"].append(f"ep{tag}: clean master failed: {str(e)[:300]}")
            else:
                man["gaps"].append(f"ep{tag}: no clean master (supply {tag}.cut.mp4)")
        if clean and os.path.exists(clean_mp4):
            spec = probe_spec(exe, clean_mp4)
            ep["files"]["clean_master"] = {"path": f"clean/{tag}.mp4", "subtitles": "none", **spec}
            # Clean and subtitled must be the same edit: > 1 s apart means wrong parameters.
            mdur = (ep["files"].get("episode") or {}).get("duration_s")
            if mdur and abs(spec.get("duration_s", 0) - mdur) > 1.0:
                man["gaps"].append(f"ep{tag}: clean master {spec.get('duration_s')}s vs episode "
                                   f"{mdur}s — different edit, do not ship")

        if covers:
            raw, origin = src["cover"], "supplied"
            if not raw:
                raw = _first(input_dir, ["cover"], IMAGE_EXT)
                origin = "series cover"
            if not raw:
                raw = grab_frame(exe, cut_src or src["video"], os.path.join(wd, "frame.jpg"))
                origin = "video frame"
                if raw:
                    man["notes"].append(f"ep{tag}: cover generated from a video frame — "
                                        f"supply {tag}.jpg for real key art")
            if raw:
                spec = make_cover(raw, os.path.join(outdir, "covers", f"{tag}.jpg"))
                ep["files"]["cover"] = {"path": f"covers/{tag}.jpg", "ratio": "3:4",
                                        "source": origin, **spec}
            else:
                man["gaps"].append(f"ep{tag}: cover missing")

        if timeline:
            if src["timeline"]:
                with open(src["timeline"], encoding="utf-8") as f:
                    proj = json.load(f)
                label = f"EP{num}" + (f" · {ep['title']}" if ep["title"] else "")
                info = render_timeline(proj, os.path.join(outdir, "timeline", f"{tag}.png"),
                                       os.path.join(outdir, "timeline", f"{tag}.edl.csv"),
                                       title=label)
                ep["files"]["timeline"] = {"path": f"timeline/{tag}.png", "kind": "rendered",
                                           "edl_path": f"timeline/{tag}.edl.csv", **info}
            if src["ui"]:
                dst = os.path.join(outdir, "timeline", "ui", f"{tag}{os.path.splitext(src['ui'])[1]}")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src["ui"], dst)
                ep["files"]["timeline_ui"] = {"path": os.path.relpath(dst, outdir),
                                              "kind": "screenshot"}
        man["episodes"].append(ep)

    if timeline and not any("timeline" in e["files"] or "timeline_ui" in e["files"]
                            for e in man["episodes"]):
        man["gaps"].append("no edit-project evidence (NN.timeline.json / NN.ui.png) — "
                           "some platforms require it")

    if platform_pairs:
        _build_pairs(exe, outdir, man, work, log)

    man["rights"] = check_rights(
        rights_path, input_dir=input_dir, bed_mood=mood, external_music=ext_music,
        subtitle_font=(show.get("subtitle_font") or M.SUB_FONT) if used_subs else None,
        card_font_path=M.card_font_path() if used_card else None)
    if man["rights"]["status"] == "red":
        man["gaps"].append("rights check is RED — see manifest.json \"rights\"")

    _write_docs(outdir, man, show)
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return man


def _build_pairs(exe: str, outdir: str, man: dict, work: str, log) -> None:
    """Platform variant: two episodes per file (~2 min). Platforms commonly specify
    1–3 minutes per episode while social cuts run ~1 minute. Built from **the delivered
    files themselves** — every frame a platform receives must be identical to the
    per-episode version, or "the same series" stops being true."""
    eps = [e for e in man["episodes"] if "episode" in e["files"]]
    for i in range(0, len(eps) - 1, 2):
        a, b = eps[i], eps[i + 1]
        n = i // 2 + 1
        tag = f"{n:02d}"
        log(f"[platform {tag}] EP{a['episode']} + EP{b['episode']}")
        pe: dict = {"pair": n, "source_episodes": [a["episode"], b["episode"]], "files": {}}
        p = lambda rel: os.path.join(outdir, rel)  # noqa: E731
        dst = p(f"platform/episodes/{tag}.mp4")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        M.concat_mp4(exe, [p(a["files"]["episode"]["path"]), p(b["files"]["episode"]["path"])], dst)
        pe["files"]["episode"] = {"path": f"platform/episodes/{tag}.mp4", **probe_spec(exe, dst)}
        if "srt" in a["files"] and "srt" in b["files"]:
            off = float(a["files"]["episode"].get("duration_s") or 0)
            n_cues = merge_srt(p(a["files"]["srt"]["path"]), p(b["files"]["srt"]["path"]), off,
                               p(f"platform/episodes/{tag}.srt"))
            pe["files"]["srt"] = {"path": f"platform/episodes/{tag}.srt", "cues": n_cues,
                                  "offset_s": round(off, 2)}
        if "clean_master" in a["files"] and "clean_master" in b["files"]:
            cdst = p(f"platform/clean/{tag}.mp4")
            os.makedirs(os.path.dirname(cdst), exist_ok=True)
            M.concat_mp4(exe, [p(a["files"]["clean_master"]["path"]),
                               p(b["files"]["clean_master"]["path"])], cdst)
            cspec = probe_spec(exe, cdst)
            pe["files"]["clean_master"] = {"path": f"platform/clean/{tag}.mp4",
                                           "subtitles": "none", **cspec}
            if abs(cspec.get("duration_s", 0) - pe["files"]["episode"].get("duration_s", 0)) > 1.0:
                man["gaps"].append(f"platform {tag}: clean vs subtitled length mismatch — do not ship")
        man["platform"].append(pe)
    if len(eps) % 2:
        man["notes"].append(f"platform cut: EP{eps[-1]['episode']} has no partner and is "
                            "delivered only as a single episode")


# --- docs --------------------------------------------------------------------------

def _music_rows(man: dict) -> str:
    rows = [f for f in (man.get("rights") or {}).get("findings", []) if f["kind"] == "music"]
    if not rows:
        return "| (none declared) | | |\n"
    return "".join(f"| {f['item']} | {f.get('source') or '-'} | {f['level']}: {f['message']} |\n"
                   for f in rows)


def _write_docs(outdir: str, man: dict, show: dict) -> None:
    docs = os.path.join(outdir, "docs")
    os.makedirs(docs, exist_ok=True)
    title = man["title"]
    eps = len(man["episodes"])
    studio = man.get("studio") or "[STUDIO NAME]"
    holder = show.get("rights_holder") or "[FULL LEGAL NAME OR ENTITY]"
    year = show.get("production_year") or "[YEAR]"
    lang = man.get("language") or "en"
    expl = show.get("existing_exploitation") or []
    expl_rows = "".join(f"| {r.get('platform', '')} | {r.get('scope', '')} | {r.get('since', '')} |\n"
                        for r in expl) + "| [add any prior licensee] | | |\n"
    footer = f"\n---\n\n*{footer_line()}*\n"

    # Chain of title is left blank to be signed. It is a legal representation made by a
    # person; a script filling it in would be making warranties on someone's behalf.
    with open(os.path.join(docs, "CHAIN-OF-TITLE.md"), "w", encoding="utf-8") as f:
        f.write(f"""# Chain of Title — {title}

> TEMPLATE — fill the bracketed fields and sign before sending. Do not submit unsigned.
> Describe the rights holder exactly as it legally exists on the date you sign (an
> individual, an individual trading under a studio name, or a registered company). Do not
> describe the studio as a company or LLC before that entity exists — that is a false
> statement of legal fact.

## 1. Work

- Title: {title}
- Format: vertical short drama, {eps} episodes delivered in this package
- Original language: {lang}
- Production year: {year}

## 2. Ownership

The rights holder of the Work is **{holder}**, producing as **{studio}** ("Rights Holder").

The Rights Holder represents that:

1. The screenplay is an original work authored by, or exclusively assigned to, the Rights
   Holder, and is not adapted from any third-party literary or dramatic property, except as
   listed here: [none / list]. [Before signing: confirm no third party — including any
   company that employs or has employed contributors — holds a work-for-hire claim over any
   part of the Work.]
2. All visual and audio elements were produced by or for the Rights Holder. Music embedded
   in the delivered files is limited to the cues in §3.
3. No performer likeness rights are implicated except as listed here: [none / list].
   Synthetic characters are not derived from, or intended to resemble, any identifiable
   living person.
4. The Work has not been assigned, exclusively licensed, or encumbered in any territory as
   of the date below, except as listed in §4.

## 3. Music and fonts

Music cues (from the rights check in `manifest.json`; overall status: **{man['rights']['status']}**):

| Cue | Source | Check |
|---|---|---|
{_music_rows(man)}
All fonts rendered into the picture are free for commercial use or licensed — see
`manifest.json` → `rights.findings`.

## 4. Existing exploitation

| Platform | Scope | Since |
|---|---|---|
{expl_rows}
## 5. Warranty

The Rights Holder warrants that the Work does not infringe any copyright, trademark, right
of publicity, or other right of any third party, and will indemnify the licensee against
third-party claims arising from breach of this warranty.

Signed: ____________________   Name: {holder}

Date: __________
{footer}""")

    ai = show.get("ai_disclosure") or {}
    mus = [f for f in man["rights"]["findings"] if f["kind"] == "music"]
    srcs = sorted({f.get("source") for f in mus if f.get("source")})
    music_line = ai.get("music") or (
        "No music declared." if not srcs else
        "Sources: " + ", ".join(s.replace("_", " ") for s in srcs) +
        (". The continuous music bed is procedurally generated (no library or licensed music)."
         if man.get("mastering") and man["mastering"].get("music_bed") else "."))
    human = ai.get("human_authored") or [
        "**Story, script, and dialogue**: written and revised by the production team.",
        "**Shot design and edit**: shot lists, staging, performance direction and the cut "
        "are authored per beat; edit evidence is included under `timeline/` when supplied.",
        "**Quality control**: episodes are measured against market benchmarks (pacing, "
        "dialogue density, loudness, seams) before release.",
    ]
    with open(os.path.join(docs, "AI-DISCLOSURE.md"), "w", encoding="utf-8") as f:
        f.write(f"""# AI Production Disclosure — {title}

> Generated from show.json — review before sending.

We disclose this up front rather than on request. Only some platforms have published an AI
policy; silence is not permission, and a licensee discovering undisclosed synthetic
production after signing is a far worse outcome than a platform declining for it.

## What is AI-generated

- **Imagery and motion**: {ai.get('imagery') or 'generated with AI video models; no camera footage, stock footage, or live performers unless stated here.'}
- **Voice**: {ai.get('voice') or 'synthetic voice performance, directed per line.'}
- **Music**: {music_line}

## What is human-authored

{chr(10).join('- ' + h for h in human)}

## Platform labelling

Self-distributed uploads should carry each platform's native synthetic-media label
(e.g. YouTube "altered or synthetic content", TikTok / Instagram AI-generated labels). We
will apply the licensee's labelling requirements on request.
{footer}""")

    gaps = man.get("gaps") or []
    mastering = man.get("mastering")
    loud = (f"- Loudness: every episode is normalised to {mastering['loudness_lufs']:g} LUFS "
            f"integrated with a constant gain and a {mastering['peak_ceiling_dbfs']:g} dBFS "
            "peak limiter (no dynamic compression of the dialogue).\n") if mastering else ""
    plat = ("| `platform/episodes/NN.mp4` (+ `.srt`, `platform/clean/`) | Two consecutive "
            "episodes joined per file (~2 min) for 1–3 min/episode specs; same frames |\n"
            if man.get("platform") else "")
    with open(os.path.join(outdir, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"""# {title} — delivery package

{eps} episodes, vertical {man.get('aspect', '9:16')}, original language: {lang}.
{('Produced by ' + man['studio'] + '.') if man.get('studio') else ''}

## Contents

| Path | What it is |
|---|---|
| `episodes/NN.mp4` | Broadcast master, subtitles burned in |
| `episodes/NN.srt` | Matching subtitle file, same numbering |
| `clean/NN.mp4` | **Clean master** — identical edit, mix and loudness, no burned-in subtitles |
| `covers/NN.jpg` | 3:4 vertical cover per episode |
| `timeline/NN.png` + `.edl.csv` | Edit timeline **rendered** from project data, plus a machine-readable cut list |
| `timeline/ui/NN.png` | Screenshots of the actual editing session, when supplied |
{plat}| `docs/` | Chain of title (to be signed), AI production disclosure |
| `manifest.json` | Measured specs of every file, rights check |

Episode files are numbered `01`, `02`, … so they sort and pair by filename.

## Notes for the reviewer

- Two kinds of edit evidence, deliberately kept apart: `timeline/NN.png` is **rendered**
  from edit data and says so on the image; `timeline/ui/` holds **actual screenshots**.
  One is never presented as the other.
{loud}- Rights check (music and fonts): **{man['rights']['status']}** — details in `manifest.json`.
- See `docs/AI-DISCLOSURE.md`.
""")
        if gaps:
            f.write("\n## Known gaps in this build\n\n" + "".join(f"- {g}\n" for g in gaps))
        f.write(footer)
