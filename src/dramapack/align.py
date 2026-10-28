"""Subtitle <-> speech alignment: compare SRT cue timings (and, when the subtitles are in
the spoken language, cue text) with a speech transcript.

The transcript comes from faster-whisper (``pip install dramapack[speech]``) through
``audit.transcribe``; everything here is pure Python on plain data so it can be tested
with hand-written segments. Transcript shape::

    {"language": "en", "duration": 62.0,
     "segments": [{"start": 0.4, "end": 2.1, "text": "...",
                   "words": [{"start": 0.4, "end": 0.7, "word": "..."}, ...]}, ...]}

``words`` is optional; with words the text check compares each cue with exactly the words
spoken under it, without them it falls back to whole segments.

What is measured, per episode:

- ``sub_drift``: median start offset (cue start - speech start) over cues that open a
  speech segment. A head trim applied to the picture but not to the SRT shows up here as
  one constant offset across the file.
- ``sub_offset_p90``: 90th percentile of the absolute per-cue offset, for a few badly
  timed lines in an otherwise good file.
- ``sub_orphan_share``: cues with no speech under them (a line that was cut from the edit
  but not from the SRT). Cues that are entirely a sound-effect / music annotation
  (``[door slams]``, ``(music)``, a music note) are exempt.
- ``sub_uncovered_s``: seconds of speech no cue covers (a missing line).
- ``sub_text``: only when the subtitle language matches the audio. Each cue is compared
  with what was heard under it (normalised edit distance); low similarity is a line that
  was rewritten in the script but not in the subtitles, and a word one or two letters off
  the heard word is a likely typo. Always yellow at most: ASR mishears names and slang,
  so this is a "look at it" list, never a blocker.
"""
import re
import statistics
import unicodedata

#: Speech segment and cue are "together" when they overlap by at least this much (s).
MIN_OVERLAP = 0.05
#: A speech segment counts as uncovered when less than this share of it is under a cue.
UNCOVERED_MIN_COVER = 0.3
#: Ignore uncovered speech segments shorter than this (breaths, ASR fragments).
UNCOVERED_MIN_SEG = 0.5
#: A cue is a likely typo / mismatched line below this similarity to the heard words.
TEXT_SIM_FLAG = 0.6
#: Below this MEDIAN similarity the subtitles are probably a translation: skip the check.
TEXT_SIM_TRANSLATED = 0.3
#: Cues shorter than this many normalised characters are too short to compare.
TEXT_MIN_CHARS = 4
MAX_FLAGS = 20

_ANNOT = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|[\u266a\u266b\u266c#*\s])+\s*$")
_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
_KANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")


def is_annotation(text: str) -> bool:
    """``[door slams]``, ``(music)``, a lone music note: not dialogue."""
    t = _TAGS.sub("", text or "")
    return bool(t.strip()) and bool(_ANNOT.match(t))


def normalize(text: str) -> str:
    """Lowercase, drop markup, punctuation and annotations; CJK keeps no spaces (edit
    distance is then per character, which is what a CJK typo is)."""
    t = _TAGS.sub("", text or "")
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)
    t = unicodedata.normalize("NFKC", t).lower()
    t = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in t)
    t = " ".join(t.split())
    if _CJK.search(t):
        t = t.replace(" ", "")
    return t


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """1 - normalised edit distance, on normalised text. 1.0 = identical."""
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def near_misses(srt_text: str, heard: str) -> list:
    """Word-level typo candidates: a subtitle word aligned against a heard word that differs
    by one or two letters (``rihgt`` / ``right``). A whole-line similarity cannot see these
    (one wrong letter in a 30-character line still scores ~0.95). Space-delimited scripts
    only; CJK lines are judged by the line similarity alone (ASR homophones would swamp a
    per-character check)."""
    import difflib  # noqa: PLC0415
    a, b = normalize(srt_text).split(), normalize(heard).split()
    if not a or _CJK.search(" ".join(a)):
        return []
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for x, y in zip(a[i1:i2], b[j1:j2]):
            if len(x) >= 3 and len(y) >= 3 and 0 < levenshtein(x, y) <= 2:
                out.append([x, y])
    return out[:5]


def guess_lang(text: str) -> str | None:
    """Script-level guess for CJK subtitles; None for everything else (Latin-script
    languages are told apart by the similarity itself, see TEXT_SIM_TRANSLATED)."""
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _CJK.search(text):
        return "zh"
    return None


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def align(cues: list, transcript: dict, *, srt_lang: str | None = None) -> dict:
    """``cues`` = ``[(start, end, text)]`` (``srt.parse_srt``); ``transcript`` as in the
    module docstring. Returns the ``sub_*`` metrics plus detail lists (capped)."""
    segs = sorted((s for s in transcript.get("segments") or []
                   if s.get("end", 0) > s.get("start", 0)), key=lambda s: s["start"])
    cues = sorted(cues, key=lambda c: c[0])
    dialog = [(i, c) for i, c in enumerate(cues) if not is_annotation(c[2])]
    out: dict = {"sub_cues": len(cues)}
    if not dialog:
        out["sub_note"] = "no dialogue cues in the SRT"
        return out
    if not segs:
        out["sub_note"] = "no speech found in the audio"
        return out

    # Each speech segment's opening is owned by the cue that overlaps it most among the
    # cues starting nearest its start. A segment spanning two cues gives the second cue no
    # onset of its own: its offset is undefined (mid-sentence), not "late".
    offsets, orphans, owner = [], [], {}
    for i, (a, b, text) in dialog:
        best, best_ov = None, 0.0
        for k, s in enumerate(segs):
            ov = _overlap(a, b, s["start"], s["end"])
            if ov > best_ov:
                best, best_ov = k, ov
        if best is None or best_ov < MIN_OVERLAP:
            orphans.append({"cue": i + 1, "start": round(a, 2), "end": round(b, 2),
                            "text": text.strip()[:80]})
            continue
        prev = owner.get(best)
        if prev is None or abs(a - segs[best]["start"]) < abs(prev[1] - segs[best]["start"]):
            owner[best] = (i, a)
    for k, (i, a) in owner.items():
        offsets.append({"cue": i + 1, "start": round(a, 2),
                        "offset": round(a - segs[k]["start"], 2)})
    offsets.sort(key=lambda o: o["cue"])

    uncovered, unc_s = [], 0.0
    for s in segs:
        d = s["end"] - s["start"]
        if d < UNCOVERED_MIN_SEG:
            continue
        cov = sum(_overlap(a, b, s["start"], s["end"]) for _, (a, b, _) in dialog)
        if cov / d < UNCOVERED_MIN_COVER:
            unc_s += d - cov
            uncovered.append({"start": round(s["start"], 2), "end": round(s["end"], 2),
                              "heard": (s.get("text") or "").strip()[:80]})

    if offsets:
        offs = [o["offset"] for o in offsets]
        out["sub_drift"] = round(abs(statistics.median(offs)), 2)
        out["sub_drift_signed"] = round(statistics.median(offs), 2)   # + = subtitles late
        out["sub_offset_p90"] = round(_p90([abs(x) for x in offs]), 2)
    out["sub_orphan_share"] = round(len(orphans) / len(dialog), 2)
    out["sub_uncovered_s"] = round(unc_s, 1)
    out["sub_orphans"] = orphans[:MAX_FLAGS]
    out["sub_uncovered"] = uncovered[:MAX_FLAGS]
    out["sub_late_early"] = [o for o in offsets
                             if abs(o["offset"]) > 0.5][:MAX_FLAGS]
    out.update(_text_check(dialog, segs, transcript.get("language"), srt_lang,
                           out.get("sub_drift_signed") or 0.0))
    return out


def _heard(a: float, b: float, segs: list) -> str:
    words = [w for s in segs for w in (s.get("words") or [])]
    if words:
        return " ".join((w.get("word") or "").strip() for w in words
                        if a <= (w["start"] + w["end"]) / 2 <= b)
    return " ".join((s.get("text") or "").strip() for s in segs
                    if _overlap(a, b, s["start"], s["end"]) >= 0.5 * (s["end"] - s["start"]))


def _text_check(dialog, segs, audio_lang, srt_lang, drift) -> dict:
    sample = " ".join(c[2] for _, c in dialog)
    srt_lang = (srt_lang or guess_lang(sample) or "").split("-")[0].lower() or None
    audio_lang = (audio_lang or "").split("-")[0].lower() or None
    if srt_lang and audio_lang and srt_lang != audio_lang:
        return {"sub_text_note": f"text check skipped: subtitles {srt_lang}, audio {audio_lang}"}
    rows = []
    for i, (a, b, text) in dialog:
        if len(normalize(text)) < TEXT_MIN_CHARS:
            continue
        # Look where the speech actually is: undo the measured drift, pad a little.
        heard = _heard(a - drift - 0.25, b - drift + 0.25, segs)
        if not normalize(heard):
            continue
        rows.append({"cue": i + 1, "start": round(a, 2), "srt": text.strip()[:120],
                     "heard": heard.strip()[:120], "similarity": round(similarity(text, heard), 2),
                     "words": near_misses(text, heard)})
    if not rows:
        return {}
    med = statistics.median(r["similarity"] for r in rows)
    if not srt_lang and med < TEXT_SIM_TRANSLATED:
        return {"sub_text_note": "text check skipped: subtitles appear to be a translation "
                                 f"(median similarity {med:.2f})"}
    flags = [r for r in rows if r["similarity"] < TEXT_SIM_FLAG or r["words"]]
    for r in rows:
        if not r["words"]:
            del r["words"]
    return {"sub_text": len(flags), "sub_text_median_sim": round(med, 2),
            "sub_text_flags": flags[:MAX_FLAGS]}
