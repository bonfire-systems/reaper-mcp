"""render_regions: its pure helpers, and the tool end to end against the fake
REAPER, whose RENDER_TARGETS and region bounds are modelled in
fake_reaper/render.py. The helper tests come from PR #7; they cover
the parsing and filesystem polling that need no DAW.
"""
import functools
import threading
import time

import pytest
from reapy import reascript_api

from reaper_mcp import render_tools
from reaper_mcp.reaper import RPR
from reaper_mcp.render_tools import (
    _await_render,
    _conflicting_targets,
    _parse_render_targets,
)
from tests.fake_reaper import api as fake_api
from tests.helpers import RENDER, WAV_24


class TestParseRenderTargets:
    def test_splits_on_semicolons(self):
        raw = "/out/a.mp4;/out/b.mp4;/out/c.mp4"
        assert _parse_render_targets(raw, "/out") == ["/out/a.mp4", "/out/b.mp4", "/out/c.mp4"]

    def test_tolerates_trailing_semicolon(self):
        # REAPER 7.75 ends RENDER_TARGETS with a separator
        assert _parse_render_targets("/out/a.mp4;/out/b.mp4;", "/out") == [
            "/out/a.mp4", "/out/b.mp4"]

    def test_region_name_containing_a_semicolon_survives(self):
        # the reason this function exists rather than a plain str.split(";")
        raw = "/out/intro; the reprise.mp4;/out/outro.mp4"
        assert _parse_render_targets(raw, "/out") == [
            "/out/intro; the reprise.mp4", "/out/outro.mp4"]

    def test_directory_given_with_a_trailing_separator(self):
        assert _parse_render_targets("/out/a.mp4;/out/b.mp4;", "/out/") == [
            "/out/a.mp4", "/out/b.mp4"]

    def test_single_target(self):
        assert _parse_render_targets("/out/only.mp4", "/out") == ["/out/only.mp4"]

    def test_empty_and_blank(self):
        assert _parse_render_targets("", "/out") == []
        assert _parse_render_targets("   ", "/out") == []
        assert _parse_render_targets(None, "/out") == []

    def test_target_outside_the_directory_is_rejected(self):
        # REAPER spelling the directory differently would otherwise turn the
        # whole string into one bogus target
        with pytest.raises(RuntimeError, match="not in /out"):
            _parse_render_targets("/elsewhere/a.mp4;/elsewhere/b.mp4;", "/out")

    def test_directory_prefix_must_end_at_a_separator(self):
        with pytest.raises(RuntimeError, match="not in /out"):
            _parse_render_targets("/outer/a.mp4;", "/out")


FAST = {"poll_interval": 0.02, "timeout": 5.0}


class TestAwaitRender:
    """Completion and stall detection. Filesystem and clock only - no REAPER."""

    def test_completes_when_every_target_is_present(self, tmp_path):
        targets = [str(tmp_path / f"{i}.mp4") for i in range(3)]
        for target in targets:
            with open(target, "wb") as handle:
                handle.write(b"x" * 32)
        written, status = _await_render(targets, stall_timeout=2.0, **FAST)
        assert status == "complete"
        assert len(written) == 3
        assert all(f["size_bytes"] == 32 for f in written)

    def test_stalls_when_a_target_never_appears(self, tmp_path):
        # a render that dies partway leaves some files and then stops writing
        targets = [str(tmp_path / "done.mp4"), str(tmp_path / "never.mp4")]
        with open(targets[0], "wb") as handle:
            handle.write(b"x" * 32)
        started = time.time()
        written, status = _await_render(targets, stall_timeout=0.3, **FAST)
        assert status == "stalled"
        assert len(written) == 1          # partial progress is still reported
        assert time.time() - started < 3.0  # gave up early, did not run to timeout

    def test_a_one_byte_target_is_finished(self, tmp_path):
        target = tmp_path / "tiny.mp4"
        target.write_bytes(b"x")
        _, status = _await_render([str(target)], stall_timeout=2.0, **FAST)
        assert status == "complete"

    def test_present_targets_without_scratch_get_no_grace(self, tmp_path):
        # every target exists but none is growing and no scratch file is open:
        # the plain stall_timeout applies, not scratch_grace
        target = tmp_path / "out.mp4"
        target.write_bytes(b"")
        _, status = _await_render([str(target)], stall_timeout=0.2, scratch_grace=30.0,
                                  timeout=5.0, poll_interval=0.02)
        assert status == "stalled"

    def test_stalls_on_a_zero_byte_target(self, tmp_path):
        # a target that exists with 0 bytes is not finished
        target = str(tmp_path / "empty.mp4")
        with open(target, "wb"):
            pass
        _, status = _await_render([target], stall_timeout=0.3, **FAST)
        assert status == "stalled"

    def test_growing_scratch_file_prevents_a_premature_stall(self, tmp_path):
        # growth of a .sb- file counts as progress, so a long render that writes
        # there before its final file appears is not cut off
        target = tmp_path / "out.mp4"
        scratch = tmp_path / "out.mp4.sb-deadbeef"

        def render():
            deadline = time.time() + 1.0      # keep busy well past stall_timeout
            while time.time() < deadline:
                with open(scratch, "ab") as handle:
                    handle.write(b"x" * 4096)
                time.sleep(0.02)
            scratch.unlink()
            with open(target, "wb") as handle:
                handle.write(b"y" * 128)

        worker = threading.Thread(target=render)
        worker.start()
        try:
            written, status = _await_render([str(target)], stall_timeout=0.3, **FAST)
        finally:
            worker.join()
        assert status == "complete"
        assert len(written) == 1

    def test_reports_timeout_separately_from_stall(self, tmp_path):
        target = str(tmp_path / "never.mp4")
        written, status = _await_render(
            [target], stall_timeout=60.0, timeout=0.2, poll_interval=0.02)
        assert status == "timeout"
        assert written == []

    def test_no_targets_is_trivially_complete(self):
        assert _await_render([]) == ([], "complete")

    def test_open_scratch_file_defers_the_stall(self, tmp_path):
        # a .sb- file is treated as an open render; giving up would restore the
        # project's render settings underneath it
        scratch = tmp_path / "out.mp4.sb-deadbeef"
        with open(scratch, "wb") as handle:
            handle.write(b"x" * 64)
        target = str(tmp_path / "out.mp4")
        started = time.time()
        _, status = _await_render([target], stall_timeout=0.2, scratch_grace=30.0,
                                  timeout=1.0, poll_interval=0.02)
        # ran to the hard timeout instead of stalling at 0.2s
        assert status == "timeout"
        assert time.time() - started >= 0.9

    def test_other_files_in_the_directory_do_not_count_as_progress(self, tmp_path):
        # a busy output folder must not stretch a dead render to the timeout
        other = tmp_path / "unrelated.log"
        stop = threading.Event()

        def busy():
            while not stop.is_set():
                with open(other, "ab") as handle:
                    handle.write(b"x" * 64)
                time.sleep(0.02)

        worker = threading.Thread(target=busy)
        worker.start()
        started = time.time()
        try:
            _, status = _await_render([str(tmp_path / "never.mp4")], stall_timeout=0.3,
                                      poll_interval=0.02, timeout=10.0)
        finally:
            stop.set()
            worker.join()
        assert status == "stalled"
        assert time.time() - started < 2.0

    def test_scratch_file_of_another_name_does_not_defer_the_stall(self, tmp_path):
        # only a target's own scratch file stands for a render in progress
        (tmp_path / "foo.sb-old").write_bytes(b"x" * 64)
        started = time.time()
        _, status = _await_render([str(tmp_path / "out.mp4")], stall_timeout=0.2,
                                  scratch_grace=30.0, timeout=10.0, poll_interval=0.02)
        assert status == "stalled"
        assert time.time() - started < 2.0

    def test_scratch_file_named_after_the_stem_defers_the_stall(self, tmp_path):
        # the scratch name was seen as <name>.sb-<hash> on macOS; whether <name>
        # keeps the extension is unconfirmed, so both spellings count
        (tmp_path / "out.sb-deadbeef").write_bytes(b"x" * 64)
        _, status = _await_render([str(tmp_path / "out.mp4")], stall_timeout=0.2,
                                  scratch_grace=30.0, timeout=1.0, poll_interval=0.02)
        assert status == "timeout"

    def test_orphaned_scratch_file_still_stalls_eventually(self, tmp_path):
        # ...but a dead render that left a scratch behind must not hang forever
        scratch = tmp_path / "out.mp4.sb-deadbeef"
        with open(scratch, "wb") as handle:
            handle.write(b"x" * 64)
        target = str(tmp_path / "out.mp4")
        started = time.time()
        _, status = _await_render([target], stall_timeout=0.2, scratch_grace=0.6,
                                  timeout=30.0, poll_interval=0.02)
        assert status == "stalled"
        assert time.time() - started < 5.0


    def test_a_growing_target_counts_as_progress(self, tmp_path):
        # REAPER 7.82 on Linux writes the target directly, with no scratch file
        target = tmp_path / "out.mp4"
        worker = threading.Thread(target=_grow, args=(target, 1.0))
        worker.start()
        try:
            _, status = _await_render([str(target)], stall_timeout=0.3, **FAST)
        finally:
            worker.join()
        assert status == "complete"

    def test_targets_in_several_directories_are_all_watched(self, tmp_path):
        # pattern="$region/mix" renders out/intro/mix.wav, out/outro/mix.wav
        first, second = tmp_path / "intro" / "mix.wav", tmp_path / "outro" / "mix.wav"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"x" * 32)
        worker = threading.Thread(target=_grow, args=(second, 1.0))
        worker.start()
        try:
            written, status = _await_render([str(first), str(second)], stall_timeout=0.3,
                                            **FAST)
        finally:
            worker.join()
        assert status == "complete" and len(written) == 2

    def test_a_directory_that_does_not_exist_yet_stalls(self, tmp_path):
        _, status = _await_render([str(tmp_path / "later" / "out.mp4")], stall_timeout=0.2,
                                  **FAST)
        assert status == "stalled"


def _grow(path, seconds: float) -> None:
    """Append to path for `seconds`, as a render writing its output does."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        with open(path, "ab") as handle:
            handle.write(b"x" * 4096)
        time.sleep(0.02)


class TestConflictingTargets:
    """Targets that already exist are reported, in target order."""

    def test_none_when_directory_is_empty(self, tmp_path):
        targets = [str(tmp_path / f"{i}.mp4") for i in range(3)]
        assert _conflicting_targets(targets) == []

    def test_reports_only_the_files_that_exist(self, tmp_path):
        targets = [str(tmp_path / f"{i}.mp4") for i in range(3)]
        for i in (0, 2):
            with open(targets[i], "wb") as handle:
                handle.write(b"x")
        assert _conflicting_targets(targets) == [targets[0], targets[2]]

    def test_preserves_target_order(self, tmp_path):
        targets = [str(tmp_path / n) for n in ("c.mp4", "a.mp4", "b.mp4")]
        for t in targets:
            with open(t, "wb") as handle:
                handle.write(b"x")
        assert _conflicting_targets(targets) == targets


# ---------------------------------------------------------------------------
# The tool, against the fake REAPER
# ---------------------------------------------------------------------------

REGIONS = [(0.0, 1.0, "intro"), (1.0, 2.5, "verse; take 2"), (2.5, 3.0, "outro")]
SAVED = {"RENDER_FILE": "/saved/dir", "RENDER_PATTERN": "saved", "RENDER_FORMAT": WAV_24,
         "RENDER_BOUNDSFLAG": 1.0, "RENDER_ADDTOPROJ": 1.0}


@pytest.fixture
def regions(reaper, monkeypatch):
    reaper.regions = list(REGIONS)
    reaper.project_info.update(SAVED)
    # Poll fast: the fake renders synchronously, so only stability is awaited.
    monkeypatch.setattr(render_tools, "_await_render",
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
