"""reapy.Project, faked over FakeReaper's state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reapy.errors import DistError

from tests.fake_reaper.objects import FakeMarker, FakeRegion, FakeTrack, TrackState

if TYPE_CHECKING:
    from tests.fake_reaper.api import FakeReaper


class FakeProject:
    def __init__(self, reaper: FakeReaper) -> None:
        self._reaper = reaper
        self.id = "(ReaProject*)0x0000000000000001"

    @property
    def bpm(self) -> float:
        """reapy reads the tempo in beats of the denominator (240 in 6/8 at a
        quarter-note 120), though its setter takes quarter notes."""
        return self._reaper.bpm * self._reaper.time_signature_at_start()[1] / 4

    @bpm.setter
    def bpm(self, value: float) -> None:
        self._reaper.bpm = value

    @property
    def time_signature(self) -> tuple[float, float]:
        """reapy returns (bpm, bpi): the tempo and the numerator, not num/denom."""
        return self.bpm, float(self._reaper.time_signature_at_start()[0])

    @property
    def cursor_position(self) -> float:
        return self._reaper.cursor

    @cursor_position.setter
    def cursor_position(self, value: float) -> None:
        self._reaper.cursor = value

    @property
    def time_selection(self) -> tuple[float, float]:
        return self._reaper.time_selection

    @time_selection.setter
    def time_selection(self, value: tuple[float, float]) -> None:
        self._reaper.time_selection = (value[0], value[1])

    @property
    def name(self) -> str:
        return self._reaper.project_name

    @property
    def path(self) -> str:
        return self._reaper.project_path

    @property
    def length(self) -> float:
        return 8.0

    @property
    def n_tracks(self) -> int:
        return len(self._reaper.tracks)

    @property
    def tracks(self) -> list[FakeTrack]:
        return [FakeTrack(self._reaper, s) for s in self._reaper.tracks]

    @property
    def master_track(self) -> FakeTrack:
        return FakeTrack(self._reaper, self._reaper.master)

    @property
    def n_markers(self) -> int:
        return len(self._reaper.markers)

    @property
    def markers(self) -> list[FakeMarker]:
        return [FakeMarker(p) for p, _ in self._reaper.markers]

    @property
    def n_regions(self) -> int:
        return len(self._reaper.regions)

    @property
    def regions(self) -> list[FakeRegion]:
        return [FakeRegion(s, e) for s, e, _ in self._reaper.regions]

    def add_marker(self, position, name="", color=0) -> FakeMarker:
        self._reaper.markers.append((position, name))
        return FakeMarker(position)

    def add_region(self, start, end, name="", color=0) -> FakeRegion:  # noqa: PLR0917 -- mirrors reapy.Project.add_region
        self._reaper.regions.append((start, end, name))
        return FakeRegion(start, end)

    def add_track(self, index=0, name="") -> FakeTrack:
        state = TrackState(self._reaper.new_pointer("MediaTrack"), name)
        n = len(self._reaper.tracks)
        self._reaper.tracks.insert(max(0, min(index, n)), state)
        return FakeTrack(self._reaper, state)

    def save(self, force_save_as=False) -> None:
        """reapy forwards to Main_SaveProject(proj, forceSaveAsIn), and REAPER's
        Python binding rejects anything that is not an int-compatible flag."""
        if not isinstance(force_save_as, (bool, int)):
            # Raised inside REAPER, so reapy re-raises it as a DistError.
            raise DistError(
                "  File \"reaper_python.py\", in RPR_Main_SaveProject\n"
                f"TypeError: '{type(force_save_as).__name__}' object cannot be interpreted as "
                "an integer\n"
            )
        self._reaper.saves.append(bool(force_save_as))
