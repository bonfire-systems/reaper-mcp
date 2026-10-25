"""region_render's helpers, which need no DAW: parsing RENDER_TARGETS, and
the filesystem polling that decides whether a render is complete, stalled or
timed out. The tool itself is tested in test_region_render.py.
"""
import threading
import time

import pytest

from reaper_mcp.region_render import (
    _await_render,
    _conflicting_targets,
    _parse_render_targets,
)


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
