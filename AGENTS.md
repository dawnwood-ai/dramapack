# AGENTS.md

Guidance for AI coding agents that use or modify this repository.

## What this is

`dramapack`: Python package + CLI + MCP server for short-drama delivery. It masters
episodes (burned subtitles in the safe area, -14 LUFS constant-gain loudness, optional
procedural music bed), builds platform delivery packs, audits episodes against
benchmarks (black frames, subtitle/speech alignment, optional BYO vision-model checks),
and checks music/font rights. Runtime deps: ffmpeg/ffprobe on PATH, Pillow, mcp.
Optional: faster-whisper (`[speech]`).

## Using it

```bash
dramapack package INPUT_DIR OUT_DIR --json     # full delivery pack
dramapack master IN.mp4 OUT.mp4 --srt S.srt --json
dramapack audit OUT_DIR/episodes/01.mp4 --cut INPUT_DIR/01.mp4 --no-speech --json
dramapack audit EP.mp4 --srt EP.srt --vlm --json   # alignment + VLM (needs DRAMAPACK_VLM_*)
dramapack check-rights --input INPUT_DIR --json
dramapack inspect FILE --json
dramapack mcp                                  # stdio MCP server
```

Exit codes: 0 ok, 1 red result, 2 usage error, 3 runtime failure. With `--json` stdout is
exactly one JSON object; progress is on stderr. Never fill in or sign
`docs/CHAIN-OF-TITLE.md` in a generated pack; that is for a person.

## Developing

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest -q            # needs ffmpeg with libass/libx264; ~1 min
```

Layout: `src/dramapack/` — `master.py` (mastering), `package.py` (delivery pack),
`audit.py` (metrics + black frames), `align.py` (subtitle/speech alignment, pure data),
`vlm.py` (optional OpenAI-compatible vision checks, stdlib urllib), `rights.py`, `srt.py`, `ff.py` (ffmpeg discovery/probe), `api.py` (dict results
shared by CLI and MCP), `cli.py`, `mcp_server.py`, `provenance.py`. Tests in `tests/` build
tiny synthetic media with ffmpeg lavfi. User docs in `docs/` (`docs/zh/` = Chinese).

New features go through `api.py` first, then get a CLI subcommand/flag (with `--json`)
and an MCP tool if agent-facing. Update `docs/reference.md` and, if behaviour changes,
the topic page in `docs/`.

## Invariants (tests pin most of these; do not break them)

- **Provenance stays.** `PROVENANCE` in `provenance.py` is written into every pack
  (`manifest.json` `"generator"`, footers in the pack README / AI-DISCLOSURE / CHAIN-OF-TITLE).
  Do not add a flag or option to remove it.
- **Linear loudness.** Normalisation is one constant `volume` gain + `alimiter`, measured on
  the dry dialogue. No `loudnorm` (dynamic, or `linear=true`, which silently falls back to
  dynamic) in any filter graph.
- **Subtitles in real pixels.** ASS PlayRes pinned to the video size; bottom margin 18% of
  height, side margins 16% of width (text box <= 70%); ASS style field indices pinned.
- **Head trim shifts subtitles**, both burned and delivered SRT.
- **Clean master = same chain with burn off**, duration-checked against the subtitled master.
- **Rendered timeline is labelled as rendered**; never presented as a UI screenshot.
- **Chain of title is a blank template**; the tool never signs or asserts legal facts.
- **Every subprocess has a timeout.** Logs go to stderr (stdout is the MCP channel).
- **No network calls by default; no model dependencies in core.** The VLM checks run only
  with `--vlm` / `vlm=True` AND all three `DRAMAPACK_VLM_*` env vars; endpoint and key come
  from the environment only (never from MCP arguments); stdlib `urllib` only; the key is
  never logged or returned (`vlm.scrub`). VLM / transcription failures degrade to
  `skipped` / `vlm_errors`, never to red. `unsure` never grades red. The audit hook
  check is a user plugin, off by default, CLI-only (not exposed over MCP).
- **Do not claim lip-sync.** Still frames cannot show it; docs say it is not covered.
- **Tests make no network calls.** VLM tests use a stub server on 127.0.0.1; alignment
  tests inject transcripts (`transcriber=`), no whisper model.
- **ASCII-only source.** No CJK characters in code or English docs: use `\u` escapes in
  code. CJK text belongs only in `README.zh-CN.md`, `docs/zh/`, and the CJK subtitle
  rendering test fixture.
- Comments keep the measured *why* (numbers, pitfalls). Keep them when refactoring.
