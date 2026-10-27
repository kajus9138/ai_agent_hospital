"""Health check dos serviços de que o agente depende: Ollama, PostgreSQL e servidor MCP."""

import asyncio
import logging

import psycopg

from ai_agent_hospital.agent.llm import check_ollama_health
from ai_agent_hospital.config import Settings, get_settings
from ai_agent_hospital.mcp_client import DengueMCPClient

logger = logging.getLogger(__name__)


async def check_db_health(settings: Settings | None = None, timeout: float = 5.0) -> bool:
    """True se o PostgreSQL do DATABASE_URL aceita conexão e responde a uma consulta."""
    settings = settings or get_settings()
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url, connect_timeout=max(int(timeout), 1)
        ) as conn:
            await conn.execute("SELECT 1")
    except psycopg.Error as exc:
        logger.warning("PostgreSQL indisponível: %s", exc)
        return False
    return True


async def check_mcp_health(settings: Settings | None = None, timeout: float = 30.0) -> bool:
    """True se o servidor MCP sobe, faz o handshake e lista ao menos uma tool."""
    settings = settings or get_settings()
    try:
        # Timeout em volta de tudo: um servidor que trava no list_tools não prende o health.
        async with asyncio.timeout(timeout):
            # Uma tentativa só: o health mostra o estado atual, não espera o servidor se recuperar.
            async with DengueMCPClient.from_settings(settings, max_retries=1) as client:
                return bool(await client.list_tools())
    # Qualquer falha (subprocesso, handshake, list_tools) é "fora do ar": o health não levanta.
    except Exception as exc:
        logger.warning("Servidor MCP indisponível: %s", exc)
        return False


async def health_check(settings: Settings | None = None) -> dict[str, bool]:
    """Estado de cada serviço, verificados em paralelo."""
    settings = settings or get_settings()
    checks = {
        "ollama": check_ollama_health(settings),
        "database": check_db_health(settings),
        "mcp": check_mcp_health(settings),
    }
    # Cada corrotina vira uma task do gather: o cliente MCP abre e fecha dentro da mesma task.
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    status = {}
    for name, result in zip(checks, results, strict=True):
        # Exceção não prevista numa checagem (ex.: URL malformada) conta como serviço fora.
        if isinstance(result, BaseException):
            logger.warning("Health check de %s falhou: %r", name, result)
        status[name] = result is True
    return status
