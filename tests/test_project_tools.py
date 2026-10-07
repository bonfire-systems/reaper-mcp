"""Characterization tests for project_tools, run end to end against the fake REAPER."""

import anyio

from tests.conftest import _call

NEW_PROJECT = 41929


def call_with_name(tool, **arguments):
    """`call` reserves `name` for the tool name, so tools taking `name` go through here."""
    return anyio.run(_call, tool, arguments)


def test_create_project_default_time_signature_bug(reaper, call):
    reaper.add_track("old")
    result = call("create_project", tempo=90.0)
    # BUG: Project.time_signature is read-only, so every create with a time signature
    # fails after REAPER has already opened a new project and changed the tempo.
    assert result["success"] is False
    assert "has no setter" in result["error"]
    assert reaper.commands == [NEW_PROJECT]
    assert reaper.tracks == []
    assert reaper.bpm == 90.0
    assert reaper.time_signature == (4, 4)


def test_create_project_without_time_signature(reaper):
    reaper.add_track("old")
    result = call_with_name("create_project", tempo=100.0, time_signature="", name="Song")
    assert result == {"success": True, "name": "Song", "tempo": 100.0, "time_signature": ""}
    assert reaper.commands == [NEW_PROJECT]
    assert reaper.tracks == []
    assert reaper.bpm == 100.0


def test_create_project_default_name(reaper, call):
    result = call("create_project", time_signature="")
    assert result["success"] is True
    assert result["name"].startswith("New Project ")
    assert result["tempo"] == 120.0


def test_create_project_malformed_time_signature(reaper, call):
    result = call("create_project", tempo=80.0, time_signature="four")
    assert result["success"] is False
    assert "invalid literal for int()" in result["error"]
    assert reaper.bpm == 80.0


def test_save_project_with_path_bug(reaper, call, tmp_path):
    target = tmp_path / "out" / "song.rpp"
    result = call("save_project", project_path=str(target))
    # BUG: reapy's Project.save takes a force_save_as flag, not a path, so saving never works.
    # The error is REAPER's own traceback, relayed by reapy as a DistError.
    assert result["success"] is False
    assert "An error occurred while running a function inside REAPER" in result["error"]
    assert "'str' object cannot be interpreted as an integer" in result["error"]
    assert target.parent.is_dir()
    assert reaper.saves == []


def test_save_project_default_path_bug(reaper, call, monkeypatch):
    tmp_path = reaper.tmp
    monkeypatch.setenv("HOME", str(tmp_path))
    result = call("save_project")
    # BUG: the default path is built and its folder created, then the save itself fails.
    assert result["success"] is False
    assert "cannot be interpreted as an integer" in result["error"]
    assert (tmp_path / "Documents" / "REAPER Projects").is_dir()
    assert reaper.saves == []


def test_load_project_missing_file(reaper, call, tmp_path):
    path = str(tmp_path / "missing.rpp")
    result = call("load_project", project_path=path)
    assert result == {"success": False, "error": f"File not found: {path}"}
    assert reaper.opened == []


def test_load_project_time_signature_bug(reaper, call, tmp_path):
    path = tmp_path / "song.rpp"
    path.write_text("<REAPER_PROJECT\n>\n")
    reaper.bpm = 95.0
    reaper.time_signature = (3, 4)
    result = call("load_project", project_path=str(path))
    # BUG: time_signature is (bpm, numerator), so a 3/4 project at 95 BPM reports "95.0/3.0".
    assert result == {
        "success": True,
        "name": "Test Project",
        "tempo": 95.0,
        "time_signature": "95.0/3.0",
        "project_path": str(path),
    }
    assert reaper.opened == [str(path)]


def test_get_project_info_empty(reaper, call):
    reaper.project_path = "/songs"
    reaper.add_track("a")
    result = call("get_project_info")
    # BUG: the time signature is reported as "<bpm>/<numerator>", not "4/4".
    assert result == {
        "success": True,
        "name": "Test Project",
        "path": "/songs",
        "tempo": 120.0,
        "time_signature": "120.0/4.0",
        "length": 8.0,
        "track_count": 1,
        "markers": [],
        "regions": [],
    }


def test_get_project_info_markers_and_regions_bug(reaper, call):
    reaper.markers = [1.0, 2.0]
    reaper.regions = [(0.0, 4.0)]
    result = call("get_project_info")
    # BUG: reapy Marker/Region have no name, so the swallowed AttributeError
    # makes every project report no markers and no regions.
    assert result["success"] is True
    assert result["markers"] == []
    assert result["regions"] == []


def test_set_tempo(reaper, call):
    assert call("set_tempo", bpm=140.5) == {"success": True, "tempo": 140.5}
    assert reaper.bpm == 140.5


def test_set_time_signature_bug(reaper, call):
    result = call("set_time_signature", numerator=6, denominator=8)
    # BUG: Project.time_signature is read-only, so the time signature can never be changed.
    assert result["success"] is False
    assert "has no setter" in result["error"]
    assert reaper.time_signature == (4, 4)
