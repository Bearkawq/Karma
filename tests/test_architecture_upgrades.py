from agent.agent_loop import AgentLoop, load_config
from core.runtime_governor import RuntimeGovernor
from core.retrieval import RetrievalBus


def test_runtime_governor_cools_down_tools():
    gov = RuntimeGovernor(parse_cache_size=8, cooldown_failures=2, cooldown_turns=2)
    gov.record_tool_result("shell", False)
    gov.record_tool_result("shell", False)
    assert gov.allow_tool("shell") is False
    gov.record_execution(True, 0.7)
    gov.record_execution(True, 0.7)
    assert gov.allow_tool("shell") is True


def test_retrieval_cache_invalidation():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    rb = agent.retrieval
    a = rb.retrieve_context_bundle("what can you do", "respond")
    first_hits = rb._metrics.get("cache_hits", 0)
    b = rb.retrieve_context_bundle("what can you do", "respond")
    assert len(a) == len(b)
    assert rb._metrics.get("cache_hits", 0) >= first_hits + 1
    old_gen = rb._cache_generation
    rb.store_health_event("cache test issue", "warning", "none", "tests")
    assert rb._cache_generation == old_gen + 1


def test_capabilities_output_includes_governor_snapshot():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    out = agent.run("what can you do")
    assert "Tools:" in out
    assert "Memory:" in out
