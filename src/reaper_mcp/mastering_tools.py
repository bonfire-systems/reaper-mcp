import os

from reaper_mcp.reaper import get_project

MASTERING_PRESETS = {
    "default": ["ReaEQ", "ReaComp", "ReaLimit"],
    "loud":    ["ReaEQ", "ReaComp", "ReaComp", "ReaLimit"],
    "gentle":  ["ReaEQ", "ReaComp", "ReaLimit"],
}


def add_master_fx(*, fx_name: str) -> dict:
    """Add an FX plugin to the master track."""
    project = get_project()
    master = project.master_track
    fx_index = master.add_fx(fx_name)
    if fx_index < 0:
        return {"success": False, "error": f"Plugin not found: '{fx_name}'"}
    fx = master.fxs[fx_index]
    return {"success": True, "fx_index": fx_index, "name": fx.name, "n_params": fx.n_params}

def list_master_fx() -> dict:
    """List all FX plugins on the master track."""
    project = get_project()
    master = project.master_track
    fx_list = []
    for i in range(master.n_fxs):
        fx = master.fxs[i]
        fx_list.append({"index": i, "name": fx.name, "enabled": fx.is_enabled, "n_params": fx.n_params})
    return {"success": True, "fx": fx_list}

def set_master_fx_parameter(*, fx_index: int, param_index: int, value: float) -> dict:
    """Set a normalized parameter (0.0–1.0) on a master track FX plugin."""
    project = get_project()
    master = project.master_track
    fx = master.fxs[fx_index]
    fx.params[param_index].normalized_value = value
    return {
        "success": True,
        "fx_index": fx_index,
        "param_index": param_index,
        "param_name": fx.params[param_index].name,
        "value": value,
    }

def set_master_volume(*, volume_db: float) -> dict:
    """Set the master track output volume in dB."""
    project = get_project()
    master = project.master_track
    master.volume = volume_db
    return {"success": True, "volume_db": master.volume}

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
    project = get_project()
    master = project.master_track
    added = []
    for fx_name in MASTERING_PRESETS[preset]:
        fx_index = master.add_fx(fx_name)
        if fx_index >= 0:
            fx = master.fxs[fx_index]
            added.append({"fx_index": fx_index, "name": fx.name})
    return {"success": True, "preset": preset, "fx_chain": added}

def apply_limiter(*, threshold_db: float = -0.5, release_ms: float = 50.0) -> dict:
    """
    Add ReaLimit to the master track.
    After adding, use set_master_fx_parameter with the parameter indices from
    get_fx_parameters to set the threshold and release values.
    """
    project = get_project()
    master = project.master_track
    fx_index = master.add_fx("ReaLimit")
    if fx_index < 0:
        return {"success": False, "error": "ReaLimit not found — check REAPER installation"}
    fx = master.fxs[fx_index]
    return {
        "success": True,
        "fx_index": fx_index,
        "name": fx.name,
        "hint": (
            f"ReaLimit added at index {fx_index}. "
            "Use get_fx_parameters to find threshold/release param indices, "
            "then use set_master_fx_parameter to set them."
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
    project = get_project()
    master = project.master_track
    new_vol_db = master.volume + gain_db
    master.volume = new_vol_db

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
