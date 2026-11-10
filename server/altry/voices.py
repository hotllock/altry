"""Voice library: reference recordings the engines clone from."""
import ipaddress
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config, media

REF_SR = 24000
MAX_REF_SECONDS = 30
MIN_REF_SECONDS = 3
MAX_DOWNLOAD = 60 * 1024 * 1024
CATALOG = Path(__file__).with_name("catalog.json")


class VoiceError(ValueError):
    pass


def _meta_path(voice_id: str) -> Path:
    return config.VOICES_DIR / f"{voice_id}.json"


def wav_path(voice_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", voice_id or ""):
        raise VoiceError("Geçersiz ses / invalid voice id")
    path = config.VOICES_DIR / f"{voice_id}.wav"
    if not path.exists():
        raise VoiceError("Ses bulunamadı / voice not found")
    return path


def list_voices() -> list[dict]:
    voices = [json.loads(p.read_text(encoding="utf-8")) for p in config.VOICES_DIR.glob("*.json")]
    return sorted(voices, key=lambda v: v["created"], reverse=True)


def prepare_reference(src, dst) -> float:
    """Normalise any audio/video file into a clean mono reference clip. Returns its duration."""
    media.ffmpeg(
        "-i", src, "-vn", "-ac", 1, "-ar", REF_SR,
        "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,"
               "highpass=f=60,loudnorm=I=-18:TP=-2:LRA=11",
        "-t", MAX_REF_SECONDS, "-c:a", "pcm_s16le", dst,
    )
    return media.probe(dst)["duration"]


def add_from_file(src, name: str, source: str = "upload", language: str = "", voice_id: str | None = None,
                  extra: dict | None = None) -> dict:
    name = (name or "").strip()[:60] or "Ses"
    voice_id = voice_id or uuid.uuid4().hex[:12]
    dst = config.VOICES_DIR / f"{voice_id}.wav"
    try:
        duration = prepare_reference(src, dst)
    except media.MediaError as e:
        dst.unlink(missing_ok=True)
        raise VoiceError("Ses dosyası okunamadı / could not read the audio") from e
    if duration < MIN_REF_SECONDS:
        dst.unlink(missing_ok=True)
        raise VoiceError(f"Kayıt çok kısa: en az {MIN_REF_SECONDS} sn konuşma gerekli (10+ sn önerilir)")
    meta = {"id": voice_id, "name": name, "source": source, "language": language,
            "duration": round(duration, 1), "created": time.time(), **(extra or {})}
    _meta_path(voice_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def _check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise VoiceError("Yalnızca http(s) bağlantıları / only http(s) links")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            return  # no local DNS: the outbound proxy resolves (and cannot reach our local network)
        raise VoiceError("Adres çözülemedi / host not found") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise VoiceError("Yerel ağ adreslerine izin yok / local addresses are not allowed")


def add_from_url(url: str, name: str, **kwargs) -> dict:
    """Download an audio (or video) file from the internet and add it as a voice."""
    _check_public_url(url)
    tmp = config.VOICES_DIR / f"dl_{uuid.uuid4().hex}"
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60,
                          headers={"User-Agent": "altry-server"}) as resp:
            if resp.status_code != 200:
                raise VoiceError(f"İndirilemedi / download failed (HTTP {resp.status_code})")
            size = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise VoiceError("Dosya çok büyük / file too large")
                    f.write(chunk)
        return add_from_file(tmp, name, source="url", **kwargs)
    except httpx.HTTPError as e:
        raise VoiceError(f"İndirilemedi / download failed: {type(e).__name__}") from e
    finally:
        tmp.unlink(missing_ok=True)


def delete(voice_id: str) -> None:
    wav_path(voice_id).unlink()
    _meta_path(voice_id).unlink(missing_ok=True)


def catalog() -> list[dict]:
    installed = {v["id"] for v in list_voices()}
    items = json.loads(CATALOG.read_text(encoding="utf-8"))
    return [{**item, "installed": item["id"] in installed} for item in items]


def install_from_catalog(item_id: str) -> dict:
    item = next((i for i in catalog() if i["id"] == item_id), None)
    if item is None:
        raise VoiceError("Katalogda yok / not in catalog")
    return add_from_url(item["url"], item["name"], language=item["language"], voice_id=item["id"],
                        extra={"license": item["license"], "credit": item["credit"]})
