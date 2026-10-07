"""Characterization tests for mixing_tools, run end to end against the fake REAPER."""

import pytest

from reaper_mcp.mixing_tools import _db_to_linear

OUT_OF_RANGE = "list index out of range"


def test_db_to_linear():
    assert _db_to_linear(0.0) == 1.0
    assert _db_to_linear(-6.0) == pytest.approx(0.501187, rel=1e-5)
    assert _db_to_linear(6.0) == pytest.approx(1.995262, rel=1e-5)
    assert _db_to_linear(-149.9) == pytest.approx(10 ** (-149.9 / 20))
    assert _db_to_linear(-150.0) == 0.0
    assert _db_to_linear(-500.0) == 0.0


# add_volume_automation


def test_add_volume_automation_inserts_linear_point(reaper, call):
    reaper.add_track("A")
    vox = reaper.add_track("Vox")
    reaper.show_envelope(vox, "Volume")
    result = call("add_volume_automation", track_index=1, position=2.5, value_db=-6.0)
    assert result == {"success": True, "track_index": 1, "position": 2.5, "value_db": -6.0}
    [(time, value)] = reaper.envelopes[(vox.pointer, "Volume")]
    assert time == 2.5
    assert value == pytest.approx(_db_to_linear(-6.0))


def test_add_volume_automation_floor_is_silence(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Volume")
    call("add_volume_automation", track_index=0, position=0.0, value_db=-200.0)
    assert reaper.envelopes[(track.pointer, "Volume")] == [(0.0, 0.0)]


def test_add_volume_automation_envelope_hidden(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Pan")
    result = call("add_volume_automation", track_index=0, position=1.0, value_db=0.0)
    assert result == {
        "success": False,
        "error": (
            "Volume envelope not found. Show it first: right-click the track "
            "in REAPER and choose 'Show envelope for track volume'."
        ),
    }
    assert reaper.envelopes == {(track.pointer, "Pan"): []}


def test_add_volume_automation_bad_track(reaper, call):
    reaper.add_track("A")
    result = call("add_volume_automation", track_index=3, position=1.0, value_db=0.0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# add_pan_automation


def test_add_pan_automation_inserts_raw_point(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Pan")
    result = call("add_pan_automation", track_index=0, position=4.0, pan=-0.5)
    assert result == {"success": True, "track_index": 0, "position": 4.0, "pan": -0.5}
    assert reaper.envelopes[(track.pointer, "Pan")] == [(4.0, -0.5)]


def test_add_pan_automation_passes_out_of_range_pan_through(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Pan")
    result = call("add_pan_automation", track_index=0, position=0.0, pan=3.0)
    assert result["success"] is True
    assert reaper.envelopes[(track.pointer, "Pan")] == [(0.0, 3.0)]


def test_add_pan_automation_envelope_hidden(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Volume")
    result = call("add_pan_automation", track_index=0, position=1.0, pan=0.0)
    assert result == {
        "success": False,
        "error": (
            "Pan envelope not found. Show it first: right-click the track "
            "in REAPER and choose 'Show envelope for track pan'."
        ),
    }
    assert reaper.envelopes == {(track.pointer, "Volume"): []}


def test_add_pan_automation_bad_track(reaper, call):
    result = call("add_pan_automation", track_index=0, position=1.0, pan=0.0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# create_send


def test_create_send_default_volume(reaper, call):
    src = reaper.add_track("Src")
    dst = reaper.add_track("Dst")
    result = call("create_send", source_track_index=0, dest_track_index=1)
    assert result == {
        "success": True,
        "source_track_index": 0,
        "dest_track_index": 1,
        "send_index": 0,
        "volume_db": 0.0,
    }
    [send] = src.sends
    assert (send.dest, send.volume, send.pan, send.muted) == (dst.pointer, 1.0, 0.0, False)
    assert dst.sends == []


def test_create_send_sets_volume_and_indexes_sequentially(reaper, call):
    src = reaper.add_track("Src")
    reaper.add_track("Bus 1")
    reaper.add_track("Bus 2")
    call("create_send", source_track_index=0, dest_track_index=1)
    result = call("create_send", source_track_index=0, dest_track_index=2, volume_db=-6.0)
    assert result["send_index"] == 1
    assert result["volume_db"] == -6.0
    assert src.sends[1].volume == pytest.approx(_db_to_linear(-6.0))
    assert src.sends[0].volume == 1.0


def test_create_send_bad_dest_creates_nothing(reaper, call):
    src = reaper.add_track("Src")
    result = call("create_send", source_track_index=0, dest_track_index=5)
    assert result == {"success": False, "error": OUT_OF_RANGE}
    assert src.sends == []


def test_create_send_bad_source(reaper, call):
    reaper.add_track("Dst")
    result = call("create_send", source_track_index=5, dest_track_index=0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# list_sends


def test_list_sends_reports_each_send(reaper, call):
    src = reaper.add_track("Src")
    reaper.add_track("A")
    reaper.add_track("B")
    call("create_send", source_track_index=0, dest_track_index=1, volume_db=-6.0)
    call("create_send", source_track_index=0, dest_track_index=2)
    src.sends[1].pan = 0.25
    src.sends[1].muted = True
    result = call("list_sends", track_index=0)
    assert result["success"] is True
    assert result["track_index"] == 0
    first, second = result["sends"]
    assert first["send_index"] == 0
    assert first["volume_linear"] == pytest.approx(_db_to_linear(-6.0))
    assert (first["pan"], first["muted"]) == (0.0, False)
    assert second == {"send_index": 1, "volume_linear": 1.0, "pan": 0.25, "muted": True}


def test_list_sends_none(reaper, call):
    reaper.add_track("A")
    assert call("list_sends", track_index=0) == {"success": True, "track_index": 0, "sends": []}


def test_list_sends_bad_track(reaper, call):
    assert call("list_sends", track_index=0) == {"success": False, "error": OUT_OF_RANGE}


# remove_send


def test_remove_send_removes_by_index(reaper, call):
    src = reaper.add_track("Src")
    a = reaper.add_track("A")
    b = reaper.add_track("B")
    call("create_send", source_track_index=0, dest_track_index=1)
    call("create_send", source_track_index=0, dest_track_index=2)
    result = call("remove_send", source_track_index=0, send_index=0)
    assert result == {"success": True, "source_track_index": 0, "send_index": 0}
    assert [s.dest for s in src.sends] == [b.pointer]
    assert a.pointer not in [s.dest for s in src.sends]


def test_remove_send_bad_track(reaper, call):
    result = call("remove_send", source_track_index=2, send_index=0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# set_send_volume


def test_set_send_volume(reaper, call):
    src = reaper.add_track("Src")
    reaper.add_track("A")
    call("create_send", source_track_index=0, dest_track_index=1)
    result = call("set_send_volume", source_track_index=0, send_index=0, volume_db=-12.0)
    assert result == {
        "success": True,
        "source_track_index": 0,
        "send_index": 0,
        "volume_db": -12.0,
    }
    assert src.sends[0].volume == pytest.approx(_db_to_linear(-12.0))


def test_set_send_volume_floor_is_silence(reaper, call):
    src = reaper.add_track("Src")
    reaper.add_track("A")
    call("create_send", source_track_index=0, dest_track_index=1)
    call("set_send_volume", source_track_index=0, send_index=0, volume_db=-150.0)
    assert src.sends[0].volume == 0.0


def test_set_send_volume_bad_track(reaper, call):
    result = call("set_send_volume", source_track_index=0, send_index=0, volume_db=0.0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# create_bus


def test_create_bus_appends_track_and_routes(reaper, call):
    kick = reaper.add_track("Kick")
    snare = reaper.add_track("Snare")
    reaper.add_track("Vox")
    result = call("create_bus", name="Drums", track_indices=[0, 1])
    assert result == {
        "success": True,
        "bus_index": 3,
        "bus_name": "Drums",
        "sends": [{"track_index": 0, "send_index": 0}, {"track_index": 1, "send_index": 0}],
    }
    assert [t.name for t in reaper.tracks] == ["Kick", "Snare", "Vox", "Drums"]
    bus = reaper.tracks[3]
    assert [s.dest for s in kick.sends] == [bus.pointer]
    assert [s.dest for s in snare.sends] == [bus.pointer]
    assert reaper.tracks[2].sends == []
    assert bus.sends == []


def test_create_bus_no_sources(reaper, call):
    result = call("create_bus", name="Empty", track_indices=[])
    assert result == {"success": True, "bus_index": 0, "bus_name": "Empty", "sends": []}
    assert [t.name for t in reaper.tracks] == ["Empty"]


def test_create_bus_invalid_index_leaves_partial_bus_bug(reaper, call):
    kick = reaper.add_track("Kick")
    result = call("create_bus", name="Drums", track_indices=[0, 7])
    # BUG: a failed create_bus leaves the new bus track and the sends made so far in the project.
    assert result == {"success": False, "error": OUT_OF_RANGE}
    assert [t.name for t in reaper.tracks] == ["Kick", "Drums"]
    assert [s.dest for s in kick.sends] == [reaper.tracks[1].pointer]


def test_remove_send_bad_send_index_reports_success_bug(reaper, call):
    # BUG: REAPER's RemoveTrackSend returns false for a missing send; the tool ignores it and reports success.
    track = reaper.add_track("Src")
    assert call("remove_send", source_track_index=0, send_index=5)["success"] is True
    assert track.sends == []


def test_set_send_volume_bad_send_index_reports_success_bug(reaper, call):
    # BUG: SetTrackSendInfo_Value returns false for a missing send; the tool ignores it and reports success.
    reaper.add_track("Src")
    result = call("set_send_volume", source_track_index=0, send_index=5, volume_db=-6.0)
    assert result["success"] is True
