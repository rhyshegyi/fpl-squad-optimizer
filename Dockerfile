# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — build the React SPA. Runs npm install + vite build, then hands
# frontend/dist to the runtime stage.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — Python runtime. uv resolves deps and installs the fpl-optimizer
# package; FastAPI serves both /api routes and the static SPA on port 8080.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# uv statically-linked binary from Astral's image
COPY --from=ghcr.io/astral-sh/uv:0.5.29 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# LightGBM links against the GNU OpenMP runtime, which python:3.13-slim
# doesn't ship. The API deliberately never imports LightGBM, so this isn't
# needed for the server to boot — but without it, any accidental import of
# the training stack kills the process at startup rather than failing
# somewhere recoverable. Cheap insurance against a repeat.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for better layer caching
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the app + built frontend + committed artifacts.
# README.md is required: pyproject.toml declares `readme = "README.md"`, and
# the uv_build backend reads it while building the package below.
COPY README.md ./
COPY src/ ./src/
COPY data/artifacts/ ./data/artifacts/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8080

# Bind to 0.0.0.0 so Fly's proxy can reach us
CMD ["uvicorn", "fpl_optimizer.api:app", "--host", "0.0.0.0", "--port", "8080"]
