"""Checkpointer do LangGraph no PostgreSQL: guarda o estado de cada thread do agente."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row

from ai_agent_hospital.config import get_settings
from ai_agent_hospital.db.connection import create_pool


class CheckpointerError(Exception):
    """Falha ao conectar ou preparar as tabelas do checkpointer."""


@asynccontextmanager
async def open_checkpointer(
    conninfo: str | None = None, *, connect_timeout: float = 10.0, **pool_kwargs
) -> AsyncIterator[AsyncPostgresSaver]:
    """Abre o checkpointer sobre um pool próprio e cria suas tabelas, se faltarem.

    Sem `conninfo`, usa o DATABASE_URL. O pool não é o do repository: o saver exige conexões com
    autocommit e `dict_row`, e o repository lê as linhas como tuplas. `pool_kwargs` vão para o
    AsyncConnectionPool (ex.: `max_size`).
    """
    if conninfo is None:
        conninfo = get_settings().database_url
    pool = create_pool(
        conninfo,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        **pool_kwargs,
    )
    async with AsyncExitStack() as stack:
        # Registrado antes do open: um open que estoura o timeout já deixou workers rodando.
        stack.push_async_callback(pool.close)
        # Só a abertura é traduzida: erros de banco durante o uso propagam como estão.
        try:
            # wait=True: URL errada ou banco fora do ar falham aqui, não na primeira mensagem.
            await pool.open(wait=True, timeout=connect_timeout)
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
        except psycopg.Error as exc:
            raise CheckpointerError(
                f"Não foi possível abrir o checkpointer no PostgreSQL: {exc}. Confira o "
                "DATABASE_URL e se o banco está no ar (`docker compose up -d`)."
            ) from exc
        yield checkpointer
