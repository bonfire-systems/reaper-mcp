"""Characterization tests for analysis_tools, run end to end against the fake REAPER.

The fake renders 4 s of 440 Hz at 0.5 (left) and 660 Hz at 0.25 (right), so every
expected number below is derived from that signal rather than from the tool's code.
"""

import math

import numpy as np
import pytest

from reaper_mcp.analysis_tools import _band_rms_db

RENDER = 41824
LEFT, RIGHT = 0.5, 0.25
# Mono downmix (L + R) / 2: 440 Hz at 0.25 plus 660 Hz at 0.125.
MONO_440, MONO_660 = LEFT / 2, RIGHT / 2
MONO_RMS_DB = 10 * np.log10(MONO_440**2 / 2 + MONO_660**2 / 2)
BAND_RANGES = {
    "sub_bass": "20–60",
    "bass": "60–250",
    "low_mids": "250–500",
    "mids": "500–2000",
    "high_mids": "2000–4000",
    "presence": "4000–8000",
    "brilliance": "8000–20000",
}


def assert_rendered_and_deleted(reaper, rate=48000):
    """One render to a .wav temp file at `rate`, 24-bit stereo, removed afterwards."""
    assert reaper.commands == [RENDER]
    [path] = reaper.renders
    assert path.suffix == ".wav"
    assert not path.exists()
    assert reaper.project_info == {
        "RENDER_FILE": str(path),
        "RENDER_FORMAT": 0,
        "RENDER_FORMAT2": 2,
        "RENDER_SRATE": float(rate),
        "RENDER_CHANNELS": 2.0,
        "RENDER_BOUNDSFLAG": 0.0,
    }


def stft_band_db(amplitude, n_bins, n_fft=2048):
    """Mean |STFT|^2 of a Hann-windowed sine spread over n_bins (Parseval), in dB."""
    window_power = 3 * n_fft / 8
    return 10 * np.log10((n_fft / 2) * (amplitude**2 / 2) * window_power / n_bins)


def mono_peak():
    """Peak of the mono downmix over one 1/220 s period, sampled densely."""
    t = np.linspace(0, 1 / 220, 200_001)
    mix = MONO_440 * np.sin(2 * np.pi * 440 * t) + MONO_660 * np.sin(2 * np.pi * 660 * t)
    return float(np.max(np.abs(mix)))


# _band_rms_db


def test_band_rms_db_empty_band():
    d = np.ones((4, 3))
    assert _band_rms_db(d, np.array([10.0, 20.0, 30.0, 40.0]), (50, 60)) == -120.0


def test_band_rms_db_uses_inclusive_edges():
    freqs = np.array([10.0, 20.0, 30.0, 40.0])
    d = np.array([[1.0, 1.0], [10.0, 10.0], [10.0, 10.0], [100.0, 100.0]])
    assert _band_rms_db(d, freqs, (20, 30)) == pytest.approx(20.0)
    assert _band_rms_db(d, freqs, (10, 40)) == pytest.approx(10 * np.log10((1 + 100 + 100 + 10_000) / 4))


def test_band_rms_db_mean_power_over_bins_and_frames():
    d = np.array([[3.0, 0.0], [4.0, 0.0]])
    assert _band_rms_db(d, np.array([1.0, 2.0]), (0, 5)) == pytest.approx(10 * np.log10(25 / 4))


def test_band_rms_db_silence_floor():
    assert _band_rms_db(np.zeros((2, 2)), np.array([1.0, 2.0]), (0, 5)) == pytest.approx(-120.0)


# analyze_frequency_spectrum


def test_analyze_frequency_spectrum(reaper, call):
    result = call("analyze_frequency_spectrum")
    bands = result["frequency_bands"]
    assert result["success"] is True
    assert {name: band["range_hz"] for name, band in bands.items()} == BAND_RANGES
    levels = {name: band["level_db"] for name, band in bands.items()}
    # Bin spacing is 48000/2048 Hz: 250–500 Hz spans 11 bins, 500–2000 Hz spans 64.
    assert levels["low_mids"] == pytest.approx(stft_band_db(MONO_440, 11), abs=0.3)
    assert levels["mids"] == pytest.approx(stft_band_db(MONO_660, 64), abs=0.3)
    others = [v for k, v in levels.items() if k not in {"low_mids", "mids"}]
    assert max(others) < levels["mids"] - 20
    assert levels == {
        "sub_bass": -6.5,
        "bass": -5.3,
        "low_mids": 33.5,
        "mids": 19.8,
        "high_mids": -35.3,
        "presence": -47.4,
        "brilliance": -59.5,
    }
    assert_rendered_and_deleted(reaper)


def test_analyze_frequency_spectrum_silent(reaper, call):
    reaper.silent = True
    result = call("analyze_frequency_spectrum")
    assert result == {
        "success": True,
        "frequency_bands": {
            name: {"range_hz": hz, "level_db": -120.0} for name, hz in BAND_RANGES.items()
        },
    }
    assert_rendered_and_deleted(reaper)


# detect_clipping


def test_detect_clipping(reaper, call):
    result = call("detect_clipping")
    assert result == {
        "success": True,
        "clipping_detected": False,
        "clipped_samples": 0,
        "peak_db": pytest.approx(20 * np.log10(LEFT), abs=0.01),
        "peak_linear": LEFT,
    }
    assert result["peak_db"] == -6.02
    assert_rendered_and_deleted(reaper)


def test_detect_clipping_silent(reaper, call):
    reaper.silent = True
    assert call("detect_clipping") == {
        "success": True,
        "clipping_detected": False,
        "clipped_samples": 0,
        "peak_db": -120.0,
        "peak_linear": 0.0,
    }
    assert_rendered_and_deleted(reaper)


# analyze_dynamics


def test_analyze_dynamics(reaper, call):
    result = call("analyze_dynamics")
    peak_db = 20 * np.log10(mono_peak())
    assert result["success"] is True
    assert result["rms_db"] == pytest.approx(MONO_RMS_DB, abs=0.1)
    assert result["peak_db"] == pytest.approx(peak_db, abs=0.1)
    assert result["crest_factor_db"] == pytest.approx(peak_db - MONO_RMS_DB, abs=0.15)
    # 4 s holds one whole 3 s block, and a steady tone's block crest equals the overall one.
    assert result["dr_score"] == pytest.approx(peak_db - MONO_RMS_DB, abs=0.15)
    assert result == {
        "success": True,
        "rms_db": -14.1,
        "peak_db": -8.9,
        "crest_factor_db": 5.1,
        "dr_score": 5.1,
    }
    assert_rendered_and_deleted(reaper)


def test_analyze_dynamics_silent(reaper, call):
    reaper.silent = True
    assert call("analyze_dynamics") == {
        "success": True,
        "rms_db": -120.0,
        "peak_db": -120.0,
        "crest_factor_db": 0.0,
        "dr_score": 0.0,
    }
    assert_rendered_and_deleted(reaper)


# analyze_stereo_field

NOTES = (
    "width_ratio: 0=mono, >0.5=wide stereo. "
    "lr_correlation: 1=mono, 0=fully wide, <0=phase problems."
)


def test_analyze_stereo_field(reaper, call):
    result = call("analyze_stereo_field")
    # Mid and side both hold 440 Hz at 0.25 and 660 Hz at +/-0.125, so their RMS match.
    assert result["stereo_width_ratio"] == pytest.approx(1.0, abs=0.01)
    assert result["lr_correlation"] == pytest.approx(0.0, abs=0.01)
    assert result["mid_rms_db"] == pytest.approx(MONO_RMS_DB, abs=0.1)
    assert result["side_rms_db"] == pytest.approx(MONO_RMS_DB, abs=0.1)
    # mono_compatible is `correlation > 0` on the unrounded value; near 0 it falls True here.
    assert result == {
        "success": True,
        "stereo_width_ratio": 1.0,
        "lr_correlation": 0.0,
        "mid_rms_db": -14.1,
        "side_rms_db": -14.1,
        "mono_compatible": True,
        "notes": NOTES,
    }
    assert_rendered_and_deleted(reaper)


def test_analyze_stereo_field_silent_bug(reaper, call):
    reaper.silent = True
    result = call("analyze_stereo_field")
    # BUG: correlation of silence is NaN, sent as the non-JSON token NaN that strict JSON clients reject.
    assert math.isnan(result.pop("lr_correlation"))
    # The silence floor here is -200 dB, unlike the -120 dB the other analysis tools report.
    assert result == {
        "success": True,
        "stereo_width_ratio": 0.0,
        "mid_rms_db": -200.0,
        "side_rms_db": -200.0,
        "mono_compatible": False,
        "notes": NOTES,
    }
    assert_rendered_and_deleted(reaper)


# analyze_transients


def test_analyze_transients(reaper, call):
    result = call("analyze_transients")
    times = result["onset_times_seconds"]
    assert result["success"] is True
    assert result["note"] is None
    # Two steady tones have no real attacks; librosa's default detector still reports
    # 66 onsets from frame-to-frame flux. Pinned as-is.
    assert result["onset_count"] == len(times) == 66
    assert times == sorted(times)
    assert 0 < times[0] and times[-1] < 4.0
    assert times[:5] == [0.035, 0.104, 0.151, 0.209, 0.255]
    assert times[-3:] == [3.855, 3.901, 3.959]
    # Transient analysis renders at 44.1 kHz instead of the 48 kHz default.
    assert_rendered_and_deleted(reaper, rate=44100)


def test_analyze_transients_silent(reaper, call):
    reaper.silent = True
    assert call("analyze_transients") == {
        "success": True,
        "onset_count": 0,
        "onset_times_seconds": [],
        "note": None,
    }
    assert_rendered_and_deleted(reaper, rate=44100)
