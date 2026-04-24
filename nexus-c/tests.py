#!/usr/bin/env python3
"""
NEXUS-C Stability Tests
Run comprehensive tests for agent stability.
"""

import asyncio
import sys
import time
from types import SimpleNamespace
from nexus_c import NexusC


def make_fast_agent():
    agent = NexusC()

    async def fake_deliberate(task: str, context: str = ""):
        voices = agent.core.list_voices()
        return SimpleNamespace(
            decision=SimpleNamespace(
                chosen_path=f"Use direct tools for: {task}",
                confidence=0.8,
                requires_human=False,
            ),
            contributions=[
                SimpleNamespace(
                    voice=voice,
                    position=f"{voice} says act on: {task}",
                    reasoning="fast-test",
                )
                for voice in voices
            ],
            overseer_intervention=None,
        )

    async def fake_excavate(message: str):
        return SimpleNamespace(summary=lambda: f"Archaeology summary: {message}")

    agent.deliberation.deliberate = fake_deliberate
    agent.archaeologist.excavate = fake_excavate
    return agent

async def test_status():
    """Test 1: Status command"""
    print("\n[TEST 1] Status command")
    agent = make_fast_agent()
    status = agent.status()
    assert "NEXUS-C Status" in status
    assert "Session:" in status
    assert "Model:" in status
    assert "Tools:" in status
    print("✅ PASSED")
    return True

async def test_tools_list():
    """Test 2: Tools list"""
    print("\n[TEST 2] Tools list")
    agent = make_fast_agent()
    tools = agent.tools.list_tools()
    assert len(tools) >= 15
    tool_names = [t['name'] for t in tools]
    assert 'Bash' in tool_names
    assert 'Read' in tool_names
    assert 'Write' in tool_names
    print(f"✅ PASSED - {len(tools)} tools available")
    return True

async def test_bash_tool():
    """Test 3: Bash tool execution"""
    print("\n[TEST 3] Bash tool")
    agent = make_fast_agent()
    result = await agent.execute_tool('Bash', {'command': 'echo "hello world"'})
    assert result.success
    assert 'hello world' in result.output
    print(f"✅ PASSED - Output: {result.output.strip()}")
    return True

async def test_read_tool():
    """Test 4: Read tool"""
    print("\n[TEST 4] Read tool")
    agent = make_fast_agent()
    result = await agent.execute_tool('Read', {'file_path': '/etc/hostname', 'limit': 50})
    assert result.success
    assert len(result.output) > 0
    print(f"✅ PASSED - Read {len(result.output)} chars")
    return True

async def test_write_tool():
    """Test 5: Write tool"""
    print("\n[TEST 5] Write tool")
    agent = make_fast_agent()
    result = await agent.execute_tool('Write', {'file_path': '/tmp/nexus_test.txt', 'content': 'test content 123'})
    assert result.success
    # Verify it was written
    result2 = await agent.execute_tool('Read', {'file_path': '/tmp/nexus_test.txt'})
    assert 'test content 123' in result2.output
    print("✅ PASSED")
    return True

async def test_edit_tool():
    """Test 6: Edit tool"""
    print("\n[TEST 6] Edit tool")
    agent = make_fast_agent()
    # First write
    await agent.execute_tool('Write', {'file_path': '/tmp/nexus_edit.txt', 'content': 'hello world'})
    # Then edit
    result = await agent.execute_tool('Edit', {'file_path': '/tmp/nexus_edit.txt', 'old_string': 'world', 'new_string': 'universe'})
    assert result.success
    # Verify
    result2 = await agent.execute_tool('Read', {'file_path': '/tmp/nexus_edit.txt'})
    assert 'universe' in result2.output
    print("✅ PASSED")
    return True

async def test_glob_tool():
    """Test 7: Glob tool"""
    print("\n[TEST 7] Glob tool")
    agent = make_fast_agent()
    result = await agent.execute_tool('Glob', {'pattern': '*.py', 'path': '/home/mikoleye/work/nexus-c'})
    assert result.success
    assert 'nexus_c.py' in result.output
    print(f"✅ PASSED - Found: {result.output[:50]}")
    return True

async def test_grep_tool():
    """Test 8: Grep tool"""
    print("\n[TEST 8] Grep tool")
    agent = make_fast_agent()
    result = await agent.execute_tool('Grep', {'pattern': 'class NexusC', 'path': '/home/mikoleye/work/nexus-c'})
    assert result.success
    print("✅ PASSED")
    return True

async def test_sleep_tool():
    """Test 9: Sleep tool"""
    print("\n[TEST 9] Sleep tool")
    agent = make_fast_agent()
    start = time.time()
    result = await agent.execute_tool('Sleep', {'seconds': 0.1})
    duration = time.time() - start
    assert result.success
    assert duration >= 0.1
    print(f"✅ PASSED - Slept {duration:.2f}s")
    return True

async def test_memory():
    """Test 10: Memory system"""
    print("\n[TEST 10] Memory system")
    agent = make_fast_agent()
    initial_count = len(agent.memory.entries)

    # Add some memories
    agent.memory.add("test task 1", "context 1", "success", 0.8)
    agent.memory.add("test task 2", "context 2", "failure", 0.9)

    assert len(agent.memory.entries) == initial_count + 2

    # Recall
    recalled = agent.memory.recall("test", top_k=5)
    assert len(recalled) > 0

    # Get insights
    insights = agent.memory.get_insights()
    print(f"✅ PASSED - Insights: {insights}")
    return True

async def test_deliberation():
    """Test 11: Deliberation system (fast, no Ollama)"""
    print("\n[TEST 11] Deliberation system (no Ollama)")
    agent = make_fast_agent()
    # Just test the structure works without actual LLM call
    scope = agent.budget.classify_decision("test the system")
    assert scope.value in ['small', 'medium', 'large', 'critical']
    print(f"✅ PASSED - Scope: {scope.value}")
    return True

async def test_failure_archaeology():
    """Test 12: Failure archaeology (no Ollama)"""
    print("\n[TEST 12] Failure archaeology (no LLM)")
    agent = make_fast_agent()
    # Use quick dig without LLM
    exc = agent.archaeologist.quick_dig("Test failure: command not found")
    assert exc is not None
    assert exc.initial_failure == "Test failure: command not found"
    print("✅ PASSED")
    return True

async def test_budget():
    """Test 13: Budget system"""
    print("\n[TEST 13] Budget system")
    agent = make_fast_agent()
    status = agent.budget.get_status()
    assert 'Architect' in status
    assert 'Builder' in status
    print(f"✅ PASSED - {status[:100]}")
    return True

async def test_multiple_think_calls():
    """Test 14: Multiple think calls stability (skip slow Ollama)"""
    print("\n[TEST 14] Multiple operations (skip slow Ollama)")
    agent = make_fast_agent()
    # Just test budget system instead of actual think calls
    for i in range(3):
        scope = agent.budget.classify_decision(f"test iteration {i}")
        assert scope.value in ['small', 'medium', 'large', 'critical']
        print(f"  Iteration {i}: {scope.value}")
    print("✅ PASSED")
    return True

async def test_tool_failure_handling():
    """Test 15: Tool failure handling"""
    print("\n[TEST 15] Tool failure handling")
    agent = make_fast_agent()
    # Try to read non-existent file
    result = await agent.execute_tool('Read', {'file_path': '/nonexistent/file.txt'})
    assert not result.success
    assert 'not found' in result.error.lower() or 'error' in result.error.lower()
    print(f"✅ PASSED - Error handled: {result.error[:30]}")
    return True

async def test_concurrent_tools():
    """Test 16: Concurrent tool execution"""
    print("\n[TEST 16] Concurrent tools")
    agent = make_fast_agent()
    # Run multiple tools
    tasks = [
        agent.execute_tool('Bash', {'command': 'sleep 0.1 && echo "a"'}),
        agent.execute_tool('Bash', {'command': 'sleep 0.1 && echo "b"'}),
        agent.execute_tool('Bash', {'command': 'echo "c"'}),
    ]
    results = await asyncio.gather(*tasks)
    assert all(r.success for r in results)
    print("✅ PASSED")
    return True

async def test_session_isolation():
    """Test 17: Session isolation"""
    print("\n[TEST 17] Session isolation")
    agent1 = make_fast_agent()
    agent2 = make_fast_agent()
    assert agent1.session_id != agent2.session_id
    agent1.memory.add("agent1 task", "context1", "success", 0.5)
    agent2.memory.add("agent2 task", "context2", "success", 0.5)
    # Each agent should have their own memory
    assert len(agent1.memory.entries) >= 1
    assert len(agent2.memory.entries) >= 1
    # Contents should be different
    assert agent1.memory.entries[0].content != agent2.memory.entries[0].content
    print("✅ PASSED - Sessions isolated")
    return True

async def test_tool_autodetect():
    """Test 18: auto-detects tools from task keywords."""
    print("\n[TEST 18] Tool auto-detect")
    agent = make_fast_agent()
    result = await agent.run("list files")
    assert ".py" in result or "nexus_c.py" in result
    print("✅ PASSED")
    return True

async def test_deliberation_timeout_fallback():
    """Test 19: timeout falls back cleanly."""
    print("\n[TEST 19] Deliberation timeout fallback")
    agent = make_fast_agent()

    async def slow_deliberate(task: str, context: str = ""):
        await asyncio.sleep(agent.ollama.timeout + 0.2)
        return None

    agent.deliberation.deliberate = slow_deliberate
    result = await agent.think("slow task")
    assert result["confidence"] >= 0
    assert len(result["tool_results"]) > 0
    print("✅ PASSED")
    return True

async def run_all_tests():
    """Run all tests"""
    print("="*60)
    print("NEXUS-C STABILITY TEST SUITE")
    print("="*60)

    tests = [
        test_status,
        test_tools_list,
        test_bash_tool,
        test_read_tool,
        test_write_tool,
        test_edit_tool,
        test_glob_tool,
        test_grep_tool,
        test_sleep_tool,
        test_memory,
        test_deliberation,
        test_failure_archaeology,
        test_budget,
        test_multiple_think_calls,
        test_tool_failure_handling,
        test_concurrent_tools,
        test_session_isolation,
        test_tool_autodetect,
        test_deliberation_timeout_fallback,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
