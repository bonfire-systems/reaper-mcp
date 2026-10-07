"""Characterization tests for mastering_tools, run end to end against the fake REAPER."""

import numpy as np
import pytest

from tests.fake_reaper.objects import FXState

DEFAULT_INFO = {"D_VOL": 1.0, "D_PAN": 0.0, "B_MUTE": 0.0, "I_SOLO": 0.0}
RENDER = 41824


def plugins(reaper):
    return [fx.plugin for fx in reaper.master.fxs]


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


# add_master_fx


def test_add_master_fx_index_comparison_bug(reaper, call):
    result = call("add_master_fx", fx_name="ReaEQ")
    # BUG: reapy add_fx returns an FX, not an index; the plugin is inserted but the tool reports failure.
    assert result == {
        "success": False,
        "error": "'<' not supported between instances of 'FakeFX' and 'int'",
    }
    assert plugins(reaper) == ["ReaEQ"]


def test_add_master_fx_unknown_plugin(reaper, call):
    result = call("add_master_fx", fx_name="Nope")
    assert result == {"success": False, "error": "Can't find FX named Nope"}
    assert reaper.master.fxs == []


# list_master_fx


def test_list_master_fx_empty(reaper, call):
    assert call("list_master_fx") == {"success": True, "fx": []}


def test_list_master_fx(reaper, call):
    reaper.master.fxs.append(FXState("ReaEQ", [0.5, 0.5, 0.5]))
    reaper.master.fxs.append(FXState("ReaLimit", [0.1, 0.2, 0.3], enabled=False))
    assert call("list_master_fx") == {
        "success": True,
        "fx": [
            {"index": 0, "name": "VST: ReaEQ (Cockos)", "enabled": True, "n_params": 3},
            {"index": 1, "name": "VST: ReaLimit (Cockos)", "enabled": False, "n_params": 3},
        ],
    }


def test_list_master_fx_ignores_track_fx(reaper, call):
    reaper.add_track("a").fxs.append(FXState("ReaComp", [0.5] * 4))
    assert call("list_master_fx") == {"success": True, "fx": []}


# set_master_fx_parameter


def test_set_master_fx_parameter_bug(reaper, call):
    reaper.master.fxs.append(FXState("ReaEQ", [0.5, 0.5, 0.5]))
    result = call("set_master_fx_parameter", fx_index=0, param_index=1, value=0.9)
    # BUG: FXParam has `normalized`, not `normalized_value`; REAPER's parameter never changes.
    assert result == {
        "success": True,
        "fx_index": 0,
        "param_index": 1,
        "param_name": "Freq-Low",
        "value": 0.9,
    }
    assert reaper.master.fxs[0].values == [0.5, 0.5, 0.5]


def test_set_master_fx_parameter_fx_out_of_range(reaper, call):
    reaper.master.fxs.append(FXState("ReaEQ", [0.5, 0.5, 0.5]))
    result = call("set_master_fx_parameter", fx_index=1, param_index=0, value=0.9)
    assert result == {"success": False, "error": "list index out of range"}


def test_set_master_fx_parameter_param_out_of_range(reaper, call):
    reaper.master.fxs.append(FXState("ReaEQ", [0.5, 0.5, 0.5]))
    result = call("set_master_fx_parameter", fx_index=0, param_index=3, value=0.9)
    assert result == {"success": False, "error": "list index out of range"}
    assert reaper.master.fxs[0].values == [0.5, 0.5, 0.5]


# set_master_volume


def test_set_master_volume_bug(reaper, call):
    result = call("set_master_volume", volume_db=-3.0)
    # BUG: reapy Track has no volume; the value lands on a throwaway proxy and the master fader never moves.
    assert result == {"success": True, "volume_db": -3.0}
    assert reaper.master.info == DEFAULT_INFO


# apply_mastering_chain


@pytest.mark.parametrize("preset", ["default", "loud", "gentle"])
def test_apply_mastering_chain_index_comparison_bug(reaper, call, preset):
    result = call("apply_mastering_chain", preset=preset)
    # BUG: add_fx returns an FX, so `>= 0` raises after the first plugin; REAPER is left with only ReaEQ.
    assert result == {
        "success": False,
        "error": "'>=' not supported between instances of 'FakeFX' and 'int'",
    }
    assert plugins(reaper) == ["ReaEQ"]


def test_apply_mastering_chain_default_preset_bug(reaper, call):
    result = call("apply_mastering_chain")
    # BUG: same as above with the preset left at its default; the chain stops after ReaEQ.
    assert result["success"] is False
    assert plugins(reaper) == ["ReaEQ"]


def test_apply_mastering_chain_unknown_preset(reaper, call):
    result = call("apply_mastering_chain", preset="x")
    assert result == {
        "success": False,
        "error": "Unknown preset 'x'. Available: ['default', 'loud', 'gentle']",
    }
    assert reaper.master.fxs == []


# apply_limiter


def test_apply_limiter_index_comparison_bug(reaper, call):
    result = call("apply_limiter", threshold_db=-1.0, release_ms=80.0)
    # BUG: add_fx returns an FX, so `< 0` raises; ReaLimit is inserted but the tool reports failure.
    assert result == {
        "success": False,
        "error": "'<' not supported between instances of 'FakeFX' and 'int'",
    }
    # threshold_db and release_ms are never applied to any parameter.
    assert [(fx.plugin, fx.values) for fx in reaper.master.fxs] == [("ReaLimit", [0.5] * 3)]


# analyze_loudness


def test_analyze_loudness(reaper, call):
    result = call("analyze_loudness")
    # BS.1770 ungated loudness of the two channels' mean squares; K-weighting barely
    # touches 440/660 Hz, and gating keeps every block of a steady tone.
    expected_lufs = -0.691 + 10 * np.log10(0.5**2 / 2 + 0.25**2 / 2)
    assert set(result) == {"success", "integrated_lufs", "true_peak_dbtp", "sample_rate"}
    assert result["success"] is True
    assert result["integrated_lufs"] == pytest.approx(expected_lufs, abs=0.2)
    assert result["integrated_lufs"] == -8.8
    assert result["true_peak_dbtp"] == pytest.approx(20 * np.log10(0.5), abs=0.05)
    assert result["true_peak_dbtp"] == -6.0
    assert result["sample_rate"] == 48000
    assert_rendered_and_deleted(reaper)


def test_analyze_loudness_silent_bug(reaper, call):
    reaper.silent = True
    result = call("analyze_loudness")
    # BUG: -inf LUFS is sent as the non-JSON token -Infinity, which strict JSON clients reject.
    assert result == {
        "success": True,
        "integrated_lufs": float("-inf"),
        "true_peak_dbtp": -120.0,
        "sample_rate": 48000,
    }
    assert_rendered_and_deleted(reaper)


# normalize_project


def test_normalize_project_volume_bug(reaper, call):
    result = call("normalize_project", target_lufs=-14.0)
    # BUG: reapy Track has no volume, so after measuring, reading master.volume raises and no gain is applied.
    assert result == {"success": False, "error": "'FakeTrack' object has no attribute 'volume'"}
    assert reaper.master.info == DEFAULT_INFO
    assert_rendered_and_deleted(reaper)


def test_normalize_project_silent(reaper, call):
    reaper.silent = True
    assert call("normalize_project") == {"success": False, "error": "Project appears to be silent"}
    assert reaper.master.info == DEFAULT_INFO
    assert_rendered_and_deleted(reaper)
