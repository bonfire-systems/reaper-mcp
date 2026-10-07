"""Track FX tools, and the FX helpers the master-track tools share.

reapy facts these rely on (tests/contract, REAPER 7.82): Track.add_fx returns
the FX object, not an index, and raises ValueError for an unknown plugin;
FXParam.normalized's setter is broken in reapy 0.10, so parameters are set
through TrackFX_SetParamNormalized.
"""

from reaper_mcp.reaper import RPR, get_project


def add_plugin(track, fx_name: str):
    """Add fx_name to track; the new FX, or None when REAPER has no such plugin."""
    try:
        return track.add_fx(fx_name)
    except ValueError:
        return None


def set_param_normalized(track, fx_index: int, param_index: int, *, value: float):
    """Set a parameter's normalized value; returns the parameter as REAPER now has it."""
    track.fxs[fx_index].params[param_index]  # raises IndexError for a bad index first
    RPR.TrackFX_SetParamNormalized(track.id, fx_index, param_index, value)
    return track.fxs[fx_index].params[param_index]


def add_fx(*, track_index: int, fx_name: str) -> dict:
    """
    Add an FX plugin to a track. Works for both instruments (VSTi) and effects (VST/AU).
    Use the exact plugin name as shown in REAPER's FX browser.
    Built-in Cockos plugins: ReaEQ, ReaComp, ReaDelay, ReaVerb, ReaLimit, ReaSynth,
    ReaSamplOmatic5000, ReaTune, ReaGate, ReaFIR, ReaXcomp.
    """
    track = get_project().tracks[track_index]
    fx = add_plugin(track, fx_name)
    if fx is None:
        return {"success": False, "error": f"Plugin not found: '{fx_name}'"}
    return {
        "success": True,
        "fx_index": fx.index,
        "name": fx.name,
        "n_params": fx.n_params,
        "track_index": track_index,
    }


def remove_fx(*, track_index: int, fx_index: int) -> dict:
    """Remove an FX plugin from a track by its index."""
    track = get_project().tracks[track_index]
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
    track = get_project().tracks[track_index]
    param = set_param_normalized(track, fx_index, param_index, value=value)
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "param_index": param_index,
        "param_name": param.name,
        "value": param.normalized,
    }


def get_fx_parameters(*, track_index: int, fx_index: int) -> dict:
    """Get all parameters for an FX plugin, including names, indices, and current values."""
    fx = get_project().tracks[track_index].fxs[fx_index]
    params = [
        {
            "index": i,
            "name": param.name,
            "normalized_value": param.normalized,
            "formatted_value": param.formatted,
        }
        for i, param in enumerate(fx.params)
    ]
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "parameters": params,
    }


def list_track_fx(*, track_index: int) -> dict:
    """List all FX plugins on a track."""
    track = get_project().tracks[track_index]
    fx_list = [
        {"index": i, "name": fx.name, "enabled": fx.is_enabled, "n_params": fx.n_params}
        for i, fx in enumerate(track.fxs)
    ]
    return {"success": True, "track_index": track_index, "fx": fx_list}


def bypass_fx(*, track_index: int, fx_index: int, bypassed: bool) -> dict:
    """Enable or bypass (disable) an FX plugin on a track."""
    track = get_project().tracks[track_index]
    fx = track.fxs[fx_index]
    fx.is_enabled = not bypassed
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "bypassed": not track.fxs[fx_index].is_enabled,
    }


def load_fx_preset(*, track_index: int, fx_index: int, preset_name: str) -> dict:
    """Load a saved preset by name for an FX plugin."""
    track = get_project().tracks[track_index]
    fx = track.fxs[fx_index]
    if not RPR.TrackFX_SetPreset(track.id, fx_index, preset_name):
        return {"success": False, "error": f"{fx.name} has no preset named '{preset_name}'"}
    return {
        "success": True,
        "track_index": track_index,
        "fx_index": fx_index,
        "fx_name": fx.name,
        "preset": track.fxs[fx_index].preset,
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
