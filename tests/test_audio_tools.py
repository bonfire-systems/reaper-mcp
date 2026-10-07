"""Characterization tests for audio_tools, run end to end against the fake REAPER."""

import pytest

from reaper_mcp import audio_tools
from tests.fake_reaper.objects import ItemState

RECORD, STOP, PLAY = 1013, 1016, 1007


def _audio_item(reaper, position=1.0, length=4.0):
    """A track holding one audio item."""
    track = reaper.add_track("Audio")
    track.items.append(ItemState(reaper.new_pointer("MediaItem"), position, length, midi=False))
    return track


# import_audio_file


def test_import_audio_file(reaper, call, tmp_path):
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"RIFF")
    other = reaper.add_track("Other")
    track = reaper.add_track("Audio")
    result = call("import_audio_file", file_path=str(wav), track_index=1, position=3.0)
    assert result == {
        "success": True,
        "track_index": 1,
        "item_index": 0,
        "position": 3.0,
        "length": 2.0,
        "file_path": str(wav),
    }
    assert reaper.cursor == 3.0
    assert (track.selected, other.selected) == (True, False)
    assert [(i.position, i.midi) for i in track.items] == [(3.0, False)]
    assert other.items == []


def test_import_audio_file_appends_after_existing_items(reaper, call, tmp_path):
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"RIFF")
    track = _audio_item(reaper)
    result = call("import_audio_file", file_path=str(wav), track_index=0)
    assert (result["item_index"], result["position"]) == (1, 0.0)
    assert len(track.items) == 2


def test_import_audio_file_from_python_defaults_to_the_start(reaper, tmp_path):
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"RIFF")
    track = reaper.add_track("Audio")
    reaper.cursor = 5.0
    result = audio_tools.import_audio_file(file_path=str(wav), track_index=0)
    assert (result["success"], result["position"]) == (True, 0.0)
    assert [i.position for i in track.items] == [0.0]


def test_import_audio_file_missing_file(reaper, call, tmp_path):
    reaper.add_track("Audio")
    missing = str(tmp_path / "nope.wav")
    result = call("import_audio_file", file_path=missing, track_index=0)
    assert result == {"success": False, "error": f"File not found: {missing}"}
    assert reaper.tracks[0].items == []


def test_import_audio_file_bad_track(reaper, call, tmp_path):
    wav = tmp_path / "loop.wav"
    wav.write_bytes(b"RIFF")
    result = call("import_audio_file", file_path=str(wav), track_index=0)
    assert result == {"success": False, "error": "list index out of range"}


# start_recording / stop_transport / play_project


def test_start_recording_arms_the_track(reaper, call):
    track = reaper.add_track("Vox")
    result = call("start_recording", track_index=0)
    assert result == {
        "success": True,
        "track_index": 0,
        "message": "Recording started. Call stop_transport to stop.",
    }
    assert (reaper.commands, reaper.transport) == ([RECORD], "recording")
    assert track.info["I_RECARM"] == 1


def test_start_recording_bad_track(reaper, call):
    result = call("start_recording", track_index=0)
    assert result == {"success": False, "error": "list index out of range"}
    assert reaper.commands == []


def test_stop_transport(reaper, call):
    reaper.transport = "playing"
    assert call("stop_transport") == {"success": True, "message": "Transport stopped"}
    assert (reaper.commands, reaper.transport) == ([STOP], "stopped")


def test_play_project(reaper, call):
    assert call("play_project") == {"success": True, "message": "Playback started"}
    assert (reaper.commands, reaper.transport) == ([PLAY], "playing")


# set_cursor_position


def test_set_cursor_position(reaper, call):
    assert call("set_cursor_position", position=12.5) == {"success": True, "position": 12.5}
    assert reaper.cursor == 12.5


# edit_audio_item


def test_edit_audio_item_no_changes(reaper, call):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0)
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "position": 1.0, "length": 4.0,
    }
    assert (track.items[0].position, track.items[0].length) == (1.0, 4.0)


def test_edit_audio_item_end_trim(reaper, call):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0, end_trim=1.5)
    assert (result["success"], result["position"], result["length"]) == (True, 1.0, 2.5)
    assert (track.items[0].position, track.items[0].length) == (1.0, 2.5)


def test_edit_audio_item_trims_both_ends(reaper, call):
    track = _audio_item(reaper)
    track.items[0].take_info["D_PLAYRATE"] = 2.0
    result = call("edit_audio_item", track_index=0, item_index=0, start_trim=1.0, end_trim=1.0)
    assert result == {"success": True, "track_index": 0, "item_index": 0, "position": 2.0, "length": 2.0}
    # The source offset moves in source seconds: one second at double speed is two.
    assert track.items[0].take_info["D_STARTOFFS"] == 2.0


@pytest.mark.parametrize(("start_trim", "end_trim"), [(2.0, 2.0), (-1.0, 0.0), (0.0, 5.0)])
def test_edit_audio_item_refuses_impossible_trims(reaper, call, start_trim, end_trim):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0,
                  start_trim=start_trim, end_trim=end_trim)
    assert result["success"] is False and "trims must be >= 0" in result["error"]
    assert (track.items[0].position, track.items[0].length) == (1.0, 4.0)


def test_edit_audio_item_fades(reaper, call):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0, fade_in=0.5, fade_out=0.25)
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "position": 1.0, "length": 4.0,
    }
    assert track.items[0].info == {"D_FADEINLEN": 0.5, "D_FADEOUTLEN": 0.25}


def test_edit_audio_item_keeps_existing_fades(reaper, call):
    track = _audio_item(reaper)
    track.items[0].info.update({"D_FADEINLEN": 0.5, "D_FADEOUTLEN": 0.25})
    call("edit_audio_item", track_index=0, item_index=0, end_trim=1.0)
    assert track.items[0].info == {"D_FADEINLEN": 0.5, "D_FADEOUTLEN": 0.25}


def test_edit_audio_item_from_python_defaults_change_nothing(reaper):
    track = _audio_item(reaper)
    track.items[0].info.update({"D_FADEINLEN": 0.5, "D_FADEOUTLEN": 0.25})
    result = audio_tools.edit_audio_item(track_index=0, item_index=0)
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "position": 1.0, "length": 4.0,
    }
    item = track.items[0]
    assert (item.position, item.length, item.take_info["D_STARTOFFS"]) == (1.0, 4.0, 0.0)
    assert item.info == {"D_FADEINLEN": 0.5, "D_FADEOUTLEN": 0.25}


def test_edit_audio_item_bad_item(reaper, call):
    reaper.add_track("Audio")
    result = call("edit_audio_item", track_index=0, item_index=0, end_trim=1.0)
    assert result == {"success": False, "error": "list index out of range"}


# adjust_pitch / adjust_playback_rate


def test_adjust_pitch(reaper, call):
    track = _audio_item(reaper)
    result = call("adjust_pitch", track_index=0, item_index=0, semitones=-2.5)
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "pitch_semitones": -2.5,
    }
    assert track.items[0].take_info["D_PITCH"] == -2.5


def test_adjust_pitch_bad_item(reaper, call):
    reaper.add_track("Audio")
    result = call("adjust_pitch", track_index=0, item_index=0, semitones=1.0)
    assert result == {"success": False, "error": "list index out of range"}


def test_adjust_playback_rate(reaper, call):
    track = _audio_item(reaper)
    result = call("adjust_playback_rate", track_index=0, item_index=0, rate=0.5)
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "playback_rate": 0.5,
    }
    assert track.items[0].take_info["D_PLAYRATE"] == 0.5


def test_adjust_playback_rate_bad_track(reaper, call):
    result = call("adjust_playback_rate", track_index=0, item_index=0, rate=2.0)
    assert result == {"success": False, "error": "list index out of range"}
