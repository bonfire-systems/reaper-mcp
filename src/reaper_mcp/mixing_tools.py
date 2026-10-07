from reaper_mcp.reaper import RPR, get_project, is_null
from reaper_mcp.units import db_to_linear




# "Track: Toggle track volume/pan envelope visible", run on the selected tracks.
SHOW_ENVELOPE = {"Volume": 40406, "Pan": 40407}


def _envelope(project, track, name: str):
    """The track's envelope called name, shown first if the track has none yet.

    REAPER only creates a track envelope when it is shown, and the show action
    works on the selected tracks, so the track is selected for that one action
    and the previous selection is restored afterwards.
    """
    envelope = RPR.GetTrackEnvelopeByName(track.id, name)
    if not is_null(envelope):
        return envelope
    tracks = project.tracks
    selected = [t.id for t in tracks if t.is_selected]
    RPR.SetOnlyTrackSelected(track.id)
    RPR.Main_OnCommand(SHOW_ENVELOPE[name], 0)
    for t in tracks:
        RPR.SetTrackSelected(t.id, t.id in selected)
    envelope = RPR.GetTrackEnvelopeByName(track.id, name)
    if is_null(envelope):
        raise RuntimeError(f"REAPER did not create the {name.lower()} envelope")
    return envelope


def add_volume_automation(*, track_index: int, position: float, value_db: float) -> dict:
    """
    Add a volume automation point on a track, showing its volume envelope if needed.
    position: time in seconds. value_db: volume level in dB.
    """
    project = get_project()
    envelope = _envelope(project, project.tracks[track_index], "Volume")
    # Volume envelopes usually use fader scaling, where a raw linear 0.5 is near
    # silence; convert to the envelope's own scale.
    raw = RPR.ScaleToEnvelopeMode(RPR.GetEnvelopeScalingMode(envelope), db_to_linear(value_db))
    RPR.InsertEnvelopePoint(envelope, position, raw, 0, 0, False, True)
    RPR.Envelope_SortPoints(envelope)
    return {"success": True, "track_index": track_index, "position": position, "value_db": value_db}


def add_pan_automation(*, track_index: int, position: float, pan: float) -> dict:
    """
    Add a pan automation point on a track, showing its pan envelope if needed.
    pan: -1.0 (full left) to 1.0 (full right).
    """
    project = get_project()
    envelope = _envelope(project, project.tracks[track_index], "Pan")
    # REAPER's pan envelope runs opposite to track pan: +1 is full left there.
    RPR.InsertEnvelopePoint(envelope, position, -pan, 0, 0, False, True)
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
    # REAPER can answer with a valid index and create nothing (a send from a
    # track to itself returns 0), so the send count is the evidence.
    before = RPR.GetTrackNumSends(src.id, 0)
    send_idx = RPR.CreateTrackSend(src.id, dst.id)
    if RPR.GetTrackNumSends(src.id, 0) != before + 1:
        return {
            "success": False,
            "error": f"REAPER did not create a send from track {source_track_index} "
                     f"to track {dest_track_index}",
        }
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
    if not RPR.RemoveTrackSend(track.id, 0, send_index):
        return {"success": False, "error": f"track {source_track_index} has no send {send_index}"}
    return {"success": True, "source_track_index": source_track_index, "send_index": send_index}

def set_send_volume(*, source_track_index: int, send_index: int, volume_db: float) -> dict:
    """Set the volume of a send in dB."""
    project = get_project()
    track = project.tracks[source_track_index]
    if not RPR.SetTrackSendInfo_Value(track.id, 0, send_index, "D_VOL", db_to_linear(volume_db)):
        return {"success": False, "error": f"track {source_track_index} has no send {send_index}"}
    return {
        "success": True,
        "source_track_index": source_track_index,
        "send_index": send_index,
        "volume_db": volume_db,
    }

def create_bus(*, name: str, track_indices: list[int]) -> dict:
    """
    Create a new bus track and route the given tracks to it via sends.
    track_indices: list of track indices to feed into the bus.
    """
    project = get_project()
    sources = [project.tracks[idx] for idx in track_indices]  # IndexError before any change
    bus_idx = project.n_tracks
    project.add_track(bus_idx, name)
    bus_track = project.tracks[bus_idx]
    sends = [
        {"track_index": idx, "send_index": RPR.CreateTrackSend(src.id, bus_track.id)}
        for idx, src in zip(track_indices, sources, strict=True)
    ]
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
