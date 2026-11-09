# Upstream v2.3.0, reviewed source: 395d881d246fc9ef3f8f8c299b08e7d9f1359b89.
FROM ghcr.io/taylorwilsdon/google_workspace_mcp:2.3.0@sha256:f6729c8497b026911641a7358aabef89a941df2a5327c9fd13cf3dd43e0034b5
COPY --chown=app:app google-workspace/security-requirements.txt /app/jarvis-security-requirements.txt
# Retain the reviewed baseline; pypdf 6.21.4 patches the base's 6.21.3.
# Unrelated base packages stay untouched by these hash-locked overrides.
RUN uv --no-config pip install --python /app/.venv/bin/python --no-deps --require-hashes -r /app/jarvis-security-requirements.txt \
    && uv --no-config pip check --python /app/.venv/bin/python
COPY --chown=app:app google-workspace/entrypoint.py /app/jarvis_entrypoint.py
COPY --chown=app:app lib/http_observation.py /app/jarvis_http_observation.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/jarvis_entrypoint.py"]
CMD ["--transport", "streamable-http", "--single-user", "--tool-tier", "complete", "--tools", "gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "appscript"]
