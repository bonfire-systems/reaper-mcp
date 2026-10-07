"""Project tools against a running REAPER."""

import pytest

from tests.live.rpr import RPR

pytestmark = pytest.mark.live


def time_signature_at_start() -> tuple[int, int]:
    _, _, numerator, denominator, _ = RPR.TimeMap_GetTimeSigAtTime(0, 0.0, 0, 0, 0)
    return numerator, denominator


def test_set_time_signature(live_project, call):
    assert call("set_time_signature", numerator=3, denominator=4) == {
        "success": True, "time_signature": "3/4",
    }
    assert time_signature_at_start() == (3, 4)
    assert live_project.bpm == pytest.approx(120.0)
    call("set_time_signature", numerator=6, denominator=8)
    assert time_signature_at_start() == (6, 8)


def seconds_per_four_quarter_notes() -> float:
    return RPR.TimeMap_QNToTime(4.0)


def test_set_tempo_changes_playback_timing(live_project, call):
    assert call("set_tempo", bpm=90.0)["tempo"] == pytest.approx(90.0)
    assert seconds_per_four_quarter_notes() == pytest.approx(4 * 60 / 90)


def test_tempo_still_changes_after_a_time_signature(live_project, call):
    call("set_time_signature", numerator=3, denominator=4)
    assert call("set_tempo", bpm=90.0)["tempo"] == pytest.approx(90.0)
    assert seconds_per_four_quarter_notes() == pytest.approx(4 * 60 / 90)
    marker = RPR.GetTempoTimeSigMarker(0, 0, 0.0, 0, 0.0, 0.0, 0, 0, False)
    assert (marker[6], marker[7], marker[8]) == (pytest.approx(90.0), 3, 4)
    assert time_signature_at_start() == (3, 4)


def test_project_info_reports_signature_markers_and_regions(live_project, call):
    call("set_time_signature", numerator=7, denominator=8)
    live_project.add_marker(1.0, name="verse")
    live_project.add_region(2.0, 4.0, name="chorus")
    info = call("get_project_info")
    assert info["success"] is True, info
    assert info["time_signature"] == "7/8"
    assert info["markers"] == [{"index": 0, "name": "verse", "position": pytest.approx(1.0)}]
    assert info["regions"] == [
        {"index": 0, "name": "chorus", "start": pytest.approx(2.0), "end": pytest.approx(4.0)}
    ]


def test_save_project_writes_the_file(live_project, call, tmp_path):
    target = tmp_path / "nested" / "song.rpp"
    result = call("save_project", project_path=str(target))
    assert result == {"success": True, "project_path": str(target)}
    assert target.is_file()
    assert target.read_text(errors="replace").startswith("<REAPER_PROJECT")


NULL_PROJECT = "(ReaProject*)0x0000000000000000"
NEW_TAB_TEMPLATE = "noprompt:"
CLOSE_TAB = 40860


def open_projects() -> list[str]:
    tabs = (RPR.EnumProjects(i, "", 512)[0] for i in range(64))
    return [p for p in tabs if p != NULL_PROJECT]


def close_current_tab_without_prompt(tmp_path) -> None:
    """A fresh tab is dirty and saving a copy does not clean it; reopening that
    copy with REAPER's noprompt: prefix does, so the tab closes silently."""
    scratch = tmp_path / "scratch.rpp"
    RPR.Main_SaveProjectEx(0, str(scratch), 0)
    RPR.Main_openProject(NEW_TAB_TEMPLATE + str(scratch))
    RPR.Main_OnCommand(CLOSE_TAB, 0)


def test_create_project_opens_a_new_tab_and_keeps_the_current_one(live_project, call, tmp_path):
    live_project.add_track(0, "unsaved work")
    assert RPR.IsProjectDirty(0)
    original = RPR.EnumProjects(-1, "", 512)[0]
    tabs = len(open_projects())
    try:
        result = call("create_project", tempo=95.0, time_signature="7/8", name="Sketch")
        assert result["success"] is True, result
        assert len(open_projects()) == tabs + 1
        assert RPR.EnumProjects(-1, "", 512)[0] != original
        assert RPR.CountTracks(0) == 0
        assert (RPR.Master_GetTempo(), time_signature_at_start()) == (pytest.approx(95.0), (7, 8))
    finally:
        if RPR.EnumProjects(-1, "", 512)[0] != original:
            close_current_tab_without_prompt(tmp_path)
    assert RPR.EnumProjects(-1, "", 512)[0] == original
    assert live_project.tracks[0].name == "unsaved work"
