"""Local vector memory and durable coordinator checkpoints."""
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient, models

from .config import ROOT


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


class Journal:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "sessions.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def put(self, state: dict) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,state) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                       (state["id"], json.dumps(state)))

    def get(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_pending(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT state FROM sessions ORDER BY rowid DESC LIMIT 100").fetchall()
        return [state for row in rows if (state := json.loads(row[0]))["status"] != "complete"]


class DebateMemory:
    collection = "completed_debates_v1"

    def __init__(self, directory: Path | None = None, embedder=None):
        self.directory = directory or ROOT / "data"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.client = QdrantClient(path=str(self.directory / "vectors"))
        self.embedder = embedder

    def _embed(self, text: str) -> list[float]:
        if self.embedder is None:
            from fastembed import TextEmbedding
            self.embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5",
                cache_dir=str(self.directory / "models"), threads=2)
        value = next(iter(self.embedder.embed([text])))
        return value.tolist() if hasattr(value, "tolist") else list(value)

    def search(self, resolution: str, limit: int = 3) -> list[dict]:
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return []
            vector = self._embed(resolution)
            result = self.client.query_points(collection_name=self.collection, query=vector,
                limit=limit, with_payload=True, score_threshold=0.82)
            matches = []
            for point in result.points:
                payload = point.payload or {}
                exact = normalize(resolution) == normalize(payload.get("resolution", ""))
                matches.append({"id": str(point.id), "resolution": payload["resolution"],
                    "date": payload["date"], "winner": payload.get("winner"),
                    "similarity": round(float(point.score), 4), "exact": exact})
            return sorted(matches, key=lambda item: (item["exact"], item["similarity"]), reverse=True)

    def save(self, record: dict) -> None:
        if not record.get("complete") or not record.get("data", {}).get("scores"):
            raise ValueError("Only completed, judged debates may enter vector memory")
        with self.lock:
            vector = self._embed(record["data"]["resolution"])
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(self.collection,
                    vectors_config=models.VectorParams(size=len(vector), distance=models.Distance.COSINE))
            self.client.upsert(self.collection, points=[models.PointStruct(
                id=record["id"], vector=vector,
                payload={"resolution": record["data"]["resolution"], "date": record["date"],
                         "winner": record["data"]["winner"], "record": record})], wait=True)

    def get(self, session_id: str) -> dict | None:
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return None
            results = self.client.retrieve(self.collection, ids=[session_id], with_payload=True)
            return (results[0].payload or {}).get("record") if results else None

    def close(self):
        with self.lock:
            self.client.close()


if __name__ == "__main__":
    memory = DebateMemory()
    try:
        vector = memory._embed("A school debate about smartphone rules.")
        print(f"Local embedding model ready: {len(vector)} dimensions")
    finally:
        memory.close()
