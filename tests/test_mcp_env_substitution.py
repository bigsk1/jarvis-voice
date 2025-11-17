#!/usr/bin/env python3
"""
Test MCP environment variable substitution
"""
import os
import sys

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from mcp_client import MCPClient


def test_env_substitution():
    """Test that ${VAR_NAME} substitution works correctly."""
    
    # Set test environment variables
    os.environ['TEST_API_KEY'] = 'secret-api-key-12345'
    os.environ['TEST_TOKEN'] = 'token-67890'
    os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-should-not-leak'
    
    # Test case 1: Simple substitution
    client1 = MCPClient(
        name="test1",
        command="echo",
        args=["test"],
        env={
            "API_KEY": "${TEST_API_KEY}",
            "TOKEN": "${TEST_TOKEN}"
        }
    )
    
    env1 = client1._build_env_with_substitution()
    assert env1["API_KEY"] == "secret-api-key-12345", f"Expected 'secret-api-key-12345', got '{env1['API_KEY']}'"
    assert env1["TOKEN"] == "token-67890", f"Expected 'token-67890', got '{env1['TOKEN']}'"
    assert "ANTHROPIC_API_KEY" not in env1, "ANTHROPIC_API_KEY should NOT be in env (security issue!)"
    print("✅ Test 1 passed: Simple substitution works")
    
    # Test case 2: Empty env (secure by default)
    client2 = MCPClient(
        name="test2",
        command="echo",
        args=["test"],
        env={}
    )
    
    env2 = client2._build_env_with_substitution()
    assert len(env2) == 0, f"Expected empty env, got {env2}"
    assert "ANTHROPIC_API_KEY" not in env2, "ANTHROPIC_API_KEY should NOT be in env (security issue!)"
    print("✅ Test 2 passed: Empty env passes nothing (secure)")
    
    # Test case 3: Variable not found (keeps ${} syntax)
    client3 = MCPClient(
        name="test3",
        command="echo",
        args=["test"],
        env={
            "MISSING": "${NONEXISTENT_VAR}"
        }
    )
    
    env3 = client3._build_env_with_substitution()
    assert env3["MISSING"] == "${NONEXISTENT_VAR}", f"Expected '${{NONEXISTENT_VAR}}', got '{env3['MISSING']}'"
    print("✅ Test 3 passed: Missing variables keep ${} syntax")
    
    # Test case 4: Multiple substitutions in one value
    client4 = MCPClient(
        name="test4",
        command="echo",
        args=["test"],
        env={
            "COMBINED": "prefix-${TEST_API_KEY}-middle-${TEST_TOKEN}-suffix"
        }
    )
    
    env4 = client4._build_env_with_substitution()
    expected = "prefix-secret-api-key-12345-middle-token-67890-suffix"
    assert env4["COMBINED"] == expected, f"Expected '{expected}', got '{env4['COMBINED']}'"
    print("✅ Test 4 passed: Multiple substitutions in one value")
    
    # Test case 5: Non-string values are converted to strings
    client5 = MCPClient(
        name="test5",
        command="echo",
        args=["test"],
        env={
            "NUMBER": 12345,
            "BOOL": True
        }
    )
    
    env5 = client5._build_env_with_substitution()
    assert env5["NUMBER"] == "12345", f"Expected '12345', got '{env5['NUMBER']}'"
    assert env5["BOOL"] == "True", f"Expected 'True', got '{env5['BOOL']}'"
    print("✅ Test 5 passed: Non-string values converted")
    
    print("\n🎉 All tests passed!")
    print("\n🔒 Security verification:")
    print(f"   • Empty env = {len(env2)} variables (should be 0)")
    print(f"   • ANTHROPIC_API_KEY leaked? {'❌ YES (BAD!)' if 'ANTHROPIC_API_KEY' in env2 else '✅ NO (GOOD!)'}")
    print(f"   • Only explicit vars passed? ✅ YES")


if __name__ == "__main__":
    try:
        test_env_substitution()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

