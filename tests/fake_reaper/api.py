"""REAPER's state, and the ReaScript functions the server calls on it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from tests.fake_reaper.objects import ItemState, Send, TrackState
from tests.fake_reaper.project import FakeProject

RENDER_PROJECT = 41824
NEW_PROJECT = 41929
TRANSPORT = {1007: "playing", 1013: "recording", 1016: "stopped"}


@dataclass
class FakeReaper:
    tmp: Path
    bpm: float = 120.0
    # bpm is in quarter notes, as REAPER displays it. The project-settings time
    # signature follows the last marker at 0, even once that marker is deleted.
    time_signature: tuple[int, int] = (4, 4)
    # [position, bpm, numerator, denominator] per tempo/time signature marker.
    tempo_markers: list[list[float]] = field(default_factory=list)
    cursor: float = 0.0
    time_selection: tuple[float, float] = (0.0, 0.0)
    project_name: str = "Test Project"
    project_path: str = ""
    transport: str = "stopped"
    tracks: list[TrackState] = field(default_factory=list)
    markers: list[tuple[float, str]] = field(default_factory=list)
    regions: list[tuple[float, float, str]] = field(default_factory=list)
    project_info: dict[str, float | str] = field(default_factory=dict)
    envelopes: dict[tuple[str, str], list[tuple[float, float]]] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)
    saves: list[bool] = field(default_factory=list)
    saved_paths: list[str] = field(default_factory=list)
    commands: list[int] = field(default_factory=list)
    renders: list[Path] = field(default_factory=list)
    # Names of the soloed tracks at each render, in render order.
    render_solos: list[list[str]] = field(default_factory=list)
    silent: bool = False
    _pointer: int = 0

    def __post_init__(self) -> None:
        self.master = TrackState(self.new_pointer("MediaTrack"), "MASTER")
        self.project = FakeProject(self)

    def new_pointer(self, kind: str) -> str:
        self._pointer += 1
        return f"({kind}*)0x{self._pointer:016X}"

    def add_track(self, name: str = "") -> TrackState:
        self.project.add_track(len(self.tracks), name)
        return self.tracks[-1]

    def track(self, pointer: str) -> TrackState:
        for state in [*self.tracks, self.master]:
            if state.pointer == pointer:
                return state
        raise ValueError(f"no track {pointer}")

    def time_signature_at_start(self) -> tuple[int, int]:
        for position, _, numerator, denominator in self.tempo_markers:
            if position == 0.0:
                return int(numerator), int(denominator)
        return self.time_signature

    def show_envelope(self, track: TrackState, name: str) -> None:
        self.envelopes[(track.pointer, name)] = []

    # Actions, undo and UI

    def Main_OnCommand(self, command: int, flag: int) -> None:
        self.commands.append(command)
        if command == RENDER_PROJECT:
            self._render()
        elif command == NEW_PROJECT:
            for contents in (self.tracks, self.markers, self.regions, self.tempo_markers):
                contents.clear()
        elif command in TRANSPORT:
            self.transport = TRANSPORT[command]

    def Main_openProject(self, path: str) -> None:
        self.opened.append(path)
        if path.lower().endswith(".rtracktemplate"):
            for line in Path(path).read_text().splitlines():
                if line.startswith("<TRACK"):
                    self.add_track(f"from {Path(path).stem}")

    def Main_SaveProjectEx(self, project: int, path: str, options: int) -> None:
        Path(path).write_text("<REAPER_PROJECT 0.1\n>\n")
        self.saved_paths.append(path)

    def Undo_BeginBlock2(self, project: int) -> None:
        pass

    def Undo_EndBlock2(self, project: int, description: str, flags: int) -> None:
        pass

    def PreventUIRefresh(self, count: int) -> None:
        pass

    def TrackList_AdjustWindows(self, is_minor: bool) -> None:
        pass

    def UpdateArrange(self) -> None:
        pass

    def GetResourcePath(self) -> str:
        return str(self.tmp / "resources")

    # Project settings

    def GetSetProjectInfo(self, project: int, desc: str, value: float, is_set: bool) -> float:  # noqa: PLR0917 -- mirrors the ReaScript signature
        if is_set:
            self.project_info[desc] = value
        return float(self.project_info.get(desc, 0.0))

    def GetSetProjectInfo_String(self, project: int, desc: str, value: str, is_set: bool):  # noqa: PLR0917 -- mirrors the ReaScript signature
        if is_set:
            self.project_info[desc] = value
        return (True, project, desc, self.project_info.get(desc, ""), is_set)

    def _render(self) -> None:
        """Write what REAPER would: a stereo file at RENDER_FILE, at RENDER_SRATE."""
        path = Path(str(self.project_info["RENDER_FILE"]))
        rate = int(self.project_info.get("RENDER_SRATE", 48000))
        t = np.arange(rate * 4) / rate
        left = np.zeros_like(t) if self.silent else 0.5 * np.sin(2 * np.pi * 440 * t)
        right = np.zeros_like(t) if self.silent else 0.25 * np.sin(2 * np.pi * 660 * t)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, np.stack([left, right], axis=1), rate, format="WAV")
        self.renders.append(path)
        self.render_solos.append([t.name for t in self.tracks if t.info["I_SOLO"]])

    # Tempo and time signature (return shapes as REAPER 7.82 gives them)

    def Master_GetTempo(self) -> float:
        return self.bpm

    def CountTempoTimeSigMarkers(self, project: int) -> int:
        return len(self.tempo_markers)

    def GetTempoTimeSigMarker(self, project, index, *_out) -> list:
        position, bpm, numerator, denominator = self.tempo_markers[index]
        return [True, project, index, position, 0, 0.0, bpm, numerator, denominator, False]

    def SetTempoTimeSigMarker(self, project, index, position, _measure, _beat, bpm, *rest) -> bool:  # noqa: PLR0917 -- mirrors the ReaScript signature
        numerator, denominator, _linear = rest
        marker = [position, bpm, numerator, denominator]
        if position == 0.0:
            self.time_signature = (int(numerator), int(denominator))
        if index == -1:
            self.tempo_markers.append(marker)
            self.tempo_markers.sort(key=lambda m: m[0])
        else:
            self.tempo_markers[index] = marker
        return True

    def DeleteTempoTimeSigMarker(self, project: int, index: int) -> bool:
        del self.tempo_markers[index]
        return True

    def TimeMap_GetTimeSigAtTime(self, project, time, *_out) -> list:
        numerator, denominator = self.time_signature_at_start()
        return [project, time, numerator, denominator, self.bpm]

    # Markers and regions, in position order as REAPER enumerates them

    def _markers_and_regions(self) -> list[tuple[bool, float, float, str]]:
        entries = [(False, p, 0.0, n) for p, n in self.markers]
        entries += [(True, s, e, n) for s, e, n in self.regions]
        return sorted(entries, key=lambda entry: entry[1])

    def CountProjectMarkers(self, project: int, _markers: int, _regions: int) -> list:
        return [len(self.markers) + len(self.regions), project, len(self.markers), len(self.regions)]

    def GetRegionOrMarker(self, project: int, index: int, guid: str) -> str:
        return f"(ProjectMarker*){index}"

    def _marker(self, handle: str) -> tuple[bool, float, float, str]:
        return self._markers_and_regions()[int(handle.removeprefix("(ProjectMarker*)"))]

    def GetRegionOrMarkerInfo_Value(self, project: int, handle: str, param: str) -> float:
        is_region, start, end, _ = self._marker(handle)
        return {"B_ISREGION": float(is_region), "D_STARTPOS": start, "D_ENDPOS": end}[param]

    def GetSetRegionOrMarkerInfo_String(self, project, handle, param, value, is_set) -> list:  # noqa: PLR0917 -- mirrors the ReaScript signature
        return [True, project, handle, param, self._marker(handle)[3], is_set]

    # Tracks

    def CountTracks(self, project: int) -> int:
        return len(self.tracks)

    def GetTrack(self, project: int, index: int) -> str:
        return self.tracks[index].pointer

    def GetTrackGUID(self, track: str) -> str:
        return self.track(track).guid

    def DeleteTrack(self, track: str) -> None:
        self.tracks.remove(self.track(track))

    def SetMediaTrackInfo_Value(self, track: str, param: str, value: float) -> bool:
        self.track(track).info[param] = value
        return True

    def ColorToNative(self, r: int, g: int, b: int) -> int:
        return r | (g << 8) | (b << 16)

    def SetOnlyTrackSelected(self, track: str) -> None:
        for state in self.tracks:
            state.selected = state.pointer == track

    def SetTrackSelected(self, track: str, selected: bool) -> None:
        self.track(track).selected = selected

    def ReorderSelectedTracks(self, before_index: int, make_prev_folder: int) -> bool:
        """Move the selected tracks, in order, to just before track before_index."""
        moving = [t for t in self.tracks if t.selected]
        anchor = next((t for t in self.tracks[before_index:] if not t.selected), None)
        staying = [t for t in self.tracks if not t.selected]
        at = staying.index(anchor) if anchor is not None else len(staying)
        self.tracks[:] = staying[:at] + moving + staying[at:]
        return True

    # Media and FX

    def InsertMedia(self, path: str, mode: int) -> int:
        for state in self.tracks:
            if state.selected:
                state.items.append(ItemState(self.new_pointer("MediaItem"), self.cursor, 2.0, False))
        return 1

    def TrackFX_Delete(self, track: str, fx_index: int) -> bool:
        del self.track(track).fxs[fx_index]
        return True

    # Sends

    def CreateTrackSend(self, source: str, dest: str) -> int:
        sends = self.track(source).sends
        sends.append(Send(dest))
        return len(sends) - 1

    def RemoveTrackSend(self, track: str, category: int, send_index: int) -> bool:
        """REAPER returns false for a send index that does not exist; it does not raise."""
        sends = self.track(track).sends
        if not 0 <= send_index < len(sends):
            return False
        del sends[send_index]
        return True

    def GetTrackNumSends(self, track: str, category: int) -> int:
        return len(self.track(track).sends)

    def GetTrackSendInfo_Value(self, track: str, category: int, i: int, param: str) -> float:  # noqa: PLR0917 -- mirrors the ReaScript signature
        send = self.track(track).sends[i]
        return {"D_VOL": send.volume, "D_PAN": send.pan, "B_MUTE": float(send.muted)}[param]

    def SetTrackSendInfo_Value(self, track, category, i, param, value) -> bool:  # noqa: PLR0917 -- mirrors the ReaScript signature
        sends = self.track(track).sends
        if not 0 <= i < len(sends):
            return False  # REAPER reports a bad send index by returning false
        send = sends[i]
        if param == "D_VOL":
            send.volume = value
        elif param == "D_PAN":
            send.pan = value
        return True

    # Envelopes

    def GetTrackEnvelopeByName(self, track: str, name: str) -> str:
        return f"(TrackEnvelope*){track}|{name}" if (track, name) in self.envelopes else ""

    def InsertEnvelopePoint(self, envelope, time, value, shape, tension, selected, no_sort) -> bool:  # noqa: PLR0917 -- mirrors the ReaScript signature
        track, name = envelope.removeprefix("(TrackEnvelope*)").rsplit("|", 1)
        self.envelopes[(track, name)].append((time, value))
        return True

    def Envelope_SortPoints(self, envelope: str) -> bool:
        return True


RPR_FUNCTIONS = sorted(
    name for name, value in vars(FakeReaper).items() if name[:1].isupper() and callable(value)
)
