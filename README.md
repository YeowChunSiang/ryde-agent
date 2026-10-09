# RydeResolve — Multi-Agent Autonomous Dispute Resolution

> A multi-agent arbitration backend + live observability console for ride-hailing
> disputes. Built for the **Tencent Cloud AI Singapore Hackathon 2026** (Ryde
> problem statement) on the AI Agent Digital Native track.

## What it solves

Ride-hailing platforms process thousands of dispute tickets a day — fare
disputes, route deviations, no-show charges, property damage. Today every one
of them waits 24–72 hours for a human agent to read GPS pings, chat logs and
photos, then write up a ruling. RydeResolve replaces that with an **explicit,
auditable, state-pipelined multi-agent system** that issues a defensible ruling
in under a second and falls back to a human reviewer when the evidence is thin.

## Architecture

```mermaid
flowchart LR
    subgraph Frontend
        UI[React + Vite UI]
    end

    subgraph Backend [FastAPI service :3000]
        POST[POST /dispute]
        OVR[POST /override/{run_id}]
        SSE[GET /stream/{run_id}]
        ORCH[Orchestrator<br/>deterministic state machine]
        SLA[SLA & Routing Manager]
        COL[Evidence Collection Agent<br/>async upstream fan-out]
        EVD[Evidence Engine<br/>pure Python]
        FRD[Fraud & Bad-Faith Agent]
        PRC[Policy & Precedent Agent<br/>mock RAG]
        VIS[Image Analysis Agent]
        RAD[Rider Advocate]
        DAD[Driver Advocate]
        JDG[Judge Agent]
        ESC[Escalation Gate]
        LRN[Learning Feedback Loop]
        LLM{{Tencent Cloud ADP<br/>wss.lke.tencentcloud.com}}
        OFF[Offline Reasoner<br/>deterministic fallback]
    end

    UI -- HTTP --> POST
    UI -- HTTP --> OVR
    UI -- SSE --> SSE
    POST --> SLA
    SLA --> ORCH
    ORCH -- parallel --> COL
    ORCH -- parallel --> FRD
    ORCH -- parallel --> PRC
    ORCH --> EVD
    ORCH --> VIS
    ORCH --> RAD
    ORCH --> DAD
    RAD --> LLM
    DAD --> LLM
    JDG --> LLM
    FRD --> LLM
    PRC --> LLM
    LLM -. failures .-> OFF
    RAD -. fallback .-> OFF
    DAD -. fallback .-> OFF
    JDG -. fallback .-> OFF
    FRD -. fallback .-> OFF
    PRC -. fallback .-> OFF
    ORCH --> JDG
    JDG --> ESC
    OVR --> LRN
    LRN --> PRC
    SSE -- event:info/evidence/argument/ruling/warning --> UI
```

Every arrow above corresponds to a discrete, loggable state transition — the
agents' conversation is observable in real time through the SSE stream.

Pipeline order: **intake → SLA routing → (evidence + collection + fraud +
precedent, run concurrently) → vision → parallel advocacy → arbitration →
escalation gate**, with the override endpoint closing the loop back into the
precedent knowledge base.

## Project layout

```
backend/
  main.py            FastAPI app, /api + / routes, CORS, optional static
  config.py          12-factor settings (env-driven)
  models.py          Pydantic v2 schemas (SLA, risk, precedent, wire contracts)
  prompts.py         Agent system prompts + JSON output contracts
  evidence.py        Deterministic fact extraction (the auditable core)
  agents.py          SLA router, collection agent, fraud agent, precedent RAG
  adp_client.py      LLMProvider protocol, ADP SSE client, OfflineReasoner
  orchestrator.py    Async state pipeline, run broker, SSE generator, overrides
  cases.py           DISP-001..005 sample datasets
  data/precedents.json  precedent knowledge base (gitignored, grows at runtime)
frontend/
  src/
    pages/Index.tsx          main page
    components/CaseRail.tsx          left rail
    components/PipelineRail.tsx      progress rail (9 stages)
    components/AgentStream.tsx       live SSE feed
    components/EvidencePanel.tsx     facts + policy + risk + vision
    components/RiskPanel.tsx         SLA routing, collection, fraud, precedents
    components/AdvocatesPanel.tsx    rider vs driver cards
    components/VerdictPanel.tsx      ruling + confidence + summaries
    components/EscalationPanel.tsx   escalation packet + human override form
    components/agent-meta.ts         shared color/metadata
    types/index.ts                   mirror of backend schemas
    lib/api.ts                       typed API + EventSource client
```

## Running it

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # optional — leave ADP_APP_KEY empty for offline
python -m uvicorn main:app --host 0.0.0.0 --port 3000
```

You should see:

```
INFO uvicorn.error | Application startup complete.
INFO ryderesolve | ADP_APP_KEY not set — running the deterministic offline reasoner.
INFO ryderesolve | Serving built frontend from .../frontend/dist  (if built)
```

### 2. Frontend (dev)

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:5173
```

Vite proxies `/api/*` to `http://localhost:3000`.

### 3. Single-port deploy

```bash
cd frontend && pnpm build
cd ../backend && python -m uvicorn main:app --port 3000
# Open http://localhost:3000
```

When `frontend/dist` exists the FastAPI app mounts it at `/` and serves the
whole product from one process.

## Talking to it by hand

```bash
# 1. List the built-in disputes
curl -s http://localhost:3000/api/cases | jq

# 2. Open the official hackathon sample
curl -s -X POST http://localhost:3000/api/dispute \
  -H "Content-Type: application/json" \
  -d '{"case_id":"DISP-002"}' | jq

# 3. Watch the agents talk (Server-Sent Events)
curl -N http://localhost:3000/api/stream/<run_id>

# 4. Read the final ruling + evidence
curl -s http://localhost:3000/api/result/<run_id> | jq

# 5. Human override — writes the correction back as a precedent (learning loop)
curl -s -X POST http://localhost:3000/api/override/<run_id> \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id":"ops-1","decision":"partial_refund","amount":12.5,
       "rationale":"Telemetry shows the driver waited less than the full window."}' | jq

# 6. Inspect the knowledge base and the escalation queue
curl -s http://localhost:3000/api/precedents | jq
curl -s http://localhost:3000/api/escalations | jq
```

## Why an "evidence-first" design?

The Ryde problem statement calls out **inconsistent rulings** as a core pain
point. Letting the LLM invent facts from raw JSON does not solve that — it
embeds the inconsistency inside an opaque model.

So the evidence layer (`backend/evidence.py`) is the *only* thing that touches
the numbers:

* Haversine distance between every GPS ping and the pickup pin
* Wait duration, contact attempt count, pickup drift, route deviation vs. optimal
* EXIF-vs-trip-end delta, AI-generation probability, fare overcharge
* Per-claim policy compliance (CANCEL-1..5, ROUTE-1..3, DAMAGE-1..2)

Every output fact carries a `source` and a `supports` party tag. The
advocates and the judge are *only* allowed to argue over those facts, and
must cite fact keys in their output. A reviewer can replay the arithmetic
for any ruling and explain to the rider *exactly* why they won or lost.

When Tencent Cloud ADP is unreachable (or no AppKey is configured), the
`OfflineReasoner` produces the same shape of output deterministically from
the same evidence packet, so the system is demoable end-to-end without
credentials — and so it can be A/B-tested against a baseline ruling
("responsible AI" criterion).

## Expected rulings for the built-in samples

| Case       | Category        | Priority | Expected ruling                                     |
| ---------- | --------------- | -------- | --------------------------------------------------- |
| `DISP-001` | Route Deviation | normal   | **PARTIAL REFUND** — ~$5.60 (traffic justified part) |
| `DISP-002` | No-Show Charge  | normal   | **CHARGE UPHELD** — driver met every policy clause   |
| `DISP-003` | Property Damage | high     | **NO ACTION** + escalated to Fraud & Safety (fake photo) |
| `DISP-004` | Property Damage | high     | **COMPENSATE DRIVER** — $60 cleaning fee awarded      |
| `DISP-005` | Safety Incident | critical | **ESCALATED TO HUMAN** — never auto-resolved          |

## Stretch goals implemented

* **SLA & Routing Manager** (`agents.py`) — tags every ticket with a
  `sla_priority` (critical/high/normal/low), a queue and an SLA due time
  *before* arbitration starts. `safety_incident` and high-value claims are
  fast-tracked; `DISP-005` lands in the `safety_escalations` queue as CRITICAL.
* **Evidence Collection Agent** — an async fan-out that "queries" five upstream
  services (trip, telemetry, messaging, mobile analytics, identity), reporting
  per-source latency, record counts and degraded/failed status. It is a
  data-ingestion orchestrator, not a text generator.
* **Fraud & Bad-Faith Detection Agent** — scores `fraud_flags` +
  `dispute_history` + evidence contradictions into a `FraudAssessment`
  (risk score, verdict, per-party risk, `RiskSignal[]`) and hands it straight
  to the judge.
* **Policy & Precedent Agent** (mock RAG) — retrieves the top-k analogous past
  rulings by fact-signature similarity and tells the judge how to stay
  consistent; the knowledge base is a JSON store that grows at runtime.
* **Escalation Protocol** — a gate right after the judge: confidence below
  `CONFIDENCE_ESCALATION_THRESHOLD` (default 0.70) or an always-human dispute
  type halts autonomy, sets `escalated_to_human` and emits a full
  `EscalationPacket` (routing, evidence digest, conflicts, risk flags,
  recommended focus).
* **Learning Feedback Loop** — `POST /override/{run_id}` captures a reviewer's
  decision and injects it into the precedent knowledge base as a new
  `human_override` precedent, so the next analogous dispute is arbitrated
  against what the reviewer actually decided. The UI shows the new precedent id
  and the growing KB size.

All six agents emit events on the SSE stream, and the console renders them in
the 9-stage pipeline rail and the **Risk & RAG** tab.

## Environment

| Variable                         | Default | Purpose                                          |
| -------------------------------- | ------- | ------------------------------------------------ |
| `ADP_APP_KEY`                    | (empty) | Tencent Cloud ADP credential; empty = offline    |
| `ADP_ENDPOINT`                   | `https://wss.lke.tencentcloud.com/adp/v2/chat` | ADP chat URL     |
| `ENGINE_MODE`                    | `auto`  | `auto` / `adp` / `offline`                       |
| `CONFIDENCE_ESCALATION_THRESHOLD`| `0.70`  | Below this confidence the judge is overridden    |
| `AUTO_ESCALATE_DISPUTE_TYPES`    | `safety_incident` | Comma-separated dispute types always escalated |
| `OFFLINE_DEMO_PACING_MS`         | `220`   | Per-step delay for the offline reasoner (demo only) |
| `SLA_HIGH_VALUE_THRESHOLD`       | `50`    | Claim amount (SGD) that promotes a ticket to HIGH |
| `COLLECTION_SIMULATE_LATENCY`    | `true`  | Emulate upstream API round-trips in the collection agent |
| `COLLECTION_BASE_LATENCY_MS`     | `40`    | Base latency per upstream call                   |
| `COLLECTION_JITTER_MS`           | `90`    | Random jitter added per upstream call            |
| `PRECEDENT_TOP_K`                | `2`     | Precedents retrieved per dispute                 |
| `PRECEDENT_STORE_PATH`           | (none)  | JSON file backing the knowledge base (persists across restarts) |
| `PORT`                           | `3000`  | HTTP port                                        |

## Submitting to the hackathon

* Project title: **RydeResolve**
* Short blurb: *Multi-agent autonomous dispute resolution for ride-hailing.*
* Architecture diagram: see above.
* Live demo URL: deploy `frontend/dist` + `backend` as one process and share
  the `https://.../` URL.
* Conversation history: see `/workspace/.codebuddy/...`.
