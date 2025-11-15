# Test Results Directory

This directory contains test execution logs and results from automated test runs.

## Files Generated

### Per-Test Run (timestamped)
- `test-cloud-comprehensive_YYYYMMDD_HHMMSS.log` - Full test output with color codes
- `test-cloud-comprehensive_YYYYMMDD_HHMMSS_results.json` - Structured JSON results

## JSON Result Format

```json
{
  "test_run": {
    "timestamp": "2025-11-15T12:00:00-08:00",
    "script": "test-cloud-comprehensive.sh",
    "mode": "cloud",
    "tests": [
      {
        "test_number": 1,
        "name": "Cache Test 1 (Write)",
        "query": "What time is it?",
        "expected": "time",
        "passed": true,
        "duration_sec": 3,
        "ok": true,
        "speech": "It's 12:00 PM",
        "cache_read_tokens": 0,
        "cache_write_tokens": 10884,
        "cache_savings_usd": 0.0,
        "cost_usd": 0.023
      }
    ],
    "summary": {
      "total": 22,
      "passed": 22,
      "failed": 0,
      "pass_rate": 100,
      "completed_at": "2025-11-15T12:05:00-08:00"
    }
  }
}
```

## Viewing Results

### Quick Summary
```bash
# View latest test summary
jq '.test_run.summary' logs/test/test-cloud-comprehensive_*.json | tail -n 10

# View all failed tests from latest run
jq '.test_run.tests[] | select(.passed == false)' logs/test/test-cloud-comprehensive_*.json | tail -n 100
```

### Full Details
```bash
# View specific test result
jq '.test_run.tests[0]' logs/test/test-cloud-comprehensive_20251115_120000_results.json

# View cache metrics across all tests
jq '.test_run.tests[] | {name: .name, cache_read: .cache_read_tokens, savings: .cache_savings_usd}' logs/test/test-cloud-comprehensive_*.json | tail -n 50
```

### Cost Analysis
```bash
# Total cost of test run
jq '[.test_run.tests[].cost_usd] | add' logs/test/test-cloud-comprehensive_*.json | tail -n 1

# Total savings from cache
jq '[.test_run.tests[].cache_savings_usd] | add' logs/test/test-cloud-comprehensive_*.json | tail -n 1
```

## Retention Policy

Test logs are kept locally but **not tracked in Git** (excluded via `.gitignore`).

Consider cleaning old logs manually:
```bash
# Keep only last 30 days
find logs/test -name "*.log" -mtime +30 -delete
find logs/test -name "*.json" -mtime +30 -delete
```

## Git Tracking

Only this README is tracked in Git. All test result files are excluded to avoid repository bloat.

