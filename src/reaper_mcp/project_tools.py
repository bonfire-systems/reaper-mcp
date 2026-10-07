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
        project.time_signature = (num, denom)
    return {
        "success": True,
        "name": name or f"New Project {time.strftime('%Y-%m-%d %H-%M-%S')}",
        "tempo": project.bpm,
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
    project.save(project_path)
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
        "tempo": project.bpm,
        "time_signature": f"{project.time_signature[0]}/{project.time_signature[1]}",
        "project_path": project_path,
    }


def _markers(project) -> list[dict]:
    markers = []
    try:
        for i in range(project.n_markers):
            m = project.markers[i]
            markers.append({"index": i, "name": m.name, "position": m.position})
    except Exception:
        pass
    return markers


def _regions(project) -> list[dict]:
    regions = []
    try:
        for i in range(project.n_regions):
            r = project.regions[i]
            regions.append({"index": i, "name": r.name, "start": r.start, "end": r.end})
    except Exception:
        pass
    return regions


def get_project_info() -> dict:
    """Get information about the current project: name, path, tempo, tracks, length."""
    project = get_project()
    return {
        "success": True,
        "name": project.name,
        "path": project.path,
        "tempo": project.bpm,
        "time_signature": f"{project.time_signature[0]}/{project.time_signature[1]}",
        "length": project.length,
        "track_count": project.n_tracks,
        "markers": _markers(project),
        "regions": _regions(project),
    }


def set_tempo(*, bpm: float) -> dict:
    """Set the project tempo in BPM."""
    project = get_project()
    project.bpm = bpm
    return {"success": True, "tempo": project.bpm}


def set_time_signature(*, numerator: int, denominator: int) -> dict:
    """Set the project time signature, e.g. 4/4, 3/4, 6/8."""
    project = get_project()
    project.time_signature = (numerator, denominator)
    return {"success": True, "time_signature": f"{numerator}/{denominator}"}


TOOLS = (
    create_project,
    save_project,
    load_project,
    get_project_info,
    set_tempo,
    set_time_signature,
)
