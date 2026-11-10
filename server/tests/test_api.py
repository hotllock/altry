"""End-to-end API tests. The AI models are replaced by stand-ins (ALTRY_FAKE=1);
everything else - ffmpeg, timing, mixing, muxing, the job queue - is the real code."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="altry-test-"))
os.environ["ALTRY_FAKE"] = "1"
os.environ["ALTRY_DATA"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from altry import config, engines, media, pipeline  # noqa: E402
from altry.app import app  # noqa: E402

client = TestClient(app)


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


@pytest.fixture(scope="session")
def video():
    path = TMP / "clip.mp4"
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=8", "-f", "lavfi", "-i",
       "sine=frequency=300:duration=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path)
    return path


@pytest.fixture(scope="session")
def voice_file():
    path = TMP / "voice.wav"
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=6", path)
    return path


@pytest.fixture(scope="session")
def voice_id(voice_file):
    with open(voice_file, "rb") as f:
        r = client.post("/api/voices", data={"name": "Benim sesim", "consent": "true"}, files={"file": f})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait(job: dict) -> dict:
    for _ in range(600):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    return job


def download(job: dict, extra: str = "") -> Path:
    r = client.get(f"/api/jobs/{job['id']}/result", params={"extra": extra} if extra else None)
    assert r.status_code == 200
    path = TMP / f"{job['id']}_{extra or job['result']}"
    path.write_bytes(r.content)
    return path


def test_health_and_languages():
    assert client.get("/api/health").json()["ok"] is True
    codes = [lang["code"] for lang in client.get("/api/languages").json()]
    assert "tr" in codes and "en" in codes


def test_voice_library(voice_id, voice_file):
    listed = client.get("/api/voices").json()
    assert [v["id"] for v in listed] == [voice_id] and listed[0]["duration"] >= 5
    assert client.get(f"/api/voices/{voice_id}/sample").status_code == 200
    with open(voice_file, "rb") as f:  # no consent -> refused
        assert client.post("/api/voices", data={"name": "x"}, files={"file": f}).status_code == 400
    short = TMP / "short.wav"
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=1", short)
    with open(short, "rb") as f:
        r = client.post("/api/voices", data={"name": "x", "consent": "true"}, files={"file": f})
    assert r.status_code == 400 and "kısa" in r.json()["detail"]
    assert len(client.get("/api/voices").json()) == 1
    assert len(client.get("/api/voices/catalog").json()) >= 5


def test_url_import_rejects_local_addresses():
    r = client.post("/api/voices/from-url", data={"name": "x", "url": "http://127.0.0.1/a.mp3", "consent": "true"})
    assert r.status_code == 400


def test_dub_keeps_video_and_length(video):
    with open(video, "rb") as f:
        r = client.post("/api/jobs/dub", data={"target_lang": "tr", "subtitles": "true"}, files={"file": f})
    assert r.status_code == 200, r.text
    job = wait(r.json())
    info = media.probe(download(job))
    assert info["has_video"] and info["has_audio"] and abs(info["duration"] - 8) < 0.3
    srt = download(job, "srt").read_text(encoding="utf-8")
    assert "[tr] Sample sentence 1." in srt and "-->" in srt
    assert job["extras"]["segments"] == 3


def test_dub_with_library_voice_audio_only(voice_id, voice_file):
    with open(voice_file, "rb") as f:
        r = client.post("/api/jobs/dub", data={"target_lang": "en", "voice_id": voice_id}, files={"file": f})
    job = wait(r.json())
    assert job["result"].endswith(".m4a")


def test_dub_rejects_bad_input(video):
    with open(video, "rb") as f:
        assert client.post("/api/jobs/dub", data={"target_lang": "xx"}, files={"file": f}).status_code == 400
    r = client.post("/api/jobs/dub", data={"target_lang": "tr"}, files={"file": ("a.mp4", b"not a video")})
    job = r.json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "queued" and job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "error" and job["error"]


def test_voice_change(video, voice_id):
    with open(video, "rb") as f:
        r = client.post("/api/jobs/voice-change", data={"voice_id": voice_id}, files={"file": f})
    info = media.probe(download(wait(r.json())))
    assert info["has_video"] and abs(info["duration"] - 8) < 0.3


def test_speak_and_narrate(video, voice_id):
    data = {"text": "Merhaba dünya. Bu benim sesim.", "language": "tr", "voice_id": voice_id}
    assert media.probe(download(wait(client.post("/api/jobs/speak", data=data).json())))["duration"] > 1
    with open(video, "rb") as f:
        r = client.post("/api/jobs/speak", data={**data, "original_volume": "0.2"}, files={"file": f})
    info = media.probe(download(wait(r.json())))
    assert info["has_video"] and abs(info["duration"] - 8) < 0.3
    long_text = {**data, "text": "Uzun bir cümle. " * 40}  # narration longer than the 8 s video
    with open(video, "rb") as f:
        r = client.post("/api/jobs/speak", data=long_text, files={"file": f})
    assert media.probe(download(wait(r.json())))["duration"] > 12


def test_create_video(voice_id):
    script = "Altry ile video üretmek çok kolay.\nİkinci sahne burada başlıyor ve biraz daha uzun bir cümle içeriyor."
    data = {"script": script, "language": "tr", "voice_id": voice_id, "aspect": "9:16"}
    job = wait(client.post("/api/jobs/create-video", data=data).json())
    info = media.probe(download(job))
    assert (info["width"], info["height"]) == (720, 1280) and info["has_audio"] and job["extras"]["scenes"] == 2
    image, music = TMP / "pic.png", TMP / "music.wav"
    ff("-f", "lavfi", "-i", "testsrc=size=640x480", "-frames:v", "1", image)
    ff("-f", "lavfi", "-i", "sine=frequency=500:duration=2", music)
    with open(image, "rb") as i, open(music, "rb") as m:
        r = client.post("/api/jobs/create-video", data={**data, "aspect": "16:9", "subtitles": "false"},
                        files=[("images", ("pic.png", i)), ("music", ("music.wav", m))])
    info = media.probe(download(wait(r.json())))
    assert (info["width"], info["height"]) == (1280, 720) and info["duration"] > 4


def test_delete_job_and_voice_validation(voice_id):
    job = wait(client.post("/api/jobs/speak", data={"text": "Selam", "language": "tr", "voice_id": voice_id}).json())
    assert client.delete(f"/api/jobs/{job['id']}").json()["ok"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    r = client.post("/api/jobs/speak", data={"text": "Selam", "language": "tr", "voice_id": "../etc"})
    assert r.status_code == 400


def test_token(monkeypatch):
    monkeypatch.setattr(config, "TOKEN", "gizli")
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"X-Altry-Token": "gizli"}).status_code == 200


def test_text_and_segment_helpers():
    chunks = engines.split_text("Bir. İki! Üç? " + "çok uzun kelime " * 40, limit=100)
    assert all(len(c) <= 100 for c in chunks) and chunks[0] == "Bir. İki! Üç?"
    merged = pipeline.merge_segments([
        {"start": 0.0, "end": 1.0, "text": "Hello"}, {"start": 1.2, "end": 2.0, "text": "world."},
        {"start": 2.1, "end": 3.0, "text": "Next"}])
    assert [m["text"] for m in merged] == ["Hello world.", "Next"]
    assert pipeline.split_scenes("A b.\n\nC d. E f.") == ["A b.", "C d. E f."]
    chunks = pipeline._caption_chunks("Boğaz'da gün batımını izlemek, şehrin en güzel anlarından biridir.", 60)
    assert len(chunks) == 2 and min(len(c) for c in chunks) > 20 and max(len(c) for c in chunks) <= 60
