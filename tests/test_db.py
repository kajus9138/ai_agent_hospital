"""Testes da camada de persistência (schema, pool e repository).

Os testes de integração usam TEST_DATABASE_URL (ou DATABASE_URL) e são pulados se o Postgres não
estiver acessível. Cada teste roda num schema temporário, apagado no fim: o banco de dev fica
intocado.
"""

import os
import uuid

import psycopg
import pytest
from psycopg import errors, sql

from ai_agent_hospital import config
from ai_agent_hospital.db import connection
from ai_agent_hospital.db.connection import create_pool, init_schema, load_schema, transaction
from ai_agent_hospital.db.repository import ThreadRepository


def test_load_schema_has_tables():
    ddl = load_schema()
    assert "CREATE TABLE IF NOT EXISTS threads" in ddl
    assert "CREATE TABLE IF NOT EXISTS messages" in ddl


def test_create_pool_uses_database_url(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/x")
    pool = create_pool()
    assert pool.conninfo == "postgresql://u:p@db:5432/x"
    assert pool.closed  # criado fechado: abrir é responsabilidade de quem chama


@pytest.fixture
async def pool():
    url = os.getenv("TEST_DATABASE_URL") or config.get_settings().database_url
    schema = f"test_{uuid.uuid4().hex}"
    try:
        admin = await psycopg.AsyncConnection.connect(url, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponível: {exc}")

    async with admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            async with connection.create_pool(
                url, min_size=1, max_size=2, kwargs={"options": f"-c search_path={schema}"}
            ) as p:
                await init_schema(p)
                yield p
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def repo(pool):
    return ThreadRepository(pool)


@pytest.mark.integration
async def test_init_schema_is_idempotent(pool):
    await init_schema(pool)


@pytest.mark.integration
async def test_create_and_list_threads(repo):
    first = await repo.create_thread()
    second = await repo.create_thread({"title": "Leitos UTI"})

    threads = await repo.list_threads()

    assert [t.id for t in threads] == [second, first]
    assert threads[0].metadata == {"title": "Leitos UTI"}
    assert threads[1].metadata == {}


@pytest.mark.integration
async def test_messages_round_trip_in_order(repo):
    thread_id = await repo.create_thread()
    tool_calls = [{"name": "casos_dengue", "args": {"municipio": "São Paulo"}, "id": "call_1"}]

    await repo.add_message(thread_id, "user", "Quantos casos de dengue esta semana?")
    saved = await repo.add_message(thread_id, "assistant", "", tool_calls=tool_calls)
    await repo.add_message(thread_id, "tool", '{"casos": 1234}')

    messages = await repo.get_thread_messages(thread_id)

    assert [m.role for m in messages] == ["user", "assistant", "tool"]
    assert messages[1] == saved
    assert messages[1].tool_calls == tool_calls
    assert messages[0].tool_calls is None
    assert all(m.thread_id == thread_id for m in messages)


@pytest.mark.integration
async def test_messages_in_same_transaction_keep_order(pool):
    thread_id = await ThreadRepository(pool).create_thread()
    async with transaction(pool) as conn:
        for i in range(5):
            await conn.execute(
                "INSERT INTO messages (thread_id, role, content) VALUES (%s, 'user', %s)",
                (thread_id, str(i)),
            )

    messages = await ThreadRepository(pool).get_thread_messages(thread_id)

    assert [m.content for m in messages] == ["0", "1", "2", "3", "4"]


@pytest.mark.integration
async def test_invalid_role_is_rejected(repo):
    thread_id = await repo.create_thread()
    with pytest.raises(errors.CheckViolation):
        await repo.add_message(thread_id, "admin", "não permitido")


@pytest.mark.integration
async def test_message_requires_existing_thread(repo):
    with pytest.raises(errors.ForeignKeyViolation):
        await repo.add_message(uuid.uuid4(), "user", "órfã")


@pytest.mark.integration
async def test_delete_thread_cascades_to_messages(pool, repo):
    thread_id = await repo.create_thread()
    await repo.add_message(thread_id, "user", "oi")

    async with transaction(pool) as conn:
        await conn.execute("DELETE FROM threads WHERE id = %s", (thread_id,))

    assert await repo.get_thread_messages(thread_id) == []


@pytest.mark.integration
async def test_transaction_rolls_back_on_error(pool, repo):
    with pytest.raises(RuntimeError):
        async with transaction(pool) as conn:
            await conn.execute("INSERT INTO threads DEFAULT VALUES")
            raise RuntimeError("falha no meio da transação")

    assert await repo.list_threads() == []
