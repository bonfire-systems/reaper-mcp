"""Characterization tests for project_tools, run end to end against the fake REAPER."""

from reapy import reascript_api

NEW_PROJECT_TAB = 41929


def test_create_project_sets_tempo_and_time_signature(reaper, call):
    reaper.add_track("old")
    result = call("create_project", tempo=90.0, time_signature="7/8")
    assert result["success"] is True
    assert (result["tempo"], result["time_signature"]) == (90.0, "7/8")
    assert reaper.commands == [NEW_PROJECT_TAB]
    assert reaper.tracks == []
    assert reaper.tempo_markers == [[0.0, 90.0, 7, 8]]
    [(old_tracks, *_)] = reaper.background_tabs
    assert [t.name for t in old_tracks] == ["old"]


def test_create_project_without_time_signature(reaper, call):
    reaper.add_track("old")
    result = call("create_project", tempo=100.0, time_signature="", name="Song")
    assert result == {"success": True, "name": "Song", "tempo": 100.0, "time_signature": ""}
    assert reaper.commands == [NEW_PROJECT_TAB]
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


def test_save_project_to_a_path(reaper, call, tmp_path):
    target = tmp_path / "out" / "song.rpp"
    assert call("save_project", project_path=str(target)) == {
        "success": True, "project_path": str(target),
    }
    assert reaper.saved_paths == [str(target)]
    assert target.is_file()


def test_save_project_default_path(reaper, call, monkeypatch):
    monkeypatch.setenv("HOME", str(reaper.tmp))
    result = call("save_project")
    expected = reaper.tmp / "Documents" / "REAPER Projects" / "Test Project.rpp"
    assert result == {"success": True, "project_path": str(expected)}
    assert expected.is_file()


def test_save_project_reports_a_file_reaper_did_not_write(reaper, call, monkeypatch):
    monkeypatch.setattr(reascript_api, "Main_SaveProjectEx", lambda *_: None)
    target = reaper.tmp / "song.rpp"
    result = call("save_project", project_path=str(target))
    assert result == {"success": False, "error": f"REAPER did not write {target}"}


def test_load_project_missing_file(reaper, call, tmp_path):
    path = str(tmp_path / "missing.rpp")
    result = call("load_project", project_path=path)
    assert result == {"success": False, "error": f"File not found: {path}"}
    assert reaper.opened == []


def test_load_project(reaper, call, tmp_path):
    path = tmp_path / "song.rpp"
    path.write_text("<REAPER_PROJECT\n>\n")
    reaper.bpm = 95.0
    reaper.time_signature = (3, 4)
    result = call("load_project", project_path=str(path))
    assert result == {
        "success": True,
        "name": "Test Project",
        "tempo": 95.0,
        "time_signature": "3/4",
        "project_path": str(path),
    }
    assert reaper.opened == [str(path)]


def test_get_project_info_empty(reaper, call):
    reaper.project_path = "/songs"
    reaper.add_track("a")
    result = call("get_project_info")
    assert result == {
        "success": True,
        "name": "Test Project",
        "path": "/songs",
        "tempo": 120.0,
        "time_signature": "4/4",
        "length": 4.0,
        "track_count": 1,
        "markers": [],
        "regions": [],
    }


def test_get_project_info_markers_and_regions(reaper, call):
    reaper.markers = [(1.0, "verse"), (6.0, "")]
    reaper.regions = [(0.5, 4.0, "intro")]
    result = call("get_project_info")
    assert result["markers"] == [
        {"index": 0, "name": "verse", "position": 1.0},
        {"index": 1, "name": "", "position": 6.0},
    ]
    assert result["regions"] == [{"index": 0, "name": "intro", "start": 0.5, "end": 4.0}]


def test_set_tempo(reaper, call):
    assert call("set_tempo", bpm=140.5) == {"success": True, "tempo": 140.5}
    assert reaper.bpm == 140.5


def test_set_time_signature_adds_a_marker_at_the_start(reaper, call):
    assert call("set_time_signature", numerator=6, denominator=8) == {
        "success": True, "time_signature": "6/8",
    }
    assert reaper.tempo_markers == [[0.0, 120.0, 6, 8]]


def test_set_time_signature_edits_the_marker_at_the_start(reaper, call):
    reaper.tempo_markers = [[0.0, 100.0, 4, 4], [8.0, 140.0, 4, 4]]
    reaper.bpm = 100.0
    call("set_time_signature", numerator=3, denominator=4)
    assert reaper.tempo_markers == [[0.0, 100.0, 3, 4], [8.0, 140.0, 4, 4]]


def test_set_time_signature_keeps_a_later_marker(reaper, call):
    reaper.tempo_markers = [[8.0, 140.0, 4, 4]]
    call("set_time_signature", numerator=5, denominator=4)
    assert reaper.tempo_markers == [[0.0, 120.0, 5, 4], [8.0, 140.0, 4, 4]]


def test_set_tempo_edits_the_marker_at_the_start(reaper, call):
    reaper.tempo_markers = [[0.0, 120.0, 3, 4]]
    assert call("set_tempo", bpm=90.0) == {"success": True, "tempo": 90.0}
    assert reaper.tempo_markers == [[0.0, 90.0, 3, 4]]
