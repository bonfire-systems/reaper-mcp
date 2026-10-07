"""Schema checks for registered tools (no REAPER needed)."""

import asyncio

from mcp.client import Client

from reaper_mcp.server import mcp


def _list_tools():
    async def run():
        async with Client(mcp) as client:
            return (await client.list_tools()).tools

    return asyncio.run(run())


def test_none_defaults_accept_null():
    # A parameter that defaults to None advertises "default": null, so its
    # type must also allow null, or a client sending that value explicitly
    # is rejected before the tool runs.
    bad = []
    for tool in _list_tools():
        for name, prop in tool.input_schema.get("properties", {}).items():
            if "default" in prop and prop["default"] is None:
                types = [prop.get("type")] + [b.get("type") for b in prop.get("anyOf", [])]
                if "null" not in types:
                    bad.append(f"{tool.name}.{name}")
    assert bad == []
