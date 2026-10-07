"""Track template tools: list and insert REAPER .RTrackTemplate files.

Insertion goes through RPR.Main_openProject(path_to_template), which is what
REAPER itself does for "Track: Insert track from template". That keeps exact FX
state, routing between the template's own tracks, folder structure, envelopes
and items. The alternative (parsing the file into <TRACK chunks and applying
them with SetTrackStateChunk) breaks multi-track templates because AUXRECV
lines reference track indices inside the template, which REAPER only remaps
on a native insert.

Main_openProject inserts after the *last touched* track, which is not
necessarily the selected one and not something an MCP client can observe.
So the insert is treated as "land somewhere", the new tracks are identified
by diffing track GUIDs before and after, and they are moved to the requested
position with ReorderSelectedTracks (default: end of the project).
"""

import difflib
from pathlib import Path
from typing import Any

from reaper_mcp.reaper import RPR, ensure_connected, get_project


TEMPLATE_SUFFIX = ".rtracktemplate"


def get_template_dir() -> Path:
    """REAPER's TrackTemplates folder, resolved from the running REAPER's resource path."""
    ensure_connected()
    return Path(RPR.GetResourcePath()) / "TrackTemplates"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'", "`"):
        return value[1:-1]
    return value


def parse_track_names(path: Path) -> list[str]:
    """Return the names of the top-level tracks stored in a template file.

    A .RTrackTemplate is a sequence of top-level <TRACK ...> chunks. Nested
    chunks (<FXCHAIN, <ITEM, ...) are skipped with a depth counter so that an
    item's or plugin's NAME line is never mistaken for the track name.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        return _top_level_track_names(raw.strip() for raw in f)


def _top_level_track_names(lines) -> list[str]:
    names: list[str] = []
    depth = 0
    for line in lines:
        if line.startswith("<"):
            if depth == 0 and line.startswith("<TRACK"):
                names.append("")
            depth += 1
        elif line == ">":
            depth -= 1
        elif depth == 1 and names and line.startswith("NAME"):
            names[-1] = _unquote(line[4:])
    return names


def find_templates(template_dir: Path) -> list[dict]:
    """Recursively list .RTrackTemplate files under template_dir.

    Subfolders are included because REAPER mirrors them as submenus in its
    own "Insert track from template" menu. The extension match is
    case-insensitive (files are usually .RTrackTemplate but not always).
    """
    if not template_dir.is_dir():
        return []
    results = []
    for path in sorted(template_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != TEMPLATE_SUFFIX:
            continue
        if any(part.startswith(".") for part in path.relative_to(template_dir).parts):
            continue
        rel = path.relative_to(template_dir).with_suffix("").as_posix()
        entry: dict[str, Any] = {
            "name": path.stem,
            "path": rel,
            "file": str(path),
        }
        try:
            track_names = parse_track_names(path)
            entry["track_count"] = len(track_names)
            entry["track_names"] = track_names
        except OSError as e:
            entry["track_count"] = None
            entry["track_names"] = []
            entry["parse_error"] = str(e)
        results.append(entry)
    return results


def resolve_template(name: str, template_dir: Path) -> Path:
    """Map a user-supplied template name to a template file.

    Accepts, in this order:
      1. an absolute/relative filesystem path to an existing template file
      2. the template's path relative to the TrackTemplates folder, with or
         without extension, any slash style, case-insensitive ("Vocals/Lead Vox")
      3. just the template name (file stem), case-insensitive, if it is unique
         across all subfolders

    Raises FileNotFoundError or ValueError (ambiguous) with a helpful message.
    """
    direct = Path(name).expanduser()
    if direct.is_file():
        return direct

    key = name.replace("\\", "/").strip().strip("/")
    if key.lower().endswith(TEMPLATE_SUFFIX):
        key = key[: -len(TEMPLATE_SUFFIX)]
    key_lower = key.lower()

    templates = find_templates(template_dir)
    if not templates:
        raise FileNotFoundError(f"No track templates found in {template_dir}")

    by_path = [t for t in templates if t["path"].lower() == key_lower]
    if len(by_path) == 1:
        return Path(by_path[0]["file"])

    by_name = [t for t in templates if t["name"].lower() == key_lower]
    if len(by_name) == 1:
        return Path(by_name[0]["file"])
    if len(by_name) > 1:
        options = ", ".join(t["path"] for t in by_name)
        raise ValueError(
            f"Template name '{name}' is ambiguous; use one of the full paths: {options}"
        )

    close = difflib.get_close_matches(
        key_lower, [t["path"].lower() for t in templates], n=5, cutoff=0.5
    )
    hint = ""
    if close:
        pretty = [t["path"] for t in templates if t["path"].lower() in close]
        hint = f" Did you mean: {', '.join(pretty)}?"
    raise FileNotFoundError(
        f"Track template '{name}' not found in {template_dir}.{hint} "
        "Use list_track_templates to see what is available."
    )


def _all_track_guids() -> list[str]:
    count = int(RPR.CountTracks(0))
    return [RPR.GetTrackGUID(RPR.GetTrack(0, i)) for i in range(count)]


def list_track_templates() -> dict:
    """
    List the track templates (.RTrackTemplate files) in REAPER's TrackTemplates folder,
    including subfolders. Each entry has 'name' (file name without extension), 'path'
    (relative to the TrackTemplates folder, e.g. "Vocals/Lead Vox"), the absolute 'file',
    and the names of the tracks the template contains.
    Pass either 'name' or 'path' to insert_track_template.
    """
    template_dir = get_template_dir()
    templates = find_templates(template_dir)
    return {
        "success": True,
        "template_directory": str(template_dir),
        "count": len(templates),
        "templates": templates,
    }

def insert_track_template(*, template: str, position: int | None = None) -> dict:
    """
    Insert a saved track template into the current project, exactly like REAPER's own
    "Insert track from template": FX with their saved state, routing, folder structure,
    envelopes and items are all preserved. Templates can contain several tracks.
    template: a name or path from list_track_templates ("Vocal Chain", "Vocals/Lead Vox"),
              or an absolute path to a .RTrackTemplate file.
    position: 0-based track index the template's first track should occupy. Existing
              tracks at that index and below are shifted down. Omit to append at the end.
    The inserted tracks are left selected, matching REAPER's behaviour.
    """
    template_dir = get_template_dir()
    path = resolve_template(template, template_dir)

    before = _all_track_guids()
    n_before = len(before)
    if position is None:
        position = n_before
    if not 0 <= position <= n_before:
        return {
            "success": False,
            "error": f"position must be between 0 and {n_before} (the project has "
                     f"{n_before} tracks); got {position}",
        }

    inserted_guids = _open_and_place(path, before, position)
    if not inserted_guids:
        return {
            "success": False,
            "error": f"REAPER did not insert any tracks from {path}. "
                     "Check that the file is a valid track template.",
        }
    tracks = _tracks_with_guids(inserted_guids)
    return {
        "success": True,
        "template": path.stem,
        "file": str(path),
        "inserted_count": len(tracks),
        "first_track_index": tracks[0]["index"],  # inserted_guids is never empty here
        "tracks": tracks,
    }


def _open_and_place(path: Path, before: list[str], position: int) -> set[str]:
    """Insert the template as one undo step and move its tracks to position.

    Returns the GUIDs of the inserted tracks (empty when REAPER inserted none).
    """
    RPR.Undo_BeginBlock2(0)
    RPR.PreventUIRefresh(1)
    try:
        RPR.Main_openProject(str(path))
        after = _all_track_guids()
        known = set(before)
        inserted = [i for i, guid in enumerate(after) if guid not in known]
        if inserted:
            _move_inserted(inserted, position)
        return {after[i] for i in inserted}
    finally:
        RPR.PreventUIRefresh(-1)
        RPR.Undo_EndBlock2(0, f"Insert track template: {path.stem}", -1)
        RPR.TrackList_AdjustWindows(False)
        RPR.UpdateArrange()


def _move_inserted(inserted: list[int], position: int) -> None:
    n_inserted = len(inserted)
    first = inserted[0]

    # Select exactly the inserted tracks so ReorderSelectedTracks moves
    # them and nothing else, and so the result matches REAPER's native
    # behaviour of leaving the new tracks selected.
    RPR.SetOnlyTrackSelected(RPR.GetTrack(0, first))
    for i in inserted[1:]:
        RPR.SetTrackSelected(RPR.GetTrack(0, i), True)

    if position != first:
        # Indices of pre-existing tracks at or after the landing spot
        # have shifted by n_inserted; translate the requested
        # position into the current numbering.
        before_idx = position if position < first else position + n_inserted
        RPR.ReorderSelectedTracks(before_idx, 0)


def _tracks_with_guids(guids: set[str]) -> list[dict]:
    project = get_project()
    return [
        {"index": i, "name": project.tracks[i].name}
        for i, guid in enumerate(_all_track_guids())
        if guid in guids
    ]

TOOLS = (
    list_track_templates,
    insert_track_template,
)
