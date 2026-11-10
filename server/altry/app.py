"""HTTP API used by the Android app. Run with:  uvicorn altry.app:app --host 0.0.0.0 --port 8000"""
import hmac
import mimetypes
from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import config, engines, pipeline, voices
from .jobs import Job, JobManager

config.ensure_dirs()
manager = JobManager()


def require_token(x_altry_token: str = Header(default="")):
    if config.TOKEN and not hmac.compare_digest(x_altry_token.encode(), config.TOKEN.encode()):
        raise HTTPException(401, "Geçersiz erişim anahtarı / invalid token")


app = FastAPI(title="Altry", version=config.VERSION)
api = FastAPI(dependencies=[Depends(require_token)])


@api.exception_handler(voices.VoiceError)
@api.exception_handler(pipeline.PipelineError)
async def bad_request(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def save_upload(upload: UploadFile, dst_dir: Path, stem: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()[:8]
    dst = dst_dir / f"{stem}{suffix if suffix.replace('.', '').isalnum() else ''}"
    limit, size = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    with open(dst, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, f"Dosya çok büyük (en fazla {config.MAX_UPLOAD_MB} MB)")
            f.write(chunk)
    if size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, "Boş dosya / empty file")
    return dst


def job_view(job: Job) -> dict:
    return {"id": job.id, "type": job.type, "title": job.title, "status": job.status,
            "progress": job.progress, "stage": job.stage, "created": job.created,
            "finished": job.finished, "error": job.error, "result": job.result, "extras": job.extras}


def check_language(code: str) -> str:
    if code not in config.LANGUAGES:
        raise HTTPException(400, "Desteklenmeyen dil / unsupported language")
    return code


def check_voice(voice_id: str, allow_original: bool = False) -> str:
    if not (allow_original and voice_id == pipeline.ORIGINAL):
        voices.wav_path(voice_id)
    return voice_id


def get_job(job_id: str) -> Job:
    job = manager.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "İş bulunamadı / job not found")
    return job


def launch(job: Job, fn, **kwargs) -> dict:
    return job_view(manager.start(job, partial(fn, **kwargs)))


def new_job_with_upload(type_: str, upload: UploadFile) -> tuple[Job, Path]:
    job = manager.new_job(type_, upload.filename or type_)
    try:
        return job, save_upload(upload, job.dir, "input")
    except HTTPException:
        manager.discard(job)
        raise


# ---------------------------------------------------------------- info

@api.get("/health")
def health():
    return {"ok": True, "name": "altry", "version": config.VERSION, "engines": engines.status(),
            "limits": {"upload_mb": config.MAX_UPLOAD_MB, "minutes": config.MAX_MEDIA_MINUTES}}


@api.get("/languages")
def languages():
    return [{"code": code, "name": name} for code, name in config.LANGUAGES.items()]


# ---------------------------------------------------------------- voices

@api.get("/voices")
def list_voices():
    return voices.list_voices()


@api.post("/voices")
def add_voice(name: str = Form(...), consent: bool = Form(False), language: str = Form(""),
              file: UploadFile = File(...)):
    """Clone a voice from a recording. `consent` confirms the speaker agreed to it."""
    if not consent:
        raise HTTPException(400, "Sesin sahibi olduğunuzu veya izniniz olduğunu onaylayın / consent required")
    tmp = save_upload(file, config.VOICES_DIR, "upload_tmp")
    try:
        return voices.add_from_file(tmp, name, language=language)
    finally:
        tmp.unlink(missing_ok=True)


@api.post("/voices/from-url")
def add_voice_from_url(name: str = Form(...), url: str = Form(...), consent: bool = Form(False),
                       language: str = Form("")):
    if not consent:
        raise HTTPException(400, "Sesi kullanma izniniz olduğunu onaylayın / consent required")
    return voices.add_from_url(url, name, language=language)


@api.get("/voices/catalog")
def voice_catalog():
    return voices.catalog()


@api.post("/voices/catalog/{item_id}")
def install_catalog_voice(item_id: str):
    return voices.install_from_catalog(item_id)


@api.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str):
    return FileResponse(voices.wav_path(voice_id), media_type="audio/wav")


@api.delete("/voices/{voice_id}")
def delete_voice(voice_id: str):
    voices.delete(voice_id)
    return {"ok": True}


# ---------------------------------------------------------------- jobs

@api.post("/jobs/dub")
def create_dub(file: UploadFile = File(...), target_lang: str = Form(...), source_lang: str = Form(""),
               voice_id: str = Form(pipeline.ORIGINAL), keep_background: bool = Form(True),
               subtitles: bool = Form(False), expressiveness: float = Form(0.5)):
    check_language(target_lang), check_voice(voice_id, allow_original=True)
    job, src = new_job_with_upload("dub", file)
    return launch(job, pipeline.dub, src=src, target_lang=target_lang, source_lang=source_lang,
                  voice_id=voice_id, keep_background=keep_background, subtitles=subtitles,
                  expressiveness=expressiveness)


@api.post("/jobs/voice-change")
def create_voice_change(file: UploadFile = File(...), voice_id: str = Form(...),
                        keep_background: bool = Form(True)):
    check_voice(voice_id)
    job, src = new_job_with_upload("voice-change", file)
    return launch(job, pipeline.change_voice, src=src, voice_id=voice_id, keep_background=keep_background)


@api.post("/jobs/speak")
def create_speech(text: str = Form(...), language: str = Form(...), voice_id: str = Form(...),
                  expressiveness: float = Form(0.5), original_volume: float = Form(0.0),
                  file: UploadFile | None = File(None)):
    """Text to speech with a library voice. With a video attached, the speech is put on the video."""
    check_language(language), check_voice(voice_id)
    if not text.strip():
        raise HTTPException(400, "Metin boş / empty text")
    if file is None:
        job = manager.new_job("speak", text.strip())
        return launch(job, pipeline.speak, text=text, language=language, voice_id=voice_id,
                      expressiveness=expressiveness)
    job, src = new_job_with_upload("narrate", file)
    return launch(job, pipeline.narrate, src=src, text=text, language=language, voice_id=voice_id,
                  original_volume=original_volume, expressiveness=expressiveness)


@api.post("/jobs/create-video")
def create_video(script: str = Form(...), language: str = Form(...), voice_id: str = Form(...),
                 aspect: str = Form("9:16"), subtitles: bool = Form(True), expressiveness: float = Form(0.5),
                 images: list[UploadFile] = File(default=[]), music: UploadFile | None = File(None),
                 auto_images: bool = Form(False), image_query: str = Form("")):
    """Script to video. Without uploaded images, `auto_images` finds pictures on the internet:
    about `image_query` when given, otherwise matching each scene's own words."""
    check_language(language), check_voice(voice_id)
    if not script.strip():
        raise HTTPException(400, "Metin boş / empty script")
    if aspect not in pipeline.SIZES:
        raise HTTPException(400, "Geçersiz en-boy oranı / invalid aspect ratio")
    job = manager.new_job("create-video", script.strip())
    try:
        image_paths = [save_upload(image, job.dir, f"input_image_{i}") for i, image in enumerate(images[:40])]
        music_path = save_upload(music, job.dir, "input_music") if music else None
    except HTTPException:
        manager.discard(job)
        raise
    return launch(job, pipeline.create_video, script=script, language=language, voice_id=voice_id,
                  images=image_paths, aspect=aspect, subtitles=subtitles, music=music_path,
                  expressiveness=expressiveness, auto_images=auto_images, image_query=image_query[:120])


@api.get("/jobs")
def list_jobs():
    return [job_view(job) for job in manager.list()]


@api.get("/jobs/{job_id}")
def job_status(job_id: str):
    return job_view(get_job(job_id))


@api.get("/jobs/{job_id}/result")
def job_result(job_id: str, extra: str = ""):
    job = get_job(job_id)
    if job.status != "done":
        raise HTTPException(409, "İş henüz bitmedi / job not finished")
    name = job.extras.get(extra) if extra else job.result
    if not isinstance(name, str) or not (job.dir / name).is_file():
        raise HTTPException(404, "Dosya yok / no such file")
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(job.dir / name, media_type=mime, filename=name)


@api.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    get_job(job_id)
    manager.delete(job_id)
    return {"ok": True}


app.mount("/api", api)


@app.get("/")
def root():
    return {"name": "altry", "version": config.VERSION, "docs": "/api/docs"}
