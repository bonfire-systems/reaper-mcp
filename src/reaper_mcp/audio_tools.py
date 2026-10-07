import os
import logging
from reaper_mcp.reaper import RPR, get_project



logger = logging.getLogger("reaper_mcp.audio_tools")



def import_audio_file(*, file_path: str, track_index: int, position: float = 0.0) -> dict:
    """
    Import an audio file onto a track at the given position (seconds).
    Supports all formats REAPER can read: wav, aiff, mp3, flac, ogg, etc.
    """
    if not os.path.exists(file_path):
        return {"success": False, "error": f"File not found: {file_path}"}
    project = get_project()
    track = project.tracks[track_index]
    # Select only this track, set cursor, then insert media at cursor
    RPR.SetOnlyTrackSelected(track.id)
    project.cursor_position = position
    RPR.InsertMedia(file_path, 0)
    # Retrieve the item that was just created (last item on the track)
    track_refreshed = project.tracks[track_index]
    if track_refreshed.n_items == 0:
        return {"success": False, "error": "Insert succeeded but no item found on track"}
    item = track_refreshed.items[track_refreshed.n_items - 1]
    return {
        "success": True,
        "track_index": track_index,
        "item_index": track_refreshed.n_items - 1,
        "position": item.position,
        "length": item.length,
        "file_path": file_path,
    }

def start_recording(*, track_index: int) -> dict:
    """Arm a track and start recording. Call stop_transport when done."""
    project = get_project()
    track = project.tracks[track_index]
    track.armed = True
    RPR.Main_OnCommand(1013, 0)  # Transport: Record
    return {
        "success": True,
        "track_index": track_index,
        "message": "Recording started. Call stop_transport to stop.",
    }

def stop_transport() -> dict:
    """Stop playback or recording."""
    RPR.Main_OnCommand(1016, 0)  # Transport: Stop
    return {"success": True, "message": "Transport stopped"}

def play_project() -> dict:
    """Start project playback from the current cursor position."""
    RPR.Main_OnCommand(1007, 0)  # Transport: Play
    return {"success": True, "message": "Playback started"}

def set_cursor_position(*, position: float) -> dict:
    """Move the edit cursor to a position in seconds."""
    project = get_project()
    project.cursor_position = position
    return {"success": True, "position": project.cursor_position}

def edit_audio_item(
    *,
    track_index: int,
    item_index: int,
    start_trim: float = 0.0,
    end_trim: float = 0.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> dict:
    """
    Trim an audio item and/or add fades. All values in seconds.
    start_trim: seconds to remove from the beginning.
    end_trim: seconds to remove from the end.
    fade_in/fade_out: fade length in seconds.
    """
    project = get_project()
    track = project.tracks[track_index]
    item = track.items[item_index]

    if start_trim > 0:
        item.position += start_trim
        item.length -= start_trim
        take = item.active_take
        if take:
            take.start_offset += start_trim

    if end_trim > 0:
        item.length -= end_trim

    if fade_in > 0:
        item.fade_in_length = fade_in

    if fade_out > 0:
        item.fade_out_length = fade_out

    return {
        "success": True,
        "track_index": track_index,
        "item_index": item_index,
        "position": item.position,
        "length": item.length,
    }

def adjust_pitch(*, track_index: int, item_index: int, semitones: float) -> dict:
    """Adjust the pitch of an audio item by semitones (can be fractional)."""
    project = get_project()
    track = project.tracks[track_index]
    item = track.items[item_index]
    take = item.active_take
    take.pitch = semitones
    return {
        "success": True,
        "track_index": track_index,
        "item_index": item_index,
        "pitch_semitones": take.pitch,
    }

def adjust_playback_rate(*, track_index: int, item_index: int, rate: float) -> dict:
    """Adjust playback rate of an audio item. 1.0 = normal speed, 0.5 = half speed."""
    project = get_project()
    track = project.tracks[track_index]
    item = track.items[item_index]
    take = item.active_take
    take.playback_rate = rate
    return {
        "success": True,
        "track_index": track_index,
        "item_index": item_index,
        "playback_rate": take.playback_rate,
    }


TOOLS = (
    import_audio_file,
    start_recording,
    stop_transport,
    play_project,
    set_cursor_position,
    edit_audio_item,
    adjust_pitch,
    adjust_playback_rate,
)
