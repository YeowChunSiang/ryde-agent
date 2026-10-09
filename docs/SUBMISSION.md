# Hackathon submission sheet — RydeResolve

Fill the entries below into the submission form.

## Project title
**RydeResolve**

## Short blurb (≤ 10 words)
> Multi-agent autonomous dispute resolution for ride-hailing.

## Project description

### Project overview
- **Target scenario:** thousands of dispute tickets per day on ride-hailing
  platforms — no-show charges, route deviations, property damage.
- **Target users:** rider and driver support organisations, marketplace
  operations teams.
- **Value proposition:** replace 24–72 hour human review with sub-second
  multi-agent arbitration that is auditable, consistent and explicitly
  hands off to a human when the evidence is thin.

### Real-world scenario insights
- **Pain point:** 24–72 hour resolution times, millions spent on human
  support, inconsistent rulings between agents, user churn from perceived
  unfairness.
- **Target audience:** every ride-hailing marketplace (Ryde, Gojek, Grab,
  Uber, Lyft, Ola) and any other multi-party marketplace with dispute
  resolution (food delivery, parcel, freelancer platforms).
- **Core problems solved:** slow resolution, inconsistent rulings,
  opacity, scalability.

### Comprehensive solution design
- **Business architecture:** four-agent arbitration pipeline (intake →
  evidence → vision → parallel rider/driver advocates → judge) with a
  human-in-the-loop escalation gate.
- **Technical architecture:** pure Python 3.11 + FastAPI + Pydantic v2 +
  httpx; React 19 + Vite + shadcn/ui console. Tennet Cloud ADP for
  inference (with a deterministic offline reasoner fallback so the demo
  works without credentials).
- **How prompts drive AI generation:** the four agent system prompts pin
  every model call to a strict JSON output contract; the LLM is *only*
  allowed to argue over facts that Python already computed, never to
  invent them. The deterministic reasoning engine is A/B-comparable to
  the model output for a Responsible-AI baseline.

### Business value
- Cuts average resolution time from 24–72 hours to **< 1 second** for
  the autonomous path.
- **Consistent** rulings: same evidence → same verdict, always
  (verifiable from the evidence packet).
- **Auditable** to any rider or driver: every fact is tagged with its
  source and the party it supports.
- **Safe** by construction: confidence below 65% (or any safety
  incident) is escalated to a human reviewer — the system never rules
  autonomously when unsure.
- Implementation is **swappable**: drop in any LLM/agent framework
  the team prefers (LangChain, AutoGen, CrewAI, or a custom client).
  Our `LLMProvider` protocol is the seam.

## Cover image
`docs/cover.png` (380×216)

## CodeBuddy / WorkBuddy conversation history
This conversation log is the proof.

## Demo flow (link in `/docs/screenshots/`)
1. `01_disp003_verdict.png` — property damage with a fabricated photo,
   vision agent rejects evidence, ruling = NO ACTION + escalation to
   Fraud & Safety.
2. `02_disp002_verdict.png` — the official hackathon sample: no-show
   charge, ruling = **CHARGE UPHELD** at 88% confidence, every
   policy clause satisfied.
3. `03_evidence_panel.png` — auditable evidence extracted in pure
   Python, every fact tagged with source and `supports` party.
4. `04_arguments_panel.png` — the two advocates, with **declared
   weaknesses** for adversarial honesty.
5. `05_full_pipeline_stream.png` — the live inter-agent
   communication feed (the observability requirement).

## Project link
Set `ADP_APP_KEY` and run `python -m uvicorn main:app --port 3000`
plus `pnpm dev` in `frontend/`, or build `frontend/dist` and serve
everything from FastAPI on a single port.
