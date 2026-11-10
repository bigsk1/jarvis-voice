# Upstream v2.4.0, reviewed source: 53c392dc426ca8795e27dcf0301f92b5abe85688.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.4.0@sha256:df7f96f6db9bdc92774f683fc237ad9287ea8614a5414c0909c1be1f0d8227b0
# The pinned base includes the former security overlay's exact patched versions.
RUN uv --no-config pip check --python /app/.venv/bin/python
COPY --chown=app:app google-workspace/entrypoint.py /app/jarvis_entrypoint.py
COPY --chown=app:app lib/http_observation.py /app/jarvis_http_observation.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
