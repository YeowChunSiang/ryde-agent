"""FastAPI application — RydeResolve multi-agent dispute resolution service.

Endpoints (mounted both at ``/`` and ``/api`` so the Vite dev proxy and direct
calls both work):

===========  =======================  ==========================================
Method       Path                     Purpose
===========  =======================  ==========================================
GET          /health                  Liveness + configured engine mode
GET          /cases                   Built-in sample dossiers for the demo UI
GET          /cases/{case_id}         Raw JSON of one sample dossier
POST         /dispute                 Ingest a dispute, start arbitration, return run_id
GET          /stream/{run_id}         SSE stream of live inter-agent messages
GET          /stream                  SSE stream for the most recent run
GET          /result/{run_id}         Final resolution result
POST         /resolve                 Synchronous resolve (no streaming) — for tests
===========  =======================  ==========================================
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from cases import CASE_REGISTRY, get_case, list_cases
from config import get_settings
from media_store import MediaStore, media_type_for
from models import (
    AgentRole,
    DisputeAccepted,
    DisputeCase,
    DisputeRequest,
    EventLevel,
    MediaAttachment,
    OverrideAccepted,
    OverrideRequest,
    ResolutionResult,
)
from orchestrator import Orchestrator, RunBroker, event_stream
from trtc_client import SimulatedASRClient, build_asr_provider, probe_audio_duration
from vision_utils import VideoProcessingError, analyse_video, backend_name, ffmpeg_available

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("ryderesolve")

settings = get_settings()
broker = RunBroker()
media_store = MediaStore(settings)
orchestrator = Orchestrator(settings, broker)
orchestrator.media_store = media_store  # one registry for uploads and playback URLs
asr_provider = build_asr_provider(settings)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.adp_configured and orchestrator.engine == "adp":
        logger.info("Tencent Cloud ADP configured — agents will use live LLM inference")
    else:
        logger.warning(
            "ADP_APP_KEY not set — running the deterministic offline reasoner. "
            "Set ADP_APP_KEY in backend/.env to switch to live Tencent Cloud ADP."
        )
    yield
    provider = getattr(orchestrator, "provider", None)
    aclose = getattr(provider, "aclose", None)
    if aclose is not None:
        await aclose()


app = FastAPI(
    title="RydeResolve",
    description=(
        "Multi-agent autonomous dispute resolution for ride-hailing: parallel rider/driver "
        "advocates, an impartial judge, a forensic vision agent and a confidence-gated "
        "escalation protocol."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_case(payload: DisputeRequest) -> DisputeCase:
    if payload.case is not None:
        case = payload.case
    else:
        assert payload.case_id is not None
        try:
            case = get_case(payload.case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Graft anything uploaded earlier through /upload-audio or /upload-video
    # onto the dossier, keyed by the case or dispute id.
    merged = media_store.merge_into(case)
    if merged:
        logger.info(
            "attached %d uploaded media payload(s) to %s", len(merged), case.dispute_id
        )
    return case


def _accepted(run) -> DisputeAccepted:
    routing = run.routing
    return DisputeAccepted(
        run_id=run.run_id,
        dispute_id=run.case.dispute_id,
        dispute_type=run.case.dispute_type,
        stream_url=f"/api/stream/{run.run_id}",
        result_url=f"/api/result/{run.run_id}",
        engine=run.engine,  # type: ignore[arg-type]
        sla_priority=routing.priority if routing else None,
        fast_tracked=routing.fast_tracked if routing else False,
        queue=routing.queue if routing else None,
        sla_due_at=routing.sla_due_at if routing else None,
    )


async def _run_pipeline(run) -> None:
    """Background wrapper so POST /dispute can return before arbitration ends."""
    try:
        await orchestrator._pipeline(run)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("pipeline failed: %s", exc)
        run.result.errors.append(f"{type(exc).__name__}: {exc}")
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "pipeline_error",
            f"Pipeline failed: {type(exc).__name__}: {exc}",
            level=EventLevel.ERROR,
        )
    finally:
        run.result.finished_at = datetime.now(timezone.utc)
        if run.result.duration_ms is None:
            run.result.duration_ms = 0
        run.done = True


def _stream(run) -> StreamingResponse:
    return StreamingResponse(
        event_stream(run),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "RydeResolve",
        "engine": orchestrator.engine,
        "adp_configured": settings.adp_configured,
        "escalation_threshold": settings.confidence_escalation_threshold,
        "demo_pacing_ms": settings.offline_demo_pacing_ms,
        "knowledge_base_precedents": orchestrator.knowledge_base_size,
        "runs": len(broker.runs),
        # --- Phase 3: multi-modal capability report -------------------------
        "asr_engine": "trtc" if settings.trtc_secret_id else "simulated",
        "video_backend": backend_name(),
        "ffmpeg_available": ffmpeg_available(),
        "uploaded_media": sum(len(media_store.pending(k)) for k in media_store.all_keys()),
    }


@app.get("/cases")
async def cases() -> dict:
    return {"cases": [c.model_dump(mode="json") for c in list_cases()]}


@app.get("/cases/{case_id}")
async def case_detail(case_id: str) -> dict:
    if case_id not in CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown case '{case_id}'")
    return CASE_REGISTRY[case_id]


# ---------------------------------------------------------------------------
# Phase 3: multi-modal ingestion (audio + video)
# ---------------------------------------------------------------------------


@app.post("/upload-audio")
async def upload_audio(
    file: UploadFile = File(...),
    case_id: Optional[str] = Form(default=None),
    uploaded_by: str = Form(default="rider"),
    captured_at: Optional[str] = Form(default=None),
    caption: Optional[str] = Form(default=None),
    transcript_hint: Optional[str] = Form(default=None),
) -> dict:
    """Ingest an audio recording and transcribe it with TRTC ASR.

    Accepts an in-app safety recording or a passenger's covert recording. The
    transcript is attached to the case's ``media_attachments`` so the Evidence
    Engine, the Fraud Agent and the Judge can all weigh it.

    Without TRTC credentials the deterministic simulated ASR runs instead, so
    the endpoint is always demoable (and testable in CI).
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio payload")
    kind = media_type_for(file.filename or "clip.wav")
    if kind != "audio":
        raise HTTPException(
            status_code=415, detail=f"'{file.filename}' is not an audio payload"
        )

    saved = media_store.save(file.filename or "clip.wav", raw, "audio")
    duration = probe_audio_duration(saved)

    attachment = MediaAttachment(
        media_type="audio",
        url=media_store.web_path(saved),
        uploaded_by="rider" if uploaded_by not in ("rider", "driver") else uploaded_by,  # type: ignore[arg-type]
        captured_at=_parse_dt(captured_at),
        device_model="in-app safety recorder",
        exif_present=True,
        caption=caption or (file.filename or "audio evidence"),
        duration_s=duration,
        local_path=str(saved),
    )
    # Simulation knob: without TRTC credentials the deterministic ASR needs a
    # script to "hear". Real deployments leave this empty and the live ASR
    # transcribes the actual waveform.
    if transcript_hint:
        attachment.transcript_hint = transcript_hint  # type: ignore[attr-defined]

    try:
        transcript = await asr_provider.transcribe(attachment)
    except Exception as exc:  # live ASR failure -> deterministic fallback
        logger.warning("TRTC ASR failed (%s); using simulated transcription", exc)
        transcript = await SimulatedASRClient(settings).transcribe(attachment)
        transcript.engine = "simulated"
    attachment.transcript = transcript

    if case_id:
        media_store.attach(case_id, attachment)
    logger.info(
        "audio uploaded: %s (%s, %.1fs, hostility %.2f, threat=%s)",
        attachment.attachment_id,
        file.filename,
        transcript.duration_s,
        transcript.hostility_score,
        transcript.threat_detected,
    )
    web_path = media_store.web_path(saved)
    return {
        # Flat summary the UI renders directly.
        "status": "transcribed",
        "dispute_id": case_id,
        "attachment_id": attachment.attachment_id,
        "media_type": "audio",
        "filename": file.filename or "clip.wav",
        "web_path": web_path,
        "duration_s": transcript.duration_s,
        "transcript": transcript.model_dump(mode="json"),
        # Full dossier attachment, for callers that want everything.
        "attachment": attachment.model_dump(mode="json"),
        "stored_at": web_path,
        "attached_to": case_id,
        "asr_engine": transcript.engine,
    }


@app.post("/upload-video")
async def upload_video(
    file: UploadFile = File(...),
    case_id: Optional[str] = Form(default=None),
    uploaded_by: str = Form(default="driver"),
    captured_at: Optional[str] = Form(default=None),
    caption: Optional[str] = Form(default=None),
) -> dict:
    """Ingest a dashcam / cabin video and extract keyframes for the vision agent.

    The clip is decoded at 1 frame per second (configurable) and the resulting
    frames are served back at ``/media/frames/...`` so a reviewer can scrub the
    exact frames the agent reasoned over.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty video payload")
    kind = media_type_for(file.filename or "clip.mp4")
    if kind != "video":
        raise HTTPException(
            status_code=415, detail=f"'{file.filename}' is not a video payload"
        )

    saved = media_store.save(file.filename or "clip.mp4", raw, "video")
    attachment = MediaAttachment(
        media_type="video",
        url=media_store.web_path(saved),
        uploaded_by="driver" if uploaded_by not in ("rider", "driver") else uploaded_by,  # type: ignore[arg-type]
        captured_at=_parse_dt(captured_at),
        device_model="dashcam",
        exif_present=True,
        caption=caption or (file.filename or "video evidence"),
        local_path=str(saved),
    )

    try:
        analysis = await asyncio.to_thread(
            analyse_video, saved, settings, attachment.attachment_id
        )
    except VideoProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    attachment.video = analysis
    attachment.duration_s = analysis.duration_s

    if case_id:
        media_store.attach(case_id, attachment)
    logger.info(
        "video uploaded: %s (%s, %.1fs, %d keyframes)",
        attachment.attachment_id,
        file.filename,
        analysis.duration_s,
        analysis.frames_extracted,
    )
    web_path = media_store.web_path(saved)
    return {
        # Flat summary the UI renders directly.
        "status": "analysed",
        "dispute_id": case_id,
        "attachment_id": attachment.attachment_id,
        "media_type": "video",
        "filename": file.filename or "clip.mp4",
        "web_path": web_path,
        "duration_s": analysis.duration_s,
        "video": analysis.model_dump(mode="json"),
        # Full dossier attachment, for callers that want everything.
        "attachment": attachment.model_dump(mode="json"),
        "stored_at": web_path,
        "attached_to": case_id,
        "video_backend": analysis.engine,
    }


@app.get("/media/uploads")
async def list_uploads() -> dict:
    """Everything uploaded so far, grouped by the case it is attached to."""
    return {
        "cases": media_store.all_keys(),
        "attachments": {
            key: [a.model_dump(mode="json") for a in media_store.pending(key)]
            for key in media_store.all_keys()
        },
    }


def _parse_dt(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@app.post("/dispute", response_model=DisputeAccepted)
async def create_dispute(payload: DisputeRequest) -> DisputeAccepted:
    """Ingest a dispute and kick off arbitration in the background.

    Returns immediately with a ``run_id``; subscribe to ``/stream/{run_id}`` to
    watch the agents work in real time.

    The SLA & Routing Manager intercepts the ticket here, *before* the run is
    queued, so a safety incident is tagged CRITICAL and fast-tracked ahead of
    whatever standard disputes are already waiting.
    """
    case = _resolve_case(payload)
    run = broker.create(case, orchestrator.engine)
    run.routing = orchestrator.triage(case)
    run.result.routing = run.routing
    asyncio.create_task(_run_pipeline(run))
    logger.info(
        "dispute %s accepted as %s (engine=%s, priority=%s, fast_tracked=%s)",
        case.dispute_id,
        run.run_id,
        run.engine,
        run.routing.priority.value,
        run.routing.fast_tracked,
    )
    return _accepted(run)


@app.post("/resolve", response_model=ResolutionResult)
async def resolve_sync(payload: DisputeRequest) -> ResolutionResult:
    """Run arbitration to completion and return the result (no streaming)."""
    case = _resolve_case(payload)
    run = await orchestrator.arbitrate(case)
    return run.result


@app.get("/stream/{run_id}")
async def stream_run(run_id: str) -> StreamingResponse:
    run = broker.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")
    return _stream(run)


@app.get("/stream")
async def stream_latest() -> StreamingResponse:
    run = broker.get()
    if run is None:
        raise HTTPException(status_code=404, detail="No runs yet — POST /dispute first")
    return _stream(run)


@app.get("/result/{run_id}", response_model=ResolutionResult)
async def result(run_id: str) -> ResolutionResult:
    run = broker.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")
    return run.result


# ---------------------------------------------------------------------------
# Learning feedback loop
# ---------------------------------------------------------------------------


@app.post("/override/{run_id}", response_model=OverrideAccepted)
async def override_run(run_id: str, payload: OverrideRequest) -> OverrideAccepted:
    """Human reviewer overrides an escalated ruling.

    The correction is captured and injected back into the Policy & Precedent
    Agent's knowledge base as a new precedent, so the next analogous dispute is
    arbitrated against what the reviewer actually decided. That closes the
    loop from human judgement back into autonomous arbitration.
    """
    result = await orchestrator.apply_override(run_id, payload)
    if result is None or result.override is None:
        raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")
    logger.info(
        "override on %s by %s -> %s (knowledge base now %d precedents)",
        run_id,
        payload.reviewer_id,
        payload.decision.value,
        result.override.knowledge_base_size,
    )
    return result.override


@app.get("/precedents")
async def precedents() -> dict:
    """Current contents of the precedent knowledge base."""
    store = orchestrator.policy_agent.store
    return {
        "count": store.size,
        "precedents": [p.model_dump(mode="json") for p in store.all()],
    }


@app.get("/escalations")
async def escalations() -> dict:
    """Runs halted by the escalation protocol and awaiting human review."""
    items = []
    for run in broker.runs.values():
        ruling = run.result.ruling
        if ruling is None:
            continue
        # Keep overridden runs visible — they are the ones that fed the
        # knowledge base, so hiding them would hide the learning loop.
        if not ruling.escalated and run.result.override is None:
            continue
        items.append(
            {
                "run_id": run.run_id,
                "dispute_id": run.case.dispute_id,
                "priority": run.routing.priority.value if run.routing else "normal",
                "queue": run.routing.queue if run.routing else None,
                "sla_due_at": run.routing.sla_due_at.isoformat() if run.routing else None,
                "overridden": run.result.override is not None,
                "escalation": (
                    run.result.escalation.model_dump(mode="json")
                    if run.result.escalation
                    else None
                ),
            }
        )
    return {"escalations": items, "count": len(items)}


# ---------------------------------------------------------------------------
# /api aliases — the Vite dev proxy forwards /api -> :3000
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def api_health() -> dict:
    return await health()


@app.get("/api/cases")
async def api_cases() -> dict:
    return await cases()


@app.get("/api/cases/{case_id}")
async def api_case_detail(case_id: str) -> dict:
    return await case_detail(case_id)


@app.post("/api/dispute", response_model=DisputeAccepted)
async def api_create_dispute(payload: DisputeRequest) -> DisputeAccepted:
    return await create_dispute(payload)


@app.post("/api/resolve", response_model=ResolutionResult)
async def api_resolve_sync(payload: DisputeRequest) -> ResolutionResult:
    return await resolve_sync(payload)


@app.get("/api/stream/{run_id}")
async def api_stream_run(run_id: str) -> StreamingResponse:
    return await stream_run(run_id)


@app.get("/api/stream")
async def api_stream_latest() -> StreamingResponse:
    return await stream_latest()


@app.get("/api/result/{run_id}", response_model=ResolutionResult)
async def api_result(run_id: str) -> ResolutionResult:
    return await result(run_id)


@app.post("/api/override/{run_id}", response_model=OverrideAccepted)
async def api_override_run(run_id: str, payload: OverrideRequest) -> OverrideAccepted:
    return await override_run(run_id, payload)


@app.get("/api/precedents")
async def api_precedents() -> dict:
    return await precedents()


@app.get("/api/escalations")
async def api_escalations() -> dict:
    return await escalations()


@app.post("/api/upload-audio")
async def api_upload_audio(
    file: UploadFile = File(...),
    case_id: Optional[str] = Form(default=None),
    uploaded_by: str = Form(default="rider"),
    captured_at: Optional[str] = Form(default=None),
    caption: Optional[str] = Form(default=None),
    transcript_hint: Optional[str] = Form(default=None),
) -> dict:
    return await upload_audio(file, case_id, uploaded_by, captured_at, caption, transcript_hint)


@app.post("/api/upload-video")
async def api_upload_video(
    file: UploadFile = File(...),
    case_id: Optional[str] = Form(default=None),
    uploaded_by: str = Form(default="driver"),
    captured_at: Optional[str] = Form(default=None),
    caption: Optional[str] = Form(default=None),
) -> dict:
    return await upload_video(file, case_id, uploaded_by, captured_at, caption)


@app.get("/api/media/uploads")
async def api_list_uploads() -> dict:
    return await list_uploads()


# ---------------------------------------------------------------------------
# Phase 3: serve ingested media + extracted keyframes
# ---------------------------------------------------------------------------

FRAME_ROOT = Path(settings.frame_dir)
if not FRAME_ROOT.is_absolute():
    FRAME_ROOT = (Path(__file__).resolve().parent / FRAME_ROOT).resolve()
FRAME_ROOT.mkdir(parents=True, exist_ok=True)
media_store.root.mkdir(parents=True, exist_ok=True)

# More specific mounts first — Starlette matches routes in registration order.
for prefix in ("/media/frames", "/api/media/frames"):
    app.mount(prefix, StaticFiles(directory=str(FRAME_ROOT)), name=f"frames{prefix}")
for prefix in ("/media", "/api/media"):
    app.mount(prefix, StaticFiles(directory=str(media_store.root)), name=f"media{prefix}")

logger.info(
    "Serving ingested media from %s and extracted keyframes from %s (video backend: %s)",
    media_store.root,
    FRAME_ROOT,
    backend_name(),
)


# ---------------------------------------------------------------------------
# Optional single-port static hosting (only if the frontend has been built)
# ---------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
    logger.info("Serving built frontend from %s", FRONTEND_DIST)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )
