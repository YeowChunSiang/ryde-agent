"""Runtime configuration for the RydeResolve dispute resolution backend.

Configuration is read from environment variables (12-factor) with sane defaults so
the service boots with zero setup. When no Tencent Cloud ADP ``AppKey`` is present
the orchestrator transparently falls back to the deterministic offline reasoner,
which keeps the system demoable in an air-gapped hackathon environment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _load_dotenv() -> None:
    """Load a local .env if python-dotenv is installed (optional dependency)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


class Settings(BaseModel):
    """Application settings."""

    # --- Tencent Cloud ADP -------------------------------------------------
    adp_app_key: str = Field(default="", description="ADP application AppKey")
    adp_endpoint: str = Field(
        default="https://wss.lke.tencentcloud.com/adp/v2/chat",
        description="ADP chat endpoint (HTTP SSE)",
    )
    adp_visitor_id_prefix: str = Field(default="ryderesolve")
    adp_timeout_s: float = Field(default=60.0)
    adp_max_retries: int = Field(default=1)

    # --- Engine behaviour --------------------------------------------------
    engine_mode: Literal["auto", "adp", "offline"] = Field(
        default="auto",
        description="auto = use ADP when a key exists, else offline reasoner",
    )
    confidence_escalation_threshold: float = Field(
        default=0.70,
        description="Rulings below this confidence are escalated to a human reviewer",
    )
    offline_demo_pacing_ms: float = Field(
        default=220.0,
        description=(
            "Artificial delay between agent steps when running the offline reasoner. "
            "Offline rulings take ~50 ms, which makes the SSE stream impossible to watch "
            "in a live demo. Set to 0 for unthrottled operation. Ignored in ADP mode, "
            "where real model latency already paces the stream."
        ),
    )
    auto_escalate_dispute_types: tuple[str, ...] = Field(
        default=("safety_incident",),
        description="Dispute categories that always require a human reviewer",
    )

    # --- SLA & Routing Manager ---------------------------------------------
    sla_high_value_threshold: float = Field(
        default=50.0,
        description="Claimed amount (SGD) above which a ticket is promoted to HIGH priority",
    )

    # --- Evidence Collection Agent ------------------------------------------
    collection_simulate_latency: bool = Field(
        default=True, description="Sleep to emulate upstream API round-trips"
    )
    collection_base_latency_ms: int = Field(default=40)
    collection_jitter_ms: int = Field(default=90)

    # --- Policy & Precedent Agent (mock RAG) ---------------------------------
    precedent_top_k: int = Field(
        default=2, description="Number of analogous precedents retrieved per dispute"
    )
    precedent_store_path: Optional[Path] = Field(
        default=None,
        description="JSON file backing the precedent knowledge base (survives restarts)",
    )

    # --- Multi-modal ingestion (Phase 3) -----------------------------------
    trtc_asr_endpoint: str = Field(
        default="https://trtc.tencentcloudapi.com",
        description="Tencent Cloud TRTC ASR endpoint used by trtc_client.py",
    )
    trtc_secret_id: str = Field(
        default="", description="TRTC/ASR SecretId; empty = simulated transcription"
    )
    trtc_secret_key: str = Field(
        default="", description="TRTC/ASR SecretKey; empty = simulated transcription"
    )
    trtc_app_id: str = Field(default="", description="TRTC SdkAppId for the ASR task")
    trtc_timeout_s: float = Field(default=30.0)

    media_dir: Path = Field(
        default=Path("data/uploads"),
        description="Where /upload-audio and /upload-video persist raw payloads",
    )
    frame_dir: Path = Field(
        default=Path("data/frames"),
        description="Where vision_utils.py writes extracted video keyframes",
    )
    video_frame_fps: float = Field(
        default=1.0, description="Keyframes extracted per second of video evidence"
    )
    video_max_frames: int = Field(
        default=12, description="Hard cap on keyframes analysed per video attachment"
    )

    # --- Service -----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 3000
    log_level: str = "info"

    @property
    def adp_configured(self) -> bool:
        return bool(self.adp_app_key.strip())


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""
    _load_dotenv()
    return Settings(
        adp_app_key=os.getenv("ADP_APP_KEY", "").strip(),
        adp_endpoint=os.getenv(
            "ADP_ENDPOINT", "https://wss.lke.tencentcloud.com/adp/v2/chat"
        ),
        adp_visitor_id_prefix=os.getenv("ADP_VISITOR_ID_PREFIX", "ryderesolve"),
        adp_timeout_s=float(os.getenv("ADP_TIMEOUT_S", "60")),
        adp_max_retries=int(os.getenv("ADP_MAX_RETRIES", "1")),
        engine_mode=os.getenv("ENGINE_MODE", "auto"),  # type: ignore[arg-type]
        confidence_escalation_threshold=float(
            os.getenv("CONFIDENCE_ESCALATION_THRESHOLD", "0.70")
        ),
        offline_demo_pacing_ms=float(os.getenv("OFFLINE_DEMO_PACING_MS", "220")),
        auto_escalate_dispute_types=_env_tuple(
            "AUTO_ESCALATE_DISPUTE_TYPES", ("safety_incident",)
        ),
        sla_high_value_threshold=float(os.getenv("SLA_HIGH_VALUE_THRESHOLD", "50")),
        collection_simulate_latency=os.getenv("COLLECTION_SIMULATE_LATENCY", "1") not in (
            "0",
            "false",
            "False",
        ),
        collection_base_latency_ms=int(os.getenv("COLLECTION_BASE_LATENCY_MS", "40")),
        collection_jitter_ms=int(os.getenv("COLLECTION_JITTER_MS", "90")),
        precedent_top_k=int(os.getenv("PRECEDENT_TOP_K", "2")),
        precedent_store_path=Path(
            os.getenv(
                "PRECEDENT_STORE_PATH",
                str(Path(__file__).resolve().parent / "data" / "precedents.json"),
            )
        ),
        trtc_asr_endpoint=os.getenv(
            "TRTC_ASR_ENDPOINT", "https://trtc.tencentcloudapi.com"
        ),
        trtc_secret_id=os.getenv("TRTC_SECRET_ID", "").strip(),
        trtc_secret_key=os.getenv("TRTC_SECRET_KEY", "").strip(),
        trtc_app_id=os.getenv("TRTC_APP_ID", "").strip(),
        trtc_timeout_s=float(os.getenv("TRTC_TIMEOUT_S", "30")),
        media_dir=Path(
            os.getenv("MEDIA_DIR", str(Path(__file__).resolve().parent / "data" / "uploads"))
        ),
        frame_dir=Path(
            os.getenv("FRAME_DIR", str(Path(__file__).resolve().parent / "data" / "frames"))
        ),
        video_frame_fps=float(os.getenv("VIDEO_FRAME_FPS", "1")),
        video_max_frames=int(os.getenv("VIDEO_MAX_FRAMES", "12")),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "3000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
