"""Characterization tests for audio_tools, run end to end against the fake REAPER."""

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


def test_start_recording_does_not_arm_bug(reaper, call):
    track = reaper.add_track("Vox")
    result = call("start_recording", track_index=0)
    assert result == {
        "success": True,
        "track_index": 0,
        "message": "Recording started. Call stop_transport to stop.",
    }
    assert (reaper.commands, reaper.transport) == ([RECORD], "recording")
    # BUG: reapy Track has no `armed`; the assignment lands on a throwaway proxy, so nothing records.
    assert track.info == {"D_VOL": 1.0, "D_PAN": 0.0, "B_MUTE": 0.0, "I_SOLO": 0.0}


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


def test_edit_audio_item_start_trim_bug(reaper, call):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0, start_trim=1.0, end_trim=1.0)
    assert result["success"] is False
    assert "start_offset" in result["error"]
    assert "has no setter" in result["error"]
    # BUG: Take.start_offset is read-only, so the trim errors after moving the item: audio slides
    # instead of being trimmed, and end_trim never runs.
    assert (track.items[0].position, track.items[0].length) == (2.0, 3.0)


def test_edit_audio_item_fades_bug(reaper, call):
    track = _audio_item(reaper)
    result = call("edit_audio_item", track_index=0, item_index=0, fade_in=0.5, fade_out=0.25)
    # BUG: reapy Item has no fade_in_length/fade_out_length; reported success, no fades applied.
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "position": 1.0, "length": 4.0,
    }
    assert (track.items[0].position, track.items[0].length) == (1.0, 4.0)


def test_edit_audio_item_bad_item(reaper, call):
    reaper.add_track("Audio")
    result = call("edit_audio_item", track_index=0, item_index=0, end_trim=1.0)
    assert result == {"success": False, "error": "list index out of range"}


# adjust_pitch / adjust_playback_rate


def test_adjust_pitch_no_effect_bug(reaper, call):
    track = _audio_item(reaper)
    before = (track.items[0].position, track.items[0].length)
    result = call("adjust_pitch", track_index=0, item_index=0, semitones=-2.5)
    # BUG: reapy Take has no `pitch`; the value lands on a throwaway proxy and is echoed back.
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "pitch_semitones": -2.5,
    }
    assert (track.items[0].position, track.items[0].length) == before


def test_adjust_pitch_bad_item(reaper, call):
    reaper.add_track("Audio")
    result = call("adjust_pitch", track_index=0, item_index=0, semitones=1.0)
    assert result == {"success": False, "error": "list index out of range"}


def test_adjust_playback_rate_no_effect_bug(reaper, call):
    track = _audio_item(reaper)
    result = call("adjust_playback_rate", track_index=0, item_index=0, rate=0.5)
    # BUG: reapy Take has no `playback_rate`; nothing changes in REAPER though success is reported.
    assert result == {
        "success": True, "track_index": 0, "item_index": 0, "playback_rate": 0.5,
    }
    assert (track.items[0].position, track.items[0].length) == (1.0, 4.0)


def test_adjust_playback_rate_bad_track(reaper, call):
    result = call("adjust_playback_rate", track_index=0, item_index=0, rate=2.0)
    assert result == {"success": False, "error": "list index out of range"}
