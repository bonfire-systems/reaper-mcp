"""Shared test fixtures.

reaper-mcp's modules import `reapy` at module load time, but `reapy` only
works inside a running REAPER process. Tests run outside REAPER, so we
install a lightweight fake `reapy` module in `sys.modules` before any
`reaper_mcp` module is imported, and let individual tests monkeypatch the
pieces they care about (`get_project`, `RPR`, ...).
"""

import sys
import types
from unittest.mock import MagicMock


def _install_fake_reapy() -> None:
    if "reapy" in sys.modules:
        return

    fake_reapy = types.ModuleType("reapy")
    fake_reapy.reascript_api = MagicMock(name="RPR")
    fake_reapy.connect = MagicMock(name="connect")
    fake_reapy.Project = MagicMock(name="Project")
    sys.modules["reapy"] = fake_reapy


_install_fake_reapy()


class FakeMCP:
    """Stand-in for the real `mcp.server.fastmcp.FastMCP` instance.

    `register_tools(mcp)` decorates plain functions with `@mcp.tool()`; this
    fake just records them by name so tests can call the underlying function
    directly, without pulling in the real `mcp` package.
    """

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator
