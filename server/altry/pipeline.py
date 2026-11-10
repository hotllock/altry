"""The actual features: dubbing, voice changing, narration and video creation."""
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config, engines, media, voices
from .jobs import Context

ORIGINAL = "original"  # pseudo voice id: clone the speaker heard in the uploaded media


class PipelineError(ValueError):
    pass


def _check_media(src, need_audio: bool = True) -> dict:
    info = media.probe(src)
    if need_audio and not info["has_audio"]:
        raise PipelineError("Dosyada ses yok / the file has no audio track")
    if info["duration"] > config.MAX_MEDIA_MINUTES * 60:
        raise PipelineError(f"Dosya çok uzun (en fazla {config.MAX_MEDIA_MINUTES} dk)")
    return info


def _reference(voice_id: str, ctx: Context, speech_wav=None, segments=None) -> Path:
    """Resolve a voice id to a reference clip; ORIGINAL builds one from the media itself."""
    if voice_id != ORIGINAL:
        return voices.wav_path(voice_id)
    if speech_wav is None:
        raise PipelineError("Bu işlem için kütüphaneden bir ses seçin / pick a library voice")
    data, sr = media.read_wav(speech_wav)
    parts, total = [], 0.0
    for seg in sorted(segments or [], key=lambda s: s["end"] - s["start"], reverse=True):
        parts.append(data[int(seg["start"] * sr): int(seg["end"] * sr)])
        total += seg["end"] - seg["start"]
        if total >= 15:
            break
    raw = media.write_wav(ctx.work / "speaker_raw.wav", np.concatenate(parts) if parts else data, sr)
    ref = ctx.work / "speaker_ref.wav"
    voices.prepare_reference(raw, ref)
    return ref


def _finish(ctx: Context, src, info: dict, audio_wav, name: str, subtitles=None) -> Path:
    """Put the new audio on the original picture, or export audio only."""
    if info["has_video"]:
        return media.mux(src, audio_wav, ctx.dir / f"{name}.mp4", duration=info["duration"], subtitles=subtitles)
    return media.encode_audio(audio_wav, ctx.dir / f"{name}.m4a")


def _normalise_peak(data: np.ndarray) -> np.ndarray:
    peak = float(np.abs(data).max(initial=0.0))
    return data * (0.97 / peak) if peak > 0.97 else data


# ---------------------------------------------------------------- dubbing

def merge_segments(segments: list[dict], max_gap: float = 0.5, max_len: float = 12.0) -> list[dict]:
    """Join recognizer fragments into sentence-sized pieces so translation has context."""
    merged: list[dict] = []
    for seg in segments:
        last = merged[-1] if merged else None
        if (last and seg["start"] - last["end"] <= max_gap and seg["end"] - last["start"] <= max_len
                and not re.search(r"[.!?…]$", last["text"])):
            last["end"], last["text"] = seg["end"], f'{last["text"]} {seg["text"]}'
        else:
            merged.append(dict(seg))
    return merged


def _duck_envelope(length: int, sr: int, segments: list[dict], floor: float) -> np.ndarray:
    """Gain curve: `floor` while the original speaker talks, 1.0 elsewhere, with soft edges."""
    gain = np.ones(length, dtype="float32")
    for seg in segments:
        gain[max(0, int((seg["start"] - 0.1) * sr)): int((seg["end"] + 0.1) * sr)] = floor
    k = int(0.08 * sr)
    csum = np.cumsum(np.concatenate([np.full(k, gain[0], dtype="float64"), gain, np.full(k, gain[-1])]))
    return ((csum[2 * k:] - csum[:-2 * k]) / (2 * k)).astype("float32")[:length]


def dub(ctx: Context, src, target_lang: str, source_lang: str = "", voice_id: str = ORIGINAL,
        keep_background: bool = True, subtitles: bool = False, expressiveness: float = 0.5):
    if target_lang not in config.LANGUAGES:
        raise PipelineError("Desteklenmeyen hedef dil / unsupported target language")
    info = _check_media(src)
    ctx.progress(0.02, "Ses çıkarılıyor")
    full = media.extract_audio(src, ctx.work / "full.wav")

    stems = None
    if keep_background:
        ctx.progress(0.05, "Konuşma ve arka plan ayrılıyor")
        stems = engines.separate(full, ctx.work)
    speech = stems[0] if stems else full

    ctx.progress(0.12, "Konuşma yazıya dökülüyor")
    stt_wav = media.extract_audio(speech, ctx.work / "stt.wav", sr=16000)
    raw_segments, detected = engines.transcribe(stt_wav, source_lang or None)
    if not raw_segments:
        raise PipelineError("Videoda konuşma bulunamadı / no speech found")
    segments = merge_segments(raw_segments)

    ctx.progress(0.25, "Çevriliyor")
    texts = engines.translate([s["text"] for s in segments], detected, target_lang)
    ref = _reference(voice_id, ctx, speech, segments)

    sr = None
    clips: list[tuple[float, np.ndarray]] = []
    cues: list[tuple[float, float, str]] = []
    cursor = 0.0
    for i, (seg, text) in enumerate(zip(segments, texts)):
        ctx.progress(0.3 + 0.55 * i / len(segments), f"Seslendiriliyor {i + 1}/{len(segments)}")
        wav = engines.speak(text, target_lang, ref, ctx.work / f"seg_{i}.wav", expressiveness)
        data, sr = media.read_wav(wav)
        start = max(seg["start"], cursor)
        next_start = segments[i + 1]["start"] if i + 1 < len(segments) else max(info["duration"], seg["end"])
        slot = next_start - start - 0.05
        if slot > 0.3 and len(data) / sr > slot:  # too long for its slot: speak a little faster
            factor = min(len(data) / sr / slot, 1.35)
            data, sr = media.read_wav(media.change_tempo(wav, ctx.work / f"fit_{i}.wav", factor))
        clips.append((start, data))
        cues.append((start, start + len(data) / sr, text))
        cursor = start + len(data) / sr + 0.05

    ctx.progress(0.88, "Ses miksleniyor")
    total = max(info["duration"], cursor)
    track = np.zeros(int(total * sr) + sr, dtype="float32")
    for start, data in clips:
        at = int(start * sr)
        track[at: at + len(data)] += data[: len(track) - at]
    dub_wav = media.write_wav(ctx.work / "dub.wav", track, sr)
    mix, mix_sr = media.read_wav(dub_wav, media.MIX_SR)
    if keep_background:
        background, _ = media.read_wav(stems[1] if stems else full, media.MIX_SR)
        n = min(len(mix), len(background))
        if not stems:  # no separation available: lower the original while it speaks
            background = background[:n] * _duck_envelope(n, mix_sr, raw_segments, 0.06)
        mix[:n] += background[:n]
    final = media.write_wav(ctx.work / "final.wav", _normalise_peak(mix), mix_sr)

    ctx.progress(0.95, "Video birleştiriliyor")
    srt = media.write_srt(ctx.dir / "subtitles.srt", cues)
    out = _finish(ctx, src, info, final, f"dublaj_{target_lang}", subtitles=srt if subtitles else None)
    return out, {"srt": srt.name, "source_language": detected, "segments": len(segments),
                 "background": "separated" if stems else ("ducked" if keep_background else "removed")}


# ---------------------------------------------------------------- voice changer

def change_voice(ctx: Context, src, voice_id: str, keep_background: bool = True):
    info = _check_media(src)
    ref = voices.wav_path(voice_id)
    ctx.progress(0.03, "Ses çıkarılıyor")
    full = media.extract_audio(src, ctx.work / "full.wav")
    stems = None
    if keep_background:
        ctx.progress(0.06, "Konuşma ve arka plan ayrılıyor")
        stems = engines.separate(full, ctx.work)
    converted = engines.convert_voice(
        stems[0] if stems else full, ref, ctx.work / "converted.wav",
        progress=lambda f: ctx.progress(0.1 + 0.8 * f, "Ses dönüştürülüyor"))
    mix, sr = media.read_wav(converted, media.MIX_SR)
    if stems:
        background, _ = media.read_wav(stems[1], media.MIX_SR)
        n = min(len(mix), len(background))
        mix[:n] += background[:n]
    final = media.write_wav(ctx.work / "final.wav", _normalise_peak(mix), sr)
    ctx.progress(0.95, "Birleştiriliyor")
    return _finish(ctx, src, info, final, "ses_degistirildi"), {"background": "separated" if stems else "none"}


# ---------------------------------------------------------------- text to speech / narration

def speak(ctx: Context, text: str, language: str, voice_id: str, expressiveness: float = 0.5):
    ctx.progress(0.1, "Seslendiriliyor")
    wav = engines.speak(text, language, voices.wav_path(voice_id), ctx.work / "speech.wav", expressiveness)
    ctx.progress(0.9, "Kaydediliyor")
    return media.encode_audio(wav, ctx.dir / "seslendirme.m4a"), {}


def narrate(ctx: Context, src, text: str, language: str, voice_id: str, original_volume: float = 0.0,
            expressiveness: float = 0.5):
    """Say `text` with the chosen voice and lay it over an existing video."""
    info = _check_media(src, need_audio=False)
    if not info["has_video"]:
        raise PipelineError("Bir video seçin / pick a video file")
    ctx.progress(0.1, "Seslendiriliyor")
    wav = engines.speak(text, language, voices.wav_path(voice_id), ctx.work / "speech.wav", expressiveness)
    mix, sr = media.read_wav(wav, media.MIX_SR)
    if original_volume > 0 and info["has_audio"]:
        original, _ = media.read_wav(media.extract_audio(src, ctx.work / "full.wav"))
        length = max(len(mix), len(original))
        mix = np.pad(mix, (0, length - len(mix)))
        mix[: len(original)] += original * min(original_volume, 1.0)
    final = media.write_wav(ctx.work / "final.wav", _normalise_peak(mix), sr)
    speech_len = len(mix) / sr
    ctx.progress(0.85, "Video birleştiriliyor")
    out = ctx.dir / "seslendirilmis_video.mp4"
    if speech_len > info["duration"] + 0.2:  # narration outlasts the video: hold the last frame
        media.ffmpeg("-i", src, "-i", final, "-filter_complex",
                     f"[0:v]tpad=stop_mode=clone:stop_duration={speech_len - info['duration']:.2f}[v]",
                     "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    else:
        media.mux(src, final, out, duration=info["duration"])
    return out, {}


# ---------------------------------------------------------------- video from scratch

SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}
FPS = 25
PALETTES = [((28, 20, 84), (149, 48, 160)), ((6, 60, 90), (20, 160, 150)), ((92, 22, 42), (230, 120, 50)),
            ((16, 24, 48), (60, 100, 200)), ((30, 70, 40), (170, 190, 70))]


def split_scenes(script: str) -> list[str]:
    scenes: list[str] = []
    for line in script.splitlines():
        scenes += engines.split_text(line, limit=200)
    return scenes


def _font(size: int):
    candidates = [config.FONT, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _gradient(size: tuple[int, int], index: int, path) -> Path:
    w, h = size
    top, bottom = PALETTES[index % len(PALETTES)]
    ramp = np.linspace(0, 1, h, dtype="float32")[:, None, None]
    tilt = np.linspace(-0.15, 0.15, w, dtype="float32")[None, :, None]
    mix = np.clip(ramp + tilt, 0, 1)
    pixels = np.array(top, dtype="float32") * (1 - mix) + np.array(bottom, dtype="float32") * mix
    Image.fromarray(pixels.astype("uint8")).save(path, quality=92)
    return Path(path)


def _caption_chunks(text: str, limit: int) -> list[str]:
    """Split a scene's text into caption-sized pieces of similar length (no one-word leftovers)."""
    target = len(text) / max(1, math.ceil(len(text) / limit)) - 4
    chunks, current = [], ""
    for word in text.split():
        if current and (len(current) + len(word) + 1 > limit or len(current) >= target):
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    chunks.append(current)
    if len(chunks) > 1 and len(chunks[-1]) < 15:  # a stub at the end: share the last two evenly
        joined = f"{chunks[-2]} {chunks[-1]}"
        if len(joined) <= limit:
            chunks[-2:] = [joined]
        else:
            cut = min((i for i, ch in enumerate(joined) if ch == " "), key=lambda i: abs(i - len(joined) / 2))
            chunks[-2:] = [joined[:cut], joined[cut + 1:]]
    return [c for c in chunks if c]


def _caption_image(text: str, size: tuple[int, int], path) -> Path:
    w, h = size
    font = _font(int(min(w, h) * 0.058))
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > w * 0.84:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    line_h = int(font.size * 1.3)
    block_h = line_h * len(lines)
    block_w = max(draw.textlength(line, font=font) for line in lines)
    cy, pad = int(h * 0.76), int(font.size * 0.5)
    draw.rounded_rectangle([(w - block_w) / 2 - pad, cy - block_h / 2 - pad,
                            (w + block_w) / 2 + pad, cy + block_h / 2 + pad],
                           radius=pad, fill=(0, 0, 0, 150))
    for i, line in enumerate(lines):
        draw.text((w / 2, cy - block_h / 2 + i * line_h + line_h / 2), line, font=font,
                  fill=(255, 255, 255, 255), anchor="mm")
    image.save(path)
    return Path(path)


def _scene_clip(ctx: Context, index: int, image, audio, duration: float, captions: list[tuple[float, float, Path]],
                size: tuple[int, int]) -> Path:
    w, h = size
    frames = math.ceil(duration * FPS)
    zoom = f"1+0.12*on/{frames}" if index % 2 == 0 else f"1.12-0.12*on/{frames}"
    graph = [f"[0:v]scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},setsar=1,"
             f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}[v0]"]
    inputs = ["-i", image, "-i", audio]
    for n, (start, end, png) in enumerate(captions):
        inputs += ["-i", png]
        graph.append(f"[v{n}][{n + 2}:v]overlay=enable='between(t,{start:.3f},{end:.3f})'[v{n + 1}]")
    graph.append("[1:a]apad,aresample=44100[a]")
    out = ctx.work / f"scene_{index}.mp4"
    media.ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", f"[v{len(captions)}]", "-map", "[a]",
                 "-t", f"{frames / FPS:.3f}", "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ac", 2, out)
    return out


def create_video(ctx: Context, script: str, language: str, voice_id: str, images: list | None = None,
                 aspect: str = "9:16", subtitles: bool = True, music=None, expressiveness: float = 0.5):
    """Turn a script into a narrated video: one scene per sentence/line, with captions."""
    size = SIZES.get(aspect)
    if size is None:
        raise PipelineError("Geçersiz en-boy oranı / invalid aspect ratio")
    scenes = split_scenes(script)
    if not scenes:
        raise PipelineError("Metin boş / empty script")
    ref = voices.wav_path(voice_id)

    pictures = []
    for i, path in enumerate(images or []):
        try:
            picture = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except OSError as e:
            raise PipelineError(f"Görsel okunamadı / unreadable image #{i + 1}") from e
        picture.save(ctx.work / f"image_{i}.jpg", quality=92)
        pictures.append(ctx.work / f"image_{i}.jpg")

    clips, cues, clock = [], [], 0.0
    for i, text in enumerate(scenes):
        ctx.progress(0.05 + 0.85 * i / len(scenes), f"Sahne {i + 1}/{len(scenes)}")
        wav = engines.speak(text, language, ref, ctx.work / f"scene_{i}.wav", expressiveness)
        speech = media.probe(wav)["duration"]
        duration = speech + 0.4
        image = pictures[i % len(pictures)] if pictures else _gradient(size, i, ctx.work / f"bg_{i}.jpg")
        captions, chunks, t = [], _caption_chunks(text, 60 if size[0] < size[1] else 80), 0.0
        letters = sum(len(c) for c in chunks)
        for n, chunk in enumerate(chunks):
            span = speech * len(chunk) / letters
            cues.append((clock + t, clock + t + span, chunk))
            if subtitles:  # the last caption stays up through the short pause that ends the scene
                until = duration if n == len(chunks) - 1 else t + span
                captions.append((t, until, _caption_image(chunk, size, ctx.work / f"cap_{i}_{n}.png")))
            t += span
        clips.append(_scene_clip(ctx, i, image, wav, duration, captions, size))
        clock += math.ceil(duration * FPS) / FPS

    ctx.progress(0.92, "Sahneler birleştiriliyor")
    listing = ctx.work / "scenes.txt"
    listing.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    out = ctx.dir / "video.mp4"
    joined = ctx.work / "joined.mp4" if music else out
    media.ffmpeg("-f", "concat", "-safe", 0, "-i", listing, "-c", "copy", "-movflags", "+faststart", joined)
    if music:
        ctx.progress(0.96, "Müzik ekleniyor")
        media.ffmpeg("-i", joined, "-stream_loop", -1, "-i", music, "-filter_complex",
                     "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                     "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", "-movflags", "+faststart", out)
    srt = media.write_srt(ctx.dir / "subtitles.srt", cues)
    return out, {"srt": srt.name, "scenes": len(scenes)}
