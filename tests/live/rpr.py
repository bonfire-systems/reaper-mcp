"""The ReaScript functions the live tests call, typed: the server's surface
plus the few the tests use only to read REAPER's state back."""

from typing import Protocol, cast

from reapy import reascript_api

from reaper_mcp.reaper import Pointer, ReaScriptAPI


class LiveReaScriptAPI(ReaScriptAPI, Protocol):
    def DeleteTempoTimeSigMarker(self, _project: int, _index: int, /) -> bool: ...
    def TimeMap_QNToTime(self, _qn: float, /) -> float: ...
    def MIDI_CountEvts(self, _take: Pointer, _notes: int, _ccs: int, _sysex: int, /) -> list: ...
    def MIDI_GetNote(
        self, _take: Pointer, _index: int, _selected: int, _muted: int, _start: float,
        _end: float, _channel: int, _pitch: int, _velocity: int, /,
    ) -> list: ...
    def MIDI_GetProjTimeFromPPQPos(self, _take: Pointer, _ppq: float, /) -> float: ...
    def EnumProjects(self, _index: int, _path: str, _size: int, /) -> list: ...
    def IsProjectDirty(self, _project: int, /) -> int: ...


RPR = cast(LiveReaScriptAPI, reascript_api)
