"""render_tools against the fake REAPER, whose render follows REAPER 7.82:
RENDER_FILE is the directory, RENDER_PATTERN the name, RENDER_FORMAT a base64
sink string, and a would-be dialog raises ModalDialog (see fake_reaper/render.py).
tests/live/test_render_tools_live.py checks the same behaviour against REAPER."""

import base64
from pathlib import Path

import pytest
import soundfile as sf
from reapy import reascript_api

from reaper_mcp.render_tools import (
    render_project,
    render_stems,
    render_time_selection,
    render_to_temp_file,
)
from tests.helpers import RENDER, WAV_24


def fmt(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_render_project_settings(reaper, call, tmp_path):
    out = tmp_path / "mix.wav"
    result = call("render_project", output_path=str(out), sample_rate=44100, bit_depth=16, channels=1)
    assert result == {
        "success": True, "output_path": str(out), "file_size_bytes": out.stat().st_size,
        "format": "wav", "sample_rate": 44100, "bit_depth": 16, "channels": 1,
    }
    assert reaper.project_info == {
        "RENDER_FILE": str(tmp_path), "RENDER_PATTERN": "mix", "RENDER_FORMAT": fmt(b"evaw\x10\x00\x01"),
        "RENDER_SRATE": 44100.0, "RENDER_CHANNELS": 1.0, "RENDER_BOUNDSFLAG": 1.0, "RENDER_ADDTOPROJ": 0.0,
    }
    info = sf.info(str(out))
    assert (info.samplerate, info.channels, info.subtype) == (44100, 1, "PCM_16")


@pytest.mark.parametrize(("bit_depth", "subtype"), [(24, "PCM_24"), (32, "FLOAT")])
def test_render_project_wav_bit_depths(reaper, call, tmp_path, bit_depth, subtype):
    out = tmp_path / "mix.wav"
    call("render_project", output_path=str(out), bit_depth=bit_depth)
    assert sf.info(str(out)).subtype == subtype


@pytest.mark.parametrize(("format", "tag"), [("flac", b"calf"), ("ogg", b"vggo"), ("mp3", b"l3pm")])
def test_render_project_other_formats_use_reaper_defaults(reaper, call, tmp_path, format, tag):
    result = call("render_project", output_path=str(tmp_path / "mix"), format=format, bit_depth=99)
    assert result["output_path"] == str(tmp_path / f"mix.{format}")
    assert reaper.project_info["RENDER_FORMAT"] == fmt(tag)


def test_render_project_refusals_send_nothing_to_reaper(reaper, call, tmp_path):
    cases = [
        ({"format": "aiff"}, "unsupported format 'aiff'"),
        ({"bit_depth": 20}, "unsupported WAV bit depth 20"),
        ({"output_path": str(tmp_path / "mix.mp3")}, "does not match format 'wav'"),
    ]
    for arguments, message in cases:
        result = call("render_project", **{"output_path": str(tmp_path / "mix.wav"), **arguments})
        assert result["success"] is False and message in result["error"]
    assert reaper.commands == []


def test_render_empty_project_is_refused_before_reaper_sees_it(reaper, call, tmp_path):
    reaper.length = 0.0
    result = call("render_project", output_path=str(tmp_path / "mix.wav"))
    assert result == {"success": False, "error": "the project is empty; there is nothing to render"}
    assert reaper.commands == []


def test_render_project_replaces_an_existing_file(reaper, call, tmp_path):
    out = tmp_path / "deep" / "mix.wav"
    assert call("render_project", output_path=str(out))["success"] is True
    assert call("render_project", output_path=str(out))["success"] is True
    assert reaper.commands == [RENDER, RENDER]


def test_render_project_reports_a_file_reaper_did_not_write(reaper, call, tmp_path, monkeypatch):
    monkeypatch.setattr(reascript_api, "Main_OnCommand", lambda *_: None)
    out = tmp_path / "mix.wav"
    assert call("render_project", output_path=str(out)) == {
        "success": False, "error": f"REAPER did not write {out}",
    }


def test_render_to_temp_file(reaper):
    path = Path(render_to_temp_file(sample_rate=22050))
    assert path.name.startswith("reaper-mcp-") and path.suffix == ".wav"
    assert sf.info(str(path)).samplerate == 22050
    path.unlink()
    reaper.length = 0.0
    with pytest.raises(RuntimeError, match="nothing to render"):
        render_to_temp_file()


def test_render_time_selection(reaper, call, tmp_path):
    reaper.time_selection = (0.1, 0.2)
    out = tmp_path / "part.wav"
    result = call("render_time_selection", output_path=str(out), start=0.5, end=1.5)
    assert result == {
        "success": True, "output_path": str(out), "file_size_bytes": out.stat().st_size,
        "start": 0.5, "end": 1.5, "format": "wav",
    }
    assert reaper.project_info["RENDER_BOUNDSFLAG"] == 2.0
    assert sf.info(str(out)).duration == pytest.approx(1.0)
    assert reaper.time_selection == (0.1, 0.2)


@pytest.mark.parametrize(("start", "end"), [(2.0, 1.0), (1.0, 1.0), (-1.0, 1.0)])
def test_render_time_selection_invalid_range(reaper, call, tmp_path, start, end):
    result = call("render_time_selection", output_path=str(tmp_path / "p.wav"), start=start, end=end)
    assert result["success"] is False and "need 0 <= start < end" in result["error"]
    assert reaper.commands == []


def test_render_stems_solos_each_track_and_restores_solo(reaper, call, tmp_path):
    reaper.add_track("Kick")
    reaper.add_track("Snare/Top").info["I_SOLO"] = 2.0
    reaper.add_track("")
    result = call("render_stems", output_directory=str(tmp_path), track_indices=None)
    assert [s["output_path"] for s in result["stems"]] == [
        str(tmp_path / "Kick.wav"), str(tmp_path / "Snare_Top.wav"), str(tmp_path / "Track_2.wav"),
    ]
    assert all(s["exists"] for s in result["stems"])
    assert reaper.render_solos == [["Kick"], ["Snare/Top"], [""]]
    assert [t.info["I_SOLO"] for t in reaper.tracks] == [0.0, 2.0, 0.0]


def test_render_stems_subset_duplicates_and_format(reaper, call, tmp_path):
    for name in ("Kick", "Bass", "Kick"):
        reaper.add_track(name)
    result = call("render_stems", output_directory=str(tmp_path), track_indices=[2, 0], format="flac")
    assert [s["output_path"] for s in result["stems"]] == [
        str(tmp_path / "Kick.flac"), str(tmp_path / "Kick_2.flac"),
    ]
    assert [s["track_index"] for s in result["stems"]] == [2, 0]


def test_render_stems_bad_index_renders_nothing(reaper, call, tmp_path):
    reaper.add_track("Kick")
    result = call("render_stems", output_directory=str(tmp_path), track_indices=[0, 5])
    assert result == {"success": False, "error": "list index out of range"}
    assert reaper.commands == []


def test_render_stems_empty_project_is_refused(reaper, call, tmp_path):
    reaper.length = 0.0
    result = call("render_stems", output_directory=str(tmp_path))
    assert result["success"] is False and "nothing to render" in result["error"]


def test_render_project_creates_missing_parent_folders(reaper, call, tmp_path):
    out = tmp_path / "new" / "deeper" / "mix.wav"
    assert call("render_project", output_path=str(out))["success"] is True
    assert out.is_file()


def test_render_project_of_a_short_project(reaper, call, tmp_path):
    reaper.length = 0.5
    out = tmp_path / "mix.wav"
    assert call("render_project", output_path=str(out))["success"] is True
    assert sf.info(str(out)).duration == pytest.approx(0.5)


DEFAULT_SETTINGS = {"RENDER_FORMAT": WAV_24, "RENDER_SRATE": 48000.0, "RENDER_CHANNELS": 2.0}


def _settings(reaper) -> dict:
    return {key: reaper.project_info[key] for key in DEFAULT_SETTINGS}


def test_render_project_python_defaults(reaper, tmp_path):
    out = tmp_path / "mix"
    result = render_project(output_path=str(out))
    assert result["output_path"] == str(tmp_path / "mix.wav")
    assert (result["format"], result["sample_rate"], result["bit_depth"], result["channels"]) == (
        "wav", 48000, 24, 2,
    )
    assert _settings(reaper) == DEFAULT_SETTINGS


def test_render_time_selection_python_defaults(reaper, tmp_path):
    result = render_time_selection(output_path=str(tmp_path / "part"), start=0.0, end=1.0)
    assert (result["output_path"], result["format"]) == (str(tmp_path / "part.wav"), "wav")
    assert _settings(reaper) == DEFAULT_SETTINGS


def test_render_stems_python_defaults(reaper, tmp_path):
    reaper.add_track("Kick")
    result = render_stems(output_directory=str(tmp_path))
    assert result["stems"][0]["output_path"] == str(tmp_path / "Kick.wav")
    assert _settings(reaper) == DEFAULT_SETTINGS


def test_render_time_selection_from_the_project_start(reaper, call, tmp_path):
    out = tmp_path / "intro.wav"
    result = call("render_time_selection", output_path=str(out), start=0.0, end=0.5)
    assert result["success"] is True and (result["start"], result["end"]) == (0.0, 0.5)
    assert sf.info(str(out)).duration == pytest.approx(0.5)


def test_render_stems_reply_and_settings(reaper, call, tmp_path):
    reaper.add_track("Kick")
    reaper.add_track("")
    result = call("render_stems", output_directory=str(tmp_path), sample_rate=44100, bit_depth=16)
    assert result == {
        "success": True,
        "output_directory": str(tmp_path),
        "stems": [
            {"track_index": 0, "track_name": "Kick", "output_path": str(tmp_path / "Kick.wav"),
             "exists": True},
            {"track_index": 1, "track_name": "Track_1", "output_path": str(tmp_path / "Track_1.wav"),
             "exists": True},
        ],
    }
    # Stems are always stereo, over the whole project.
    assert reaper.project_info["RENDER_CHANNELS"] == 2.0
    assert reaper.project_info["RENDER_BOUNDSFLAG"] == 1.0
    assert reaper.project_info["RENDER_FORMAT"] == fmt(b"evaw\x10\x00\x01")


def test_render_stems_unsupported_format_renders_nothing(reaper, call, tmp_path):
    reaper.add_track("Kick").info["I_SOLO"] = 1.0
    reaper.add_track("Bass")
    result = call("render_stems", output_directory=str(tmp_path), format="aiff")
    assert result == {
        "success": False,
        "error": "unsupported format 'aiff'; use one of ['flac', 'mp3', 'ogg', 'wav']",
    }
    assert reaper.commands == []
    assert [t.info["I_SOLO"] for t in reaper.tracks] == [1.0, 0.0]
