# Upstream v2.1.2, reviewed source: 49e5e29bc1202ebf4e7218419cd8ff501de556f3.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.1.2@sha256:1b074c340eaf9de65d85f7a02fa7af1b18fcaa4b29e0428fe0f3835171a7d462
COPY --chown=app:app entrypoint.py /app/jarvis_entrypoint.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
