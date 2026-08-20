"""Unit tests for render_regions' pure helpers.

Deliberately no REAPER: these cover the parsing that has no business talking to
a DAW, and that is where the subtle breakage lives. The tool functions
themselves need a live REAPER and are not covered here.
"""
import threading
import time

from reaper_mcp.render_tools import (
    _await_render,
    _conflicting_targets,
    _parse_render_targets,
)


class TestParseRenderTargets:
    def test_splits_on_semicolons(self):
        raw = "/out/a.mp4;/out/b.mp4;/out/c.mp4"
        assert _parse_render_targets(raw, "/out") == ["/out/a.mp4", "/out/b.mp4", "/out/c.mp4"]

    def test_tolerates_trailing_semicolon(self):
        # REAPER emits a trailing separator
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
        # REAPER creates the output file before writing to it; 0 bytes is not done
        target = str(tmp_path / "empty.mp4")
        with open(target, "wb"):
            pass
        _, status = _await_render([target], stall_timeout=0.3, **FAST)
        assert status == "stalled"

    def test_growing_scratch_file_prevents_a_premature_stall(self, tmp_path):
        # REAPER writes into <name>.sb-<hash> before the final file appears, so
        # that growth must count as progress or long renders get cut off
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
        # a scratch file means REAPER still has the render open; giving up would
        # restore the project's render settings underneath it
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
    """REAPER neither overwrites nor reports a clash - it writes <name>-001."""

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
