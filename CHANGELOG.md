# Changelog

All notable changes to dramapack. Versions follow [Semantic Versioning](https://semver.org/).

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
