"""Characterization tests for mastering_tools, run end to end against the fake REAPER."""

import numpy as np
import pytest

from tests.fake_reaper.objects import FXState
from reaper_mcp.mastering_tools import MASTERING_PRESETS
from tests.helpers import assert_rendered_and_deleted

DEFAULT_INFO = {"D_VOL": 1.0, "D_PAN": 0.0, "B_MUTE": 0.0, "I_SOLO": 0.0}


def plugins(reaper):
    return [fx.plugin for fx in reaper.master.fxs]


# add_master_fx


def test_add_master_fx(reaper, call):
    assert call("add_master_fx", fx_name="ReaEQ") == {
        "success": True, "fx_index": 0, "name": "VST: ReaEQ (Cockos)", "n_params": 3,
    }
    assert call("add_master_fx", fx_name="ReaComp")["fx_index"] == 1
    assert plugins(reaper) == ["ReaEQ", "ReaComp"]


def test_add_master_fx_unknown_plugin(reaper, call):
    result = call("add_master_fx", fx_name="Nope")
    assert result == {"success": False, "error": "Plugin not found: 'Nope'"}
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


def test_set_master_fx_parameter(reaper, call):
    reaper.master.fxs.append(FXState("ReaEQ", [0.5, 0.5, 0.5]))
    result = call("set_master_fx_parameter", fx_index=0, param_index=1, value=0.9)
    assert result == {
        "success": True,
        "fx_index": 0,
        "param_index": 1,
        "param_name": "Freq-Low",
        "value": 0.9,
    }
    assert reaper.master.fxs[0].values == [0.5, 0.9, 0.5]


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


def test_set_master_volume(reaper, call):
    assert call("set_master_volume", volume_db=-3.0) == {"success": True, "volume_db": -3.0}
    assert reaper.master.info["D_VOL"] == pytest.approx(10 ** (-3 / 20))


# apply_mastering_chain


@pytest.mark.parametrize(
    ("preset", "chain"),
    [("default", ["ReaEQ", "ReaComp", "ReaLimit"]),
     ("loud", ["ReaEQ", "ReaComp", "ReaComp", "ReaLimit"]),
     ("gentle", ["ReaEQ", "ReaComp", "ReaLimit"])],
)
def test_apply_mastering_chain(reaper, call, preset, chain):
    result = call("apply_mastering_chain", preset=preset)
    assert result["success"] is True
    assert [fx["fx_index"] for fx in result["fx_chain"]] == list(range(len(chain)))
    assert result["missing"] == []
    assert plugins(reaper) == chain


def test_apply_mastering_chain_reports_missing_plugins(reaper, call, monkeypatch):
    monkeypatch.setitem(MASTERING_PRESETS, "default", ["ReaEQ", "NoSuchComp", "ReaLimit"])
    result = call("apply_mastering_chain")
    assert result["missing"] == ["NoSuchComp"]
    assert plugins(reaper) == ["ReaEQ", "ReaLimit"]


def test_apply_mastering_chain_unknown_preset(reaper, call):
    result = call("apply_mastering_chain", preset="x")
    assert result == {
        "success": False,
        "error": "Unknown preset 'x'. Available: ['default', 'loud', 'gentle']",
    }
    assert reaper.master.fxs == []


# apply_limiter


def test_apply_limiter_sets_the_threshold(reaper, call):
    result = call("apply_limiter", threshold_db=-1.0, release_ms=80.0)
    assert result["success"] is True
    assert (result["fx_index"], result["threshold"]) == (0, "-1.00 dB")
    assert result["release_ms_applied"] is False
    assert "release_ms=80.0 was not applied" in result["hint"]
    [limiter] = reaper.master.fxs
    # The bisection runs over REAPER's two-decimal display, so it is exact to that.
    assert limiter.values[0] * 72 - 60 == pytest.approx(-1.0, abs=0.005)
    assert limiter.values[1:] == [0.5, 0.5]


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


def test_analyze_loudness_silent(reaper, call):
    reaper.silent = True
    assert call("analyze_loudness") == {"success": False, "error": "Project appears to be silent"}
    assert_rendered_and_deleted(reaper)


# normalize_project


def test_normalize_project(reaper, call):
    reaper.master.info["D_VOL"] = 0.5
    result = call("normalize_project", target_lufs=-14.0)
    gain = -14.0 - result["original_lufs"]
    assert result["success"] is True
    assert result["gain_applied_db"] == pytest.approx(gain, abs=0.1)
    assert result["new_master_volume_db"] == pytest.approx(-6.02 + gain, abs=0.1)
    assert reaper.master.info["D_VOL"] == pytest.approx(10 ** ((-6.0206 + gain) / 20), rel=0.01)
    assert_rendered_and_deleted(reaper)


def test_normalize_project_silent(reaper, call):
    reaper.silent = True
    assert call("normalize_project") == {"success": False, "error": "Project appears to be silent"}
    assert reaper.master.info == DEFAULT_INFO
    assert_rendered_and_deleted(reaper)
