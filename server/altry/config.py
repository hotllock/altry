"""Runtime configuration, all overridable through environment variables."""
import os
from pathlib import Path

VERSION = "1.0.0"

DATA_DIR = Path(os.environ.get("ALTRY_DATA", Path(__file__).resolve().parent.parent / "data"))
VOICES_DIR = DATA_DIR / "voices"
JOBS_DIR = DATA_DIR / "jobs"

# Optional shared secret. When set, every /api request must send it in X-Altry-Token.
TOKEN = os.environ.get("ALTRY_TOKEN", "")

# Speech-to-text model size for faster-whisper: tiny, base, small, medium, large-v3 ...
WHISPER_MODEL = os.environ.get("ALTRY_WHISPER", "small")

# "auto" = free online translation first, the offline model as fallback.
# "offline" = offline model only. "google" = online only.
TRANSLATOR = os.environ.get("ALTRY_TRANSLATOR", "auto")
# Offline translation model. facebook/m2m100_1.2B is more accurate but larger and slower.
TRANSLATION_MODEL = os.environ.get("ALTRY_TRANSLATION_MODEL", "facebook/m2m100_418M")

# "auto" = use Demucs to keep background music/effects when it is installed.
SEPARATE = os.environ.get("ALTRY_SEPARATE", "auto")

# Replace the AI engines with tiny deterministic stand-ins (tests / smoke runs).
FAKE = os.environ.get("ALTRY_FAKE", "") == "1"

MAX_UPLOAD_MB = int(os.environ.get("ALTRY_MAX_UPLOAD_MB", "500"))
MAX_MEDIA_MINUTES = int(os.environ.get("ALTRY_MAX_MINUTES", "30"))
FONT = os.environ.get("ALTRY_FONT", "")

# Languages the voice engine can speak (Chatterbox Multilingual).
LANGUAGES = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
    "it": "Italiano", "pt": "Português", "ru": "Русский", "ar": "العربية", "nl": "Nederlands",
    "pl": "Polski", "sv": "Svenska", "da": "Dansk", "no": "Norsk", "fi": "Suomi",
    "el": "Ελληνικά", "he": "עברית", "hi": "हिन्दी", "ja": "日本語", "ko": "한국어",
    "zh": "中文", "ms": "Bahasa Melayu", "sw": "Kiswahili",
}


def ensure_dirs() -> None:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
