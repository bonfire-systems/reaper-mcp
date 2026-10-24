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
    _set_str("RENDER_FILE", str(target.parent))
    _set_str("RENDER_PATTERN", target.stem)
    _set_str("RENDER_FORMAT", config)
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
# directory, the file name pattern, the bounds and RENDER_ADDTOPROJ are
# changed, and all four are restored on return.
# ---------------------------------------------------------------------------

ALL_REGIONS = 3
SELECTED_REGIONS = 5
REGION_STRINGS = ("RENDER_FILE", "RENDER_PATTERN")
REGION_NUMBERS = ("RENDER_BOUNDSFLAG", "RENDER_ADDTOPROJ")


def _get_str(key: str) -> str:
    # reapy returns the out-parameters: (ok, project, key, value, is_set).
    result = RPR.GetSetProjectInfo_String(0, key, "", False)
    assert isinstance(result, (tuple, list)), result
    return str(result[3])


def _set_str(key: str, value: str) -> None:
    RPR.GetSetProjectInfo_String(0, key, value, True)


def _parse_render_targets(raw: str | None, directory: str) -> list[str]:
    """Split REAPER's semicolon-separated RENDER_TARGETS into paths.

    Region names may themselves contain ';', which would corrupt a naive split,
    so split on the ';' that immediately precedes the output directory. That
    only works if REAPER spells the directory as given; when it does not, the
    split cannot be trusted, so it is an error rather than a guess.
    """
    raw = (raw or "").strip().rstrip(";")
    if not raw:
        return []
    prefix = directory.rstrip(os.sep) + os.sep
    chunks = raw.split(";" + prefix)
    targets = [chunks[0]] + [prefix + chunk for chunk in chunks[1:]]
    stray = [t for t in targets if not t.startswith(prefix)]
    if stray:
        raise RuntimeError(f"REAPER reported render targets not in {directory}: {stray}")
    return targets


def _duplicate_targets(targets: list[str]) -> list[str]:
    """Targets listed more than once. REAPER 7.82 numbers clashing names itself
    ("take-001", "take-002"), but a repeat would leave _await_render waiting
    for more distinct files than will ever exist, so it is refused first."""
    return sorted({t for t in targets if targets.count(t) > 1})


def _conflicting_targets(targets: list[str]) -> list[str]:
    """Targets that already exist on disk. Rendering over one opens REAPER's
    overwrite prompt (see the module docstring), so they are refused first."""
    return [t for t in targets if os.path.exists(t)]


def _watched_sizes(targets: list[str]) -> dict[str, int]:
    """Sizes, by path, of the targets and of their `<name>.sb-<hash>` scratch
    files that exist now. Nothing else is watched, so a busy folder or another
    render's leftovers cannot pass for progress. A pattern can put targets in
    several directories ("$region/mix"), so each one is read."""
    sizes: dict[str, int] = {}
    for directory in {os.path.dirname(t) for t in targets}:
        sizes.update(_sizes_in(directory, set(targets)))
    return sizes


def _sizes_in(directory: str, targets: set[str]) -> dict[str, int]:
    # <name> was seen on macOS without saying whether it keeps the extension,
    # so a scratch file named after either spelling counts.
    stems = {os.path.splitext(t)[0] for t in targets}
    try:
        entries = list(os.scandir(directory))
    except OSError:  # not created yet
        return {}
    sizes = {}
    for entry in entries:
        stem, scratch, _ = entry.path.rpartition(".sb-")
        if entry.path in targets or (scratch and (stem in targets or stem in stems)):
            try:
                sizes[entry.path] = entry.stat().st_size
            except OSError:  # removed since the scan, as REAPER does with scratch files
                continue
    return sizes


def _await_render(targets: list[str], *, stall_timeout: float = 120.0,
                  timeout: float = 3600.0, poll_interval: float = 1.0,
                  scratch_grace: float | None = None) -> tuple[list[dict], str]:
    """Wait for a render to finish. Returns (files, status), status being
    "complete", "stalled" or "timeout"."""
    # Completion is read from the filesystem, without calling REAPER: the
    # render is complete once every expected target exists at a stable
    # non-zero size, whether or not action 42230 returned first. Progress is
    # any change in the targets or their own scratch files (_watched_sizes),
    # so a render that stops writing trips stall_timeout instead of running to
    # timeout. While a target's `.sb-` file is present, quiet time is tolerated
    # up to scratch_grace (3x stall_timeout), because giving up restores the
    # render settings. One snapshot per poll feeds all of it, so a file that
    # disappears between checks cannot raise.
    #
    # Observed on REAPER 7.75 rendering two 60 s WAV regions: 42230 returned
    # after both files were complete, and no `.sb-` file appeared. On REAPER
    # 7.82 / Linux, WAV, FLAC, MP3, OGG and H.264 MP4 all wrote the target
    # directly, with no `.sb-` file; the longest pause between writes was 10 s
    # (a 2-minute black MP4), against the 120 s stall_timeout default.
    if not targets:
        return [], "complete"

    if scratch_grace is None:
        scratch_grace = stall_timeout * 3
    deadline = time.time() + timeout
    last_activity = time.time()
    watched = _watched_sizes(targets)
    stable = 0

    while time.time() < deadline:
        current = _watched_sizes(targets)
        sizes = [current[t] for t in targets if t in current]
        finished = len(sizes) == len(targets) and all(size > 0 for size in sizes)
        stable = stable + 1 if finished and current == watched else 0
        if stable >= 3:
            return _files(targets, current), "complete"
        if current != watched:
            watched, last_activity = current, time.time()

        quiet = time.time() - last_activity
        in_flight = not current.keys() <= set(targets)  # a scratch file is open
        limit = scratch_grace if in_flight else stall_timeout
        if quiet > limit:
            return _files(targets, current), "stalled"
        time.sleep(poll_interval)
    return _files(targets, watched), "timeout"


def _files(targets: list[str], sizes: dict[str, int]) -> list[dict]:
    return [{"path": t, "size_bytes": sizes[t]} for t in targets if t in sizes]


def _render_regions(directory: str, regions: list, *, pattern: str, selected_only: bool,
                    dry_run: bool, stall_timeout: float, timeout: float) -> dict:
    _set_str("RENDER_FILE", directory)
    _set_str("RENDER_PATTERN", pattern)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG",
                          float(SELECTED_REGIONS if selected_only else ALL_REGIONS), True)
    # Off, as _render sets it: "add rendered items to the project" would add an
    # item per region, and its "skip silent files" bit would leave a silent
    # region without a file, which reads as a stall.
    RPR.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0.0, True)
    # REAPER resolves the pattern per region itself, including names and the
    # numbering of clashing names, so its own RENDER_TARGETS is the authority
    # on what will be written.
    targets = _parse_render_targets(_get_str("RENDER_TARGETS"), directory)
    if not targets:
        return {"success": False, "error": "REAPER reported no render targets"}
    duplicates = _duplicate_targets(targets)
    if duplicates:
        return {"success": False,
                "error": "REAPER reported the same output file more than once; "
                         "render_regions cannot tell when such a render is done.",
                "duplicates": duplicates}
    clashes = _conflicting_targets(targets)
    counts = {"total_regions": len(regions), "target_count": len(targets)}
    if dry_run:
        return {"success": True, "dry_run": True, "already_exist": clashes,
                "output_directory": directory, **counts, "regions": regions,
                "would_write": targets}
    if clashes:
        return {"success": False,
                "error": f"{len(clashes)} output file(s) already exist; render_regions "
                         "does not render over existing files. Move or delete them, "
                         "or render into an empty directory.",
                "already_exist": clashes}

    os.makedirs(directory, exist_ok=True)
    started = time.time()
    RPR.Main_OnCommand(RENDER_PROJECT, 0)
    written, status = _await_render(targets, stall_timeout=stall_timeout, timeout=timeout)
    complete = status == "complete"
    result = {"success": complete, "output_directory": directory, **counts,
              "files_written": len(written), "files": written, "expected": targets,
              "status": status, "elapsed_seconds": round(time.time() - started, 1)}
    if not complete:
        result["error"] = (f"render did not finish ({status}): wrote {len(written)} of "
                           f"{len(targets)} expected files")
    return result


def _save_render_settings() -> tuple[dict[str, str], dict[str, float]]:
    return ({key: _get_str(key) for key in REGION_STRINGS},
            {key: RPR.GetSetProjectInfo(0, key, 0.0, False) for key in REGION_NUMBERS})


def _restore_render_settings(strings: dict[str, str], numbers: dict[str, float]) -> list[str]:
    """Put each setting back on its own, so one failure (say, a client that
    disconnected during a long render) does not leave the rest unrestored.
    Returns the failures as "KEY: error"."""
    errors = []
    for key, value in strings.items():
        try:
            _set_str(key, value)
        except Exception as e:
            errors.append(f"{key}: {e}")
    for key, number in numbers.items():
        try:
            RPR.GetSetProjectInfo(0, key, number, True)
        except Exception as e:
            errors.append(f"{key}: {e}")
    return errors


def _with_restore_errors(error: str | None, restore_errors: list[str]) -> str:
    note = "render settings not restored: " + "; ".join(restore_errors)
    return f"{error.rstrip('.')}; {note}" if error else note


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
    pattern: file name pattern; $region, $regionnumber, $project are available,
        and it may name subdirectories. REAPER numbers names that would clash
        ("take-001", "take-002").
    selected_only: render only the regions selected in REAPER; with none
        selected, REAPER renders all of them.
    dry_run: return the project's regions and the files REAPER would write,
        without rendering. It sets the render settings and restores them.
    Fails without rendering if any output file already exists; never deletes files.
    Blocks until every file is written; status is then "complete". Gives up
    with "stalled" once the files stop growing for stall_timeout_seconds
    (longer while REAPER holds a scratch file), or "timeout" after
    timeout_seconds in total.
    Region "index" is the position among regions, as in get_project_info.
    """
    # The render settings must stay in place until REAPER is done with them,
    # which is why the call blocks: an async mode would need a job API.
    if stall_timeout_seconds <= 0 or timeout_seconds <= 0:
        raise ValueError("stall_timeout_seconds and timeout_seconds must be positive")
    directory = str(Path(output_directory).expanduser().resolve())
    regions = markers_and_regions()[1]
    if not regions:
        return {"success": False, "error": "no regions are defined in the current project"}

    strings, numbers = _save_render_settings()
    try:
        result = _render_regions(
            directory, regions, pattern=pattern, selected_only=selected_only,
            dry_run=dry_run, stall_timeout=stall_timeout_seconds, timeout=timeout_seconds)
    except Exception as e:
        restore_errors = _restore_render_settings(strings, numbers)
        if restore_errors:
            raise RuntimeError(_with_restore_errors(str(e), restore_errors)) from e
        raise
    restore_errors = _restore_render_settings(strings, numbers)
    if restore_errors:
        # The files may be complete, but the project was left changed, so the
        # call did not do everything it reports.
        result.update(success=False, restore_errors=restore_errors,
                      error=_with_restore_errors(result.get("error"), restore_errors))
    return result


TOOLS = (
    render_project,
    render_time_selection,
    render_stems,
    render_regions,
)

