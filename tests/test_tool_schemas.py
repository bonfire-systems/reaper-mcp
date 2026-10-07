"""The tool list is the public interface: every client sees each tool's name,
description and input schema. This test pins all three, so any change to them
is a reviewed diff of tests/snapshots/tool_schemas.json rather than a side
effect.

To accept an intended change, regenerate the snapshot and review the diff:

    UPDATE_TOOL_SCHEMAS=1 pytest tests/test_tool_schemas.py
"""

import json
import os
from pathlib import Path

import anyio
import pytest
from mcp.client import Client

from reaper_mcp.server import mcp

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_schemas.json"


async def _list_tools() -> dict:
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    return {
        tool.name: {"description": tool.description, "input_schema": tool.input_schema}
        for tool in sorted(tools, key=lambda t: t.name)
    }


def current_schemas() -> dict:
    return anyio.run(_list_tools)


def test_tool_schemas_match_snapshot():
    current = current_schemas()
    if os.environ.get("UPDATE_TOOL_SCHEMAS"):
        SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    assert current == json.loads(SNAPSHOT.read_text())


@pytest.mark.xfail(strict=True, reason="render_stems.track_indices is `list = None` (see PR #13)")
def test_optional_parameters_accept_null():
    """A parameter defaulting to None must admit null in its schema, or the SDK
    rejects an explicit null before the tool runs."""
    offenders = []
    for name, tool in current_schemas().items():
        for param, schema in tool["input_schema"].get("properties", {}).items():
            if "default" in schema and schema["default"] is None:
                types = [schema.get("type")] + [s.get("type") for s in schema.get("anyOf", [])]
                if "null" not in types:
                    offenders.append(f"{name}.{param}")
    assert offenders == []
