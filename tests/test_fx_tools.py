"""Characterization tests for fx_tools, run end to end against the fake REAPER."""

from tests.fake_reaper.objects import FXState


def _fx_track(reaper):
    """A track carrying ReaEQ then ReaComp, with distinct parameter values."""
    track = reaper.add_track("Bus")
    track.fxs.append(FXState("ReaEQ", [0.1, 0.2, 0.3]))
    track.fxs.append(FXState("ReaComp", [0.4, 0.5, 0.6, 0.7]))
    return track


# add_fx


def test_add_fx_compares_fx_object_bug(reaper, call):
    track = reaper.add_track("Bus")
    result = call("add_fx", track_index=0, fx_name="ReaComp")
    # BUG: reapy add_fx returns an FX, not an index, so `< 0` raises; every add reports failure.
    assert result["success"] is False
    assert result["error"].startswith("'<' not supported between instances of")
    assert result["error"].endswith("and 'int'")
    # ...yet the plugin was inserted.
    assert [(f.plugin, f.values) for f in track.fxs] == [("ReaComp", [0.5] * 4)]


def test_add_fx_missing_plugin(reaper, call):
    track = reaper.add_track("Bus")
    result = call("add_fx", track_index=0, fx_name="NoSuchVerb")
    assert result == {"success": False, "error": "Can't find FX named NoSuchVerb"}
    assert track.fxs == []


def test_add_fx_bad_track(reaper, call):
    result = call("add_fx", track_index=0, fx_name="ReaEQ")
    assert result == {"success": False, "error": "list index out of range"}


# remove_fx


def test_remove_fx(reaper, call):
    track = _fx_track(reaper)
    result = call("remove_fx", track_index=0, fx_index=0)
    assert result == {"success": True, "track_index": 0, "removed": "VST: ReaEQ (Cockos)"}
    assert [f.plugin for f in track.fxs] == ["ReaComp"]


def test_remove_fx_bad_index(reaper, call):
    track = _fx_track(reaper)
    result = call("remove_fx", track_index=0, fx_index=2)
    assert result == {"success": False, "error": "list index out of range"}
    assert len(track.fxs) == 2


def test_remove_fx_bad_track(reaper, call):
    result = call("remove_fx", track_index=0, fx_index=0)
    assert result == {"success": False, "error": "list index out of range"}


# set_fx_parameter


def test_set_fx_parameter_no_effect_bug(reaper, call):
    track = _fx_track(reaper)
    result = call("set_fx_parameter", track_index=0, fx_index=1, param_index=1, value=0.9)
    assert result == {
        "success": True,
        "track_index": 0,
        "fx_index": 1,
        "param_index": 1,
        "param_name": "Ratio",
        "value": 0.9,
    }
    # BUG: FXParam has `normalized`, not `normalized_value`; the write hits a throwaway proxy.
    assert track.fxs[1].values == [0.4, 0.5, 0.6, 0.7]


def test_set_fx_parameter_bad_param(reaper, call):
    _fx_track(reaper)
    result = call("set_fx_parameter", track_index=0, fx_index=0, param_index=3, value=0.9)
    assert result == {"success": False, "error": "list index out of range"}


def test_set_fx_parameter_bad_fx(reaper, call):
    _fx_track(reaper)
    result = call("set_fx_parameter", track_index=0, fx_index=5, param_index=0, value=0.9)
    assert result == {"success": False, "error": "list index out of range"}


# get_fx_parameters


def test_get_fx_parameters_wrong_attribute_bug(reaper, call):
    _fx_track(reaper)
    result = call("get_fx_parameters", track_index=0, fx_index=0)
    # BUG: FXParam has `normalized`/`formatted`, not `normalized_value`; reading params always fails.
    assert result["success"] is False
    assert result["error"].endswith("object has no attribute 'normalized_value'")


def test_get_fx_parameters_no_params(reaper, call):
    track = reaper.add_track("Bus")
    track.fxs.append(FXState("ReaEQ", []))
    result = call("get_fx_parameters", track_index=0, fx_index=0)
    assert result == {
        "success": True,
        "track_index": 0,
        "fx_index": 0,
        "fx_name": "VST: ReaEQ (Cockos)",
        "parameters": [],
    }


def test_get_fx_parameters_bad_fx(reaper, call):
    reaper.add_track("Bus")
    result = call("get_fx_parameters", track_index=0, fx_index=0)
    assert result == {"success": False, "error": "list index out of range"}


# list_track_fx


def test_list_track_fx(reaper, call):
    track = _fx_track(reaper)
    track.fxs[1].enabled = False
    assert call("list_track_fx", track_index=0) == {
        "success": True,
        "track_index": 0,
        "fx": [
            {"index": 0, "name": "VST: ReaEQ (Cockos)", "enabled": True, "n_params": 3},
            {"index": 1, "name": "VST: ReaComp (Cockos)", "enabled": False, "n_params": 4},
        ],
    }


def test_list_track_fx_empty(reaper, call):
    reaper.add_track("Bus")
    assert call("list_track_fx", track_index=0) == {"success": True, "track_index": 0, "fx": []}


def test_list_track_fx_bad_track(reaper, call):
    result = call("list_track_fx", track_index=0)
    assert result == {"success": False, "error": "list index out of range"}


# bypass_fx


def test_bypass_fx(reaper, call):
    track = _fx_track(reaper)
    result = call("bypass_fx", track_index=0, fx_index=1, bypassed=True)
    assert result == {
        "success": True,
        "track_index": 0,
        "fx_index": 1,
        "fx_name": "VST: ReaComp (Cockos)",
        "bypassed": True,
    }
    assert [f.enabled for f in track.fxs] == [True, False]
    assert call("bypass_fx", track_index=0, fx_index=1, bypassed=False)["bypassed"] is False
    assert [f.enabled for f in track.fxs] == [True, True]


def test_bypass_fx_bad_fx(reaper, call):
    reaper.add_track("Bus")
    result = call("bypass_fx", track_index=0, fx_index=0, bypassed=True)
    assert result == {"success": False, "error": "list index out of range"}


# load_fx_preset


def test_load_fx_preset_no_effect_bug(reaper, call):
    track = _fx_track(reaper)
    result = call("load_fx_preset", track_index=0, fx_index=0, preset_name="Vocal Air")
    assert result == {
        "success": True,
        "track_index": 0,
        "fx_index": 0,
        "fx_name": "VST: ReaEQ (Cockos)",
        "preset": "Vocal Air",
    }
    # BUG: reapy FX has `preset`, not `preset_name`; the preset is never loaded in REAPER.
    assert [f.preset for f in track.fxs] == ["", ""]


def test_load_fx_preset_bad_fx(reaper, call):
    reaper.add_track("Bus")
    result = call("load_fx_preset", track_index=0, fx_index=0, preset_name="Vocal Air")
    assert result == {"success": False, "error": "list index out of range"}
