import pytest
import tempfile
import os
from storage.memory import MemorySystem


@pytest.fixture
def temp_memory():
    """Create temporary MemorySystem."""
    with tempfile.TemporaryDirectory() as td:
        ms = MemorySystem(
            episodic_file=os.path.join(td, "episodic.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json")
        )
        yield ms


def test_save_task_with_explicit_id(temp_memory):
    """save_task should use explicit id when provided."""
    ms = temp_memory
    task = {"id": "test_id_123", "status": "pending"}
    ms.save_task(task)
    assert "test_id_123" in ms.tasks
    loaded = ms.get_task("test_id_123")
    assert loaded["id"] == "test_id_123"


def test_save_task_without_id_generates_one(temp_memory):
    """save_task should generate id when missing."""
    ms = temp_memory
    task = {"status": "pending"}
    ms.save_task(task)
    loaded = ms.get_task(list(ms.tasks.keys())[0])
    assert loaded["id"].startswith("task_")


def test_save_task_empty_string_id_generates_new(temp_memory):
    """save_task with empty string id should generate new id."""
    ms = temp_memory
    task = {"id": "", "status": "pending"}
    ms.save_task(task)
    assert list(ms.tasks.keys())[0].startswith("task_")


def test_save_task_none_id_generates_new(temp_memory):
    """save_task with None id should generate new id."""
    ms = temp_memory
    task = {"id": None, "status": "pending"}
    ms.save_task(task)
    assert list(ms.tasks.keys())[0].startswith("task_")


def test_save_task_non_dict_fails_clearly(temp_memory):
    """save_task should fail clearly on non-dict."""
    ms = temp_memory
    with pytest.raises(ValueError, match="Task must be a dict"):
        ms.save_task("not a dict")
