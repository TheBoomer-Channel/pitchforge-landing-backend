# ─── Build Stage ────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps (needed for weasyprint, fastembed, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    libcairo2 \
    libcairo2-dev \
    libgirepository1.0-dev \
    pkg-config \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtualenv at a neutral location
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python deps inside the virtualenv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Runtime Stage ──────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install runtime deps (weasyprint needs cairo/pango at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libcairo2 \
    libgirepository-1.0-1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder (neutral location, world-readable)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code (before user switch so files are owned by root)
COPY . .

# Create non-root user and grant ownership of /app
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app

# Make /opt/venv readable and executable by all
RUN chmod -R a+rX /opt/venv

USER app

# Expose port
EXPOSE 8086

# Healthcheck — use python from venv
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8086/health')" || exit 1

# Production CMD — no --reload. Use python -m uvicorn for reliable venv resolution
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
