import time
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app import deps
from app.engine import CapitalMarketAssumptions
from app.rebalance import RebalanceSettings, propose_rebalance
from app.services import load_account_portfolio, run_portfolio_simulation
from app.video import VideoGenAgent, VideoJobManager, build_scenes
from app.video.render import build_audio, loudness
from app.voice import DISCLAIMER
from tests.test_voice import FakeEngine


@pytest.fixture
def setup():
    sources = deps.get_sources()
    cma = CapitalMarketAssumptions.load("config/capital_market_assumptions.json")
    settings = RebalanceSettings.load("config/rebalance.json")
    pf = load_account_portfolio(sources, "A1001")
    run = lambda w: run_portfolio_simulation(pf, cma, w, trials=1000, seed=42)  # noqa: E731
    return sources, cma, settings, pf, run(pf.current_weights), run(pf.model.weights), run


def _plan(pf):
    a = pf.account
    return {"retirement_age": a.retirement_age, "plan_end_age": a.plan_end_age}


def test_scenes_use_engine_figures_and_end_with_disclaimer(client, setup):
    _, _, settings, pf, cur, mod, run = setup
    proposal = propose_rebalance("A1001", pf.positions, pf.model, settings)
    after = run(proposal.post_trade_weights).success_probability
    scenes = build_scenes(pf, cur, mod, _plan(pf), proposal, after, today=date(2026, 10, 27))
    assert [s.kind for s in scenes] == ["title", "success", "fan", "allocation", "outcomes", "rebalance", "closing"]
    text = " ".join(s.narration for s in scenes)
    assert f"{cur.success_probability * 100:.1f}%" in text and f"{mod.success_probability * 100:.1f}%" in text
    assert f"{after * 100:.1f}%" in text and "US Bonds" in text
    assert scenes[0].data["date"] == "October 27, 2026" and "Hello Jane" in scenes[0].narration
    assert scenes[-1].narration.endswith(DISCLAIMER)


def test_rebalance_scene_is_optional(client, setup):
    _, _, _, pf, cur, mod, _ = setup
    assert "rebalance" not in [s.kind for s in build_scenes(pf, cur, mod, _plan(pf))]


def test_audio_timeline_and_subtitles(client, setup):
    _, _, _, pf, cur, mod, _ = setup
    scenes = build_scenes(pf, cur, mod, _plan(pf))
    engine = FakeEngine()
    samples, rate, timeline = build_audio(scenes, engine)
    assert len(timeline) == len(scenes) and len(engine.texts) == len(scenes)
    assert all("%" not in t and "$" not in t for t in engine.texts)  # spoken form
    assert timeline[1].start == pytest.approx(timeline[0].start + timeline[0].duration)
    assert timeline[1].subtitles[0][2].startswith("We tested your plan")
    assert len(samples) / rate == pytest.approx(sum(t.duration for t in timeline), abs=0.01)
    env = loudness(samples, rate, 30)
    assert env.min() >= 0 and env.max() <= 1


def test_render_produces_mp4_with_audio(client, setup, tmp_path):
    from app.video.render import render_video

    _, _, _, pf, cur, mod, _ = setup
    scenes = build_scenes(pf, cur, mod, _plan(pf))[:2]
    out = tmp_path / "v.mp4"
    seconds = render_video(scenes, FakeEngine(), "Alex Morgan", "Jane Smith", out, fps=10)
    data = out.read_bytes()
    assert data[4:8] == b"ftyp" and len(data) > 10_000
    assert seconds == pytest.approx(2 * (0.6 + 2.0 + 0.8), abs=0.05)


def _fake_renderer(scenes, engine, advisor, client_name, out: Path, on_progress=None):
    if on_progress:
        on_progress(0.5)
    out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    return 12.0


def test_agent_and_job_manager(client, setup):
    sources, cma, settings, *_ = setup
    agent = VideoGenAgent(FakeEngine(), sources, cma, settings, renderer=_fake_renderer)
    clip = agent.create({"account_id": "A1001", "trials": 500, "include_rebalance": False})
    assert clip.client_name == "Jane Smith" and clip.file_name.startswith("A1001_plan_update_")
    assert clip.file_name.endswith(".mp4") and "rebalance" not in clip.scenes
    jobs = VideoJobManager(agent)
    job = jobs.submit({"account_id": "A1001", "trials": 500})
    for _ in range(100):
        if jobs.get(job.job_id).status in ("done", "error"):
            break
        time.sleep(0.05)
    done = jobs.get(job.job_id)
    assert done.status == "done" and done.progress == 1.0
    assert jobs.video(done.video.video_id).data.startswith(b"\x00\x00\x00\x18ftyp")
    bad = jobs.submit({"account_id": "ZZZ"})
    for _ in range(100):
        if jobs.get(bad.job_id).status == "error":
            break
        time.sleep(0.05)
    assert "Unknown account" in jobs.get(bad.job_id).message


@pytest.fixture
def video_client(client, setup):
    sources, cma, settings, *_ = setup
    jobs = VideoJobManager(VideoGenAgent(FakeEngine(), sources, cma, settings, renderer=_fake_renderer))
    client.app.dependency_overrides[deps.get_video_jobs] = lambda: jobs
    return client


def test_video_endpoints(video_client):
    r = video_client.post("/api/video", json={"account_id": "A1001", "trials": 500})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(100):
        body = video_client.get(f"/api/video/jobs/{job_id}").json()
        if body["status"] == "done":
            break
        time.sleep(0.05)
    assert body["video"]["url"].startswith("/video/")
    mp4 = video_client.get(f"/api{body['video']['url']}", params={"download": True})
    assert mp4.headers["content-type"] == "video/mp4"
    assert "attachment" in mp4.headers["content-disposition"] and ".mp4" in mp4.headers["content-disposition"]
    assert video_client.post("/api/video", json={"account_id": "ZZZ"}).status_code == 404
    assert video_client.post("/api/video", json={"account_id": "A1001", "trials": 30_000}).status_code == 422
    assert video_client.get("/api/video/jobs/nope").status_code == 404
    assert video_client.get("/api/video/nope").status_code == 404


def test_technical_indicator_video_uses_page_context_without_simulation(video_client, setup):
    points = [{
        "date": f"2026-{month:02d}-01",
        "close": 100 + month,
        "rsi": 55 + month / 10,
        "macd": 1.2 + month / 100,
        "macd_signal": 1.0 + month / 100,
        "bollinger_upper": 110 + month,
        "bollinger_lower": 90 + month,
    } for month in range(1, 13)]
    response = video_client.post("/api/video", json={
        "page_context": {
            "kind": "technical_indicators",
            "title": "Technical Indicators",
            "data_label": "sample-price-history.csv",
            "latest_date": points[-1]["date"],
            "close": points[-1]["close"],
            "rsi": points[-1]["rsi"],
            "macd": points[-1]["macd"],
            "macd_signal": points[-1]["macd_signal"],
            "bollinger_upper": points[-1]["bollinger_upper"],
            "bollinger_lower": points[-1]["bollinger_lower"],
            "series": points,
        },
    })
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    for _ in range(100):
        body = video_client.get(f"/api/video/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert body["account_id"] is None
    assert body["video"]["client_name"] == "Technical Indicators"
    assert body["video"]["account_id"] is None
    assert body["video"]["scenes"] == [
        "indicator_title", "indicator_chart", "indicator_chart", "indicator_chart", "indicator_closing",
    ]


def test_chat_starts_video_job(client, setup):
    from langchain_core.messages import AIMessage
    from tests.test_chat import _cache, _call

    sources, cma, settings, *_ = setup
    jobs = VideoJobManager(VideoGenAgent(FakeEngine(), sources, cma, settings, renderer=_fake_renderer))
    cache = _cache([_call("create_investor_video", {"account_id": "A1001"}),
                    AIMessage(content="Your video is being created.")], video_jobs=jobs)
    client.app.dependency_overrides[deps.get_agent_cache] = lambda: cache
    body = client.post("/api/chat", json={"message": "Make a video for Jane", "thread_id": "v1",
                                          "provider": "ollama"}).json()
    assert len(body["video_jobs"]) == 1 and body["video_jobs"][0]["account_id"] == "A1001"
    assert np.isfinite(body["video_jobs"][0]["progress"])
