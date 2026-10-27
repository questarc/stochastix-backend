"""Render scenes + narration into an MP4 (H.264 video, AAC audio)."""
from __future__ import annotations

import io
import re
import tempfile
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..voice.engine import SpeechEngine
from ..voice.script import speakable
from .avatar import MOUTH_LEVELS, avatar_badge
from .layout import AVATAR, BAR_Y, H, SUB_X, W, advisor_bar, background, header, progress_bar, subtitle_image
from .narration import Scene
from .scenes import draw_scene

LEAD, TAIL = 0.6, 0.8      # seconds of silence before and after each scene's narration
FADE = 0.5                 # fade in/out of the whole video
DEFAULT_FPS = 30


@dataclass
class Timeline:
    scene: Scene
    start: float
    duration: float
    subtitles: list[tuple[float, float, str]]


def _read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip()) if s]


def build_audio(scenes: list[Scene], engine: SpeechEngine) -> tuple[np.ndarray, int, list[Timeline]]:
    chunks, timeline, t, rate = [], [], 0.0, 22050
    for scene in scenes:
        samples, rate = _read_wav(engine.synthesize(speakable(scene.narration)))
        speech = len(samples) / rate
        sents = _sentences(scene.narration)
        weights = np.array([len(speakable(s)) for s in sents], float)
        bounds = np.concatenate([[0], np.cumsum(weights / weights.sum() * speech)])
        subs = [(t + LEAD + bounds[i], t + LEAD + bounds[i + 1], s) for i, s in enumerate(sents)]
        silence = lambda sec: np.zeros(int(sec * rate), np.int16)  # noqa: E731
        chunks += [silence(LEAD), samples, silence(TAIL)]
        duration = LEAD + speech + TAIL
        timeline.append(Timeline(scene, t, duration, subs))
        t += duration
    return np.concatenate(chunks), rate, timeline


def loudness(samples: np.ndarray, rate: int, fps: int) -> np.ndarray:
    """Per-frame loudness 0..1, used to animate the advisor's mouth."""
    hop = rate / fps
    n = max(1, int(np.ceil(len(samples) / hop)))
    x = samples.astype(np.float32)
    rms = np.array([np.sqrt(np.mean(x[int(i * hop):int((i + 1) * hop)] ** 2)) if int(i * hop) < len(x) else 0.0
                    for i in range(n)])
    ref = float(np.percentile(rms, 95))
    if ref < 1.0:  # silence: keep the mouth closed
        return np.zeros(n)
    env = np.clip(rms / ref, 0, 1)
    return np.clip(np.convolve(env, np.ones(3) / 3, mode="same"), 0, 1)


@lru_cache(maxsize=128)
def _badge(level: int, blink: bool, glow_q: int) -> Image.Image:
    return avatar_badge(AVATAR, level, blink, glow_q / 7)


def render_video(scenes: list[Scene], engine: SpeechEngine, advisor: str, client: str, out_path: Path,
                 fps: int = DEFAULT_FPS, on_progress: Callable[[float], None] | None = None) -> float:
    import imageio_ffmpeg

    samples, rate, timeline = build_audio(scenes, engine)
    total = len(samples) / rate
    env = loudness(samples, rate, fps)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "narration.wav"
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(samples.tobytes())
        writer = imageio_ffmpeg.write_frames(
            str(out_path), (W, H), fps=fps, codec="libx264", quality=None, macro_block_size=16,
            output_params=["-crf", "18", "-preset", "medium", "-tune", "animation", "-movflags", "+faststart",
                           "-b:a", "160k", "-shortest"],
            audio_path=str(wav_path), audio_codec="aac", ffmpeg_log_level="error")
        writer.send(None)
        frames = int(total * fps)
        scene_index, statics, caches = 0, {}, {}
        for f in range(frames):
            now = f / fps
            while scene_index < len(timeline) - 1 and now >= timeline[scene_index + 1].start:
                scene_index += 1
            seg = timeline[scene_index]
            if scene_index not in statics:
                base = background().copy()
                header(base, seg.scene.title, client, scene_index + 1, len(timeline))
                statics[scene_index] = base
            frame = statics[scene_index].copy()
            draw_scene(frame, seg.scene, now - seg.start, caches.setdefault(scene_index, {}))
            advisor_bar(frame, advisor)
            e = float(env[min(f, len(env) - 1)])
            blink = (now % 3.7) < 0.14
            badge = _badge(int(round(e * (MOUTH_LEVELS - 1))), blink, int(round(e * 7)))
            frame.paste(badge, (26, BAR_Y + 8), badge)
            sub = next((s for a, b, s in seg.subtitles if a <= now < b + 0.25), "")
            if sub:
                si = subtitle_image(sub)
                frame.paste(si, (SUB_X, BAR_Y + 76), si)
            progress_bar(frame, now / total)
            fade = min(1.0, now / FADE, (total - now) / FADE)
            arr = np.asarray(frame, dtype=np.uint8)
            if fade < 1.0:
                arr = (arr.astype(np.float32) * max(fade, 0.0)).astype(np.uint8)
            writer.send(arr.tobytes())
            if on_progress and f % fps == 0:
                on_progress(f / frames)
        writer.close()
    return total
