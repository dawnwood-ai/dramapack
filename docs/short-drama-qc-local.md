# How to QC a short drama locally before delivery

Run `dramapack audit` on every finished episode before you upload it. It checks, on your
own machine and without an account, the things a platform reviewer or a viewer catches
first: **black frames, subtitles that don't match the speech, pacing and loudness against
market benchmarks**, and, if you bring your own vision model, **AI visual defects and
content-policy flags**. Each metric is graded green / yellow / red; red means "a person
should look before this ships".

```bash
pip install "dramapack[speech]"        # speech extra = faster-whisper, for subtitle checks
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
dramapack audit out/episodes/*.mp4 --json > qc.json     # whole series, machine-readable
```

By default nothing leaves your machine: dramapack makes **zero network calls** unless you
pass `--vlm` **and** configure an endpoint (which can itself be a local model).

## What gets checked

| Check | How | Grades |
|---|---|---|
| Black frames | ffmpeg `blackdetect` (runs in the same decode as shot detection) | mid-episode black >= 0.5 s red, shorter mid black yellow; head/tail black <= 1 s green (a fade), longer yellow |
| Subtitle timing | SRT cues vs. whisper speech segments: median start offset (`sub_drift`), 90th-percentile offset (`sub_offset_p90`) | drift green <= 0.3 s, red > 0.8 s; p90 green <= 0.5 s, red > 1.0 s |
| Cue with no speech | `sub_orphan_share` - a line cut from the edit but not the SRT. `[SFX]` / `(music)` cues are exempt | green <= 5% of cues, red > 20% |
| Speech with no cue | `sub_uncovered_s` - seconds of dialogue nobody subtitled | green <= 1.5 s, red > 4 s |
| Subtitle typos / wrong line | per-cue normalised edit distance to the words heard under it, plus word-level near misses (`rihgt` vs `right`), only when the subtitles are in the spoken language | line similarity < 0.6 or a word 1-2 letters off: yellow (ASR mishears names; never red) |
| Pacing, dialogue density, loudness, seams, end card | existing benchmark metrics ([reference](reference.md#audit-thresholds)) | see thresholds |
| Visual defects (optional, `--vlm`) | your vision model on sampled frames: deformed faces / hands / extra limbs, garbled on-screen text, artifacts, identity drift between frames | anatomy / garbled text / identity drift red; artifacts yellow |
| Content policy flags (optional, `--vlm`) | sexual content, graphic violence, minors in unsafe contexts, self-harm | `mild` yellow, `explicit` red. Flags for review, not legal advice |
| First-frame hook (optional, `--vlm`) | is a person visible in frame 0, is any text legible | yellow at most (advice) |

Where the subtitles come from: `--srt FILE`, or a same-name `.srt` next to each video
(`episodes/01.mp4` + `episodes/01.srt`, which is what `dramapack package` writes). With
`--cut`, subtitles, hook and VLM checks run on the master, because that is the picture and
the subtitle timing that get delivered.

**Not covered: lip-sync.** Still frames cannot show whether mouths match the audio, and
dramapack does not claim to check it. Watch dialogue close-ups yourself.

## Local tool vs. cloud QC services

Cloud QC services for short dramas have appeared, for example Kunlun's SkyProduction QC
([launch article, 2026-09](https://www.qbitai.com/2026/09/494043.html)), which checks
subtitles, audio/visual issues and content compliance on uploaded episodes and returns a
report. Both approaches are useful; they differ in where the work happens:

| | dramapack 0.2 (local) | Cloud QC service (e.g. SkyProduction) |
|---|---|---|
| Speech without subtitles / subtitles without speech | yes (`[speech]` extra) | yes |
| Subtitle timing offset | yes | yes |
| Subtitle typos | partial: same-language subtitles only, yellow hints | yes |
| Subtitle format / line-splitting rules | no | yes |
| Black frames | yes | yes |
| Black bars, dropped frames, colour consistency, watermarks | no (end-of-file freeze only) | yes |
| Loudness | yes: -14 LUFS measurement, mean volume, splice-seam jumps | audio checks (volume stability, mono) |
| AI visual defects (hands, faces, identity drift, garbled text) | with your own VLM (`--vlm`) | garbled on-screen text, AI labels |
| Content compliance flags | with your own VLM (`--vlm`) | yes |
| Lip-sync | **no** | see the service's current list |
| Market benchmarks (duration for creator rewards, shot length, dialogue density, end-card length) | yes | not advertised |
| Cost | free (Apache-2.0); VLM calls billed by your provider, or free with a local model | per minute (about CNY 12.4 per 100 min with all checks, per the launch article) |
| Account / upload | none; files stay local (frames go only to the VLM endpoint you configure) | account; upload episodes |
| Automation | CLI `--json`, Python API, MCP server for AI agents | web workflow, downloadable report |

## Bring your own vision model

The VLM checks speak the OpenAI-compatible Chat Completions protocol with images as base64
`data:` URIs, using only the Python standard library. Turn them on per run with `--vlm`
(CLI) or `vlm=True` (Python / MCP), and configure the endpoint in the environment:

```bash
export DRAMAPACK_VLM_BASE_URL=...   # OpenAI-compatible base URL (without /chat/completions)
export DRAMAPACK_VLM_API_KEY=...    # provider key; any non-empty string for local servers
export DRAMAPACK_VLM_MODEL=...      # a vision-capable model
# optional: DRAMAPACK_VLM_TIMEOUT=120 (s per request), DRAMAPACK_VLM_RETRIES=2
dramapack audit ep01.mp4 --vlm --vlm-max-frames 12
```

With `--vlm` but without all three variables, the audit runs normally and lists
`VLM checks skipped: set ...` under `skipped`. The key goes only into the
`Authorization` header of requests to your base URL and is scrubbed from every error and
log line.

Model names change often: pick a current **vision-capable** model from your provider's
model list.

**OpenAI**

```bash
export DRAMAPACK_VLM_BASE_URL=https://api.openai.com/v1
export DRAMAPACK_VLM_API_KEY="$OPENAI_API_KEY"
export DRAMAPACK_VLM_MODEL=<a vision-capable GPT model>
```

**Anthropic (Claude, via its OpenAI SDK compatibility endpoint)**

```bash
export DRAMAPACK_VLM_BASE_URL=https://api.anthropic.com/v1
export DRAMAPACK_VLM_API_KEY="$ANTHROPIC_API_KEY"
export DRAMAPACK_VLM_MODEL=<a Claude model name>
```

Anthropic describes this layer as intended for testing and comparison. Use a key scoped
to a workspace (dramapack sends no extra headers). dramapack sends no `temperature` or
`response_format`, which this endpoint restricts or ignores.

**Google Gemini (OpenAI compatibility)**

```bash
export DRAMAPACK_VLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export DRAMAPACK_VLM_API_KEY="$GEMINI_API_KEY"
export DRAMAPACK_VLM_MODEL=<a Gemini model with image input>
```

**Alibaba Cloud Model Studio / DashScope (Qwen-VL, compatible mode)**

```bash
# International (Singapore):
export DRAMAPACK_VLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# Mainland China (Beijing):
# export DRAMAPACK_VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export DRAMAPACK_VLM_API_KEY="$DASHSCOPE_API_KEY"
export DRAMAPACK_VLM_MODEL=<a Qwen-VL model, e.g. from the qwen3-vl family>
```

A Model Studio key works only in the region it was created in. Newer accounts may be
shown workspace-specific endpoints
(`https://{WorkspaceId}.<region>.maas.aliyuncs.com/compatible-mode/v1`); use what your
console shows.

**Volcengine Ark (Doubao vision)**

```bash
export DRAMAPACK_VLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export DRAMAPACK_VLM_API_KEY="$ARK_API_KEY"
export DRAMAPACK_VLM_MODEL=<Doubao vision model ID, or your endpoint ID ep-...>
```

Check the provider docs for which Doubao models accept image input in your region.

**Ollama (fully offline)**

```bash
ollama pull qwen3-vl:8b
export DRAMAPACK_VLM_BASE_URL=http://localhost:11434/v1
export DRAMAPACK_VLM_API_KEY=ollama          # ignored by Ollama, must be non-empty
export DRAMAPACK_VLM_MODEL=qwen3-vl:8b
```

**vLLM (fully offline)**

```bash
vllm serve <a vision-language model>         # serves http://localhost:8000/v1
export DRAMAPACK_VLM_BASE_URL=http://localhost:8000/v1
export DRAMAPACK_VLM_API_KEY=EMPTY           # or the value of vllm serve --api-key
export DRAMAPACK_VLM_MODEL=<the served model name>
```

### Cost and what is sent

Per episode: frame 0, 6 evenly spaced frames and one frame 0.3 s after each detected cut,
capped at `--vlm-max-frames` (default 12), downscaled to 640 px on the long side
(~40-60 KB JPEG each). Three requests per episode: visual defects and policy flags each see
all sampled frames, the hook check sees frame 0. The audit prints the request and frame
estimate to stderr before it calls the model, and the JSON result carries it under
`vlm`.

### How the vision model is asked to judge

The prompts come from a verifier used in AI-drama production and keep its calibration:

- `yes` needs concrete evidence (which frame, where, what); `unsure` is only for "the part
  is too small, blurred or out of frame". `unsure` never grades red.
- Lighting, angle, expression and makeup changes are not identity drift; a new outfit
  alone does not prove a different person; an over-the-shoulder shoulder is not an extra
  person; motion blur, grain and stylisation are not artifacts; legible signs and correct
  burned subtitles are not garbled text.
- Policy flags judge only what is visible, not imagined story context: a slap is `mild`
  violence, visible wounds or gore are `explicit`.
- Replies must be strict JSON with an allowed answer for every question. A malformed reply
  is re-asked once, then reported under `vlm_errors` and graded nothing: a broken checker
  never blocks delivery and never passes silently.

A vision model can be wrong in both directions. Treat VLM red as "look at this frame",
and keep a human in the loop for policy decisions.

## From an AI agent

The MCP `audit` tool takes `speech`, `align`, `srt`, `srt_lang`, `vlm` and
`vlm_max_frames`. The VLM endpoint and key come only from the MCP server's environment, so
an agent can switch the checks on but cannot point them anywhere else. See
[ai-agent-mcp.md](ai-agent-mcp.md) and the [reference](reference.md).
