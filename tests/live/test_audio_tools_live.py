"""Audio item tools against a running REAPER, read back through REAPER's own
item and take info values."""

import pytest

pytestmark = pytest.mark.live


def item_and_take(live_project):
    item = live_project.tracks[0].items[0]
    return item, item.active_take


def test_edit_audio_item_trims_and_fades(add_tone, call, live_project):
    add_tone("a", 440)
    result = call("edit_audio_item", track_index=0, item_index=0, start_trim=0.5, end_trim=0.25,
                  fade_in=0.1, fade_out=0.2)
    assert result["success"] is True, result
    item, take = item_and_take(live_project)
    assert item.position == pytest.approx(0.5)
    assert item.length == pytest.approx(1.25)
    assert take.get_info_value("D_STARTOFFS") == pytest.approx(0.5)
    assert item.get_info_value("D_FADEINLEN") == pytest.approx(0.1)
    assert item.get_info_value("D_FADEOUTLEN") == pytest.approx(0.2)
    assert (result["position"], result["length"]) == (pytest.approx(0.5), pytest.approx(1.25))


def test_adjust_pitch(add_tone, call, live_project):
    add_tone("a", 440)
    assert call("adjust_pitch", track_index=0, item_index=0, semitones=-3.5)["pitch_semitones"] == -3.5
    assert item_and_take(live_project)[1].get_info_value("D_PITCH") == pytest.approx(-3.5)


def test_adjust_playback_rate(add_tone, call, live_project):
    add_tone("a", 440)
    assert call("adjust_playback_rate", track_index=0, item_index=0, rate=0.5)["playback_rate"] == 0.5
    assert item_and_take(live_project)[1].get_info_value("D_PLAYRATE") == pytest.approx(0.5)


def test_start_recording_arms_the_track(live_project, call):
    live_project.add_track(0, "vox")
    result = call("start_recording", track_index=0)
    call("stop_transport")
    assert result["success"] is True, result
    assert live_project.tracks[0].get_info_value("I_RECARM") == 1
    for item in list(live_project.tracks[0].items):
        item.delete()
