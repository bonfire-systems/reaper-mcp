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
    """The subset of REAPER's ReaScript API this server calls."""

    # Actions, undo and UI
    def Main_OnCommand(self, command: int, flag: int, /) -> None: ...
    def Main_openProject(self, path: str, /) -> None: ...
    def Undo_BeginBlock2(self, project: int, /) -> None: ...
    def Undo_EndBlock2(self, project: int, description: str, flags: int, /) -> None: ...
    def PreventUIRefresh(self, count: int, /) -> None: ...
    def TrackList_AdjustWindows(self, is_minor: bool, /) -> None: ...
    def UpdateArrange(self) -> None: ...
    def GetResourcePath(self) -> str: ...

    # Project settings
    def GetSetProjectInfo(
        self, project: int, desc: str, value: float, is_set: bool, /
    ) -> float: ...
    def GetSetProjectInfo_String(
        self, project: int, desc: str, value: str, is_set: bool, /
    ) -> object: ...

    # Tracks
    def CountTracks(self, project: int, /) -> int: ...
    def GetTrack(self, project: int, index: int, /) -> Pointer: ...
    def GetTrackGUID(self, track: Pointer, /) -> str: ...
    def DeleteTrack(self, track: Pointer, /) -> None: ...
    def SetMediaTrackInfo_Value(self, track: Pointer, param: str, value: float, /) -> bool: ...
    def ColorToNative(self, r: int, g: int, b: int, /) -> int: ...
    def SetOnlyTrackSelected(self, track: Pointer, /) -> None: ...
    def SetTrackSelected(self, track: Pointer, selected: bool, /) -> None: ...
    def ReorderSelectedTracks(self, before_index: int, make_prev_folder: int, /) -> bool: ...

    # Media and FX
    def InsertMedia(self, path: str, mode: int, /) -> int: ...
    def TrackFX_Delete(self, track: Pointer, fx_index: int, /) -> bool: ...

    # Sends
    def CreateTrackSend(self, source: Pointer, dest: Pointer, /) -> int: ...
    def RemoveTrackSend(self, track: Pointer, category: int, send_index: int, /) -> bool: ...
    def GetTrackNumSends(self, track: Pointer, category: int, /) -> int: ...
    def GetTrackSendInfo_Value(
        self, track: Pointer, category: int, send_index: int, param: str, /
    ) -> float: ...
    def SetTrackSendInfo_Value(
        self, track: Pointer, category: int, send_index: int, param: str, value: float, /
    ) -> bool: ...

    # Envelopes
    def GetTrackEnvelopeByName(self, track: Pointer, name: str, /) -> Pointer: ...
    def InsertEnvelopePoint(
        self,
        envelope: Pointer,
        time: float,
        value: float,
        shape: int,
        tension: float,
        selected: bool,
        no_sort: bool,
        /,
    ) -> bool: ...
    def Envelope_SortPoints(self, envelope: Pointer, /) -> bool: ...


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
