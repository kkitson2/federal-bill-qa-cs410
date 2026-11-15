"""Meaning-based (dense) search: sections are split into overlapping chunks, each chunk is embedded,
and a section scores as its best chunk (max-passage). Needs `uv sync --group search`.

The embedding model (about 70 MB) downloads once into the cache directory; chunk embeddings are
cached there too, keyed by model and chunk text, so later runs start in a second.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .corpus import Section

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# BGE's recommended instruction for short queries against passages.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CHUNK_WORDS = 200  # well under the model's 512-token limit
CHUNK_OVERLAP = 50


def cache_dir() -> Path:
    return Path(os.getenv("SEARCH_CACHE_DIR") or Path.cwd() / ".cache" / "search")


def chunk_section(section: Section, words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Overlapping word windows, each prefixed with the heading so it keeps its topic."""
    if overlap >= words:
        raise ValueError("overlap must be smaller than the chunk size")
    tokens = section.text.split()
    head = f"{section.heading}\n" if section.heading else ""
    if not tokens:
        return [head.strip() or section.section_id]
    step = words - overlap
    starts = range(0, max(len(tokens) - overlap, 1), step)
    return [head + " ".join(tokens[i:i + words]) for i in starts]


class SemanticIndex:
    def __init__(self, sections: list[Section], model: str = DEFAULT_MODEL):
        import numpy as np
        from fastembed import TextEmbedding

        self._np = np
        self.model_name = model
        self.chunks: list[str] = []
        self.owner: list[int] = []  # chunk -> section index
        for i, section in enumerate(sections):
            for chunk in chunk_section(section):
                self.chunks.append(chunk)
                self.owner.append(i)
        self.owner_array = np.asarray(self.owner)
        self.n_sections = len(sections)
        cache = cache_dir()
        self.model = TextEmbedding(model_name=model, cache_dir=str(cache / "models"))
        self.vectors = self._load_or_embed(cache)

    def _load_or_embed(self, cache: Path):
        np = self._np
        key = hashlib.sha256("\x00".join([self.model_name, *self.chunks]).encode()).hexdigest()[:16]
        path = cache / f"{self.model_name.replace('/', '__')}-{key}.npy"
        if path.exists():
            return np.load(path)
        vectors = self._normalize(np.asarray(list(self.model.embed(self.chunks, batch_size=32)), dtype=np.float32))
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, vectors)
        return vectors

    def _normalize(self, m):
        return m / self._np.maximum(self._np.linalg.norm(m, axis=1, keepdims=True), 1e-12)

    def scores(self, question: str) -> list[float]:
        """Cosine similarity of each section's best chunk to the question."""
        np = self._np
        q = self._normalize(np.asarray(list(self.model.embed([QUERY_PREFIX + question])), dtype=np.float32))[0]
        chunk_scores = self.vectors @ q
        best = np.full(self.n_sections, -1.0, dtype=np.float32)
        np.maximum.at(best, self.owner_array, chunk_scores)
        return best.tolist()
