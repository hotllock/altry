"""A small persistent job queue. One worker: the models are heavy and not thread safe."""
import json
import queue
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config


class Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    type: str
    title: str
    status: str = "queued"  # queued | running | done | error | cancelled
    progress: float = 0.0
    stage: str = "Sırada"
    created: float = field(default_factory=time.time)
    finished: float | None = None
    error: str | None = None
    result: str | None = None  # file name inside the job directory
    extras: dict = field(default_factory=dict)  # e.g. {"srt": "subtitles.srt"}

    @property
    def dir(self) -> Path:
        return config.JOBS_DIR / self.id

    def save(self) -> None:
        (self.dir / "job.json").write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")


class Context:
    """Handed to the pipeline function: scratch space plus progress reporting."""

    def __init__(self, job: Job, manager: "JobManager"):
        self.job, self._manager = job, manager
        self.dir = job.dir
        self.work = job.dir / "work"
        self.work.mkdir(parents=True, exist_ok=True)

    def progress(self, fraction: float, stage: str | None = None) -> None:
        if self.job.id in self._manager.cancel_requests:
            raise Cancelled()
        self.job.progress = round(min(max(fraction, 0.0), 1.0), 3)
        if stage:
            self.job.stage = stage
        self.job.save()


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.cancel_requests: set[str] = set()
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._load()
        threading.Thread(target=self._worker, daemon=True, name="altry-worker").start()

    def _load(self) -> None:
        for path in config.JOBS_DIR.glob("*/job.json"):
            try:
                job = Job(**json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, TypeError):
                continue
            if job.status in ("queued", "running"):  # server restarted mid-job
                job.status, job.error, job.stage = "error", "Sunucu yeniden başlatıldı", "Hata"
                job.finished = time.time()
                job.save()
            self.jobs[job.id] = job

    def new_job(self, type_: str, title: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], type=type_, title=title[:80])
        job.dir.mkdir(parents=True)
        job.save()
        with self._lock:
            self.jobs[job.id] = job
        return job

    def discard(self, job: Job) -> None:
        """Drop a job that never got queued (e.g. its upload was rejected)."""
        with self._lock:
            self.jobs.pop(job.id, None)
        shutil.rmtree(job.dir, ignore_errors=True)

    def start(self, job: Job, fn) -> Job:
        """`fn(ctx)` must return (result_path_inside_job_dir, extras_dict)."""
        self._queue.put((job, fn))
        return job

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    def delete(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if job.status in ("queued", "running"):
            self.cancel_requests.add(job_id)
            if job.status == "queued":
                job.status, job.stage = "cancelled", "İptal edildi"
                job.save()
            return
        with self._lock:
            del self.jobs[job_id]
        shutil.rmtree(job.dir, ignore_errors=True)

    def _worker(self) -> None:
        while True:
            job, fn = self._queue.get()
            if job.id in self.cancel_requests:
                self.cancel_requests.discard(job.id)
                continue
            job.status, job.stage = "running", "Başlıyor"
            job.save()
            ctx = Context(job, self)
            try:
                result, extras = fn(ctx)
                job.result, job.extras = Path(result).name, extras or {}
                job.status, job.progress, job.stage = "done", 1.0, "Tamamlandı"
            except Cancelled:
                job.status, job.stage = "cancelled", "İptal edildi"
            except Exception as e:  # report every failure to the client instead of dying
                traceback.print_exc()
                job.status, job.stage = "error", "Hata"
                job.error = str(e)[:500] or type(e).__name__
            finally:
                self.cancel_requests.discard(job.id)
                job.finished = time.time()
                shutil.rmtree(ctx.work, ignore_errors=True)
                job.save()
