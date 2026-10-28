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
    [--hook-plugin module:function] [--json]

dramapack check-rights [rights.json] [--input DIR] [--bed MOOD] [--music FILE]
    [--subtitle-font NAME] [--end-card] [--no-mastering-fonts] [--allow-font NAME ...] [--json]

dramapack inspect FILE [--json]

dramapack mcp          # MCP server on stdio
```

- `master --cover-band 0.2` blurs the bottom 20% first, for re-subtitling footage that
  already has burned-in subtitles.
- `audit --cut`: the raw cut is graded on pacing / speech / seams, the master only on
  duration, first line, frozen tail and hook. A music bed hides seams and confuses speech
  detection, so grading those on the master gives false reds.
- `audit --hook-plugin` (CLI only, off by default): your function
  `f(path, ffmpeg_exe) -> {"fails": [...], "warns": [...], "note": "..."}`, e.g. a
  vision-model check that the first frame shows a person. dramapack itself needs no model,
  network access or API key.

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
- `audit`: `status`, `rows[]` (metrics + `grades` + `red`), `skipped`, `thresholds`
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

## Environment

| Variable | Effect |
|---|---|
| `DRAMAPACK_FFMPEG` / `DRAMAPACK_FFPROBE` | ffmpeg / ffprobe binaries (default: from `PATH`) |
| `DRAMAPACK_FONTSDIR` | font directory for libass |
| `DRAMAPACK_WHISPER_MODEL` | faster-whisper model for speech metrics (default `base`) |

## Python API

```python
from dramapack import api

api.inspect_file("ep01.mp4")
api.master_episode("cut01.mp4", "ep01.mp4", srt="01.srt", bed="suspense")
api.build_package("input/", "out/", title="My Show", platform_pairs=True)
api.audit_files(["out/episodes/01.mp4"], cut="input/01.mp4", speech=False)
api.check_rights("input/rights.json", input_dir="input/")
```

Lower-level building blocks live in `dramapack.master`, `dramapack.package`,
`dramapack.audit`, `dramapack.rights` and `dramapack.srt`.
