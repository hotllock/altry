"""Free, openly licensed pictures from the internet for the scenes of a generated video.

Two keyless sources are asked in turn: Wikimedia Commons, then Openverse (Creative Commons photos
from Flickr and others). Nothing here needs an account or an API key.
"""
import re
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from . import voices

# Wikimedia refuses anonymous-looking clients: the agent must say what it is and where it lives.
HEADERS = {"User-Agent": "Altry/1.0 (https://github.com/hotllock/altry)"}
MAX_BYTES = 15 * 1024 * 1024
MIN_SIDE = 480
STOPWORDS = set("""a about after all also an and any are as at be because been but by can could did do does
    for from had has have he her here him his how i if in into is it its just like more most my no not of on
    one only or other our out over she so some such than that the their them then there these they this to
    too up us very was we were what when where which who why will with would you your""".split())


def keywords(text: str, limit: int = 4) -> str:
    """The few most telling words of an (English) sentence, as a search query."""
    words = [w for w in re.findall(r"[^\W\d_]+", text.lower()) if len(w) > 2 and w not in STOPWORDS]
    unique = list(dict.fromkeys(words))
    longest = set(sorted(unique, key=len, reverse=True)[:limit])
    return " ".join(w for w in unique if w in longest)


def _openverse(query: str, aspect: str) -> list[dict]:
    shape = {"9:16": "tall", "16:9": "wide", "1:1": "square"}.get(aspect, "wide")
    resp = httpx.get("https://api.openverse.org/v1/images/", headers=HEADERS, timeout=20,
                     params={"q": query, "page_size": 20, "aspect_ratio": shape, "mature": "false",
                             # cropping and captions make a derivative: skip "no derivatives" licences
                             "license_type": "modification"})
    resp.raise_for_status()
    return [{"url": r["url"], "title": r.get("title") or "", "creator": r.get("creator") or "",
             "license": f'CC {r.get("license", "")} {r.get("license_version") or ""}'.strip().upper(),
             "page": r.get("foreign_landing_url") or ""}
            for r in resp.json().get("results", [])
            if r.get("url") and min(r.get("width") or 0, r.get("height") or 0) >= MIN_SIDE]


def _commons(query: str, aspect: str) -> list[dict]:
    resp = httpx.get("https://commons.wikimedia.org/w/api.php", headers=HEADERS, timeout=20,
                     params={"action": "query", "format": "json", "generator": "search",
                             "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
                             "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1280,
                             "iiextmetadatafilter": "LicenseShortName|Artist"})
    resp.raise_for_status()
    pages = sorted(resp.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    tall = aspect == "9:16"
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl") or min(info.get("width") or 0, info.get("height") or 0) < MIN_SIDE:
            continue
        meta = info.get("extmetadata") or {}
        found.append({"url": info["thumburl"], "title": page.get("title", "").removeprefix("File:"),
                      "creator": re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()[:80],
                      "license": meta.get("LicenseShortName", {}).get("value", ""),
                      "page": info.get("descriptionurl") or "",
                      "fits": (info.get("height", 0) > info.get("width", 0)) == tall})
    return sorted(found, key=lambda f: not f.pop("fits"))  # stable: right orientation first


def search(query: str, aspect: str = "16:9") -> list[dict]:
    """Candidate pictures for `query`: [{url, title, creator, license, page}]. Empty when nothing is found."""
    query = " ".join(query.split())[:120]
    if not query:
        return []
    for source in (_commons, _openverse):
        try:
            found = source(query, aspect)
        except (httpx.HTTPError, ValueError, KeyError):
            continue
        if found:
            return found
    return []


def download(url: str, dst) -> Path | None:
    """Save the picture at `url` as a JPEG. Returns None when it cannot be fetched or is not a picture."""
    try:
        voices._check_public_url(url)
        data = b""
        with httpx.stream("GET", url, follow_redirects=True, timeout=30, headers=HEADERS) as resp:
            if resp.status_code != 200:
                return None
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
        picture = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        picture.thumbnail((2560, 2560))
        picture.save(dst, quality=92)
        return Path(dst)
    except (httpx.HTTPError, voices.VoiceError, OSError, ValueError, Image.DecompressionBombError):
        return None


def credit_line(item: dict) -> str:
    by = f' — {item["creator"]}' if item.get("creator") else ""
    return f'{item.get("title") or "Görsel"}{by} ({item.get("license") or "?"}) {item.get("page", "")}'.strip()
