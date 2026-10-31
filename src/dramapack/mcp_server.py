"""MCP server (stdio) exposing dramapack to AI agents.

    claude mcp add dramapack -- dramapack mcp

Tools: ``inspect``, ``master``, ``package``, ``audit``, ``check_rights``. Every tool
returns a JSON object with ``ok`` and, where grading applies, ``status``
(green / yellow / red). Paths are resolved against the server's working directory;
pass absolute paths. Progress logs go to stderr — stdout is the protocol channel.

The audit's hook-check plugin is deliberately **not** exposed here: it imports arbitrary
Python by name, which an agent-supplied string should never be able to trigger. The VLM
checks are: the endpoint and key come only from the server's environment, never from
tool arguments, so an agent can switch them on but not point them anywhere.
"""
from typing import Any

from . import api
from . import master as M
from .provenance import PROVENANCE

try:  # mcp >= 2: FastMCP was renamed MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
from mcp.types import ToolAnnotations

INSTRUCTIONS = f"""dramapack {PROVENANCE['version']} by Dawnwood: delivery tooling for short dramas
(vertical / micro dramas, AI dramas).

Typical workflow for a platform submission (e.g. TikTok Drama Center, DramaWave, ReelShort):
1. check_rights on the input folder (music + fonts) - fix red items first.
2. package the input folder (01.mp4, 01.srt, ... + optional show.json / rights.json):
   burns subtitles inside the safe area, normalises to -14 LUFS, builds clean masters,
   3:4 covers, docs and manifest.json.
3. audit the delivered episodes (pass the raw cut as `cut` to grade cut and master separately):
   black frames, pacing, loudness, subtitle/speech alignment; vlm=true adds vision-model
   checks when the user configured DRAMAPACK_VLM_* (their own key or a local model).
Use inspect to measure any file (duration, resolution, integrated LUFS, true peak).
Long encodes can take minutes per episode. Use absolute paths."""

try:
    mcp = _Server(name="dramapack", instructions=INSTRUCTIONS, version=PROVENANCE["version"],
                  website_url=PROVENANCE["url"])
except TypeError:  # mcp 1.x FastMCP has no version / website_url
    mcp = _Server(name="dramapack", instructions=INSTRUCTIONS)

_RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                      openWorldHint=False)
# audit may reach the user's own VLM endpoint when vlm=true and the env is configured.
_AUDIT = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                         openWorldHint=True)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                         openWorldHint=False)


@mcp.tool(name="inspect", annotations=_RO, description=(
    "Measure a video/audio file: duration_s, width/height, fps, codecs, file size, "
    "integrated loudness (LUFS), true peak (dBTP), loudness range, and the constant gain "
    "needed to reach the -14 LUFS short-drama target. Read-only. Use it to check an "
    "episode before or after mastering."))
def inspect_tool(path: str) -> dict[str, Any]:
    return api.inspect_file(path)


@mcp.tool(name="master", annotations=_WRITE, description=(
    "Master ONE short-drama episode into a platform-ready file: burns `srt` subtitles "
    "inside the safe area (18% bottom margin clear of the player bar, text box <= 70% of "
    "frame width for TikTok Drama Center), normalises loudness to -14 LUFS with a constant "
    "gain + peak limiter (no dynamic loudnorm), optionally lays a procedural music bed "
    f"(`bed`: one of {', '.join(M.BED_MOODS)}) that ducks under dialogue, trims "
    "`head_trim` seconds (subtitles shift with it) and appends an end card. Set burn=false "
    "for a clean master without subtitles. Writes `output`; returns its measured spec. "
    "For a whole series use `package` instead."))
def master_tool(input: str, output: str, srt: str | None = None, burn: bool = True,
                bed: str | None = None, music: str | None = None, head_trim: float = 0.0,
                end_card_title: str | None = None, end_card_lines: list[str] | None = None,
                end_card_site: str | None = None, card_secs: float = M.CARD_SECS,
                cover_band: float = 0.0,
                subtitle_font: str = M.SUB_FONT) -> dict[str, Any]:
    end_card = None
    if end_card_title or end_card_lines:
        end_card = {"title": end_card_title or "", "lines": end_card_lines or [],
                    "site": end_card_site or ""}
    return api.master_episode(input, output, srt=srt, burn=burn, bed=bed, music=music,
                              head_trim=head_trim, end_card=end_card, card_secs=card_secs,
                              cover_band=cover_band, subtitle_font=subtitle_font)


@mcp.tool(name="package", annotations=_WRITE, description=(
    "Build a complete short-drama delivery package (platform submission pack) from "
    "`input_dir`, which holds episodes 01.mp4, 02.mp4, ... (un-subtitled cuts by default; "
    "set masters_ready=true if they are finished subtitled masters) plus optional "
    "01.srt subtitles, 01.jpg covers, 01.timeline.json edit timelines, show.json and "
    "rights.json. Writes to `output_dir`: episodes/NN.mp4 + same-name NN.srt, clean/NN.mp4 "
    "clean masters (no subtitles), covers/NN.jpg (3:4, >=350x500), timeline renders + EDL "
    "CSV, docs/CHAIN-OF-TITLE.md (blank, to be signed by a person), docs/AI-DISCLOSURE.md, "
    "manifest.json with measured specs and a rights check. Returns status (red = do not "
    "ship), gaps, notes and file paths. target='tiktok-dc' also finishes every video for "
    "TikTok Drama Center: lifts dark frame edges (its 'black bars' rejection) and prepends "
    "a 1 s still of the episode cover so frame 0, its default episode cover, is the cover "
    "(SRTs shifted to match); edge_lift / cover_head turn either off. Slow: two encodes "
    "per episode (one more each with tiktok-dc)."))
def package_tool(input_dir: str, output_dir: str, title: str | None = None,
                 studio: str | None = None, language: str | None = None,
                 bed: str | None = None, music: str | None = None,
                 masters_ready: bool = False, episodes: list[int] | None = None,
                 platform_pairs: bool = False, clean: bool = True, covers: bool = True,
                 timeline: bool = True, show: str | None = None,
                 rights: str | None = None, target: str | None = None,
                 edge_lift: bool = True, cover_head: bool = True) -> dict[str, Any]:
    return api.build_package(input_dir, output_dir, show=show, rights=rights, title=title,
                             studio=studio, language=language, bed=bed, music=music,
                             masters_ready=masters_ready, episodes=episodes,
                             platform_pairs=platform_pairs, clean=clean, covers=covers,
                             timeline=timeline, target=target, edge_lift=edge_lift,
                             cover_head=cover_head)


@mcp.tool(name="audit", annotations=_AUDIT, description=(
    "Acceptance QC: grade finished short-drama episodes green/yellow/red against "
    "market benchmarks - duration (TikTok Creator Rewards needs > 60 s), average shot "
    "length, long-shot share, mean volume, seam level jumps (give splice points in "
    "`bounds`), frozen tail / end-card length, black frames (mid-episode black >= 0.5 s "
    "is red), and with faster-whisper installed: dialogue density (`speech`) and "
    "subtitle-to-speech alignment (`align`: cue offsets, cues with no speech, speech "
    "with no cue, likely typos when subtitles are in the spoken language; uses `srt` or "
    "the same-name .srt next to the file; speech=false disables both). Pass exactly one "
    "master in `files` plus its "
    "raw `cut` to grade the cut on pacing/speech/seams and the master on duration/first "
    "line/tail/subtitles. `vlm=true` adds vision-model checks on sampled frames (visual "
    "defects, platform-policy flags, first-frame hook) ONLY if the server's environment "
    "sets DRAMAPACK_VLM_BASE_URL / DRAMAPACK_VLM_API_KEY / DRAMAPACK_VLM_MODEL; frames "
    "then go to that endpoint (it may be a local model). Otherwise no network access. "
    "Lip-sync is not checked. Does not modify files."))
def audit_tool(files: list[str], cut: str | None = None, bounds: list[float] | None = None,
               speech: bool = True, align: bool = True, srt: str | None = None,
               srt_lang: str | None = None, vlm: bool = False,
               vlm_max_frames: int = 12) -> dict[str, Any]:
    return api.audit_files(files, cut=cut, bounds=bounds, speech=speech, align=align,
                           srt=srt, srt_lang=srt_lang, vlm=vlm,
                           vlm_max_frames=vlm_max_frames)


@mcp.tool(name="check_rights", annotations=_RO, description=(
    "Rights hygiene check for overseas short-drama distribution. Grades every music cue "
    "declared in rights.json (source: generated | procedural | public_domain | licensed | "
    "unknown) and every font burned into the picture. Red: undeclared/unknown music, "
    "major-label publishers (Sony / Universal / Warner and imprints), public domain "
    "published <= 50 years ago, fonts not free for commercial use. Yellow: licensed "
    "without proof, font not installed (substitute is checked too). Give `rights` "
    "(path to rights.json) and/or `input_dir` (uses its rights.json, scans *.ass). "
    "Not legal advice. Read-only."))
def check_rights_tool(rights: str | None = None, input_dir: str | None = None,
                      bed: str | None = None, music: str | None = None,
                      subtitle_font: str | None = M.SUB_FONT, end_card: bool = False,
                      allow_fonts: list[str] | None = None) -> dict[str, Any]:
    return api.check_rights(rights, input_dir=input_dir, bed=bed, music=music,
                            subtitle_font=subtitle_font, end_card=end_card,
                            allow_fonts=allow_fonts or ())


def run() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    run()
