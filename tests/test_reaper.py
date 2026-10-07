"""reaper_mcp.reaper without REAPER: the null-pointer test, and connecting
once with an error that says how to enable reapy."""

import pytest
import reapy

from reaper_mcp import reaper


@pytest.mark.parametrize(("pointer", "null"), [
    ("(TrackEnvelope*)0x0000000000000000", True),
    ("(ReaProject*)0x0000000000000000", True),
    ("", True),
    ("(TrackEnvelope*)0x00000001580089F0", False),
    ("(MediaTrack*)0x0000000000000010", False),
])
def test_is_null(pointer, null):
    assert reaper.is_null(pointer) is null


@pytest.fixture
def disconnected(monkeypatch):
    monkeypatch.setattr(reaper, "_connected", False)


def test_connects_once(monkeypatch, disconnected):
    calls = []
    monkeypatch.setattr(reapy, "connect", lambda: calls.append("connect"))
    monkeypatch.setattr(reapy, "Project", lambda: "project")
    assert reaper.get_project() == "project"
    assert reaper.get_project() == "project"
    assert calls == ["connect"]


def test_unreachable_reaper_explains_how_to_enable_reapy(monkeypatch, disconnected):
    def refuse():
        raise ConnectionRefusedError("[Errno 61] Connection refused")

    monkeypatch.setattr(reapy, "connect", refuse)
    with pytest.raises(RuntimeError) as raised:
        reaper.ensure_connected()
    message = str(raised.value)
    assert message.startswith("Cannot connect to REAPER: [Errno 61] Connection refused.")
    assert "scripts/enable_reapy.py" in message
    assert "reapy.config.enable_dist_api()" in message
    assert isinstance(raised.value.__cause__, ConnectionRefusedError)
    assert reaper._connected is False
