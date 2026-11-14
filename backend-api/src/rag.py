"""The scoped RAG for the agent (Round 9 §9.5.2): one lazily built AskSources, so importing the agent touches neither Postgres nor Cohere.

Needs: Postgres with the Cohere index (docker/docker-compose.yml), COHERE_API_KEY_1.. and GEMINI_API_KEY_1.. / GROQ_API_KEY_1.. in the environment,
src/paper_rag/.env (TABLE_NAME=chunks_cohere, EMBEDDING_PROVIDER=cohere, EMBEDDING_SIZE=1024, EMBEDDING_MODEL_ID=embed-v4.0). Without them `available()`
is False and the agent falls back to the serving.db text search (search_text), LOUDLY: `startup_check()` prints one line (RAG: ON / RAG: OFF, reason)
and every fallback answer is recorded in logs/retrieval.jsonl with its path.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("rag")
_asker = None
_override = None


def set_asker(a) -> None:
    """Tests (and the live agent, if it wants to) inject an AskSources / fake."""
    global _override
    _override = a


class Status:
    """Is the RAG usable, and if not, why. Printed once at startup and recorded on every answer that does not come from it."""

    def __init__(self, on: bool = False, reason: str = "not checked yet", detail: str = "", checked: bool = False) -> None:
        self.on, self.reason, self.detail, self.checked = on, reason, detail, checked

    @property
    def line(self) -> str:
        if self.on:
            return f"RAG: ON ({self.detail})"
        return f"RAG: OFF, {self.reason}. Free questions are answered by the old serving.db text search (search_text), without sources or the checker."


STATUS = Status()


class RemoteAsker:
    """The RAG of a deployed agent (LiveKit Cloud): it has no Postgres. The question goes to the backend API (POST /api/internal/rag/ask, header X-Internal-Key),
    which runs the same AskSources next to Postgres. Same `ask()` contract and result as the local one."""

    def __init__(self, url: str, key: str, timeout: float = 6.0) -> None:
        import httpx
        self.url, self.key = url.rstrip("/"), key
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0))
        self.s = None

    async def ask(self, question: str, **params) -> dict:
        r = await self.http.post(f"{self.url}/api/internal/rag/ask", headers={"X-Internal-Key": self.key}, json={"question": question, "params": {k: v for k, v in params.items() if v is not None}})
        r.raise_for_status()
        return r.json()


def remote_url() -> str:
    return os.getenv("RAG_API_URL", "").strip()


async def check(timeout: float = 4.0) -> Status:
    """Everything the RAG needs, in order; the first thing missing is the reason. Uses its own throw-away engine (the agent's loop is not running yet)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    if os.getenv("RAG_ENABLED", "1") == "0":
        return Status(False, "disabled by RAG_ENABLED=0", checked=True)
    if remote_url():                                   # a deployed agent: the backend API owns Postgres, Cohere and the composer
        import httpx
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(remote_url().rstrip("/") + "/health")
            if r.status_code == 200 and r.json().get("rag"):
                return Status(True, "", f"remote RAG at {remote_url()}", checked=True)
            return Status(False, f"the backend API at {remote_url()} says its RAG is off", checked=True)
        except Exception as e:  # noqa: BLE001
            return Status(False, f"the backend API at {remote_url()} is not reachable ({type(e).__name__})", checked=True)
    if not any(k.lower().startswith("cohere_api_key") for k in os.environ):
        return Status(False, "no COHERE_API_KEY_* in the environment (embeddings and rerank need them)", checked=True)
    if not os.getenv("FLAMEO_DB"):
        return Status(False, "FLAMEO_DB is not set (the scope needs serving.db)", checked=True)
    try:
        from src.paper_rag.helpers.config import get_settings
        st = get_settings()
    except Exception as e:  # noqa: BLE001
        return Status(False, f"src/paper_rag/.env is unreadable ({type(e).__name__})", checked=True)
    if not (st.POSTGRES_USER and st.POSTGRES_MAIN_DB):
        return Status(False, "Postgres settings are missing in src/paper_rag/.env", checked=True)
    eng = create_async_engine(f"postgresql+asyncpg://{st.POSTGRES_USER}:{st.POSTGRES_PASSWORD}@{st.POSTGRES_HOST}:{st.POSTGRES_PORT}/{st.POSTGRES_MAIN_DB}")
    try:
        async with eng.connect() as c:
            await asyncio.wait_for(c.execute(text("select 1")), timeout)
            exists = (await c.execute(text("select 1 from pg_tables where tablename = :t"), {"t": st.TABLE_NAME})).scalar_one_or_none()
            if not exists:
                return Status(False, f"the index table {st.TABLE_NAME} does not exist in Postgres", checked=True)
            n = (await c.execute(text(f'select count(*) from "{st.TABLE_NAME}"'))).scalar_one()
            if not n:
                return Status(False, f"the index table {st.TABLE_NAME} is empty", checked=True)
    except Exception as e:  # noqa: BLE001
        return Status(False, f"Postgres not reachable at {st.POSTGRES_HOST}:{st.POSTGRES_PORT} ({type(e).__name__})", checked=True)
    finally:
        await eng.dispose()
    comp = [n for n in ("GEMINI", "GROQ") if any(k.upper().startswith(f"{n}_API_KEY") for k in os.environ)]
    answer = "composer " + " + ".join(c.lower() for c in comp) if comp else "NO composer keys: extractive sentences only"
    return Status(True, "", f"{st.TABLE_NAME}, {n:,} chunks, {st.EMBEDDING_MODEL_ID}, Cohere rerank, {answer}", checked=True)


def startup_check(required: bool | None = None) -> Status:
    """Called once when the agent starts. Prints one clear line. RAG_REQUIRED=1 stops the agent instead of running without the RAG."""
    global STATUS
    try:
        STATUS = asyncio.run(check())
    except Exception as e:  # noqa: BLE001
        STATUS = Status(False, f"the check itself failed ({type(e).__name__}: {e})", checked=True)
    print(STATUS.line, flush=True)   # one line, on stdout where the demo operator looks
    if required is None:
        required = os.getenv("RAG_REQUIRED", "0") == "1"
    if required and not STATUS.on:
        raise SystemExit(STATUS.line + " (RAG_REQUIRED=1)")
    return STATUS


def available() -> bool:
    if _override is not None:
        return True
    if STATUS.checked:
        return STATUS.on
    if os.getenv("RAG_ENABLED", "1") == "0":
        return False
    if remote_url():
        return True
    return any(k.lower().startswith("cohere_api_key") for k in os.environ)


def off_reason() -> str:
    return STATUS.reason if STATUS.checked and not STATUS.on else ("disabled by RAG_ENABLED=0" if os.getenv("RAG_ENABLED", "1") == "0" else "no COHERE_API_KEY_* in the environment")


def get():
    global _asker
    if _override is not None:
        return _override
    if _asker is None:
        _asker = build()
    return _asker


def build(budget_s: float = 4.0):
    if remote_url():
        return RemoteAsker(remote_url(), os.getenv("RAG_INTERNAL_KEY", ""))
    from src import flameo
    from src.paper_rag import chunks as C
    from src.paper_rag.ask import AskSources
    from src.paper_rag.db import db_client
    from src.paper_rag.factory import composer_pools, embedder, reranker
    from src.paper_rag.helpers.config import get_settings
    from src.paper_rag.scope import ScopeResolver
    from src.paper_rag.search import Searcher
    from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider

    st = get_settings()
    serving = os.getenv("FLAMEO_DB", "")
    searcher = Searcher(PGvectorProvider(db_client()), st.TABLE_NAME, embedder(st), reranker(st))
    from src.paper_rag.extract import Extractor

    return AskSources(searcher, ScopeResolver(serving), composer_pools(), C.Vocab.from_serving(serving), serving_call=flameo.call, budget_s=budget_s, extractor=Extractor(serving))


_extractor = None


def extractor():
    """The question-text extractor (needs only FLAMEO_DB, not Postgres or Cohere): used by the router guard and by the conditions binding."""
    global _extractor
    if _extractor is None and os.getenv("FLAMEO_DB"):
        from src.paper_rag.extract import Extractor
        _extractor = Extractor(os.environ["FLAMEO_DB"])
    return _extractor


async def warm_up() -> None:
    """One embed + one rerank call at start-up, so the first question of the session does not pay for connection setup (Round 12 item 1). Never raises."""
    try:
        a = get()
        if getattr(a, "s", None) is None:
            return
        await asyncio.wait_for(a.s.search("microgravity flame spread", scope=None, top_n=2), timeout=6)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("rag").info("warm-up skipped (%s)", type(e).__name__)
