"""Characterization tests for midi_tools, run end to end against the fake REAPER."""

import pytest

from reaper_mcp import midi_tools
from reaper_mcp.midi_tools import _parse_chord
from tests.fake_reaper.objects import ItemState, Note


def _midi_item(reaper, call):
    """A track holding one empty MIDI item at 1.0s, 4.0s long."""
    track = reaper.add_track("Keys")
    call("create_midi_item", track_index=0, start_position=1.0, length=4.0)
    return track


# _parse_chord


@pytest.mark.parametrize(
    ("chord", "intervals", "root"),
    [
        ("C", [0, 4, 7], 0),
        ("Am", [0, 3, 7], 9),
        ("Amin", [0, 3, 7], 9),
        ("F#maj7", [0, 4, 7, 11], 6),
        ("Bbm7", [0, 3, 7, 10], 10),
        ("Eb7", [0, 4, 7, 10], 3),
        ("Gdom7", [0, 4, 7, 10], 7),
        ("Bdim", [0, 3, 6], 11),
        ("Bhdim7", [0, 3, 6, 10], 11),
        ("Ddim7", [0, 3, 6, 9], 2),
        ("Caug", [0, 4, 8], 0),
        ("Dsus2", [0, 2, 7], 2),
        ("Dsus4", [0, 5, 7], 2),
        ("  Gm  ", [0, 3, 7], 7),
    ],
)
def test_parse_chord_known_chords(chord, intervals, root):
    assert _parse_chord(chord) == (intervals, root)


def test_parse_chord_unknown_type_falls_back_to_major():
    assert _parse_chord("Cxyz") == ([0, 4, 7], 0)
    assert _parse_chord("Dm9") == ([0, 4, 7], 2)


def test_parse_chord_unknown_root_falls_back_to_c():
    assert _parse_chord("H") == ([0, 4, 7], 0)
    assert _parse_chord("") == ([0, 4, 7], 0)


def test_parse_chord_enharmonic_roots():
    assert _parse_chord("Cb") == ([0, 4, 7], 11)
    assert _parse_chord("Fb") == ([0, 4, 7], 4)
    assert _parse_chord("E#m") == ([0, 3, 7], 5)
    assert _parse_chord("B#") == ([0, 4, 7], 0)


# create_midi_item


def test_create_midi_item(reaper, call):
    reaper.add_track("Keys")
    track = reaper.add_track("Bass")
    result = call("create_midi_item", track_index=1, start_position=1.5, length=2.0)
    [item] = track.items
    assert result == {
        "success": True,
        "item_id": item.pointer,
        "item_index": 0,
        "position": 1.5,
        "length": 2.0,
        "track_index": 1,
    }
    assert (item.position, item.length, item.midi, item.notes) == (1.5, 2.0, True, [])
    assert reaper.tracks[0].items == []


def test_create_midi_item_second_item_index(reaper, call):
    track = _midi_item(reaper, call)
    result = call("create_midi_item", track_index=0, start_position=6.0, length=1.0)
    assert result["item_index"] == 1
    assert len(track.items) == 2


def test_create_midi_item_bad_track(reaper, call):
    result = call("create_midi_item", track_index=0, start_position=0.0, length=1.0)
    assert result == {"success": False, "error": "list index out of range"}


# add_midi_note


def test_add_midi_note(reaper, call):
    track = _midi_item(reaper, call)
    result = call(
        "add_midi_note", track_index=0, item_index=0, pitch=64, start=0.5, length=0.25,
        velocity=90, channel=3,
    )
    assert result == {
        "success": True,
        "track_index": 0,
        "item_index": 0,
        "pitch": 64,
        "start": 0.5,
        "length": 0.25,
        "velocity": 90,
        "channel": 3,
    }
    assert track.items[0].notes == [Note(0.5, 0.75, 64, 90, 3)]


def test_add_midi_note_defaults(reaper, call):
    track = _midi_item(reaper, call)
    result = call("add_midi_note", track_index=0, item_index=0, pitch=60, start=0.0, length=1.0)
    assert (result["velocity"], result["channel"]) == (100, 0)
    assert track.items[0].notes == [Note(0.0, 1.0, 60, 100, 0)]


def test_add_midi_note_python_defaults(reaper, call):
    # Called from Python, not through the MCP schema: the function's own defaults.
    track = _midi_item(reaper, call)
    midi_tools.add_midi_note(track_index=0, item_index=0, pitch=60, start=0.0, length=1.0)
    assert track.items[0].notes == [Note(0.0, 1.0, 60, 100, 0)]


def test_add_midi_note_audio_item(reaper, call):
    track = reaper.add_track("Audio")
    track.items.append(ItemState(reaper.new_pointer("MediaItem"), 0.0, 2.0, midi=False))
    result = call("add_midi_note", track_index=0, item_index=0, pitch=60, start=0.0, length=1.0)
    assert result == {"success": False, "error": "Item is not a MIDI item"}
    assert track.items[0].notes == []


def test_add_midi_note_bad_track(reaper, call):
    result = call("add_midi_note", track_index=2, item_index=0, pitch=60, start=0.0, length=1.0)
    assert result == {"success": False, "error": "list index out of range"}


def test_add_midi_note_bad_item(reaper, call):
    reaper.add_track("Keys")
    result = call("add_midi_note", track_index=0, item_index=0, pitch=60, start=0.0, length=1.0)
    assert result == {"success": False, "error": "list index out of range"}


# create_chord_progression


def test_create_chord_progression(reaper, call):
    track = reaper.add_track("Keys")
    result = call("create_chord_progression", track_index=0, chords="C, Am", start_position=1.0)
    [item] = track.items
    assert result == {
        "success": True,
        "item_id": item.pointer,
        "chords": [
            {"chord": "C", "position": 0.0, "length": 2.0},
            {"chord": "Am", "position": 2.0, "length": 2.0},
        ],
        "start_position": 1.0,
        "total_length": 4.0,
    }
    assert (item.position, item.length, item.midi) == (1.0, 4.0, True)
    notes = [(n.start, round(n.end, 9), n.pitch, n.velocity, n.channel) for n in item.notes]
    assert notes == [
        (0.0, 1.9, 60, 80, 0),
        (0.0, 1.9, 64, 80, 0),
        (0.0, 1.9, 67, 80, 0),
        (2.0, 3.9, 69, 80, 0),
        (2.0, 3.9, 72, 80, 0),
        (2.0, 3.9, 76, 80, 0),
    ]


def test_create_chord_progression_follows_tempo_and_beats(reaper, call):
    reaper.bpm = 60.0
    track = reaper.add_track("Keys")
    result = call(
        "create_chord_progression", track_index=0, chords="G7", start_position=0.0,
        beats_per_chord=2,
    )
    assert result["chords"] == [{"chord": "G7", "position": 0.0, "length": 2.0}]
    assert result["total_length"] == 2.0
    assert [n.pitch for n in track.items[0].notes] == [67, 71, 74, 77]
    assert [n.end for n in track.items[0].notes] == pytest.approx([1.9] * 4)


def test_create_chord_progression_python_default_is_four_beats(reaper):
    track = reaper.add_track("Keys")
    result = midi_tools.create_chord_progression(track_index=0, chords="C", start_position=0.0)
    # 4 beats at 120 bpm.
    assert result["total_length"] == 2.0
    assert track.items[0].length == 2.0


def test_create_chord_progression_unparseable_chords_become_c_major(reaper, call):
    track = reaper.add_track("Keys")
    result = call("create_chord_progression", track_index=0, chords="Hxyz,", start_position=0.0)
    assert [c["chord"] for c in result["chords"]] == ["Hxyz", ""]
    assert [n.pitch for n in track.items[0].notes] == [60, 64, 67, 60, 64, 67]


def test_create_chord_progression_zero_tempo(reaper, call):
    reaper.bpm = 0.0
    track = reaper.add_track("Keys")
    result = call("create_chord_progression", track_index=0, chords="C", start_position=0.0)
    assert result == {"success": False, "error": "float division by zero"}
    assert track.items == []


def test_create_chord_progression_bad_track(reaper, call):
    result = call("create_chord_progression", track_index=0, chords="C", start_position=0.0)
    assert result == {"success": False, "error": "list index out of range"}


# create_drum_pattern


def test_create_drum_pattern(reaper, call):
    track = reaper.add_track("Drums")
    result = call(
        "create_drum_pattern", track_index=0, pattern="k.sx", start_position=2.0, repeats=2
    )
    [item] = track.items
    assert result == {
        "success": True,
        "item_id": item.pointer,
        "pattern": "k.sx",
        "repeats": 2,
        "start_position": 2.0,
        "total_length": 4.0,
    }
    assert (item.position, item.length, item.midi) == (2.0, 4.0, True)
    assert item.notes == [
        Note(0.0, 0.25, 36, 100, 9),
        Note(1.0, 1.25, 38, 100, 9),
        Note(2.0, 2.25, 36, 100, 9),
        Note(3.0, 3.25, 38, 100, 9),
    ]


def test_create_drum_pattern_maps_every_drum(reaper, call):
    reaper.bpm = 60.0
    track = reaper.add_track("Drums")
    call("create_drum_pattern", track_index=0, pattern="kshotmfcr", start_position=0.0, beats=9)
    notes = track.items[0].notes
    assert [n.pitch for n in notes] == [36, 38, 42, 46, 41, 45, 48, 49, 51]
    assert [n.start for n in notes] == [float(i) for i in range(9)]
    assert {n.end - n.start for n in notes} == {0.5}
    assert {(n.velocity, n.channel) for n in notes} == {(100, 9)}


def test_create_drum_pattern_python_defaults(reaper):
    # One bar of 4 beats at 120 bpm, played once.
    track = reaper.add_track("Drums")
    result = midi_tools.create_drum_pattern(track_index=0, pattern="k.", start_position=0.0)
    assert (result["repeats"], result["total_length"]) == (1, 2.0)
    assert track.items[0].notes == [Note(0.0, 0.5, 36, 100, 9)]


def test_create_drum_pattern_empty_pattern_creates_nothing(reaper, call):
    track = reaper.add_track("Drums")
    result = call("create_drum_pattern", track_index=0, pattern="", start_position=0.0)
    assert result == {"success": False, "error": "pattern is empty; give one character per step"}
    assert track.items == []


def test_create_drum_pattern_bad_track(reaper, call):
    result = call("create_drum_pattern", track_index=0, pattern="k", start_position=0.0)
    assert result == {"success": False, "error": "list index out of range"}
