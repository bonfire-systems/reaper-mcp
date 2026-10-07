"""The console entry point: logging set up from --debug, then the server run
over stdio. The server's run is replaced, so nothing listens."""

import logging
import sys

import pytest

from reaper_mcp import __main__
from reaper_mcp.server import mcp


@pytest.fixture
def runs(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: calls.append(("logging", kwargs)))
    return calls


@pytest.mark.parametrize(("argv", "level"), [([], logging.WARNING), (["--debug"], logging.DEBUG)])
def test_main_configures_logging_and_runs_over_stdio(monkeypatch, runs, argv, level):
    monkeypatch.setattr("sys.argv", ["reaper-mcp-server", *argv])
    __main__.main()
    (tag, config), run = runs
    assert tag == "logging"
    assert config["level"] == level
    assert config["stream"] is sys.stderr  # stdout carries the MCP protocol
    assert "%(levelname)s" in config["format"]
    assert run == {"transport": "stdio"}


def test_main_rejects_unknown_arguments(monkeypatch, runs):
    monkeypatch.setattr("sys.argv", ["reaper-mcp-server", "--nope"])
    with pytest.raises(SystemExit):
        __main__.main()
    assert runs == []
