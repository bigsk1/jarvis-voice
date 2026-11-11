# Upstream v2.4.1, reviewed source: d94a6a7e693ce97c633f744b55249616b3806e9c.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.4.1@sha256:bc9864d11d9f510abdeea4d22bb177328fb6c720b3f794f5675b7f83c956d9fa
# The pinned base includes the former security overlay's exact patched versions.
RUN uv --no-config pip check --python /app/.venv/bin/python
COPY --chown=app:app google-workspace/entrypoint.py /app/jarvis_entrypoint.py
COPY --chown=app:app lib/http_observation.py /app/jarvis_http_observation.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
