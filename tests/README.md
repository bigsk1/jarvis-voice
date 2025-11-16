# Tests Directory

Organized test suite for Jarvis Voice Assistant.

## Structure

```
tests/
├── integration/          # End-to-end integration tests
│   ├── test-all-tools.sh              # Comprehensive cloud mode tests (MOVED TO ROOT)
│   ├── test-all-tools-local.sh        # Comprehensive local mode tests (MOVED TO ROOT)
│   ├── test-memory-tools.sh           # Memory tool selection tests (NEW)
│   ├── test-memory-real-world.sh      # Complex memory scenarios (NEW)
│   ├── compare-models.sh              # Model comparison framework (NEW)
│   ├── test-opencode-safe.sh          # Safe OpenCode connection tests
│   ├── test-opencode-integration.sh   # Full OpenCode integration flow test
│   └── logs/                          # Test results and AI analysis
├── unit/                # Unit tests (Python)
│   └── (future unit tests)
└── e2e/                 # Full voice pipeline tests
    └── (future e2e tests)
```

**Note**: The main tool test scripts (`test-all-tools.sh`, `test-all-tools-local.sh`) are now in the project root for convenience.

## Running Tests

### Integration Tests

```bash
# All tools (cloud/local)
./test-all-tools.sh        # Cloud mode comprehensive tests
./test-all-tools-local.sh  # Local mode comprehensive tests

# Memory system tests
./tests/integration/test-memory-tools.sh        # Principle-based tool selection
./tests/integration/test-memory-real-world.sh   # Complex real-world scenarios

# Model comparison (creates database backups!)
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
./tests/integration/compare-models.sh cloud claude-sonnet-4-5 gpt-4o

# OpenCode tests
./tests/integration/test-opencode-safe.sh         # Safe connection test
./tests/integration/test-opencode-integration.sh  # Full integration test
```

**Important**: The `compare-models.sh` script backs up your database before running tests. Restore from `data/*.db.backup_*` if needed.

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

## Model Comparison Framework

The `compare-models.sh` script allows you to test and compare different LLM models side-by-side:

### Features
- ✅ **Self-contained**: Populates its own test data (6 memories)
- ✅ **Automatic backups**: Backs up database before testing
- ✅ **Fair comparison**: Both models tested on identical data
- ✅ **AI analysis**: Uses Claude to analyze results
- ✅ **Comprehensive metrics**: Speed, accuracy, tool selection

### Usage
```bash
./tests/integration/compare-models.sh <mode> <model1> <model2>

# Examples:
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
./tests/integration/compare-models.sh cloud claude-sonnet-4-5 gpt-4o
```

### Output
- Markdown report: `tests/integration/logs/comparison_<mode>_<timestamp>.md`
- Individual test logs: `tests/integration/logs/m1_test*.log`, `m2_test*.log`
- AI analysis: Insights from Claude Sonnet 4.5
- Database backup: `data/jarvis_memory_*.db.backup_<timestamp>`

### Test Methodology
1. **Clean database** (backup created)
2. **Populate test data** (6 memories using Model 1)
3. **Test Model 1** (6 recall queries)
4. **Test Model 2** (same 6 queries)
5. **Generate comparison** (side-by-side table)
6. **AI analysis** (Claude analyzes results)

## Adding New Tests

1. **Safe tests** → `tests/integration/`
2. **Unit tests** → `tests/unit/`
3. **E2E tests** → `tests/e2e/`
4. Mark executable: `chmod +x tests/path/to/test.sh`
5. Use `--json` flag for clean output parsing
6. Include error handling and clear pass/fail messages

## Test Results Location

All test results are saved to `tests/integration/logs/`:
- `comparison_*.md` - Model comparison reports
- `m1_test*.log`, `m2_test*.log` - Individual test logs
- `setup*.log` - Database population logs
- `analysis_response.log` - AI analysis output

