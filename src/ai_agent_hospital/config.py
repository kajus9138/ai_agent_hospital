"""Configurações lidas de variáveis de ambiente (e do arquivo .env, se existir)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ai_agent_hospital"


@dataclass(frozen=True)
class Settings:
    ollama_model: str
    ollama_base_url: str
    database_url: str


def get_settings() -> Settings:
    """Carrega o .env (sem sobrescrever variáveis já definidas) e monta as configurações."""
    load_dotenv()
    return Settings(
        ollama_model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
