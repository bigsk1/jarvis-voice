# Jarvis Proactive API - Documentation

Event-driven webhook system for proactive notifications.

![reactive-vs-proactive-info-graph](../images/reactive-vs-proactive-info-graph.jpeg)

---

## 📚 Documentation Index

### Getting Started
- **[API Overview](API_OVERVIEW.md)** - What it is, how it works, quick start
- **[Ready to Use Guide](READY_TO_USE.md)** - Setup and deployment
- **[API Quick Start](API_QUICK_START.md)** - Endpoint reference

### Integration & Examples
- **[Code Examples](code-examples/)** - Ready-to-use templates (Python, Node.js, Bash, Docker)
- **[Alert Scenarios](code-examples/ALERT_SCENARIOS.md)** - Complete integration patterns
- **[Remote Monitoring](REMOTE_MONITORING.md)** - Monitor remote servers/containers
- **[Security Options](SECURITY_OPTIONS.md)** - Tailscale, WireGuard, secure access

### Intelligence API ⭐ NEW
The API exposes intelligence layer metrics and controls:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/intelligence/stats` | GET | Basic stats (experiences, insights) |
| `/api/intelligence/health` | GET | Health check with issue detection |
| `/api/intelligence/metrics` | GET | Prometheus-style metrics |
| `/api/intelligence/insights` | GET | Recent insights (last 20) |
| `/api/intelligence/experiences` | GET | Recent experiences (last 20) |
| `/api/intelligence/logs/recent` | GET | Today's intelligence logs |
| `/api/intelligence/reflect` | POST | Trigger manual reflection |
| `/api/intelligence/evaluate` | GET | Meta-cognition evaluation |

See **[../INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md)** for full documentation.

### Prometheus Metrics
Intelligence metrics exposed at `/metrics`:
```promql
jarvis_intelligence_experiences_total{mode="cloud"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="positive"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="negative"}
jarvis_intelligence_avg_confidence{mode="cloud"}
jarvis_intelligence_pending_reflections{mode="cloud"}
```

### Reference
- **[Fixes Log](FIXES_LOG.md)** - Historical fixes and updates

### Architecture (see `docs/service/`)
- [Proactive System Architecture](../service/PROACTIVE_ASSISTANT_SYSTEM.md)
- [Service Architecture FAQ](../service/SERVICE_ARCHITECTURE_FAQ.md)
- [Phase 1 Complete](../service/PHASE_1_COMPLETE.md)

---

## Quick Links

**Start Here**: [API Overview](API_OVERVIEW.md)

**Need Examples?**: [Code Examples](code-examples/)

**Remote Setup?**: [Remote Monitoring Guide](REMOTE_MONITORING.md)

**Intelligence Layer**: [INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md)
