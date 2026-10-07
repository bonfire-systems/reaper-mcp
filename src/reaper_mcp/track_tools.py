from reaper_mcp.reaper import RPR, get_project
from reaper_mcp.units import db_to_linear, linear_to_db


def create_track(*, name: str, track_type: str = "audio") -> dict:
    """
    Create a new track at the end of the project.
    track_type: audio, midi, instrument, folder
    """
    project = get_project()
    idx = project.n_tracks
    project.add_track(idx, name)
    track = project.tracks[idx]

    if track_type in ("midi", "instrument"):
        RPR.SetMediaTrackInfo_Value(track.id, "I_RECINPUT", 4096)  # All MIDI inputs
    elif track_type == "folder":
        RPR.SetMediaTrackInfo_Value(track.id, "I_FOLDERDEPTH", 1)

    return {
        "success": True,
        "track_index": idx,
        "name": track.name,
        "type": track_type,
    }

def delete_track(*, track_index: int) -> dict:
    """Delete a track by its index."""
    project = get_project()
    track = project.tracks[track_index]
    RPR.DeleteTrack(track.id)
    return {"success": True, "deleted_index": track_index}

def rename_track(*, track_index: int, name: str) -> dict:
    """Rename a track."""
    project = get_project()
    track = project.tracks[track_index]
    track.name = name
    return {"success": True, "track_index": track_index, "name": track.name}

# REAPER's I_SOLO: 0 = not soloed, 2 = soloed in place (REAPER's default solo).
SOLO_IN_PLACE = 2


def set_track_volume(*, track_index: int, volume_db: float) -> dict:
    """Set track volume in dB. Range: roughly -150 to +12 dB."""
    track = get_project().tracks[track_index]
    track.set_info_value("D_VOL", db_to_linear(volume_db))
    return {"success": True, "track_index": track_index, "volume_db": _volume_db(track)}


def set_track_pan(*, track_index: int, pan: float) -> dict:
    """Set track pan. -1.0 = full left, 0.0 = center, 1.0 = full right."""
    track = get_project().tracks[track_index]
    track.set_info_value("D_PAN", pan)
    return {"success": True, "track_index": track_index, "pan": track.get_info_value("D_PAN")}


def set_track_mute(*, track_index: int, muted: bool) -> dict:
    """Mute or unmute a track."""
    track = get_project().tracks[track_index]
    track.set_info_value("B_MUTE", 1 if muted else 0)
    return {"success": True, "track_index": track_index, "muted": track.is_muted}


def set_track_solo(*, track_index: int, soloed: bool) -> dict:
    """Solo or unsolo a track."""
    # Through I_SOLO: reapy's solo() and is_solo setter go through an action
    # that leaves solo unchanged (tests/contract).
    track = get_project().tracks[track_index]
    track.set_info_value("I_SOLO", SOLO_IN_PLACE if soloed else 0)
    return {"success": True, "track_index": track_index, "soloed": track.is_solo}


def _volume_db(track) -> float:
    return round(linear_to_db(track.get_info_value("D_VOL")), 2)


def _mix_state(track) -> dict:
    return {
        "volume_db": _volume_db(track),
        "pan": track.get_info_value("D_PAN"),
        "muted": track.is_muted,
        "soloed": track.is_solo,
    }


def _item_summary(index: int, item) -> dict:
    take = item.active_take
    return {
        "index": index,
        "position": item.position,
        "length": item.length,
        "name": take.name if take else "",
    }


def get_track_info(*, track_index: int) -> dict:
    """Get detailed information about a track including FX and items."""
    track = get_project().tracks[track_index]
    fx_list = [
        {"index": i, "name": fx.name, "enabled": fx.is_enabled} for i, fx in enumerate(track.fxs)
    ]
    items = [_item_summary(i, item) for i, item in enumerate(track.items)]
    return {
        "success": True,
        "track_index": track_index,
        "name": track.name,
        **_mix_state(track),
        "fx_count": len(fx_list),
        "fx": fx_list,
        "item_count": len(items),
        "items": items,
    }


def list_tracks() -> dict:
    """List all tracks in the current project with their basic parameters."""
    tracks = [
        {
            "index": i,
            "name": track.name,
            **_mix_state(track),
            "fx_count": track.n_fxs,
            "item_count": track.n_items,
        }
        for i, track in enumerate(get_project().tracks)
    ]
    return {"success": True, "count": len(tracks), "tracks": tracks}


def set_track_color(*, track_index: int, r: int, g: int, b: int) -> dict:
    """Set track color using RGB values (0–255 each)."""
    project = get_project()
    track = project.tracks[track_index]
    color = RPR.ColorToNative(r, g, b) | 0x1000000
    RPR.SetMediaTrackInfo_Value(track.id, "I_CUSTOMCOLOR", color)
    return {"success": True, "track_index": track_index, "r": r, "g": g, "b": b}


TOOLS = (
    create_track,
    delete_track,
    rename_track,
    set_track_volume,
    set_track_pan,
    set_track_mute,
    set_track_solo,
    get_track_info,
    list_tracks,
    set_track_color,
)
