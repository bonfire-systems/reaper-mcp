"""render_regions end to end against the fake REAPER, whose RENDER_TARGETS
and region bounds are modelled in fake_reaper/render.py. The helpers are
tested in test_region_render_helpers.py.
"""
import functools

import pytest
from reapy import reascript_api

from reaper_mcp import region_render
from reaper_mcp.reaper import RPR
from reaper_mcp.region_render import _await_render
from tests.fake_reaper import api as fake_api
from tests.helpers import RENDER, WAV_24

REGIONS = [(0.0, 1.0, "intro"), (1.0, 2.5, "verse; take 2"), (2.5, 3.0, "outro")]
SAVED = {"RENDER_FILE": "/saved/dir", "RENDER_PATTERN": "saved", "RENDER_FORMAT": WAV_24,
         "RENDER_BOUNDSFLAG": 1.0, "RENDER_ADDTOPROJ": 1.0}


@pytest.fixture
def regions(reaper, monkeypatch):
    reaper.regions = list(REGIONS)
    reaper.project_info.update(SAVED)
    # Poll fast: the fake renders synchronously, so only stability is awaited.
    monkeypatch.setattr(region_render, "_await_render",
                        functools.partial(_await_render, poll_interval=0.01))
    return reaper


def test_renders_one_file_per_region_and_restores_settings(regions, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path))
    expected = [str(tmp_path / f"{name}.wav") for _, _, name in REGIONS]
    assert result["expected"] == expected  # the ';' in a region name survives
    assert [f["path"] for f in result["files"]] == expected
    assert isinstance(result.pop("elapsed_seconds"), float)
    assert {k: v for k, v in result.items() if k not in ("files", "expected")} == {
        "success": True, "output_directory": str(tmp_path), "total_regions": 3,
        "target_count": 3, "files_written": 3, "status": "complete"}
    assert regions.commands == [RENDER]
    assert regions.project_info == SAVED


def test_dry_run_reports_targets_without_rendering(regions, call, tmp_path):
    out = tmp_path / "not-yet"
    result = call("render_regions", output_directory=str(out), dry_run=True)
    assert [r["name"] for r in result.pop("regions")] == [n for _, _, n in REGIONS]
    assert result == {"success": True, "dry_run": True, "already_exist": [],
                      "output_directory": str(out), "total_regions": 3, "target_count": 3,
                      "would_write": [str(out / f"{n}.wav") for _, _, n in REGIONS]}
    assert not out.exists()  # a dry run leaves the disk alone
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_existing_outputs_are_refused_not_deleted(regions, call, tmp_path):
    stale = tmp_path / "intro.wav"
    stale.write_bytes(b"previous run")
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {
        "success": False, "already_exist": [str(stale)],
        "error": "1 output file(s) already exist; render_regions does not render over "
                 "existing files. Move or delete them, or render into an empty directory."}
    assert stale.read_bytes() == b"previous run"
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_pattern_is_applied(regions, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path), pattern="clip-$region",
                  dry_run=True)
    assert result["would_write"][0] == str(tmp_path / "clip-intro.wav")


def test_no_regions_is_refused(reaper, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {"success": False, "error": "no regions are defined in the current project"}
    assert reaper.commands == []


def test_selected_only_with_nothing_selected_renders_every_region(regions, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path), selected_only=True,
                  dry_run=True)
    assert result["would_write"] == [str(tmp_path / f"{n}.wav") for _, _, n in REGIONS]
    assert regions.project_info == SAVED


def test_duplicate_region_names_get_numbered_files(regions, call, tmp_path):
    # REAPER 7.82 numbers clashing names itself, so every target is distinct
    regions.regions = [(0.0, 1.0, "take"), (1.0, 2.0, "take")]
    result = call("render_regions", output_directory=str(tmp_path), stall_timeout_seconds=1.0)
    expected = [str(tmp_path / "take-001.wav"), str(tmp_path / "take-002.wav")]
    assert result["success"] is True and result["status"] == "complete", result
    assert [f["path"] for f in result["files"]] == expected


def test_duplicate_targets_are_refused(regions, call, tmp_path, monkeypatch):
    # If REAPER ever reports the same path twice, waiting for len(targets)
    # distinct files would never finish; refuse instead of rendering.
    a, b = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    monkeypatch.setattr(fake_api, "render_targets", lambda _: f"{b};{b};{a};{a};")
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {
        "success": False, "duplicates": [a, b],
        "error": "REAPER reported the same output file more than once; "
                 "render_regions cannot tell when such a render is done."}
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_targets_outside_the_directory_are_refused(regions, call, tmp_path, monkeypatch):
    monkeypatch.setattr(fake_api, "render_targets", lambda _: "/elsewhere/a.wav;")
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {"success": False, "error": f"REAPER reported render targets not in "
                                                 f"{tmp_path}: ['/elsewhere/a.wav']"}
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_a_failed_restore_keeps_the_result_and_restores_the_rest(regions, call, tmp_path,
                                                                monkeypatch):
    # The fake is bound into reapy's reascript_api, so wrap it there.
    set_string = RPR.GetSetProjectInfo_String

    def failing(project, desc, value, is_set):
        if is_set and desc == "RENDER_FILE" and regions.commands:
            raise RuntimeError("client disconnected")
        return set_string(project, desc, value, is_set)

    monkeypatch.setattr(reascript_api, "GetSetProjectInfo_String", failing)
    result = call("render_regions", output_directory=str(tmp_path))
    # The files are complete, but the project was left changed, so the call
    # did not do all it claims: success is False, as when REAPER silently
    # skips a send (mixing_tools.create_send).
    assert result["success"] is False and "not restored" in result["error"], result
    assert result["status"] == "complete" and result["files_written"] == 3
    assert result["restore_errors"] == ["RENDER_FILE: client disconnected"]
    assert regions.project_info["RENDER_PATTERN"] == SAVED["RENDER_PATTERN"]
    assert regions.project_info["RENDER_BOUNDSFLAG"] == SAVED["RENDER_BOUNDSFLAG"]


@pytest.mark.parametrize(("selected_only", "bounds"), [(False, 3.0), (True, 5.0)])
def test_selected_only_chooses_the_bounds(regions, call, tmp_path, monkeypatch,
                                          selected_only, bounds):
    # The fake renders every region for both, so read the bounds REAPER is given.
    seen = []
    render_targets = fake_api.render_targets

    def targets(reaper):
        seen.append(reaper.project_info["RENDER_BOUNDSFLAG"])
        return render_targets(reaper)

    monkeypatch.setattr(fake_api, "render_targets", targets)
    call("render_regions", output_directory=str(tmp_path), selected_only=selected_only,
         dry_run=True)
    assert seen == [bounds]


def test_no_render_targets_is_refused(regions, call, tmp_path, monkeypatch):
    monkeypatch.setattr(fake_api, "render_targets", lambda _: "")
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {"success": False, "error": "REAPER reported no render targets"}
    assert regions.commands == []
    assert regions.project_info == SAVED


@pytest.fixture
def renders_first_only(regions, monkeypatch):
    """REAPER writes the first region's file and then stops."""
    render = fake_api.render

    def first_only(reaper):
        paths = render(reaper)
        for path in paths[1:]:
            path.unlink()
        return paths[:1]

    monkeypatch.setattr(fake_api, "render", first_only)
    return regions


def test_an_unfinished_render_reports_what_was_written(renders_first_only, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path), stall_timeout_seconds=0.2)
    assert result["success"] is False and result["status"] == "stalled"
    assert result["error"] == "render did not finish (stalled): wrote 1 of 3 expected files"
    assert result["files_written"] == 1
    assert result["elapsed_seconds"] < 5  # stall_timeout_seconds reached _await_render
    assert renders_first_only.project_info == SAVED


def test_timeout_seconds_bounds_the_wait(renders_first_only, call, tmp_path):
    result = call("render_regions", output_directory=str(tmp_path), stall_timeout_seconds=60.0,
                  timeout_seconds=0.3)
    assert result["status"] == "timeout"
    assert result["error"] == "render did not finish (timeout): wrote 1 of 3 expected files"


def test_restore_failures_are_all_reported_after_an_unfinished_render(
        renders_first_only, call, tmp_path, monkeypatch):
    set_string, set_number = RPR.GetSetProjectInfo_String, RPR.GetSetProjectInfo
    rendered = renders_first_only.commands

    def failing_string(project, desc, value, is_set):
        if is_set and desc == "RENDER_FILE" and rendered:
            raise RuntimeError("client disconnected")
        return set_string(project, desc, value, is_set)

    def failing_number(project, desc, value, is_set):
        if is_set and desc == "RENDER_BOUNDSFLAG" and rendered:
            raise RuntimeError("timed out")
        return set_number(project, desc, value, is_set)

    monkeypatch.setattr(reascript_api, "GetSetProjectInfo_String", failing_string)
    monkeypatch.setattr(reascript_api, "GetSetProjectInfo", failing_number)
    result = call("render_regions", output_directory=str(tmp_path), stall_timeout_seconds=0.2)
    assert result["restore_errors"] == ["RENDER_FILE: client disconnected",
                                        "RENDER_BOUNDSFLAG: timed out"]
    assert result["error"] == (
        "render did not finish (stalled): wrote 1 of 3 expected files; render settings not "
        "restored: RENDER_FILE: client disconnected; RENDER_BOUNDSFLAG: timed out")
    assert renders_first_only.project_info["RENDER_PATTERN"] == SAVED["RENDER_PATTERN"]


def test_add_to_project_is_off_while_rendering(regions, call, tmp_path, monkeypatch):
    # "Add rendered items to the project" would insert one item per region, and
    # its "skip silent files" bit would leave a silent region with no file.
    seen = []
    render = fake_api.render

    def recording(reaper):
        seen.append(reaper.project_info["RENDER_ADDTOPROJ"])
        return render(reaper)

    monkeypatch.setattr(fake_api, "render", recording)
    call("render_regions", output_directory=str(tmp_path))
    assert seen == [0.0]
    assert regions.project_info == SAVED


def test_regions_and_targets_are_counted_apart(regions, call, tmp_path, monkeypatch):
    only = str(tmp_path / "intro.wav")
    monkeypatch.setattr(fake_api, "render_targets", lambda _: f"{only};")
    result = call("render_regions", output_directory=str(tmp_path), dry_run=True)
    assert (result["total_regions"], result["target_count"]) == (3, 1)


def test_the_output_directory_exists_before_rendering(regions, call, tmp_path, monkeypatch):
    out = tmp_path / "new" / "dir"
    render = fake_api.render

    def check(reaper):
        assert out.is_dir()
        return render(reaper)

    monkeypatch.setattr(fake_api, "render", check)
    assert call("render_regions", output_directory=str(out))["success"] is True


def test_relative_and_home_directories_are_resolved(regions, call, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    relative = call("render_regions", output_directory="out", dry_run=True)
    home = call("render_regions", output_directory="~/clips", dry_run=True)
    assert relative["output_directory"] == str(tmp_path / "out")
    assert home["output_directory"] == str(tmp_path / "home" / "clips")


@pytest.mark.parametrize("arguments", [{"stall_timeout_seconds": 0.0},
                                       {"timeout_seconds": 0.0},
                                       {"timeout_seconds": -1.0}])
def test_non_positive_timeouts_are_refused(regions, call, tmp_path, arguments):
    result = call("render_regions", output_directory=str(tmp_path), **arguments)
    assert result == {"success": False, "error": "stall_timeout_seconds and timeout_seconds "
                                                 "must be positive"}
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_restore_failures_survive_an_exception(regions, call, tmp_path, monkeypatch):
    # REAPER disconnecting mid-render raises; the settings it could not put
    # back are still named.
    set_string = RPR.GetSetProjectInfo_String

    def failing(project, desc, value, is_set):
        if is_set and desc == "RENDER_FILE" and regions.commands:
            raise RuntimeError("client disconnected")
        return set_string(project, desc, value, is_set)

    def disconnect(reaper):
        reaper.commands.append(RENDER)
        raise RuntimeError("connection lost")

    monkeypatch.setattr(reascript_api, "GetSetProjectInfo_String", failing)
    monkeypatch.setattr(fake_api, "render", disconnect)
    result = call("render_regions", output_directory=str(tmp_path))
    assert result == {"success": False, "error": "connection lost; render settings not "
                                                 "restored: RENDER_FILE: client disconnected"}


def test_a_restore_failure_after_a_refusal_reads_as_one_message(regions, call, tmp_path,
                                                                 monkeypatch):
    same = str(tmp_path / "same.wav")
    set_string = RPR.GetSetProjectInfo_String

    def failing(project, desc, value, is_set):
        if is_set and desc == "RENDER_FILE" and value == SAVED["RENDER_FILE"]:
            raise RuntimeError("client disconnected")
        return set_string(project, desc, value, is_set)

    monkeypatch.setattr(fake_api, "render_targets", lambda _: f"{same};{same};")
    monkeypatch.setattr(reascript_api, "GetSetProjectInfo_String", failing)
    result = call("render_regions", output_directory=str(tmp_path))
    assert result["error"] == (
        "REAPER reported the same output file more than once; render_regions cannot tell "
        "when such a render is done; render settings not restored: RENDER_FILE: client "
        "disconnected")
