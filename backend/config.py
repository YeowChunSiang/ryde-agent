"""Runtime configuration for the RydeResolve dispute resolution backend.

Configuration is read from environment variables (12-factor) with sane defaults so
the service boots with zero setup. When no Tencent Cloud ADP ``AppKey`` is present
the orchestrator transparently falls back to the deterministic offline reasoner,
which keeps the system demoable in an air-gapped hackathon environment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

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
        default=0.65,
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
            os.getenv("CONFIDENCE_ESCALATION_THRESHOLD", "0.65")
        ),
        offline_demo_pacing_ms=float(os.getenv("OFFLINE_DEMO_PACING_MS", "220")),
        auto_escalate_dispute_types=_env_tuple(
            "AUTO_ESCALATE_DISPUTE_TYPES", ("safety_incident",)
        ),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "3000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
