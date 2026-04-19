from concurrent.futures import ThreadPoolExecutor

from agent.agent_loop import AgentLoop, load_config
from core.runtime_governor import RuntimeGovernor


def test_runtime_governor_thread_safe_cache_access():
    gov = RuntimeGovernor(parse_cache_size=16)

    def worker(i: int):
        key = f"hello-{i % 4}"
        gov.cache_intent(key, {"intent": "demo", "confidence": 0.9})
        return gov.get_cached_intent(key)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(100)))

    assert all(r and r.get("intent") == "demo" for r in results)
    snap = gov.snapshot()
    assert snap["parse_cache_entries"] <= 16


def test_search_output_is_readable():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    out = agent.run("search files *.py in tests")
    assert "matches:" in out
    assert "tests/" in out or "test_" in out
