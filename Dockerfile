# ============================================
# Elephantasm Backend - Multi-Stage Dockerfile
# ============================================
# Stage 1: Builder - Install dependencies and prepare virtual environment
# Stage 2: Runtime - Minimal image with only necessary files
# ============================================

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.12.6-slim AS builder

# Set working directory
WORKDIR /app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# ============================================
# Stage 2: Final Runtime Image
# ============================================
FROM python:3.12.6-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies only (no build tools)
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code from builder
COPY --from=builder /app /app

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT="production"

# Expose port 8000 for uvicorn
EXPOSE 8000

# Health check using simple liveness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Run uvicorn server
# - Single worker (Fly.io handles horizontal scaling via machines)
# - No access log (use Fly.io logs instead for better performance)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
