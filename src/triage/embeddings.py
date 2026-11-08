"""Local sentence-transformers embeddings (ONNX via fastembed) behind LangChain's Embeddings interface."""
from __future__ import annotations

import hashlib
import json
import re
import threading

from langchain_core.embeddings import Embeddings

_lock = threading.Lock()
_models: dict[str, object] = {}


def model_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[-40:]


class LocalEmbeddings(Embeddings):
    def __init__(self, model_name: str, cache_dir: str | None = None, redis=None, ttl: int = 86400) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.redis = redis
        self.ttl = ttl

    def _model(self):
        with _lock:
            if self.model_name not in _models:
                from fastembed import TextEmbedding

                _models[self.model_name] = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
            return _models[self.model_name]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model().embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        key = None
        if self.redis is not None:
            key = "emb:" + model_slug(self.model_name) + ":" + hashlib.sha1(text.encode()).hexdigest()
            try:
                hit = self.redis.get(key)
                if hit:
                    return json.loads(hit)
            except Exception:
                pass
        vec = next(iter(self._model().query_embed([text]))).tolist()
        if key:
            try:
                self.redis.set(key, json.dumps(vec), ex=self.ttl)
            except Exception:
                pass
        return vec
