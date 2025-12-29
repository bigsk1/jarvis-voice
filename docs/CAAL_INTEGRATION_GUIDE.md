# CAAL Integration Guide - Implementation Steps

> **Goal:** Integrate the best features from CAAL into Jarvis while maintaining Jarvis's superior architecture.

See [`CAAL_ANALYSIS.md`](./CAAL_ANALYSIS.md) for full comparison and rationale.

---

## Phase 1: Quick Wins (1-2 Days)

### 1.1 Add `/announce` Webhook Endpoint (30 minutes)

**File:** `jarvis-api/routes/api.py`

```python
@api_bp.route('/announce', methods=['POST'])
def announce():
    """
    Simple announce API (CAAL-compatible).
    Speaks a message via TTS immediately.
    
    POST /announce
    {
        "message": "Package delivered at front door"
    }
    """
    data = request.get_json() or {}
    message = data.get('message', '')
    
    if not message:
        return jsonify({'ok': False, 'error': 'message required'}), 400
    
    try:
        # Use existing TTS system
        mode = get_settings_manager().mode
        load_jarvis_config(mode)
        
        # Trigger TTS (same as proactive alerts)
        from ..utils import speak_text
        speak_text(message, mode)
        
        # Also create alert for logging
        alert_data = {
            'service_name': 'announce',
            'alert_type': 'info',
            'message': message,
            'alert_id': f"announce_{int(time.time())}",
            'metadata': {'source': 'announce_api'}
        }
        
        # Use existing alert system
        create_alert_internal(alert_data)
        
        return jsonify({
            'ok': True,
            'speech': message
        })
    
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500
```

**Test:**
```bash
# Terminal 1: Start Jarvis API
./bin/jarvis-api

# Terminal 2: Test announce
curl -X POST http://localhost:8880/announce \
  -H "Content-Type: application/json" \
  -d '{"message": "Test announcement from CAAL integration"}'
```

**Benefit:** External systems (Home Assistant, IFTTT, n8n) can trigger voice announcements with one simple API call.

---

### 1.2 n8n Workflow Auto-Discovery (1 Day)

**Goal:** Auto-discover n8n workflows with webhooks and expose as Jarvis tools (CAAL pattern).

#### Step 1: Create Discovery Module

**File:** `lib/n8n_discovery.py`

```python
#!/usr/bin/env python3
"""
n8n Workflow Auto-Discovery (CAAL-inspired)

Auto-discovers n8n workflows with webhook triggers and converts them to Jarvis tools.
Follows CAAL's pattern: workflow_name = webhook_path = tool_name
"""
import os
import sys
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import get_config_value


@dataclass
class N8NWorkflow:
    """Represents an n8n workflow with webhook trigger."""
    id: str
    name: str
    active: bool
    webhook_path: str
    description: str
    parameters: Dict[str, Any]


class N8NWorkflowDiscovery:
    """
    Discovers n8n workflows and converts them to Jarvis tools.
    
    Pattern:
    - n8n workflow name: "espn_get_nfl_scores"
    - Webhook path: "espn_get_nfl_scores" (POST)
    - Tool name: "n8n_espn_get_nfl_scores"
    - Description: From webhook node notes
    """
    
    def __init__(self, n8n_url: str, api_key: Optional[str] = None):
        """
        Initialize discovery client.
        
        Args:
            n8n_url: n8n instance URL (e.g., http://localhost:5678)
            api_key: Optional API key for authentication
        """
        self.n8n_url = n8n_url.rstrip('/')
        self.api_key = api_key
        self.headers = {}
        
        if api_key:
            self.headers['X-N8N-API-KEY'] = api_key
    
    def discover_workflows(self) -> List[N8NWorkflow]:
        """
        Query n8n API for workflows with webhook triggers.
        
        Returns:
            List of N8NWorkflow objects
        """
        import requests
        
        try:
            # Get all active workflows
            response = requests.get(
                f"{self.n8n_url}/api/v1/workflows",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            
            workflows = response.json().get('data', [])
            webhook_workflows = []
            
            for wf in workflows:
                # Skip inactive workflows
                if not wf.get('active'):
                    continue
                
                # Parse workflow structure
                workflow = self._parse_workflow(wf)
                if workflow:
                    webhook_workflows.append(workflow)
            
            return webhook_workflows
        
        except Exception as e:
            print(f"[n8n Discovery] Error: {e}", file=sys.stderr)
            return []
    
    def _parse_workflow(self, workflow_data: Dict[str, Any]) -> Optional[N8NWorkflow]:
        """
        Parse workflow data and extract webhook info.
        
        Args:
            workflow_data: Raw workflow JSON from n8n API
        
        Returns:
            N8NWorkflow if has webhook trigger, else None
        """
        nodes = workflow_data.get('nodes', [])
        
        # Find webhook trigger node
        webhook_node = None
        for node in nodes:
            if node.get('type') == 'n8n-nodes-base.webhook':
                webhook_node = node
                break
        
        if not webhook_node:
            return None
        
        # Extract webhook path (defaults to workflow name)
        webhook_params = webhook_node.get('parameters', {})
        webhook_path = webhook_params.get('path', workflow_data['name'])
        
        # Extract description from notes field
        description = webhook_node.get('notes', workflow_data.get('name', 'No description'))
        
        # Extract parameters from webhook node
        parameters = self._extract_parameters(webhook_node)
        
        return N8NWorkflow(
            id=workflow_data['id'],
            name=workflow_data['name'],
            active=workflow_data.get('active', False),
            webhook_path=webhook_path,
            description=description,
            parameters=parameters
        )
    
    def _extract_parameters(self, webhook_node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract parameter schema from webhook node notes.
        
        Expected format in notes:
        ```
        Description of tool
        
        Parameters:
        - param1 (string): Description
        - param2 (number): Description
        ```
        
        Returns:
            Parameter schema dict
        """
        notes = webhook_node.get('notes', '')
        parameters = {}
        
        # Simple parser for parameters from notes
        # TODO: Enhance with JSON schema parsing if needed
        if 'Parameters:' in notes:
            param_section = notes.split('Parameters:')[1]
            for line in param_section.split('\n'):
                line = line.strip()
                if line.startswith('-'):
                    # Parse: "- param_name (type): description"
                    parts = line[1:].strip().split(':', 1)
                    if len(parts) == 2:
                        param_def = parts[0].strip()
                        param_desc = parts[1].strip()
                        
                        # Extract name and type
                        if '(' in param_def:
                            param_name = param_def.split('(')[0].strip()
                            param_type = param_def.split('(')[1].split(')')[0].strip()
                            
                            parameters[param_name] = {
                                'type': param_type,
                                'description': param_desc
                            }
        
        return parameters
    
    def to_jarvis_tool_format(self, workflow: N8NWorkflow) -> Dict[str, Any]:
        """
        Convert N8NWorkflow to Jarvis tool JSON format.
        
        Args:
            workflow: N8NWorkflow object
        
        Returns:
            Tool definition dict
        """
        return {
            "enabled": True,
            "name": f"n8n_{workflow.name}",
            "description": workflow.description,
            "script": None,  # No local script - calls webhook
            "webhook_url": f"{self.n8n_url}/webhook/{workflow.webhook_path}",
            "parameters": {
                "type": "object",
                "properties": workflow.parameters,
                "required": []  # Make all params optional by default
            },
            "permissions": {
                "dangerous": False,
                "bash": False,
                "network": True,
                "auto_approve": True
            },
            "metadata": {
                "source": "n8n_workflow",
                "workflow_id": workflow.id,
                "auto_discovered": True
            }
        }


def main():
    """Test discovery."""
    n8n_url = get_config_value('N8N_URL', 'http://localhost:5678')
    api_key = get_config_value('N8N_API_KEY', '')
    
    discovery = N8NWorkflowDiscovery(n8n_url, api_key if api_key else None)
    workflows = discovery.discover_workflows()
    
    print(f"📡 Discovered {len(workflows)} n8n workflows with webhooks:\n")
    
    for wf in workflows:
        print(f"  {wf.name}")
        print(f"    Path: /webhook/{wf.webhook_path}")
        print(f"    Description: {wf.description}")
        if wf.parameters:
            print(f"    Parameters: {list(wf.parameters.keys())}")
        print()


if __name__ == "__main__":
    main()
```

#### Step 2: Integrate with ToolRegistry

**File:** `lib/tool_schema.py` (add method)

```python
def _discover_n8n_workflows(self):
    """Discover n8n workflows and add as tools."""
    n8n_url = os.environ.get('N8N_URL')
    
    if not n8n_url:
        return  # n8n not configured
    
    try:
        from n8n_discovery import N8NWorkflowDiscovery
        
        api_key = os.environ.get('N8N_API_KEY')
        discovery = N8NWorkflowDiscovery(n8n_url, api_key)
        workflows = discovery.discover_workflows()
        
        for wf in workflows:
            tool_def = discovery.to_jarvis_tool_format(wf)
            
            # Create Tool object
            tool = Tool(
                name=tool_def['name'],
                description=tool_def['description'],
                parameters=tool_def['parameters'],
                permissions=tool_def['permissions'],
                script=None,  # Webhook-based
                enabled=True,
                metadata=tool_def['metadata']
            )
            
            # Add to registry
            self.tools[tool.name] = tool
        
        if workflows:
            print(f"✅ Loaded {len(workflows)} n8n workflow tools")
    
    except Exception as e:
        print(f"⚠️  n8n workflow discovery failed: {e}", file=sys.stderr)
```

**Call in `__init__`:**
```python
def __init__(self, skills_dir, mcp_config_path=None):
    self.skills_dir = skills_dir
    self.mcp_config_path = mcp_config_path
    self.tools = {}
    self.mcp_manager = None
    
    self._discover_local_tools()
    
    if mcp_config_path:
        self._discover_mcp_tools()
    
    # NEW: n8n workflow discovery
    self._discover_n8n_workflows()
```

#### Step 3: Create n8n Workflow Executor

**File:** `lib/n8n_executor.py`

```python
#!/usr/bin/env python3
"""Execute n8n workflow via webhook."""
import requests
from typing import Dict, Any


def execute_n8n_workflow(webhook_url: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute n8n workflow via webhook POST.
    
    Args:
        webhook_url: Full webhook URL
        args: Tool arguments
    
    Returns:
        Result dict with ok, speech, data
    """
    try:
        response = requests.post(
            webhook_url,
            json=args,
            timeout=60
        )
        response.raise_for_status()
        
        # n8n returns result
        result = response.json()
        
        return {
            'ok': True,
            'speech': result.get('speech', 'Workflow executed'),
            'data': result
        }
    
    except Exception as e:
        return {
            'ok': False,
            'error': str(e),
            'speech': f"Workflow failed: {e}"
        }
```

#### Step 4: Update Executor to Handle n8n Tools

**File:** `orchestrator/executor.py`

```python
def _execute_tool_internal(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tool (local script, MCP, or n8n workflow)."""
    tool = self.registry.get_tool(tool_name)
    
    if not tool:
        return self._tool_not_found(tool_name)
    
    # n8n workflow tool (webhook-based)
    if tool.metadata and tool.metadata.get('source') == 'n8n_workflow':
        from n8n_executor import execute_n8n_workflow
        webhook_url = tool.metadata.get('webhook_url')
        return execute_n8n_workflow(webhook_url, args)
    
    # MCP tool
    if tool_name.startswith('mcp_'):
        return self._execute_mcp_tool(tool_name, args)
    
    # Local Python script (existing)
    return self._execute_local_tool(tool, args)
```

#### Step 5: Configuration

**File:** `config/cloud.env` (add)

```bash
# n8n Workflow Discovery
N8N_URL=http://localhost:5678
N8N_API_KEY=  # Optional, if using n8n auth
```

**File:** `config/local.env` (add same)

#### Step 6: Test

```bash
# Start n8n (if not running)
docker run -d -p 5678:5678 --name n8n n8nio/n8n

# Create test workflow in n8n:
# 1. Add Webhook node with path "test_jarvis"
# 2. Add notes: "Test workflow for Jarvis integration"
# 3. Add Function node that returns: { "speech": "Test successful!" }
# 4. Activate workflow

# Test discovery
source ~/jarvis-venv/bin/activate
python3 lib/n8n_discovery.py

# Test with Jarvis
./orchestrator/orchestrator_v2.py cloud "use n8n_test_jarvis"
```

**Expected:**
- n8n workflows auto-discovered on startup
- Voice command "use n8n_test_jarvis" triggers webhook
- Result returned to user

---

## Phase 2: Docker Deployment (2-3 Days)

### 2.1 Create Docker Compose File

**File:** `docker-compose.yaml`

```yaml
version: "3.8"

services:
  # Jarvis API (proactive system)
  jarvis-api:
    build:
      context: .
      dockerfile: Dockerfile.api
    container_name: jarvis-api
    ports:
      - "8880:8880"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./logs:/app/logs
    env_file:
      - ./config/cloud.env
    restart: unless-stopped
    networks:
      - jarvis

  # Jarvis Background Services
  jarvis-services:
    build:
      context: .
      dockerfile: Dockerfile.services
    container_name: jarvis-services
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./logs:/app/logs
    env_file:
      - ./config/cloud.env
    restart: unless-stopped
    depends_on:
      - jarvis-api
    networks:
      - jarvis

  # Jarvis Web UI
  jarvis-web:
    build:
      context: ./jarvis-web
      dockerfile: Dockerfile
    container_name: jarvis-web
    ports:
      - "5001:5001"
    environment:
      - JARVIS_API_URL=http://jarvis-api:8880
      - NODE_ENV=production
    restart: unless-stopped
    depends_on:
      - jarvis-api
    networks:
      - jarvis

  # Memory Browser UI
  jarvis-memory:
    build:
      context: ./jarvis-memory
      dockerfile: Dockerfile
    container_name: jarvis-memory
    ports:
      - "5002:5002"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    env_file:
      - ./config/cloud.env
    restart: unless-stopped
    networks:
      - jarvis

  # Intelligence Dashboard
  jarvis-intelligence:
    build:
      context: ./jarvis-intelligence
      dockerfile: Dockerfile
    container_name: jarvis-intelligence
    ports:
      - "5003:5003"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    env_file:
      - ./config/cloud.env
    restart: unless-stopped
    networks:
      - jarvis

  # Canvas Viewer
  jarvis-canvas:
    build:
      context: ./jarvis-canvas
      dockerfile: Dockerfile
    container_name: jarvis-canvas
    ports:
      - "8090:8090"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    networks:
      - jarvis

  # Optional: LiveKit Voice (CAAL-inspired)
  livekit:
    image: livekit/livekit-server:latest
    container_name: livekit
    ports:
      - "7880:7880"      # WebSocket
      - "7881:7881"      # WebRTC fallback
      - "50000-50100:50000-50100/udp"  # WebRTC media
    volumes:
      - ./config/livekit.yaml:/livekit.yaml
    command: --config /livekit.yaml
    restart: unless-stopped
    profiles:
      - voice
    networks:
      - jarvis

  # Optional: Speaches STT (for LiveKit)
  speaches:
    image: ghcr.io/matatonic/speaches:latest
    container_name: speaches
    ports:
      - "8000:8000"
    volumes:
      - ./models/whisper:/models
    restart: unless-stopped
    profiles:
      - voice
    networks:
      - jarvis

  # Optional: Kokoro TTS (for LiveKit)
  kokoro:
    image: ghcr.io/remsky/kokoro-fastapi:latest
    container_name: kokoro
    ports:
      - "8880:8880"
    restart: unless-stopped
    profiles:
      - voice
    networks:
      - jarvis

  # Optional: Grafana Monitoring
  grafana:
    image: grafana/grafana:latest
    container_name: jarvis-grafana
    ports:
      - "3001:3000"
    volumes:
      - ./monitoring/grafana:/etc/grafana/provisioning
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    restart: unless-stopped
    profiles:
      - monitoring
    networks:
      - jarvis

  # Optional: Prometheus
  prometheus:
    image: prom/prometheus:latest
    container_name: jarvis-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus:/etc/prometheus
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: unless-stopped
    profiles:
      - monitoring
    networks:
      - jarvis

networks:
  jarvis:
    driver: bridge

volumes:
  grafana-data:
  prometheus-data:
```

### 2.2 Create Dockerfiles

**File:** `Dockerfile.api`

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    ffmpeg \
    sox \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY lib /app/lib
COPY orchestrator /app/orchestrator
COPY skills /app/skills
COPY jarvis-api /app/jarvis-api
COPY bin /app/bin

# Create directories
RUN mkdir -p /app/data /app/logs /app/config

# Expose port
EXPOSE 8880

# Run API server
CMD ["python3", "/app/jarvis-api/server.py"]
```

**File:** `Dockerfile.services`

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Same base as API
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lib /app/lib
COPY services /app/services
COPY bin /app/bin

RUN mkdir -p /app/data /app/logs /app/config

CMD ["python3", "/app/services/daemon.py"]
```

### 2.3 Usage

```bash
# Basic deployment (API + Web UI + Dashboards)
docker compose up -d

# With LiveKit voice
docker compose --profile voice up -d

# With monitoring
docker compose --profile monitoring up -d

# Everything
docker compose --profile voice --profile monitoring up -d

# View logs
docker compose logs -f jarvis-api

# Restart services
docker compose restart jarvis-api

# Stop everything
docker compose down
```

---

## Phase 3: LiveKit Voice Mode (2-3 Days)

### 3.1 Add LiveKit Agent

**File:** `bin/jarvis-voice-livekit.py`

```python
#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LiveKit Mode (CAAL-inspired)
Real-time full-duplex voice conversation using LiveKit.
"""
import os
import sys
import asyncio
from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config


async def entrypoint(ctx: JobContext):
    """LiveKit agent entrypoint."""
    # Connect to room
    await ctx.connect()
    
    # Setup STT, TTS, LLM
    # TODO: Implement LiveKit integration
    pass


if __name__ == "__main__":
    load_config('cloud')
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

**Note:** This requires LiveKit Python SDK and significant implementation. See CAAL's `voice_agent.py` for reference.

---

## Testing Checklist

### Phase 1 Tests

- [ ] `/announce` endpoint works
  ```bash
  curl -X POST http://localhost:8880/announce \
    -H "Content-Type: application/json" \
    -d '{"message": "Test"}'
  ```

- [ ] n8n workflow discovery works
  ```bash
  python3 lib/n8n_discovery.py
  ```

- [ ] n8n workflow execution works
  ```bash
  ./orchestrator/orchestrator_v2.py cloud "use n8n_test_workflow"
  ```

### Phase 2 Tests

- [ ] Docker Compose builds successfully
  ```bash
  docker compose build
  ```

- [ ] All services start
  ```bash
  docker compose up -d
  docker compose ps
  ```

- [ ] Web UI accessible at http://localhost:5001

- [ ] API accessible at http://localhost:8880/health

### Phase 3 Tests

- [ ] LiveKit server starts
- [ ] Voice agent connects
- [ ] Full-duplex conversation works

---

## Rollback Plan

If any integration causes issues:

1. **Phase 1:** Remove `/announce` route, comment out `_discover_n8n_workflows()`
2. **Phase 2:** Use native install (existing `./jarvis` scripts work unchanged)
3. **Phase 3:** LiveKit is optional, doesn't affect core functionality

---

## Conclusion

This guide implements CAAL's best features while maintaining Jarvis's superior architecture. Start with Phase 1 (quick wins), then Phase 2 (Docker), then Phase 3 (LiveKit) if needed.

**Total Effort:** 4-6 days for all phases.

