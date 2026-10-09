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
        SSE[GET /stream/{run_id}]
        ORCH[Orchestrator<br/>deterministic state machine]
        EVD[Evidence Engine<br/>pure Python]
        VIS[Image Analysis Agent]
        RAD[Rider Advocate]
        DAD[Driver Advocate]
        JDG[Judge Agent]
        ESC[Escalation Gate]
        LLM{{Tencent Cloud ADP<br/>wss.lke.lke.tencentcloud.com}}
        OFF[Offline Reasoner<br/>deterministic fallback]
    end

    UI -- HTTP --> POST
    UI -- SSE --> SSE
    POST --> ORCH
    ORCH --> EVD
    ORCH --> VIS
    ORCH --> RAD
    ORCH --> DAD
    RAD --> LLM
    DAD --> LLM
    JDG --> LLM
    LLM -. failures .-> OFF
    RAD -. fallback .-> OFF
    DAD -. fallback .-> OFF
    JDG -. fallback .-> OFF
    ORCH --> JDG
    ORCH --> ESC
    SSE -- event:info/evidence/argument/ruling --> UI
```

Every arrow above corresponds to a discrete, loggable state transition — the
agents' conversation is observable in real time through the SSE stream.

## Project layout

```
backend/
  main.py            FastAPI app, /api + / routes, CORS, optional static
  config.py          12-factor settings (env-driven)
  models.py          Pydantic v2 schemas (DISP-002 + wire contracts)
  prompts.py         Agent system prompts + JSON output contracts
  evidence.py        Deterministic fact extraction (the auditable core)
  adp_client.py      LLMProvider protocol, ADP SSE client, OfflineReasoner
  orchestrator.py    Async state pipeline, run broker, SSE generator
  cases.py           DISP-001..004 sample datasets
  main.py + uvicorn  :3000
frontend/
  src/
    pages/Index.tsx          main page
    components/CaseRail.tsx          left rail
    components/PipelineRail.tsx      progress rail
    components/AgentStream.tsx       live SSE feed
    components/EvidencePanel.tsx     facts + policy + risk
    components/AdvocatesPanel.tsx    rider vs driver cards
    components/VerdictPanel.tsx      ruling + summary
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

| Case       | Category        | Expected ruling                                     |
| ---------- | --------------- | --------------------------------------------------- |
| `DISP-001` | Route Deviation | **PARTIAL REFUND** — ~$5.60 (traffic justified part) |
| `DISP-002` | No-Show Charge  | **CHARGE UPHELD** — driver met every policy clause   |
| `DISP-003` | Property Damage | **NO ACTION** + escalated to Fraud & Safety (fake photo) |
| `DISP-004` | Property Damage | **COMPENSATE DRIVER** — $60 cleaning fee awarded      |

## Stretch goals implemented

* **Image Analysis Agent** (multi-modal, mocked) — forensic screen rejects
  fabricated photos, admits genuine ones.
* **Fraud & Bad-Faith Detection** — every case emits risk signals from
  profiles, dispute history and evidence patterns.
* **Escalation Protocol** — confidence below 65% (or safety-incident type)
  routes the ruling to a human reviewer; DISP-003 demonstrates the
  fraud-referral path.
* **Escalation feedback hook** — every escalated case keeps its computed
  ruling + evidence so a human override can be replayed against the
  `Policy & Precedent` knowledge base (the hook lives in `_apply_escalation`).

## Environment

| Variable                         | Default | Purpose                                          |
| -------------------------------- | ------- | ------------------------------------------------ |
| `ADP_APP_KEY`                    | (empty) | Tencent Cloud ADP credential; empty = offline    |
| `ADP_ENDPOINT`                   | `https://wss.lke.tencentcloud.com/adp/v2/chat` | ADP chat URL     |
| `ENGINE_MODE`                    | `auto`  | `auto` / `adp` / `offline`                       |
| `CONFIDENCE_ESCALATION_THRESHOLD`| `0.65`  | Below this confidence the judge is overridden    |
| `AUTO_ESCALATE_DISPUTE_TYPES`    | `safety_incident` | Comma-separated dispute types always escalated |
| `OFFLINE_DEMO_PACING_MS`         | `220`   | Per-step delay for the offline reasoner (demo only) |
| `PORT`                           | `3000`  | HTTP port                                        |

## Submitting to the hackathon

* Project title: **RydeResolve**
* Short blurb: *Multi-agent autonomous dispute resolution for ride-hailing.*
* Architecture diagram: see above.
* Live demo URL: deploy `frontend/dist` + `backend` as one process and share
  the `https://.../` URL.
* Conversation history: see `/workspace/.codebuddy/...`.
