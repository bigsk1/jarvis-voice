FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV JARVIS_VENV=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        imagemagick \
        jq \
        libportaudio2 \
        libsndfile1 \
        lsof \
        procps \
        ripgrep \
        sqlite3 \
        sox \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$JARVIS_VENV"

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN chmod +x /app/docker/entrypoint.sh /app/docker/services.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
