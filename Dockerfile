# Multi-stage build: Frontend compilation + Python runtime
FROM node:22-alpine AS frontend-builder
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AP_CONFIG=/app/.runtime/app.json

# Install minimal system dependencies for OCR & graphics
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for ultra-fast, reproducible dependency management
COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /bin/uv

# Copy project definition and locked dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application backend and migrations
COPY ap/ ./ap/
COPY migrations/ ./migrations/
COPY README.md ./

# Copy compiled frontend from stage 1
COPY --from=frontend-builder /web/dist ./web/dist

EXPOSE 8765

CMD ["uv", "run", "uvicorn", "ap.api:app", "--host", "0.0.0.0", "--port", "8765"]
