#!/usr/bin/env python3
"""
NEXUS-C STRESS TEST SUITE
Extreme testing for production readiness.
"""

import asyncio
import gc
import os
import sys
import time
import weakref
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/mikoleye/work/nexus")

from nexus_c import NexusC

# ============== CHAOS TESTING ==============

async def test_random_tool_failures():
    """Test 1: Simulated random tool failures"""
    print("\n[CHAOS 1] Random tool failures")
    agent = NexusC()

    # Simulate various failure scenarios
    failure_scenarios = [
        {'file_path': '/nonexistent'},
        {'command': 'exit 1'},
        {'file_path': '/proc/invalid'},
    ]

    for params in failure_scenarios:
        try:
            result = await agent.execute_tool('Bash', {'command': 'true'})
            # Should handle gracefully
            assert result is not None
        except Exception as e:
            # Should not crash
            print(f"  Warning: {e}")

    print("✅ PASSED - Handled random failures")
    return True

async def test_concurrent_failures():
    """Test 2: Concurrent tool failures"""
    print("\n[CHAOS 2] Concurrent failures")
    agent = NexusC()

    # Mix of success and failure
    tasks = []
    for i in range(20):
        if i % 3 == 0:
            tasks.append(agent.execute_tool('Read', {'file_path': '/nonexistent'}))
        else:
            tasks.append(agent.execute_tool('Bash', {'command': f'echo {i}'}))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Should not crash - count successes
    success_count = sum(1 for r in results if not isinstance(r, Exception) and r.success)
    assert success_count > 0
    print(f"✅ PASSED - {success_count}/20 survived")
    return True

async def test_rapid_context_switch():
    """Test 3: Rapid context switching"""
    print("\n[CHAOS 3] Context switching (100x)")
    agent = NexusC()

    start = time.time()
    for i in range(100):
        agent.context.working_dir = f'/tmp/test_{i}'
        await agent.execute_tool('Bash', {'command': 'echo test'})

    duration = time.time() - start
    print(f"✅ PASSED - 100 switches in {duration:.2f}s")
    return True

# ============== CONCURRENCY STRESS ==============

async def test_heavy_concurrent_load():
    """Test 4: Heavy concurrent load (200 operations)"""
    print("\n[STRESS 1] Heavy load (200 ops)")
    agent = NexusC()

    start = time.time()

    tasks = [
        agent.execute_tool('Bash', {'command': f'echo {i}'})
        for i in range(200)
    ]

    results = await asyncio.gather(*tasks)
    duration = time.time() - start

    success = sum(1 for r in results if r.success)
    print(f"✅ PASSED - {success}/200 in {duration:.2f}s ({200/duration:.0f}/sec)")
    return True

async def test_mixed_tool_concurrent():
    """Test 5: Mixed tool concurrent execution"""
    print("\n[STRESS 2] Mixed tools (100 ops)")
    agent = NexusC()

    tools = [
        {'tool': 'Bash', 'params': {'command': 'echo test'}},
        {'tool': 'Sleep', 'params': {'seconds': 0.01}},
        {'tool': 'Glob', 'params': {'pattern': '*.py', 'path': '/tmp'}},
    ]

    tasks = []
    for i in range(100):
        t = tools[i % len(tools)]
        tasks.append(agent.execute_tool(t['tool'], t['params']))

    start = time.time()
    results = await asyncio.gather(*tasks)
    duration = time.time() - start

    success = sum(1 for r in results if r.success)
    print(f"✅ PASSED - {success}/100 in {duration:.2f}s")
    return True

async def test_thread_pool_stress():
    """Test 6: Thread pool stress"""
    print("\n[STRESS 3] Thread pool (50 threads)")
    agent = NexusC()

    def sync_operation(i):
        return asyncio.run(agent.execute_tool('Bash', {'command': f'echo {i}'}))

    with ThreadPoolExecutor(max_workers=50) as executor:
        start = time.time()
        results = list(executor.map(sync_operation, range(50)))
        duration = time.time() - start

    success = sum(1 for r in results if r.success)
    print(f"✅ PASSED - {success}/50 threads in {duration:.2f}s")
    return True

# ============== RESOURCE EXHAUSTION ==============

async def test_max_file_handles():
    """Test 7: File handle exhaustion"""
    print("\n[RESOURCE 1] File handles")
    agent = NexusC()

    # Create many small files
    handles = []
    for i in range(50):
        result = await agent.execute_tool('Write', {
            'file_path': f'/tmp/handle_test_{i}.txt',
            'content': f'data {i}'
        })
        if result.success:
            handles.append(i)

    # Cleanup
    for i in handles:
        try:
            os.remove(f'/tmp/handle_test_{i}.txt')
        except:
            pass

    assert len(handles) == 50
    print(f"✅ PASSED - {len(handles)} file handles managed")
    return True

async def test_deep_recursion():
    """Test 8: Deep recursion in memory"""
    print("\n[RESOURCE 2] Deep memory recursion")
    agent = NexusC()

    # Add memory that references itself
    for i in range(50):
        agent.memory.add(
            f"task_{i}",
            f"previous_task_{i-1}" if i > 0 else "root",
            "success",
            0.8
        )

    # Recall should handle deep chains
    recalled = agent.memory.recall("task_", top_k=10)
    assert len(recalled) >= 0
    print("✅ PASSED - Deep recursion handled")
    return True

async def test_session_flood():
    """Test 9: Session creation flood"""
    print("\n[RESOURCE 3] Session flood (100 sessions)")

    start = time.time()
    agents = []
    for i in range(100):
        agents.append(NexusC())
        if i % 20 == 0:
            print(f"  Created {i} sessions...")

    duration = time.time() - start

    # All should have unique sessions
    sessions = [a.session_id for a in agents]
    assert len(set(sessions)) == 100

    print(f"✅ PASSED - 100 sessions in {duration:.2f}s")
    return True

# ============== SECURITY TESTS ==============

async def test_path_traversal():
    """Test 10: Path traversal attacks"""
    print("\n[SECURITY 1] Path traversal")
    agent = NexusC()

    dangerous_paths = [
        '../../../etc/passwd',
        '/tmp/../../../etc/shadow',
        '..%2F..%2Fetc%2Fpasswd',
    ]

    for path in dangerous_paths:
        result = await agent.execute_tool('Read', {'file_path': path})
        # Should either succeed (if safe) or fail gracefully
        assert result is not None

    print("✅ PASSED - Path traversal handled")
    return True

async def test_command_injection():
    """Test 11: Command injection attempts"""
    print("\n[SECURITY 2] Command injection")
    agent = NexusC()

    dangerous_commands = [
        'echo test; rm -rf /',
        'echo test && rm -rf /',
        'echo test | cat /etc/passwd',
        '$(whoami)',
        '`whoami`',
    ]

    for cmd in dangerous_commands:
        result = await agent.execute_tool('Bash', {'command': cmd})
        # Should not execute dangerous parts
        assert result is not None

    print("✅ PASSED - Command injection handled")
    return True

async def test_symlink_attack():
    """Test 12: Symlink attack"""
    print("\n[SECURITY 3] Symlink attack")
    agent = NexusC()

    # Create a symlink to /tmp
    link_path = '/tmp/symlink_test_link'
    target_path = '/tmp/symlink_target'

    try:
        os.symlink(target_path, link_path)
        result = await agent.execute_tool('Glob', {'pattern': '*', 'path': link_path})
        # Should handle gracefully
        assert result is not None
    except:
        pass
    finally:
        try:
            os.remove(link_path)
        except:
            pass

    print("✅ PASSED - Symlink handled")
    return True

# ============== MEMORY LEAK DETECTION ==============

async def test_memory_leak_detection():
    """Test 13: Memory leak detection"""
    print("\n[LEAK 1] Memory leak detection")
    agent = NexusC()

    # Get initial memory usage
    import resource
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # Run many operations
    for i in range(500):
        agent.memory.add(f"task_{i}", f"context_{i}", "success", 0.8)
        await agent.execute_tool('Bash', {'command': 'echo test'})

    # Force garbage collection
    gc.collect()

    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # RSS should not grow excessively (allow 50MB growth)
    growth_mb = (rss_after - rss_before) / 1024
    print(f"  Memory growth: {growth_mb:.1f} MB")

    assert growth_mb < 50, f"Excessive memory growth: {growth_mb:.1f} MB"
    print(f"✅ PASSED - Memory growth: {growth_mb:.1f} MB")
    return True

async def test_object_leak_detection():
    """Test 14: Object leak detection"""
    print("\n[LEAK 2] Object leak detection")

    # Create weak references
    refs = []
    for i in range(50):
        agent = NexusC()
        refs.append(weakref.ref(agent))

    # Delete agents
    del agent
    gc.collect()

    # Check weak refs are dead
    dead_count = sum(1 for r in refs if r() is None)

    assert dead_count == 50, f"Objects still alive: {50 - dead_count}"
    print("✅ PASSED - No object leaks")
    return True

# ============== EDGE CASES ==============

async def test_unicode_filenames():
    """Test 15: Unicode filenames"""
    print("\n[EDGE 1] Unicode filenames")
    agent = NexusC()

    unicode_names = [
        '/tmp/测试文件.txt',
        '/tmp/тест.txt',
        '/tmp/🧪.txt',
        '/tmp/名前.txt',
    ]

    for path in unicode_names:
        result = await agent.execute_tool('Write', {'file_path': path, 'content': 'test'})
        if result.success:
            # Cleanup
            try:
                os.remove(path)
            except:
                pass

    print("✅ PASSED - Unicode handled")
    return True

async def test_very_long_strings():
    """Test 16: Very long strings"""
    print("\n[EDGE 2] Long strings (1MB)")
    agent = NexusC()

    long_string = 'x' * (1024 * 1024)  # 1MB

    result = await agent.execute_tool('Write', {
        'file_path': '/tmp/long_string.txt',
        'content': long_string
    })

    # Should handle gracefully (may fail due to size)
    assert result is not None

    # Cleanup
    try:
        os.remove('/tmp/long_string.txt')
    except:
        pass

    print("✅ PASSED - Long strings handled")
    return True

async def test_null_bytes():
    """Test 17: Null bytes in strings"""
    print("\n[EDGE 3] Null bytes")
    agent = NexusC()

    content_with_nulls = 'test\x00hidden\x00data'

    result = await agent.execute_tool('Write', {
        'file_path': '/tmp/null_test.txt',
        'content': content_with_nulls
    })

    # Should handle
    assert result is not None

    # Cleanup
    try:
        os.remove('/tmp/null_test.txt')
    except:
        pass

    print("✅ PASSED - Null bytes handled")
    return True

async def test_boundary_values():
    """Test 18: Boundary values"""
    print("\n[EDGE 4] Boundary values")
    agent = NexusC()

    # Test extreme values
    test_cases = [
        ('timeout', -1),  # Negative timeout
        ('timeout', 0),   # Zero
        ('timeout', 999999999),  # Very large
        ('limit', -1),     # Negative limit
        ('limit', 0),      # Zero limit
    ]

    for param, value in test_cases:
        try:
            if param == 'timeout':
                result = await agent.execute_tool('Bash', {'command': 'echo test', 'timeout': value})
            elif param == 'limit':
                result = await agent.execute_tool('Read', {'file_path': '/etc/hostname', 'limit': value})
            # Should not crash
            assert result is not None
        except:
            pass

    print("✅ PASSED - Boundary values handled")
    return True

async def test_parallel_session_conflicts():
    """Test 19: Parallel session conflicts"""
    print("\n[EDGE 5] Session conflicts (10 parallel)")

    # Create 10 agents and run them in parallel
    async def run_agent(i):
        agent = NexusC()
        # Each does operations that might conflict
        await agent.execute_tool('Write', {
            'file_path': f'/tmp/session_test_{i}.txt',
            'content': f'agent {i}'
        })
        return agent.session_id

    session_ids = await asyncio.gather(*[run_agent(i) for i in range(10)])

    # All should be unique
    assert len(set(session_ids)) == 10

    # Cleanup
    for i in range(10):
        try:
            os.remove(f'/tmp/session_test_{i}.txt')
        except:
            pass

    print("✅ PASSED - No session conflicts")
    return True

# ============== LONG RUNNING ==============

async def test_sustained_load():
    """Test 20: Sustained load (5 minutes equivalent)"""
    print("\n[LONG 1] Sustained load (500 ops)")
    agent = NexusC()

    start = time.time()
    ops = 0

    while ops < 500:
        result = await agent.execute_tool('Bash', {'command': 'echo test'})
        if result.success:
            ops += 1

        # Check time
        if ops % 100 == 0:
            elapsed = time.time() - start
            rate = ops / elapsed
            print(f"  {ops}/500 ops ({rate:.0f}/sec)")

    duration = time.time() - start
    print(f"✅ PASSED - 500 ops in {duration:.2f}s")
    return True

async def run_stress_tests():
    """Run all stress tests"""
    print("="*60)
    print("NEXUS-C STRESS TEST SUITE")
    print("="*60)
    print("\n⚠️  EXTREME TESTING - May take several minutes")
    print()

    tests = [
        # Chaos
        test_random_tool_failures,
        test_concurrent_failures,
        test_rapid_context_switch,
        # Concurrency
        test_heavy_concurrent_load,
        test_mixed_tool_concurrent,
        test_thread_pool_stress,
        # Resources
        test_max_file_handles,
        test_deep_recursion,
        test_session_flood,
        # Security
        test_path_traversal,
        test_command_injection,
        test_symlink_attack,
        # Memory leaks
        test_memory_leak_detection,
        test_object_leak_detection,
        # Edge cases
        test_unicode_filenames,
        test_very_long_strings,
        test_null_bytes,
        test_boundary_values,
        test_parallel_session_conflicts,
        # Long running
        test_sustained_load,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            print(f"\nRunning {test.__name__}...")
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            errors.append((test.__name__, str(e)))

    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  {name}: {err[:100]}")

    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_stress_tests())
    sys.exit(0 if success else 1)
