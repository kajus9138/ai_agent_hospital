"""Testes da camada de persistência (schema, pool e repository).

Os testes de integração usam as fixtures de `conftest.py`: cada um roda num schema temporário e é
pulado se o Postgres não estiver acessível.
"""

import asyncio
import uuid

import pytest
from psycopg import errors

from ai_agent_hospital import config
from ai_agent_hospital.db.connection import create_pool, init_schema, load_schema, transaction
from ai_agent_hospital.db.repository import HistoryDivergedError, ThreadRepository, ThreadSummary


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


@pytest.mark.integration
async def test_add_messages_keeps_order_and_counts(repo):
    thread_id = await repo.create_thread()
    tool_calls = [{"name": "situacao_atual", "args": {}, "id": "call_1"}]

    await repo.add_messages(
        thread_id, [("user", "oi", None), ("assistant", "", tool_calls), ("tool", "{}", None)]
    )

    messages = await repo.get_thread_messages(thread_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool"]
    assert messages[1].tool_calls == tool_calls
    assert await repo.count_messages(thread_id) == 3


@pytest.mark.integration
async def test_add_messages_is_atomic(repo):
    thread_id = await repo.create_thread()
    with pytest.raises(errors.CheckViolation):
        await repo.add_messages(thread_id, [("user", "ok", None), ("admin", "inválida", None)])

    assert await repo.count_messages(thread_id) == 0


@pytest.mark.integration
async def test_list_threads_with_preview(repo):
    empty = await repo.create_thread({"title": "vazia"})
    older = await repo.create_thread()
    await repo.add_messages(older, [("user", "primeira", None), ("assistant", "última", None)])

    previews = await repo.list_threads_with_preview()

    # A thread com mensagem teve atividade depois da criação da vazia.
    assert [p.id for p in previews] == [older, empty]
    assert previews[0].message_count == 2
    assert previews[0].last_message == "última"
    assert previews[0].last_message_at is not None
    assert previews[1].message_count == 0
    assert previews[1].last_message is None
    assert previews[1].metadata == {"title": "vazia"}


@pytest.mark.integration
async def test_get_thread_summary(repo):
    thread_id = await repo.create_thread()
    assert await repo.get_thread_summary(thread_id) == ThreadSummary(thread_id, 0, None, None)

    await repo.add_messages(thread_id, [("user", "a", None), ("assistant", "b", None)])
    messages = await repo.get_thread_messages(thread_id)

    summary = await repo.get_thread_summary(thread_id)
    assert summary.message_count == 2
    assert summary.first_message_at == messages[0].created_at
    assert summary.last_message_at == messages[1].created_at
    assert await repo.get_thread_summary(uuid.uuid4()) is None


@pytest.mark.integration
async def test_get_and_delete_thread(repo):
    thread_id = await repo.create_thread({"title": "x"})
    await repo.add_message(thread_id, "user", "oi")

    assert (await repo.get_thread(thread_id)).metadata == {"title": "x"}
    assert await repo.delete_thread(thread_id) is True
    assert await repo.get_thread(thread_id) is None
    assert await repo.count_messages(thread_id) == 0
    assert await repo.delete_thread(thread_id) is False


@pytest.mark.integration
async def test_append_missing_messages_writes_only_the_tail(repo):
    thread_id = await repo.create_thread()
    history = [("user", "a", None), ("assistant", "b", None)]

    assert await repo.append_missing_messages(thread_id, history[:1]) == 1
    assert await repo.append_missing_messages(thread_id, history) == 1
    assert await repo.append_missing_messages(thread_id, history) == 0
    assert [m.content for m in await repo.get_thread_messages(thread_id)] == ["a", "b"]
    assert await repo.append_missing_messages(uuid.uuid4(), history) is None


@pytest.mark.integration
async def test_append_missing_messages_detects_divergence(repo):
    thread_id = await repo.create_thread()
    await repo.add_messages(thread_id, [("user", "a", None), ("assistant", "b", None)])

    with pytest.raises(HistoryDivergedError):
        await repo.append_missing_messages(thread_id, [("user", "a", None)])


@pytest.mark.integration
async def test_concurrent_appends_do_not_duplicate(pool, repo):
    thread_id = await repo.create_thread()
    history = [("user", "a", None), ("assistant", "b", None)]

    written = await asyncio.gather(
        repo.append_missing_messages(thread_id, history),
        repo.append_missing_messages(thread_id, history),
    )

    assert sorted(written) == [0, 2]
    assert await repo.count_messages(thread_id) == 2
