"""The one module that imports reapy.

Every tool reaches REAPER through here: ``RPR`` for ReaScript API calls and
``get_project()`` for reapy's object model. Keeping reapy behind one module
gives the type checker a declared surface to check calls against (reapy
attaches the ReaScript functions at runtime, so its own stub declares none of
them), and gives tests a single seam to replace with a fake.
"""

import logging
from typing import Protocol, cast

import reapy
from reapy import reascript_api as _reascript_api

logger = logging.getLogger("reaper_mcp.reaper")

# reapy hands REAPER object pointers across the bridge as strings such as
# "(MediaTrack*)0x0000600001234567".
Pointer = str


class ReaScriptAPI(Protocol):
    """The subset of REAPER's ReaScript API this server calls.

    Parameters are positional-only, as REAPER's are; the leading underscore
    marks their names as documentation, not API.
    """

    # Actions, undo and UI
    def Main_OnCommand(self, _command: int, _flag: int, /) -> None: ...
    def Main_openProject(self, _path: str, /) -> None: ...
    def Undo_BeginBlock2(self, _project: int, /) -> None: ...
    def Undo_EndBlock2(self, _project: int, _description: str, _flags: int, /) -> None: ...
    def PreventUIRefresh(self, _count: int, /) -> None: ...
    def TrackList_AdjustWindows(self, _is_minor: bool, /) -> None: ...
    def UpdateArrange(self) -> None: ...
    def GetResourcePath(self) -> str: ...

    def Main_SaveProjectEx(self, _project: int, _path: str, _options: int, /) -> None: ...

    # Project settings
    def GetSetProjectInfo(  # noqa: PLR0917 -- REAPER's own signature
        self, _project: int, _desc: str, _value: float, _is_set: bool, /
    ) -> float: ...
    def GetSetProjectInfo_String(  # noqa: PLR0917 -- REAPER's own signature
        self, _project: int, _desc: str, _value: str, _is_set: bool, /
    ) -> object: ...

    # Tempo and time signature
    def Master_GetTempo(self) -> float: ...
    def CountTempoTimeSigMarkers(self, _project: int, /) -> int: ...
    def GetTempoTimeSigMarker(  # noqa: PLR0913, PLR0917 -- REAPER's own signature
        self, _project: int, _index: int, _pos: float, _measure: int, _beat: float,
        _bpm: float, _num: int, _denom: int, _linear: bool, /,
    ) -> list: ...
    def SetTempoTimeSigMarker(  # noqa: PLR0913, PLR0917 -- REAPER's own signature
        self, _project: int, _index: int, _pos: float, _measure: int, _beat: float,
        _bpm: float, _num: int, _denom: int, _linear: bool, /,
    ) -> bool: ...
    def TimeMap_GetTimeSigAtTime(  # noqa: PLR0917 -- REAPER's own signature
        self, _project: int, _time: float, _num: int, _denom: int, _tempo: float, /
    ) -> list: ...

    # Markers and regions (REAPER 7: string out-parameters of EnumProjectMarkers
    # do not survive the Python binding, so names are read through these).
    def CountProjectMarkers(self, _project: int, _markers: int, _regions: int, /) -> list: ...
    def GetRegionOrMarker(self, _project: int, _index: int, _guid: str, /) -> Pointer: ...
    def GetRegionOrMarkerInfo_Value(self, _project: int, _marker: Pointer, _param: str, /) -> float: ...
    def GetSetRegionOrMarkerInfo_String(  # noqa: PLR0917 -- REAPER's own signature
        self, _project: int, _marker: Pointer, _param: str, _value: str, _is_set: bool, /
    ) -> list: ...

    # Tracks
    def CountTracks(self, _project: int, /) -> int: ...
    def GetTrack(self, _project: int, _index: int, /) -> Pointer: ...
    def GetTrackGUID(self, _track: Pointer, /) -> str: ...
    def DeleteTrack(self, _track: Pointer, /) -> None: ...
    def SetMediaTrackInfo_Value(self, _track: Pointer, _param: str, _value: float, /) -> bool: ...
    def ColorToNative(self, _r: int, _g: int, _b: int, /) -> int: ...
    def SetOnlyTrackSelected(self, _track: Pointer, /) -> None: ...
    def SetTrackSelected(self, _track: Pointer, _selected: bool, /) -> None: ...
    def ReorderSelectedTracks(self, _before_index: int, _make_prev_folder: int, /) -> bool: ...

    # Media and FX
    def InsertMedia(self, _path: str, _mode: int, /) -> int: ...
    def TrackFX_Delete(self, _track: Pointer, _fx_index: int, /) -> bool: ...
    def TrackFX_SetParamNormalized(  # noqa: PLR0917 -- REAPER's own signature
        self, _track: Pointer, _fx: int, _param: int, _value: float, /
    ) -> bool: ...
    def TrackFX_SetPreset(self, _track: Pointer, _fx: int, _preset: str, /) -> bool: ...
    def TrackFX_GetFormattedParamValue(  # noqa: PLR0917 -- REAPER's own signature
        self, _track: Pointer, _fx: int, _param: int, _buf: str, _size: int, /
    ) -> list: ...
    def TrackFX_FormatParamValueNormalized(  # noqa: PLR0917 -- REAPER's own signature
        self, _track: Pointer, _fx: int, _param: int, _value: float, _buf: str, _size: int, /
    ) -> list: ...

    # Sends
    def CreateTrackSend(self, _source: Pointer, _dest: Pointer, /) -> int: ...
    def RemoveTrackSend(self, _track: Pointer, _category: int, _send_index: int, /) -> bool: ...
    def GetTrackNumSends(self, _track: Pointer, _category: int, /) -> int: ...
    def GetTrackSendInfo_Value(  # noqa: PLR0917 -- REAPER's own signature
        self, _track: Pointer, _category: int, _send_index: int, _param: str, /
    ) -> float: ...
    def SetTrackSendInfo_Value(  # noqa: PLR0917 -- REAPER's own signature
        self, _track: Pointer, _category: int, _send_index: int, _param: str, _value: float, /
    ) -> bool: ...

    # Envelopes
    def GetTrackEnvelopeByName(self, _track: Pointer, _name: str, /) -> Pointer: ...
    def InsertEnvelopePoint(  # noqa: PLR0917 -- REAPER's own signature
        self,
        _envelope: Pointer,
        _time: float,
        _value: float,
        _shape: int,
        _tension: float,
        _selected: bool,
        _no_sort: bool,
        /,
    ) -> bool: ...
    def Envelope_SortPoints(self, _envelope: Pointer, /) -> bool: ...


RPR = cast(ReaScriptAPI, _reascript_api)

_connected = False


def ensure_connected() -> None:
    global _connected
    if _connected:
        return
    try:
        reapy.connect()
        _connected = True
        logger.info("Connected to REAPER")
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to REAPER: {e}. "
            "Make sure REAPER is running and the distant API is enabled. "
            "To enable it: run the setup script (scripts/enable_reapy.py) or "
            "in REAPER go to Actions > Run ReaScript, then run: "
            "import reapy; reapy.config.enable_dist_api()"
        ) from e


def get_project() -> reapy.Project:
    ensure_connected()
    return reapy.Project()
