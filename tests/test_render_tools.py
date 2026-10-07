"""Characterization tests for render_tools, run end to end against the fake REAPER."""

import os
from pathlib import Path

import pytest
import soundfile as sf

from reaper_mcp.render_tools import _set_render_settings, render_to_temp_file

RENDER = 41824


def _settings(reaper) -> dict:
    keys = ["RENDER_FILE", "RENDER_FORMAT", "RENDER_FORMAT2", "RENDER_SRATE",
            "RENDER_CHANNELS", "RENDER_BOUNDSFLAG"]
    return {k: reaper.project_info[k] for k in keys}


# Module-level helpers


def test_set_render_settings_writes_project_info(reaper):
    _set_render_settings("/x/mix.flac", "FLAC", 44100, 16, 1, bounds=1)
    assert _settings(reaper) == {
        "RENDER_FILE": "/x/mix.flac",
        "RENDER_FORMAT": 5,
        "RENDER_FORMAT2": 0,
        "RENDER_SRATE": 44100.0,
        "RENDER_CHANNELS": 1.0,
        "RENDER_BOUNDSFLAG": 1.0,
    }
    assert isinstance(reaper.project_info["RENDER_SRATE"], float)


@pytest.mark.parametrize(
    "case",
    [
        ("wav", 24, (0, 2)),
        ("mp3", 32, (3, 4)),
        ("ogg", 16, (4, 0)),
        ("aiff", 8, (0, 2)),  # unknown format -> WAV, unknown depth -> 24-bit code
    ],
)
def test_set_render_settings_codes(reaper, case):
    fmt, bit_depth, codes = case
    _set_render_settings("/x/out", fmt, 48000, bit_depth, 2, bounds=0)
    assert (reaper.project_info["RENDER_FORMAT"], reaper.project_info["RENDER_FORMAT2"]) == codes
    assert reaper.commands == []


def test_render_to_temp_file(reaper):
    path = render_to_temp_file(sample_rate=22050)
    try:
        assert path.endswith(".wav")
        assert os.path.exists(path)
        assert reaper.commands == [RENDER]
        assert _settings(reaper) == {
            "RENDER_FILE": path,
            "RENDER_FORMAT": 0,
            "RENDER_FORMAT2": 2,
            "RENDER_SRATE": 22050.0,
            "RENDER_CHANNELS": 2.0,
            "RENDER_BOUNDSFLAG": 0.0,
        }
        assert sf.info(path).samplerate == 22050
    finally:
        Path(path).unlink(missing_ok=True)


# render_project


def test_render_project_defaults(reaper, call, tmp_path):
    out = tmp_path / "new" / "dir" / "mix.wav"
    result = call("render_project", output_path=str(out))
    assert result == {
        "success": True,
        "output_path": str(out.resolve()),
        "format": "wav",
        "sample_rate": 48000,
        "bit_depth": 24,
        "channels": 2,
        "file_size_bytes": out.stat().st_size,
    }
    assert reaper.commands == [RENDER]
    assert reaper.renders == [out.resolve()]
    assert _settings(reaper) == {
        "RENDER_FILE": str(out.resolve()),
        "RENDER_FORMAT": 0,
        "RENDER_FORMAT2": 2,
        "RENDER_SRATE": 48000.0,
        "RENDER_CHANNELS": 2.0,
        "RENDER_BOUNDSFLAG": 0.0,
    }


def test_render_project_custom_settings(reaper, call, tmp_path):
    out = tmp_path / "mix.flac"
    result = call("render_project", output_path=str(out), format="flac",
                  sample_rate=44100, bit_depth=16, channels=1)
    assert result["success"] is True
    assert (result["format"], result["sample_rate"], result["bit_depth"], result["channels"]) == (
        "flac", 44100, 16, 1)
    assert reaper.project_info["RENDER_FORMAT"] == 5
    assert reaper.project_info["RENDER_FORMAT2"] == 0
    assert reaper.project_info["RENDER_CHANNELS"] == 1.0
    assert sf.info(str(out)).samplerate == 44100


def test_render_project_resolves_relative_path(reaper, call, monkeypatch):
    tmp_path = reaper.tmp
    monkeypatch.chdir(tmp_path)
    result = call("render_project", output_path="renders/mix.wav")
    assert result["output_path"] == str((tmp_path / "renders" / "mix.wav").resolve())
    assert reaper.project_info["RENDER_FILE"] == result["output_path"]


def test_render_project_unwritable_directory(reaper, call, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    result = call("render_project", output_path=str(blocker / "mix.wav"))
    assert result["success"] is False
    assert result["error"] == f"[Errno 17] File exists: '{blocker.resolve()}'"
    assert reaper.commands == []
    assert reaper.project_info == {}


# render_time_selection


def test_render_time_selection(reaper, call, tmp_path):
    out = tmp_path / "sel" / "part.wav"
    result = call("render_time_selection", output_path=str(out), start=1.0, end=3.5)
    assert result == {
        "success": True,
        "output_path": str(out.resolve()),
        "start": 1.0,
        "end": 3.5,
        "format": "wav",
        "file_size_bytes": out.stat().st_size,
    }
    assert reaper.time_selection == (1.0, 3.5)
    assert reaper.commands == [RENDER]
    assert _settings(reaper) == {
        "RENDER_FILE": str(out.resolve()),
        "RENDER_FORMAT": 0,
        "RENDER_FORMAT2": 2,
        "RENDER_SRATE": 48000.0,
        "RENDER_CHANNELS": 2.0,
        "RENDER_BOUNDSFLAG": 1.0,
    }


def test_render_time_selection_custom_settings(reaper, call, tmp_path):
    out = tmp_path / "part.ogg"
    result = call("render_time_selection", output_path=str(out), start=0.0, end=2.0,
                  format="ogg", sample_rate=96000, bit_depth=32, channels=1)
    assert result["format"] == "ogg"
    assert "sample_rate" not in result
    assert reaper.project_info["RENDER_FORMAT"] == 4
    assert reaper.project_info["RENDER_FORMAT2"] == 4
    assert reaper.project_info["RENDER_SRATE"] == 96000.0
    assert reaper.project_info["RENDER_CHANNELS"] == 1.0


def test_render_time_selection_does_not_validate_range(reaper, call, tmp_path):
    result = call("render_time_selection", output_path=str(tmp_path / "x.wav"), start=5.0, end=1.0)
    assert result["success"] is True
    assert reaper.time_selection == (5.0, 1.0)


def test_render_time_selection_unwritable_directory(reaper, call, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    reaper.time_selection = (9.0, 10.0)
    result = call("render_time_selection", output_path=str(blocker / "x.wav"), start=1.0, end=2.0)
    assert result == {"success": False, "error": f"[Errno 17] File exists: '{blocker.resolve()}'"}
    assert reaper.time_selection == (9.0, 10.0)
    assert reaper.commands == []


# render_stems


def test_render_stems_all_tracks(reaper, call, tmp_path):
    for name in ["Kick", "Snare/Top", ""]:
        reaper.add_track(name)
    out = tmp_path / "stems"
    result = call("render_stems", output_directory=str(out))
    root = out.resolve()
    assert result == {
        "success": True,
        "output_directory": str(root),
        "stems": [
            {"track_index": 0, "track_name": "Kick",
             "output_path": str(root / "Kick.wav"), "exists": True},
            {"track_index": 1, "track_name": "Snare/Top",
             "output_path": str(root / "Snare_Top.wav"), "exists": True},
            {"track_index": 2, "track_name": "Track_2",
             "output_path": str(root / "Track_2.wav"), "exists": True},
        ],
    }
    assert reaper.commands == [RENDER] * 3
    assert reaper.renders == [root / "Kick.wav", root / "Snare_Top.wav", root / "Track_2.wav"]
    assert reaper.project_info["RENDER_FILE"] == str(root / "Track_2.wav")
    assert reaper.project_info["RENDER_BOUNDSFLAG"] == 0.0
    assert reaper.project_info["RENDER_CHANNELS"] == 2.0


def test_render_stems_does_not_solo_bug(reaper, call, tmp_path):
    reaper.add_track("Kick")
    reaper.add_track("Bass")
    reaper.tracks[1].info["I_SOLO"] = 1.0
    result = call("render_stems", output_directory=str(tmp_path))
    assert result["success"] is True
    # BUG: `track.solo = ...` shadows reapy's solo() method, so REAPER's solo state never changes:
    # every stem is a render of the full mix, and a pre-existing solo is not cleared afterwards.
    assert reaper.render_solos == [["Bass"], ["Bass"]]
    assert [t.info["I_SOLO"] for t in reaper.tracks] == [0.0, 1.0]


def test_render_stems_subset_and_format(reaper, call, tmp_path):
    reaper.add_track("Kick")
    reaper.add_track("Bass")
    result = call("render_stems", output_directory=str(tmp_path), track_indices=[1],
                  format="flac", sample_rate=44100, bit_depth=16)
    assert result["stems"] == [{"track_index": 1, "track_name": "Bass",
                                "output_path": str(tmp_path.resolve() / "Bass.flac"),
                                "exists": True}]
    assert reaper.project_info["RENDER_FORMAT"] == 5
    assert reaper.project_info["RENDER_FORMAT2"] == 0
    assert reaper.project_info["RENDER_SRATE"] == 44100.0


def test_render_stems_duplicate_names_overwrite(reaper, call, tmp_path):
    reaper.add_track("Gtr")
    reaper.add_track("Gtr")
    result = call("render_stems", output_directory=str(tmp_path))
    paths = [s["output_path"] for s in result["stems"]]
    assert paths == [str(tmp_path.resolve() / "Gtr.wav")] * 2
    assert len(reaper.renders) == 2


def test_render_stems_empty_project(reaper, call, tmp_path):
    result = call("render_stems", output_directory=str(tmp_path / "none"))
    assert result == {"success": True, "output_directory": str((tmp_path / "none").resolve()),
                      "stems": []}
    assert (tmp_path / "none").is_dir()
    assert reaper.commands == []


def test_render_stems_bad_index_after_partial_render(reaper, call, tmp_path):
    reaper.add_track("Kick")
    result = call("render_stems", output_directory=str(tmp_path), track_indices=[0, 4])
    assert result == {"success": False, "error": "list index out of range"}
    assert reaper.renders == [tmp_path.resolve() / "Kick.wav"]


def test_render_stems_unwritable_directory(reaper, call, tmp_path):
    reaper.add_track("Kick")
    blocker = tmp_path / "file"
    blocker.write_text("x")
    result = call("render_stems", output_directory=str(blocker))
    assert result == {"success": False, "error": f"[Errno 17] File exists: '{blocker.resolve()}'"}
    assert reaper.commands == []


def test_render_stems_explicit_null_rejected_bug(reaper, call, tmp_path):
    reaper.add_track("Kick")
    # BUG: `track_indices: list = None` has no null in its schema, so a client sending
    # the documented `null` ("render all tracks") gets a validation error instead.
    with pytest.raises(AssertionError, match="validation error for render_stemsArguments"):
        call("render_stems", output_directory=str(tmp_path), track_indices=None)
    assert reaper.commands == []
