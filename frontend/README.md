# RydeResolve frontend

A React + Vite + shadcn/ui console that consumes the backend's SSE stream and
exposes the arbitration pipeline as a live "ops console".

## Pages

`src/pages/Index.tsx` assembles:

| Region                  | Source                          | What it shows                                                  |
| ----------------------- | ------------------------------- | -------------------------------------------------------------- |
| Header                  | `useEffect(fetchHealth)`        | engine mode, ADP credential status, **Run Arbitration** button |
| Left rail               | `components/CaseRail.tsx`       | Dispute queue, 4 sample dossiers with expected rulings         |
| Pipeline rail           | `components/PipelineRail.tsx`   | 6 stages, ticked off as events arrive                           |
| Center (Inter-Agent)    | `components/AgentStream.tsx`    | Live SSE feed of every agent message with auto-scroll          |
| Right panel (tabs)      | Evidence / Arguments / Verdict  | Auditable facts, side-by-side advocacy, final ruling           |

## State machine

```
idle  --[Run]-->  streaming  --[end event]-->  done
                  \--[error]-->                error
```

When the SSE `end` event fires, the UI auto-switches to the **Verdict** tab and
fetches the canonical `/api/result/{run_id}` to populate the structured
panels (so a refreshed page also shows the full state).

## API

`src/lib/api.ts` exports `fetchHealth`, `fetchCases`, `startDispute`,
`fetchResult` and `subscribeToRun` (which uses an `EventSource` with named
event listeners for each `level`).

## Run

```bash
pnpm install
pnpm dev          # http://localhost:5173
```

Vite proxies `/api/*` to `http://localhost:3000` (see `vite.config.ts`).
