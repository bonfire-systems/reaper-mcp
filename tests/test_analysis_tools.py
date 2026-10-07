"""Characterization tests for analysis_tools, run end to end against the fake REAPER.

The fake renders 4 s of 440 Hz at 0.5 (left) and 660 Hz at 0.25 (right), so every
expected number below is derived from that signal rather than from the tool's code.
"""


import numpy as np
import pytest

from reaper_mcp.analysis_tools import _band_rms_db
from tests.helpers import assert_rendered_and_deleted

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
    # The bands without a tone hold only window leakage and quantization noise,
    # which depends on the render's bit depth, so only their ceiling is pinned.
    assert max(others) < levels["mids"] - 20
    # Levels are reported to 0.1 dB.
    assert levels == {name: round(level, 1) for name, level in levels.items()}
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


def test_detect_clipping_short_render_misses_the_crest(reaper, call):
    # 1 ms is 48 samples: none lands on the 440 Hz crest, so the peak sample sits
    # just under 0.5, and the reply keeps four decimals of it.
    reaper.length = 0.001
    n = np.arange(48) / 48000
    peak = float(np.max(LEFT * np.sin(2 * np.pi * 440 * n)))
    result = call("detect_clipping")
    assert result["peak_linear"] == pytest.approx(peak, abs=0.00005)
    assert result == {
        "success": True,
        "clipping_detected": False,
        "clipped_samples": 0,
        "peak_db": -6.02,
        "peak_linear": 0.4999,
    }
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


@pytest.mark.parametrize(("seconds", "dr_score"), [(3.0, 5.1), (2.99, 0.0)])
def test_analyze_dynamics_dr_needs_one_whole_3s_block(reaper, call, seconds, dr_score):
    # Exactly 3 s holds one DR block, whose crest is the steady tone's; anything
    # shorter holds none, and the DR score falls back to 0.
    reaper.length = seconds
    assert call("analyze_dynamics") == {
        "success": True,
        "rms_db": -14.1,
        "peak_db": -8.9,
        "crest_factor_db": 5.1,
        "dr_score": dr_score,
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


def stereo_stats(n_samples):
    """Width, L/R correlation and mid/side RMS (dB) of the first n samples, by definition."""
    t = np.arange(n_samples) / 48000
    left, right = LEFT * np.sin(2 * np.pi * 440 * t), RIGHT * np.sin(2 * np.pi * 660 * t)
    mid_rms = np.sqrt(np.mean(((left + right) / 2) ** 2))
    side_rms = np.sqrt(np.mean(((left - right) / 2) ** 2))
    corr = np.corrcoef(left, right)[0, 1]
    return side_rms / mid_rms, corr, 20 * np.log10(mid_rms), 20 * np.log10(side_rms)


@pytest.mark.parametrize(
    ("seconds", "width", "corr", "mid_db", "side_db", "mono_ok"),
    [(0.001, 0.599, 0.349, -12.1, -16.6, True), (0.003, 1.215, -0.25, -14.9, -13.2, False)],
)
def test_analyze_stereo_field_short_render(reaper, call, seconds, width, corr, mid_db, side_db,
                                           mono_ok):
    # Over a few milliseconds the two tones are not orthogonal, so mid and side differ
    # and the correlation leaves 0: positive at 1 ms, negative (phase trouble) at 3 ms.
    reaper.length = seconds
    result = call("analyze_stereo_field")
    expected = stereo_stats(round(seconds * 48000))
    got = [result[k] for k in ("stereo_width_ratio", "lr_correlation", "mid_rms_db", "side_rms_db")]
    assert got == pytest.approx(expected, abs=0.06)
    assert result == {
        "success": True,
        "stereo_width_ratio": width,
        "lr_correlation": corr,
        "mid_rms_db": mid_db,
        "side_rms_db": side_db,
        "mono_compatible": mono_ok,
        "notes": NOTES,
    }
    assert_rendered_and_deleted(reaper)


def test_analyze_stereo_field_silent(reaper, call):
    reaper.silent = True
    assert call("analyze_stereo_field") == {"success": False, "error": "Project appears to be silent"}
    assert_rendered_and_deleted(reaper)


# analyze_transients


def test_analyze_transients(reaper, call):
    result = call("analyze_transients")
    times = result["onset_times_seconds"]
    assert result["success"] is True
    assert result["note"] is None
    # Two steady tones have no real attacks, yet librosa's default detector reports
    # dozens of onsets from frame-to-frame flux and quantization noise; their exact
    # count depends on the render's bit depth, so only their shape is pinned.
    assert 0 < result["onset_count"] == len(times) <= 100
    # Distinct events in time order, each to the millisecond.
    assert times == sorted(set(times))
    assert times == [round(t, 3) for t in times]
    assert 0 < times[0] and times[-1] < 4.0
    # Transient analysis renders at 44.1 kHz instead of the 48 kHz default.
    assert_rendered_and_deleted(reaper, rate=44100)


def test_analyze_transients_caps_the_list_at_100(reaper, call):
    # 8 s of the steady tones yields well over 100 detected onsets.
    reaper.length = 8.0
    result = call("analyze_transients")
    times = result["onset_times_seconds"]
    assert result["onset_count"] > 100
    assert len(times) == 100
    assert result["note"] == "Showing up to 100 events"
    assert times == sorted(set(times))
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
