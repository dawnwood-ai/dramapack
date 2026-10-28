# dramapack reference

Input folder, file schemas, CLI, JSON output and exit codes. For the why behind each
default, see the topic pages in [docs/](README.md).

## Input folder

| File | Required | What it is |
|---|---|---|
| `NN.mp4` (`.mov` / `.m4v` / `.mkv`) | yes | Episode `NN`. By default an **un-subtitled cut**; with `--masters-ready` a finished subtitled master |
| `NN.srt` | recommended | Subtitles for episode `NN` |
| `NN.jpg` / `NN.png` / `NN.cover.jpg` | no | Episode cover (any ratio; cropped to 3:4 from the top). Fallback `cover.jpg`, then a video frame |
| `NN.timeline.json` | no | Edit timeline → rendered timeline PNG + EDL CSV |
| `NN.ui.png` | no | Real screenshot of your editor's timeline (copied to `timeline/ui/`) |
| `NN.cut.mp4` | `--masters-ready` only | Raw cut used to build the clean master |
| `*.ass` | no | Scanned for font names by the rights check |
| `show.json` | no | Series metadata and mastering options |
| `rights.json` | recommended | Music and font declarations |

Episode numbers may be `1.mp4` or `01.mp4`; output is always zero-padded. A complete
example is in [`examples/input/`](../examples/input/).

## `show.json`

```json
{
  "title": "The Last Ferry",
  "studio": "Example Studio",
  "language": "en",
  "tagline": "",
  "production_year": 2026,
  "rights_holder": "",
  "subtitle_font": "Noto Sans CJK SC",
  "music_bed": "tension",
  "music": null,
  "music_db": -6.0,
  "head_trim": 0.0,
  "end_card": {"title": "THE LAST FERRY", "lines": ["EP.{next} TOMORROW"], "site": "example.com", "secs": 4},
  "episodes": {"1": {"title": "Pilot", "head_trim": 0.5}},
  "ai_disclosure": {"imagery": "...", "voice": "...", "music": "...", "human_authored": ["..."]},
  "existing_exploitation": [{"platform": "YouTube (own channel)", "scope": "non-exclusive", "since": "2026-01"}]
}
```

- `music_bed`: `tension`, `warm`, `suspense`, `dread`, `hope`, `true` (= tension) or `null`.
- `music`: your own bed file (relative to the input folder); declare it in `rights.json`
  with a matching `"file"` or the rights check is red.
- `end_card.lines` may use `{num}`, `{next}`, `{title}`. Keep cards around 4 s.
- `episodes` overrides per episode (`title`, `head_trim`, `end_card`).
- `rights_holder` empty → the chain of title keeps a blank to be filled in and signed.

## `NN.timeline.json`

```json
{
  "name": "EP1", "fps": 30, "ratio": "9:16",
  "tracks": {
    "video":   [{"id": "c1", "source": "shot_01.mp4", "in": 0.0, "out": 3.2},
                {"id": "c2", "source": "shot_02.mp4", "in": 0.4, "out": 2.9}],
    "audio":   [{"id": "a1", "source": "dialogue_01.wav", "in": 0.0, "out": 5.7}],
    "overlay": [{"id": "t1", "start": 0.5, "end": 2.0, "text": "Subtitle or title text"}]
  }
}
```

Video and audio clips are laid end to end by `out - in`; overlays use absolute
`start`/`end` seconds. A top-level `media: [{id, src_ref}]` list with `media_id` on clips
is accepted in place of `source`.

## `rights.json`

```json
{
  "music": [
    {"cue": "Main theme", "episodes": ["01", "02"], "source": "licensed",
     "title": "Night Water", "artist": "Indie Artist", "publisher": "Indie Artist",
     "license": "Sync licence, worldwide, perpetual", "proof": "licenses/night-water.pdf",
     "file": "theme.wav"},
    {"cue": "Ep 3 waltz", "source": "public_domain", "title": "Waltz in A minor",
     "year": 1890, "notes": "own performance"},
    {"cue": "Stingers", "source": "generated", "tool": "your AI music tool"},
    {"cue": "Drone", "source": "procedural"}
  ],
  "fonts": [
    {"name": "Noto Sans CJK SC", "license": "OFL-1.1"},
    {"name": "Studio Display", "license": "commercial desktop + video", "proof": "licenses/font.pdf"}
  ],
  "font_allowlist": ["Studio Display"],
  "blocked_publishers": ["Some Catalogue Ltd"]
}
```

| Field | Meaning |
|---|---|
| `music[].source` | `generated` (AI) / `procedural` / `public_domain` / `licensed` / `unknown` |
| `music[].proof` | licence file (relative to rights.json) or URL; required for `licensed` |
| `music[].year` | publication year; required for `public_domain` |
| `music[].publisher` / `label` / `rights_owner` | checked against major-label patterns |
| `music[].file` | audio file name, to match a `--music` / `show.json` `music` bed |
| `fonts[]` | `name`, optional `license`, optional `proof` |
| `font_allowlist` | extra font families to accept (prefix match) |
| `blocked_publishers` | extra publisher/label names to flag red |

Grades are explained in [music-font-rights-checklist.md](music-font-rights-checklist.md).
Use `"music": []` to declare that the episodes contain no music.

## Output pack

```
out/
  episodes/NN.mp4        subtitled master (burned subtitles, -14 LUFS)
  episodes/NN.srt        same-name subtitles (shifted to match any head trim)
  clean/NN.mp4           clean master: same edit, mix and loudness, no subtitles
  covers/NN.jpg          3:4 cover (>= 350x500)
  timeline/NN.png        timeline RENDERED from data (labelled as such) + NN.edl.csv
  timeline/ui/NN.png     your real editor screenshots, when supplied
  platform/...           two-episodes-per-file cuts (--platform-pairs)
  docs/CHAIN-OF-TITLE.md template, left blank to be signed by a person
  docs/AI-DISCLOSURE.md  AI production disclosure (review before sending)
  manifest.json          measured specs of every file, rights check, generator
  README.md              one page for the recipient
```

## CLI

Every subcommand except `mcp` accepts `--json`: stdout then carries exactly one JSON
object (progress goes to stderr).

```
dramapack master IN.mp4 OUT.mp4 [--srt S.srt] [--no-burn] [--bed MOOD | --music FILE]
    [--music-db -6] [--head-trim SECS] [--end-card-title T --end-card-line L ... --end-card-site S]
    [--card-secs 4] [--cover-band FRAC] [--subtitle-font NAME] [--no-normalize] [--json]

dramapack package INPUT_DIR OUTPUT_DIR [--show show.json] [--rights rights.json]
    [--title T] [--studio S] [--language xx] [--bed MOOD] [--music FILE]
    [--masters-ready] [--episodes 1,2,3] [--platform-pairs]
    [--no-clean] [--no-covers] [--no-timeline] [--keep-work] [--strict] [--json]

dramapack audit FILE... [--cut RAW.mp4] [--bounds 3.2,7.9] [--no-speech]
    [--srt S.srt] [--srt-lang xx] [--no-align] [--vlm] [--vlm-max-frames 12]
    [--hook-plugin module:function] [--json]

dramapack check-rights [rights.json] [--input DIR] [--bed MOOD] [--music FILE]
    [--subtitle-font NAME] [--end-card] [--no-mastering-fonts] [--allow-font NAME ...] [--json]

dramapack inspect FILE [--json]

dramapack mcp          # MCP server on stdio
```

- `master --cover-band 0.2` blurs the bottom 20% first, for re-subtitling footage that
  already has burned-in subtitles.
- `audit --cut`: the raw cut is graded on pacing / speech / seams, the master on
  duration, first line, frozen tail, black frames, subtitle alignment, hook and VLM checks
  (black frames are graded on both). A music bed hides seams and confuses speech
  detection, so grading those on the master gives false reds.
- `audit` subtitle alignment (needs the `[speech]` extra): uses `--srt` (single file) or
  the same-name `.srt` next to each file; `--no-align` turns it off, `--no-speech` turns
  off whisper entirely. `--srt-lang` states the subtitle language; the text check runs
  only when it matches the audio (CJK is detected from the script, Latin-script
  translations are recognised by low similarity).
- `audit --vlm`: vision-model checks on sampled frames with your own OpenAI-compatible
  endpoint (`DRAMAPACK_VLM_*` below); without those variables they are skipped with a
  message. `--vlm-max-frames` caps frames per file (default 12). See
  [short-drama-qc-local.md](short-drama-qc-local.md). Lip-sync is not checked.
- `audit --hook-plugin` (CLI only, off by default): your function
  `f(path, ffmpeg_exe) -> {"fails": [...], "warns": [...], "note": "..."}`. Without
  `--vlm` (and its environment) dramapack needs no model, network access or API key.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success, nothing red (yellow findings and non-blocking gaps still exit 0) |
| 1 | completed but red: an audit metric, the rights check, or a blocking package gap; `package --strict` also exits 1 on any gap |
| 2 | usage error (bad arguments) |
| 3 | runtime failure (ffmpeg missing, unreadable input, encode failed); with `--json` prints `{"ok": false, "error": "..."}` |

### JSON shapes

All results have `"ok": true` on success.

- `master`: `output`, `subtitles` (`burned` / `none`), `music_bed`, `music_file`, `spec`, `generator`
- `package`: `status`, `output_dir`, `manifest`, `rights_status`, `rights_summary`, `gaps`,
  `notes`, `episodes[].files.{episode,srt,clean_master,cover,timeline,timeline_ui}` (absolute
  paths), `platform`, `generator`
- `audit`: `status`, `rows[]` (metrics + `grades` + `red`), `skipped`, `thresholds`, and
  `vlm` (`model`, `base_url`, `requests`, `max_frames_per_file`) when VLM checks ran.
  Row detail fields: `black`, `black_segments[]` (`start`, `end`, `dur`, `where`
  head/tail/mid, `level`); `srt`, `sub_drift`, `sub_drift_signed` (+ = subtitles late),
  `sub_offset_p90`, `sub_orphan_share`, `sub_uncovered_s`, `sub_orphans[]`,
  `sub_uncovered[]`, `sub_late_early[]`, `sub_text`, `sub_text_flags[]`, `sub_text_note`;
  `vlm_visual` / `vlm_compliance` / `vlm_hook` (levels), `vlm_*_answers`,
  `vlm_findings[]` (`check`, `item`, `answer`, `level`, `frame`, `t`, `note`),
  `vlm_frames`, `vlm_errors[]`, `vlm_hook_note`
- `check-rights`: `status`, `summary`, `findings[]` (`level`, `kind`, `item`, `message`), `rights_path`
- `inspect`: `path`, `duration_s`, `width`, `height`, `fps`, `audio`, `bytes`,
  `integrated_lufs`, `true_peak_dbtp`, `loudness_range_lu`, `loudness_gain_to_target_db`

## Audit thresholds

| Metric | Green | Red | Why |
|---|---|---|---|
| `dur` | >= 65 s | < 60 s | TikTok Creator Rewards requires > 1 min |
| `asl` | <= 2.0 s | > 3.0 s | live-action platform series run 1.1-1.5 s |
| `long_share` | <= 0.30 | > 0.50 | share of runtime in shots > 4 s |
| `speech_share` | >= 0.80 | < 0.65 | competitors' median 0.90 |
| `wpm` | >= 90 | < 70 | Chinese counted per character x 3/5 |
| `max_gap` | <= 5 s | > 8 s | longest stretch without dialogue |
| `mean_volume` | >= -20 dB | < -23 dB | competitors -16 to -21.5 |
| `seam_db` | <= 6 dB | > 15 dB | level jump at splice points |
| `first_speech` | <= 1.5 s | > 3.0 s | the hook line should land immediately |
| `tail_static` | <= 5 s | > 6.5 s | long static end cards crush completion |
| `black` | no mid-episode black; head/tail <= 1 s | mid-episode black >= 0.5 s | a render gap or failed clip; shorter mid black or longer edge black is yellow |
| `sub_drift` | <= 0.3 s | > 0.8 s | median cue start offset vs speech (head trim not applied to the SRT) |
| `sub_offset_p90` | <= 0.5 s | > 1.0 s | a few badly timed cues |
| `sub_orphan_share` | <= 0.05 | > 0.20 | cues with no speech under them (SFX cues exempt) |
| `sub_uncovered_s` | <= 1.5 s | > 4.0 s | dialogue no cue covers |
| `sub_text` | 0 | never red | cues with line similarity < 0.6 to the heard words, or a word 1-2 letters off the heard word (yellow) |
| `vlm_visual` | no finding | anatomy / garbled text / identity drift | artifacts are yellow |
| `vlm_compliance` | all `none` | any `explicit` | `mild` is yellow; flags, not legal advice |
| `vlm_hook` | person visible, text legible | never red | advice |

## Environment

| Variable | Effect |
|---|---|
| `DRAMAPACK_FFMPEG` / `DRAMAPACK_FFPROBE` | ffmpeg / ffprobe binaries (default: from `PATH`) |
| `DRAMAPACK_FONTSDIR` | font directory for libass |
| `DRAMAPACK_WHISPER_MODEL` | faster-whisper model for speech metrics and alignment (default `base`) |
| `DRAMAPACK_VLM_BASE_URL` | OpenAI-compatible base URL for `audit --vlm` |
| `DRAMAPACK_VLM_API_KEY` | key for that endpoint (any non-empty string for local servers); never logged |
| `DRAMAPACK_VLM_MODEL` | vision-capable model name |
| `DRAMAPACK_VLM_TIMEOUT` / `DRAMAPACK_VLM_RETRIES` | seconds per request (120) / retries on 429, 5xx, network errors (2) |

## Python API

```python
from dramapack import api

api.inspect_file("ep01.mp4")
api.master_episode("cut01.mp4", "ep01.mp4", srt="01.srt", bed="suspense")
api.build_package("input/", "out/", title="My Show", platform_pairs=True)
api.audit_files(["out/episodes/01.mp4"], cut="input/01.mp4", speech=False)
api.audit_files(["ep01.mp4"], srt="ep01.srt", vlm=True, vlm_max_frames=8,
                transcriber=my_asr)   # optional: f(path) -> transcript, see dramapack.align
api.check_rights("input/rights.json", input_dir="input/")
```

Lower-level building blocks live in `dramapack.master`, `dramapack.package`,
`dramapack.audit`, `dramapack.align`, `dramapack.vlm`, `dramapack.rights` and
`dramapack.srt`.
