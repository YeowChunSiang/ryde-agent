# RydeResolve backend

The four files listed in the Ryde problem statement, plus a few supporting
modules, run a deterministic multi-agent arbitration pipeline.

## Deliverables (as specified in the problem statement)

| File                  | Purpose                                                            |
| --------------------- | ------------------------------------------------------------------ |
| `models.py`           | Pydantic v2 schemas mirroring `DISP-002` (with `media_attachments`)|
| `prompts.py`          | System prompts + strict JSON output contracts                       |
| `orchestrator.py`     | Async state pipeline that calls ADP via httpx                      |
| `main.py`             | FastAPI app exposing `/dispute` and `/stream`                      |

Supporting modules (in the same package):

* `config.py` — 12-factor settings
* `evidence.py` — deterministic fact extraction
* `adp_client.py` — `LLMProvider` protocol, `ADPClient` (httpx SSE), `OfflineReasoner`
* `cases.py` — built-in `DISP-001`..`DISP-004` sample dossiers

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app --host 0.0.0.0 --port 3000
```

See the project-level [README.md](../README.md) for end-to-end usage.
