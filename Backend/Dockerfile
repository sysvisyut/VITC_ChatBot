# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install all Python dependencies
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System deps needed by camelot-py (ghostscript + opencv) and PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Copy and install requirements first (layer cache — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install/deps --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — lean image, non-root user, no build tools
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Same runtime system libs (no build tools like gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder
COPY --from=builder /install/deps /usr/local

# Create a non-root user to run the app
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy application source code (Dockerfile is in Backend/, so . = Backend/)
COPY --chown=appuser:appgroup . .

# Create the data directory (PDF storage) and set ownership
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

USER appuser

# Expose uvicorn port
EXPOSE 8000

# Run with uvicorn — explicit host/port, single worker (scale via compose replicas)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
