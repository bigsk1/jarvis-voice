# Jarvis Playground Design Document

> **Status:** Self-Play IMPLEMENTED, others planned  
> **Last Updated:** 2025-12-02  
> **Purpose:** Design doc for testing, training, and experimental Jarvis environments

---

## Table of Contents

1. [Overview](#overview)
2. [Goals](#goals)
3. [Architecture Options](#architecture-options)
4. [Self-Play System (P0)](#self-play-system-p0)
5. [Jarvis VM Workspace (P1)](#jarvis-vm-workspace-p1)
6. [Dockerized Jarvis Image (P1)](#dockerized-jarvis-image-p1)
7. [Digital Twin - Carvis (P2)](#digital-twin---carvis-p2)
8. [Web UI Playground (P3)](#web-ui-playground-p3)
9. [Implementation Priority](#implementation-priority)
10. [Decision Log](#decision-log)

---

## Overview

The Jarvis Playground encompasses several related concepts for testing, training, and experimenting with Jarvis without impacting the production system.

### Core Ideas

| Concept | Purpose | Isolation Level |
|---------|---------|-----------------|
| **Self-Play** | Generate training data, find gaps, trigger evolution | Process (tmux/subprocess) |
| **Jarvis VM** | Dedicated workspace for Jarvis to do work | VM (Proxmox) |
| **Docker Image** | Reproducible, portable deployment | Container |
| **Digital Twin** | Experimental fork for risky changes | Separate instance |

### What Actually Produces Improvements?

```
┌─────────────────────────────────────────────────────────────────┐
│                    IMPROVEMENT CYCLE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Query Generator ──► Self-Play ──► Feedback ──► Evolution      │
│         │                              │              │          │
│         │                              ▼              ▼          │
│         │                        Gap Detector   Better Prompts   │
│         │                              │                         │
│         │                              ▼                         │
│         │                        Tool Builder                    │
│         │                              │                         │
│         └──────────────────────────────┴─────────────────────────│
│                                                                  │
│   RESULT: Jarvis gets smarter, faster, more capable              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Goals

### Primary Goals

1. **Find tool gaps** - Identify where dedicated tools would beat Brave search
2. **Generate diverse training data** - Novel queries, not repetitive history
3. **Trigger evolution** - Feed the feedback/evolution loop with real scenarios
4. **Safe experimentation** - Break things without affecting production

### Non-Goals (For Now)

- Full production deployment in Docker (audio is problematic)
- Multi-user support
- Public-facing demo

---

## Architecture Options

### Option A: Simple (tmux/subprocess)

```
Production Jarvis
      │
      └── Self-Play Process (same machine)
          ├── Runs queries silently (no TTS)
          ├── Uses same code, different DB path
          └── Logs to separate directory
```

**Pros:** Simple, no infrastructure changes  
**Cons:** Not fully isolated, shares resources

### Option B: Docker Container

```
┌─────────────────────────────────────────────────────────────────┐
│                    HOST MACHINE                                  │
│  /home/boss/jarvis-voice (production)                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │     READ-ONLY MOUNTS      │
              │  - /skills                │
              │  - /lib                   │
              │  - /orchestrator          │
              │  - /config/*.example      │
              └─────────────┬─────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                 PLAYGROUND CONTAINER                             │
│  - Own /data volume (separate DBs)                              │
│  - Own /logs volume                                             │
│  - CLI ONLY (no audio - Docker audio is problematic)            │
│  - OpenCode DISABLED                                            │
│  - Email/Webhook tools → disabled or mocked                     │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:** Full isolation, reproducible  
**Cons:** CLI only (audio in Docker is horrible), MCP containers need setup

### Option C: Proxmox VM

```
┌─────────────────────────────────────────────────────────────────┐
│                         PROXMOX HOST                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Mini PC (jarvis-prod)         VM: jarvis-workspace              │
│  ├── Voice I/O                 ├── Ubuntu Server                 │
│  ├── Main Jarvis               ├── SSH access for Jarvis         │
│  └── Real credentials          ├── OpenCode (separate install)   │
│                                └── Heavy compute tasks           │
│                                                                  │
│                                VM: jarvis-playground             │
│                                ├── Sandbox testing               │
│                                ├── Can be snapshot/restored      │
│                                └── Isolated network (optional)   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:** Full OS isolation, snapshot/restore, dedicated resources  
**Cons:** More infrastructure, OpenCode needs fresh setup in VM

### Option D: Hybrid

```
Mini PC (voice + main orchestration)
    │
    ├── Self-Play (local process, simple)
    │
    └── SSH to Proxmox VMs (for heavy tasks)
        ├── jarvis-workspace (OpenCode, builds)
        └── jarvis-playground (experiments)
```

**Pros:** Best of all worlds  
**Cons:** Complexity

---

## Self-Play System (P0)

### Difference from Existing Tests

| Aspect | `test-all-tools.sh` | Self-Play |
|--------|---------------------|-----------|
| **Queries** | Predefined, static | Novel, LLM-generated |
| **Purpose** | Verify functionality | Find gaps, trigger evolution |
| **Feedback** | Pass/fail | Full feedback grading (1-5) |
| **Output** | Test report | Insights, tool gaps, evolution triggers |

### Components

#### 1. Query Generator

```python
# lib/self_play.py

QUERY_CATEGORIES = {
    "productivity": {
        "examples": [
            "Schedule a meeting for next Tuesday",
            "What's on my calendar this week?",
            "Remind me to call the dentist",
        ],
        "weight": 0.2,  # 20% of queries
    },
    "research": {
        "examples": [
            "Compare PostgreSQL vs MySQL",
            "What are the pros and cons of Kubernetes?",
            "Latest trends in home automation",
        ],
        "weight": 0.25,
    },
    "information": {
        "examples": [
            "What's the weather forecast?",
            "Current Bitcoin price",
            "What time is it in Tokyo?",
        ],
        "weight": 0.2,
    },
    "coding": {
        "examples": [
            "How do I parse JSON in Python?",
            "Explain async/await",
            "Best practices for error handling",
        ],
        "weight": 0.15,
    },
    "home_automation": {
        "examples": [
            "Turn off the lights",
            "What's the temperature inside?",
            "Is the garage door open?",
        ],
        "weight": 0.1,
    },
    "general": {
        "examples": [
            "Tell me a joke",
            "What's the capital of France?",
            "How far is the moon?",
        ],
        "weight": 0.1,
    },
}

# LLM generates variations, NOT pulled from history
# Filters: No emails, reminders, alerts, webhooks (action queries)
```

#### 2. Gap Detector

```python
def analyze_tool_gaps(session_logs: List[dict]) -> List[dict]:
    """
    Analyze self-play session to find tool gaps.
    
    A "gap" is when Brave search is used repeatedly
    for similar queries that could have a dedicated tool.
    """
    brave_queries = []
    
    for log in session_logs:
        tools = log.get("tools_used", [])
        if any("brave" in t.lower() for t in tools):
            brave_queries.append({
                "query": log["query"],
                "category": classify_query(log["query"]),
            })
    
    # Cluster by category
    gaps = defaultdict(list)
    for q in brave_queries:
        gaps[q["category"]].append(q["query"])
    
    # Flag categories with 3+ queries
    tool_gaps = []
    for category, queries in gaps.items():
        if len(queries) >= 3:
            tool_gaps.append({
                "pattern": category,
                "query_count": len(queries),
                "example_queries": queries[:5],
                "suggestion": f"Consider dedicated '{category}' tool",
            })
    
    return tool_gaps
```

#### 3. Execution Runner

```python
def run_self_play_session(
    num_queries: int = 50,
    mode: str = "cloud",
    silent: bool = True,  # No TTS
) -> dict:
    """
    Run a self-play session.
    
    1. Generate novel queries
    2. Execute through orchestrator
    3. Auto-trigger feedback on each
    4. Analyze for gaps
    5. Return summary
    """
    queries = generate_novel_queries(num_queries)
    results = []
    
    for query in queries:
        result = execute_query(query, mode, silent=silent)
        
        # Auto-trigger feedback
        feedback = collect_feedback(query, result)
        
        results.append({
            "query": query,
            "result": result,
            "feedback": feedback,
        })
    
    # Analyze
    gaps = analyze_tool_gaps(results)
    low_ratings = [r for r in results if r["feedback"]["rating"] < 4]
    
    # Safe average calculation (avoid division by zero)
    avg_rating = (
        sum(r["feedback"]["rating"] for r in results) / len(results)
        if results else 0.0
    )
    
    return {
        "total_queries": num_queries,
        "avg_rating": avg_rating,
        "low_ratings": len(low_ratings),
        "tool_gaps": gaps,
        "evolution_triggered": check_evolution_triggered(),
    }
```

### CLI Usage

```bash
# Run self-play session
./bin/jarvis-self-play --queries 50 --mode cloud

# Output:
# Self-Play Session Started
# ├── Generating 50 novel queries...
# │   ├── productivity: 10
# │   ├── research: 12
# │   ├── information: 10
# │   ├── coding: 8
# │   ├── home_automation: 5
# │   └── general: 5
# ├── Executing queries...
# │   ├── [====================] 50/50
# │   ├── Avg response time: 12.3s
# │   └── Avg rating: 3.8
# ├── Analyzing gaps...
# │   ├── TOOL GAP: weather (5 queries hit Brave)
# │   └── TOOL GAP: stock_prices (3 queries hit Brave)
# └── Summary:
#     ├── Low ratings (<4): 12
#     ├── Evolution triggered: Yes
#     └── Tool gaps found: 2

# View results
./bin/jarvis-self-play results --session latest

# Schedule nightly (cron)
# 0 3 * * * /home/boss/jarvis-voice/bin/jarvis-self-play --queries 100 --mode cloud
```

---

## Jarvis VM Workspace (P1)

### Purpose

A dedicated Ubuntu Server VM that Jarvis can SSH into for:
- Running OpenCode projects (isolated from host)
- Executing untrusted code
- Heavy builds/compiles
- Testing tool scripts before deployment

### Setup

```bash
# Proxmox VM creation
qm create 105 --name jarvis-workspace --memory 4096 --cores 2
qm set 105 --scsi0 local-lvm:32
qm set 105 --net0 virtio,bridge=vmbr0
# Install Ubuntu Server 24.04

# In VM - create jarvis user
sudo adduser jarvis
sudo usermod -aG sudo jarvis

# SSH key setup (from mini PC)
ssh-copy-id jarvis@jarvis-workspace

# Pre-install common tools
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm docker.io git
```

### OpenCode in VM

OpenCode needs a fresh setup in the VM since it's a separate program:

```bash
# In VM
cd ~
git clone <opencode-repo> opencode
cd opencode
# Follow OpenCode setup...

# Configure to use jarvis-workspace directory
export OPENCODE_WORKSPACE=/home/jarvis/workspace
```

### Jarvis Tool: `vm_workspace`

```python
# skills/vm_workspace.py

def ssh_execute(command: str, timeout: int = 60) -> dict:
    """
    Execute command on jarvis-workspace VM.
    
    Safety:
    - Whitelisted VM only
    - All commands logged
    - Timeout enforced
    - No sudo unless explicitly allowed per command
    """
    result = subprocess.run(
        ["ssh", "jarvis@jarvis-workspace", command],
        capture_output=True,
        timeout=timeout,
        text=True,
    )
    
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }
```

### Use Cases

1. **OpenCode Projects**
   ```
   User: "Build me a Flask API for todo lists"
   Jarvis → SSH to workspace → Run OpenCode → Return result
   ```

2. **Code Execution**
   ```
   User: "Run this Python script"
   Jarvis → SSH to workspace → Execute in sandbox → Return output
   ```

3. **System Tasks**
   ```
   User: "Check disk space on the workspace"
   Jarvis → SSH → df -h → Return result
   ```

---

## Dockerized Jarvis Image (P1)

### Purpose

A reproducible, portable Jarvis deployment for:
- Testing in isolation
- Deploying to other machines
- Version-controlled releases
- CI/CD pipelines

### Limitations

**CLI ONLY** - Audio in Docker is problematic:
- Microphone passthrough is complex
- Speaker output often sounds terrible
- WebUI with browser audio would need:
  - localhost only (CORS issues from LAN)
  - Additional web server component

### Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . /app

# Create data directories
RUN mkdir -p /app/data /app/logs

# Default environment
ENV MODE=cloud
ENV OPENCODE_ENABLED=false
ENV DANGEROUS_TOOLS_DISABLED=true

# Entry point
ENTRYPOINT ["python", "orchestrator/orchestrator_v2.py"]
CMD ["cloud", "--help"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  jarvis:
    build: .
    volumes:
      # Config (read-only, use examples or provide real)
      - ./config/cloud.env.example:/app/config/cloud.env:ro
      
      # Persistent data
      - jarvis-data:/app/data
      - jarvis-logs:/app/logs
      
    environment:
      - MODE=cloud
      - OPENCODE_ENABLED=false
      
    # For interactive CLI
    stdin_open: true
    tty: true

volumes:
  jarvis-data:
  jarvis-logs:
```

### Usage

```bash
# Build
docker build -t jarvis:latest .

# Run single query
docker run --rm jarvis:latest cloud "What time is it?"

# Interactive session
docker run -it --rm jarvis:latest

# With real config
docker run --rm \
  -v $(pwd)/config/cloud.env:/app/config/cloud.env:ro \
  jarvis:latest cloud "Search for Bitcoin news"
```

### MCP Servers in Docker

MCP servers are Docker-based, so running Jarvis in Docker creates "Docker in Docker" complexity:

**Option A:** Mount Docker socket (security risk)
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**Option B:** Run MCP servers on host, Jarvis connects via network
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Option C:** Disable MCP tools in Docker version (simplest)
```yaml
environment:
  - MCP_ENABLED=false
```

---

## Digital Twin - Carvis (P2)

### Concept

A separate Jarvis instance with different system prompt that can:
- Try experimental approaches
- Break without affecting production
- Be destroyed and recreated from base image

### Architecture

```
┌─────────────────┐          ┌─────────────────┐
│     JARVIS      │          │     CARVIS      │
│   (Production)  │          │   (Experiment)  │
├─────────────────┤          ├─────────────────┤
│ Stable prompts  │          │ Experimental    │
│ Verified tools  │          │ New tools       │
│ Real data       │          │ Sandbox data    │
│ Conservative    │          │ Risk-taking     │
└────────┬────────┘          └────────┬────────┘
         │                            │
         │      ┌─────────────┐       │
         └─────►│   SYNC      │◄──────┘
                │  (manual)   │
                └─────────────┘
```

### Different System Prompt

```python
CARVIS_SYSTEM_PROMPT = """
You are Carvis, an experimental version of Jarvis.

Your purpose:
- Try new approaches that might fail
- Test edge cases aggressively
- Report detailed logs of what worked and what didn't
- You CAN fail - that's expected and valuable

Differences from Jarvis:
- More willing to try multiple tool combinations
- Verbose logging of decision process
- No real emails/webhooks (mocked)
- Can be reset to clean state anytime

After each interaction, include a brief "experiment notes" section
describing what you tried and whether it worked.
"""
```

### Workflow

1. **Deploy:** Spin up Carvis from base Jarvis image
2. **Experiment:** Run queries, try new tools
3. **Analyze:** Review logs, find improvements
4. **Promote:** If something works, apply to Jarvis
5. **Reset:** Destroy Carvis, spin up fresh

---

## Web UI Playground (P3)

### Concept

A visual interface for:
- Manual query testing
- Watching execution traces
- Viewing gap analysis
- Triggering dream sessions

### Challenges

1. **Audio in browser:**
   - Would need WebRTC for voice
   - CORS issues if not on localhost
   - Additional complexity

2. **Alternative:** Keep Canvas UI, add testing features there
   - `localhost:8890/playground`
   - Text input only (no voice)
   - Visual execution trace

### Possible Implementation

```
Jarvis Canvas (existing)
└── /playground (new route)
    ├── Query input box
    ├── "Run" / "Run 10 variants" / "Dream mode" buttons
    ├── Live execution trace panel
    ├── Gap analysis panel
    └── Session history
```

---

## Implementation Priority

| Priority | Feature | Effort | Impact | Status |
|----------|---------|--------|--------|--------|
| **P0** | Self-Play System | 1-2 days | High | ✅ **IMPLEMENTED** |
| **P1** | Jarvis VM Workspace | 1 day | Medium | Planned |
| **P1** | Dockerized Image | 1 day | Medium | Planned |
| **P2** | Digital Twin (Carvis) | 2-3 days | Medium | Future |
| **P3** | Web UI Playground | 1 week | Low | Future |

### Recommended Order

1. **Week 1:** Self-Play System
   - Query generator
   - Gap detector
   - Integration with feedback/evolution

2. **Week 2:** Infrastructure
   - Jarvis VM setup
   - Docker image
   - CI/CD basics

3. **Later:** Experimental
   - Carvis twin
   - Web UI additions

---

## Decision Log

### 2025-12-02: Initial Design

**Decision:** Start with Self-Play (P0) before infrastructure

**Rationale:**
- Self-play directly feeds the existing feedback/evolution loop
- No infrastructure changes needed
- Immediate value (finds gaps, triggers improvements)
- Docker/VM can come later for isolation

**Decision:** Docker = CLI only, no audio

**Rationale:**
- Docker audio is problematic (complex setup, poor quality)
- WebUI with browser audio has CORS issues from LAN
- CLI is sufficient for testing/automation
- Voice stays on mini PC (production)

**Decision:** OpenCode in VM needs fresh setup

**Rationale:**
- OpenCode is a separate program with server + plugin
- Can't just mount from host
- VM provides true isolation for code execution
- Worth the setup effort for safety

---

## Related Documentation

- [ADVANCED_AI_TECHNIQUES.md](ADVANCED_AI_TECHNIQUES.md) - Self-evolving system
- [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) - Feedback loop
- [TOOL_BUILDER.md](TOOL_BUILDER.md) - Dynamic tool creation
- [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) - Self-learning

---

**Document Version:** 1.0  
**Author:** Planning Session 2025-12-02

