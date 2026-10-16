# Deploying RYsolve to Tencent CloudBase (云托管 / CloudRun)

RYsolve runs as **one HTTP port**: FastAPI serves both the JSON API and the
built React console (`frontend/dist`). That makes it a direct fit for
**CloudBase 云托管 (CloudRun)**, which only needs a container that listens on a
single port.

```
browser ──► CloudBase CloudRun service ──► uvicorn main:app :$PORT
                                            ├─ /api/*         (FastAPI routes)
                                            ├─ /assets/*      (built JS/CSS)
                                            ├─ /media/*       (uploaded audio/video)
                                            └─ /*             (SPA shell → index.html)
```

## 0. What you need from Tencent Cloud

| Item | Where to get it |
| --- | --- |
| A Tencent Cloud account | <https://cloud.tencent.com> |
| A CloudBase environment (`envId`) | CloudBase console → 环境 → 创建环境 (e.g. `ryde-1a2b3c`) |
| (Optional) A TCR / 容器镜像服务 namespace | if you deploy by pushing an image instead of source |
| CloudBase CLI | `npm i -g @cloudbase/cli` → `tcb -v` |

## 1. Files added for this deployment

| File | Purpose |
| --- | --- |
| `Dockerfile` | two-stage build: pnpm builds the console, then `python:3.11-slim` runs FastAPI on `$PORT` (default 8080). Installs `ffmpeg` for keyframe extraction plus `opencv-python-headless` as the documented fallback. |
| `.dockerignore` | keeps the build context small (no `node_modules`, no `docs`, no local `backend/data`). |
| `cloudbaserc.json` | CloudBase Framework manifest — **replace `REPLACE_WITH_YOUR_ENV_ID`** with your real `envId`. |

## 2. Route A — CloudBase CLI / Framework (from source)

```bash
npm i -g @cloudbase/cli
tcb login                       # browser authorisation (or set TENCENTCLOUD_SECRET_ID / _KEY)

# edit cloudbaserc.json → set envId
tcb framework deploy            # builds the Dockerfile in the cloud and creates the 云托管 service
```

The CLI prints the public domain of the service when it finishes.

## 3. Route B — build locally, push an image

```bash
# 1. build
docker build -t ryderesolve:latest .

# 2. smoke-test it locally
docker run --rm -p 8080:8080 -e PORT=8080 ryderesolve:latest
curl localhost:8080/api/health          # → {"status":"ok", ...}
open http://localhost:8080              # → reviewer portal (reviewer / reviewer)

# 3. tag + push to TCR (个人版/企业版), then create a 云托管 service from that image
docker tag ryderesolve:latest <tcr-host>/<namespace>/ryderesolve:latest
docker push <tcr-host>/<namespace>/ryderesolve:latest
```

In the CloudBase console: 云托管 → 新建服务 → 镜像来源选 TCR → 端口 `8080` →
CPU 1 核 / 内存 2 G → 最小副本 1 → 部署.

## 4. Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `PORT` | `8080` | CloudBase injects its own; the container reads `${PORT:-8080}`. |
| `HOST` | `0.0.0.0` | must stay `0.0.0.0` or the health check fails. |
| `ADP_APP_KEY` / `ADP_APP_ID` | unset | Tencent Cloud ADP credentials. **Leave unset to run on the deterministic offline reasoner** — the demo works fully without them. |
| `REVIEWER_TOKEN` | unset | Bearer token for approve/override endpoints; unset = auth disabled (demo mode). |
| `TRTC_*` | unset | live ASR; falls back to the deterministic simulated ASR client. |

## 5. Post-deploy checklist

```bash
curl https://<service-domain>/api/health     # 200 + "status":"ok"
curl -o /dev/null -w '%{http_code}' https://<service-domain>/dashboard   # 200 (SPA fallback)
```

Then in the browser: log in with `reviewer / reviewer`, open `DISP-002`, click
**Run arbitration**, and watch the 10-stage SSE pipeline resolve it.

## 6. Two things to know before you go live

1. **Containers are stateless.** The precedent knowledge base
   (`backend/data/precedents.json`) and uploaded media are written to the
   container filesystem, so they are lost on redeploy/scale-out. For a real
   deployment, mount a CFS volume at `/app/data` (and `/app/uploads`) or move
   the KB to CloudBase 数据库 / COS.
2. **Cold starts.** With `minNum: 0` the first request after idle takes a few
   seconds. `minNum: 1` (as configured) keeps one instance warm at the cost of
   always-on billing.

## 7. Local parity check

The image is byte-for-byte the same stack as local dev, so the usual
regressions apply inside it too:

```bash
cd backend && python3 -m pytest tests -q     # 50 passing
cd frontend && pnpm build                    # must pass before docker build
```
