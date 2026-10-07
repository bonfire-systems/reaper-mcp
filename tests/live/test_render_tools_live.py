"""Rendering against a running REAPER: real files, read back and checked."""

from typing import Any

import numpy as np
import pytest
import soundfile as sf

pytestmark = pytest.mark.live


def dominant_hz(path) -> float:
    data, rate = sf.read(str(path))
    mono = data.mean(axis=1) if data.ndim > 1 else data
    spectrum = np.abs(np.fft.rfft(mono))
    return float(np.fft.rfftfreq(len(mono), 1 / rate)[spectrum.argmax()])


@pytest.mark.parametrize(("bit_depth", "subtype"), [(16, "PCM_16"), (24, "PCM_24"), (32, "FLOAT")])
def test_render_project_wav(add_tone, call, tmp_path, bit_depth, subtype):
    add_tone("a", 440)
    out = tmp_path / "mix.wav"
    result = call("render_project", output_path=str(out), sample_rate=44100, bit_depth=bit_depth)
    assert result["success"] is True, result
    info = sf.info(str(out))
    assert (info.samplerate, info.channels, info.subtype) == (44100, 2, subtype)
    assert info.duration == pytest.approx(2.0, abs=0.01)


@pytest.mark.parametrize(("fmt", "container"), [("flac", "FLAC"), ("ogg", "OGG"), ("mp3", "MP3")])
def test_render_project_other_formats(add_tone, call, tmp_path, fmt, container):
    add_tone("a", 440)
    result = call("render_project", output_path=str(tmp_path / "mix"), format=fmt)
    assert result["success"] is True, result
    assert result["output_path"] == str(tmp_path / f"mix.{fmt}")
    assert sf.info(result["output_path"]).format == container


def test_render_project_twice_to_the_same_path(add_tone, call, tmp_path):
    add_tone("a", 440)
    out = str(tmp_path / "mix.wav")
    assert call("render_project", output_path=out)["success"] is True
    assert call("render_project", output_path=out)["success"] is True


def test_render_empty_project_is_refused(live_project, call, tmp_path):
    result = call("render_project", output_path=str(tmp_path / "mix.wav"))
    assert result == {"success": False, "error": "the project is empty; there is nothing to render"}
    assert call("analyze_loudness")["success"] is False


def test_render_time_selection(add_tone, call, tmp_path, live_project):
    add_tone("a", 440)
    live_project.time_selection = (0.1, 0.2)
    out = tmp_path / "part.wav"
    result = call("render_time_selection", output_path=str(out), start=0.5, end=1.5)
    assert result["success"] is True, result
    assert sf.info(str(out)).duration == pytest.approx(1.0, abs=0.01)
    selection: Any = live_project.time_selection  # a TimeSelection; reapy annotates a tuple
    assert (selection.start, selection.end) == pytest.approx((0.1, 0.2))


def test_render_stems_solos_each_track(add_tone, call, tmp_path, live_project):
    add_tone("low", 220)
    add_tone("high", 880)
    live_project.tracks[1].set_info_value("I_SOLO", 2)
    result = call("render_stems", output_directory=str(tmp_path), track_indices=None)
    assert result["success"] is True, result
    low, high = (stem["output_path"] for stem in result["stems"])
    assert dominant_hz(low) == pytest.approx(220, abs=2)
    assert dominant_hz(high) == pytest.approx(880, abs=2)
    assert [t.get_info_value("I_SOLO") for t in live_project.tracks] == [0, 2]


def test_render_stems_duplicate_names_get_unique_files(add_tone, call, tmp_path):
    add_tone("Kick", 220)
    add_tone("Kick", 330)
    result = call("render_stems", output_directory=str(tmp_path))
    paths = [stem["output_path"] for stem in result["stems"]]
    assert paths == [str(tmp_path / "Kick.wav"), str(tmp_path / "Kick_2.wav")]
    assert dominant_hz(paths[1]) == pytest.approx(330, abs=2)
