"""Fail a live run loudly when REAPER opens a dialog, instead of hanging.

A REAPER modal ("Nothing to render!", the overwrite prompt, "Save changes?")
blocks the reapy call that caused it until someone clicks, so a live test
would wait forever. This thread polls REAPER's windows through System Events
and, if anything but the main window stays open past a grace period, records
what it saw in ``tripped``. guard_reapy() makes reapy's blocking read poll
that flag and end the run with it. It never clicks anything: a dialog is a
finding, not noise.

(Signals were tried first and do not work here: a SIGINT aimed at the main
thread did not interrupt reapy's read under pytest, and pytest's capture
hid the message.)

macOS only (System Events); elsewhere it reports that it is not guarding.
"""

import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

GRACE_SECONDS = 15.0
POLL_SECONDS = 1.0
# REAPER's own progress window while a render runs; it closes itself.
TRANSIENT_PREFIXES = ("Rendering",)

# One line per window: title, tab, subrole. REAPER's alerts ("Nothing to
# render!") have an empty title and subrole AXDialog, so titles alone miss them.
_WINDOWS = """
tell application "System Events" to tell process "REAPER"
    set out to ""
    repeat with w in windows
        set out to out & (name of w as text) & tab & (subrole of w as text) & linefeed
    end repeat
end tell
return out
"""


def _osascript(script: str) -> str:
    # rstrip only: a leading tab is an empty window title, not whitespace.
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    return out.stdout.rstrip("\n") or out.stderr.strip()


def _describe(index: int) -> str:
    return _osascript(
        'tell application "System Events" to tell process "REAPER" to get '
        f"{{value of every static text, name of every button}} of window {index}"
    )


def _dialogs() -> dict[str, int]:
    """Open dialogs, keyed by a label (title, or subrole when untitled), to window index."""
    found = {}
    for index, line in enumerate(_osascript(_WINDOWS).splitlines(), start=1):
        title, _, subrole = line.partition("\t")
        if " - REAPER v" in title or title.startswith(TRANSIENT_PREFIXES):
            continue
        if title or subrole in ("AXDialog", "AXSystemDialog"):
            found[title or f"untitled {subrole}"] = index
    return found


class Watchdog:
    def __init__(self) -> None:
        self.available = sys.platform == "darwin" and shutil.which("osascript") is not None
        self.tripped: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if self.available:
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        first_seen: dict[str, float] = {}
        while not self._stop.wait(POLL_SECONDS):
            try:
                open_now = _dialogs()
            except (subprocess.SubprocessError, OSError):
                continue
            now = time.monotonic()
            first_seen = {w: first_seen.get(w, now) for w in open_now}
            stuck = [w for w, t in first_seen.items() if now - t >= GRACE_SECONDS]
            if stuck:
                self.tripped = "; ".join(f"{w!r}: {_describe(open_now[w])}" for w in stuck)
                return


def guard_reapy(watchdog: Watchdog, monkeypatch) -> None:
    """Make reapy's blocking reads give up when the watchdog trips.

    reapy waits for REAPER's reply with no timeout; this reads the same bytes
    in one-second slices and ends the run, naming the dialog, once REAPER is
    known to be blocked on one.
    """
    from reapy.tools.network.socket import Socket

    original = Socket.recv

    def recv(self, timeout=0.0001):
        if timeout is not None:
            return original(self, timeout)
        self.settimeout(1.0)
        while True:
            try:
                length = int.from_bytes(self._socket.recv(8), "little")
                break
            except socket.timeout:
                if watchdog.tripped:
                    pytest.exit(f"REAPER is blocked on a dialog: {watchdog.tripped}", returncode=3)
        if length == 0:
            raise ConnectionAbortedError
        self.settimeout(None)
        return self._socket.recv(length, socket.MSG_WAITALL)

    monkeypatch.setattr(Socket, "recv", recv)
