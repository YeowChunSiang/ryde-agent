"""Tencent Cloud TRTC Speech Recognition (ASR) client for audio evidence.

Ride-hailing safety disputes frequently hinge on a recording: an in-app
"safety recording" the platform captured, or a covert recording a passenger
made on their phone. This module turns that payload into a structured
transcript the rest of the pipeline can reason over.

Two implementations, chosen by configuration:

``TRTCASRClient``
    Calls the real Tencent Cloud TRTC ASR API (TC3-HMAC-SHA256 signed POST).
    Requires ``TRTC_SECRET_ID`` / ``TRTC_SECRET_KEY`` / ``TRTC_APP_ID``.

``SimulatedASRClient``
    Deterministic, offline transcription used when no credential is
    configured — the same philosophy as ``OfflineReasoner``: a hackathon demo
    (and a CI run) must never depend on a live credential.

Both return an :class:`AudioTranscript` that carries a ``hostility_score``,
``threat_detected`` and matched ``keywords``, so the Evidence Engine, the
Fraud & Bad-Faith Agent and the Judge can all weigh abusive or threatening
language without re-parsing raw text.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, Sequence, runtime_checkable

import httpx

from config import Settings
from models import AudioSegment, AudioTranscript, MediaAttachment

# ---------------------------------------------------------------------------
# Lexicons used for hostility / threat scoring
# ---------------------------------------------------------------------------

THREAT_PHRASES: tuple[str, ...] = (
    "i will kill",
    "i'll kill",
    "gonna kill",
    "i know where you live",
    "i will find you",
    "i'll find you",
    "break your",
    "hurt you",
    "beat you",
    "smash your",
    "kill you",
    "ruin you",
)

ABUSE_PHRASES: tuple[str, ...] = (
    "stupid",
    "idiot",
    "moron",
    "useless",
    "shut up",
    "shut your",
    "damn",
    "bloody",
    "worthless",
    "disgusting",
    "you people",
    "go back to",
)

AGGRESSION_CUES: tuple[str, ...] = (
    "screaming",
    "shouting",
    "raised voice",
    "yelling",
)


def _score_text(text: str) -> tuple[float, bool, list[str]]:
    """Return (hostility score, threat detected, matched keywords) for text."""
    low = text.lower()
    keywords: list[str] = []

    threats = [p for p in THREAT_PHRASES if p in low]
    abuse = [p for p in ABUSE_PHRASES if p in low]
    cues = [p for p in AGGRESSION_CUES if p in low]

    score = 0.0
    score += 0.55 * min(len(threats), 2)
    score += 0.18 * min(len(abuse), 3)
    score += 0.12 * min(len(cues), 2)
    if re.search(r"!{2,}", text):
        score += 0.08
    if text.isupper() and len(text.split()) >= 4:
        score += 0.08

    keywords.extend(threats)
    keywords.extend(abuse)
    keywords.extend(cues)
    # de-duplicate, keep order
    seen: set[str] = set()
    unique = [k for k in keywords if not (k in seen or seen.add(k))]

    return (round(min(score, 1.0), 3), bool(threats), unique)


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ASRProvider(Protocol):
    """Contract used by the orchestrator for audio transcription."""

    async def transcribe(self, attachment: MediaAttachment) -> AudioTranscript: ...


# ---------------------------------------------------------------------------
# Real TRTC ASR client
# ---------------------------------------------------------------------------


class TRTCASRClient:
    """Tencent Cloud TRTC ASR over the signed TC3 JSON API.

    The request shape mirrors Tencent's ``CreateCloudRecording``/ASR style
    endpoints: a TC3-HMAC-SHA256 signature over the canonical request. When the
    call fails (missing credential, network, quota) the orchestrator's
    ``_guarded`` wrapper falls back to the simulated client, so a live demo
    degrades gracefully instead of crashing.
    """

    SERVICE = "trtc"
    ALGORITHM = "TC3-HMAC-SHA256"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.trtc_timeout_s)

    @property
    def configured(self) -> bool:
        return bool(self.settings.trtc_secret_id and self.settings.trtc_secret_key)

    # --- TC3 signing -------------------------------------------------------
    def _sign(self, payload: str, timestamp: int) -> str:
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        canonical_request = "\n".join(
            [
                "POST",
                "/",
                "",
                "content-type:application/json",
                f"host:{self._host}",
                f"x-tc-action:{self._action.lower()}",
                "",
                "content-type;host;x-tc-action",
                hashlib.sha256(payload.encode()).hexdigest(),
            ]
        )
        credential_scope = f"{date}/{self.SERVICE}/tc3_request"
        to_sign = "\n".join(
            [
                self.ALGORITHM,
                str(timestamp),
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )

        def hmac_sha256(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = hmac_sha256(f"TC3{self.settings.trtc_secret_key}".encode(), date)
        secret_service = hmac_sha256(secret_date, self.SERVICE)
        secret_signing = hmac_sha256(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return (
            f"{self.ALGORITHM} Credential={self.settings.trtc_secret_id}/{credential_scope}, "
            f"SignedHeaders=content-type;host;x-tc-action, Signature={signature}"
        )

    @property
    def _host(self) -> str:
        return re.sub(r"^https?://", "", self.settings.trtc_asr_endpoint).rstrip("/")

    @property
    def _action(self) -> str:
        return "DescribeASRTask"

    async def transcribe(self, attachment: MediaAttachment) -> AudioTranscript:
        """Submit an audio payload to TRTC ASR and normalise the response."""
        if not self.configured:
            raise RuntimeError("TRTC credentials not configured")

        timestamp = int(time.time())
        body = {
            "SdkAppId": self.settings.trtc_app_id,
            "TaskId": attachment.attachment_id,
            "MediaUrl": attachment.url,
            "Language": "en-SG",
        }
        payload = json.dumps(body, separators=(",", ":"))
        response = await self._client.post(
            self.settings.trtc_asr_endpoint,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Host": self._host,
                "X-TC-Action": self._action,
                "X-TC-Timestamp": str(timestamp),
                "X-TC-Version": "2019-07-22",
                "Authorization": self._sign(payload, timestamp),
            },
        )
        response.raise_for_status()
        data = response.json()
        inner = data.get("Response", data)
        segments = [
            AudioSegment(
                speaker=str(s.get("Speaker", "unknown")).lower(),
                start_s=float(s.get("StartTs", 0) or 0),
                end_s=float(s.get("EndTs", 0) or 0),
                text=str(s.get("Text", "")),
                hostility=_score_text(str(s.get("Text", "")))[0],
            )
            for s in inner.get("Segments", []) or []
        ]
        full_text = " ".join(s.text for s in segments).strip()
        score, threat, keywords = _score_text(full_text)
        return AudioTranscript(
            attachment_id=attachment.attachment_id,
            engine="trtc",
            duration_s=float(inner.get("Duration", attachment.duration_s or 0.0) or 0.0),
            confidence=float(inner.get("Confidence", 0.8) or 0.8),
            segments=segments,
            full_text=full_text,
            hostility_score=score,
            threat_detected=threat,
            keywords=keywords,
            summary=_summarise(score, threat, keywords),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Deterministic simulated ASR (offline / demo / CI)
# ---------------------------------------------------------------------------


class SimulatedASRClient:
    """Deterministic transcription used when TRTC credentials are absent.

    The transcript is derived from the attachment itself:

    * ``attachment.caption`` / ``transcript_hint`` — the mock payload shipped
      with the sample dossiers carries the scripted dialogue, so the
      transcription step is reproducible and the downstream agents still
      receive realistic text to score.
    * otherwise a neutral placeholder is produced, which keeps the pipeline
      shape intact for ad-hoc uploads.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings

    async def transcribe(self, attachment: MediaAttachment) -> AudioTranscript:
        hint = _hint_of(attachment)
        segments = _segmentise(hint, attachment.duration_s)
        full_text = " ".join(s.text for s in segments).strip()
        score, threat, keywords = _score_text(full_text)
        return AudioTranscript(
            attachment_id=attachment.attachment_id,
            engine="simulated",
            language="en-SG",
            duration_s=_duration_of(attachment, segments),
            confidence=0.62 if hint else 0.35,
            segments=segments,
            full_text=full_text,
            hostility_score=score,
            threat_detected=threat,
            keywords=keywords,
            summary=_summarise(score, threat, keywords),
        )

    async def aclose(self) -> None:  # pragma: no cover - nothing to close
        return None


def _hint_of(attachment: MediaAttachment) -> str:
    """Pull the scripted dialogue off an attachment (see ``cases.py``).

    Sample dossiers ship a ``transcript_hint`` string with the mock recording so
    the transcription step is reproducible; ad-hoc uploads simply have none.
    """
    extras = getattr(attachment, "model_extra", None) or {}
    value = extras.get("transcript_hint")
    if value:
        return str(value)
    # Fall back to the caption so an uploaded file without a hint is still
    # transcribed into something the downstream agents can score.
    return str(attachment.caption or "")


def _segmentise(hint: str, duration_s: Optional[float]) -> list[AudioSegment]:
    """Split a scripted dialogue string into timestamped speaker turns."""
    if not hint.strip():
        return [
            AudioSegment(
                speaker="unknown",
                start_s=0.0,
                end_s=float(duration_s or 0.0),
                text="[unintelligible] no speech recognised in the uploaded recording",
            )
        ]

    # "driver: ... | rider: ..." or newline-separated turns.
    raw_turns = [t.strip() for t in re.split(r"\s*\|\s*|\n", hint) if t.strip()]
    total = float(duration_s or max(4.0, 2.5 * len(raw_turns)))
    per_turn = total / max(len(raw_turns), 1)
    segments: list[AudioSegment] = []
    for i, turn in enumerate(raw_turns):
        speaker = "unknown"
        text = turn
        match = re.match(r"^(rider|driver)\s*:\s*(.+)$", turn, flags=re.IGNORECASE)
        if match:
            speaker = match.group(1).lower()
            text = match.group(2).strip()
        score = _score_text(text)[0]
        segments.append(
            AudioSegment(
                speaker=speaker,  # type: ignore[arg-type]
                start_s=round(i * per_turn, 2),
                end_s=round(min((i + 1) * per_turn, total), 2),
                text=text,
                hostility=score,
            )
        )
    return segments


def _duration_of(attachment: MediaAttachment, segments: Sequence[AudioSegment]) -> float:
    if attachment.duration_s:
        return round(float(attachment.duration_s), 2)
    if segments:
        return round(max(s.end_s for s in segments), 2)
    return 0.0


def _summarise(score: float, threat: bool, keywords: Sequence[str]) -> str:
    if threat:
        return (
            f"Transcript contains an explicit threat (hostility {score:.2f}); "
            f"matched: {', '.join(keywords) if keywords else 'threat language'}."
        )
    if score >= 0.45:
        return (
            f"Abusive or aggressive language detected (hostility {score:.2f}); "
            f"matched: {', '.join(keywords) if keywords else 'tone cues'}."
        )
    if score >= 0.15:
        return f"Mildly confrontational language (hostility {score:.2f})."
    return "No abusive or threatening language detected in the transcript."


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_asr_provider(settings: Settings) -> ASRProvider:
    """Return the real TRTC client when configured, else the simulated one."""
    if settings.trtc_secret_id and settings.trtc_secret_key:
        return TRTCASRClient(settings)
    return SimulatedASRClient(settings)


def probe_audio_duration(path: Path) -> Optional[float]:
    """Best-effort duration read from a WAV header (no external dependency)."""
    try:
        import wave

        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return round(frames / float(rate), 2)
    except Exception:  # pragma: no cover - non-WAV payloads
        return None
