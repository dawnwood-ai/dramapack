"""Delivery mastering — turn a raw episode cut into a file you can hand to a platform.

Three things, each a *requirement* for delivery rather than polish (all measured against
competing vertical dramas):

1. **Burned-in subtitles.** 80–85% of mobile viewing is muted; platform-ready episodes
   always carry burned subtitles. A sidecar SRT alone puts zero words on screen.
2. **Loudness.** Our early masters measured mean_volume −24.7 to −27.4 dB against −16.0 to
   −21.5 dB for the competition — 5–11 dB quieter, which on a phone speaker reads as
   "can't hear it".
3. **A continuous music bed.** Competing episodes don't "break" between clips because a
   continuous bed papers over the splice points. Its job is not to be pretty, it is to
   **hide the seams**: one measured splice dropped from a 40.8 dB level jump to 24.6 dB
   once a bed was laid under it.

The bed is **procedurally generated** (see :func:`render_bed`): no copyright exposure,
reproducible, no dependency on a music library. When dialogue plays the bed ducks via a
sidechain compressor — simply turning it down fails both ways (inaudible in the quiet
stretches, still muddy under the lines).
"""
import os
import re
import statistics
import subprocess

from .ff import (TIMEOUT_LONG, TIMEOUT_SHORT, ffmpeg_exe, has_audio, log_stderr, probe_duration,
                 video_fps, video_size)
from .srt import shift_srt

#: Integrated loudness target for finished episodes (LUFS).
#:
#: Benchmark: high-performing titles on large short-drama distribution networks measure
#: around −12.4 LUFS; masters at −15.8 to −17.7 sound "half as loud" on a phone. An A/B
#: listen of −15.8 vs −14.0 settled on −14 as the house standard.
#:
#: Normalisation happens in exactly one place, :func:`normalize_loudness`, and it is a
#: **constant gain** (measure integrated LUFS → one ``volume`` cut → true-peak ``alimiter``
#: as a ceiling). There is no ``loudnorm`` anywhere in the filter graphs, because:
#: single-pass loudnorm is *dynamic* (it pushes short-term loudness toward the target in
#: ~3 s windows), and two-pass ``linear=true`` only *permits* linear mode — when the source
#: LRA exceeds the target LRA (11) or the linear gain would break the TP ceiling, ffmpeg
#: **silently falls back to dynamic** (the second pass prints ``normalization_type=dynamic``).
#: Dialogue-plus-silence short-drama takes typically have an LRA of 15–20, so the fallback
#: is the norm, not the exception. Measured on a real master: dynamic mode lifted quiet
#: passages by +33 dB and the silent tail by +49 dB, raising the noise floor from −76 to
#: −30 dBFS — a clean take turned into an audibly hissy master.
TARGET_LUFS = "-14"

#: Base attenuation of the bed relative to dialogue (dB); the sidechain ducks it further
#: under lines. This value was measured — and measured wrong once. The first version was
#: tuned on the full-band seam jump to −16 dB; the metric looked great (61.8 → 27 dB) but
#: listeners reported "there's no music", because that bed was all low end and **phone
#: speakers can't reproduce below ~300 Hz**: quiet passages had only −58 dBFS in
#: 300–3000 Hz, 42 dB under the dialogue. Full-band RMS lied; people don't listen full-band.
#: Re-calibrated in the band phones can actually play (measured):
#:   bed −10 dB → quiet-passage midband −43.3 (27.1 under dialogue)   seam 12.4
#:   bed  −6 dB → quiet-passage midband −40.2 (23.9 under dialogue)   seam 10.7   ← chosen
#:   bed  −3 dB → quiet-passage midband −36.9 (21.2 under dialogue)   seam  9.7
#: Under dialogue, a −6 dB bed moves the speech band by only +0.1 dB (−20.5 → −20.4): the
#: sidechain is doing its job. Red line: the bed is background level and must never cover
#: the dialogue.
MUSIC_DB = -6.0

#: Subtitle style in **real pixels** (the ASS PlayRes is pinned to the video size below).
#: Pitfall: ffmpeg's srt→ass conversion defaults to a 384×288 canvas, so passing
#: ``force_style=FontSize=22`` gets scaled by libass by video_height/PlayResY ≈ 6.7× —
#: measured ~147 px glyphs, three lines smeared across the middle of the frame.
SUB_PX = {"FontSize": 52, "Outline": 4, "Shadow": 2, "MarginV": 150,
          "MarginL": 60, "MarginR": 60}
#: Bottom margin as a fraction of frame height rather than a fixed 150 px: 150/1920 ≈ 7.8%
#: sits exactly where player hover controls (progress bar) cover the frame, and below the
#: bottom UI safe area of TikTok/Douyin-style feeds. 18% ≈ 346 px on a 1920-high frame;
#: holds for portrait and landscape.
SUB_MARGINV_FRAC = 0.18
#: Left/right margins as a fraction of frame width. TikTok Drama Center's subtitle safe
#: area requires the text box to be ≤ 70% of frame width; a fixed 60 px margin let long
#: lines wrap at 89% width and a whole season was flagged "Optimizable". 0.16 ≈ 173 px on
#: a 1080-wide frame → text box ≤ 68%.
SUB_MARGINLR_FRAC = 0.16
#: Pin the font family. ffmpeg-generated ASS defaults to ``Fontname=Arial``; what libass
#: then renders depends on the machine's fontconfig (one box maps Arial to Liberation Sans
#: Bold, another falls through to Noto), so the same FontSize came out visibly larger on
#: one machine than another. Pinning a family keeps every machine identical. Glyphs the
#: family lacks (e.g. Devanagari) fall back per-glyph to other installed Noto families.
#: Noto is SIL OFL — free for commercial use, which the rights check verifies.
SUB_FONT = "Noto Sans CJK SC"

#: Bed presets — one synthesis engine, only pitch/tremolo/EQ change.
#: **The bed must have midrange.** A first version kept all energy under 300 Hz (to stay
#: out of the dialogue's way) and phone speakers simply could not play it — quiet passages
#: measured −58 dBFS in 300–1000 Hz, 42 dB under dialogue, and listeners heard "no music".
#: The seam metric improved at the time because it measured full-band RMS. Now the
#: fundamentals extend up to 2.6 kHz and the bed yields to dialogue via the **sidechain**,
#: not via frequency avoidance.
#: tension = D minor (default); warm = F major, slow tremolo, soft top;
#: suspense = minor-second friction, fast tremolo; dread = tritone, low centre, very slow
#: tremolo; hope = D major, bright tilt.
BED_PRESETS = {
    "tension":  {"notes": (73.42, 110.00, 174.61, 220.00),   # D2, A2, F3, A3
                 "gains": (-4, -8, -13, -16), "tremolo": (0.11, 0.13, 0.17, 0.19),
                 "lp": 2600, "hp": 40, "tilt_db": 14, "tilt_hz": 700},
    "warm":     {"notes": (87.31, 130.81, 220.00, 261.63),   # F2, C3, A3, C4
                 "gains": (-6, -9, -12, -16), "tremolo": (0.10, 0.12, 0.14, 0.16),
                 "lp": 2000, "hp": 50, "tilt_db": 10, "tilt_hz": 500},
    "suspense": {"notes": (73.42, 110.00, 155.56, 196.00),   # D2, A2, Eb3, G3
                 "gains": (-4, -9, -14, -18), "tremolo": (0.17, 0.23, 0.29, 0.31),
                 "lp": 2600, "hp": 40, "tilt_db": 12, "tilt_hz": 800},
    "dread":    {"notes": (73.42, 110.00, 174.61, 207.65),   # D2, A2, F3, G#3 (tritone)
                 "gains": (-3, -7, -14, -17), "tremolo": (0.10, 0.11, 0.12, 0.13),
                 "lp": 2200, "hp": 35, "tilt_db": 12, "tilt_hz": 600},
    "hope":     {"notes": (73.42, 110.00, 185.00, 246.94),   # D2, A2, F#3, B3
                 "gains": (-5, -8, -12, -15), "tremolo": (0.10, 0.13, 0.16, 0.18),
                 "lp": 3000, "hp": 45, "tilt_db": 14, "tilt_hz": 900},
}
BED_MOODS = tuple(BED_PRESETS)
#: Midrange lift: low fundamentals dominate naturally, and without a lift the bed's
#: 300–3000 Hz energy sits 12 dB under its full-band level — and **that band is all a
#: phone speaker plays**. +14 dB @ 700 Hz closes the gap to 8 dB (−39.3 → −33.3 dBFS).
BED_TILT_DB = BED_PRESETS["tension"]["tilt_db"]
#: Bed fade-in. **It used to be 2.0 s, and that was why openings sounded empty**: cold opens
#: are usually dialogue-free establishing shots, so the first two seconds measured −45 to
#: −52 dBFS. Feed viewers decide to stay or swipe in those seconds. 0.4 s avoids a click
#: and still has the bed present immediately.
BED_FADE_IN = 0.4
BED_FADE_OUT = 3.0

#: End card length. Not decoration — two hard uses: (1) TikTok Creator Rewards requires
#: videos longer than one minute, and a short card lifts 50–59 s episodes over the line;
#: (2) feed captions aren't clickable, so "next episode when/where" has to be on screen.
#: **4 s, not 7.5 s**: a 7.5 s card is 12% of a 61 s episode, and retention curves showed
#: it crushing end-of-video retention (r75 = 58% → r100 = 16%, versus 30–43% at r100 for
#: episodes without one). Completion rate feeds Shorts/Reels distribution directly. Four
#: lines read in 4 s; close duration gaps with story, not with a longer card. The audit's
#: ``tail_static`` metric watches this.
CARD_SECS = 4.0
CARD_BG = (8, 8, 10)
CARD_FG = (232, 226, 216)
CARD_DIM = (198, 190, 180)
CARD_MUTED = (120, 116, 112)
CARD_RULE = (150, 40, 45)
#: Serif first, then sans. All candidates are free for commercial use (Noto: SIL OFL;
#: DejaVu: Bitstream Vera license) — see rights.FONT_ALLOWLIST.
CARD_FONTS = (
    "/usr/share/fonts/google-noto-cjk/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def fontsdir() -> str | None:
    """A directory libass can scan for CJK fonts — missing glyphs burn in as boxes."""
    env = os.environ.get("DRAMAPACK_FONTSDIR")
    if env and os.path.isdir(env):
        return env
    for p in ("/usr/share/fonts/google-noto-cjk", "/usr/share/fonts/opentype/noto",
              "/usr/share/fonts/truetype/noto", "/usr/share/fonts"):
        if os.path.isdir(p):
            return p
    return None


# --- music bed ---------------------------------------------------------------------

def render_bed(exe: str, seconds: float, out: str, mood: str = "tension",
               fade_in: bool = True, fade_out: bool = True) -> str:
    """Procedurally generate a music bed (pure ffmpeg oscillators; no external material,
    hence no copyright exposure). ``mood`` selects a :data:`BED_PRESETS` entry.
    ``fade_in``/``fade_out`` exist for :func:`render_bed_sections`, whose inner sections
    must not fade on their own — the joins are crossfaded instead.

    Each fundamental carries two overtones (2f/3f) so the tone isn't hollow; a low-pass
    sits just above the voice. **No frequency-band avoidance of the voice** — the version
    that tried that was inaudible on phones; ducking is the sidechain's job."""
    p = BED_PRESETS.get(mood) or BED_PRESETS["tension"]
    seconds = max(2.0, float(seconds))
    cmd = [exe, "-y", "-hide_banner", "-v", "error"]
    chains, labels, i = [], [], 0
    for f, g, tf in zip(p["notes"], p["gains"], p["tremolo"]):
        for mult, extra in ((1, 0), (2, -9), (3, -15)):   # fundamental + two overtones
            if f * mult > p["lp"]:
                continue
            cmd += ["-f", "lavfi", "-t", f"{seconds:.2f}",
                    "-i", f"sine=frequency={f * mult:.2f}:sample_rate=48000"]
            tf = max(0.1, tf)   # ffmpeg's tremolo rejects < 0.1 Hz and fails the whole graph
            chains.append(f"[{i}:a]volume={g + extra}dB,tremolo=f={tf}:d=0.35[n{i}]")
            labels.append(f"[n{i}]")
            i += 1
    tail = (f"[sum]lowpass=f={p['lp']},highpass=f={p['hp']},"
            f"equalizer=f={p['tilt_hz']}:width_type=o:width=2.2:g={p['tilt_db']}")
    if fade_in:
        tail += f",afade=t=in:d={BED_FADE_IN}"
    if fade_out:
        tail += f",afade=t=out:st={max(0.0, seconds - BED_FADE_OUT):.2f}:d={BED_FADE_OUT}"
    graph = ";".join(chains) + ";" + (
        "".join(labels) + f"amix=inputs={len(labels)}:normalize=0[sum];"
        + tail + ",aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
    )
    cmd += ["-filter_complex", graph, "-map", "[a]", "-c:a", "pcm_s16le", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_LONG)
    if r.returncode != 0:
        raise RuntimeError(f"music bed render failed: {r.stderr[-600:]}")
    return out


def render_bed_sections(exe: str, sections: list, out: str, xf: float = 2.0) -> str:
    """A bed whose mood changes per section: ``sections=[{"secs", "mood"}]`` rendered
    individually and joined with ``acrossfade``. Total ≈ sum(secs) (non-final sections are
    rendered ``xf`` longer to pay for the overlap). Only the first section fades in and
    only the last fades out, so the bed never dips at a join. One section degrades to
    :func:`render_bed`."""
    n = len(sections)
    if not n:
        raise RuntimeError("music bed: no sections")
    secs = [max(2.0, float(s.get("secs") or 0)) for s in sections]
    if n == 1:
        return render_bed(exe, secs[0], out, sections[0].get("mood") or "tension")
    xf = max(0.5, min(float(xf), min(secs)))   # the overlap can't exceed the shortest section
    workdir = os.path.dirname(os.path.abspath(out)) or "."
    cmd = [exe, "-y", "-hide_banner", "-v", "error"]
    for i, s in enumerate(sections):
        part = os.path.join(workdir, f"bedsec{i}.wav")
        render_bed(exe, secs[i] + (xf if i < n - 1 else 0.0), part, s.get("mood") or "tension",
                   fade_in=(i == 0), fade_out=(i == n - 1))
        cmd += ["-i", part]
    chains, prev = [], "[0:a]"
    for i in range(1, n):
        lbl = "[a]" if i == n - 1 else f"[x{i}]"
        chains.append(f"{prev}[{i}:a]acrossfade=d={xf:.2f}:c1=tri:c2=tri{lbl}")
        prev = lbl
    cmd += ["-filter_complex", ";".join(chains), "-map", "[a]", "-c:a", "pcm_s16le", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_LONG)
    if r.returncode != 0:
        raise RuntimeError(f"music bed section join failed: {r.stderr[-600:]}")
    return out


def duck_graph(music_db: float = MUSIC_DB) -> str:
    """Dialogue + bed mix with **sidechain ducking**: lines play, the bed yields; lines end,
    it comes back.

    Dialogue ``[0:a]`` is split — one leg to the mix, one leg as the sidechain key; the bed
    is attenuated to ``music_db`` then compressed by the key; ``amix`` outputs ``[a]``.
    **No loudnorm at the end of the chain**: final loudness is set by
    :func:`normalize_loudness` with a constant gain (a dynamic loudnorm here would lift the
    bed and noise floor in quiet passages — see :data:`TARGET_LUFS`)."""
    return (f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[dry][key];"
            f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume={music_db}dB[bed];"
            f"[bed][key]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=400"
            f":makeup=1[duck];"
            f"[dry][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")


# --- subtitles ---------------------------------------------------------------------

def ass_from_srt(exe: str, srt: str, workdir: str, size: tuple,
                 font: str = SUB_FONT) -> str:
    """SRT → ASS with PlayRes pinned to the video size and the style written in real pixels.

    Not optional: ffmpeg's srt→ass defaults to PlayRes 384×288 and libass scales every
    size by video_height/PlayResY — FontSize and margins in ``force_style`` all come out
    wrong."""
    w, h = size
    ass = os.path.join(workdir, "subs.ass")
    subprocess.run([exe, "-y", "-v", "error", "-i", srt, ass], check=True,
                   capture_output=True, timeout=TIMEOUT_SHORT)
    txt = open(ass, encoding="utf-8").read()
    txt = re.sub(r"^PlayResX:.*$", f"PlayResX: {w}", txt, flags=re.M)
    txt = re.sub(r"^PlayResY:.*$", f"PlayResY: {h}", txt, flags=re.M)
    if "PlayResX" not in txt:   # some ffmpeg builds don't write it at all
        txt = txt.replace("[Script Info]", f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}", 1)

    def _style(m):
        f = m.group(1).split(",")
        # 0 Name, 1 Fontname, 2 Fontsize, 3 Primary, 4 Secondary, 5 Outline, 6 Back,
        # 7 Bold, 8 Italic, 9 Underline, 10 StrikeOut, 11 ScaleX, 12 ScaleY, 13 Spacing,
        # 14 Angle, 15 BorderStyle, 16 Outline, 17 Shadow, 18 Alignment,
        # 19 MarginL, 20 MarginR, 21 MarginV, 22 Encoding
        # Pitfall: an off-by-one from BorderStyle onward once wrote MarginV into Encoding;
        # the real MarginV stayed at ffmpeg's default and subtitles sat under the player's
        # hover controls. tests/test_subtitles.py pins every slot.
        if len(f) >= 23:
            f[1] = font
            f[2] = str(SUB_PX["FontSize"])
            f[3] = "&H00FFFFFF"           # white text
            f[5] = "&H00000000"           # black outline
            f[7] = "-1"                   # bold
            f[15] = "1"                   # BorderStyle = outline + shadow
            f[16] = str(SUB_PX["Outline"])
            f[17] = str(SUB_PX["Shadow"])
            f[18] = "2"                   # Alignment = bottom centre
            f[19] = str(max(SUB_PX["MarginL"], round(w * SUB_MARGINLR_FRAC)))
            f[20] = str(max(SUB_PX["MarginR"], round(w * SUB_MARGINLR_FRAC)))
            f[21] = str(max(SUB_PX["MarginV"], round(h * SUB_MARGINV_FRAC)))
        return "Style: " + ",".join(f)

    txt = re.sub(r"^Style:\s*(.+)$", _style, txt, flags=re.M)
    with open(ass, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return ass


# --- end card ----------------------------------------------------------------------

def card_font_path() -> str | None:
    """The font file the end card will actually use (None = PIL's built-in bitmap font)."""
    for p in CARD_FONTS:
        if os.path.exists(p):
            return p
    return None


def _card_font(size: int):
    from PIL import ImageFont  # noqa: PLC0415
    for p in CARD_FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001 — .ttc index / damaged font, try the next
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:               # Pillow < 10.1
        return ImageFont.load_default()


def end_card_png(path: str, size: tuple, *, title: str, lines=(), site: str = "") -> str:
    """Draw an end card. ``title`` wraps at the middle word when it has more than two
    words; ``lines`` are the CTA lines in the middle (e.g. "EP.5 TOMORROW", "7PM ET");
    ``site`` is the small line at the bottom. Pure PIL, no external assets."""
    from PIL import Image, ImageDraw  # noqa: PLC0415
    w, h = size
    img = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(img)
    s = w / 1080.0                                  # font sizes are specified for 1080 wide
    f_title, f_cta, f_site = _card_font(int(78 * s)), _card_font(int(52 * s)), _card_font(int(40 * s))

    def center(txt, y, font, fill):
        if not txt:
            return
        bb = d.textbbox((0, 0), txt, font=font)
        # Long lines (a next-episode hook) shrink until they fit within 90% width.
        fsize = getattr(font, "size", None)
        while bb[2] > w * 0.9 and fsize and fsize > int(24 * s):
            fsize = int(fsize * 0.92)
            font = _card_font(fsize)
            bb = d.textbbox((0, 0), txt, font=font)
        d.text(((w - bb[2]) // 2, y), txt, font=font, fill=fill)

    words = (title or "").split()
    head = [" ".join(words[:len(words) // 2]), " ".join(words[len(words) // 2:])] \
        if len(words) > 2 else [title or ""]
    y = int(h * 0.385)
    for ln in head:
        center(ln, y, f_title, CARD_FG)
        y += int(95 * s)
    y += int(30 * s)
    d.line([(w // 2 - int(150 * s), y), (w // 2 + int(150 * s), y)], fill=CARD_RULE,
           width=max(2, int(3 * s)))
    y += int(60 * s)
    for ln in lines:
        center(ln, y, f_cta, CARD_DIM)
        y += int(70 * s)
    center(site, y + int(65 * s), f_site, CARD_MUTED)
    img.save(path)
    return path


# --- loudness ----------------------------------------------------------------------

def measure_loudness(exe: str, path: str, target: float | None = None) -> dict | None:
    """Measurement pass: loudnorm's JSON block (input_i/input_tp/input_lra/...) for the
    whole audio track, or None when there's no measurable audio. Measurement only — the
    gain is applied by :func:`normalize_loudness` as a constant."""
    import json  # noqa: PLC0415
    r = subprocess.run([exe, "-hide_banner", "-nostats", "-i", path,
                        "-af", f"loudnorm=I={target if target is not None else TARGET_LUFS}"
                               f":TP=-1.0:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True,
                       timeout=TIMEOUT_LONG)
    # Don't anchor at end of output: some ffmpeg builds print more after the JSON block.
    # Take the *last* block that parses and contains input_i.
    for blk in reversed(re.findall(r"\{[^{}]*\}", r.stderr)):
        try:
            d = json.loads(blk)
        except ValueError:
            continue
        if "input_i" in d:
            return d
    return None


def measure_integrated_lufs(exe: str, path: str) -> float | None:
    """Integrated LUFS of the whole track; None when unmeasurable or silent (< −70)."""
    m = measure_loudness(exe, path)
    try:
        v = float(m["input_i"]) if m else None
    except (TypeError, ValueError, KeyError):
        return None
    return v if v is not None and v > -70.0 else None


#: Near-silent / ambience-only segments (insert shots, empty rooms) measure below −40 LUFS.
#: There's no dialogue to align them to; pushing them up only turns room tone into hiss.
FOLLOW_FLOOR_LUFS = -40.0


def loudness_gains(lufs_list: list, *, clamp_db: float = 12.0, min_db: float = 0.5,
                   floor_lufs: float = FOLLOW_FLOOR_LUFS) -> list:
    """Per-part gain table (dB) that aligns every part to the **first** part before
    concatenation. First part is always 0; unmeasurable (None) → 0 (don't guess); either
    side below ``floor_lufs`` (near silence) → 0; |gain| < ``min_db`` counts as aligned;
    clamped to ±``clamp_db`` (automatic paths stay conservative). Pure function."""
    if not lufs_list:
        return []
    ref = lufs_list[0]
    out = [0.0]
    for v in lufs_list[1:]:
        if ref is None or v is None or ref < floor_lufs or v < floor_lufs:
            out.append(0.0)
            continue
        g = ref - v
        if abs(g) < min_db:
            g = 0.0
        out.append(round(max(-clamp_db, min(clamp_db, g)), 2))
    return out


def loudness_match_gains(lufs_list: list, *, clamp_db: float = 12.0, min_db: float = 0.5,
                         floor_lufs: float = FOLLOW_FLOOR_LUFS,
                         target: float | None = None) -> list:
    """Per-part gain table (dB) toward a **common target** — by default the median of the
    parts that contain dialogue — instead of following the first part.

    Why not follow the first part: when the first part happens to be a quiet scene (mostly
    silence and one or two lines, e.g. −32.9 vs −20.4/−22.3 LUFS for the rest) every other
    part is pulled down, hits the clamp and still doesn't align; when the first part is
    near-silent (an empty establishing shot) :func:`loudness_gains` returns all zeros and
    nothing is aligned at all. The median is robust to one outlier and minimises total
    gain (absolute level is set afterwards by :func:`normalize_loudness`; this only fixes
    relative levels, and every dB not lifted is noise floor not lifted).

    Unmeasurable / below ``floor_lufs`` → 0 and excluded from the target; no dialogue parts
    → all 0; |gain| < ``min_db`` → 0; clamped ±``clamp_db``. Pure function."""
    speech = [float(v) for v in lufs_list if v is not None and v >= floor_lufs]
    if not speech:
        return [0.0] * len(lufs_list)
    if target is None:
        target = statistics.median(speech)
    out = []
    for v in lufs_list:
        if v is None or v < floor_lufs:
            out.append(0.0)
            continue
        g = float(target) - float(v)
        if abs(g) < min_db:
            g = 0.0
        out.append(round(max(-clamp_db, min(clamp_db, g)), 2))
    return out


#: Constant-gain clamp for :func:`normalize_loudness`. Real takes land at −20 to −27 LUFS
#: (+6 to +13 dB to reach −14); +20 covers very quiet takes down to −34 LUFS. Anything
#: quieter is a near-silent / breath-only take — pushing it just makes the noise floor
#: audible; re-render those instead. −24 leaves room to pull down clipped material.
#: A constant gain never changes SNR; the clamp only prevents "lifting silence into noise".
GAIN_MAX_DB = 20.0
GAIN_MIN_DB = -24.0
#: Peak ceiling for streaming delivery. The limiter only touches samples above it.
TRUE_PEAK_DB = -1.0


def loudness_gain_db(measured_lufs: float, target: float | None = None) -> float:
    """Constant gain (dB) = target − measured integrated LUFS, clamped to
    [GAIN_MIN_DB, GAIN_MAX_DB]. Pure function."""
    tgt = float(target if target is not None else TARGET_LUFS)
    return round(max(GAIN_MIN_DB, min(GAIN_MAX_DB, tgt - float(measured_lufs))), 2)


def normalize_loudness(src: str, out: str, *, exe: str | None = None,
                       target: float | None = None, measure_src: str | None = None,
                       log=log_stderr) -> str:
    """Final loudness: measure integrated LUFS → one **constant** ``volume`` gain to the
    target → ``alimiter`` to catch peaks above :data:`TRUE_PEAK_DB`. Audio is re-encoded;
    video is stream-copied, so the timeline is unchanged.

    Why not loudnorm (even two-pass ``linear=true``): it only *permits* linear mode and
    silently falls back to dynamic when source LRA > target LRA or the gain would break
    TP — then soft passages, pauses and the noise floor are lifted separately (measured
    under fallback: three steps of a test signal lifted +5/+7/+12 dB; on a real master
    +33 dB in quiet passages, +49 dB on the tail). Short-drama takes run LRA 15–20, so the
    fallback is routine. Constant gain + peak limiter is standard mastering practice: SNR
    is preserved bit for bit; the landing point is the target minus whatever the clamp or
    limiter removed.

    ``measure_src``: measure on this file, apply the gain to ``src``. :func:`master` passes
    the **dry dialogue cut**: integrated LUFS uses a relative gate, and once a bed is laid
    the bed in quiet passages gets let through the gate and pulls the measurement down
    2–3 LU (a −14.8 cut measured −18.4 after bedding). Measuring the mix would push the
    dialogue 3–4 dB into the limiter. "Anchored on dialogue" means measured on dialogue."""
    exe = exe or ffmpeg_exe()
    tgt = float(target if target is not None else TARGET_LUFS)
    lufs = measure_integrated_lufs(exe, measure_src or src)
    if lufs is None:
        raise RuntimeError(f"loudness: cannot measure {src} (no audio track / all silent?)")
    gain = loudness_gain_db(lufs, tgt)
    limit = 10 ** (TRUE_PEAK_DB / 20)
    af = f"volume={gain:.2f}dB,alimiter=limit={limit:.3f}:attack=5:release=50:level=false"
    r = subprocess.run([exe, "-y", "-hide_banner", "-v", "error", "-i", src,
                        "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-ar", "48000", "-movflags", "+faststart", out],
                       capture_output=True, text=True, timeout=TIMEOUT_LONG)
    if r.returncode != 0:
        raise RuntimeError(f"loudness normalisation failed: {r.stderr[-800:]}")
    if log:
        log(f"normalize_loudness: {lufs:.1f} LUFS -> {gain:+.1f} dB constant (target {tgt:g})")
    return out


# --- master ------------------------------------------------------------------------

def master(video: str, srt: str | None, out: str, *, burn: bool = True,
           music: str | None = None, music_db: float = MUSIC_DB,
           exe: str | None = None, head_trim: float = 0.0,
           end_card: dict | None = None, card_secs: float = CARD_SECS,
           normalize: bool = True, cover_band: float = 0.0,
           subtitle_font: str = SUB_FONT, log=log_stderr) -> str:
    """Burn subtitles + normalise loudness (+ optional bed / head trim / end card).

    ``head_trim`` cuts the first N seconds. Openings often start with a dead frame of no
    dialogue and no motion, and feed viewers decide within those seconds.

    ``end_card = {"title", "lines", "site"}`` appends a ``card_secs`` card (see
    :data:`CARD_SECS`). The card is silent, but **the bed spans the total length including
    the card**, so the episode never drops into dead air.

    ``cover_band`` (0.05–0.4) blurs that fraction of the frame bottom before burning new
    subtitles — for re-subtitling source material that already has burned-in subtitles
    (e.g. a localised version).

    Intermediate files (``_endcard.png``, ``_shifted.srt``, ``subs.ass``,
    ``_premaster.mp4``) are written next to ``out``; stage into a scratch directory when
    ``out`` lives in a delivery folder."""
    exe = exe or ffmpeg_exe()
    work = os.path.dirname(os.path.abspath(out)) or "."
    size = video_size(exe, video)
    head_trim = max(0.0, float(head_trim or 0.0))
    body = max(0.1, probe_duration(exe, video) - head_trim)
    card_secs = float(card_secs) if end_card else 0.0
    total = body + card_secs

    vchain = []
    if burn and srt:
        if head_trim:                      # a head trim must shift the subtitles too
            srt = shift_srt(srt, os.path.join(work, "_shifted.srt"), -head_trim)
        ass = ass_from_srt(exe, srt, work, size, font=subtitle_font)
        # The ass filter needs an *escaped* path (colon/backslash are option separators).
        esc = ass.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        fd = fontsdir()
        vchain.append(f"ass=filename='{esc}'" + (f":fontsdir='{fd}'" if fd else ""))

    cmd = [exe, "-y", "-hide_banner", "-v", "error"]
    if head_trim:
        cmd += ["-ss", f"{head_trim:.3f}"]           # applies to input 0 (the episode) only
    cmd += ["-i", video]
    idx_card = idx_music = None
    if end_card:
        png = end_card_png(os.path.join(work, "_endcard.png"), size,
                           title=end_card.get("title") or "", lines=end_card.get("lines") or (),
                           site=end_card.get("site") or "")
        cmd += ["-loop", "1", "-t", f"{card_secs:.3f}", "-i", png]
        idx_card = 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        idx_music = (idx_card or 0) + 1

    parts = []
    src_v = "[0:v]"
    if cover_band and 0.05 <= float(cover_band) <= 0.4:
        bh = max(2, int(size[1] * float(cover_band)) // 2 * 2)
        parts.append(f"[0:v]split[vb0][vb1];[vb1]crop=iw:{bh}:0:ih-{bh},"
                     f"boxblur=luma_radius=24:luma_power=3,"
                     f"eq=brightness=-0.08[vblur];[vb0][vblur]overlay=0:H-{bh}[vcov]")
        src_v = "[vcov]"
    parts.append(f"{src_v}{','.join(vchain) + ',' if vchain else ''}"
                 f"setsar=1,format=yuv420p[v0]")
    if idx_card is not None:
        # The card must match size / pixel format, or concat refuses it.
        parts.append(f"[{idx_card}:v]scale={size[0]}:{size[1]},setsar=1,format=yuv420p,"
                     f"fade=t=in:st=0:d=0.4[v1]")
        parts.append("[v0][v1]concat=n=2:v=1:a=0[v]")
        vlabel = "[v]"
    else:
        vlabel = "[v0]"
    # Audio: dialogue padded to the total length (silence under the card), then the
    # sidechain mix if there is a bed. **No loudnorm in the graph** (dynamic normalisation
    # lifts the noise floor); final loudness is the constant-gain pass below.
    parts.append(f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[dlg]")
    if music:
        parts.append(f"[{idx_music}:a]atrim=0:{total:.3f}[bedsrc]")
        parts.append(duck_graph(music_db).replace("[0:a]", "[dlg]").replace("[1:a]", "[bedsrc]"))
        alabel = "[a]"
    else:
        alabel = "[dlg]"

    pre = os.path.join(work, "_premaster.mp4") if normalize else out
    cmd += ["-filter_complex", ";".join(parts), "-map", vlabel, "-map", alabel,
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", pre]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_LONG)
    if r.returncode != 0:
        raise RuntimeError(f"master encode failed: {r.stderr[-1200:]}")
    # ``normalize=False`` exists for tests that measure *pre-normalisation* properties
    # (the ducking tests measure bed/dialogue ratios; the clamp and limiter move absolute
    # levels and would muddy absolute-level assertions).
    if normalize:
        try:
            # Anchor on the dialogue: measure the dry input, not the bedded mix.
            normalize_loudness(pre, out, exe=exe, measure_src=video, log=log)
            os.remove(pre)
        except RuntimeError as e:
            # A failed normalisation does not discard the master; it ships un-normalised
            # and the reason is logged for a human to look at.
            if log:
                log(f"loudness normalisation skipped (un-normalised master kept): {e}")
            os.replace(pre, out)
    return out


def concat_mp4(exe: str, parts: list, dest: str, *, preset: str = "medium") -> str:
    """Join finished episodes end to end with the concat **filter**, not demuxer + ``-c copy``.

    Separately encoded masters can differ subtly in timebase/SPS; a stream-copied join
    plays but often drops frames or slips A/V sync at the seam — and this file is what a
    buyer watches first. One re-encode buys a seam that's certainly clean. Parts are
    aligned to the first part's loudness (:func:`loudness_gains`)."""
    cmd = [exe, "-y", "-hide_banner", "-v", "error"]
    for p in parts:
        cmd += ["-i", p]
    n = len(parts)
    try:
        gains = loudness_gains([measure_integrated_lufs(exe, p) for p in parts])
    except Exception:  # noqa: BLE001
        gains = [0.0] * n
    chains = "".join(f"[{i}:a:0]volume={gains[i]:.2f}dB[ga{i}];" if gains[i] else ""
                     for i in range(n))
    streams = "".join(f"[{i}:v:0]" + (f"[ga{i}]" if gains[i] else f"[{i}:a:0]")
                      for i in range(n))
    cmd += ["-filter_complex", f"{chains}{streams}concat=n={n}:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", preset, "-crf", "19",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", dest]
    subprocess.run(cmd, check=True, capture_output=True, timeout=TIMEOUT_LONG)
    return dest


# --- TikTok Drama Center finishing ----------------------------------------------------

#: Edge lift. Drama Center rejects episodes with a dark band along one side ("black bars",
#: code 4; detection in ``audit.edge_runs``). Two fixes, both measured on rejected
#: episodes (2026-10-31):
#: 1. Crop EDGE_CROP_PX off every side and scale back to the frame size. Removes the hard
#:    2 px black column that AI-video sources rendered 1078 wide and padded to 1080 carry
#:    on the right edge. 4 px at 1080 is a 0.4% zoom, invisible.
#: 2. A four-side LIFT_PX cosine ramp up to luma LIFT_LUMA (full range; 0 in the middle)
#:    blended with ``lighten``: only pixels darker than the mask move, so a bright edge is
#:    untouched and a black one becomes a dark grey the detector no longer counts.
#:    Re-measured after the lift: every 20 px band averaged >= 25.5 (threshold 12).
#: Sizes are stated at 1080 wide and scaled to the frame.
EDGE_CROP_PX = 4
LIFT_PX = 160
LIFT_LUMA = 26
#: Cover head. Drama Center uses frame 0 as the default episode cover; picking a keyframe
#: is a manual step per episode in its UI. A 1 s still of the cover (silent audio) at the
#: head makes frame 0 the cover.
COVER_HEAD_S = 1.0


def edge_mask_png(path: str, size: tuple) -> str:
    """Grey mask for :func:`dc_finish`: cosine ramp from LIFT_LUMA at each edge to 0 at
    LIFT_PX in. Built from four ramps merged with ``lighter`` (max) - the same as taking
    the nearest edge, without a per-pixel loop."""
    import math  # noqa: PLC0415

    from PIL import Image, ImageChops  # noqa: PLC0415

    w, h = size
    n = max(2, round(LIFT_PX * w / 1080))
    ramp = [int(round(LIFT_LUMA * 0.5 * (1 + math.cos(math.pi * d / n)))) for d in range(n)]
    col = Image.new("L", (1, n))
    col.putdata(ramp)
    row = Image.new("L", (n, 1))
    row.putdata(ramp)
    top, left = col.resize((w, n)), row.resize((n, h))
    mask = Image.new("L", (w, h), 0)
    for im, xy in ((top, (0, 0)), (top.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, h - n)),
                   (left, (0, 0)), (left.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (w - n, 0))):
        layer = Image.new("L", (w, h), 0)
        layer.paste(im, xy)
        mask = ImageChops.lighter(mask, layer)
    mask.save(path, "PNG")
    return path


def dc_finish(src: str, out: str, *, cover: str | None = None, lift: bool = True,
              head_s: float = COVER_HEAD_S, exe: str | None = None, log=log_stderr) -> dict:
    """TikTok Drama Center finishing of a finished episode: optional ``cover`` still for
    ``head_s`` at the head (frame 0 = the cover), and the edge lift (crop + scale back +
    ``lighten`` mask). The frame size and rate stay those of ``src``. Burned subtitles move
    with the picture; a sidecar SRT must be shifted by ``head_s`` (the caller does it).
    Returns what was applied."""
    exe = exe or ffmpeg_exe()
    w, h = video_size(exe, src)
    fps = video_fps(exe, src)
    audio = has_audio(exe, src)
    info: dict = {"cover_head_s": head_s if cover else 0.0, "edge_lift": None}
    cmd = [exe, "-y", "-hide_banner", "-v", "error", "-i", src]
    graph = []
    if lift:
        cx = max(2, 2 * round(EDGE_CROP_PX * w / 1080 / 2))
        cy = max(2, 2 * round(cx * h / w / 2))
        graph.append(f"[0:v]crop={w - 2 * cx}:{h - 2 * cy},scale={w}:{h},setsar=1,"
                     f"format=yuv420p[body]")
        info["edge_lift"] = {"crop_px": [cx, cy], "mask_px": max(2, round(LIFT_PX * w / 1080)),
                             "mask_luma": LIFT_LUMA}
    else:
        graph.append("[0:v]setsar=1,format=yuv420p[body]")
    body = "[body]"
    nxt = 1
    if cover:
        # Fill the frame (scale up + centre crop), never pad: padding a 3:4 cover would
        # put black bars on the head, the very thing this function removes.
        cmd += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{head_s:.3f}", "-i", cover]
        graph.append(f"[{nxt}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                     f"crop={w}:{h},setsar=1,fps={fps:g},format=yuv420p[head]")
        nxt += 1
        if audio:
            cmd += ["-f", "lavfi", "-t", f"{head_s:.3f}", "-i",
                    "anullsrc=r=48000:cl=stereo"]
            A = "aformat=sample_rates=48000:channel_layouts=stereo"
            graph.append(f"[{nxt}:a]{A}[ha];[0:a]{A}[ba];[head][ha][body][ba]"
                         "concat=n=2:v=1:a=1[cat][oa]")
            nxt += 1
        else:
            graph.append("[head][body]concat=n=2:v=1:a=0[cat]")
        body = "[cat]"
    if lift:
        mask = edge_mask_png(os.path.splitext(out)[0] + ".mask.png", (w, h))
        cmd += ["-loop", "1", "-framerate", f"{fps:g}", "-i", mask]
        # blend needs shortest=1: the looped mask never ends. c1/c2 "normal" at opacity 1
        # keep the picture's chroma; only luma is lightened.
        graph.append(f"[{nxt}:v]format=gray,format=yuv420p[mask];{body}[mask]blend="
                     "c0_mode=lighten:c1_mode=normal:c2_mode=normal:c1_opacity=1:"
                     "c2_opacity=1:shortest=1[ov]")
        body = "[ov]"
    cmd += ["-filter_complex", ";".join(graph), "-map", body]
    if audio:
        cmd += ["-map", "[oa]" if cover else "0:a",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_LONG)
    if lift:
        try:
            os.remove(os.path.splitext(out)[0] + ".mask.png")
        except OSError:
            pass
    if r.returncode != 0:
        raise RuntimeError(f"dc_finish failed: {r.stderr[-400:]}")
    if log:
        log(f"dc_finish: cover head {info['cover_head_s']:g} s, edge lift "
            f"{'on' if lift else 'off'}")
    return info
