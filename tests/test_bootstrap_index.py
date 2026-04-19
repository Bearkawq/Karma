import os
import sqlite3
from agents.retriever_agent import RetrieverAgent


class DummyAdapter:
    def __init__(self):
        self.is_loaded = True

    def embed(self, input_data):
        # return a fake vector blob
        return b"\x01\x02\x03\x04"


def test_bootstrap_creates_index(tmp_path, monkeypatch):
    # Ensure index path is in a temp data dir to avoid clobbering repo data
    orig_path = RetrieverAgent._index_path
    try:
        temp_data = tmp_path / "data"
        temp_data.mkdir()
        # override _get_index_path to point into tmp_path
        monkeypatch.setattr(RetrieverAgent, "_get_index_path", classmethod(lambda cls: str(temp_data / "embed_index.db")))
        # call bootstrap_index
        adapter = DummyAdapter()
        # ensure db does not exist
        dbpath = RetrieverAgent._get_index_path()
        if os.path.exists(dbpath):
            os.remove(dbpath)
        RetrieverAgent.bootstrap_index(adapter)
        assert os.path.exists(dbpath)
        con = sqlite3.connect(dbpath)
        cur = con.execute("SELECT COUNT(*) FROM bootstrap_log")
        count = cur.fetchone()[0]
        con.close()
        assert count >= 0
    finally:
        # restore
        RetrieverAgent._index_path = orig_path
