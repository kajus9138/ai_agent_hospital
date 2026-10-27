"""Pool de conexões async (psycopg 3) e inicialização do schema."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from ai_agent_hospital.config import get_settings


def create_pool(conninfo: str | None = None, **kwargs) -> AsyncConnectionPool:
    """Cria o pool fechado; quem chama faz `await pool.open()` ou usa `async with pool`.

    Sem `conninfo`, usa o DATABASE_URL das configurações. `kwargs` vão para o AsyncConnectionPool.
    """
    if conninfo is None:
        conninfo = get_settings().database_url
    # open=True no construtor de um pool async gera warning e vai virar erro no psycopg_pool.
    return AsyncConnectionPool(conninfo, open=False, **kwargs)


def load_schema() -> str:
    """Lê o DDL de schema.sql, empacotado junto com o módulo."""
    return files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")


async def init_schema(pool: AsyncConnectionPool) -> None:
    """Cria tabelas e índices que ainda não existem."""
    async with pool.connection() as conn:
        await conn.execute(load_schema())


@asynccontextmanager
async def transaction(pool: AsyncConnectionPool) -> AsyncIterator[AsyncConnection]:
    """Conexão do pool dentro de uma transação: commit ao sair, rollback se houver exceção."""
    async with pool.connection() as conn, conn.transaction():
        yield conn
