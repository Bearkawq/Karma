#!/usr/bin/env python3
"""Smoke tests for Karma agent.

Verifies:
  - Clean CLI output (no timestamps, no telemetry, just the response)
  - Slang normalization works
  - Entity extraction works
  - run() always returns a string
"""

import sys
import os

# Run from project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from agent.agent_loop import AgentLoop, load_config


def run_smoke():
    config = load_config("config.json")
    agent = AgentLoop(config)

    tests = [
        ("list files", "list_files intent"),
        ("read file named test.txt", "read_file intent"),
        ('golearn python decorators 2 depth', "golearn intent"),
        ("what can you do", "capabilities"),
        ("wanna list files in /tmp", "slang normalization -> list_files"),
    ]

    passed = 0
    failed = 0

    for input_text, description in tests:
        print(f"\n--- Test: {description} ---")
        print(f"  Input: \"{input_text}\"")

        result = agent.run(input_text)

        # Must be a string
        if not isinstance(result, str):
            print(f"  FAIL: run() returned {type(result).__name__}, expected str")
            failed += 1
            continue

        # Must not be empty
        if not result.strip():
            print(f"  FAIL: run() returned empty string")
            failed += 1
            continue

        # Must not contain timestamps (ISO format)
        import re
        if re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', result):
            print(f"  FAIL: output contains timestamp: {result[:100]}")
            failed += 1
            continue

        # Print clean output
        print(f"  Output: {result[:200]}")
        print(f"  PASS")
        passed += 1

    # Test normalizer directly
    print(f"\n--- Test: Normalizer unit ---")
    from core.normalize import Normalizer
    n = Normalizer()
    cases = [
        ("wanna list files", "want to list files"),
        ("gimme the file pls", "give me the file please"),
        ("uh like show files yo", "show files"),
        ("I'm gonna read the file", "i am going to read the file"),
    ]
    norm_pass = True
    for raw, expected in cases:
        got = n.normalize_for_match(raw)
        if got != expected:
            print(f"  FAIL: normalize_for_match(\"{raw}\") = \"{got}\", expected \"{expected}\"")
            norm_pass = False
            failed += 1
    if norm_pass:
        print(f"  All normalizer cases passed")
        passed += 1

    # Test entity extraction fix
    print(f"\n--- Test: Entity extraction ---")
    from core.symbolic import SymbolicCore
    sc = SymbolicCore()
    sc.add_rule(r'(?P<command>read)\s+(?:the\s+)?file\s+(?:named?\s+)?(?P<filename>\S+)', 'read_file', 0.85)
    intent = sc.classify_intent("read file named config.json")
    entities = intent.get("entities", {})
    if entities.get("filename") == "config.json" and entities.get("command") == "read":
        print(f"  Entities: {entities}")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: expected filename=config.json, command=read, got {entities}")
        failed += 1

    # Test typo tolerance
    print(f"\n--- Test: Typo tolerance ---")
    from core.symbolic import SymbolicCore as SC2
    sc2 = SC2()
    sc2.add_rule(r'(?P<command>list|show)\s+(?:(?:the|my|all)\s+)?files', 'list_files', 0.9)
    sc2.add_rule(r'(?P<command>read)\s+(?:the\s+)?file\s+(?:named?\s+)?(?P<filename>\S+)', 'read_file', 0.85)
    typo_intent = sc2.classify_intent("lsit files")
    if typo_intent.get("intent") == "list_files":
        print(f"  'lsit files' -> {typo_intent['intent']} (conf={typo_intent['confidence']:.2f})")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: 'lsit files' -> {typo_intent.get('intent')}")
        failed += 1

    typo_intent2 = sc2.classify_intent("raed file named foo.py")
    if typo_intent2.get("intent") == "read_file":
        print(f"  'raed file named foo.py' -> {typo_intent2['intent']}")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: 'raed file named foo.py' -> {typo_intent2.get('intent')}")
        failed += 1

    # Test intent chaining
    print(f"\n--- Test: Intent chaining ---")
    result = agent.run("list files then what can you do")
    if isinstance(result, str) and "path:" in result and ("tool" in result.lower() or "help" in result.lower() or "learn" in result.lower()):
        print(f"  Chained output has both results")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: chain result: {result[:120]}")
        failed += 1

    # Test context memory ("again")
    print(f"\n--- Test: Context memory (again) ---")
    agent.run("list files")  # prime context
    result_again = agent.run("again")
    if isinstance(result_again, str) and "path:" in result_again:
        print(f"  'again' replayed list_files")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: 'again' returned: {result_again[:100]}")
        failed += 1

    # Test ML confidence calibration
    print(f"\n--- Test: ML confidence calibration ---")
    from ml.ml import NaiveBayesClassifier
    import math
    nb = NaiveBayesClassifier()
    nb.train([
        {"intent": "list_files", "features": ["list", "files"]},
        {"intent": "read_file", "features": ["read", "file"]},
        {"intent": "help", "features": ["help", "commands"]},
    ])
    _, conf = nb.classify(["list", "files"])
    if 0.3 < conf < 0.95:  # should NOT be ~1.0 anymore
        print(f"  Confidence: {conf:.3f} (reasonable range)")
        print(f"  PASS")
        passed += 1
    else:
        print(f"  FAIL: confidence={conf:.3f} (expected 0.3-0.95)")
        failed += 1

    # Summary
    total = passed + failed
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_smoke())
