"""Fixtures for tests that drive a real, running REAPER (selected with --live).

Isolation is by reset, not by a new project: REAPER's "New project" asks
whether to save a dirty project in a modal dialog, which would hang the run.
"""

import sys

import pytest
import reapy
from reapy import reascript_api as RPR

from tests.live.watchdog import Watchdog, guard_reapy

RESET_BPM = 120.0


def _connect() -> reapy.Project:
    try:
        reapy.connect()
        return reapy.Project()
    except Exception as e:  # reapy raises several unrelated types here
        pytest.fail(
            f"--live was given but REAPER is not reachable through reapy: {e}. Start REAPER "
            "with the reapy server enabled (see README, Development)."
        )


def reset(project: reapy.Project) -> None:
    for track in reversed(list(project.tracks)):
        track.delete()
    for marker in list(project.markers):
        marker.delete()
    for region in list(project.regions):
        region.delete()
    master = project.master_track
    for fx in reversed(list(master.fxs)):
        fx.delete()
    for i in reversed(range(RPR.CountTempoTimeSigMarkers(0))):
        RPR.DeleteTempoTimeSigMarker(0, i)
    # Deleting the last marker leaves its time signature as the project's, so
    # write a 4/4 one and delete that.
    RPR.SetTempoTimeSigMarker(0, -1, 0.0, -1, -1, RESET_BPM, 4, 4, False)
    RPR.DeleteTempoTimeSigMarker(0, 0)
    project.bpm = RESET_BPM


@pytest.fixture(scope="session")
def dialog_watchdog():
    """End the run, naming the dialog, if REAPER blocks on one."""
    watchdog = Watchdog()
    if not watchdog.available:
        print("[live watchdog] not guarding: needs macOS System Events", file=sys.__stderr__)
    watchdog.start()
    with pytest.MonkeyPatch.context() as monkeypatch:
        guard_reapy(watchdog, monkeypatch)
        yield watchdog
    watchdog.stop()


@pytest.fixture
def live_project(dialog_watchdog):
    """The running REAPER's current project, emptied before and after the test."""
    project = _connect()
    reset(project)
    yield project
    reset(project)
