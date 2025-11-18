FROM python:3.13-slim

LABEL maintainer="Jarvis Monitoring Agent"
LABEL description="Universal monitoring agent for sending alerts to Jarvis"

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir requests docker

# Copy monitoring script
COPY monitor.py /app/

# Make script executable
RUN chmod +x /app/monitor.py

# Health check - verify monitor process is responsive
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import os; os.path.exists('/tmp/monitor_healthy')" || exit 1

# Run monitor
CMD ["python", "-u", "/app/monitor.py"]

