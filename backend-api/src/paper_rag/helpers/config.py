from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# built from __file__: the old "src\paper_rag\.env" was a Windows path and failed on Linux
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    ## LLM. Gemini keys come from the numbered pool in the environment (GEMINI_API_KEY_1..), never from this file.
    GEMINI_API_KEY: str = ""
    COHERE_API_KEY: str = ""        # optional: with a key the reranker is Cohere, without it rank fusion
    EMBEDDING_PROVIDER: str = "gemini"   # gemini | cohere
    EMBEDDING_SIZE: int = 768
    GENERATION_MODEL_ID: str = ""
    EMBEDDING_MODEL_ID: str = "gemini-embedding-001"

    MAX_INPUT_TOKENS: int = 8000
    MAX_OUTPUT_TOKENS: int = 1000
    TEMPERATURE: float = 0.2

    RERANKER_BACKEND: str = "auto"       # auto | cohere | rrf
    RERANKER_MODEL_NAME: str = "rerank-v3.5"

    ## postgres
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_MAIN_DB: str = ""

    TABLE_NAME: str = "chunks"

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")


def get_settings() -> Settings:
    return Settings()
