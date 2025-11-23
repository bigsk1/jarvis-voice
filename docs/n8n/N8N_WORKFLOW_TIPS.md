# n8n Workflow Tips & Gotchas

## 🔧 Webhook Workflows

### Critical: Manual Activation Required
When creating webhooks via API:
1. Create workflow → Works ✅
2. Activate via API → Sets flag but webhook NOT registered ❌
3. **Must toggle OFF/ON in UI** → Webhook actually registers ✅

**Why?** Security feature - prevents automated webhook hijacking.

### Webhook URL Format
- **NOT:** `/webhook/{workflowId}/path` ❌
- **YES:** `/webhook/{path}` ✅

The `path` parameter from your webhook node config IS the URL path.

### Finding Your Webhook URL
1. Open workflow in UI
2. Click webhook node
3. Look at node details panel (right side)
4. URLs are shown for test & production modes

---

## 🎨 Workflow Creation via MCP

### What Works
```bash
# Via MCP tools:
- search_nodes() - Find nodes
- get_node_essentials() - Get config requirements
- validate_node_minimal() - Check if valid

# Via API (direct curl):
- POST /api/v1/workflows - Create workflow
- PUT /api/v1/workflows/{id} - Update workflow
- PATCH /api/v1/workflows/{id} - NOT SUPPORTED ❌
```

### Best Practice
1. Use MCP to discover & validate nodes
2. Create workflow via REST API
3. Activate in UI (for webhooks)
4. Test via API/curl

---

## 🐛 Common Issues

### "Webhook not registered" 
**Symptom:** 404 error on webhook URL  
**Fix:** Toggle OFF/ON in UI, wait for confirmation popup

### Multiple duplicate workflows
**Symptom:** 3+ workflows with same name  
**Cause:** API retries during testing  
**Fix:** Archive or delete duplicates via UI

### Conflicting webhook paths
**Symptom:** Can only activate one workflow  
**Cause:** Multiple workflows using same `path` parameter  
**Fix:** Archive inactive ones or change path

---

## 💡 Pro Tips

1. **Always check UI for webhook URL** - Don't guess the format
2. **Wait for popup** - Confirms webhook actually registered
3. **Test mode first** - Click "Execute Workflow" button, test URL works once
4. **Production mode** - Requires active workflow, works repeatedly
5. **Clean up test workflows** - Archive or delete after testing

---

## 🔗 Useful API Endpoints

```bash
# List workflows
GET /api/v1/workflows?active=true

# Get workflow details
GET /api/v1/workflows/{id}

# List executions
GET /api/v1/executions?workflowId={id}&limit=10

# Get execution details
GET /api/v1/executions/{id}
```

---

**Last Updated:** 2025-11-23  
**n8n Version:** 1.120.4

