"""MIDI tools against a running REAPER: notes read back with MIDI_GetNote
and placed in project time, for an item that does not start at zero."""

import pytest
from tests.live.rpr import RPR

pytestmark = pytest.mark.live


def notes_in_project_time(live_project) -> list[tuple[float, float, int, int, int]]:
    take = live_project.tracks[0].items[0].active_take
    _, _, count, _, _ = RPR.MIDI_CountEvts(take.id, 0, 0, 0)
    notes = []
    for i in range(count):
        r = RPR.MIDI_GetNote(take.id, i, 0, 0, 0, 0, 0, 0, 0)
        start, end = (RPR.MIDI_GetProjTimeFromPPQPos(take.id, ppq) for ppq in (r[5], r[6]))
        notes.append((round(start, 4), round(end, 4), r[8], r[9], r[7]))  # pitch, velocity, channel
    return notes


def test_add_midi_note_is_relative_to_the_item(live_project, call):
    live_project.add_track(0, "keys")
    assert call("create_midi_item", track_index=0, start_position=4.0, length=4.0)["success"] is True
    result = call("add_midi_note", track_index=0, item_index=0, pitch=60, start=1.0, length=0.5,
                  velocity=90, channel=2)
    assert result["success"] is True, result
    assert notes_in_project_time(live_project) == [(5.0, 5.5, 60, 90, 2)]


def test_chord_progression_lands_inside_its_item(live_project, call):
    live_project.add_track(0, "keys")
    result = call("create_chord_progression", track_index=0, chords="C,Am", start_position=4.0,
                  beats_per_chord=4)
    assert result["success"] is True, result
    notes = notes_in_project_time(live_project)
    assert [n[2] for n in notes] == [60, 64, 67, 69, 72, 76]
    assert {n[0] for n in notes} == {4.0, 6.0}  # 120 BPM: 2 s per 4-beat chord


def test_drum_pattern_lands_inside_its_item(live_project, call):
    live_project.add_track(0, "drums")
    result = call("create_drum_pattern", track_index=0, pattern="k...s...", start_position=2.0, beats=2)
    assert result["success"] is True, result
    assert notes_in_project_time(live_project) == [(2.0, 2.0625, 36, 100, 9), (2.5, 2.5625, 38, 100, 9)]
