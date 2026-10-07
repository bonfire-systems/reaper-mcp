import os
import time
from pathlib import Path

from reaper_mcp.reaper import RPR, get_project


def create_project(*, tempo: float = 120.0, time_signature: str = "4/4", name: str = "") -> dict:
    """Create a new REAPER project with the given tempo and time signature."""
    RPR.Main_OnCommand(41929, 0)  # File: New project
    project = get_project()
    project.bpm = tempo
    if time_signature:
        num, denom = map(int, time_signature.split("/"))
        _set_time_signature(num, denom)
    return {
        "success": True,
        "name": name or f"New Project {time.strftime('%Y-%m-%d %H-%M-%S')}",
        "tempo": _tempo(),
        "time_signature": time_signature,
    }


def save_project(*, project_path: str = "") -> dict:
    """Save the current project. If no path is given, saves to ~/Documents/REAPER Projects."""
    project = get_project()
    if not project_path:
        proj_name = project.name or f"Project {time.strftime('%Y-%m-%d %H-%M-%S')}"
        default_dir = Path.home() / "Documents" / "REAPER Projects"
        os.makedirs(default_dir, exist_ok=True)
        project_path = str(default_dir / f"{proj_name}.rpp")
    os.makedirs(os.path.dirname(os.path.abspath(project_path)), exist_ok=True)
    # reapy's Project.save takes a "force save as" flag, not a path.
    RPR.Main_SaveProjectEx(0, project_path, 0)
    if not os.path.isfile(project_path):
        return {"success": False, "error": f"REAPER did not write {project_path}"}
    return {"success": True, "project_path": project_path}


def load_project(*, project_path: str) -> dict:
    """Load a REAPER project (.rpp) from the given file path."""
    if not os.path.exists(project_path):
        return {"success": False, "error": f"File not found: {project_path}"}
    RPR.Main_openProject(project_path)
    project = get_project()
    return {
        "success": True,
        "name": project.name,
        "tempo": _tempo(),
        "time_signature": _time_signature_text(),
        "project_path": project_path,
    }


def _markers_and_regions() -> tuple[list[dict], list[dict]]:
    """Project markers and regions, each indexed in their own sequence."""
    markers: list[dict] = []
    regions: list[dict] = []
    total = RPR.CountProjectMarkers(0, 0, 0)[0]
    for i in range(total):
        handle = RPR.GetRegionOrMarker(0, i, "")
        name = RPR.GetSetRegionOrMarkerInfo_String(0, handle, "P_NAME", "", False)[4]
        start = RPR.GetRegionOrMarkerInfo_Value(0, handle, "D_STARTPOS")
        if RPR.GetRegionOrMarkerInfo_Value(0, handle, "B_ISREGION"):
            end = RPR.GetRegionOrMarkerInfo_Value(0, handle, "D_ENDPOS")
            regions.append({"index": len(regions), "name": name, "start": start, "end": end})
        else:
            markers.append({"index": len(markers), "name": name, "position": start})
    return markers, regions


def _tempo() -> float:
    """The tempo in quarter notes per minute, as REAPER displays it.

    reapy's Project.bpm setter takes quarter notes, but its getter counts beats
    of the time signature's denominator: 240 for 6/8 at a quarter-note 120.
    """
    return RPR.Master_GetTempo()


def _time_signature_text() -> str:
    """The time signature at the start of the project, e.g. "3/4".

    reapy's Project.time_signature is (bpm, numerator), not a time signature.
    """
    _, _, numerator, denominator, _ = RPR.TimeMap_GetTimeSigAtTime(0, 0.0, 0, 0, 0)
    return f"{numerator}/{denominator}"


def _marker_at_start() -> list | None:
    """REAPER's tempo/time signature marker at position 0, if there is one:
    [_, _, index, position, measure, beat, bpm, numerator, denominator, linear]."""
    if RPR.CountTempoTimeSigMarkers(0) == 0:
        return None
    marker = RPR.GetTempoTimeSigMarker(0, 0, 0.0, 0, 0.0, 0.0, 0, 0, False)
    return marker if marker[3] <= 1e-9 else None


def _set_time_signature(numerator: int, denominator: int) -> None:
    """Set the time signature at the start of the project.

    REAPER keeps it on a tempo/time signature marker at position 0: edit that
    marker when there is one, otherwise add it at the current tempo.
    """
    index = 0 if _marker_at_start() else -1
    RPR.SetTempoTimeSigMarker(0, index, 0.0, -1, -1, _tempo(), numerator, denominator, False)


def _set_tempo(project, bpm: float) -> None:
    """Set the tempo at the start of the project.

    With a tempo/time signature marker at position 0, reapy's Project.bpm
    setter (SetCurrentBPM) changes the playing tempo but can leave the
    marker's own BPM stale (seen on REAPER 7.82 with a 3/4 marker), so the
    marker is edited directly, keeping its time signature.
    """
    marker = _marker_at_start()
    if marker is None:
        project.bpm = bpm
        return
    numerator, denominator, linear = marker[7], marker[8], marker[9]
    RPR.SetTempoTimeSigMarker(0, 0, 0.0, -1, -1, bpm, numerator, denominator, linear)


def get_project_info() -> dict:
    """Get information about the current project: name, path, tempo, tracks, length."""
    project = get_project()
    markers, regions = _markers_and_regions()
    return {
        "success": True,
        "name": project.name,
        "path": project.path,
        "tempo": _tempo(),
        "time_signature": _time_signature_text(),
        "length": project.length,
        "track_count": project.n_tracks,
        "markers": markers,
        "regions": regions,
    }


def set_tempo(*, bpm: float) -> dict:
    """Set the project tempo in BPM."""
    _set_tempo(get_project(), bpm)
    return {"success": True, "tempo": _tempo()}


def set_time_signature(*, numerator: int, denominator: int) -> dict:
    """Set the project time signature, e.g. 4/4, 3/4, 6/8."""
    _set_time_signature(numerator, denominator)
    return {"success": True, "time_signature": _time_signature_text()}


TOOLS = (
    create_project,
    save_project,
    load_project,
    get_project_info,
    set_tempo,
    set_time_signature,
)
