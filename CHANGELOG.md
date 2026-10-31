# Changelog

All notable changes to dramapack. Versions follow [Semantic Versioning](https://semver.org/).

## 0.3.0 - 2026-10-31

TikTok Drama Center finishing, from two real "Can be improved" rejections.

### Added

- **Dark edge bands** in `audit` (`edge_dark`): the longest run, per side, of a 20 px band
  (at 1080 wide) or its outer 2 px line darker than mean luma 12 (0-255), sampled at
  5 fps in the same decode as shot and black-frame detection. Red above 3.5 s, yellow
  above 2 s. Drama Center rejects these as black bars (code 4) even when the rest of the
  frame is fine, including the 2 px black column of a 1078-wide AI render padded to
  1080. Row fields `edge_dark`, `edge_dark_side`, `edge_dark_at`, `edge_sides`.
- **`package --target tiktok-dc`** (or `show.json` `"target"`; MCP `target`): every
  delivered video, subtitled and clean, gets
  - an **edge lift**: 4 px cropped off each side and scaled back, then a 160 px cosine
    ramp to luma 26 blended with `lighten` (only darker pixels move). Opt out with
    `--no-edge-lift` / `edge_lift=False`.
  - a **1 s cover head**: a still of the episode cover (`NN.jpg`, `cover.jpg`, or a frame
    from the cut) with silent audio, because Drama Center uses frame 0 as the default
    episode cover. Delivered SRTs are shifted by 1 s. Opt out with `--no-cover-head` /
    `cover_head=False`.
- Manifest: `target`, `dc_finish`, per-file `cover_head_s` / `edge_lift`,
  `files.srt.shifted_s`, `episodes[].thumbnail.frame0` (`cover` / `picture`).
- `master.dc_finish()` for finishing a single file from Python.
- Docs: Drama Center section in the delivery-package guide (English and Chinese),
  including a note that its subtitle-area detector can flag compliant subtitles and a
  re-upload often clears it.

## 0.2.1 - 2026-10-27

### Fixed

- VLM visual check: hands or limbs that are motion-blurred, cut off by the frame edge or
  too small to count fingers are now answered "unsure" instead of being flagged as an
  anatomy failure. Found on a real talking-head clip where a gesturing hand at the bottom
  edge was graded red.

## 0.2.0 - 2026-10-27

Local short-drama QC: the audit now covers what cloud QC services check first, free and
without an account. Without `--vlm` there are still no network calls.

### Added

- **Black-frame detection** in `audit` (ffmpeg `blackdetect`, same decode pass as shot
  detection): `black`, `black_segments[]` with head / tail / mid and a level per run.
  Mid-episode black >= 0.5 s is red; head/tail fades up to 1 s are green.
- **Subtitle/speech alignment** (`[speech]` extra): per-cue start offsets, median drift,
  cues with no speech, speech with no cue, and, when the subtitles are in the spoken
  language, likely typos / mismatched lines (normalised edit distance, yellow only).
  Uses `--srt` or the same-name `.srt` next to each file. `transcriber=` is injectable in
  the Python API.
- **Optional vision-model checks**, bring your own key or run a local model (`--vlm`,
  `vlm=True`, `DRAMAPACK_VLM_BASE_URL` / `_API_KEY` / `_MODEL`): visual defects
  (anatomy, garbled on-screen text, artifacts, identity drift), content-policy flags
  (sexual, violence, minors, self-harm) and a first-frame hook check. Any
  OpenAI-compatible Chat Completions endpoint (OpenAI, Anthropic, Gemini, DashScope,
  Volcengine Ark, Ollama, vLLM); standard library only; strict JSON validation, retries,
  key never logged. `--vlm-max-frames` caps frames; the request estimate is printed first.
- CLI: `audit --srt --srt-lang --no-align --vlm --vlm-max-frames`. MCP `audit`: `speech`,
  `align`, `srt`, `srt_lang`, `vlm`, `vlm_max_frames`.
- Docs: [How to QC a short drama locally before delivery](docs/short-drama-qc-local.md)
  (and [Chinese](docs/zh/short-drama-qc-local.md)), with a capability comparison against
  cloud QC services and provider setup.

### Changed

- `audit --cut`: the master is now also graded on black frames, subtitle alignment and VLM
  checks; the cut on black frames as well.
- Speech metrics now share one faster-whisper transcript (with word timestamps) with the
  alignment check.

### Not covered

- Lip-sync. Still frames cannot show it.

## 0.1.0 - 2026-10-27

First release.

- `package`: delivery packs for short-drama platforms (TikTok Drama Center, DramaWave,
  ReelShort): subtitled masters, same-name SRTs, clean masters, 3:4 covers, timeline
  renders + EDL, chain-of-title template, AI disclosure, `manifest.json`.
- `master`: burned subtitles in the safe area (ASS PlayRes pinned to the frame), -14 LUFS
  constant-gain normalisation with a limiter (no `loudnorm`), procedural music beds that
  duck under dialogue, head trim with shifted subtitles, end cards.
- `audit`: green/yellow/red against market benchmarks (duration, shot length, long-shot
  share, dialogue density, loudness, seam jumps, first line, frozen tail).
- `check-rights`: music and font rights hygiene.
- `inspect`: measured specs, integrated loudness, true peak.
- MCP server (`dramapack mcp`), `--json` on every subcommand, stable exit codes.
