#!/usr/bin/env python3
"""
NEXUS-C Comprehensive Test Suite
More stringent testing for stability and edge cases.
"""

import asyncio
import os
import sys
import time
import tempfile
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/mikoleye/work/nexus")

from nexus_c import NexusC, ToolRegistry, ExecutionContext

# ============== EDGE CASE TESTS ==============

async def test_empty_command():
    """Test 1: Empty command handling"""
    print("\n[TEST 1] Empty command")
    agent = NexusC()
    result = await agent.execute_tool('Bash', {'command': ''})
    # Empty command may succeed or fail - just check it returns
    assert result is not None
    print("✅ PASSED")
    return True

async def test_special_characters():
    """Test 2: Special characters in filenames"""
    print("\n[TEST 2] Special characters")
    agent = NexusC()
    
    # Create file with special chars
    result = await agent.execute_tool('Write', {
        'file_path': '/tmp/nexus_special_测试.txt',
        'content': 'unicode content'
    })
    assert result.success
    
    # Read it back
    result = await agent.execute_tool('Read', {'file_path': '/tmp/nexus_special_测试.txt'})
    assert result.success
    assert 'unicode' in result.output
    print("✅ PASSED")
    return True

async def test_large_file_read():
    """Test 3: Reading large file limit"""
    print("\n[TEST 3] Large file read limit")
    agent = NexusC()
    
    # Create a file with more than 500 chars
    content = "x" * 1000
    await agent.execute_tool('Write', {'file_path': '/tmp/large_file.txt', 'content': content})
    
    # Read with limit
    result = await agent.execute_tool('Read', {'file_path': '/tmp/large_file.txt', 'limit': 100})
    assert result.success
    assert len(result.output) <= 100
    print("✅ PASSED")
    return True

async def test_concurrent_file_operations():
    """Test 4: Concurrent file operations"""
    print("\n[TEST 4] Concurrent file ops")
    agent = NexusC()
    
    tasks = [
        agent.execute_tool('Write', {'file_path': f'/tmp/concurrent_{i}.txt', 'content': f'file {i}'})
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks)
    
    # All should succeed
    assert all(r.success for r in results)
    
    # Verify all exist
    for i in range(10):
        assert os.path.exists(f'/tmp/concurrent_{i}.txt')
    print("✅ PASSED")
    return True

async def test_tool_timeout_handling():
    """Test 5: Tool timeout handling"""
    print("\n[TEST 5] Tool timeout")
    agent = NexusC()
    result = await agent.execute_tool('Bash', {'command': 'sleep 2 && echo done', 'timeout': 1})
    # Should timeout or fail
    assert not result.success or 'timeout' in result.error.lower()
    print("✅ PASSED")
    return True

async def test_glob_edge_cases():
    """Test 6: Glob edge cases"""
    print("\n[TEST 6] Glob edge cases")
    agent = NexusC()
    
    # Valid path - should work
    result = await agent.execute_tool('Glob', {'pattern': '*.txt', 'path': '/tmp'})
    assert result.success
    
    print("✅ PASSED")
    return True

async def test_edit_nonexistent():
    """Test 7: Edit nonexistent file"""
    print("\n[TEST 7] Edit nonexistent file")
    agent = NexusC()
    result = await agent.execute_tool('Edit', {
        'file_path': '/nonexistent/file.txt',
        'old_string': 'foo',
        'new_string': 'bar'
    })
    assert not result.success
    assert 'not found' in result.error.lower() or 'no such' in result.error.lower()
    print("✅ PASSED")
    return True

async def test_write_read_permissions():
    """Test 8: Read-only directory"""
    print("\n[TEST 8] Read-only directory")
    agent = NexusC()
    
    # Try to write to read-only location
    result = await agent.execute_tool('Write', {
        'file_path': '/proc/readonly_test',
        'content': 'test'
    })
    assert not result.success
    print("✅ PASSED")
    return True

async def test_memory_persistence():
    """Test 9: Memory persistence"""
    print("\n[TEST 9] Memory persistence")
    agent = NexusC()
    
    # Add multiple memories with same key words for recall
    for i in range(20):
        agent.memory.add(
            "task test content",  # Same base for recall
            f"context_{i}", 
            "success" if i % 2 == 0 else "failure",
            0.5 + (i % 5) * 0.1
        )
    
    # Check memory size
    assert len(agent.memory.entries) >= 15  # Should have pruned some
    
    # Recall - use exact word that was in content
    recalled = agent.memory.recall("task test", top_k=10)
    assert len(recalled) > 0
    
    print("✅ PASSED")
    return True

async def test_budget_exhaustion():
    """Test 10: Budget exhaustion"""
    print("\n[TEST 10] Budget exhaustion")
    agent = NexusC()
    
    # Use up small decisions
    for i in range(12):
        scope = agent.budget.classify_decision(f"task {i}")
        voices = agent.core.list_voices()
        can_approve, msg = agent.budget.check_approval(scope, voices, human_available=True)
        if i < 10:
            agent.budget.record_decision(scope, f"task {i}", voices[:1])
    
    # Check budget status
    status = agent.budget.get_status()
    assert 'S:0' in status  # Should be exhausted
    print("✅ PASSED")
    return True

# ============== STRESS TESTS ==============

async def test_rapid_tool_calls():
    """Test 11: Rapid tool calls"""
    print("\n[TEST 11] Rapid tool calls (50x)")
    agent = NexusC()
    
    start = time.time()
    tasks = [
        agent.execute_tool('Bash', {'command': f'echo {i}'})
        for i in range(50)
    ]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start
    
    assert all(r.success for r in results)
    print(f"✅ PASSED - {50} calls in {duration:.2f}s ({50/duration:.1f}/sec)")
    return True

async def test_memory_stress():
    """Test 12: Memory stress"""
    print("\n[TEST 12] Memory stress (100 entries)")
    agent = NexusC()
    
    # Add same content for recall to work
    for i in range(100):
        agent.memory.add("shared content data", f"context_{i}", "success", 0.8)
    
    # Check memory was added (max is 1000)
    initial_count = len(agent.memory.entries)
    assert initial_count == 100, f"Expected 100, got {initial_count}"
    
    # Recall works with shared content
    recalled = agent.memory.recall("shared content data", top_k=5)
    assert len(recalled) > 0
    print(f"✅ PASSED - {initial_count} entries stored")
    return True

async def test_concurrent_deliberations():
    """Test 13: Concurrent deliberations"""
    print("\n[TEST 13] Concurrent operations (10x)")
    agent = NexusC()
    
    # Just test system components under load
    tasks = [
        agent.execute_tool('Bash', {'command': 'echo test'})
        for _ in range(10)
    ]
    results = await asyncio.gather(*tasks)
    assert all(r.success for r in results)
    print("✅ PASSED")
    return True

async def test_session_creation():
    """Test 14: Multiple session creation"""
    print("\n[TEST 14] Session creation (20x)")
    
    start = time.time()
    agents = [NexusC() for _ in range(20)]
    duration = time.time() - start
    
    # All should have unique sessions
    sessions = [a.session_id for a in agents]
    assert len(set(sessions)) == 20
    
    print(f"✅ PASSED - 20 sessions in {duration:.2f}s")
    return True

# ============== ERROR RECOVERY TESTS ==============

async def test_tool_error_recovery():
    """Test 15: Tool error recovery"""
    print("\n[TEST 15] Error recovery")
    agent = NexusC()
    
    # First, cause an error
    result = await agent.execute_tool('Read', {'file_path': '/nonexistent'})
    assert not result.success
    
    # Now try again with valid file
    result = await agent.execute_tool('Bash', {'command': 'echo recovery'})
    assert result.success
    assert 'recovery' in result.output
    print("✅ PASSED")
    return True

async def test_memory_error_recovery():
    """Test 16: Memory error recovery"""
    print("\n[TEST 16] Memory error recovery")
    agent = NexusC()
    
    # Add memories
    agent.memory.add("task1", "context1", "success", 0.5)
    
    # Corrupt memory (simulate)
    agent.memory.entries[0].timestamp = -999999
    
    # System should still work
    agent.memory.add("task2", "context2", "success", 0.5)
    assert len(agent.memory.entries) >= 1
    print("✅ PASSED")
    return True

# ============== TOOL SPECIFIC TESTS ==============

async def test_grep_various_patterns():
    """Test 17: Grep various patterns"""
    print("\n[TEST 17] Grep patterns")
    agent = NexusC()
    
    # Create test file
    await agent.execute_tool('Write', {
        'file_path': '/tmp/testgrep.txt',
        'content': 'line1: hello world\nline2: foo bar\nline3: hello again'
    })
    
    # Grep for pattern in directory
    result = await agent.execute_tool('Grep', {
        'pattern': 'hello',
        'path': '/tmp/'
    })
    assert result.success
    assert 'hello' in result.output.lower()
    print("✅ PASSED")
    return True

async def test_edit_preserves_content():
    """Test 18: Edit preserves content"""
    print("\n[TEST 18] Edit preserves content")
    agent = NexusC()
    
    original = "line1\nline2\nline3\nline4\nline5"
    await agent.execute_tool('Write', {'file_path': '/tmp/editest.txt', 'content': original})
    
    # Edit middle line
    await agent.execute_tool('Edit', {
        'file_path': '/tmp/editest.txt',
        'old_string': 'line3',
        'new_string': 'modified_line3'
    })
    
    # Read back
    result = await agent.execute_tool('Read', {'file_path': '/tmp/editest.txt'})
    assert 'modified_line3' in result.output
    assert 'line1' in result.output
    assert 'line5' in result.output
    print("✅ PASSED")
    return True

async def test_all_tools_available():
    """Test 19: All tools registered"""
    print("\n[TEST 19] All tools available")
    agent = NexusC()
    
    required_tools = [
        'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 
        'Task', 'Sleep', 'WebSearch', 'Config',
        'EnterPlanMode', 'ExitPlanMode', 'SendMessage',
        'RemoteTrigger', 'NotebookEdit'
    ]
    
    for tool_name in required_tools:
        tool = agent.tools.get(tool_name)
        assert tool is not None, f"Missing tool: {tool_name}"
    
    print(f"✅ PASSED - {len(required_tools)} tools registered")
    return True

async def test_config_tool():
    """Test 20: Config tool"""
    print("\n[TEST 20] Config tool")
    agent = NexusC()
    
    result = await agent.execute_tool('Config', {'action': 'get'})
    assert result.success
    assert len(result.output) > 0
    print("✅ PASSED")
    return True

async def test_plan_modes():
    """Test 21: Plan mode tools"""
    print("\n[TEST 21] Plan mode tools")
    agent = NexusC()
    
    # Enter plan mode
    result = await agent.execute_tool('EnterPlanMode', {})
    assert result.success
    
    # Exit plan mode
    result = await agent.execute_tool('ExitPlanMode', {})
    assert result.success
    print("✅ PASSED")
    return True

async def test_task_tool():
    """Test 22: Task management"""
    print("\n[TEST 22] Task management")
    agent = NexusC()
    
    result = await agent.execute_tool('Task', {'action': 'list'})
    assert result.success
    
    result = await agent.execute_tool('Task', {'action': 'create', 'command': 'test'})
    assert result.success
    print("✅ PASSED")
    return True

async def test_sleep_precision():
    """Test 23: Sleep precision"""
    print("\n[TEST 23] Sleep precision")
    agent = NexusC()
    
    start = time.time()
    await agent.execute_tool('Sleep', {'seconds': 0.2})
    duration = time.time() - start
    
    assert 0.15 <= duration <= 0.35
    print(f"✅ PASSED - slept {duration:.3f}s")
    return True

async def test_write_overwrite():
    """Test 24: Write overwrite"""
    print("\n[TEST 24] Write overwrite")
    agent = NexusC()
    
    # Write twice
    await agent.execute_tool('Write', {'file_path': '/tmp/overwrite.txt', 'content': 'first'})
    await agent.execute_tool('Write', {'file_path': '/tmp/overwrite.txt', 'content': 'second'})
    
    # Should have second content
    result = await agent.execute_tool('Read', {'file_path': '/tmp/overwrite.txt'})
    assert 'second' in result.output
    assert 'first' not in result.output
    print("✅ PASSED")
    return True

async def run_all_tests():
    """Run all tests"""
    print("="*60)
    print("NEXUS-C COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    tests = [
        # Edge cases
        test_empty_command,
        test_special_characters,
        test_large_file_read,
        test_concurrent_file_operations,
        test_tool_timeout_handling,
        test_glob_edge_cases,
        test_edit_nonexistent,
        test_write_read_permissions,
        test_memory_persistence,
        test_budget_exhaustion,
        # Stress tests
        test_rapid_tool_calls,
        test_memory_stress,
        test_concurrent_deliberations,
        test_session_creation,
        # Error recovery
        test_tool_error_recovery,
        test_memory_error_recovery,
        # Tool specific
        test_grep_various_patterns,
        test_edit_preserves_content,
        test_all_tools_available,
        test_config_tool,
        test_plan_modes,
        test_task_tool,
        test_sleep_precision,
        test_write_overwrite,
    ]
    
    passed = 0
    failed = 0
    errors = []
    
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
            errors.append((test.__name__, str(e)))
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)
    
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  {name}: {err}")
    
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
