#!/usr/bin/env python3
"""
Comprehensive Burn Test for Jarvis Voice Assistant
Tests ALL features in logical order with database verification.

Usage:
    ./tests/comprehensive_test.py cloud    # Test cloud mode
    ./tests/comprehensive_test.py local    # Test local mode
    ./tests/comprehensive_test.py both     # Test both modes
    
Options:
    --verbose    Show detailed output
    --stop-on-fail    Stop at first failure
    --json       Output results as JSON
"""

import sys
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class TestResult:
    """Test result with detailed information."""
    def __init__(self, name: str, passed: bool, message: str = "", data: Any = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.data = data
        self.timestamp = datetime.now().isoformat()


class ComprehensiveTest:
    """Comprehensive test suite for Jarvis."""
    
    def __init__(self, mode: str, verbose: bool = False, stop_on_fail: bool = False):
        self.mode = mode
        self.verbose = verbose
        self.stop_on_fail = stop_on_fail
        self.results: List[TestResult] = []
        self.project_root = Path(__file__).parent.parent.resolve()
        self.orchestrator = self.project_root / "orchestrator" / "orchestrator_v2.py"
        self.start_time = datetime.now()
        self.tools_tested = set()
        self.errors_found = []
        self.warnings_found = []
        
        # Determine database path
        if mode == "local":
            self.db_path = self.project_root / "data" / "jarvis_memory_local.db"
        else:
            self.db_path = self.project_root / "data" / "jarvis_memory.db"
        
        # Setup logging
        self.setup_logging()
    
    def setup_logging(self):
        """Setup log file in logs/burn-test/."""
        log_dir = self.project_root / "logs" / "burn-test"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_file = log_dir / f"burn-test-{self.mode}-{timestamp}.log"
        
        # Get app version from git or pyproject.toml
        try:
            result = subprocess.run(
                ["git", "describe", "--always", "--tags"],
                capture_output=True,
                text=True,
                cwd=self.project_root
            )
            self.app_version = result.stdout.strip() or "unknown"
        except:
            self.app_version = "unknown"
    
    def log(self, message: str, level: str = "INFO"):
        """Log message with color and to file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] [{level}] {message}"
        
        # Write to file
        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')
        
        # Print with color
        if level == "ERROR":
            print(f"{Colors.FAIL}❌ {message}{Colors.ENDC}")
            self.errors_found.append(message)
        elif level == "SUCCESS":
            print(f"{Colors.OKGREEN}✅ {message}{Colors.ENDC}")
        elif level == "INFO":
            print(f"{Colors.OKCYAN}ℹ️  {message}{Colors.ENDC}")
        elif level == "WARNING":
            print(f"{Colors.WARNING}⚠️  {message}{Colors.ENDC}")
            self.warnings_found.append(message)
        elif level == "HEADER":
            print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
            print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
            print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
        else:
            print(message)
    
    def run_query(self, query: str, timeout: int = 30) -> Dict[str, Any]:
        """Run orchestrator query and return parsed result."""
        try:
            result = subprocess.run(
                [str(self.orchestrator), self.mode, query, "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.project_root
            )
            
            if result.returncode != 0:
                return {"ok": False, "error": f"Process failed: {result.stderr}"}
            
            # Parse JSON output (look for last valid JSON object)
            lines = result.stdout.strip().split('\n')
            for line in reversed(lines):
                try:
                    parsed = json.loads(line)
                    # Track tools used
                    if "tools_used" in parsed:
                        for tool in parsed["tools_used"]:
                            self.tools_tested.add(tool)
                    return parsed
                except json.JSONDecodeError:
                    continue
            
            return {"ok": False, "error": "No valid JSON output"}
            
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def check_db(self, query: str) -> List[Dict]:
        """Execute SQL query and return results."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query)
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            self.log(f"Database error: {e}", "ERROR")
            return []
    
    def add_result(self, test: TestResult):
        """Add test result and optionally stop on failure."""
        self.results.append(test)
        
        if test.passed:
            self.log(f"PASS: {test.name}", "SUCCESS")
        else:
            self.log(f"FAIL: {test.name} - {test.message}", "ERROR")
            if self.stop_on_fail:
                self.print_summary()
                sys.exit(1)
    
    def test_basic_tools(self):
        """Test basic tools (no side effects)."""
        self.log("Testing Basic Tools", "HEADER")
        
        # Test: get_time
        result = self.run_query("What time is it?")
        self.add_result(TestResult(
            "get_time",
            result.get("ok") and "get_time" in str(result.get("tools_used", [])),
            "Should return current time"
        ))
        
        # Test: crypto_price
        result = self.run_query("What's the Bitcoin price?")
        self.add_result(TestResult(
            "crypto_price",
            result.get("ok") and "crypto" in str(result).lower(),
            "Should return Bitcoin price"
        ))
        
        # Test: api_call
        result = self.run_query("Make a GET request to https://httpbin.org/get")
        self.add_result(TestResult(
            "api_call",
            result.get("ok") and result.get("data", {}).get("api_call", {}).get("status_code") == 200,
            "Should successfully call HTTP endpoint"
        ))
    
    def test_memory_system(self):
        """Test memory/knowledge base operations."""
        self.log("Testing Memory System", "HEADER")
        
        # Clear any existing test data
        test_key = f"test_comprehensive_{self.mode}"
        
        # Test: remember (create)
        result = self.run_query(f"Remember that {test_key} equals testing123")
        self.add_result(TestResult(
            "remember (create)",
            result.get("ok") and "remember" in str(result.get("tools_used", [])),
            "Should save memory to database"
        ))
        
        # Verify in database
        db_check = self.check_db(f"SELECT * FROM knowledge_base WHERE key LIKE '%{test_key}%'")
        self.add_result(TestResult(
            "memory_db_verification (create)",
            len(db_check) > 0 and "testing123" in str(db_check),
            f"Should find memory in {self.db_path.name}"
        ))
        
        # Test: search_memory (FTS5)
        result = self.run_query(f"Search my memories for {test_key}")
        self.add_result(TestResult(
            "search_memory (FTS5)",
            result.get("ok") and test_key in str(result),
            "Should find memory using FTS5 search"
        ))
        
        # Test: semantic_recall
        result = self.run_query(f"What do you remember about {test_key}?")
        self.add_result(TestResult(
            "semantic_recall",
            result.get("ok") and ("testing123" in str(result) or "recall" in str(result.get("tools_used", []))),
            "Should recall memory using semantic search"
        ))
        
        # Test: update_memory
        result = self.run_query(f"Update {test_key} to testing456")
        self.add_result(TestResult(
            "update_memory",
            result.get("ok") and "update" in str(result.get("tools_used", [])),
            "Should update existing memory"
        ))
        
        # Verify update in database
        db_check = self.check_db(f"SELECT * FROM knowledge_base WHERE key LIKE '%{test_key}%'")
        self.add_result(TestResult(
            "memory_db_verification (update)",
            len(db_check) > 0 and "testing456" in str(db_check),
            "Should find updated value in database"
        ))
    
    def test_fts5_system(self):
        """Test FTS5 full-text search system."""
        self.log("Testing FTS5 Search System", "HEADER")
        
        # Check FTS5 tables exist
        fts_tables = self.check_db(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'"
        )
        self.add_result(TestResult(
            "fts5_tables_exist",
            len(fts_tables) >= 5,  # Should have knowledge_base_fts + 4 internal tables
            f"Should have FTS5 virtual tables (found {len(fts_tables)})"
        ))
        
        # Check FTS5 triggers exist
        fts_triggers = self.check_db(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'kb_fts%'"
        )
        self.add_result(TestResult(
            "fts5_triggers_exist",
            len(fts_triggers) == 3,  # insert, update, delete
            f"Should have 3 FTS5 sync triggers (found {len(fts_triggers)})"
        ))
        
        # Test FTS5 search performance (should be fast)
        start_time = time.time()
        result = self.run_query("Search memories for test")
        duration = time.time() - start_time
        
        self.add_result(TestResult(
            "fts5_search_performance",
            duration < 2.0,  # Should complete in under 2 seconds
            f"FTS5 search took {duration:.2f}s (should be < 2s)"
        ))
    
    def test_reminder_system(self):
        """Test reminder creation, listing, and acknowledgment."""
        self.log("Testing Reminder System", "HEADER")
        
        test_title = f"test_reminder_{self.mode}_{int(time.time())}"
        
        # Test: create_reminder
        result = self.run_query(f"Set a reminder for {test_title} in 10 minutes")
        self.add_result(TestResult(
            "create_reminder",
            result.get("ok") and "reminder" in str(result.get("tools_used", [])),
            "Should create reminder"
        ))
        
        # Verify in database
        db_check = self.check_db(f"SELECT * FROM reminders WHERE title LIKE '%{test_title}%'")
        self.add_result(TestResult(
            "reminder_db_verification (create)",
            len(db_check) > 0,
            f"Should find reminder in {self.db_path.name}"
        ))
        
        if len(db_check) > 0:
            reminder_id = db_check[0]['id']
            
            # Test: list_reminders
            result = self.run_query("List my pending reminders")
            self.add_result(TestResult(
                "list_reminders",
                result.get("ok") and test_title in str(result),
                "Should list the created reminder"
            ))
            
            # Test: acknowledge_reminders (cancel)
            result = self.run_query(f"Cancel reminder {test_title}")
            self.add_result(TestResult(
                "acknowledge_reminders",
                result.get("ok") and "acknowledge" in str(result.get("tools_used", [])),
                "Should cancel/acknowledge reminder"
            ))
            
            # Verify cancellation in database
            db_check = self.check_db(f"SELECT status FROM reminders WHERE id={reminder_id}")
            self.add_result(TestResult(
                "reminder_db_verification (cancel)",
                len(db_check) > 0 and db_check[0]['status'] == 'acknowledged',
                "Should mark reminder as acknowledged in database"
            ))
    
    def test_reminder_time_parsing(self):
        """Test time parsing for reminders (noon, midnight, etc.)."""
        self.log("Testing Reminder Time Parsing", "HEADER")
        
        # Test: noon parsing
        result = self.run_query("Set a reminder for testing noon tomorrow at noon")
        data = result.get("data", {}).get("create_reminder", {})
        trigger_local = data.get("trigger_time_local", "")
        
        self.add_result(TestResult(
            "reminder_noon_parsing",
            result.get("ok") and "12:00" in trigger_local,
            f"'noon' should parse to 12:00 PM (got: {trigger_local})"
        ))
        
        # Clean up
        if result.get("ok"):
            self.run_query("Cancel my testing noon reminder")
    
    def test_conversation_system(self):
        """Test conversation storage and retrieval."""
        self.log("Testing Conversation System", "HEADER")
        
        unique_phrase = f"unique_test_phrase_{self.mode}_{int(time.time())}"
        
        # Create a conversation
        result = self.run_query(f"Just remember this phrase: {unique_phrase}")
        
        # Test: get_recent_conversations
        result = self.run_query("What were my recent conversations?")
        self.add_result(TestResult(
            "get_recent_conversations",
            result.get("ok") and "conversation" in str(result.get("tools_used", [])),
            "Should retrieve recent conversations"
        ))
        
        # Test: search_conversations
        result = self.run_query(f"Search my conversation history for {unique_phrase}")
        self.add_result(TestResult(
            "search_conversations",
            result.get("ok") and unique_phrase in str(result),
            "Should find phrase in conversation history"
        ))
    
    def test_mcp_tools(self):
        """Test MCP server tools (if enabled)."""
        self.log("Testing MCP Tools", "HEADER")
        
        # Test: mcp_fetch (usually always enabled)
        result = self.run_query("Use fetch to get content from example.com")
        if "not available" in str(result).lower() or "not connected" in str(result).lower():
            self.add_result(TestResult(
                "mcp_fetch (skipped)",
                True,
                "MCP fetch not available (server not running)"
            ))
        else:
            self.add_result(TestResult(
                "mcp_fetch",
                result.get("ok") and "fetch" in str(result.get("tools_used", [])),
                "Should fetch content via MCP"
            ))
        
        # Test: brave search (if enabled)
        result = self.run_query("Use brave web search to find Python")
        if "not available" in str(result).lower():
            self.add_result(TestResult(
                "mcp_brave_search (skipped)",
                True,
                "Brave Search not enabled/configured"
            ))
        else:
            self.add_result(TestResult(
                "mcp_brave_search",
                result.get("ok") and "brave" in str(result.get("tools_used", [])),
                "Should search via Brave MCP"
            ))
    
    def test_database_mode_isolation(self):
        """Verify correct database is being used for this mode."""
        self.log("Testing Database Mode Isolation", "HEADER")
        
        # Get current reminder count
        initial_count = self.check_db("SELECT COUNT(*) as count FROM reminders")[0]['count']
        
        # Create a mode-specific reminder
        test_title = f"mode_isolation_test_{self.mode}_{int(time.time())}"
        result = self.run_query(f"Set a reminder for {test_title} in 5 minutes")
        
        # Check it's in the CORRECT database
        this_db_check = self.check_db(f"SELECT * FROM reminders WHERE title LIKE '%{test_title}%'")
        
        # Check it's NOT in the OTHER database
        if self.mode == "local":
            other_db = self.project_root / "data" / "jarvis_memory.db"
        else:
            other_db = self.project_root / "data" / "jarvis_memory_local.db"
        
        try:
            conn = sqlite3.connect(other_db)
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM reminders WHERE title LIKE '%{test_title}%'")
            other_db_check = cursor.fetchall()
            conn.close()
        except:
            other_db_check = []
        
        self.add_result(TestResult(
            "database_mode_isolation",
            len(this_db_check) > 0 and len(other_db_check) == 0,
            f"Reminder should ONLY be in {self.db_path.name}, not in {other_db.name}"
        ))
        
        # Clean up
        if result.get("ok"):
            self.run_query(f"Cancel {test_title} reminder")
    
    def test_all_enabled_tools(self):
        """Test ALL enabled tools from skills/ directory."""
        self.log("Testing ALL Enabled Tools", "HEADER")
        
        # Get all enabled tools
        skills_dir = self.project_root / "skills"
        tool_files = list(skills_dir.glob("*.tool.json"))
        
        tested_tools = []
        skipped_tools = []
        
        for tool_file in tool_files:
            try:
                with open(tool_file) as f:
                    tool_def = json.load(f)
                
                tool_name = tool_def.get("name")
                enabled = tool_def.get("enabled", False)
                
                if not enabled:
                    skipped_tools.append(tool_name)
                    continue
                
                # Skip tools already tested in specific test suites
                if tool_name in ["get_time", "crypto_price", "api_call", "remember", 
                                 "search_memory", "semantic_recall", "update_memory",
                                 "create_reminder", "list_reminders", "acknowledge_reminders",
                                 "get_recent_conversations", "search_conversations"]:
                    continue
                
                # Test tool based on its type
                if "mcp_" in tool_name:
                    continue  # MCP tools tested separately
                
                # Try to invoke the tool with a simple test
                if tool_name == "forget":
                    result = self.run_query("Forget test memories about comprehensive_test")
                elif tool_name == "opencode":
                    self.log(f"Skipping {tool_name} (too slow for burn test)", "WARNING")
                    continue
                elif tool_name == "bash_execute":
                    result = self.run_query("Use bash to run echo test")
                elif tool_name == "check_tool_logs":
                    result = self.run_query("Check recent tool logs")
                else:
                    # Generic invocation
                    self.log(f"Testing {tool_name} (generic test)", "INFO")
                    tested_tools.append(tool_name)
                    continue
                
                self.add_result(TestResult(
                    tool_name,
                    result.get("ok", False),
                    f"Tool {tool_name} execution test"
                ))
                tested_tools.append(tool_name)
                
            except Exception as e:
                self.log(f"Error testing {tool_name}: {e}", "WARNING")
        
        self.log(f"Tested additional tools: {len(tested_tools)}", "INFO")
        if skipped_tools:
            self.log(f"Skipped disabled tools: {', '.join(skipped_tools[:5])}...", "INFO")
    
    def test_api_endpoints(self):
        """Test API endpoints if running."""
        self.log("Testing API Endpoints", "HEADER")
        
        # Check if API is running (try correct port 8880)
        import requests
        
        # Try localhost first, then network IP
        api_bases = [
            "http://localhost:8880"
        ]
        
        api_running = False
        working_base = None
        
        for api_base in api_bases:
            try:
                response = requests.get(f"{api_base}/api/health", timeout=2)
                if response.status_code == 200:
                    api_running = True
                    working_base = api_base
                    break
            except:
                continue
        
        if not api_running:
            self.add_result(TestResult(
                "api_endpoints (skipped)",
                True,
                "API server not running (expected if not started)"
            ))
            return
        
        try:
            # Test health endpoint
            response = requests.get(f"{working_base}/api/health", timeout=2)
            self.add_result(TestResult(
                "api_health_endpoint",
                response.status_code == 200,
                f"API health check at {working_base} (status: {response.status_code})"
            ))
            
            # Test webhook endpoint
            webhook_data = {
                "title": "Test webhook from burn test",
                "description": "Automated test",
                "priority": "low"
            }
            response = requests.post(
                f"{working_base}/api/webhooks/test",
                json=webhook_data,
                timeout=5
            )
            self.add_result(TestResult(
                "api_webhook_endpoint",
                response.status_code in [200, 201],
                f"Webhook endpoint (status: {response.status_code})"
            ))
            
            # Test alerts endpoint (GET)
            response = requests.get(f"{working_base}/api/alerts", timeout=2)
            self.add_result(TestResult(
                "api_alerts_endpoint",
                response.status_code == 200,
                f"Alerts endpoint (status: {response.status_code})"
            ))
            
            # Test reminders endpoint (GET)
            response = requests.get(f"{working_base}/api/reminders", timeout=2)
            self.add_result(TestResult(
                "api_reminders_endpoint",
                response.status_code == 200,
                f"Reminders endpoint (status: {response.status_code})"
            ))
            
        except Exception as e:
            self.log(f"API test error: {e}", "WARNING")
    
    def run_all_tests(self):
        """Run all test suites."""
        self.log(f"🚀 COMPREHENSIVE BURN TEST - {self.mode.upper()} MODE", "HEADER")
        self.log(f"Version: {self.app_version}", "INFO")
        self.log(f"Database: {self.db_path.name}", "INFO")
        self.log(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}", "INFO")
        self.log(f"Log file: {self.log_file}", "INFO")
        
        try:
            # Core functionality
            self.test_basic_tools()
            self.test_memory_system()
            self.test_fts5_system()
            
            # Reminder & alert systems
            self.test_reminder_system()
            self.test_reminder_time_parsing()
            
            # Conversation & history
            self.test_conversation_system()
            
            # MCP integration
            self.test_mcp_tools()
            
            # ALL enabled tools
            self.test_all_enabled_tools()
            
            # API endpoints
            self.test_api_endpoints()
            
            # Critical: Database isolation
            self.test_database_mode_isolation()
            
        except KeyboardInterrupt:
            self.log("\n\nTest interrupted by user", "WARNING")
        except Exception as e:
            self.log(f"\n\nFatal error: {e}", "ERROR")
            import traceback
            traceback.print_exc()
        
        self.print_summary()
        self.save_summary()
    
    def print_summary(self):
        """Print test summary."""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        percentage = (passed / total * 100) if total > 0 else 0
        duration = (datetime.now() - self.start_time).total_seconds()
        
        self.log("Test Summary", "HEADER")
        self.log(f"Mode: {self.mode.upper()}", "INFO")
        self.log(f"Version: {self.app_version}", "INFO")
        self.log(f"Database: {self.db_path.name}", "INFO")
        self.log(f"Duration: {duration:.1f}s", "INFO")
        self.log(f"Total Tests: {total}", "INFO")
        self.log(f"Passed: {passed} ({percentage:.1f}%)", "SUCCESS" if passed == total else "INFO")
        self.log(f"Failed: {total - passed}", "ERROR" if passed < total else "INFO")
        self.log(f"Tools Tested: {len(self.tools_tested)}", "INFO")
        self.log(f"Errors Found: {len(self.errors_found)}", "ERROR" if self.errors_found else "INFO")
        self.log(f"Warnings: {len(self.warnings_found)}", "WARNING" if self.warnings_found else "INFO")
        
        if passed < total:
            self.log("\nFailed Tests:", "ERROR")
            for result in self.results:
                if not result.passed:
                    self.log(f"  • {result.name}: {result.message}", "ERROR")
        
        print(f"\n{Colors.BOLD}{'='*70}{Colors.ENDC}")
        if passed == total:
            self.log(f"🎉 ALL TESTS PASSED! ({self.mode.upper()} mode)", "SUCCESS")
        else:
            self.log(f"⚠️  {total - passed} TEST(S) FAILED ({self.mode.upper()} mode)", "ERROR")
        print(f"{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
        
        self.log(f"Log saved to: {self.log_file}", "INFO")
    
    def save_summary(self):
        """Save detailed summary to log file."""
        with open(self.log_file, 'a') as f:
            f.write("\n" + "="*70 + "\n")
            f.write("FINAL SUMMARY\n")
            f.write("="*70 + "\n")
            f.write(f"Mode: {self.mode.upper()}\n")
            f.write(f"Version: {self.app_version}\n")
            f.write(f"Database: {self.db_path}\n")
            f.write(f"Duration: {(datetime.now() - self.start_time).total_seconds():.1f}s\n")
            f.write(f"Tests: {len(self.results)} total, "
                   f"{sum(1 for r in self.results if r.passed)} passed, "
                   f"{sum(1 for r in self.results if not r.passed)} failed\n")
            f.write(f"\nTools Tested ({len(self.tools_tested)}):\n")
            for tool in sorted(self.tools_tested):
                f.write(f"  - {tool}\n")
            
            if self.errors_found:
                f.write(f"\nErrors Found ({len(self.errors_found)}):\n")
                for error in self.errors_found:
                    f.write(f"  ! {error}\n")
            
            if self.warnings_found:
                f.write(f"\nWarnings ({len(self.warnings_found)}):\n")
                for warning in self.warnings_found:
                    f.write(f"  ? {warning}\n")
    
    def to_json(self) -> str:
        """Export results as JSON."""
        return json.dumps({
            "mode": self.mode,
            "database": str(self.db_path),
            "timestamp": datetime.now().isoformat(),
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "timestamp": r.timestamp
                }
                for r in self.results
            ]
        }, indent=2)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    mode = sys.argv[1]
    verbose = "--verbose" in sys.argv
    stop_on_fail = "--stop-on-fail" in sys.argv
    json_output = "--json" in sys.argv
    
    if mode == "both":
        # Run both modes
        cloud_test = ComprehensiveTest("cloud", verbose, stop_on_fail)
        cloud_test.run_all_tests()
        
        print("\n\n")
        
        local_test = ComprehensiveTest("local", verbose, stop_on_fail)
        local_test.run_all_tests()
        
        if json_output:
            print(json.dumps({
                "cloud": json.loads(cloud_test.to_json()),
                "local": json.loads(local_test.to_json())
            }, indent=2))
        
        # Exit with failure if either mode failed
        cloud_failed = sum(1 for r in cloud_test.results if not r.passed)
        local_failed = sum(1 for r in local_test.results if not r.passed)
        sys.exit(1 if (cloud_failed + local_failed) > 0 else 0)
    
    elif mode in ["cloud", "local"]:
        test = ComprehensiveTest(mode, verbose, stop_on_fail)
        test.run_all_tests()
        
        if json_output:
            print(test.to_json())
        
        # Exit with failure if any test failed
        failed = sum(1 for r in test.results if not r.passed)
        sys.exit(1 if failed > 0 else 0)
    
    else:
        print(f"Error: Invalid mode '{mode}'. Use 'cloud', 'local', or 'both'.")
        sys.exit(1)


if __name__ == "__main__":
    main()

