"""Analysis tools on signals the default render does not produce: clipping,
one silent channel, identical and inverted channels."""

import pytest

from tests.helpers import assert_rendered_and_deleted


def test_detect_clipping_finds_samples_at_full_scale(reaper, call):
    reaper.signal = [(1.5, 440.0), (0.25, 660.0)]
    result = call("detect_clipping")
    assert result["clipping_detected"] is True
    assert result["clipped_samples"] > 0
    assert (result["peak_linear"], result["peak_db"]) == (1.0, 0.0)
    assert_rendered_and_deleted(reaper)


def test_detect_clipping_stays_quiet_just_under_full_scale(reaper, call):
    reaper.signal = [(0.99, 440.0), (0.25, 660.0)]
    result = call("detect_clipping")
    assert (result["clipping_detected"], result["clipped_samples"]) == (False, 0)


def test_stereo_field_with_one_silent_channel(reaper, call):
    reaper.signal = [(0.5, 440.0), (0.0, 660.0)]
    assert call("analyze_stereo_field") == {"success": False, "error": "Project appears to be silent"}


def test_stereo_field_identical_channels_are_mono(reaper, call):
    reaper.signal = [(0.5, 440.0), (0.5, 440.0)]
    result = call("analyze_stereo_field")
    assert result["stereo_width_ratio"] == 0.0
    assert result["lr_correlation"] == pytest.approx(1.0)
    assert result["mono_compatible"] is True
    assert result["side_rms_db"] < -100


def test_stereo_field_inverted_channels_cancel_in_mono(reaper, call):
    reaper.signal = [(0.5, 440.0), (-0.5, 440.0)]
    result = call("analyze_stereo_field")
    assert result["lr_correlation"] == pytest.approx(-1.0)
    assert result["mono_compatible"] is False
    assert result["mid_rms_db"] < -100
