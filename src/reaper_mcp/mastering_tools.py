import os

from reaper_mcp.fx_tools import add_plugin, set_param_normalized
from reaper_mcp.reaper import RPR, get_project
from reaper_mcp.units import db_to_linear, linear_to_db

MASTERING_PRESETS = {
    "default": ["ReaEQ", "ReaComp", "ReaLimit"],
    "loud":    ["ReaEQ", "ReaComp", "ReaComp", "ReaLimit"],
    "gentle":  ["ReaEQ", "ReaComp", "ReaLimit"],
}


# ReaLimit's threshold, in dB, is parameter 0. Its release control reads in
# dB/sec (REAPER's own formatter), so a release in milliseconds has no honest
# mapping onto it.
LIMITER_THRESHOLD = 0


def _added(fx) -> dict:
    return {"success": True, "fx_index": fx.index, "name": fx.name, "n_params": fx.n_params}


def add_master_fx(*, fx_name: str) -> dict:
    """Add an FX plugin to the master track."""
    fx = add_plugin(get_project().master_track, fx_name)
    if fx is None:
        return {"success": False, "error": f"Plugin not found: '{fx_name}'"}
    return _added(fx)


def list_master_fx() -> dict:
    """List all FX plugins on the master track."""
    master = get_project().master_track
    fx_list = [
        {"index": i, "name": fx.name, "enabled": fx.is_enabled, "n_params": fx.n_params}
        for i, fx in enumerate(master.fxs)
    ]
    return {"success": True, "fx": fx_list}


def set_master_fx_parameter(*, fx_index: int, param_index: int, value: float) -> dict:
    """Set a normalized parameter (0.0–1.0) on a master track FX plugin."""
    param = set_param_normalized(get_project().master_track, fx_index, param_index, value=value)
    return {
        "success": True,
        "fx_index": fx_index,
        "param_index": param_index,
        "param_name": param.name,
        "value": param.normalized,
    }


def _master_volume_db(master) -> float:
    return round(linear_to_db(master.get_info_value("D_VOL")), 2)


def set_master_volume(*, volume_db: float) -> dict:
    """Set the master track output volume in dB."""
    master = get_project().master_track
    master.set_info_value("D_VOL", db_to_linear(volume_db))
    return {"success": True, "volume_db": _master_volume_db(master)}


def apply_mastering_chain(*, preset: str = "default") -> dict:
    """
    Add a standard mastering FX chain to the master track.
    Presets: default (EQ > Comp > Limiter), loud (EQ > Comp x2 > Limiter),
    gentle (EQ > light Comp > Limiter).
    After applying, use set_master_fx_parameter to dial in specific settings.
    Use list_master_fx + get_fx_parameters to discover parameter indices.
    """
    if preset not in MASTERING_PRESETS:
        return {
            "success": False,
            "error": f"Unknown preset '{preset}'. Available: {list(MASTERING_PRESETS.keys())}",
        }
    master = get_project().master_track
    added, missing = [], []
    for fx_name in MASTERING_PRESETS[preset]:
        fx = add_plugin(master, fx_name)
        if fx is None:
            missing.append(fx_name)
        else:
            added.append({"fx_index": fx.index, "name": fx.name})
    return {"success": True, "preset": preset, "fx_chain": added, "missing": missing}


def _normalized_for_display(track, fx_index: int, param_index: int, *, target: float) -> float:
    """The normalized value whose displayed value is target, by bisection over
    REAPER's own formatter (no side effects), for a parameter that rises with it."""
    def shown(value: float) -> float:
        text = RPR.TrackFX_FormatParamValueNormalized(track.id, fx_index, param_index, value, "", 64)[5]
        return float(text.split()[0])

    low, high = 0.0, 1.0
    for _ in range(40):
        middle = (low + high) / 2
        low, high = (middle, high) if shown(middle) < target else (low, middle)
    # high is the smallest value displayed at or above target; the midpoint can
    # land one display step below it.
    return high


def apply_limiter(*, threshold_db: float = -0.5, release_ms: float = 50.0) -> dict:
    """
    Add ReaLimit to the master track.
    After adding, use set_master_fx_parameter with the parameter indices from
    get_fx_parameters to set the threshold and release values.
    """
    master = get_project().master_track
    fx = add_plugin(master, "ReaLimit")
    if fx is None:
        return {"success": False, "error": "ReaLimit not found — check REAPER installation"}
    value = _normalized_for_display(master, fx.index, LIMITER_THRESHOLD, target=threshold_db)
    RPR.TrackFX_SetParamNormalized(master.id, fx.index, LIMITER_THRESHOLD, value)
    shown = RPR.TrackFX_GetFormattedParamValue(master.id, fx.index, LIMITER_THRESHOLD, "", 64)[4]
    return {
        **_added(fx),
        "threshold": shown,
        "release_ms_applied": False,
        "hint": (
            f"ReaLimit added at index {fx.index} with its threshold at {shown}. Its release "
            f"control is in dB/sec, so release_ms={release_ms} was not applied; set it with "
            "get_fx_parameters and set_master_fx_parameter."
        ),
    }


def analyze_loudness() -> dict:
    """
    Render the project to a temp file and measure integrated loudness (LUFS)
    and true peak (dBTP) using the ITU-R BS.1770 standard.
    """
    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        data, rate = sf.read(tmp)
        meter = pyln.Meter(rate)
        integrated = meter.integrated_loudness(data)
        if integrated == float("-inf"):
            return {"success": False, "error": "Project appears to be silent"}
        peak_linear = float(np.max(np.abs(data)))
        peak_db = float(20 * np.log10(peak_linear)) if peak_linear > 0 else -120.0
        return {
            "success": True,
            "integrated_lufs": round(integrated, 1),
            "true_peak_dbtp": round(peak_db, 1),
            "sample_rate": rate,
        }
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def normalize_project(*, target_lufs: float = -14.0) -> dict:
    """
    Measure the project's integrated loudness, then adjust the master volume
    so the output hits the target LUFS level.
    Common targets: -14 LUFS (streaming), -16 LUFS (podcasts), -23 LUFS (broadcast).
    """
    import pyloudnorm as pyln
    import soundfile as sf

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        data, rate = sf.read(tmp)
        meter = pyln.Meter(rate)
        current_lufs = meter.integrated_loudness(data)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    if current_lufs == float("-inf"):
        return {"success": False, "error": "Project appears to be silent"}

    gain_db = target_lufs - current_lufs
    master = get_project().master_track
    new_vol_db = linear_to_db(master.get_info_value("D_VOL")) + gain_db
    master.set_info_value("D_VOL", db_to_linear(new_vol_db))

    return {
        "success": True,
        "original_lufs": round(current_lufs, 1),
        "target_lufs": target_lufs,
        "gain_applied_db": round(gain_db, 1),
        "new_master_volume_db": round(new_vol_db, 1),
    }


TOOLS = (
    add_master_fx,
    list_master_fx,
    set_master_fx_parameter,
    set_master_volume,
    apply_mastering_chain,
    apply_limiter,
    analyze_loudness,
    normalize_project,
)
