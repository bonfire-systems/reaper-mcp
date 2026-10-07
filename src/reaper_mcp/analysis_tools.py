import os

import numpy as np


def _band_rms_db(D: np.ndarray, freqs: np.ndarray, band: tuple[float, float]) -> float:
    lo, hi = band
    mask = (freqs >= lo) & (freqs <= hi)
    if not mask.any():
        return -120.0
    power = float(np.mean(D[mask, :] ** 2))
    return float(10 * np.log10(power + 1e-12))


def analyze_frequency_spectrum() -> dict:
    """
    Render the project and analyze frequency band levels.
    Returns RMS level in dB for seven bands:
    sub_bass (20–60Hz), bass (60–250Hz), low_mids (250–500Hz),
    mids (500–2kHz), high_mids (2–4kHz), presence (4–8kHz), brilliance (8–20kHz).
    """
    import librosa

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        y, sr = librosa.load(tmp, sr=None, mono=True)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    D = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)

    bands = {
        "sub_bass":   (20,   60),
        "bass":       (60,   250),
        "low_mids":   (250,  500),
        "mids":       (500,  2000),
        "high_mids":  (2000, 4000),
        "presence":   (4000, 8000),
        "brilliance": (8000, min(20000, sr // 2)),
    }

    results = {
        name: {
            "range_hz": f"{lo}–{hi}",
            "level_db": round(_band_rms_db(D, freqs, (lo, hi)), 1),
        }
        for name, (lo, hi) in bands.items()
    }

    return {"success": True, "frequency_bands": results}

def detect_clipping() -> dict:
    """
    Render the project and detect digital clipping (samples at or above 0 dBFS).
    Returns clipped sample count, peak level in dB, and whether clipping was found.
    """
    import soundfile as sf

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        data, rate = sf.read(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    if data.ndim > 1:
        mono = np.max(np.abs(data), axis=1)
    else:
        mono = np.abs(data)

    clip_threshold = 0.9999
    clipped_samples = int(np.sum(mono >= clip_threshold))
    peak_linear = float(np.max(mono))
    peak_db = float(20 * np.log10(peak_linear)) if peak_linear > 0 else -120.0

    return {
        "success": True,
        "clipping_detected": clipped_samples > 0,
        "clipped_samples": clipped_samples,
        "peak_db": round(peak_db, 2),
        "peak_linear": round(peak_linear, 4),
    }

def analyze_dynamics() -> dict:
    """
    Render the project and measure dynamic range: RMS, peak, crest factor,
    and a simplified DR score (average peak-to-RMS over 3-second blocks).
    """
    import soundfile as sf

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        data, rate = sf.read(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    mono = np.mean(data, axis=1) if data.ndim > 1 else data
    rms = float(np.sqrt(np.mean(mono ** 2)))
    peak = float(np.max(np.abs(mono)))
    rms_db = float(20 * np.log10(rms)) if rms > 0 else -120.0
    peak_db = float(20 * np.log10(peak)) if peak > 0 else -120.0
    crest_db = peak_db - rms_db

    # Simplified DR score: average crest factor over 3-second blocks
    block_size = rate * 3
    n_blocks = len(mono) // block_size
    dr_scores = []
    for i in range(n_blocks):
        block = mono[i * block_size:(i + 1) * block_size]
        blk_peak = np.max(np.abs(block))
        blk_rms = np.sqrt(np.mean(block ** 2))
        if blk_rms > 0:
            dr_scores.append(float(20 * np.log10(blk_peak / blk_rms)))
    dr = float(np.mean(dr_scores)) if dr_scores else 0.0

    return {
        "success": True,
        "rms_db": round(rms_db, 1),
        "peak_db": round(peak_db, 1),
        "crest_factor_db": round(crest_db, 1),
        "dr_score": round(dr, 1),
    }

def analyze_stereo_field() -> dict:
    """
    Render the project and analyze stereo width and mono compatibility.
    Returns mid/side balance, stereo width ratio, and L/R correlation.
    Correlation near 1 = mono-like, near 0 = wide stereo, negative = phase issues.
    """
    import soundfile as sf

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file()
    try:
        data, rate = sf.read(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    if data.ndim < 2 or data.shape[1] < 2:
        return {"success": False, "error": "Project rendered as mono; cannot analyze stereo field"}

    L, R = data[:, 0], data[:, 1]
    mid = (L + R) / 2
    side = (L - R) / 2
    mid_rms = float(np.sqrt(np.mean(mid ** 2)))
    side_rms = float(np.sqrt(np.mean(side ** 2)))
    width_ratio = side_rms / (mid_rms + 1e-10)
    correlation = float(np.corrcoef(L, R)[0, 1])

    return {
        "success": True,
        "stereo_width_ratio": round(width_ratio, 3),
        "lr_correlation": round(correlation, 3),
        "mid_rms_db": round(float(20 * np.log10(mid_rms + 1e-10)), 1),
        "side_rms_db": round(float(20 * np.log10(side_rms + 1e-10)), 1),
        "mono_compatible": correlation > 0.0,
        "notes": (
            "width_ratio: 0=mono, >0.5=wide stereo. "
            "lr_correlation: 1=mono, 0=fully wide, <0=phase problems."
        ),
    }

def analyze_transients() -> dict:
    """
    Render the project and detect transient events (note attacks, drum hits, etc.).
    Returns the count and timing of up to 100 transient onset events.
    """
    import librosa

    from reaper_mcp.render_tools import render_to_temp_file

    tmp = render_to_temp_file(sample_rate=44100)
    try:
        y, sr = librosa.load(tmp, sr=None, mono=True)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames")
    onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()
    capped = onset_times[:100]

    return {
        "success": True,
        "onset_count": len(onset_times),
        "onset_times_seconds": [round(t, 3) for t in capped],
        "note": "Showing up to 100 events" if len(onset_times) > 100 else None,
    }


TOOLS = (
    analyze_frequency_spectrum,
    detect_clipping,
    analyze_dynamics,
    analyze_stereo_field,
    analyze_transients,
)
