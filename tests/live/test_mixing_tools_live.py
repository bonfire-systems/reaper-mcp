"""Mixing tools against a running REAPER. Automation is checked by rendering
a mono tone and measuring where it lands, not by reading the points back."""

import numpy as np
import pytest
import soundfile as sf
from reapy import reascript_api as RPR

pytestmark = pytest.mark.live

SHOW_VOLUME_ENVELOPE = 40406
SHOW_PAN_ENVELOPE = 40407


def show_envelope(track, action):
    RPR.SetOnlyTrackSelected(track.id)
    RPR.Main_OnCommand(action, 0)


def render_rms(call, tmp_path, name):
    out = tmp_path / f"{name}.wav"
    assert call("render_project", output_path=str(out))["success"] is True
    data, _ = sf.read(str(out))
    return np.sqrt((data**2).mean(axis=0))


def test_volume_automation_sets_the_level_in_db(add_tone, call, tmp_path):
    track = add_tone("a", 440)
    plain = render_rms(call, tmp_path, "plain")
    show_envelope(track, SHOW_VOLUME_ENVELOPE)
    result = call("add_volume_automation", track_index=0, position=0.0, value_db=-6.0)
    assert result["success"] is True, result
    automated = render_rms(call, tmp_path, "automated")
    assert 20 * np.log10(automated[0] / plain[0]) == pytest.approx(-6.0, abs=0.1)


def test_pan_automation_full_right_is_right(add_tone, call, tmp_path):
    track = add_tone("a", 440)
    show_envelope(track, SHOW_PAN_ENVELOPE)
    assert call("add_pan_automation", track_index=0, position=0.0, pan=1.0)["success"] is True
    left, right = render_rms(call, tmp_path, "panned")
    assert left < 1e-4 < right


def test_sends(live_project, call):
    live_project.add_track(0, "src")
    live_project.add_track(1, "dst")
    created = call("create_send", source_track_index=0, dest_track_index=1, volume_db=-6.0)
    assert created["success"] is True, created
    source = live_project.tracks[0]
    assert RPR.GetTrackSendInfo_Value(source.id, 0, 0, "D_VOL") == pytest.approx(10 ** (-6 / 20))
    call("set_send_volume", source_track_index=0, send_index=0, volume_db=-12.0)
    assert RPR.GetTrackSendInfo_Value(source.id, 0, 0, "D_VOL") == pytest.approx(10 ** (-12 / 20))
    assert call("list_sends", track_index=0)["sends"][0]["volume_linear"] == pytest.approx(10 ** (-12 / 20))
    assert call("set_send_volume", source_track_index=0, send_index=5, volume_db=0.0)["success"] is False
    assert call("remove_send", source_track_index=0, send_index=5)["success"] is False
    assert call("remove_send", source_track_index=0, send_index=0)["success"] is True
    assert RPR.GetTrackNumSends(source.id, 0) == 0


def test_create_bus_refuses_a_bad_index_without_side_effects(live_project, call):
    live_project.add_track(0, "a")
    result = call("create_bus", name="Bus", track_indices=[0, 7])
    assert result["success"] is False
    assert live_project.n_tracks == 1
    assert RPR.GetTrackNumSends(live_project.tracks[0].id, 0) == 0
