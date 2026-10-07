"""FX and master-FX tools against a running REAPER, read back through
REAPER's own FX state."""

import numpy as np
import pytest
import soundfile as sf
from tests.live.rpr import RPR

pytestmark = pytest.mark.live


def test_add_fx_reports_its_index(live_project, call):
    live_project.add_track(0, "t")
    first = call("add_fx", track_index=0, fx_name="ReaEQ")
    second = call("add_fx", track_index=0, fx_name="ReaComp")
    assert (first["success"], first["fx_index"]) == (True, 0), first
    assert (second["fx_index"], second["name"]) == (1, "VST: ReaComp (Cockos)")
    assert [fx.name for fx in live_project.tracks[0].fxs] == ["VST: ReaEQ (Cockos)", "VST: ReaComp (Cockos)"]


def test_add_fx_missing_plugin(live_project, call):
    live_project.add_track(0, "t")
    result = call("add_fx", track_index=0, fx_name="No Such Plugin 7f3a")
    assert result == {"success": False, "error": "Plugin not found: 'No Such Plugin 7f3a'"}
    assert live_project.tracks[0].n_fxs == 0


def test_set_and_get_fx_parameters(live_project, call):
    live_project.add_track(0, "t").add_fx("ReaEQ")
    result = call("set_fx_parameter", track_index=0, fx_index=0, param_index=0, value=0.25)
    assert result["success"] is True, result
    assert live_project.tracks[0].fxs[0].params[0].normalized == pytest.approx(0.25, abs=1e-6)
    params = call("get_fx_parameters", track_index=0, fx_index=0)
    assert params["success"] is True, params
    assert params["parameters"][0]["normalized_value"] == pytest.approx(0.25, abs=1e-6)
    assert params["parameters"][0]["formatted_value"]


def test_bypass_fx(live_project, call):
    live_project.add_track(0, "t").add_fx("ReaEQ")
    assert call("bypass_fx", track_index=0, fx_index=0, bypassed=True)["bypassed"] is True
    assert live_project.tracks[0].fxs[0].is_enabled is False


def test_load_fx_preset(live_project, call):
    fx = live_project.add_track(0, "t").add_fx("ReaEQ")
    fx.use_next_preset()
    name = live_project.tracks[0].fxs[0].preset
    fx.use_next_preset()
    assert call("load_fx_preset", track_index=0, fx_index=0, preset_name=name)["success"] is True
    assert live_project.tracks[0].fxs[0].preset == name
    missing = call("load_fx_preset", track_index=0, fx_index=0, preset_name="No Such Preset 7f3a")
    assert missing["success"] is False


def test_master_fx_chain_and_limiter(live_project, call):
    chain = call("apply_mastering_chain", preset="loud")
    assert chain["success"] is True, chain
    assert [fx["fx_index"] for fx in chain["fx_chain"]] == [0, 1, 2, 3]
    limiter = call("apply_limiter", threshold_db=-3.0, release_db_per_sec=12.0)
    assert limiter["success"] is True, limiter
    master = live_project.master_track
    shown = [RPR.TrackFX_GetFormattedParamValue(master.id, limiter["fx_index"], i, "", 64)[4]
             for i in (0, 2)]  # ReaLimit: 0 Threshold, 2 Release
    assert float(shown[0].split()[0]) == pytest.approx(-3.0, abs=0.01)
    assert float(shown[1].split()[0]) == pytest.approx(12.0, abs=0.05)
    assert call("set_master_fx_parameter", fx_index=0, param_index=0, value=0.4)["success"] is True
    assert master.fxs[0].params[0].normalized == pytest.approx(0.4, abs=1e-6)


def test_set_master_volume(live_project, call):
    assert call("set_master_volume", volume_db=-6.0)["volume_db"] == pytest.approx(-6.0, abs=0.01)
    assert live_project.master_track.get_info_value("D_VOL") == pytest.approx(10 ** (-6 / 20), abs=1e-4)
    call("set_master_volume", volume_db=0.0)


def test_normalize_project_moves_the_master_fader(live_project, call, tmp_path):
    rate = 48000
    tone = 0.1 * np.sin(2 * np.pi * 440 * np.arange(rate * 4) / rate)
    wav = tmp_path / "tone.wav"
    sf.write(wav, np.stack([tone, tone], axis=1), rate)
    live_project.add_track(0, "tone")
    assert call("import_audio_file", file_path=str(wav), track_index=0)["success"] is True
    before = call("analyze_loudness")["integrated_lufs"]
    result = call("normalize_project", target_lufs=-14.0)
    assert result["success"] is True, result
    assert result["gain_applied_db"] == pytest.approx(-14.0 - before, abs=0.2)
    assert call("analyze_loudness")["integrated_lufs"] == pytest.approx(-14.0, abs=0.5)
    call("set_master_volume", volume_db=0.0)
