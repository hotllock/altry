"""AI engines: speech recognition, translation, cloned speech, voice conversion.

Everything here is open source and runs on the machine hosting the server:
  * faster-whisper            - speech to text
  * Chatterbox Multilingual   - text to speech with zero-shot voice cloning (23 languages)
  * Chatterbox VC             - speech to speech voice conversion
  * M2M100                    - offline translation (free online translation is tried first in "auto")
  * Demucs (optional)         - separates speech from music/effects

Models are loaded lazily on first use and kept in memory.
"""
import re
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

from . import config, media

_lock = threading.Lock()
_cache: dict = {}


def device() -> str:
    if config.FAKE:
        return "fake"
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _get(name: str, factory):
    with _lock:
        if name not in _cache:
            _cache[name] = factory()
        return _cache[name]


# ---------------------------------------------------------------- speech to text

def transcribe(wav_path, language: str | None = None) -> tuple[list[dict], str]:
    """Returns ([{start, end, text}], detected_language)."""
    if config.FAKE:
        duration = media.probe(wav_path)["duration"]
        segs, t = [], 0.3
        while t + 1.5 < duration:
            segs.append({"start": t, "end": t + 1.5, "text": f"Sample sentence {len(segs) + 1}."})
            t += 2.5
        return segs, language or "en"

    def load():
        from faster_whisper import WhisperModel
        cuda = device() == "cuda"
        return WhisperModel(config.WHISPER_MODEL, device="cuda" if cuda else "cpu",
                            compute_type="float16" if cuda else "int8")

    model = _get("stt", load)
    segments, info = model.transcribe(str(wav_path), language=language or None, vad_filter=True)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments if s.text.strip()]
    return out, info.language


# ---------------------------------------------------------------- translation

def _offline(texts: list[str], src: str, dst: str) -> list[str]:
    """M2M100: one open model (MIT licence) that translates directly between 100 languages."""
    import torch

    def load():
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        tokenizer = M2M100Tokenizer.from_pretrained(config.TRANSLATION_MODEL)
        model = M2M100ForConditionalGeneration.from_pretrained(config.TRANSLATION_MODEL)
        return tokenizer, model.to(device()).eval()

    tokenizer, model = _get("translator", load)
    if src not in tokenizer.lang_code_to_id or dst not in tokenizer.lang_code_to_id:
        raise RuntimeError(f"Bu dil çifti çevrilemiyor / cannot translate {src} -> {dst}")
    out: list[str] = []
    with _lock, torch.inference_mode():
        tokenizer.src_lang = src
        for i in range(0, len(texts), 8):
            batch = tokenizer(texts[i:i + 8], return_tensors="pt", padding=True, truncation=True,
                              max_length=256).to(device())
            generated = model.generate(**batch, forced_bos_token_id=tokenizer.get_lang_id(dst),
                                       num_beams=4, max_new_tokens=256)
            out += tokenizer.batch_decode(generated, skip_special_tokens=True)
    return out


def _google(texts: list[str], src: str, dst: str) -> list[str]:
    from deep_translator import GoogleTranslator
    codes = {"zh": "zh-CN", "he": "iw"}
    translator = GoogleTranslator(source=codes.get(src, src), target=codes.get(dst, dst))
    return [translator.translate(t) or t for t in texts]


def translate(texts: list[str], src: str, dst: str) -> list[str]:
    if src == dst or not texts:
        return texts
    if config.FAKE:
        return [f"[{dst}] {t}" for t in texts]
    mode = config.TRANSLATOR
    if mode in ("auto", "google"):
        try:
            return _google(texts, src, dst)
        except Exception:
            if mode == "google":
                raise
    return _offline(texts, src, dst)


# ---------------------------------------------------------------- text to speech

def split_text(text: str, limit: int = 240) -> list[str]:
    """Split into chunks the TTS model can speak in one go, on sentence boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…。！？])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:  # a single very long sentence: break on a comma or space
            cut = max(sentence.rfind(", ", 0, limit), sentence.rfind(" ", 0, limit))
            cut = cut if cut > limit // 3 else limit
            if current:
                chunks.append(current)
            chunks.append(sentence[:cut].strip())
            current, sentence = "", sentence[cut:].strip()
        if len(current) + len(sentence) + 1 <= limit:
            current = (current + " " + sentence).strip()
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _tts_model():
    def load():
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        return ChatterboxMultilingualTTS.from_pretrained(device=device())
    return _get("tts", load)


def _fake_tone(seconds: float, freq: float, sr: int = 24000) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
    return (0.3 * np.sin(2 * np.pi * freq * t) * fade).astype("float32")


def speak(text: str, language: str, ref_wav, out_path, expressiveness: float = 0.5) -> Path:
    """Say `text` in `language` with the voice heard in `ref_wav`. Writes a mono wav."""
    if language not in config.LANGUAGES:
        raise ValueError(f"Desteklenmeyen dil / unsupported language: {language}")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("Metin boş / empty text")
    if config.FAKE:
        freq = 180 + (sum(Path(ref_wav).name.encode()) % 200)
        parts, sr = [_fake_tone(max(0.4, len(c) * 0.06), freq) for c in chunks], 24000
    else:
        model = _tts_model()
        with _lock:
            if _cache.get("tts_ref") != (str(ref_wav), expressiveness):
                model.prepare_conditionals(str(ref_wav), exaggeration=expressiveness)
                _cache["tts_ref"] = (str(ref_wav), expressiveness)
            parts = [model.generate(c, language_id=language, exaggeration=expressiveness)
                     .squeeze(0).numpy().astype("float32") for c in chunks]
        sr = model.sr
    gap = np.zeros(int(0.18 * sr), dtype="float32")
    joined = []
    for i, part in enumerate(parts):
        joined.append(media.trim_silence(part, sr))
        if i < len(parts) - 1:
            joined.append(gap)
    return media.write_wav(out_path, np.concatenate(joined), sr)


# ---------------------------------------------------------------- voice conversion

def convert_voice(src_wav, ref_wav, out_path, progress=lambda f: None) -> Path:
    """Re-voice the speech in `src_wav` so it sounds like `ref_wav`. Timing and words are kept."""
    if config.FAKE:
        data, sr = media.read_wav(src_wav, 24000)
        progress(1.0)
        return media.write_wav(out_path, data[::-1].copy() * 0.8, sr)

    def load():
        from chatterbox.vc import ChatterboxVC
        if "tts" in _cache:  # share the decoder with the TTS model instead of loading it twice
            return ChatterboxVC(_cache["tts"].s3gen, device())
        return ChatterboxVC.from_pretrained(device())

    with _lock:
        if "vc" not in _cache:
            _cache["vc"] = load()
        model = _cache["vc"]
    data, sr = media.read_wav(src_wav, 16000)
    cuts = [0, *media.quiet_split_points(data, sr), len(data)]
    out, work = [], Path(out_path).parent
    with _lock:
        model.set_target_voice(str(ref_wav))
        for i in range(len(cuts) - 1):
            piece = data[cuts[i]:cuts[i + 1]]
            want = int(len(piece) / sr * model.sr)
            if np.abs(piece).max(initial=0) < 0.005:  # silence: nothing to convert
                out.append(np.zeros(want, dtype="float32"))
            else:
                chunk = media.write_wav(work / f"vc_chunk_{i}.wav", piece, sr)
                wav = model.generate(str(chunk)).squeeze(0).numpy().astype("float32")
                # keep every chunk exactly as long as its source so lips/timing stay in sync
                wav = wav[:want] if len(wav) >= want else np.pad(wav, (0, want - len(wav)))
                out.append(wav)
                chunk.unlink(missing_ok=True)
            progress((i + 1) / (len(cuts) - 1))
    return media.write_wav(out_path, np.concatenate(out), model.sr)


# ---------------------------------------------------------------- source separation

def can_separate() -> bool:
    if config.FAKE or config.SEPARATE == "0":
        return False
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def separate(wav_path, work_dir) -> tuple[Path, Path] | None:
    """Split into (vocals, background). Returns None when Demucs is unavailable or fails."""
    if not can_separate():
        return None
    out = Path(work_dir) / "demucs"
    proc = subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", str(out), str(wav_path)],
        capture_output=True, text=True,
    )
    base = out / "htdemucs" / Path(wav_path).stem
    vocals, background = base / "vocals.wav", base / "no_vocals.wav"
    if proc.returncode != 0 or not vocals.exists() or not background.exists():
        return None
    return vocals, background


def status() -> dict:
    return {
        "device": device(),
        "whisper": config.WHISPER_MODEL,
        "translator": config.TRANSLATOR,
        "separation": can_separate(),
        "loaded": sorted(k for k in _cache if k in ("stt", "tts", "vc")),
    }
