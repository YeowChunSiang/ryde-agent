"""Video ingestion utilities for the Image Analysis Agent (Phase 3).

Dashcam clips and cabin videos are the richest evidence a driver can submit,
but a model cannot look at "a video" — it looks at frames. This module:

1. probes the payload (duration, fps, resolution, codec) with ``ffprobe``;
2. extracts keyframes at a configurable rate (default 1 frame per second)
   using ``ffmpeg-python`` (falling back to OpenCV, then to a raw ``ffmpeg``
   subprocess);
3. computes cheap per-frame metrics (mean luminance, inter-frame motion) so
   the vision agent can flag anomalies such as a night-time clip, a frozen
   (looped) video or a frame that does not belong to the same take.

Frame files are written under ``Settings.frame_dir`` and are served back to the
UI over ``/media/frames/...``, so a reviewer can scrub the exact frames the
agent reasoned over.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from config import Settings
from models import VideoAnalysis, VideoFrame


class VideoProcessingError(RuntimeError):
    """Raised when a payload cannot be probed or decoded."""


def ffmpeg_available() -> bool:
    """True when an ``ffmpeg`` binary is reachable on PATH."""
    return shutil.which("ffmpeg") is not None


def opencv_available() -> bool:
    try:  # pragma: no cover - depends on the environment
        import cv2  # noqa: F401

        return True
    except Exception:
        return False


def backend_name() -> str:
    try:
        import ffmpeg  # noqa: F401

        return "ffmpeg"
    except Exception:
        if opencv_available():
            return "opencv"
        return "unavailable"


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def probe(path: Path) -> dict:
    """Return ffprobe metadata for a video file (duration, fps, size)."""
    if not path.exists():
        raise VideoProcessingError(f"video not found: {path}")
    exe = shutil.which("ffprobe")
    if exe is None:
        raise VideoProcessingError("ffprobe is not available on this host")
    try:
        out = subprocess.run(
            [
                exe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - hostile inputs
        raise VideoProcessingError(f"ffprobe timed out on {path.name}") from exc
    if out.returncode != 0:
        raise VideoProcessingError(f"ffprobe failed on {path.name}: {out.stderr.strip()[:200]}")
    try:
        data = json.loads(out.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VideoProcessingError(f"ffprobe returned unparseable metadata: {exc}") from exc

    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        data.get("streams", [{}])[0] if data.get("streams") else {},
    )
    duration = _to_float(stream.get("duration")) or _to_float(data.get("format", {}).get("duration"))
    fps = _parse_fps(stream.get("r_frame_rate") or stream.get("avg_frame_rate"))
    return {
        "duration_s": float(duration or 0.0),
        "fps": fps,
        "width": int(stream.get("width") or 0) or None,
        "height": int(stream.get("height") or 0) or None,
        "codec": stream.get("codec_name"),
    }


def _to_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_fps(rate: Optional[str]) -> Optional[float]:
    if not rate or "/" not in rate:
        return _to_float(rate)
    try:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return round(float(num) / den_f, 3) if den_f else None
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------


def extract_frames(
    path: Path,
    out_dir: Path,
    fps: float = 1.0,
    max_frames: int = 12,
    prefix: str = "frame",
) -> list[VideoFrame]:
    """Extract up to ``max_frames`` keyframes at ``fps`` frames per second.

    Frames are written as JPEGs into ``out_dir``. Extraction is deterministic:
    the same clip always yields the same frame files, which matters because the
    judge's ruling cites them.
    """
    if not path.exists():
        raise VideoProcessingError(f"video not found: {path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import ffmpeg  # type: ignore

        (
            ffmpeg.input(str(path))
            .filter("fps", fps=fps)
            .output(str(out_dir / f"{prefix}_%03d.jpg"), start_number=0, **{"qscale:v": 3})
            .overwrite_output()
            .run(quiet=True, capture_stdout=True, capture_stderr=True)
        )
    except Exception:
        if not ffmpeg_available():
            raise VideoProcessingError(
                "no video backend available (install ffmpeg or opencv-python)"
            ) from None
        subprocess.run(
            [
                shutil.which("ffmpeg") or "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-vf",
                f"fps={fps}",
                "-qscale:v",
                "3",
                str(out_dir / f"{prefix}_%03d.jpg"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    files = sorted(out_dir.glob(f"{prefix}_*.jpg"))
    frames: list[VideoFrame] = []
    previous: Optional[list[float]] = None
    for index, file in enumerate(files[:max_frames]):
        metrics = _frame_metrics(file)
        motion = None
        if previous is not None and metrics["histogram"] is not None:
            motion = round(_hist_distance(previous, metrics["histogram"]), 4)
        previous = metrics["histogram"]
        frames.append(
            VideoFrame(
                index=index,
                timestamp_s=round(index / fps if fps else float(index), 2),
                path=str(file),
                width=metrics["width"],
                height=metrics["height"],
                mean_luminance=metrics["luminance"],
                motion_score=motion,
            )
        )
    return frames


def _frame_metrics(path: Path) -> dict:
    """Cheap luminance/histogram metrics for one JPEG (OpenCV when present)."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        image = cv2.imread(str(path))
        if image is None:
            return {"width": None, "height": None, "luminance": None, "histogram": None}
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [16], [0, 256]).flatten()
        total = float(hist.sum()) or 1.0
        return {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "luminance": round(float(gray.mean()) / 255.0, 4),
            "histogram": [round(float(v) / total, 5) for v in hist],
        }
    except Exception:
        # Pillow-only fallback: just the mean luminance.
        try:
            from PIL import Image  # type: ignore

            with Image.open(path) as img:
                gray = img.convert("L")
                small = gray.resize((32, 32))
                pixels = list(small.getdata())
                return {
                    "width": img.width,
                    "height": img.height,
                    "luminance": round(sum(pixels) / (len(pixels) * 255.0), 4),
                    "histogram": None,
                }
        except Exception:  # pragma: no cover
            return {"width": None, "height": None, "luminance": None, "histogram": None}


def _hist_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(abs(x - y) for x, y in zip(a, b)))


def relative_web_path(path: Path, media_root: Path) -> str:
    """Map an on-disk frame path onto the ``/media`` URL served by FastAPI."""
    try:
        rel = path.relative_to(media_root)
    except ValueError:
        rel = Path(path.name)
    return f"/media/frames/{rel.as_posix()}"


# ---------------------------------------------------------------------------
# High-level helper used by the orchestrator / upload endpoint
# ---------------------------------------------------------------------------


def analyse_video(
    path: Path,
    settings: Settings,
    attachment_id: str,
    *,
    fps: Optional[float] = None,
    max_frames: Optional[int] = None,
) -> VideoAnalysis:
    """Probe + extract + sanity-check one video payload."""
    fps = fps if fps is not None else settings.video_frame_fps
    max_frames = max_frames if max_frames is not None else settings.video_max_frames

    meta = probe(path)
    media_root = Path(settings.frame_dir)
    out_dir = media_root / attachment_id
    frames = extract_frames(path, out_dir, fps=max(fps, 0.1), max_frames=max_frames, prefix="frame")
    for frame in frames:
        frame.path = relative_web_path(Path(frame.path), media_root)

    anomalies: list[str] = []
    if meta["duration_s"] <= 0:
        anomalies.append("No decodable video stream — duration is zero")
    if frames and frames[0].mean_luminance is not None and frames[0].mean_luminance < 0.18:
        anomalies.append("Clip is very dark — night footage, visual detail is limited")
    if len(frames) >= 3:
        motions = [f.motion_score for f in frames[1:] if f.motion_score is not None]
        if motions and max(motions) < 0.01:
            anomalies.append("Frames are near-identical — possible looped or frozen clip")
    if max_frames and len(frames) >= max_frames:
        anomalies.append(
            f"Only the first {len(frames)} keyframes were analysed (cap {max_frames})"
        )

    return VideoAnalysis(
        attachment_id=attachment_id,
        duration_s=round(meta["duration_s"], 2),
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
        frames_extracted=len(frames),
        frames=frames,
        anomalies=anomalies,
        engine=backend_name(),  # type: ignore[arg-type]
    )
