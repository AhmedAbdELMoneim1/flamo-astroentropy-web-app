"""One place that builds the embedder, reranker and table name from the settings, so the Gemini and the Cohere index run through the same code.

  EMBEDDING_PROVIDER=gemini  TABLE_NAME=chunks         EMBEDDING_SIZE=768   (gemini-embedding-001)
  EMBEDDING_PROVIDER=cohere  TABLE_NAME=chunks_cohere  EMBEDDING_SIZE=1024  (embed-v4.0)
"""
from __future__ import annotations

from pathlib import Path

from src.paper_rag.helpers.config import Settings, get_settings
from src.paper_rag.keypool import KeyPool, Limits, env_limits
from src.paper_rag.stores.llm.providers.CohereEmbedder import CohereEmbedder, CohereRerank
from src.paper_rag.stores.llm.providers.GeminiEmbedder import GeminiEmbedder

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "rag_cache"


def embedder(st: Settings | None = None):
    st = st or get_settings()
    if st.EMBEDDING_PROVIDER == "cohere":
        pool = KeyPool.from_env("COHERE", limits=env_limits("COHERE_EMBED_POOL", Limits(rpm=35, tpm=75_000, rpd=300)), state_file=CACHE / "cohere_embed_state.json")
        return CohereEmbedder(pool, st.EMBEDDING_MODEL_ID, st.EMBEDDING_SIZE)
    pool = KeyPool.from_env("GEMINI", state_file=CACHE / "keypool_state.json")
    return GeminiEmbedder(pool, st.EMBEDDING_MODEL_ID, st.EMBEDDING_SIZE)


def reranker(st: Settings | None = None):
    """Cohere rerank when Cohere keys exist, else None (rank fusion)."""
    st = st or get_settings()
    if st.RERANKER_BACKEND == "rrf":
        return None
    try:
        pool = KeyPool.from_env("COHERE", limits=env_limits("COHERE_RERANK_POOL", Limits(rpm=35, tpm=10**9, rpd=300)), state_file=CACHE / "cohere_rerank_state.json")
    except ValueError:
        return None
    return CohereRerank(pool, st.RERANKER_MODEL_NAME, timeout=float(__import__('os').getenv('COHERE_RERANK_TIMEOUT', '1.5')))


def composer_pools():
    """Key pools of the composer: Gemini (gemini-3.5-flash-lite) first, Groq second; either may be missing."""
    from src.paper_rag.composer import Composer
    gem = grq = None
    try:
        gem = KeyPool.from_env("GEMINI", limits=env_limits("GEMINI_COMPOSE_POOL", Limits(rpm=8, tpm=200_000, rpd=400)), state_file=CACHE / "gemini_compose_state.json")
    except ValueError:
        pass
    try:
        grq = KeyPool.from_env("GROQ", limits=env_limits("GROQ_COMPOSE_POOL", Limits(rpm=20, tpm=6000, rpd=600)), state_file=CACHE / "groq_compose_state.json")
    except ValueError:
        pass
    return Composer(gem, grq)
