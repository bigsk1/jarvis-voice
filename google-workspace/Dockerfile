# Upstream v2.0.1, reviewed source: 25dc59d7e045c79b3f60a40782d071a664562c86.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.0.1@sha256:e839e6b77732d8840d77dbdac87fa57551f6c2ba524b069bf12bf3f60e68f6e9
COPY --chown=app:app entrypoint.py /app/jarvis_entrypoint.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
