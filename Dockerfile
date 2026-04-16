# Arena → Samsung Frame TV Sync Dockerfile
# Stateless sync of Are.na images to Samsung Frame TV Art Mode
# Uses Python slim base with runtime dependencies for Pillow

# Build stage: install dependencies and build wheels
FROM python:3.13-slim AS builder

LABEL org.opencontainers.image.source="https://github.com/dshatokhin/framer"
LABEL org.opencontainers.image.description="Stateless sync of Are.na images to Samsung Frame TV Art Mode"

# Set non-interactive frontend for apt
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies for Pillow (build time only)
RUN apt-get update -qq && \
    apt-get install -y -qq -o APT::Install-Suggests=0 -o APT::Install-Recommends=0 \
    gcc \
    g++ \
    git \
    libjpeg-dev \
    libpng-dev \
    python3-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies to a local directory
RUN pip install --quiet --no-cache-dir --no-warn-script-location --target=/app/deps -r requirements.txt

# Copy application code
COPY sync_arena_to_tv.py .

# Runtime stage: Python slim with runtime dependencies
FROM python:3.13-slim

# Set non-interactive frontend for apt
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies for Pillow
RUN apt-get update -qq && \
    apt-get install -y -qq -o APT::Install-Suggests=0 -o APT::Install-Recommends=0 \
    libjpeg62-turbo \
    libpng16-16 \
    libtiff6 \
    libwebp7 \
    libfreetype6 \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /app/deps /app/deps
COPY --from=builder /app/sync_arena_to_tv.py /app/sync_arena_to_tv.py

# Set Python path to include dependencies
ENV PYTHONPATH=/app/deps

# Set working directory
WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser

# Entrypoint: Python script (reads environment variables directly)
ENTRYPOINT ["python3", "sync_arena_to_tv.py"]
