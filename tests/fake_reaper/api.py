"""REAPER's state, and the ReaScript functions the server calls on it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tests.fake_reaper.objects import PRESETS, ItemState, Send, TrackState
from tests.fake_reaper.project import FakeProject
from tests.fake_reaper.render import render

RENDER_PROJECT = 41824
NUMERIC_PROJECT_INFO = {
    "RENDER_SRATE", "RENDER_CHANNELS", "RENDER_BOUNDSFLAG", "RENDER_ADDTOPROJ",
    "RENDER_STARTPOS", "RENDER_ENDPOS",
}
NEW_PROJECT_TAB = 41929  # New project tab, ignore default template
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
    # Projects moved behind a new tab: (tracks, markers, regions, tempo markers).
    background_tabs: list[tuple] = field(default_factory=list)
    # Names of the soloed tracks at each render, in render order.
    render_solos: list[list[str]] = field(default_factory=list)
    silent: bool = False
    # Seconds of material in the project; 0 is an empty project.
    length: float = 4.0
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
            self.renders.append(render(self))
            self.render_solos.append([t.name for t in self.tracks if t.info["I_SOLO"]])
        elif command == NEW_PROJECT_TAB:
            # The current project moves to a background tab, untouched.
            self.background_tabs.append(
                (list(self.tracks), list(self.markers), list(self.regions), list(self.tempo_markers))
            )
            self.tracks, self.markers, self.regions, self.tempo_markers = [], [], [], []
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

    def GetSetProjectInfo(self, project: int, desc: str, value: float, is_set: bool) -> float:
        # REAPER ignores numeric keys it does not have, such as RENDER_FORMAT
        # (a string setting) and RENDER_FORMAT2.
        if is_set and desc in NUMERIC_PROJECT_INFO:
            self.project_info[desc] = value
        return float(self.project_info.get(desc, 0.0))

    def GetSetProjectInfo_String(self, project: int, desc: str, value: str, is_set: bool):
        if is_set:
            self.project_info[desc] = value
        return (True, project, desc, self.project_info.get(desc, ""), is_set)

    # Tempo and time signature (return shapes as REAPER 7.82 gives them)

    def Master_GetTempo(self) -> float:
        for position, bpm, _, _ in self.tempo_markers:
            if position == 0.0:
                return bpm
        return self.bpm

    def CountTempoTimeSigMarkers(self, project: int) -> int:
        return len(self.tempo_markers)

    def GetTempoTimeSigMarker(self, project, index, *_out) -> list:
        position, bpm, numerator, denominator = self.tempo_markers[index]
        return [True, project, index, position, 0, 0.0, bpm, numerator, denominator, False]

    def SetTempoTimeSigMarker(self, project, index, position, _measure, _beat, bpm, *rest) -> bool:
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

    def GetSetRegionOrMarkerInfo_String(self, project, handle, param, value, is_set) -> list:
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

    def TrackFX_SetParamNormalized(self, track: str, fx: int, param: int, value: float) -> bool:
        self.track(track).fxs[fx].values[param] = value
        return True

    def TrackFX_SetPreset(self, track: str, fx: int, preset: str) -> bool:
        state = self.track(track).fxs[fx]
        if preset not in PRESETS[state.plugin]:
            return False
        state.preset = preset
        return True

    def _display(self, state, param: int, value: float) -> str:
        if state.plugin == "ReaLimit" and param == 0:
            return f"{value * 72 - 60:+.2f} dB"  # ReaLimit's threshold: -60..+12 dB
        if state.plugin == "ReaLimit" and param == 2:
            # ReaLimit's release falls from "inf" as the control rises. A stand-in
            # curve; REAPER's own is exercised by tests/live.
            return "inf" if value <= 0 else f"{6 / value**0.5:.1f} dB/sec"
        return f"{value:.2f}"

    def TrackFX_GetFormattedParamValue(self, track, fx, param, buf, size) -> list:
        state = self.track(track).fxs[fx]
        return [True, track, fx, param, self._display(state, param, state.values[param]), size]

    def TrackFX_FormatParamValueNormalized(self, track, fx, param, value, buf, size) -> list:
        state = self.track(track).fxs[fx]
        return [True, track, fx, param, value, self._display(state, param, value), size]

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

    def GetTrackSendInfo_Value(self, track: str, category: int, i: int, param: str) -> float:
        send = self.track(track).sends[i]
        return {"D_VOL": send.volume, "D_PAN": send.pan, "B_MUTE": float(send.muted)}[param]

    def SetTrackSendInfo_Value(self, track, category, i, param, value) -> bool:
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

    def InsertEnvelopePoint(self, envelope, time, value, shape, tension, selected, no_sort) -> bool:
        track, name = envelope.removeprefix("(TrackEnvelope*)").rsplit("|", 1)
        self.envelopes[(track, name)].append((time, value))
        return True

    def Envelope_SortPoints(self, envelope: str) -> bool:
        return True

    def GetEnvelopeScalingMode(self, envelope: str) -> int:
        """REAPER's volume envelopes use fader scaling (1); pan is linear (0)."""
        return 1 if envelope.endswith("|Volume") else 0

    def ScaleToEnvelopeMode(self, mode: int, value: float) -> float:
        """A stand-in for REAPER's fader curve, distinguishable from the raw
        value; the real curve is exercised by tests/live (-6 dB renders -6 dB)."""
        return value * 1000.0 if mode == 1 else value


RPR_FUNCTIONS = sorted(
    name for name, value in vars(FakeReaper).items() if name[:1].isupper() and callable(value)
)
