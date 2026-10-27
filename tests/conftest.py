"""Fixtures de PostgreSQL compartilhadas pelos testes `integration`.

Usam TEST_DATABASE_URL (ou DATABASE_URL) e pulam o teste se o Postgres não estiver acessível.
"""

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ai_agent_hospital import config
from ai_agent_hospital.db.connection import create_pool, init_schema


@pytest.fixture
async def database_url():
    url = os.getenv("TEST_DATABASE_URL") or config.get_settings().database_url
    try:
        conn = await psycopg.AsyncConnection.connect(url, connect_timeout=2)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponível: {exc}")
    await conn.close()
    return url


@pytest.fixture
async def schema_url(database_url):
    """Conninfo com `search_path` num schema temporário, apagado no fim.

    O banco de dev fica intacto. Serve para o pool do repository e para o do checkpointer.
    """
    schema = f"test_{uuid.uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield make_conninfo(database_url, options=f"-c search_path={schema}")
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
async def pool(schema_url):
    async with create_pool(schema_url, min_size=1, max_size=2) as p:
        await init_schema(p)
        yield p
