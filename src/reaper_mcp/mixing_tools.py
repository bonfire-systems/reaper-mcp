from reaper_mcp.reaper import RPR, get_project
from reaper_mcp.units import db_to_linear




def add_volume_automation(*, track_index: int, position: float, value_db: float) -> dict:
    """
    Add a volume automation point on a track.
    The volume envelope must be visible in REAPER (right-click track > Show envelope).
    position: time in seconds. value_db: volume level in dB.
    """
    project = get_project()
    track = project.tracks[track_index]
    envelope = RPR.GetTrackEnvelopeByName(track.id, "Volume")
    if not envelope:
        return {
            "success": False,
            "error": (
                "Volume envelope not found. Show it first: right-click the track "
                "in REAPER and choose 'Show envelope for track volume'."
            ),
        }
    linear_val = db_to_linear(value_db)
    RPR.InsertEnvelopePoint(envelope, position, linear_val, 0, 0, False, True)
    RPR.Envelope_SortPoints(envelope)
    return {"success": True, "track_index": track_index, "position": position, "value_db": value_db}

def add_pan_automation(*, track_index: int, position: float, pan: float) -> dict:
    """
    Add a pan automation point on a track.
    The pan envelope must be visible in REAPER.
    pan: -1.0 (full left) to 1.0 (full right).
    """
    project = get_project()
    track = project.tracks[track_index]
    envelope = RPR.GetTrackEnvelopeByName(track.id, "Pan")
    if not envelope:
        return {
            "success": False,
            "error": (
                "Pan envelope not found. Show it first: right-click the track "
                "in REAPER and choose 'Show envelope for track pan'."
            ),
        }
    RPR.InsertEnvelopePoint(envelope, position, pan, 0, 0, False, True)
    RPR.Envelope_SortPoints(envelope)
    return {"success": True, "track_index": track_index, "position": position, "pan": pan}

def create_send(
    *,
    source_track_index: int, dest_track_index: int, volume_db: float = 0.0
) -> dict:
    """Create an aux send from one track to another."""
    project = get_project()
    src = project.tracks[source_track_index]
    dst = project.tracks[dest_track_index]
    send_idx = RPR.CreateTrackSend(src.id, dst.id)
    if send_idx < 0:
        return {"success": False, "error": "Failed to create send"}
    RPR.SetTrackSendInfo_Value(src.id, 0, send_idx, "D_VOL", db_to_linear(volume_db))
    return {
        "success": True,
        "source_track_index": source_track_index,
        "dest_track_index": dest_track_index,
        "send_index": send_idx,
        "volume_db": volume_db,
    }

def list_sends(*, track_index: int) -> dict:
    """List all sends from a track."""
    project = get_project()
    track = project.tracks[track_index]
    n = RPR.GetTrackNumSends(track.id, 0)
    sends = []
    for i in range(n):
        vol = RPR.GetTrackSendInfo_Value(track.id, 0, i, "D_VOL")
        pan = RPR.GetTrackSendInfo_Value(track.id, 0, i, "D_PAN")
        muted = bool(RPR.GetTrackSendInfo_Value(track.id, 0, i, "B_MUTE"))
        sends.append({"send_index": i, "volume_linear": vol, "pan": pan, "muted": muted})
    return {"success": True, "track_index": track_index, "sends": sends}

def remove_send(*, source_track_index: int, send_index: int) -> dict:
    """Remove a send from a track by its index."""
    project = get_project()
    track = project.tracks[source_track_index]
    RPR.RemoveTrackSend(track.id, 0, send_index)
    return {"success": True, "source_track_index": source_track_index, "send_index": send_index}

def set_send_volume(*, source_track_index: int, send_index: int, volume_db: float) -> dict:
    """Set the volume of a send in dB."""
    project = get_project()
    track = project.tracks[source_track_index]
    RPR.SetTrackSendInfo_Value(track.id, 0, send_index, "D_VOL", db_to_linear(volume_db))
    return {
        "success": True,
        "source_track_index": source_track_index,
        "send_index": send_index,
        "volume_db": volume_db,
    }

def create_bus(*, name: str, track_indices: list) -> dict:
    """
    Create a new bus track and route the given tracks to it via sends.
    track_indices: list of track indices to feed into the bus.
    """
    project = get_project()
    bus_idx = project.n_tracks
    project.add_track(bus_idx, name)
    bus_track = project.tracks[bus_idx]
    sends = []
    for idx in track_indices:
        src = project.tracks[idx]
        send_i = RPR.CreateTrackSend(src.id, bus_track.id)
        sends.append({"track_index": idx, "send_index": send_i})
    return {
        "success": True,
        "bus_index": bus_idx,
        "bus_name": name,
        "sends": sends,
    }


TOOLS = (
    add_volume_automation,
    add_pan_automation,
    create_send,
    list_sends,
    remove_send,
    set_send_volume,
    create_bus,
)
