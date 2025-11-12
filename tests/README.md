# Tests Directory

Organized test suite for Jarvis Voice Assistant.

## Structure

```
tests/
├── integration/          # End-to-end integration tests
│   ├── test-all-tools.sh              # Comprehensive cloud mode tests
│   ├── test-all-tools-local.sh        # Comprehensive local mode tests
│   ├── test-opencode-safe.sh          # Safe OpenCode connection tests
│   └── test-opencode-integration.sh   # Full OpenCode integration flow test
├── unit/                # Unit tests (Python)
│   └── (future unit tests)
└── e2e/                 # Full voice pipeline tests
    └── (future e2e tests)
```

## Running Tests

### Integration Tests

```bash
# Cloud mode comprehensive tests
./tests/integration/test-all-tools.sh

# Local mode comprehensive tests
./tests/integration/test-all-tools-local.sh

# Safe OpenCode connection test (no file operations)
./tests/integration/test-opencode-safe.sh

# Full OpenCode integration test (simple tasks)
./tests/integration/test-opencode-integration.sh
```

### Quick Test

```bash
# Single tool test
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Test OpenCode connection
./tests/integration/test-opencode-safe.sh
```

## Test Safety Levels

### 🟢 Safe Tests
- **test-opencode-safe.sh**: Basic connection and config validation
- **test-opencode-integration.sh**: Full flow test with simple tasks (math, greeting)
- **No file operations**
- **No workspace modifications**

### 🟡 Medium Risk Tests (future)
- File listing (read-only)
- Simple file reads
- **Isolated to test workspace**

### 🔴 High Risk Tests (future)
- File creation/modification
- Git operations
- System commands
- **Requires explicit confirmation**

## OpenCode Workspace Behavior

**Important:** OpenCode operates within its configured workspace directory (`~/jarvis-workspace` by default).

### Workspace Isolation
- OpenCode **does NOT** access files outside its workspace by default
- The workspace is separate from Jarvis codebase (`~/jarvis-voice`)
- Each OpenCode session can have its own working directory

### Workspace Structure
```
~/jarvis-workspace/
├── projects/          # Long-term projects
│   ├── websites/
│   ├── scripts/
│   └── experiments/
├── temp/              # Temporary builds (auto-cleanup)
└── deployments/       # Ready artifacts
```

### Safety Notes
- OpenCode **cannot** modify Jarvis codebase files
- OpenCode **can** create/modify files in workspace
- Always test file operations in isolated directories first
- Use `temp/` directory for experimental tests

## Adding New Tests

1. **Safe tests** → `tests/integration/`
2. **Unit tests** → `tests/unit/`
3. **E2E tests** → `tests/e2e/`
4. Mark executable: `chmod +x tests/path/to/test.sh`
5. Use `--json` flag for clean output parsing
6. Include error handling and clear pass/fail messages

