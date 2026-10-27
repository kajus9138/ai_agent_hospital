"""Testes do ThreadManager: catálogo/histórico no repository e estado do grafo no checkpointer.

O LLM é o `ScriptedChatModel` de test_react_agent. Os testes `integration` usam repository e
checkpointer no mesmo schema temporário do PostgreSQL (fixtures de conftest.py).
"""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from test_react_agent import scripted, situacao_atual, tool_call

from ai_agent_hospital.agent.checkpointer import open_checkpointer
from ai_agent_hospital.agent.react_agent import HospitalReActAgent
from ai_agent_hospital.agent.thread_manager import (
    ThreadManager,
    ThreadNotFoundError,
    to_new_message,
)
from ai_agent_hospital.db.repository import ThreadRepository


def test_to_new_message_roles():
    calls = [{"name": "situacao_atual", "args": {}, "id": "call_1", "type": "tool_call"}]

    assert to_new_message(HumanMessage("oi")) == ("user", "oi", None)
    assert to_new_message(AIMessage("resposta")) == ("assistant", "resposta", None)
    assert to_new_message(AIMessage("", tool_calls=calls)) == ("assistant", "", calls)
    assert to_new_message(ToolMessage("{}", tool_call_id="call_1")) == ("tool", "{}", None)
    assert to_new_message(SystemMessage("regras")) == ("system", "regras", None)


def test_manager_requires_checkpointer():
    agent = HospitalReActAgent(scripted("oi"), [situacao_atual])
    with pytest.raises(ValueError, match="checkpointer"):
        ThreadManager(agent, ThreadRepository(pool=None))


@pytest.fixture
async def checkpointer(schema_url):
    async with open_checkpointer(schema_url) as saver:
        yield saver


def make_manager(llm, checkpointer, pool) -> ThreadManager:
    return ThreadManager(
        HospitalReActAgent(llm, [situacao_atual], checkpointer), ThreadRepository(pool)
    )


@pytest.mark.integration
async def test_create_thread_returns_catalog_id(checkpointer, pool):
    manager = make_manager(scripted(), checkpointer, pool)

    first = await manager.create_thread({"title": "Dengue"})
    second = await manager.create_thread()

    assert isinstance(first, uuid.UUID) and first != second
    previews = await manager.list_threads()
    assert {p.id for p in previews} == {first, second}
    assert await manager.get_history(first) == []


@pytest.mark.integration
async def test_history_has_all_messages_in_order(checkpointer, pool):
    llm = scripted(tool_call("situacao_atual"), "Na semana 202643 houve 1250 casos.")
    manager = make_manager(llm, checkpointer, pool)
    thread_id = await manager.create_thread()

    answer = await manager.send_message(thread_id, "Como está a dengue?")

    history = await manager.get_history(thread_id)
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[0].content == "Como está a dengue?"
    assert history[1].tool_calls[0]["name"] == "situacao_atual"
    assert "1250" in history[2].content
    assert history[-1].content == answer
    summary = await manager.get_summary(thread_id)
    assert summary.message_count == 4
    assert summary.first_message_at <= summary.last_message_at
    assert (await manager.list_threads())[0].last_message == answer


@pytest.mark.integration
async def test_sync_messages_is_idempotent(checkpointer, pool):
    manager = make_manager(scripted("oi"), checkpointer, pool)
    thread_id = await manager.create_thread()
    await manager.send_message(thread_id, "olá")

    assert await manager.sync_messages(thread_id) == 0
    assert len(await manager.get_history(thread_id)) == 2


@pytest.mark.integration
async def test_conversation_survives_restart(schema_url, pool):
    async with open_checkpointer(schema_url) as checkpointer:
        manager = make_manager(scripted("primeira"), checkpointer, pool)
        thread_id = await manager.create_thread()
        await manager.send_message(thread_id, "pergunta 1")

    # "Reinício": novo checkpointer, novo agente, mesma thread.
    llm = scripted("segunda")
    async with open_checkpointer(schema_url) as checkpointer:
        manager = make_manager(llm, checkpointer, pool)
        await manager.send_message(thread_id, "pergunta 2")
        history = await manager.get_history(thread_id)

    assert [m.text for m in llm.calls[0][1:]] == ["pergunta 1", "primeira", "pergunta 2"]
    assert [m.content for m in history] == ["pergunta 1", "primeira", "pergunta 2", "segunda"]


@pytest.mark.integration
async def test_delete_thread_cleans_everything(checkpointer, pool):
    manager = make_manager(scripted("oi"), checkpointer, pool)
    thread_id = await manager.create_thread()
    await manager.send_message(thread_id, "olá")

    assert await manager.delete_thread(thread_id) is True

    config = {"configurable": {"thread_id": str(thread_id)}}
    assert [c async for c in checkpointer.alist(config)] == []
    assert await manager.repository.count_messages(thread_id) == 0
    assert await manager.list_threads() == []
    with pytest.raises(ThreadNotFoundError):
        await manager.get_history(thread_id)
    assert await manager.delete_thread(thread_id) is False


@pytest.mark.integration
async def test_unknown_thread_raises(checkpointer, pool):
    manager = make_manager(scripted("oi"), checkpointer, pool)
    missing = uuid.uuid4()

    with pytest.raises(ThreadNotFoundError):
        await manager.send_message(missing, "olá")
    with pytest.raises(ThreadNotFoundError):
        await manager.get_summary(missing)
    with pytest.raises(ThreadNotFoundError):
        await manager.fork_thread(missing, 2)


@pytest.mark.integration
async def test_fork_thread_branches_conversation(checkpointer, pool):
    llm = scripted("r1", "r2", "r-original", "r-fork")
    manager = make_manager(llm, checkpointer, pool)
    original = await manager.create_thread()
    await manager.send_message(original, "p1")
    await manager.send_message(original, "p2")

    fork = await manager.fork_thread(original, 2, {"title": "alternativa"})
    await manager.send_message(original, "p3")
    await manager.send_message(fork, "p2-alt")

    # O modelo, na thread do fork, só vê o que veio antes do corte.
    assert [m.text for m in llm.calls[3][1:]] == ["p1", "r1", "p2-alt"]
    fork_history = [m.content for m in await manager.get_history(fork)]
    assert fork_history == ["p1", "r1", "p2-alt", "r-fork"]
    original_history = [m.content for m in await manager.get_history(original)]
    assert original_history == ["p1", "r1", "p2", "r2", "p3", "r-original"]
    meta = (await manager.repository.get_thread(fork)).metadata
    assert meta == {"title": "alternativa", "forked_from": str(original), "from_message": 2}


@pytest.mark.integration
@pytest.mark.parametrize("cut", [0, 1, 2, 3, 5])
async def test_fork_rejects_cut_outside_finished_turn(checkpointer, pool, cut):
    # Mensagens: 1 user, 2 assistant com tool_call, 3 tool, 4 assistant final.
    manager = make_manager(scripted(tool_call("situacao_atual"), "fim"), checkpointer, pool)
    thread_id = await manager.create_thread()
    await manager.send_message(thread_id, "Como está a dengue?")

    with pytest.raises(ValueError, match="from_message|resposta final"):
        await manager.fork_thread(thread_id, cut)

    assert len(await manager.list_threads()) == 1


@pytest.mark.integration
async def test_sync_messages_unknown_thread_raises(checkpointer, pool):
    manager = make_manager(scripted(), checkpointer, pool)
    with pytest.raises(ThreadNotFoundError):
        await manager.sync_messages(uuid.uuid4())


@tool
def tool_quebrada() -> str:
    """Sempre falha."""
    raise RuntimeError("servidor MCP caiu")


@pytest.mark.integration
async def test_send_message_failure_keeps_agent_error_and_partial_history(checkpointer, pool):
    agent = HospitalReActAgent(scripted(tool_call("tool_quebrada")), [tool_quebrada], checkpointer)
    manager = ThreadManager(agent, ThreadRepository(pool))
    thread_id = await manager.create_thread()

    with pytest.raises(RuntimeError, match="servidor MCP caiu"):
        await manager.send_message(thread_id, "Como está a dengue?")

    # O que o grafo gravou antes da falha (pergunta + chamada da tool) está no histórico.
    history = await manager.get_history(thread_id)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].tool_calls[0]["name"] == "tool_quebrada"
