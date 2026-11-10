"""Thin ffmpeg / audio helpers."""
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

MIX_SR = 44100


class MediaError(RuntimeError):
    pass


def run(cmd: list) -> None:
    cmd = [str(c) for c in cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise MediaError(f"{cmd[0]} failed: {tail}")


def ffmpeg(*args) -> None:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def probe(path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError("Dosya okunamadı / unreadable media file")
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    return {
        "duration": float(info.get("format", {}).get("duration") or 0.0),
        "has_video": video is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
    }


def extract_audio(src, dst, sr: int = MIX_SR, channels: int = 1) -> Path:
    ffmpeg("-i", src, "-vn", "-ac", channels, "-ar", sr, "-c:a", "pcm_s16le", dst)
    return Path(dst)


def read_wav(path, sr: int | None = None) -> tuple[np.ndarray, int]:
    """Read as mono float32. Resamples through ffmpeg when `sr` differs."""
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if sr and file_sr != sr:
        tmp = Path(str(path) + f".{sr}.wav")
        extract_audio(path, tmp, sr=sr)
        data, file_sr = sf.read(str(tmp), dtype="float32", always_2d=True)
        data = data.mean(axis=1)
        tmp.unlink(missing_ok=True)
    return data, file_sr


def write_wav(path, data: np.ndarray, sr: int) -> Path:
    sf.write(str(path), np.clip(data, -1.0, 1.0), sr, subtype="PCM_16")
    return Path(path)


def trim_silence(data: np.ndarray, sr: int, threshold: float = 0.012, pad: float = 0.04) -> np.ndarray:
    loud = np.flatnonzero(np.abs(data) > threshold)
    if loud.size == 0:
        return data
    start = max(0, loud[0] - int(pad * sr))
    end = min(len(data), loud[-1] + int(pad * sr))
    return data[start:end]


def change_tempo(src, dst, factor: float) -> Path:
    """Speed speech up/down without changing pitch."""
    ffmpeg("-i", src, "-filter:a", f"atempo={factor:.4f}", dst)
    return Path(dst)


def quiet_split_points(data: np.ndarray, sr: int, target: float = 20.0, slack: float = 5.0) -> list[int]:
    """Cut positions (samples) roughly every `target` seconds, moved to the quietest nearby spot."""
    points, pos, frame = [], 0, int(0.05 * sr)
    while len(data) - pos > (target + slack) * sr:
        lo, hi = pos + int((target - slack) * sr), pos + int((target + slack) * sr)
        window = data[lo:hi]
        n = len(window) // frame
        rms = np.sqrt((window[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
        pos = lo + int(np.argmin(rms)) * frame + frame // 2
        points.append(pos)
    return points


def mux(video, audio, dst, duration: float | None = None, subtitles=None) -> Path:
    """Replace the audio track of `video`, keeping the picture untouched."""
    args = ["-i", video, "-i", audio]
    if subtitles:
        args += ["-i", subtitles]
    args += ["-map", "0:v:0", "-map", "1:a:0"]
    if subtitles:
        args += ["-map", "2:0", "-c:s", "mov_text", "-metadata:s:s:0", "title=Altry"]
    args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    ffmpeg(*args, dst)
    return Path(dst)


def encode_audio(src, dst) -> Path:
    ffmpeg("-i", src, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst)
    return Path(dst)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(path, cues: list[tuple[float, float, str]]) -> Path:
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines += [str(i), f"{srt_time(start)} --> {srt_time(end)}", text.strip(), ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return Path(path)
