"""
Shared pytest fixtures for all RAG service tests.
"""
import sys
import os

# Ensure project root is on the path so `app.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def sample_texts():
    return [
        "The quick brown fox jumps over the lazy dog.",
        "Machine learning is a subset of artificial intelligence.",
        "FastAPI is a modern Python web framework.",
        "Vector databases enable semantic search at scale.",
        "Redis is an in-memory data structure store.",
    ]


@pytest.fixture
def dummy_vector(dim=768):
    import numpy as np
    v = np.random.rand(dim).astype("float32")
    v /= np.linalg.norm(v)
    return v.tolist()
