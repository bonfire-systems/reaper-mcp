"""Characterization tests for mixing_tools, run end to end against the fake REAPER."""

import pytest

from reaper_mcp.mixing_tools import create_send
from reaper_mcp.units import db_to_linear as _db_to_linear

OUT_OF_RANGE = "list index out of range"


def test_db_to_linear():
    assert _db_to_linear(0.0) == 1.0
    assert _db_to_linear(-6.0) == pytest.approx(0.501187, rel=1e-5)
    assert _db_to_linear(6.0) == pytest.approx(1.995262, rel=1e-5)
    assert _db_to_linear(-149.9) == pytest.approx(10 ** (-149.9 / 20))
    assert _db_to_linear(-150.0) == 0.0
    assert _db_to_linear(-500.0) == 0.0


# add_volume_automation


def test_add_volume_automation_inserts_a_fader_scaled_point(reaper, call):
    reaper.add_track("A")
    vox = reaper.add_track("Vox")
    reaper.show_envelope(vox, "Volume")
    result = call("add_volume_automation", track_index=1, position=2.5, value_db=-6.0)
    assert result == {"success": True, "track_index": 1, "position": 2.5, "value_db": -6.0}
    [(time, value)] = reaper.envelopes[(vox.pointer, "Volume")]
    assert time == 2.5
    # The fake's stand-in fader curve is 1000 * linear (see its ScaleToEnvelopeMode).
    assert value == pytest.approx(1000 * _db_to_linear(-6.0))
    # The show action is a toggle: running it on a visible envelope would hide it.
    assert reaper.commands == []


def test_add_volume_automation_floor_is_silence(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Volume")
    call("add_volume_automation", track_index=0, position=0.0, value_db=-200.0)
    assert reaper.envelopes[(track.pointer, "Volume")] == [(0.0, 0.0)]


def test_add_volume_automation_shows_a_missing_envelope_and_keeps_the_selection(reaper, call):
    track = reaper.add_track("A")
    other = reaper.add_track("B")
    other.selected = True
    assert call("add_volume_automation", track_index=0, position=1.0, value_db=0.0)["success"] is True
    assert reaper.commands == [40406]  # Track: Toggle track volume envelope visible
    assert reaper.envelopes == {(track.pointer, "Volume"): [(1.0, 1000.0)]}
    assert (track.selected, other.selected) == (False, True)


def test_add_volume_automation_bad_track(reaper, call):
    reaper.add_track("A")
    result = call("add_volume_automation", track_index=3, position=1.0, value_db=0.0)
    assert result == {"success": False, "error": OUT_OF_RANGE}


# add_pan_automation


def test_add_pan_automation_inverts_for_the_envelope(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Pan")
    result = call("add_pan_automation", track_index=0, position=4.0, pan=-0.5)
    assert result == {"success": True, "track_index": 0, "position": 4.0, "pan": -0.5}
    # REAPER's pan envelope runs opposite to track pan (verified by render, tests/live).
    assert reaper.envelopes[(track.pointer, "Pan")] == [(4.0, 0.5)]
    assert reaper.commands == []  # already visible: not toggled


def test_add_pan_automation_passes_out_of_range_pan_through(reaper, call):
    track = reaper.add_track("A")
    reaper.show_envelope(track, "Pan")
    result = call("add_pan_automation", track_index=0, position=0.0, pan=3.0)
    assert result["success"] is True
    assert reaper.envelopes[(track.pointer, "Pan")] == [(0.0, -3.0)]


def test_add_pan_automation_shows_a_missing_envelope(reaper, call):
    track = reaper.add_track("A")
    assert call("add_pan_automation", track_index=0, position=1.0, pan=0.5)["success"] is True
    assert reaper.commands == [40407]  # Track: Toggle track pan envelope visible
    assert reaper.envelopes == {(track.pointer, "Pan"): [(1.0, -0.5)]}
    assert track.selected is False


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


def test_create_send_python_default_is_unity_gain(reaper):
    src = reaper.add_track("Src")
    reaper.add_track("Dst")
    assert create_send(source_track_index=0, dest_track_index=1)["volume_db"] == 0.0
    assert src.sends[0].volume == 1.0


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


def test_create_bus_bad_index_changes_nothing(reaper, call):
    kick = reaper.add_track("Kick")
    result = call("create_bus", name="Drums", track_indices=[0, 7])
    assert result == {"success": False, "error": OUT_OF_RANGE}
    assert [t.name for t in reaper.tracks] == ["Kick"]
    assert kick.sends == []


def test_remove_send_bad_send_index(reaper, call):
    reaper.add_track("Src")
    assert call("remove_send", source_track_index=0, send_index=5) == {
        "success": False, "error": "track 0 has no send 5",
    }


def test_set_send_volume_bad_send_index(reaper, call):
    reaper.add_track("Src")
    assert call("set_send_volume", source_track_index=0, send_index=5, volume_db=-6.0) == {
        "success": False, "error": "track 0 has no send 5",
    }




def test_automation_reports_an_envelope_reaper_did_not_create(reaper, call, monkeypatch):
    from reapy import reascript_api

    reaper.add_track("A")
    monkeypatch.setattr(reascript_api, "Main_OnCommand", lambda *_: None)
    result = call("add_volume_automation", track_index=0, position=1.0, value_db=0.0)
    assert result == {"success": False, "error": "REAPER did not create the volume envelope"}
