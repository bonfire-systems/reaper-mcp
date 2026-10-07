"""REAPER's render, as the fake performs it (semantics verified on 7.82).

RENDER_FILE is the output directory and RENDER_PATTERN the file name; the
extension comes from the RENDER_FORMAT sink string. Where REAPER would open a
modal dialog and block the caller (nothing to render, an existing target),
the fake raises ModalDialog, a BaseException, so no error envelope can turn a
would-be hang into an ordinary failed reply.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

if TYPE_CHECKING:
    from tests.fake_reaper.api import FakeReaper

EXTENSIONS = {b"evaw": "wav", b"calf": "flac", b"l3pm": "mp3", b"vggo": "ogg"}
WAV_SUBTYPES = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}
SOUNDFILE_FORMATS = {"wav": ("WAV", None), "flac": ("FLAC", "PCM_16"),
                     "ogg": ("OGG", "VORBIS"), "mp3": ("MP3", "MPEG_LAYER_III")}


class ModalDialog(BaseException):
    """REAPER would show a modal dialog here and block until someone clicks."""


def _format(config: str) -> tuple[str, str | None]:
    raw = base64.b64decode(config) if config else b"evaw"
    extension = EXTENSIONS[raw[:4]]
    if extension != "wav":
        return extension, None
    # A bare "evaw" selects WAV's defaults, which are 32-bit float.
    return extension, WAV_SUBTYPES[raw[4] if len(raw) > 4 else 32]


def _bounds(reaper: FakeReaper) -> tuple[float, float]:
    flag = int(float(reaper.project_info.get("RENDER_BOUNDSFLAG", 1.0)))
    if flag == 1:
        return 0.0, reaper.length
    if flag == 2:
        return reaper.time_selection
    start = float(reaper.project_info.get("RENDER_STARTPOS", 0.0))
    return start, float(reaper.project_info.get("RENDER_ENDPOS", 0.0))


def _signal(reaper: FakeReaper, seconds: float, rate: int) -> np.ndarray:
    """One sine per channel, from reaper.signal's (amplitude, frequency) pairs;
    silence when reaper.silent. Rendered as PCM, so peaks past 1.0 clip."""
    t = np.arange(int(rate * seconds)) / rate
    if reaper.silent:
        return np.zeros((len(t), 2))
    channels = [amplitude * np.sin(2 * np.pi * hz * t) for amplitude, hz in reaper.signal]
    return np.clip(np.stack(channels, axis=1), -1.0, 1.0)


def render(reaper: FakeReaper) -> Path:
    extension, subtype = _format(str(reaper.project_info.get("RENDER_FORMAT", "")))
    directory = Path(str(reaper.project_info["RENDER_FILE"]))
    pattern = str(reaper.project_info.get("RENDER_PATTERN", "")) or "untitled"
    path = directory / f"{pattern}.{extension}"
    start, end = _bounds(reaper)
    if end <= start:
        raise ModalDialog("Render Error: Nothing to render!")
    if path.exists():
        raise ModalDialog(f"Render Warning: {path.name} exists (overwrite / increment / cancel)")
    rate = int(float(reaper.project_info.get("RENDER_SRATE", 48000)))
    data = _signal(reaper, end - start, rate)
    if int(float(reaper.project_info.get("RENDER_CHANNELS", 2))) == 1:
        data = data.mean(axis=1)
    container, default_subtype = SOUNDFILE_FORMATS[extension]
    directory.mkdir(parents=True, exist_ok=True)
    sf.write(path, data, rate, format=container, subtype=subtype or default_subtype)
    return path
