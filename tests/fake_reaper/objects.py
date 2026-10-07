"""reapy's object model, faked over plain state.

Each ``Fake*`` class mirrors one reapy class and exposes only API that class
has (tests/test_fake_reaper.py enforces it). Like reapy, every access through
``project.tracks``, ``track.fxs``, ``track.items`` or ``fx.params`` builds a
fresh proxy over shared state, so an attribute a tool assigns that reapy does
not have lands on a throwaway object and REAPER never sees it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.fake_reaper.api import FakeReaper

# The plugins the fake REAPER has installed; anything else is "not found".
INSTALLED_FX = {
    "ReaEQ": ["Gain-Low", "Freq-Low", "Gain-High"],
    "ReaComp": ["Thresh", "Ratio", "Attack", "Release"],
    "ReaLimit": ["Threshold", "Ceiling", "Release"],
    "ReaSynth": ["Volume", "Tuning"],
}


@dataclass
class FXState:
    plugin: str
    values: list[float]
    enabled: bool = True
    preset: str = ""


@dataclass
class Note:
    start: float
    end: float
    pitch: int
    velocity: int
    channel: int


@dataclass
class ItemState:
    pointer: str
    position: float
    length: float
    midi: bool
    notes: list[Note] = field(default_factory=list)


@dataclass
class Send:
    dest: str
    volume: float = 1.0
    pan: float = 0.0
    muted: bool = False


@dataclass
class TrackState:
    pointer: str
    name: str = ""
    fxs: list[FXState] = field(default_factory=list)
    items: list[ItemState] = field(default_factory=list)
    sends: list[Send] = field(default_factory=list)
    info: dict[str, float] = field(
        default_factory=lambda: {"D_VOL": 1.0, "D_PAN": 0.0, "B_MUTE": 0.0, "I_SOLO": 0.0}
    )
    selected: bool = False

    @property
    def guid(self) -> str:
        return "{" + self.pointer[-8:] + "-0000-0000-0000-000000000000}"


class FakeFXParam(float):
    """reapy.FXParam is a float subclass whose value is the normalized one."""

    def __new__(cls, state: FXState, index: int) -> FakeFXParam:
        return float.__new__(cls, state.values[index])

    def __init__(self, state: FXState, index: int) -> None:
        float.__init__(state.values[index])
        self._state = state
        self._index = index

    @property
    def name(self) -> str:
        return INSTALLED_FX[self._state.plugin][self._index]

    @property
    def normalized(self) -> float:
        return self._state.values[self._index]

    @normalized.setter
    def normalized(self, value: float) -> None:
        """Observed on REAPER 7.82 with reapy 0.10: the setter reads
        ``parent_fx.id``, which reapy's FX does not have, and raises."""
        raise AttributeError("'FX' object has no attribute 'id'")

    @property
    def formatted(self) -> str:
        return f"{self.normalized:.2f}"


class FakeFX:
    def __init__(self, state: FXState) -> None:
        self._state = state

    @property
    def name(self) -> str:
        return f"VST: {self._state.plugin} (Cockos)"

    @property
    def n_params(self) -> int:
        return len(self._state.values)

    @property
    def params(self) -> list[FakeFXParam]:
        return [FakeFXParam(self._state, i) for i in range(len(self._state.values))]

    @property
    def is_enabled(self) -> bool:
        return self._state.enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        self._state.enabled = value

    @property
    def preset(self) -> str:
        return self._state.preset

    @preset.setter
    def preset(self, value: str) -> None:
        self._state.preset = value


class FakeTake:
    def __init__(self, state: ItemState) -> None:
        self._state = state

    @property
    def is_midi(self) -> bool:
        return self._state.midi

    @property
    def name(self) -> str:
        return "take"

    @property
    def start_offset(self) -> float:
        return 0.0

    def add_note(
        self, start, end, pitch, velocity=100, channel=0, selected=False,
        muted=False, unit="seconds", sort=True,
    ) -> None:
        self._state.notes.append(Note(start, end, pitch, velocity, channel))


class FakeItem:
    def __init__(self, state: ItemState) -> None:
        self._state = state
        self.id = state.pointer

    @property
    def position(self) -> float:
        return self._state.position

    @position.setter
    def position(self, value: float) -> None:
        self._state.position = value

    @property
    def length(self) -> float:
        return self._state.length

    @length.setter
    def length(self, value: float) -> None:
        self._state.length = value

    @property
    def active_take(self) -> FakeTake:
        return FakeTake(self._state)

    @property
    def n_takes(self) -> int:
        return 1


class FakeTrack:
    def __init__(self, reaper: FakeReaper, state: TrackState) -> None:
        self._reaper = reaper
        self._state = state
        self.id = state.pointer

    @property
    def name(self) -> str:
        return self._state.name

    @name.setter
    def name(self, value: str) -> None:
        self._state.name = value

    @property
    def n_fxs(self) -> int:
        return len(self._state.fxs)

    @property
    def fxs(self) -> list[FakeFX]:
        return [FakeFX(s) for s in self._state.fxs]

    @property
    def n_items(self) -> int:
        return len(self._state.items)

    @property
    def items(self) -> list[FakeItem]:
        return [FakeItem(s) for s in self._state.items]

    def add_fx(self, name, input_fx=False, even_if_exists=True) -> FakeFX:
        """reapy returns the FX object, and raises ValueError when not found."""
        if name not in INSTALLED_FX:
            raise ValueError(f"Can't find FX named {name}")
        state = FXState(name, [0.5] * len(INSTALLED_FX[name]))
        self._state.fxs.append(state)
        return FakeFX(state)

    def add_midi_item(self, start=0, end=1, quantize=False) -> FakeItem:
        state = ItemState(self._reaper.new_pointer("MediaItem"), start, end - start, midi=True)
        self._state.items.append(state)
        return FakeItem(state)

    @property
    def is_muted(self) -> bool:
        return bool(self._state.info["B_MUTE"])

    @is_muted.setter
    def is_muted(self, value: bool) -> None:
        self._state.info["B_MUTE"] = float(value)

    @property
    def is_solo(self) -> bool:
        return bool(self._state.info["I_SOLO"])

    @is_solo.setter
    def is_solo(self, value: bool) -> None:
        # reapy's setter calls solo()/unsolo(); see solo().
        if value:
            self.solo()
        else:
            self.unsolo()

    def mute(self) -> None:
        self.is_muted = True

    def unmute(self) -> None:
        self.is_muted = False

    def solo(self) -> None:
        """Observed on REAPER 7.82: reapy toggles solo through action 7 on the
        selected tracks, which leaves the solo state unchanged. Only I_SOLO
        (set_info_value / SetMediaTrackInfo_Value) changes it."""

    def unsolo(self) -> None:
        """See solo()."""

    def get_info_value(self, param: str) -> float:
        return self._state.info[param]

    def set_info_value(self, param: str, value: float) -> None:
        self._state.info[param] = value


class FakeTimeSelection:
    """reapy.TimeSelection: a live view with settable start, end and length."""

    def __init__(self, reaper: FakeReaper) -> None:
        self._reaper = reaper

    @property
    def start(self) -> float:
        return self._reaper.time_selection[0]

    @start.setter
    def start(self, value: float) -> None:
        self._reaper.time_selection = (value, self._reaper.time_selection[1])

    @property
    def end(self) -> float:
        return self._reaper.time_selection[1]

    @end.setter
    def end(self, value: float) -> None:
        self._reaper.time_selection = (self._reaper.time_selection[0], value)

    @property
    def length(self) -> float:
        return self.end - self.start

    @length.setter
    def length(self, value: float) -> None:
        self.end = self.start + value


class FakeMarker:
    """reapy.Marker has a position and no name."""

    def __init__(self, position: float) -> None:
        self._position = position

    @property
    def position(self) -> float:
        return self._position

    @position.setter
    def position(self, value: float) -> None:
        self._position = value


class FakeRegion:
    """reapy.Region has start and end and no name."""

    def __init__(self, start: float, end: float) -> None:
        self._start, self._end = start, end

    @property
    def start(self) -> float:
        return self._start

    @start.setter
    def start(self, value: float) -> None:
        self._start = value

    @property
    def end(self) -> float:
        return self._end

    @end.setter
    def end(self, value: float) -> None:
        self._end = value
