# OpenCode Plugin Ideas for Jarvis Integration

> **Architecture Philosophy**: Jarvis is the top-level orchestrator ($$$ model), OpenCode is a specialized subordinate agent ($$ model). Plugins should **enhance capabilities** and **enforce boundaries**, not blur the hierarchy.

**Last Updated**: November 15, 2025

---

## 🏛️ Architecture Hierarchy

```
┌─────────────────────────────────────┐
│ Jarvis (Claude Sonnet 4.5)         │  ← Top-level agent, best model
│ - Orchestration                     │  ← Decides what to remember
│ - Memory management                 │  ← Accesses all tools
│ - User interaction                  │  ← Makes final decisions
└──────────────┬──────────────────────┘
               │ delegates to
               ▼
┌─────────────────────────────────────┐
│ OpenCode (Claude Sonnet 4 / Qwen)  │  ← Specialized coding agent
│ - Code generation                   │  ← Reports back to Jarvis
│ - Project building                  │  ← No direct memory access
│ - Testing/debugging                 │  ← Works in sandbox
└──────────────┬──────────────────────┘
               │ future: may delegate to
               ▼
┌─────────────────────────────────────┐
│ OpenCode Sub-agents (Qwen/cheaper) │  ← Hyper-specialized tasks
│ - Formatting                        │  ← Even cheaper models
│ - Documentation                     │  ← Specific subtasks
│ - Testing                           │
└─────────────────────────────────────┘
```

**Key Principle**: Information flows **UP** (OpenCode → Jarvis → User), decisions flow **DOWN** (User → Jarvis → OpenCode).

---

## 🛡️ Priority 1: Safety & Boundaries

### 1. **Workspace Protection Plugin** ⭐⭐⭐⭐⭐
**Purpose**: Prevent OpenCode from damaging system or Jarvis codebase

**Location**: `~/.config/opencode/plugin/workspace-protection.js`

**Features**:
- Block `write`, `edit`, `delete` operations outside `/home/boss/jarvis-workspace`
- Block any access to `/home/boss/jarvis-voice` (Jarvis codebase)
- Block system directories (`/etc`, `/usr`, `/bin`, `/home/boss/.config` except opencode)
- Allow read-only access for reference (e.g., reading Jarvis code to understand APIs)

**Use Case**:
```
User → Jarvis: "Use opencode to Fix the bug in orchestrator_v2.py"
Jarvis → OpenCode: "Analyze and suggest fix"
OpenCode: Tries to write file → BLOCKED by plugin
OpenCode: Returns suggestion to Jarvis
Jarvis: Decides whether to apply fix
```

**Benefit**: Essential safety layer, especially for local models that may ignore system prompts.

---

### 2. **Environment File Protection** ⭐⭐⭐
**Purpose**: Prevent accidental API key exposure

**Features**:
- Block reading any `.env`, `*.env`, `config/*.env` files
- Allow reading `.env.example` files
- Log attempts to access env files (report to Jarvis)

**Benefit**: Defense-in-depth for sensitive credentials.

---

## 🐳 Priority 2: Sandbox & Testing

### 3. **Docker Sandbox Plugin** ⭐⭐⭐⭐⭐
**Purpose**: Execute untrusted code in isolated containers

**Location**: `~/.config/opencode/plugin/docker-sandbox.js`

**Custom Tools**:
```typescript
tool: {
  run_in_sandbox: tool({
    description: "Execute code/commands in isolated Docker container",
    args: {
      image: tool.schema.enum(["python:3.11", "node:20", "ubuntu:22.04"]),
      script: tool.schema.string(),
      timeout: tool.schema.number().default(30),
      network: tool.schema.boolean().default(false)  // Disable network by default
    },
    async execute(args, ctx) {
      // Create temp directory with code
      // docker run --rm -v /tmp/code:/code --network none python:3.11 python /code/script.py
      // Return output + exit code
    }
  }),
  
  test_in_sandbox: tool({
    description: "Run tests for a project in sandbox",
    args: {
      project_path: tool.schema.string(),
      test_command: tool.schema.string()
    },
    async execute(args) {
      // docker run --rm -v project:/app -w /app node:20 npm test
    }
  })
}
```

**Use Cases**:
- "Jarvis, test this Python script in a sandbox before running it"
- "Jarvis, run this npm package installation in an isolated container"
- "Jarvis, execute this shell script safely"
- "Jarvis, test if this code has any security issues"

**Benefit**: Safe execution of untrusted/experimental code without risk to system.

---

### 4. **Smart Port Allocation Plugin** ⭐⭐⭐⭐
**Purpose**: Intelligently find available ports, not just validate ranges

**Custom Tool**:
```typescript
tool: {
  allocate_port: tool({
    description: "Find and allocate an available port",
    args: {
      preferred_range_start: tool.schema.number().default(8091),
      preferred_range_end: tool.schema.number().default(8199),
      service_name: tool.schema.string()  // For documentation
    },
    async execute(args) {
      // Check ports 8091-8199
      for (let port = args.preferred_range_start; port <= args.preferred_range_end; port++) {
        const available = await checkPort(port)  // curl, nc, or node net.connect
        if (available) {
          // Log allocation to Jarvis logs
          return { port, available: true, service: args.service_name }
        }
      }
      throw new Error("No ports available in range")
    }
  }),
  
  check_port_status: tool({
    description: "Check if a specific port is responding (for testing/troubleshooting)",
    args: {
      port: tool.schema.number(),
      expected_response: tool.schema.string().optional()
    },
    async execute(args) {
      // curl localhost:port or nc -zv localhost port
      // Return: listening, responding, status_code, response_body
    }
  })
}
```

**Use Cases**:
- "Jarvis, build a Flask API" → OpenCode allocates port 8091 (first available)
- "Jarvis, is the API on port 8092 responding?" → OpenCode checks, returns 200 OK
- "Jarvis, start another service" → OpenCode allocates port 8093 (8091-8092 busy)

**Benefit**: Automatic port management, no conflicts, works for testing existing services too.

---

## 📊 Priority 3: Enhanced Telemetry & Logging

### 5. **Detailed Build Logger Plugin** ⭐⭐⭐⭐
**Purpose**: Track what OpenCode does, feed structured data back to Jarvis

**Hooks**:
```javascript
event: async ({ event }) => {
  const logger = await import('/home/boss/jarvis-voice/lib/opencode_logger.js')
  
  if (event.type === "session.start") {
    logger.logSessionStart({
      session_id: event.sessionId,
      task: event.task,
      model: event.model,
      timestamp: Date.now()
    })
  }
  
  if (event.type === "tool.execute") {
    logger.logToolExecution({
      session_id: event.sessionId,
      tool: event.tool,
      args: event.args,
      result: event.result,
      duration_ms: event.duration
    })
  }
  
  if (event.type === "session.idle") {
    logger.logSessionComplete({
      session_id: event.sessionId,
      files_created: event.filesCreated,
      files_modified: event.filesModified,
      ports_used: extractPorts(event),
      git_commits: event.commits,
      duration_ms: event.totalDuration,
      success: event.success
    })
  }
}
```

**Benefit**: Jarvis gets structured telemetry, not just text responses. Can query "what files did OpenCode create?" directly.

---

### 6. **Resource Monitor Plugin** ⭐⭐⭐
**Purpose**: Track resource usage (CPU, memory, disk) during OpenCode execution

**Custom Tool**:
```typescript
tool: {
  get_resource_usage: tool({
    description: "Get current resource usage stats",
    async execute() {
      // Return: cpu_percent, memory_mb, disk_usage, active_processes
    }
  })
}
```

**Benefit**: Jarvis can warn user "OpenCode is using 8GB RAM, may slow down" or detect runaway processes.

---

## 🔧 Priority 4: Productivity Tools (Beyond Coding)

### 7. **Web Research Plugin** ⭐⭐⭐⭐
**Purpose**: OpenCode as a research assistant, not just coder

**Custom Tools**:
```typescript
tool: {
  scrape_website: tool({
    description: "Extract structured data from websites",
    args: {
      url: tool.schema.string(),
      selectors: tool.schema.array(tool.schema.string()),  // CSS selectors
      output_format: tool.schema.enum(["json", "markdown", "csv"])
    },
    async execute(args) {
      // Use puppeteer/cheerio to extract data
      // Return structured data
    }
  }),
  
  download_file: tool({
    description: "Download files to workspace",
    args: {
      url: tool.schema.string(),
      filename: tool.schema.string()
    },
    async execute(args) {
      // Download to jarvis-workspace/downloads/
      // Validate file type, size limits
    }
  }),
  
  analyze_webpage: tool({
    description: "Analyze webpage structure, extract key info",
    args: {
      url: tool.schema.string()
    },
    async execute(args) {
      // Return: title, meta, headings, links, images, word_count, technologies_detected
    }
  })
}
```

**Use Cases**:
- "Jarvis, scrape the pricing data from competitor websites"
- "Jarvis, download all PDFs from this research page"
- "Jarvis, analyze the structure of example.com and create a similar layout"

---

### 8. **Document Processing Plugin** ⭐⭐⭐⭐
**Purpose**: Process PDFs, images, spreadsheets

**Custom Tools**:
```typescript
tool: {
  extract_pdf_text: tool({
    description: "Extract text from PDF files",
    args: {
      file_path: tool.schema.string(),
      pages: tool.schema.string().optional()  // "1-5" or "all"
    }
  }),
  
  convert_document: tool({
    description: "Convert between document formats",
    args: {
      input_file: tool.schema.string(),
      output_format: tool.schema.enum(["pdf", "docx", "md", "html", "txt"])
    }
  }),
  
  extract_tables: tool({
    description: "Extract tables from PDFs/images as CSV",
    args: {
      file_path: tool.schema.string()
    }
  }),
  
  ocr_image: tool({
    description: "Extract text from images (OCR)",
    args: {
      image_path: tool.schema.string(),
      language: tool.schema.string().default("eng")
    }
  })
}
```

**Use Cases**:
- "Jarvis, extract all the tables from this financial report PDF"
- "Jarvis, convert these Word docs to Markdown"
- "Jarvis, read the text from this screenshot"

---

### 9. **Data Analysis Plugin** ⭐⭐⭐⭐
**Purpose**: OpenCode as data analyst

**Custom Tools**:
```typescript
tool: {
  analyze_csv: tool({
    description: "Generate statistics and insights from CSV",
    args: {
      file_path: tool.schema.string(),
      operations: tool.schema.array(tool.schema.enum([
        "summary", "correlations", "outliers", "visualize"
      ]))
    }
  }),
  
  query_data: tool({
    description: "SQL-like queries on CSV/JSON files",
    args: {
      file_path: tool.schema.string(),
      query: tool.schema.string()  // "SELECT * WHERE price > 100"
    }
  }),
  
  generate_chart: tool({
    description: "Create charts from data",
    args: {
      data: tool.schema.object(),
      chart_type: tool.schema.enum(["line", "bar", "pie", "scatter"]),
      output_file: tool.schema.string()
    }
  })
}
```

**Use Cases**:
- "Jarvis, analyze this sales data CSV and find trends"
- "Jarvis, show me all entries where revenue > $10k"
- "Jarvis, create a bar chart of monthly sales"

---

### 10. **System Monitoring Plugin** ⭐⭐⭐
**Purpose**: OpenCode as system administrator

**Custom Tools**:
```typescript
tool: {
  check_service_status: tool({
    description: "Check if system services are running",
    args: {
      service_names: tool.schema.array(tool.schema.string())
    }
  }),
  
  monitor_logs: tool({
    description: "Watch log files for patterns",
    args: {
      log_path: tool.schema.string(),
      pattern: tool.schema.string(),
      tail_lines: tool.schema.number().default(100)
    }
  }),
  
  disk_usage_report: tool({
    description: "Analyze disk usage and find large files",
    args: {
      path: tool.schema.string().default("/home/boss"),
      min_size_mb: tool.schema.number().default(100)
    }
  })
}
```

**Use Cases**:
- "Jarvis, check if nginx and postgres are running"
- "Jarvis, watch the API logs for errors"
- "Jarvis, find what's taking up disk space"

---

### 11. **Automation Workflow Plugin** ⭐⭐⭐⭐
**Purpose**: OpenCode executes multi-step workflows

**Custom Tools**:
```typescript
tool: {
  execute_workflow: tool({
    description: "Run predefined automation workflows",
    args: {
      workflow_name: tool.schema.string(),
      parameters: tool.schema.object()
    }
  }),
  
  schedule_task: tool({
    description: "Schedule a task to run later (cron-like)",
    args: {
      command: tool.schema.string(),
      schedule: tool.schema.string(),  // "daily", "hourly", "0 9 * * *"
      task_name: tool.schema.string()
    }
  })
}
```

**Use Cases**:
- "Jarvis, run my daily backup workflow"
- "Jarvis, schedule a reminder to check logs every hour"
- "Jarvis, automate the deployment process"

---

## 🎯 Priority 5: Git & Project Management

### 12. **Smart Git Plugin** ⭐⭐⭐
**Purpose**: Intelligent Git operations with safety checks

**Custom Tools**:
```typescript
tool: {
  smart_commit: tool({
    description: "Analyze changes and create meaningful commit message",
    args: {
      repo_path: tool.schema.string()
    },
    async execute(args) {
      // git diff -> analyze changes -> generate commit message
      // Show user for approval (don't auto-commit)
    }
  }),
  
  branch_summary: tool({
    description: "Summarize what changed in a branch",
    args: {
      branch: tool.schema.string(),
      base_branch: tool.schema.string().default("main")
    }
  })
}
```

---

### 13. **Project Structure Enforcer** ⭐⭐⭐
**Purpose**: Ensure projects follow best practices

**Hooks**:
```javascript
"tool.execute.after": async (input, output) => {
  if (input.tool === "create_file" && output.filePath.endsWith(".py")) {
    // Ensure Python files have proper structure
    // Check for: docstrings, type hints, imports organized
  }
}
```

---

## 🧪 Priority 6: Testing & Quality

### 14. **Auto-Test Generator Plugin** ⭐⭐⭐⭐
**Purpose**: Generate and run tests automatically

**Custom Tools**:
```typescript
tool: {
  generate_tests: tool({
    description: "Generate unit tests for code",
    args: {
      file_path: tool.schema.string(),
      test_framework: tool.schema.enum(["pytest", "jest", "mocha"])
    }
  }),
  
  run_security_scan: tool({
    description: "Scan code for security vulnerabilities",
    args: {
      project_path: tool.schema.string()
    }
  }),
  
  check_dependencies: tool({
    description: "Check for outdated/vulnerable dependencies",
    args: {
      project_path: tool.schema.string()
    }
  })
}
```

---

## 🌐 Priority 7: Network & API Tools

### 15. **API Testing Plugin** ⭐⭐⭐⭐
**Purpose**: Test and document APIs

**Custom Tools**:
```typescript
tool: {
  test_api_endpoint: tool({
    description: "Comprehensive API endpoint testing",
    args: {
      url: tool.schema.string(),
      method: tool.schema.enum(["GET", "POST", "PUT", "DELETE"]),
      headers: tool.schema.object().optional(),
      body: tool.schema.object().optional(),
      expected_status: tool.schema.number().optional()
    }
  }),
  
  generate_api_docs: tool({
    description: "Generate API documentation from OpenAPI spec",
    args: {
      spec_file: tool.schema.string(),
      output_format: tool.schema.enum(["html", "markdown", "pdf"])
    }
  })
}
```

---

## 📝 Implementation Strategy

### Phase 1: Safety First (Week 1)
1. ✅ Workspace Protection Plugin
2. ✅ Environment File Protection
3. ✅ Enhanced logging/telemetry

### Phase 2: Docker Sandbox (Week 2)
1. ✅ Basic Docker sandbox tool
2. ✅ Test execution in isolation
3. ✅ Smart port allocation

### Phase 3: Productivity Tools (Ongoing)
- Start with web research (scraping, downloading)
- Add document processing (PDF, OCR)
- Expand based on real-world usage

### Phase 4: Advanced Features (Future)
- Data analysis tools
- System monitoring
- Workflow automation

---

## 🏗️ Plugin Structure Recommendation

**Global plugins**: `~/.config/opencode/plugin/`
```
plugin/
├── 00-workspace-protection.js    # Load first (safety)
├── 01-env-protection.js          # Security
├── 10-docker-sandbox.js          # Core functionality
├── 11-port-allocation.js         # Networking
├── 20-build-logger.js            # Telemetry
├── 30-web-research.js            # Productivity
├── 31-document-processing.js     # Productivity
└── 99-debug-helpers.js           # Development only
```

**Naming convention**: `NN-feature-name.js` (NN controls load order)

---

## 🎓 Key Insights

### What Makes a Good Plugin for Jarvis + OpenCode?

✅ **Good Plugin Ideas**:
- Extends OpenCode's capabilities beyond coding
- Enforces safety boundaries
- Provides structured data back to Jarvis
- Solves problems that are tedious for humans
- Respects the agent hierarchy

❌ **Bad Plugin Ideas**:
- Gives OpenCode direct access to Jarvis memory (hierarchy violation)
- Duplicates existing Jarvis tools
- Makes decisions that should be Jarvis's responsibility
- Tightly couples OpenCode to Jarvis internals

### The "Bash Execute" Alternative

You mentioned Jarvis's `execute_bash` can run multiple commands:
```bash
cd /home/boss/jarvis-workspace/project && tree -L 3 && ls -la && git status
```

**When to use plugins vs bash**:
- **Bash**: One-off inspection, simple tasks, direct system commands
- **Plugins**: Reusable logic, safety enforcement, complex multi-step operations

Both are valid! Plugins are for repeated workflows and safety, bash is for flexibility.

---

## 🚀 Next Steps

1. **Decide on Phase 1 priorities** (I recommend: workspace protection + docker sandbox)
2. **Choose memory access method** (for logger plugin):
   - Option A: Write to shared log file, Jarvis reads it
   - Option B: HTTP endpoint (overkill for now)
   - Option C: Shared SQLite database (with proper locking)
3. **Test in local mode first** (safer with Qwen model)
4. **Iterate based on real usage**

Ready to implement any of these! Which plugins excite you most? 🎯

