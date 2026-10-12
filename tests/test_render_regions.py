"""render_regions: its pure helpers, and the tool end to end against the fake
REAPER, whose RENDER_TARGETS and region bounds are modelled in
fake_reaper/render.py. The helper tests come from PR #7; they cover
the parsing and filesystem polling that need no DAW.
"""
import functools
import threading
import time

import pytest

from reaper_mcp import render_tools
from reaper_mcp.render_tools import (
    _await_render,
    _conflicting_targets,
    _parse_render_targets,
)
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

    def test_single_target(self):
        assert _parse_render_targets("/out/only.mp4", "/out") == ["/out/only.mp4"]

    def test_empty_and_blank(self):
        assert _parse_render_targets("", "/out") == []
        assert _parse_render_targets("   ", "/out") == []
        assert _parse_render_targets(None, "/out") == []

    def test_without_directory_falls_back_to_naive_split(self):
        assert _parse_render_targets("a.mp4;b.mp4") == ["a.mp4", "b.mp4"]


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
         "RENDER_BOUNDSFLAG": 1.0}


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
    assert result["success"] is True and result["status"] == "complete"
    assert result["expected"] == expected  # the ';' in a region name survives
    assert [f["path"] for f in result["files"]] == expected
    assert result["region_count"] == 3
    assert regions.commands == [RENDER]
    assert regions.project_info == SAVED


def test_dry_run_reports_targets_without_rendering(regions, call, tmp_path):
    out = tmp_path / "not-yet"
    result = call("render_regions", output_directory=str(out), dry_run=True)
    assert result["would_write"] == [str(out / f"{n}.wav") for _, _, n in REGIONS]
    assert [r["name"] for r in result["regions"]] == [n for _, _, n in REGIONS]
    assert result["already_exist"] == []
    assert not out.exists()  # a dry run leaves the disk alone
    assert regions.commands == []
    assert regions.project_info == SAVED


def test_existing_outputs_are_refused_not_deleted(regions, call, tmp_path):
    stale = tmp_path / "intro.wav"
    stale.write_bytes(b"previous run")
    result = call("render_regions", output_directory=str(tmp_path))
    assert result["success"] is False and "already exist" in result["error"]
    assert result["already_exist"] == [str(stale)]
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
