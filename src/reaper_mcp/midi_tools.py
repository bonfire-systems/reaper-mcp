import logging

from reaper_mcp.reaper import get_project

logger = logging.getLogger("reaper_mcp.midi_tools")

# GM standard drum MIDI notes
DRUM_MAPPINGS = {
    "k": 36,  # kick  - C1
    "s": 38,  # snare - D1
    "h": 42,  # hihat closed - F#1
    "o": 46,  # hihat open   - A#1
    "t": 41,  # tom low  - F1
    "m": 45,  # tom mid  - A1
    "f": 48,  # tom high - C2
    "c": 49,  # crash - C#2
    "r": 51,  # ride  - D#2
}

CHORD_TYPES = {
    "maj":   [0, 4, 7],
    "min":   [0, 3, 7],
    "m":     [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
    "maj7":  [0, 4, 7, 11],
    "min7":  [0, 3, 7, 10],
    "m7":    [0, 3, 7, 10],
    "7":     [0, 4, 7, 10],
    "dom7":  [0, 4, 7, 10],
    "dim7":  [0, 3, 6, 9],
    "hdim7": [0, 3, 6, 10],
    "sus2":  [0, 2, 7],
    "sus4":  [0, 5, 7],
}

NOTE_TO_NUMBER = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def _parse_chord(chord_str: str):
    """Return (intervals_list, root_semitone) for a chord string like 'Cm7', 'G', 'F#maj7'."""
    chord_str = chord_str.strip()
    if len(chord_str) >= 2 and chord_str[1] in ("#", "b"):
        root = chord_str[:2]
        chord_type = chord_str[2:] or "maj"
    else:
        root = chord_str[:1]
        chord_type = chord_str[1:] or "maj"
    intervals = CHORD_TYPES.get(chord_type, CHORD_TYPES["maj"])
    root_num = NOTE_TO_NUMBER.get(root, 0)
    return intervals, root_num


def create_midi_item(*, track_index: int, start_position: float, length: float) -> dict:
    """Create an empty MIDI item on a track. Returns item_id for use with add_midi_note."""
    project = get_project()
    track = project.tracks[track_index]
    item = track.add_midi_item(start_position, start_position + length)
    return {
        "success": True,
        "item_id": item.id,
        "item_index": track.n_items - 1,
        "position": item.position,
        "length": item.length,
        "track_index": track_index,
    }

def add_midi_note(
    *,
    track_index: int,
    item_index: int,
    pitch: int,
    start: float,
    length: float,
    velocity: int = 100,
    channel: int = 0,
) -> dict:
    """
    Add a MIDI note to an existing MIDI item.
    pitch: MIDI note number 0–127 (60 = middle C, 69 = A4).
    start/length: seconds, relative to the item's start.
    channel: MIDI channel 0–15 (use 9 for drums).
    """
    project = get_project()
    track = project.tracks[track_index]
    item = track.items[item_index]
    take = item.active_take
    if not take.is_midi:
        return {"success": False, "error": "Item is not a MIDI item"}
    take.add_note(
        start=start,
        end=start + length,
        pitch=pitch,
        velocity=velocity,
        channel=channel,
    )
    return {
        "success": True,
        "track_index": track_index,
        "item_index": item_index,
        "pitch": pitch,
        "start": start,
        "length": length,
        "velocity": velocity,
        "channel": channel,
    }

def create_chord_progression(
    *,
    track_index: int,
    chords: str,
    start_position: float,
    beats_per_chord: int = 4,
) -> dict:
    """
    Create a chord progression on a track as a single MIDI item.
    chords: comma-separated chord names, e.g. "C,G,Am,F" or "Cm7,Fm7,Bb7,Ebmaj7".
    Supports: maj, min/m, dim, aug, maj7, min7/m7, dom7/7, dim7, hdim7, sus2, sus4.
    All chords are voiced around middle C (MIDI 60).
    """
    project = get_project()
    track = project.tracks[track_index]
    chord_list = [c.strip() for c in chords.split(",")]
    seconds_per_beat = 60.0 / project.bpm
    chord_length = seconds_per_beat * beats_per_chord
    total_length = chord_length * len(chord_list)

    item = track.add_midi_item(start_position, start_position + total_length)
    take = item.active_take
    added_chords = []

    for i, chord_str in enumerate(chord_list):
        try:
            intervals, root_num = _parse_chord(chord_str)
            chord_start = i * chord_length
            for interval in intervals:
                note_num = 60 + root_num + interval
                take.add_note(
                    start=chord_start,
                    end=chord_start + chord_length * 0.95,
                    pitch=note_num,
                    velocity=80,
                    channel=0,
                )
            added_chords.append({
                "chord": chord_str,
                "position": chord_start,
                "length": chord_length,
            })
        except Exception as e:
            logger.warning(f"Skipping chord '{chord_str}': {e}")

    return {
        "success": True,
        "item_id": item.id,
        "chords": added_chords,
        "start_position": start_position,
        "total_length": total_length,
    }

def create_drum_pattern(
    *,
    track_index: int,
    pattern: str,
    start_position: float,
    beats: int = 4,
    repeats: int = 1,
) -> dict:
    """
    Create a drum pattern on a track using a step-sequencer string.
    Each character = one step. Characters: k=kick, s=snare, h=hihat(closed),
    o=hihat(open), t=tom(low), m=tom(mid), f=tom(high), c=crash, r=ride, .=rest.
    Example 4/4 rock beat (16 steps): "k...h...s...h..."
    All drum notes are placed on MIDI channel 9 (GM standard).
    """
    project = get_project()
    track = project.tracks[track_index]
    seconds_per_beat = 60.0 / project.bpm
    pattern_length = seconds_per_beat * beats
    total_length = pattern_length * repeats

    item = track.add_midi_item(start_position, start_position + total_length)
    take = item.active_take
    time_per_step = pattern_length / len(pattern)

    for repeat in range(repeats):
        offset = repeat * pattern_length
        for i, char in enumerate(pattern):
            if char in DRUM_MAPPINGS:
                note_start = offset + i * time_per_step
                take.add_note(
                    start=note_start,
                    end=note_start + time_per_step * 0.5,
                    pitch=DRUM_MAPPINGS[char],
                    velocity=100,
                    channel=9,
                )

    return {
        "success": True,
        "item_id": item.id,
        "pattern": pattern,
        "repeats": repeats,
        "start_position": start_position,
        "total_length": total_length,
    }


TOOLS = (
    create_midi_item,
    add_midi_note,
    create_chord_progression,
    create_drum_pattern,
)
