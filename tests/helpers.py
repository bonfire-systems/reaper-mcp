"""Assertions shared by the fake-REAPER tests."""

import base64

RENDER = 41824
WAV_24 = base64.b64encode(b"evaw\x18\x00\x01").decode()


def assert_rendered_and_deleted(reaper, rate=48000):
    """One render of the whole project to a 24-bit stereo .wav temp file, removed afterwards."""
    assert reaper.commands == [RENDER]
    [path] = reaper.renders
    assert path.suffix == ".wav"
    assert not path.exists()
    assert reaper.project_info == {
        "RENDER_FILE": str(path.parent),
        "RENDER_PATTERN": path.stem,
        "RENDER_FORMAT": WAV_24,
        "RENDER_SRATE": float(rate),
        "RENDER_CHANNELS": 2.0,
        "RENDER_BOUNDSFLAG": 1.0,
        "RENDER_ADDTOPROJ": 0.0,
    }
