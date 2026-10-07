"""Track tools against a running REAPER: each tool's effect, read back
through REAPER's own track info values rather than the tool's reply."""

import pytest

pytestmark = pytest.mark.live


def test_set_track_volume_moves_the_fader(live_project, call):
    live_project.add_track(0, "t")
    result = call("set_track_volume", track_index=0, volume_db=-6.0)
    assert result["success"] is True
    assert result["volume_db"] == pytest.approx(-6.0, abs=0.01)
    assert live_project.tracks[0].get_info_value("D_VOL") == pytest.approx(10 ** (-6 / 20), abs=1e-4)


def test_set_track_pan_moves_the_pan(live_project, call):
    live_project.add_track(0, "t")
    result = call("set_track_pan", track_index=0, pan=-0.5)
    assert result == {"success": True, "track_index": 0, "pan": pytest.approx(-0.5)}
    assert live_project.tracks[0].get_info_value("D_PAN") == pytest.approx(-0.5)


def test_set_track_mute_and_unmute(live_project, call):
    live_project.add_track(0, "t")
    assert call("set_track_mute", track_index=0, muted=True)["muted"] is True
    assert live_project.tracks[0].is_muted is True
    assert call("set_track_mute", track_index=0, muted=False)["muted"] is False
    assert live_project.tracks[0].is_muted is False


def test_set_track_solo_and_unsolo(live_project, call):
    live_project.add_track(0, "t")
    assert call("set_track_solo", track_index=0, soloed=True)["soloed"] is True
    assert live_project.tracks[0].is_solo is True
    assert call("set_track_solo", track_index=0, soloed=False)["soloed"] is False
    assert live_project.tracks[0].is_solo is False


def test_get_track_info_and_list_tracks(live_project, call):
    track = live_project.add_track(0, "Bass")
    track.set_info_value("D_VOL", 0.5)
    track.set_info_value("D_PAN", 0.25)
    track.add_midi_item(0.0, 1.0)
    info = call("get_track_info", track_index=0)
    assert info["success"] is True, info
    assert info["volume_db"] == pytest.approx(-6.02, abs=0.01)
    assert info["pan"] == pytest.approx(0.25)
    assert (info["muted"], info["soloed"]) == (False, False)
    assert info["item_count"] == 1
    assert info["items"][0]["length"] == pytest.approx(1.0)
    listed = call("list_tracks")
    assert listed["success"] is True, listed
    assert listed["tracks"][0]["name"] == "Bass"
    assert listed["tracks"][0]["volume_db"] == pytest.approx(-6.02, abs=0.01)
