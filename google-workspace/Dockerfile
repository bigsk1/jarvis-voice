# Upstream v2.2.0, reviewed source: b5cf07e6078ae10a596710d77569e9430e01ebd4.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.2.0@sha256:af95ed31eef19fc4c74fea4ee7f174e000ea57aef3b8ab2480467bcc2d985e45
COPY --chown=app:app security-requirements.txt /app/jarvis-security-requirements.txt
# Upstream's frozen lock predates newer pypdf, FastMCP and OpenTelemetry fixes.
# Hash-locked replacements retain all other packages from the pinned base.
RUN uv --no-config pip install --python /app/.venv/bin/python --no-deps --require-hashes -r /app/jarvis-security-requirements.txt \
    && uv --no-config pip check --python /app/.venv/bin/python
COPY --chown=app:app entrypoint.py /app/jarvis_entrypoint.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
