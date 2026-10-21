# Upstream v2.1.1, reviewed source: 7096dd9dba5f169cd466e0f2ffc26bfd0ff16e1d.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.1.1@sha256:27440c7d8d630d4979ca6838b54267d79b315ae4a78162273801e97b83f3180f
COPY --chown=app:app entrypoint.py /app/jarvis_entrypoint.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
