import os
import logging
from pathlib import Path

import reapy
from reapy import reascript_api as RPR

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.render_tools")

# REAPER RENDER_FORMAT codes
FORMAT_CODES = {
    "wav":  0,
    "mp3":  3,
    "ogg":  4,
    "flac": 5,
}

# REAPER RENDER_FORMAT2 codes for WAV bit depth
BIT_DEPTH_CODES = {
    16: 0,
    24: 2,
    32: 4,
}


def _set_render_settings(
    output_path: str,
    format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    bounds: int,
) -> None:
    """Configure REAPER's render settings. bounds: 0=entire project, 1=time selection."""
    fmt_code = FORMAT_CODES.get(format.lower(), 0)
    bdepth_code = BIT_DEPTH_CODES.get(bit_depth, 2)
    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", output_path, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT", fmt_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT2", bdepth_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_SRATE", float(sample_rate), True)
    RPR.GetSetProjectInfo(0, "RENDER_CHANNELS", float(channels), True)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(bounds), True)


def render_to_temp_file(sample_rate: int = 48000) -> str:
    """
    Render the current project to a temporary WAV file and return its path.
    Used by analysis and mastering tools. Caller is responsible for deleting the file.
    """
    import tempfile
    tmp = tempfile.mktemp(suffix=".wav")
    _set_render_settings(tmp, "wav", sample_rate, 24, 2, bounds=0)
    RPR.Main_OnCommand(41824, 0)
    return tmp


def register_tools(mcp):

    @mcp.tool()
    def render_project(
        output_path: str,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """
        Render the entire project to a file.
        format: wav, flac, mp3 (requires LAME), ogg.
        sample_rate: e.g. 44100, 48000, 96000.
        bit_depth: 16, 24, or 32 (WAV only; ignored for mp3/ogg/flac).
        channels: 1 (mono) or 2 (stereo).
        """
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            _set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=0)
            RPR.Main_OnCommand(41824, 0)  # File: Render project to disk (no dialog)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render command completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "format": format,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "channels": channels,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            logger.error(f"render_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_time_selection(
        output_path: str,
        start: float,
        end: float,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """Render a specific time range of the project to a file."""
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            project = get_project()
            project.time_selection = (start, end)
            _set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=1)
            RPR.Main_OnCommand(41824, 0)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "start": start,
                "end": end,
                "format": format,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_stems(
        output_directory: str,
        track_indices: list | None = None,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
    ) -> dict:
        """
        Render each track as a separate stem file by soloing each track individually.
        track_indices: list of track indices, or null to render all tracks.
        Files are named after the track names in the output directory.
        """
        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)
            project = get_project()
            indices = track_indices if track_indices is not None else list(range(project.n_tracks))
            rendered = []

            for idx in indices:
                track = project.tracks[idx]
                track_name = track.name or f"Track_{idx}"
                # Solo this track exclusively
                for j in range(project.n_tracks):
                    project.tracks[j].solo = (j == idx)
                # Sanitize filename
                safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in track_name)
                stem_path = os.path.join(output_directory, f"{safe_name}.{format}")
                _set_render_settings(stem_path, format, sample_rate, bit_depth, 2, bounds=0)
                RPR.Main_OnCommand(41824, 0)
                rendered.append({
                    "track_index": idx,
                    "track_name": track_name,
                    "output_path": stem_path,
                    "exists": os.path.exists(stem_path),
                })

            # Unsolo all tracks
            for j in range(project.n_tracks):
                project.tracks[j].solo = False

            return {
                "success": True,
                "output_directory": output_directory,
                "stems": rendered,
            }
        except Exception as e:
            # Always unsolo on error
            try:
                proj = get_project()
                for j in range(proj.n_tracks):
                    proj.tracks[j].solo = False
            except Exception:
                pass
            logger.error(f"render_stems failed: {e}")
            return {"success": False, "error": str(e)}
