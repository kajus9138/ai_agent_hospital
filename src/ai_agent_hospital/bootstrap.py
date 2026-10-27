"""Montagem da aplicação: banco, checkpointer, Ollama e servidor MCP ligados ao agente."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import psycopg

from ai_agent_hospital.agent.checkpointer import open_checkpointer
from ai_agent_hospital.agent.llm import check_ollama_health, get_llm
from ai_agent_hospital.agent.react_agent import HospitalReActAgent, create_hospital_agent
from ai_agent_hospital.agent.thread_manager import ThreadManager
from ai_agent_hospital.config import Settings, get_settings
from ai_agent_hospital.db.connection import create_pool, init_schema
from ai_agent_hospital.db.repository import ThreadRepository
from ai_agent_hospital.errors import (
    DatabaseConnectionError,
    MCPConnectionError,
    OllamaConnectionError,
)
from ai_agent_hospital.mcp_client import DengueMCPClient

DB_CONNECT_TIMEOUT = 10.0


@asynccontextmanager
async def open_session(
    settings: Settings | None = None, *, with_tools: bool
) -> AsyncIterator[ThreadManager]:
    """ThreadManager pronto para uso, com banco, checkpointer e (se `with_tools`) o servidor MCP.

    Sem tools o agente não chama o modelo nem sobe o servidor MCP: basta para listar, ler,
    bifurcar e apagar threads. Tudo é aberto e fechado nesta task (exigência do stdio do MCP), na
    ordem inversa da abertura, inclusive se a task for cancelada (Ctrl+C, SIGTERM).

    Levanta DatabaseConnectionError, OllamaConnectionError ou MCPConnectionError.
    """
    settings = settings or get_settings()
    # Antes do banco: sem Ollama o chat não serve, e esta checagem é a mais barata.
    if with_tools and not await check_ollama_health(settings):
        raise OllamaConnectionError(
            f"Ollama indisponível em {settings.ollama_base_url} ou modelo "
            f"{settings.ollama_model} não baixado (`ollama pull {settings.ollama_model}`)."
        )
    async with AsyncExitStack() as stack:
        # Pools pequenos: a CLI é um usuário só, e são dois (repository e checkpointer).
        pool = create_pool(settings.database_url, min_size=1, max_size=4)
        stack.push_async_callback(pool.close)
        try:
            # Sem retry próprio: o pool já tenta reconectar com backoff até o timeout.
            await pool.open(wait=True, timeout=DB_CONNECT_TIMEOUT)
            await init_schema(pool)
        except psycopg.Error as exc:
            raise DatabaseConnectionError(
                f"Não foi possível conectar ao PostgreSQL: {exc}. Confira o DATABASE_URL e se o "
                "banco está no ar (`docker compose up -d`)."
            ) from exc
        # CheckpointerError já é um DatabaseConnectionError.
        checkpointer = await stack.enter_async_context(
            open_checkpointer(settings.database_url, min_size=1, max_size=4)
        )

        llm = get_llm(settings)
        if with_tools:
            try:
                client = await stack.enter_async_context(DengueMCPClient.from_settings(settings))
            except ValueError as exc:  # MCP_SERVER_ARGS malformado (shlex)
                raise MCPConnectionError(f"MCP_SERVER_ARGS inválido: {exc}") from exc
            agent = await create_hospital_agent(llm, client, checkpointer)
        else:
            agent = HospitalReActAgent(llm, [], checkpointer)
        yield ThreadManager(agent, ThreadRepository(pool))
