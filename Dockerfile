# syntax=docker/dockerfile:1

# ---- frontend: React + Vite build ----
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime: FastAPI + Telethon, serves the built frontend ----
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TGT_DATA_DIR=/data

RUN groupadd --system --gid 10001 tgt \
 && useradd --system --uid 10001 --gid tgt --home-dir /app --shell /usr/sbin/nologin tgt \
 && mkdir -p /data && chown tgt:tgt /data

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /src/frontend/dist /app/frontend/dist

USER tgt
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
