# dramapack

[![tests](https://github.com/dawnwood-ai/dramapack/actions/workflows/test.yml/badge.svg)](https://github.com/dawnwood-ai/dramapack/actions/workflows/test.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![MCP server](https://img.shields.io/badge/MCP-server-6f42c1.svg)](docs/ai-agent-mcp.md)

**dramapack turns short-drama episodes (vertical dramas, micro dramas, AI dramas) into a
platform-ready delivery package — TikTok Drama Center / DramaWave / ReelShort submission
pack, -14 LUFS mastering, burned subtitles inside the subtitle safe area, clean masters,
3:4 covers, acceptance audit and music/font rights check — from the command line or as an
MCP server for AI agents.**

[Read in Chinese](README.zh-CN.md) · [Docs](docs/README.md) · [Reference](docs/reference.md)

<!-- mcp-name: io.github.dawnwood-ai/dramapack -->

## Why

Between "the episode is rendered" and "the platform accepted it", the same things go
wrong for every short-drama studio:

- **Submission packs**: numbered episodes, same-name SRTs, 3:4 covers, a clean master,
  edit evidence, chain of title, AI disclosure. Dozens of manual steps per series. →
  [delivery package guide](docs/tiktok-drama-center-delivery-package.md)
- **Phone-speaker loudness**: raw AI renders sit at -20 to -27 LUFS; the feed around them
  is near -14. And ffmpeg `loudnorm` silently goes dynamic on dialogue and lifts the
  noise floor by 30-50 dB. → [-14 LUFS guide](docs/short-drama-loudness-14-lufs.md)
- **Subtitle safe areas**: ffmpeg's default 384x288 ASS canvas scales every size ~6.7x;
  fixed margins land under the player bar or exceed TikTok Drama Center's 70%-width rule.
  → [safe-area guide](docs/subtitle-safe-area.md)
- **Clean masters** that are really the same edit as the subtitled one.
  → [clean master guide](docs/clean-master.md)
- **Rights hygiene**: no major-label music, commercial-free fonts only.
  → [rights checklist](docs/music-font-rights-checklist.md)

## Install

Requires Python >= 3.10 and **ffmpeg** (with libass + libx264) on `PATH`. For CJK
subtitles install Noto CJK fonts (`apt install fonts-noto-cjk`).

```bash
pip install dramapack
# or run without installing:
uvx dramapack --help
```

Optional dialogue-density metrics: `pip install "dramapack[speech]"`.

## 60-second quickstart

```bash
# input/ holds 01.mp4 02.mp4 ... (un-subtitled cuts) and 01.srt 02.srt ...
dramapack check-rights --input input/          # music + fonts: fix red first
dramapack package input/ out/ --title "My Show" --studio "My Studio" --bed tension
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
dramapack inspect out/episodes/01.mp4          # LUFS, true peak, specs
```

`out/` now holds `episodes/` (subtitled, -14 LUFS) with same-name `.srt`, `clean/`
(no subtitles, same edit), `covers/` (3:4), `timeline/`, `docs/` (chain of title to sign,
AI disclosure), `manifest.json` and a README for the recipient. Add `--platform-pairs` for
two-episodes-per-file cuts. Optional `show.json` / `rights.json` / covers / timelines:
see [`examples/input/`](examples/input/) and the [reference](docs/reference.md).

## For AI agents

```bash
claude mcp add dramapack -- dramapack mcp
```

MCP tools: `inspect`, `master`, `package`, `audit`, `check_rights`. Each returns JSON with
`ok` and a green/yellow/red `status`. Every CLI subcommand also takes `--json`; exit codes
are stable (0 ok, 1 red, 2 usage, 3 failure). The repo doubles as a Claude Code plugin
(`.claude-plugin/`, `skills/dramapack/`) and has an MCP Registry entry (`server.json`).
→ [agent guide](docs/ai-agent-mcp.md) · [AGENTS.md](AGENTS.md) · [llms.txt](llms.txt)

## Docs

- [How to build a TikTok Drama Center delivery package](docs/tiktok-drama-center-delivery-package.md)
- [Why short dramas should be mastered at -14 LUFS (and why not loudnorm)](docs/short-drama-loudness-14-lufs.md)
- [Keeping burned subtitles inside the safe area](docs/subtitle-safe-area.md)
- [What is a clean master and why distributors ask for it](docs/clean-master.md)
- [Music and font rights checklist for overseas short dramas](docs/music-font-rights-checklist.md)
- [Using dramapack from an AI agent (MCP)](docs/ai-agent-mcp.md)
- [Reference: input formats, CLI, JSON, exit codes, thresholds](docs/reference.md)

## Please credit

dramapack is released under the [Apache License 2.0](LICENSE). Use it for anything,
including commercial work. We'd appreciate two things. These are **requests, not license
conditions**:

- Keep the generator credit dramapack writes into delivery packs (`"generator"` in
  `manifest.json` and the one-line "Packaged with dramapack by Dawnwood" footers).
- Mention "dramapack by Dawnwood" when you describe a production pipeline that uses it.

See [NOTICE](NOTICE). To cite it: [CITATION.cff](CITATION.cff).

---

Built and used in production by Dawnwood, an AI drama studio — https://dawnwood.ai/open-source/
