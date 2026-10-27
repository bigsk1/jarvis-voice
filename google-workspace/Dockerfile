# Upstream v2.2.1, reviewed source: 0801afb3e58f51754f5a40161c07675f50565448.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.2.1@sha256:a44e788e21371ae8afbe40de327dd562efa1c74c172dfb76be75d233610fb855
COPY --chown=app:app security-requirements.txt /app/jarvis-security-requirements.txt
# Upstream's frozen lock predates newer pypdf, FastMCP and OpenTelemetry fixes.
# Hash-locked replacements retain all other packages from the pinned base.
RUN uv --no-config pip install --python /app/.venv/bin/python --no-deps --require-hashes -r /app/jarvis-security-requirements.txt \
    && uv --no-config pip check --python /app/.venv/bin/python
COPY --chown=app:app entrypoint.py /app/jarvis_entrypoint.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
