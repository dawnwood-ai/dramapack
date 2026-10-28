# Using dramapack from an AI agent (MCP)

dramapack ships an **MCP server**, so any MCP-capable agent (Claude Code, Claude Desktop,
Cursor, and others) can master episodes, build delivery packages, audit episodes and check
music/font rights by calling tools. Install the package, then register
`dramapack mcp` as a stdio server; for Claude Code that is
`claude mcp add dramapack -- dramapack mcp`. The tools are `inspect`, `master`, `package`,
`audit` and `check_rights`; each returns JSON with `ok` and, where grading applies, a
`status` of green / yellow / red. Agents that prefer shells can use the CLI with `--json`
instead.

## Install and register

```bash
pip install dramapack
claude mcp add dramapack -- dramapack mcp
```

Without installing (uv):

```bash
claude mcp add dramapack -- uvx dramapack mcp
```

Generic MCP client config:

```json
{
  "mcpServers": {
    "dramapack": {"command": "dramapack", "args": ["mcp"]}
  }
}
```

ffmpeg (with libass and libx264) must be on the server's `PATH`, or set
`DRAMAPACK_FFMPEG` / `DRAMAPACK_FFPROBE` in the server's environment.

## Tools

| Tool | Writes files | What it does |
|---|---|---|
| `inspect` | no | duration, resolution, fps, integrated LUFS, true peak, gain to -14 LUFS |
| `master` | yes | one episode: burned subtitles in the safe area, -14 LUFS, optional bed / head trim / end card; `burn=false` for a clean master |
| `package` | yes | full delivery pack from an input folder; returns status, gaps and file paths |
| `audit` | no | green/yellow/red against short-drama benchmarks; pass the raw `cut` with one master |
| `check_rights` | no | music sources, major labels, fonts |

Use **absolute paths**; relative paths resolve against the server's working directory.
`package` runs two encodes per episode and can take minutes for a series.

The audit's `--hook-plugin` (which imports Python by name) is CLI-only on purpose: an
agent-supplied string should never trigger an import.

## Suggested agent workflow

1. `check_rights` with `input_dir` and fix every red item (declare music, swap fonts).
2. `package` the input folder. If `status` is `red`, read `gaps` and the rights summary.
3. `audit` each `episodes/NN.mp4` with `cut` set to the matching input cut.
4. Report the pack path, the manifest path and anything yellow or red to the human. Never
   fill in or sign `docs/CHAIN-OF-TITLE.md`; that is for a person.

## CLI with JSON

```bash
dramapack package input/ out/ --json      # one JSON object on stdout
echo $?                                   # 0 ok, 1 red, 2 usage, 3 failure
```

## Claude Code plugin and skill

This repository is also a Claude Code plugin: `.claude-plugin/plugin.json`, `.mcp.json`
(starts the server via `uvx`) and `skills/dramapack/SKILL.md`, a skill that teaches the
workflow above. The MCP Registry entry is in `server.json`
(`io.github.dawnwood-ai/dramapack`).

See also: [reference.md](reference.md) for the JSON shapes and exit codes.
