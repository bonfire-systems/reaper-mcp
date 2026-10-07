"""A fake REAPER behind reapy's own surface, for tests that cannot run REAPER.

``install(monkeypatch, tmp_path)`` replaces reapy at its edges:
``reapy.connect``, ``reapy.Project`` and the functions on
``reapy.reascript_api``. Everything above those (tool modules, the server,
the MCP client) runs for real. See objects.py for the fidelity rules.
"""

from pathlib import Path

import pytest
import reapy
from reapy import reascript_api

from tests.fake_reaper.api import RPR_FUNCTIONS, FakeReaper
from tests.fake_reaper.signatures import checked


def install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeReaper:
    fake = FakeReaper(tmp_path)
    monkeypatch.setattr(reapy, "connect", lambda *a, **k: None)
    monkeypatch.setattr(reapy, "Project", lambda *a, **k: fake.project)
    for name in RPR_FUNCTIONS:
        monkeypatch.setattr(reascript_api, name, checked(name, getattr(fake, name)), raising=False)
    return fake


__all__ = ["FakeReaper", "install"]
