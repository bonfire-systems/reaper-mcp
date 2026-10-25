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
REGION_BOUNDS = (3, 5)  # all regions, selected regions
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


def _regions(reaper: FakeReaper) -> list[tuple[float, float, str]]:
    """The regions a region render covers. The fake has no region selection;
    REAPER 7.75 renders every region for "selected regions" (5) when none is
    selected, so both region flags cover all of them here."""
    return sorted(reaper.regions)


def _paths(reaper: FakeReaper) -> list[Path]:
    extension, _ = _format(str(reaper.project_info.get("RENDER_FORMAT", "")))
    directory = Path(str(reaper.project_info.get("RENDER_FILE", "")))
    pattern = str(reaper.project_info.get("RENDER_PATTERN", "")) or "untitled"
    flag = int(float(reaper.project_info.get("RENDER_BOUNDSFLAG", 1.0)))
    if flag in REGION_BOUNDS:
        stems = [pattern.replace("$region", name) for _, _, name in _regions(reaper)]
        return [directory / f"{stem}.{extension}" for stem in _numbered(stems)]
    return [directory / f"{pattern}.{extension}"]


def _numbered(stems: list[str]) -> list[str]:
    """REAPER 7.82 numbers file names that would clash: two regions named
    "take", or a pattern without $region, give "take-001" and "take-002"."""
    totals = {stem: stems.count(stem) for stem in stems}
    seen: dict[str, int] = {}
    numbered = []
    for stem in stems:
        seen[stem] = seen.get(stem, 0) + 1
        numbered.append(stem if totals[stem] == 1 else f"{stem}-{seen[stem]:03d}")
    return numbered


def render_targets(reaper: FakeReaper) -> str:
    """RENDER_TARGETS as REAPER 7.75 and 7.82 report it for region bounds: the
    paths, each followed by ';'. Only region bounds are modelled; for any other bounds
    the fake reports no targets."""
    flag = int(float(reaper.project_info.get("RENDER_BOUNDSFLAG", 1.0)))
    if flag not in REGION_BOUNDS:
        return ""
    return "".join(f"{path};" for path in _paths(reaper))


def render(reaper: FakeReaper) -> list[Path]:
    flag = int(float(reaper.project_info.get("RENDER_BOUNDSFLAG", 1.0)))
    if flag in REGION_BOUNDS:
        spans = [(start, end) for start, end, _ in _regions(reaper)]
    else:
        spans = [_bounds(reaper)]
    paths = _paths(reaper)
    if not paths or any(end <= start for start, end in spans):
        raise ModalDialog("Render Error: Nothing to render!")
    for path in paths:
        if path.exists():
            raise ModalDialog(f"Render Warning: {path.name} exists (overwrite / increment / cancel)")
    return [_write(reaper, path, start, end)
            for path, (start, end) in zip(paths, spans, strict=True)]


def _write(reaper: FakeReaper, path: Path, start: float, end: float) -> Path:
    extension, subtype = _format(str(reaper.project_info.get("RENDER_FORMAT", "")))
    directory = path.parent
    rate = int(float(reaper.project_info.get("RENDER_SRATE", 48000)))
    data = _signal(reaper, end - start, rate)
    if int(float(reaper.project_info.get("RENDER_CHANNELS", 2))) == 1:
        data = data.mean(axis=1)
    container, default_subtype = SOUNDFILE_FORMATS[extension]
    directory.mkdir(parents=True, exist_ok=True)
    sf.write(path, data, rate, format=container, subtype=subtype or default_subtype)
    return path
