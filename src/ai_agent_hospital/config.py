"""Configurações lidas de variáveis de ambiente (e do arquivo .env, se existir)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# O padrão do Ollama (4096 tokens sem GPU grande) não cabe o prompt com a ontologia de dengue.
DEFAULT_OLLAMA_NUM_CTX = 16384
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ai_agent_hospital"
DEFAULT_MCP_SERVER_COMMAND = "uv"
DEFAULT_MCP_SERVER_ARGS = "run --directory ${SMART_HOSPITALS_PATH} dengue-mcp"


@dataclass(frozen=True)
class Settings:
    """Configurações da aplicação; veja a tabela de variáveis no README."""

    ollama_model: str
    ollama_base_url: str
    database_url: str
    # Servidor MCP externo (repo smart_hospitals), iniciado via stdio.
    smart_hospitals_path: str | None = None
    mcp_server_command: str = DEFAULT_MCP_SERVER_COMMAND
    mcp_server_args: str = DEFAULT_MCP_SERVER_ARGS
    # Ontologias (YAML) somadas ao system prompt. Diretório None = padrão `ontologies/`, que pode
    # não existir; um diretório definido de propósito precisa existir. Lista None = todos os .yaml.
    ontologies_dir: str | None = None
    ontologies: tuple[str, ...] | None = None
    ollama_num_ctx: int = DEFAULT_OLLAMA_NUM_CTX


def parse_ontologies(value: str | None) -> tuple[str, ...] | None:
    """Lista separada por vírgula; vazia ou ausente vira None (carregar todos os .yaml)."""
    names = tuple(name.strip() for name in (value or "").split(",") if name.strip())
    return names or None


def get_settings() -> Settings:
    """Carrega o .env (sem sobrescrever variáveis já definidas) e monta as configurações."""
    load_dotenv()
    return Settings(
        ollama_model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        smart_hospitals_path=os.getenv("SMART_HOSPITALS_PATH") or None,
        mcp_server_command=os.getenv("MCP_SERVER_COMMAND", DEFAULT_MCP_SERVER_COMMAND),
        mcp_server_args=os.getenv("MCP_SERVER_ARGS", DEFAULT_MCP_SERVER_ARGS),
        ontologies_dir=os.getenv("ONTOLOGIES_DIR") or None,
        ontologies=parse_ontologies(os.getenv("ONTOLOGIES")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX") or DEFAULT_OLLAMA_NUM_CTX),
    )
