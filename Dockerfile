# RydeResolve — single-port container image (FastAPI serves API + built React console)
#
# Build:  docker build -t ryderesolve:latest .
# Run:    docker run -p 8080:8080 -e PORT=8080 ryderesolve:latest
# Health: curl localhost:8080/api/health

# ---------- Stage 1: build the React console ----------
FROM node:22-bookworm-slim AS web

WORKDIR /web
# Pin pnpm to the version the lockfile was produced with. pnpm 10 blocks
# postinstall scripts unless a package is listed in
# package.json → pnpm.onlyBuiltDependencies (esbuild, @swc/core).
RUN corepack enable && corepack prepare pnpm@10.28.2 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


# ---------- Stage 2: runtime ----------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# ffmpeg drives video keyframe extraction; opencv is the documented fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir opencv-python-headless

COPY backend/ ./

# Precedent KB and uploaded media are written at runtime.
RUN mkdir -p /app/data

# main.py resolves the console at ../frontend/dist relative to backend/,
# so the build output lands at /frontend/dist.
COPY --from=web /web/dist /frontend/dist

EXPOSE 8080

CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
