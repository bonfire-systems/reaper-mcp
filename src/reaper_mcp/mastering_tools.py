import os

from reaper_mcp.fx_tools import add_plugin, set_param_normalized
from reaper_mcp.reaper import RPR, get_project
from reaper_mcp.units import db_to_linear, linear_to_db

MASTERING_PRESETS = {
    "default": ["ReaEQ", "ReaComp", "ReaLimit"],
    "loud":    ["ReaEQ", "ReaComp", "ReaComp", "ReaLimit"],
    "gentle":  ["ReaEQ", "ReaComp", "ReaLimit"],
}


# ReaLimit's parameters, found by name. Its release control reads in dB/sec.
LIMITER_THRESHOLD = "Threshold"
LIMITER_RELEASE = "Release"


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
    fxs = master.fxs
    fx_list = [
        {"index": i, "name": fxs[i].name, "enabled": fxs[i].is_enabled, "n_params": fxs[i].n_params}
        for i in range(master.n_fxs)
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


def _shown(track, fx_index: int, param_index: int, *, value: float) -> float:
    """The number REAPER would display for value, without setting it."""
    text = RPR.TrackFX_FormatParamValueNormalized(track.id, fx_index, param_index, value, "", 64)[5]
    return float(text.split()[0])  # "-3.00 dB", "12.0 dB/sec", "inf"


def _set_to_display(track, fx, param_name: str, *, target: float) -> str:
    """Set fx's parameter so REAPER displays target, by bisection over REAPER's
    own formatter, rising or falling; returns what REAPER then displays.

    The result is the first value that reaches target, so it is exact to the
    display's precision; a target past the range lands on its end.
    """
    param_index = next(i for i in range(fx.n_params) if fx.params[i].name == param_name)
    rising = (_shown(track, fx.index, param_index, value=0.25)
              < _shown(track, fx.index, param_index, value=0.75))
    low, high = 0.0, 1.0
    for _ in range(40):
        middle = (low + high) / 2
        shown = _shown(track, fx.index, param_index, value=middle)
        short = shown < target if rising else shown > target
        low, high = (middle, high) if short else (low, middle)
    RPR.TrackFX_SetParamNormalized(track.id, fx.index, param_index, high)
    return RPR.TrackFX_GetFormattedParamValue(track.id, fx.index, param_index, "", 64)[4]


def apply_limiter(*, threshold_db: float = -0.5, release_db_per_sec: float = 15.0) -> dict:
    """
    Add ReaLimit to the master track and set its threshold and release.
    threshold_db: -60 to +12 dB.
    release_db_per_sec: how fast gain reduction recovers, in dB per second as
    ReaLimit displays it (about 6 and up; higher recovers faster; default 15).
    """
    master = get_project().master_track
    fx = add_plugin(master, "ReaLimit")
    if fx is None:
        return {"success": False, "error": "ReaLimit not found — check REAPER installation"}
    threshold = _set_to_display(master, fx, LIMITER_THRESHOLD, target=threshold_db)
    release = _set_to_display(master, fx, LIMITER_RELEASE, target=release_db_per_sec)
    return {**_added(fx), "threshold": threshold, "release": release}


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
