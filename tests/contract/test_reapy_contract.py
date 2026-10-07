"""The reapy behaviours the fake models, checked against the fake and, with
--live, against a running REAPER.

tests/test_fake_reaper.py proves the fake exposes only API reapy's classes
have. This proves the fake *behaves* like REAPER where the server's bugs and
fixes depend on it, so a characterization test that passes on the fake means
the same thing in REAPER.
"""

import pytest
from tests.live.rpr import RPR
from reapy.errors import DistError

from tests.fake_reaper import install


@pytest.fixture(params=["fake", pytest.param("live", marks=pytest.mark.live)])
def project(request, monkeypatch, tmp_path):
    if request.param == "fake":
        return install(monkeypatch, tmp_path).project
    return request.getfixturevalue("live_project")


def test_time_signature_is_bpm_and_numerator(project):
    project.bpm = 95.0
    bpm, numerator = project.time_signature
    assert bpm == pytest.approx(95.0)
    assert numerator == pytest.approx(4.0)


def test_bpm_reads_in_beats_of_the_denominator(project):
    """reapy's getter doubles the quarter-note tempo in x/8; its setter does not."""
    RPR.SetTempoTimeSigMarker(0, -1, 0.0, -1, -1, 120.0, 6, 8, False)
    assert project.bpm == pytest.approx(240.0)
    assert RPR.Master_GetTempo() == pytest.approx(120.0)
    project.bpm = 90.0
    assert RPR.Master_GetTempo() == pytest.approx(90.0)


def test_a_missing_envelope_is_a_truthy_null_pointer(project):
    track = project.add_track(0, "t")
    envelope = RPR.GetTrackEnvelopeByName(track.id, "Volume")
    assert envelope == "(TrackEnvelope*)0x0000000000000000"
    assert envelope  # truthy: `if not envelope` cannot detect it


def test_time_signature_is_read_only(project):
    with pytest.raises(AttributeError):
        project.time_signature = (3, 4)


def test_save_rejects_a_path(project):
    with pytest.raises(DistError, match="cannot be interpreted as an integer"):
        project.save("/tmp/never-written.rpp")


def test_add_fx_returns_an_fx_object(project):
    track = project.add_track(0, "fx")
    fx = track.add_fx("ReaEQ")
    assert "ReaEQ" in fx.name
    with pytest.raises(TypeError):
        _ = fx < 0
    with pytest.raises(ValueError):
        track.add_fx("No Such Plugin 7f3a")


def test_track_has_no_volume_or_pan(project):
    track = project.add_track(0, "t")
    assert not hasattr(track, "volume")
    assert not hasattr(track, "pan")


def test_solo_and_mute_are_methods_and_assignment_does_nothing(project):
    project.add_track(0, "t")
    track = project.tracks[0]
    assert callable(track.solo)
    assert callable(track.mute)
    track.solo = True
    track.mute = True
    fresh = project.tracks[0]
    assert fresh.is_solo is False
    assert fresh.is_muted is False


def test_mute_takes_effect_but_solo_does_not(project):
    """reapy mutes through action 40280, which works, and solos through
    action 7, which leaves solo unchanged on REAPER 7.82; is_solo's setter
    goes through the same path."""
    project.add_track(0, "t")
    project.tracks[0].mute()
    project.tracks[0].solo()
    project.tracks[0].is_solo = True
    assert project.tracks[0].is_muted is True
    assert project.tracks[0].is_solo is False


def test_solo_through_track_info_takes_effect(project):
    project.add_track(0, "t")
    project.tracks[0].set_info_value("I_SOLO", 2)
    assert project.tracks[0].is_solo is True
    project.tracks[0].set_info_value("I_SOLO", 0)
    assert project.tracks[0].is_solo is False


def test_markers_and_regions_have_no_name(project):
    project.add_marker(1.0, name="verse")
    project.add_region(2.0, 4.0, name="chorus")
    assert not hasattr(project.markers[0], "name")
    assert not hasattr(project.regions[0], "name")
    assert project.markers[0].position == pytest.approx(1.0)


def test_fx_param_normalized_setter_is_broken_in_reapy(project):
    """reapy 0.10's setter reads parent_fx.id, which FX does not have."""
    track = project.add_track(0, "fx")
    track.add_fx("ReaEQ")
    param = track.fxs[0].params[0]
    with pytest.raises(AttributeError, match="has no attribute 'id'"):
        param.normalized = 0.25
    assert not hasattr(param, "normalized_value")
    assert not hasattr(param, "formatted_value")


def test_midi_item_take_is_midi(project):
    track = project.add_track(0, "midi")
    item = track.add_midi_item(0.0, 2.0)
    assert item.active_take.is_midi
    assert item.length == pytest.approx(2.0)
