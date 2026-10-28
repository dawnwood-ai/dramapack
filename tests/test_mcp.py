"""MCP server: tool surface, in-process calls, and a real stdio round trip.

Works against mcp 1.x (FastMCP, camelCase fields) and 2.x (MCPServer, snake_case)."""
import asyncio
import json
import sys

import pytest

from dramapack.mcp_server import mcp

from conftest import make_clip, needs_ffmpeg

TOOLS = {"inspect", "master", "package", "audit", "check_rights"}


def _get(obj, snake, camel):
    return getattr(obj, snake, None) if hasattr(obj, snake) else getattr(obj, camel, None)


def _payload(res):
    """Tool result → dict, whatever the SDK version returns."""
    if isinstance(res, tuple):                      # mcp 1.x call_tool: (content, structured)
        content, structured = res
        if structured:
            return structured.get("result", structured)
        res = content
    sc = _get(res, "structured_content", "structuredContent") if not isinstance(res, list) else None
    if sc:
        return sc
    content = res if isinstance(res, list) else res.content
    return json.loads(content[0].text)


def test_tools_and_descriptions():
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert len(t.description or "") > 120, f"{t.name}: agents read this — describe it"
        ann = t.annotations
        ro = _get(ann, "read_only_hint", "readOnlyHint")
        assert ro is (t.name in {"inspect", "audit", "check_rights"})
    desc = {t.name: t.description for t in tools}
    assert "-14 LUFS" in desc["master"] and "safe area" in desc["master"]
    assert "clean" in desc["package"] and "manifest.json" in desc["package"]


def test_check_rights_in_process(tmp_path):
    p = tmp_path / "rights.json"
    p.write_text('{"music": [{"cue": "a", "source": "unknown"}]}')
    out = _payload(asyncio.run(mcp.call_tool("check_rights", {"rights": str(p), "subtitle_font": None})))
    assert out["ok"] is True and out["status"] == "red"


@needs_ffmpeg
def test_inspect_and_master_in_process(tmp_path):
    clip = make_clip(tmp_path / "in.mp4", 3.0)
    spec = _payload(asyncio.run(mcp.call_tool("inspect", {"path": clip})))
    assert spec["ok"] and abs(spec["duration_s"] - 3.0) < 0.2 and spec["integrated_lufs"] is not None
    out = str(tmp_path / "out.mp4")
    res = _payload(asyncio.run(mcp.call_tool("master", {"input": clip, "output": out, "bed": "warm"})))
    assert res["output"] == out and res["music_bed"] == "warm"
    after = _payload(asyncio.run(mcp.call_tool("inspect", {"path": out})))
    assert abs(after["integrated_lufs"] - (-14.0)) < 1.5


def test_stdio_round_trip():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "dramapack", "mcp"])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("check_rights", {"subtitle_font": None})
                return names, _payload(res)

    names, out = asyncio.run(asyncio.wait_for(go(), 60))
    assert names == TOOLS
    assert out["status"] == "red"     # no rights.json → music undeclared
