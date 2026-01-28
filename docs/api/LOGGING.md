# API Request Logging

The Jarvis API logs all requests to `logs/api/` for troubleshooting and monitoring.

---

## Log Files

| File Pattern | Contents |
|--------------|----------|
| `access-YYYY-MM-DD.jsonl` | External requests (excludes loopback by default) |
| `errors-YYYY-MM-DD.jsonl` | ALL errors (4xx/5xx) including loopback, with request body |

**Note:** Loopback traffic (127.0.0.1) is excluded from access logs to reduce noise from internal daemon polling. Errors from loopback are always logged.

### Log Entry Format

```json
{
  "timestamp": "2026-01-27T15:30:45.123456",
  "method": "POST",
  "path": "/api/workflows/deep_research/execute",
  "query": null,
  "status": 400,
  "duration_ms": 12.5,
  "client_ip": "100.70.158.18"
}
```

Error logs also include:
- `request_body` - First 500 chars of the request body
- `error` - Exception details if applicable

---

## Quick Commands

```bash
# Set today's date (use in commands below)
TODAY=$(date +%Y-%m-%d)

# Watch live requests (formatted)
tail -f logs/api/access-$TODAY.jsonl | jq .

# Watch live requests (compact)
tail -f logs/api/access-$TODAY.jsonl | jq -c '{t:.timestamp[11:19], m:.method, p:.path, s:.status}'

# View all errors
cat logs/api/errors-$TODAY.jsonl | jq .
```

---

## Analysis Commands

### Request Counts

```bash
# Count by endpoint
cat logs/api/access-$TODAY.jsonl | jq -r '.path' | sort | uniq -c | sort -rn

# Count by client IP
cat logs/api/access-$TODAY.jsonl | jq -r '.client_ip' | sort | uniq -c | sort -rn

# Count by status code
cat logs/api/access-$TODAY.jsonl | jq -r '.status' | sort | uniq -c | sort -rn
```

### Filter by Source

```bash
# Samantha requests (Tailscale 100.x.x.x)
cat logs/api/access-$TODAY.jsonl | jq 'select(.client_ip | startswith("100."))'

# External requests only (non-Tailscale)
cat logs/api/access-$TODAY.jsonl | jq 'select(.client_ip | startswith("100.") | not)'
```

### Performance

```bash
# Slow requests (>100ms)
cat logs/api/access-$TODAY.jsonl | jq 'select(.duration_ms > 100)'

# Average response time by endpoint
cat logs/api/access-$TODAY.jsonl | jq -s '
  group_by(.path) | 
  map({
    path: .[0].path, 
    avg_ms: (map(.duration_ms) | add / length) | floor, 
    count: length
  }) | 
  sort_by(.count) | reverse'

# Top 10 slowest requests
cat logs/api/access-$TODAY.jsonl | jq -s 'sort_by(.duration_ms) | reverse | .[0:10]'
```

### Error Investigation

```bash
# Error summary
cat logs/api/errors-$TODAY.jsonl | jq '{timestamp, path, status, request_body}'

# Workflow errors specifically
cat logs/api/errors-$TODAY.jsonl | jq 'select(.path | contains("workflow"))'

# 400 Bad Request errors
cat logs/api/errors-$TODAY.jsonl | jq 'select(.status == 400)'

# 500 Server errors
cat logs/api/errors-$TODAY.jsonl | jq 'select(.status >= 500)'
```

### Date Range Queries

```bash
# Last 7 days of access logs
cat logs/api/access-*.jsonl | jq .

# Specific date
cat logs/api/access-2026-01-25.jsonl | jq .

# Errors from last 3 days
cat logs/api/errors-2026-01-2{5,6,7}.jsonl 2>/dev/null | jq .
```

---

## Configuration

### Enable Loopback Logging

To include internal traffic (127.0.0.1) in access logs, edit `api/server.py`:

```python
# Change log_loopback=False to True
app.add_middleware(RequestLoggingMiddleware, log_loopback=True)
```

### Skipped Paths

These paths are never logged (health checks):
- `/api/health`
- `/metrics`
- `/api/status`

---

## Log Retention

API logs are managed by `bin/cleanup-logs`. Default retention is **60 days**.

```bash
# Preview what would be deleted
./bin/cleanup-logs --dry-run

# Run cleanup
./bin/cleanup-logs

# Custom retention (e.g., 30 days)
./bin/cleanup-logs --days 30
```

See [Log Management](../service/README.md#log-management) for system-wide log cleanup.

---

## Troubleshooting

### Empty Logs
- Restart the API after changing logging config
- Check file permissions: `ls -la logs/api/`

### Missing Requests
- Loopback (127.0.0.1) is filtered by default
- Health checks are skipped
- Check if request came from internal daemon

### Large Log Files
- Run `./bin/cleanup-logs` to remove old logs
- Check disk usage: `du -sh logs/api/`

---

*Last Updated: January 2026*
