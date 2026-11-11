from uuid import uuid4

import pytest

from forum.memory import DebateMemory, Journal


class TinyEmbedder:
    def embed(self, texts):
        for text in texts:
            yield [1.0, 0.0, 0.0] if any(word in text.lower() for word in ("phone", "smartphone")) else [0.0, 1.0, 0.0]


def record():
    return {"id": str(uuid4()), "date": "2026-10-31T12:00:00+00:00", "complete": True,
            "live": True, "model": "test", "data": {"resolution": "Schools should ban phones.",
            "scores": [20]*8, "winner": "Tie"}}


def test_real_qdrant_vectors_persist_and_are_idempotent(tmp_path):
    debate = record()
    memory = DebateMemory(tmp_path, TinyEmbedder())
    assert memory.search("Schools should ban phones.") == []
    memory.save(debate)
    memory.save(debate)
    assert memory.search("Schools should ban phones.")[0]["exact"] is True
    assert memory.search("Ban smartphones in school")[0]["id"] == debate["id"]
    assert memory.search("All students should wear uniforms.") == []
    memory.close()
    memory = DebateMemory(tmp_path, TinyEmbedder())
    assert memory.get(debate["id"]) == debate
    assert len(memory.search("Schools should ban phones.")) == 1
    memory.close()


def test_incomplete_debates_never_enter_vector_memory(tmp_path):
    memory = DebateMemory(tmp_path, TinyEmbedder())
    debate = record()
    debate["complete"] = False
    with pytest.raises(ValueError):
        memory.save(debate)
    assert memory.search("Schools should ban phones.") == []
    memory.close()


def test_journal_round_trips_checkpoints(tmp_path):
    journal = Journal(tmp_path)
    state = {"id": str(uuid4()), "resolution": "A resolution", "status": "needs_human", "outputs": {"opening": "case"}}
    journal.put(state)
    assert Journal(tmp_path).get(state["id"])["outputs"] == {"opening": "case"}
    assert len(journal.list_pending()) == 1
    state["status"] = "complete"
    journal.put(state)
    assert journal.list_pending() == []
