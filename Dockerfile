# ============================================================
# Fraud MVP — Production Dockerfile
# ============================================================
# Build:  docker build -t fraud-mvp .
# Run:    docker compose --profile app up
# ============================================================

FROM python:3.12-slim

# Prevent Python from writing pyc files and using excess memory
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for:
# - lxml: libxml2-dev, libxslt-dev
# - playwright: fonts, browser binaries
# - httpx: built-in (no extra deps)
# - telethon: libffi-dev (for cffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev \
    libffi-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    fonts-liberation \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Create venv and install dependencies
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --upgrade pip && pip install -r requirements.txt

# Install Playwright browsers (headless Chromium only, bundled deps are sufficient)
# If you need full deps for PDF rendering: playwright install chromium --with-deps
RUN playwright install chromium 2>&1 | tail -5

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /app/db

# Default command (API server)
# Override with: docker compose run --profile collector fraud-mvp python -m agents.collector
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
