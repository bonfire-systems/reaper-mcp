"""Rendering, and the render settings every audio-analysis tool depends on.

How REAPER takes render settings (verified on REAPER 7.82):
- RENDER_FILE is the output *directory* and RENDER_PATTERN the file name
  without extension; REAPER appends the format's extension. A full file path
  in RENDER_FILE becomes a directory of that name.
- RENDER_FORMAT is a base64 sink configuration, set as a string. A bare
  four-character type ("evaw", "calf", ...) selects that format's defaults;
  WAV's defaults are 32-bit float, so WAV always carries its bit depth.
- RENDER_BOUNDSFLAG: 1 = entire project, 2 = time selection (0 is custom
  start/end positions).

Rendering never reaches a REAPER dialog: with nothing to render REAPER shows
a modal "Nothing to render!", and with an existing target an overwrite
prompt, and either blocks the call until someone clicks. So an empty source
is refused before rendering and an existing target is removed first.
"""

import base64
import tempfile
import uuid
from pathlib import Path

from reaper_mcp.reaper import RPR, get_project

# "File: Render project, using the most recent render settings, auto-close
# render dialog". 41824 is the same without auto-close, which leaves REAPER's
# results window open after every render (spotted in PR #7).
RENDER_PROJECT = 42230
ENTIRE_PROJECT = 1
TIME_SELECTION = 2

FORMAT_TYPES = {"wav": b"evaw", "flac": b"calf", "mp3": b"l3pm", "ogg": b"vggo"}
WAV_BIT_DEPTHS = (16, 24, 32)  # 32 renders as float
SOLO_IN_PLACE = 2


def _format_config(format: str, bit_depth: int) -> str:
    fmt = format.lower()
    if fmt not in FORMAT_TYPES:
        raise ValueError(f"unsupported format {format!r}; use one of {sorted(FORMAT_TYPES)}")
    if fmt != "wav":
        return base64.b64encode(FORMAT_TYPES[fmt]).decode()
    if bit_depth not in WAV_BIT_DEPTHS:
        raise ValueError(f"unsupported WAV bit depth {bit_depth}; use one of {WAV_BIT_DEPTHS}")
    return base64.b64encode(FORMAT_TYPES[fmt] + bytes([bit_depth, 0, 1])).decode()


def _target(output_path: str, format: str) -> Path:
    """The file REAPER will write for output_path: its extension is the format's."""
    if format.lower() not in FORMAT_TYPES:
        raise ValueError(f"unsupported format {format!r}; use one of {sorted(FORMAT_TYPES)}")
    path = Path(output_path).expanduser().resolve()
    extension = "." + format.lower()
    if path.suffix.lower() in {"." + f for f in FORMAT_TYPES} and path.suffix.lower() != extension:
        raise ValueError(f"output_path {path.name!r} does not match format {format!r}")
    return path.with_suffix(extension)


def _render(target: Path, *, format: str, sample_rate: int, bit_depth: int,
            channels: int, bounds: int) -> None:
    """Configure REAPER's render settings and render to target."""
    config = _format_config(format, bit_depth)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)  # an existing file raises REAPER's overwrite prompt
    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", str(target.parent), True)
    RPR.GetSetProjectInfo_String(0, "RENDER_PATTERN", target.stem, True)
    RPR.GetSetProjectInfo_String(0, "RENDER_FORMAT", config, True)
    RPR.GetSetProjectInfo(0, "RENDER_SRATE", float(sample_rate), True)
    RPR.GetSetProjectInfo(0, "RENDER_CHANNELS", float(channels), True)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(bounds), True)
    RPR.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0.0, True)
    RPR.Main_OnCommand(RENDER_PROJECT, 0)


def _require_content(project) -> None:
    if project.length <= 0:
        raise RuntimeError("the project is empty; there is nothing to render")


def render_to_temp_file(sample_rate: int = 48000) -> str:
    """
    Render the current project to a temporary WAV file and return its path.
    Used by analysis and mastering tools. Caller is responsible for deleting the file.
    """
    _require_content(get_project())
    target = Path(tempfile.gettempdir()) / f"reaper-mcp-{uuid.uuid4().hex}.wav"
    _render(target, format="wav", sample_rate=sample_rate, bit_depth=24, channels=2,
            bounds=ENTIRE_PROJECT)
    return str(target)


def _rendered(target: Path) -> dict:
    if not target.is_file():
        return {"success": False, "error": f"REAPER did not write {target}"}
    return {"success": True, "output_path": str(target),
            "file_size_bytes": target.stat().st_size}


def render_project(
    *,
    output_path: str,
    format: str = "wav",
    sample_rate: int = 48000,
    bit_depth: int = 24,
    channels: int = 2,
) -> dict:
    """
    Render the entire project to a file.
    format: wav, flac, mp3 (requires LAME), ogg.
    sample_rate: e.g. 44100, 48000, 96000.
    bit_depth: 16, 24, or 32 (WAV only; ignored for mp3/ogg/flac).
    channels: 1 (mono) or 2 (stereo).
    """
    target = _target(output_path, format)
    _require_content(get_project())
    _render(target, format=format, sample_rate=sample_rate, bit_depth=bit_depth,
            channels=channels, bounds=ENTIRE_PROJECT)
    result = _rendered(target)
    if result["success"]:
        result.update(format=format, sample_rate=sample_rate, bit_depth=bit_depth,
                      channels=channels)
    return result


def render_time_selection(
    *,
    output_path: str,
    start: float,
    end: float,
    format: str = "wav",
    sample_rate: int = 48000,
    bit_depth: int = 24,
    channels: int = 2,
) -> dict:
    """Render a specific time range of the project to a file."""
    target = _target(output_path, format)
    if not 0 <= start < end:
        return {"success": False, "error": f"need 0 <= start < end; got start={start}, end={end}"}
    project = get_project()
    _require_content(project)
    selection = project.time_selection  # a reapy TimeSelection, not a tuple
    previous = (selection.start, selection.end)
    project.time_selection = (start, end)
    try:
        _render(target, format=format, sample_rate=sample_rate, bit_depth=bit_depth,
                channels=channels, bounds=TIME_SELECTION)
    finally:
        project.time_selection = previous
    result = _rendered(target)
    if result["success"]:
        result.update(start=start, end=end, format=format)
    return result


def render_stems(
    *,
    output_directory: str,
    track_indices: list[int] | None = None,
    format: str = "wav",
    sample_rate: int = 48000,
    bit_depth: int = 24,
) -> dict:
    """
    Render each track as a separate stem file by soloing each track individually.
    track_indices: list of track indices, or null to render all tracks.
    Files are named after the track names in the output directory.
    """
    directory = Path(output_directory).expanduser().resolve()
    project = get_project()
    _require_content(project)
    indices = track_indices if track_indices is not None else list(range(project.n_tracks))
    tracks = project.tracks
    names = _stem_names([tracks[i].name or f"Track_{i}" for i in indices])
    solos = [track.get_info_value("I_SOLO") for track in tracks]
    try:
        stems = [
            _render_stem(tracks, index, directory / f"{file_name}.{format.lower()}",
                         format=format, sample_rate=sample_rate, bit_depth=bit_depth)
            for index, file_name in zip(indices, names, strict=True)
        ]
    finally:
        for track, solo in zip(tracks, solos, strict=True):
            track.set_info_value("I_SOLO", solo)
    return {"success": True, "output_directory": str(directory), "stems": stems}


def _stem_names(track_names: list[str]) -> list[str]:
    """File-safe, unique names: a second "Kick" becomes "Kick_2"."""
    seen: dict[str, int] = {}
    names = []
    for raw in track_names:
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in raw)
        seen[safe] = seen.get(safe, 0) + 1
        names.append(safe if seen[safe] == 1 else f"{safe}_{seen[safe]}")
    return names


def _render_stem(tracks, index: int, target: Path, *, format: str,
                 sample_rate: int, bit_depth: int) -> dict:
    # Solo through I_SOLO: reapy's solo() goes through an action that leaves
    # solo unchanged (tests/contract).
    for i, track in enumerate(tracks):
        track.set_info_value("I_SOLO", SOLO_IN_PLACE if i == index else 0)
    _render(target, format=format, sample_rate=sample_rate, bit_depth=bit_depth,
            channels=2, bounds=ENTIRE_PROJECT)
    return {
        "track_index": index,
        "track_name": tracks[index].name or f"Track_{index}",
        "output_path": str(target),
        "exists": target.is_file(),
    }


TOOLS = (
    render_project,
    render_time_selection,
    render_stems,
)

