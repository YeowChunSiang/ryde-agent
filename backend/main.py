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
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from cases import CASE_REGISTRY, get_case, list_cases
from config import get_settings
from models import (
    AgentRole,
    DisputeAccepted,
    DisputeCase,
    DisputeRequest,
    EventLevel,
    ResolutionResult,
)
from orchestrator import Orchestrator, RunBroker, event_stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("ryderesolve")

settings = get_settings()
broker = RunBroker()
orchestrator = Orchestrator(settings, broker)

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
        return payload.case
    assert payload.case_id is not None
    try:
        return get_case(payload.case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _accepted(run) -> DisputeAccepted:
    return DisputeAccepted(
        run_id=run.run_id,
        dispute_id=run.case.dispute_id,
        dispute_type=run.case.dispute_type,
        stream_url=f"/api/stream/{run.run_id}",
        result_url=f"/api/result/{run.run_id}",
        engine=run.engine,  # type: ignore[arg-type]
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
        "runs": len(broker.runs),
    }


@app.get("/cases")
async def cases() -> dict:
    return {"cases": [c.model_dump(mode="json") for c in list_cases()]}


@app.get("/cases/{case_id}")
async def case_detail(case_id: str) -> dict:
    if case_id not in CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown case '{case_id}'")
    return CASE_REGISTRY[case_id]


@app.post("/dispute", response_model=DisputeAccepted)
async def create_dispute(payload: DisputeRequest) -> DisputeAccepted:
    """Ingest a dispute and kick off arbitration in the background.

    Returns immediately with a ``run_id``; subscribe to ``/stream/{run_id}`` to
    watch the agents work in real time.
    """
    case = _resolve_case(payload)
    run = broker.create(case, orchestrator.engine)
    asyncio.create_task(_run_pipeline(run))
    logger.info("dispute %s accepted as %s (engine=%s)", case.dispute_id, run.run_id, run.engine)
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
