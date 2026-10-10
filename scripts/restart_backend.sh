#!/usr/bin/env bash
# Restart the RydeResolve backend (uvicorn) in the background.
set -u
cd /workspace/backend || exit 1

if command -v fuser >/dev/null 2>&1; then
  fuser -k -n tcp 3000 >/dev/null 2>&1
else
  for pid in $(ss -ltnp 2>/dev/null | grep ':3000' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    kill "$pid" >/dev/null 2>&1
  done
fi
sleep 1

setsid nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 3000 \
  > /tmp/backend.log 2>&1 < /dev/null &

for _ in $(seq 1 30); do
  if curl -sf http://localhost:3000/api/health >/dev/null 2>&1; then
    echo "backend up"
    exit 0
  fi
  sleep 1
done

echo "backend FAILED to start"
tail -30 /tmp/backend.log
exit 1
