FROM python:3.13-slim

# OCI annotations for better metadata
LABEL org.opencontainers.image.title="Jarvis Monitor"
LABEL org.opencontainers.image.description="Universal monitoring agent for Docker containers & HTTP endpoints"
LABEL org.opencontainers.image.authors="bigsk1"
LABEL org.opencontainers.image.vendor="bigsk1"
LABEL org.opencontainers.image.url="https://github.com/bigsk1/jarvis-monitor"
LABEL org.opencontainers.image.documentation="https://github.com/bigsk1/jarvis-monitor"
LABEL org.opencontainers.image.source="https://github.com/bigsk1/jarvis-monitor"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="1.1.0"
LABEL maintainer="bigsk1"

# Security: Create non-root user with docker group access
# GID 999 is commonly used for docker group, but it may vary
# The container will inherit the host's docker socket permissions
RUN groupadd -r monitor && useradd -r -g monitor -G root monitor

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt /app/

# Install dependencies with pinned versions
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy monitoring script
COPY monitor.py /app/

# Make script executable
RUN chmod +x /app/monitor.py

# Create temp directory for health file
RUN mkdir -p /tmp

# Health check - verify monitor process is responsive
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import os; os.path.exists('/tmp/monitor_healthy')" || exit 1
   
# Run monitor
CMD ["python", "-u", "/app/monitor.py"]

