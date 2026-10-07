from reaper_mcp.reaper import RPR, get_project


def add_fx(*, track_index: int, fx_name: str) -> dict:
    """
    Add an FX plugin to a track. Works for both instruments (VSTi) and effects (VST/AU).
    Use the exact plugin name as shown in REAPER's FX browser.
    Built-in Cockos plugins: ReaEQ, ReaComp, ReaDelay, ReaVerb, ReaLimit, ReaSynth,
    ReaSamplOmatic5000, ReaTune, ReaGate, ReaFIR, ReaXcomp.
    """
    project = get_project()
    track = project.tracks[track_index]
    fx_index = track.add_fx(fx_name)
    if fx_index < 0:
        return {"success": False, "error": f"Plugin not found: '{fx_name}'"}
    fx = track.fxs[fx_index]
    return {
        "success": True,
        "fx_index": fx_index,
        "name": fx.name,
        "n_params": fx.n_params,
        "track_index": track_index,
    }

def remove_fx(*, track_index: int, fx_index: int) -> dict:
    """Remove an FX plugin from a track by its index."""
    project = get_project()
    track = project.tracks[track_index]
    fx_name = track.fxs[fx_index].name
    RPR.TrackFX_Delete(track.id, fx_index)
    return {"success": True, "track_index": track_index, "removed": fx_name}

def set_fx_parameter(
    *,
    track_index: int, fx_index: int, param_index: int, value: float
) -> dict:
    """
    Set a normalized parameter value (0.0–1.0) on an FX plugin.
    Use get_fx_parameters to discover available parameters and their indices.
    """
    project = get_project()
    track = project.tracks[track_index]
    fx = track.fxs[fx_index]
    fx.params[param_index].normalized_value = value
    param_name = fx.params[param_index].name
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "param_index": param_index,
        "param_name": param_name,
        "value": value,
    }

def get_fx_parameters(*, track_index: int, fx_index: int) -> dict:
    """Get all parameters for an FX plugin, including names, indices, and current values."""
    project = get_project()
    track = project.tracks[track_index]
    fx = track.fxs[fx_index]
    params = []
    for i in range(fx.n_params):
        param = fx.params[i]
        params.append({
            "index": i,
            "name": param.name,
            "normalized_value": param.normalized_value,
            "formatted_value": param.formatted_value,
        })
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "parameters": params,
    }

def list_track_fx(*, track_index: int) -> dict:
    """List all FX plugins on a track."""
    project = get_project()
    track = project.tracks[track_index]
    fx_list = []
    for i in range(track.n_fxs):
        fx = track.fxs[i]
        fx_list.append({
            "index": i,
            "name": fx.name,
            "enabled": fx.is_enabled,
            "n_params": fx.n_params,
        })
    return {"success": True, "track_index": track_index, "fx": fx_list}

def bypass_fx(*, track_index: int, fx_index: int, bypassed: bool) -> dict:
    """Enable or bypass (disable) an FX plugin on a track."""
    project = get_project()
    track = project.tracks[track_index]
    fx = track.fxs[fx_index]
    fx.is_enabled = not bypassed
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "bypassed": bypassed,
    }

def load_fx_preset(*, track_index: int, fx_index: int, preset_name: str) -> dict:
    """Load a saved preset by name for an FX plugin."""
    project = get_project()
    track = project.tracks[track_index]
    fx = track.fxs[fx_index]
    fx.preset_name = preset_name
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "preset": fx.preset_name,
    }


TOOLS = (
    add_fx,
    remove_fx,
    set_fx_parameter,
    get_fx_parameters,
    list_track_fx,
    bypass_fx,
    load_fx_preset,
)
