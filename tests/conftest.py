import json

import anyio
import pytest
from mcp.client import Client

from reaper_mcp.server import mcp
from tests.fake_reaper import FakeReaper, install


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true",
        help="also run tests marked `live` against a running REAPER; unreachable REAPER fails",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs a running REAPER; selected with --live")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs a running REAPER; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def reaper(monkeypatch, tmp_path) -> FakeReaper:
    """A fake REAPER behind reapy, so the tools run end to end without one."""
    return install(monkeypatch, tmp_path)


async def _call(name: str, arguments: dict) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool(name, arguments)
    assert not result.is_error, result.content
    # Tools are annotated `-> dict`, which the SDK serializes as one JSON text
    # block rather than structured content.
    [block] = result.content
    return json.loads(block.text)


def _call_tool(tool: str, /, **arguments) -> dict:
    # Positional-only, so a tool argument called `name` cannot collide with it.
    return anyio.run(_call, tool, arguments)


@pytest.fixture
def call():
    """call(tool, **arguments) -> the tool's result dict, through the MCP client."""
    return _call_tool
