"""Rendering, and the render settings every audio-analysis tool depends on.

How REAPER takes render settings (verified on REAPER 7.82):
- RENDER_FILE is the output *directory* and RENDER_PATTERN the file name
  without extension; REAPER appends the format's extension. A full file path
  in RENDER_FILE becomes a directory of that name.
- RENDER_FORMAT is a base64 sink configuration, set as a string. A bare
  four-character type ("evaw", "calf", ...) selects that format's defaults;
  WAV's defaults are 32-bit float, so WAV always carries its bit depth.
- RENDER_BOUNDSFLAG: 1 = entire project, 2 = time selection, 3 = all regions,
  5 = selected regions (0 is custom start/end positions).

Rendering never reaches a REAPER dialog: with nothing to render REAPER shows
a modal "Nothing to render!", and with an existing target an overwrite
prompt, and either blocks the call until someone clicks. So an empty source
is refused before rendering and an existing target is removed first, except
by render_regions, which refuses existing targets rather than delete them.
"""

import base64
import os
import tempfile
import time
import uuid
from pathlib import Path

from reaper_mcp.project_tools import markers_and_regions
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


# ---------------------------------------------------------------------------
# Region rendering
#
# Encoding is left to the project's own render settings. Only the output
# directory, the file name pattern and the bounds are changed, and all three
# are restored on return.
# ---------------------------------------------------------------------------

ALL_REGIONS = 3
SELECTED_REGIONS = 5


def _get_str(key: str) -> str:
    # reapy returns the out-parameters: (ok, project, key, value, is_set).
    result = RPR.GetSetProjectInfo_String(0, key, "", False)
    assert isinstance(result, (tuple, list)), result
    return str(result[3])


def _set_str(key: str, value: str) -> None:
    RPR.GetSetProjectInfo_String(0, key, value, True)


def _parse_render_targets(raw: str | None, directory: str | None = None) -> list[str]:
    """Split REAPER's semicolon-separated RENDER_TARGETS into paths.

    Region names may themselves contain ';', which would corrupt a naive split.
    When the output directory is known, split on the ';' that immediately
    precedes it instead, so only real separators are matched.
    """
    if not raw or not raw.strip():
        return []
    raw = raw.strip().rstrip(";")
    if directory:
        chunks = raw.split(";" + directory)
        parts = [chunks[0]] + [directory + chunk for chunk in chunks[1:]]
    else:
        parts = raw.split(";")
    return [part.strip() for part in parts if part.strip()]


def _conflicting_targets(targets: list[str]) -> list[str]:
    """Targets that already exist on disk. Rendering over one opens REAPER's
    overwrite prompt (see the module docstring), so they are refused first."""
    return [t for t in targets if os.path.exists(t)]


def _render_in_flight(directory: str) -> bool:
    """True while the directory holds a `.sb-` file, which is treated as a
    render still in progress (see _await_render)."""
    if not directory or not os.path.isdir(directory):
        return False
    for entry in os.scandir(directory):
        try:
            if entry.is_file() and ".sb-" in entry.name:
                return True
        except OSError:
            continue
    return False


def _directory_activity(directory: str) -> tuple[int, int]:
    """(file count, total bytes) for a directory, scratch files included."""
    if not directory or not os.path.isdir(directory):
        return (0, 0)
    count = total = 0
    for entry in os.scandir(directory):
        try:
            if entry.is_file():
                count += 1
                total += entry.stat().st_size
        except OSError:
            continue
    return (count, total)


def _await_render(targets: list[str], *, stall_timeout: float = 120.0,
                  timeout: float = 3600.0, poll_interval: float = 1.0,
                  scratch_grace: float | None = None) -> tuple[list[dict], str]:
    """Wait for a render to finish. Returns (files, status), status being
    "complete", "stalled" or "timeout"."""
    # Completion is read from the filesystem, without calling REAPER: the
    # render is complete once every expected target exists at a stable
    # non-zero size, whether or not action 42230 returned first. Only the
    # known targets count as output; progress (any change in the directory's
    # file count or size) is measured across the whole directory, so a render
    # that stops writing trips stall_timeout instead of running to timeout.
    # While a `.sb-` file is present, quiet time is tolerated up to
    # scratch_grace (3x stall_timeout), because giving up restores the render
    # settings.
    #
    # Observed on REAPER 7.75 rendering two 60 s WAV regions: 42230 returned
    # after both files were complete, and no `.sb-` file appeared.
    def collect() -> list[dict]:
        return [{"path": t, "size_bytes": os.path.getsize(t)}
                for t in targets if os.path.exists(t)]

    if not targets:
        return [], "complete"

    directory = os.path.dirname(targets[0])
    if scratch_grace is None:
        scratch_grace = stall_timeout * 3
    deadline = time.time() + timeout
    last_activity = time.time()
    activity = _directory_activity(directory)
    previous, stable = None, 0

    while time.time() < deadline:
        current = _directory_activity(directory)
        if current != activity:
            activity, last_activity = current, time.time()

        sizes = {t: os.path.getsize(t) for t in targets if os.path.exists(t)}
        finished = len(sizes) == len(targets) and all(size > 0 for size in sizes.values())
        if finished and sizes == previous:
            stable += 1
            if stable >= 3:
                return collect(), "complete"
        else:
            stable = 0
        previous = sizes

        quiet = time.time() - last_activity
        limit = scratch_grace if _render_in_flight(directory) else stall_timeout
        if quiet > limit:
            return collect(), "stalled"
        time.sleep(poll_interval)
    return collect(), "timeout"


def render_regions(
    *,
    output_directory: str,
    pattern: str = "$region",
    selected_only: bool = False,
    dry_run: bool = False,
    stall_timeout_seconds: float = 120.0,
    timeout_seconds: float = 3600.0,
) -> dict:
    """
    Render each region of the project to its own file, using the project's
    render settings.
    pattern: file name pattern; $region, $regionnumber, $project are available.
    selected_only: render only the regions selected in REAPER; with none
        selected, REAPER renders all of them.
    dry_run: return the regions and the files REAPER would write, without rendering.
    Fails without rendering if any output file already exists; never deletes files.
    Blocks until the render finishes, gives up after stall_timeout_seconds with
    nothing written, or timeout_seconds in total; status is "complete",
    "stalled" or "timeout".
    Region "index" is the position among regions, as in get_project_info.
    """
    # The render settings must stay in place until REAPER is done with them,
    # which is why the call blocks: an async mode would need a job API.
    directory = str(Path(output_directory).expanduser().resolve())
    regions = markers_and_regions()[1]
    if not regions:
        return {"success": False, "error": "no regions are defined in the current project"}

    saved = {key: _get_str(key) for key in ("RENDER_FILE", "RENDER_PATTERN")}
    saved_bounds = RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0.0, False)
    try:
        _set_str("RENDER_FILE", directory)
        _set_str("RENDER_PATTERN", pattern)
        RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG",
                              float(SELECTED_REGIONS if selected_only else ALL_REGIONS), True)
        # REAPER resolves the pattern per region itself, including names, so
        # its own RENDER_TARGETS is the authority on what will be written.
        targets = _parse_render_targets(_get_str("RENDER_TARGETS"), directory)
        if not targets:
            return {"success": False, "error": "REAPER reported no render targets"}
        clashes = _conflicting_targets(targets)
        if dry_run:
            return {"success": True, "dry_run": True, "already_exist": clashes,
                    "output_directory": directory, "region_count": len(regions),
                    "regions": regions, "would_write": targets}
        if clashes:
            return {"success": False,
                    "error": f"{len(clashes)} output file(s) already exist; render_regions "
                             "does not render over existing files. Move or delete them, "
                             "or render into an empty directory.",
                    "already_exist": clashes}

        os.makedirs(directory, exist_ok=True)
        started = time.time()
        RPR.Main_OnCommand(RENDER_PROJECT, 0)
        written, status = _await_render(
            targets, stall_timeout=stall_timeout_seconds, timeout=timeout_seconds)
        complete = status == "complete"
        result = {"success": complete, "output_directory": directory,
                  "region_count": len(regions), "files_written": len(written),
                  "files": written, "expected": targets, "status": status,
                  "elapsed_seconds": round(time.time() - started, 1)}
        if not complete:
            result["error"] = (f"render did not finish ({status}): wrote {len(written)} of "
                               f"{len(targets)} expected files")
        return result
    finally:
        for key, value in saved.items():
            _set_str(key, value)
        RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", saved_bounds, True)


TOOLS = (
    render_project,
    render_time_selection,
    render_stems,
    render_regions,
)

