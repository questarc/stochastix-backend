"""VideoGenAgent: a narrated investor video built from the simulation engine's results."""
from __future__ import annotations

import logging
import tempfile
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..engine import CapitalMarketAssumptions
from ..rebalance import RebalanceSettings, propose_rebalance
from ..services import load_account_portfolio, run_portfolio_simulation
from ..voice.engine import SpeechEngine
from .narration import build_scenes
from .render import render_video

logger = logging.getLogger(__name__)

MAX_VIDEOS = 10
MAX_VIDEO_TRIALS = 25_000
PLAN_KEYS = ("retirement_age", "plan_end_age", "annual_contribution", "annual_withdrawal")


@dataclass
class VideoClip:
    video_id: str
    account_id: str
    client_name: str
    duration_seconds: float
    scenes: list[str]
    created_at: str
    file_name: str
    data: bytes = field(repr=False)

    def to_dict(self) -> dict:
        return {"video_id": self.video_id, "account_id": self.account_id, "client_name": self.client_name,
                "duration_seconds": round(self.duration_seconds, 1), "scenes": self.scenes,
                "created_at": self.created_at, "file_name": self.file_name, "size_bytes": len(self.data),
                "url": f"/video/{self.video_id}"}


class VideoGenAgent:
    def __init__(self, engine: SpeechEngine, sources: dict, cma: CapitalMarketAssumptions,
                 rebalance_settings: RebalanceSettings, renderer: Callable = render_video):
        self.engine, self.sources, self.cma = engine, sources, cma
        self.rebalance_settings, self.renderer = rebalance_settings, renderer

    def create(self, request: dict, on_progress: Callable[[float], None] | None = None) -> VideoClip:
        """``request`` uses SimulationRequest fields plus ``include_rebalance``."""
        portfolio = load_account_portfolio(self.sources, request["account_id"], request.get("model_id"))
        a = portfolio.account
        cma = self.cma.with_distribution(request["distribution"]) if request.get("distribution") else self.cma
        plan_in = {k: request.get(k) for k in PLAN_KEYS}
        sim = dict(trials=min(int(request.get("trials") or 10_000), MAX_VIDEO_TRIALS), seed=request.get("seed", 42),
                   sampling=request.get("sampling", "prng"), copula=request.get("copula", "gaussian"),
                   copula_df=request.get("copula_df", 5))
        run = lambda w: run_portfolio_simulation(portfolio, cma, w, **plan_in, **sim)  # noqa: E731
        current, model = run(portfolio.current_weights), run(portfolio.model.weights)
        proposal = after = None
        if request.get("include_rebalance", True):
            proposal = propose_rebalance(a.account_id, portfolio.positions, portfolio.model, self.rebalance_settings)
            after = run(proposal.post_trade_weights).success_probability if proposal.trades else current.success_probability
        plan = {k: (getattr(a, k) if plan_in[k] is None else plan_in[k]) for k in PLAN_KEYS}
        scenes = build_scenes(portfolio, current, model, plan, proposal, after)
        if on_progress:
            on_progress(0.05)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "video.mp4"
            report = (lambda p: on_progress(0.05 + 0.95 * p)) if on_progress else None
            duration = self.renderer(scenes, self.engine, a.advisor, a.client_name, out, on_progress=report)
            data = out.read_bytes()
        now = datetime.now(timezone.utc)
        clip = VideoClip(uuid.uuid4().hex, a.account_id, a.client_name, duration, [s.kind for s in scenes],
                         now.isoformat(), f"{a.account_id}_plan_update_{now.strftime('%Y%m%d_%H%M%S')}.mp4", data)
        logger.info("Video account=%s seconds=%.1f bytes=%d seed=%s", a.account_id, duration, len(data), sim["seed"])
        return clip


@dataclass
class VideoJob:
    job_id: str
    account_id: str
    status: str = "queued"          # queued | rendering | done | error
    progress: float = 0.0
    message: str = "Waiting to start…"
    video: VideoClip | None = None

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "account_id": self.account_id, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message,
                "video": self.video.to_dict() if self.video else None}


class VideoJobManager:
    """Renders videos in the background (one at a time) and keeps the newest results in memory."""

    def __init__(self, agent: VideoGenAgent, workers: int = 1, max_videos: int = MAX_VIDEOS):
        self.agent = agent
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="video")
        self._jobs: OrderedDict[str, VideoJob] = OrderedDict()
        self._max = max_videos
        self._lock = threading.Lock()

    def submit(self, request: dict) -> VideoJob:
        job = VideoJob(uuid.uuid4().hex, request["account_id"])
        with self._lock:
            self._jobs[job.job_id] = job
            while len(self._jobs) > self._max * 2:
                self._jobs.popitem(last=False)
        self._pool.submit(self._run, job, request)
        return job

    def _run(self, job: VideoJob, request: dict) -> None:
        def progress(p: float) -> None:
            job.progress = min(p, 0.99)
            job.message = "Rendering video…" if p > 0.05 else "Running simulations and writing narration…"
        job.status, job.message = "rendering", "Running simulations and writing narration…"
        try:
            job.video = self.agent.create(request, progress)
            job.status, job.progress, job.message = "done", 1.0, "Video ready."
        except Exception as exc:  # reported to the user through the job status
            logger.exception("Video job %s failed", job.job_id)
            job.status, job.message = "error", str(exc.args[0]) if exc.args else str(exc)
        with self._lock:
            done = [j for j in self._jobs.values() if j.video]
            for old in done[:-self._max]:
                old.video = None

    def get(self, job_id: str) -> VideoJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def video(self, video_id: str) -> VideoClip | None:
        with self._lock:
            return next((j.video for j in self._jobs.values() if j.video and j.video.video_id == video_id), None)
