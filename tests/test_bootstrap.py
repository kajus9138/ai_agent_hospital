"""Montagem completa (`open_session`): PostgreSQL real, servidor MCP falso via stdio e LLM falso.

Exercita a integração ponta a ponta sem depender do Ollama; os erros de cada serviço saem com o
tipo certo; e o SIGTERM fecha o que foi aberto. Os testes `integration` precisam do PostgreSQL.
"""

import asyncio
import os
import shlex
import signal
import sys
from pathlib import Path

import pytest
import typer
from langchain_core.messages import AIMessage
from test_react_agent import scripted

from ai_agent_hospital import bootstrap, cli
from ai_agent_hospital.config import Settings
from ai_agent_hospital.errors import (
    DatabaseConnectionError,
    MCPConnectionError,
    OllamaConnectionError,
)
from ai_agent_hospital.mcp_client import DengueMCPClient

FAKE_SERVER = Path(__file__).parent / "fake_dengue_server.py"
UNREACHABLE_DB = "postgresql://postgres:postgres@127.0.0.1:1/nada?connect_timeout=1"


def make_settings(database_url: str, **overrides: str) -> Settings:
    params = {
        "ollama_model": "fake",
        "ollama_base_url": "http://127.0.0.1:1",
        "database_url": database_url,
        "mcp_server_command": sys.executable,
        "mcp_server_args": shlex.quote(str(FAKE_SERVER)),
    }
    return Settings(**(params | overrides))


@pytest.fixture
def fake_ollama(monkeypatch):
    """Ollama "no ar" e o LLM roteirizado no lugar do ChatOllama."""
    llm = scripted(
        AIMessage(content="", tool_calls=[{"name": "situacao_atual", "args": {}, "id": "call_1"}]),
        "Na semana 202643 houve 1250 casos.",
    )

    async def healthy(settings: Settings) -> bool:
        return True

    monkeypatch.setattr(bootstrap, "check_ollama_health", healthy)
    monkeypatch.setattr(bootstrap, "get_llm", lambda settings: llm)
    return llm


@pytest.fixture
def short_db_timeout(monkeypatch):
    monkeypatch.setattr(bootstrap, "DB_CONNECT_TIMEOUT", 1.0)


@pytest.mark.integration
async def test_end_to_end_conversation(schema_url, fake_ollama):
    async with bootstrap.open_session(make_settings(schema_url), with_tools=True) as manager:
        thread_id = await manager.create_thread()
        answer = await manager.send_message(thread_id, "Como está a dengue?")
        history = await manager.get_history(thread_id)

    assert answer == "Na semana 202643 houve 1250 casos."
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    # A tool rodou de verdade no servidor MCP (stdio), não no LLM falso.
    assert "1250" in history[2].content


async def test_unreachable_database_raises_database_error(short_db_timeout):
    with pytest.raises(DatabaseConnectionError, match="DATABASE_URL"):
        async with bootstrap.open_session(make_settings(UNREACHABLE_DB), with_tools=False):
            pass


async def test_ollama_down_fails_before_opening_database(monkeypatch):
    async def down(settings: Settings) -> bool:
        return False

    monkeypatch.setattr(bootstrap, "check_ollama_health", down)
    # Banco inacessível: se ele fosse aberto antes, o erro seria DatabaseConnectionError.
    with pytest.raises(OllamaConnectionError, match="ollama pull fake"):
        async with bootstrap.open_session(make_settings(UNREACHABLE_DB), with_tools=True):
            pass


@pytest.mark.integration
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"mcp_server_command": "comando-que-nao-existe"}, "não encontrado no PATH"),
        ({"mcp_server_args": "'aspas sem fechar"}, "MCP_SERVER_ARGS inválido"),
    ],
)
async def test_mcp_misconfigured_raises_mcp_error(schema_url, fake_ollama, overrides, match):
    with pytest.raises(MCPConnectionError, match=match):
        async with bootstrap.open_session(make_settings(schema_url, **overrides), with_tools=True):
            pass


@pytest.mark.integration
async def test_sigterm_closes_connections(schema_url, fake_ollama, monkeypatch):
    clients: list[DengueMCPClient] = []
    original = DengueMCPClient.from_settings

    def tracked(settings: Settings, **kwargs) -> DengueMCPClient:
        clients.append(original(settings, **kwargs))
        return clients[-1]

    monkeypatch.setattr(DengueMCPClient, "from_settings", tracked)
    pools = []

    async def serve() -> None:
        async with bootstrap.open_session(make_settings(schema_url), with_tools=True) as manager:
            pools.append(manager.repository.pool)
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(3600)

    with pytest.raises(typer.Exit) as info:
        await cli._cancel_on_sigterm(serve())

    assert info.value.exit_code == cli.EXIT_SIGTERM
    assert pools[0].closed
    assert clients[0]._session is None  # sessão e subprocesso MCP encerrados
