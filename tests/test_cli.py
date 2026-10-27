"""Testes da CLI.

O laço do chat roda com `ThreadManager` real (PostgreSQL em schema temporário, testes
`integration`) e o `ScriptedChatModel` de test_react_agent; a saída vai para um `Console` em
memória. Os comandos do Typer são testados com `CliRunner` e uma sessão falsa, sem banco.
"""

import asyncio
import io
import os
import signal
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from rich.console import Console
from test_react_agent import ScriptedChatModel, scripted, situacao_atual, tool_call
from typer.testing import CliRunner

from ai_agent_hospital import cli
from ai_agent_hospital.agent.checkpointer import open_checkpointer
from ai_agent_hospital.agent.react_agent import HospitalReActAgent
from ai_agent_hospital.agent.thread_manager import ThreadManager, ThreadNotFoundError
from ai_agent_hospital.db.repository import (
    Message,
    ThreadPreview,
    ThreadRepository,
    ThreadSummary,
)
from ai_agent_hospital.errors import OllamaConnectionError


def make_console() -> Console:
    return Console(file=io.StringIO(), width=120, color_system=None)


def output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def inputs(*lines: str):
    """`read_input` que devolve as linhas dadas e depois simula o Ctrl+D."""
    pending = list(lines)

    async def read() -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    return read


class StreamingChatModel(ScriptedChatModel):
    """Responde texto em pedaços, como um modelo com streaming de tokens."""

    def _stream(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Iterator:
        self.calls.append(list(messages))
        for word in self.responses[len(self.calls) - 1].text.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))


class FailingChatModel(ScriptedChatModel):
    def _generate(self, *args: Any, **kwargs: Any):
        raise RuntimeError("modelo caiu")


class HangingChatModel(ScriptedChatModel):
    """Fica esperando até ser cancelado; avisa quando começou."""

    started: Any = None

    async def _agenerate(self, *args: Any, **kwargs: Any):
        self.started.set()
        await asyncio.sleep(3600)


@pytest.fixture
async def checkpointer(schema_url):
    async with open_checkpointer(schema_url) as saver:
        yield saver


def make_manager(llm, checkpointer, pool) -> ThreadManager:
    return ThreadManager(
        HospitalReActAgent(llm, [situacao_atual], checkpointer), ThreadRepository(pool)
    )


@pytest.mark.integration
async def test_chat_turn_with_tool_saves_history(checkpointer, pool):
    llm = scripted(tool_call("situacao_atual"), "Na semana 202643 houve **1250** casos.")
    manager = make_manager(llm, checkpointer, pool)
    thread_id = await manager.create_thread()
    console = make_console()

    await cli.run_chat(manager, thread_id, console, inputs("", "Como está a dengue?", "sair"))

    out = output(console)
    assert "consultando situacao_atual" in out
    assert "1250" in out
    roles = [m.role for m in await manager.get_history(thread_id)]
    # A linha vazia não virou mensagem; "sair" encerrou sem ir ao agente.
    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.integration
async def test_chat_streams_tokens(checkpointer, pool, monkeypatch):
    tokens: list[str] = []
    original = cli.TurnRenderer.token

    def spy(self, text: str) -> None:
        tokens.append(text)
        original(self, text)

    monkeypatch.setattr(cli.TurnRenderer, "token", spy)
    llm = StreamingChatModel(responses=[AIMessage("Casos em alta na capital.")], calls=[])
    manager = make_manager(llm, checkpointer, pool)
    thread_id = await manager.create_thread()
    console = make_console()

    await cli.run_chat(manager, thread_id, console, inputs("oi"))

    # Um token por palavra: veio do stream, não do texto completo no fim da chamada.
    assert [t for t in tokens if t] == ["Casos ", "em ", "alta ", "na ", "capital. "]
    assert "Casos em alta na capital." in output(console)
    assert [m.role for m in await manager.get_history(thread_id)] == ["user", "assistant"]


@pytest.mark.integration
async def test_chat_survives_agent_error(checkpointer, pool):
    manager = make_manager(FailingChatModel(responses=[], calls=[]), checkpointer, pool)
    thread_id = await manager.create_thread()
    console = make_console()

    await cli.run_chat(manager, thread_id, console, inputs("primeira", "segunda"))

    out = output(console)
    assert out.count("Erro do agente: modelo caiu") == 2
    # A pergunta que chegou ao checkpoint antes da falha foi para o histórico.
    assert [m.content for m in await manager.get_history(thread_id)] == ["primeira", "segunda"]


@pytest.mark.integration
async def test_chat_reports_recursion_error(checkpointer, pool, monkeypatch):
    async def looping_turn(*args: Any) -> None:
        raise GraphRecursionError("limite de passos")

    monkeypatch.setattr(cli, "run_turn", looping_turn)
    manager = make_manager(scripted(), checkpointer, pool)
    thread_id = await manager.create_thread()
    console = make_console()

    await cli.run_chat(manager, thread_id, console, inputs("pergunta"))

    assert "loop chamando ferramentas" in output(console)


@pytest.mark.integration
async def test_ctrl_c_cancels_only_the_turn(checkpointer, pool):
    llm = HangingChatModel(responses=[], calls=[], started=asyncio.Event())
    manager = make_manager(llm, checkpointer, pool)
    thread_id = await manager.create_thread()
    console = make_console()

    async def interrupt_when_started() -> None:
        await llm.started.wait()
        os.kill(os.getpid(), signal.SIGINT)

    interrupter = asyncio.create_task(interrupt_when_started())
    await asyncio.wait_for(
        cli.run_chat(manager, thread_id, console, inputs("pergunta demorada", "sair")), timeout=10
    )
    await interrupter

    assert "Resposta interrompida." in output(console)
    # O handler foi removido ao sair do chat.
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


@pytest.mark.integration
async def test_ctrl_c_during_tool_closes_pending_call(checkpointer, pool):
    started = asyncio.Event()

    @tool
    async def consulta_lenta() -> str:
        """Demora."""
        started.set()
        await asyncio.sleep(3600)
        return "nunca"

    llm = scripted(tool_call("consulta_lenta"), "Pode perguntar de novo.")
    manager = ThreadManager(
        HospitalReActAgent(llm, [consulta_lenta], checkpointer), ThreadRepository(pool)
    )
    thread_id = await manager.create_thread()

    async def interrupt_when_started() -> None:
        await started.wait()
        os.kill(os.getpid(), signal.SIGINT)

    interrupter = asyncio.create_task(interrupt_when_started())
    console = make_console()
    await asyncio.wait_for(
        cli.run_chat(manager, thread_id, console, inputs("pergunta", "de novo")), timeout=10
    )
    await interrupter

    history = await manager.get_history(thread_id)
    # Chamada fechada com erro; o turno seguinte foi ao modelo normalmente.
    assert [m.role for m in history] == ["user", "assistant", "tool", "user", "assistant"]
    assert "interrompida" in history[2].content
    assert "Pode perguntar de novo." in output(console)


@pytest.mark.integration
async def test_ctrl_c_outside_turn_cancels_chat(checkpointer, pool):
    manager = make_manager(scripted(), checkpointer, pool)
    thread_id = await manager.create_thread()

    async def read() -> str:
        # Ctrl+C chegando como sinal enquanto nenhum turno roda (ex.: gravando o histórico).
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(3600)
        return ""

    task = asyncio.create_task(cli.run_chat(manager, thread_id, make_console(), read))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


@pytest.mark.integration
async def test_ctrl_d_and_ctrl_c_at_prompt_exit(checkpointer, pool):
    manager = make_manager(scripted(), checkpointer, pool)
    thread_id = await manager.create_thread()

    async def ctrl_c() -> str:
        raise KeyboardInterrupt

    for read in (inputs(), ctrl_c):
        await asyncio.wait_for(cli.run_chat(manager, thread_id, make_console(), read), timeout=5)


NOW = datetime(2026, 10, 27, 14, 30, tzinfo=UTC)


def test_renderer_discards_partial_text_on_model_retry():
    renderer = cli.TurnRenderer(make_console())
    renderer.token("Na semana 2026")  # tentativa que falhou no meio do streaming
    renderer.model_start()  # retry
    renderer.token("Na semana 202643.")
    assert renderer.text == "Na semana 202643."
    renderer.close()


def test_render_threads_table():
    tid = uuid.uuid4()
    preview = ThreadPreview(tid, NOW, {}, 4, "linha 1\nlinha 2 " + "x" * 100, NOW)
    console = make_console()

    cli.render_threads([preview], console)

    out = output(console)
    assert str(tid) in out and "27/10/26 14:30" in out
    assert "linha 1 linha 2" in out and "…" in out


def test_render_threads_empty():
    console = make_console()
    cli.render_threads([], console)
    assert "Nenhuma thread" in output(console)


def test_render_history_roles():
    tid = uuid.uuid4()
    call = {"name": "situacao_atual", "args": {"municipio": "SP"}, "id": "c1"}
    messages = [
        Message(uuid.uuid4(), tid, "user", "Como está?", None, NOW),
        Message(uuid.uuid4(), tid, "assistant", "", [call], NOW),
        Message(uuid.uuid4(), tid, "tool", '{"casos": 1250}', None, NOW),
        Message(uuid.uuid4(), tid, "assistant", "São **1250** casos.", None, NOW),
    ]
    console = make_console()

    cli.render_history(messages, console)

    out = output(console)
    assert "#1 Você: Como está?" in out
    assert "#2 → situacao_atual(municipio='SP')" in out
    assert '#3 resultado: {"casos": 1250}' in out
    assert "#4 Assistente" in out and "1250" in out


def test_render_escapes_markup():
    tid = uuid.uuid4()
    messages = [
        Message(uuid.uuid4(), tid, "user", "compare [/b] com [bold]x[/bold]", None, NOW),
        Message(uuid.uuid4(), tid, "assistant", "", None, NOW),
        Message(uuid.uuid4(), tid, "tool", "erro [/]", None, NOW),
    ]
    console = make_console()

    cli.render_history(messages, console)
    cli.render_threads([ThreadPreview(tid, NOW, {}, 3, "[/red] fim", NOW)], console)

    out = output(console)
    assert "compare [/b] com [bold]x[/bold]" in out
    assert "#2 Assistente: (sem texto)" in out
    assert "erro [/]" in out and "[/red] fim" in out


class FakeManager:
    def __init__(self) -> None:
        self.deleted: list[uuid.UUID] = []
        self.created: uuid.UUID | None = None
        self.message_count = 0

    async def create_thread(self) -> uuid.UUID:
        self.created = uuid.uuid4()
        return self.created

    async def list_threads(self) -> list[ThreadPreview]:
        return []

    async def get_summary(self, thread_id: uuid.UUID) -> ThreadSummary:
        if thread_id != self.created:
            raise ThreadNotFoundError(f"Thread {thread_id} não encontrada.")
        return ThreadSummary(thread_id, self.message_count, None, None)

    async def get_history(self, thread_id: uuid.UUID) -> list[Message]:
        return []

    async def fork_thread(self, thread_id: uuid.UUID, from_message: int) -> uuid.UUID:
        if from_message < 1:
            raise ValueError("from_message deve estar entre 1 e 2: 0.")
        return uuid.UUID(int=1)

    async def delete_thread(self, thread_id: uuid.UUID) -> bool:
        self.deleted.append(thread_id)
        return True


@pytest.fixture
def fake_session(monkeypatch) -> FakeManager:
    manager = FakeManager()

    @asynccontextmanager
    async def fake_open_session(*args: Any, **kwargs: Any) -> AsyncIterator[FakeManager]:
        yield manager

    monkeypatch.setattr(cli, "open_session", fake_open_session)
    return manager


runner = CliRunner()
TID = "6f1c7a52-6a3b-4c2e-9d55-0d2a9f1f2b11"


def test_help_lists_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("chat", "threads", "history", "fork", "delete"):
        assert command in result.output


def test_invalid_thread_id_is_usage_error(fake_session):
    result = runner.invoke(cli.app, ["history", "nao-e-uuid"])
    assert result.exit_code == 2
    assert "não é um ID de thread válido" in result.output


def test_threads_command(fake_session):
    result = runner.invoke(cli.app, ["threads"])
    assert result.exit_code == 0


def test_chat_with_unknown_thread_exits_1(fake_session):
    result = runner.invoke(cli.app, ["chat", "--thread", TID])
    assert result.exit_code == 1


@pytest.mark.parametrize(("messages", "kept"), [(0, False), (2, True)])
def test_chat_drops_new_thread_left_empty(fake_session, monkeypatch, messages, kept):
    async def fake_run_chat(*args: Any) -> None:
        fake_session.message_count = messages

    monkeypatch.setattr(cli, "run_chat", fake_run_chat)
    result = runner.invoke(cli.app, ["chat"])

    assert result.exit_code == 0
    assert (fake_session.deleted == []) is kept
    assert ("Thread salva" in result.output) is kept


def test_database_error_after_startup_exits_1(fake_session, monkeypatch):
    async def broken() -> list:
        raise psycopg.OperationalError("conexão perdida")

    monkeypatch.setattr(fake_session, "list_threads", broken)
    result = runner.invoke(cli.app, ["threads"])

    assert result.exit_code == 1
    assert "conexão perdida" in result.output


def test_fork_command(fake_session):
    ok = runner.invoke(cli.app, ["fork", TID, "--from", "2"])
    bad = runner.invoke(cli.app, ["fork", TID, "--from", "0"])

    assert ok.exit_code == 0 and str(uuid.UUID(int=1)) in ok.output
    assert bad.exit_code == 1


def test_delete_asks_confirmation(fake_session):
    declined = runner.invoke(cli.app, ["delete", TID], input="n\n")
    assert declined.exit_code == 1
    assert fake_session.deleted == []

    confirmed = runner.invoke(cli.app, ["delete", TID, "--yes"])
    assert confirmed.exit_code == 0
    assert fake_session.deleted == [uuid.UUID(TID)]


def test_startup_error_exits_1(monkeypatch):
    @asynccontextmanager
    async def broken_session(*args: Any, **kwargs: Any) -> AsyncIterator[None]:
        raise OllamaConnectionError("Ollama indisponível")
        yield

    monkeypatch.setattr(cli, "open_session", broken_session)
    result = runner.invoke(cli.app, ["threads"])
    assert result.exit_code == 1
