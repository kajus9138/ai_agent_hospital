"""Testes do agente ReAct com LLM e tools falsos (sem Ollama nem servidor MCP real).

O LLM falso devolve respostas roteirizadas e registra o que recebeu: dá para checar o prompt de
sistema, o histórico da thread e o laço pensamento → tool → resultado sem depender de um modelo.
Os testes `integration` usam o PostgreSQL (TEST_DATABASE_URL ou DATABASE_URL) e são pulados sem ele.
"""

import shlex
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import ollama
import pytest
from langchain.agents.middleware import model_retry
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from ai_agent_hospital.agent.checkpointer import CheckpointerError, open_checkpointer
from ai_agent_hospital.agent.prompts import HOSPITAL_SYSTEM_PROMPT
from ai_agent_hospital.agent.react_agent import HospitalReActAgent, create_hospital_agent
from ai_agent_hospital.errors import OllamaConnectionError, ToolExecutionError
from ai_agent_hospital.mcp_client import DengueMCPClient

FAKE_SERVER = Path(__file__).parent / "fake_dengue_server.py"


class ScriptedChatModel(BaseChatModel):
    """Devolve as respostas na ordem dada e guarda as mensagens de cada chamada."""

    responses: list[AIMessage]
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses[len(self.calls) - 1])])


@tool
def situacao_atual() -> dict:
    """Situação atual da dengue em São Paulo."""
    return {"semana": "202643", "casos": 1250}


def tool_call(name: str, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


def scripted(*responses: AIMessage | str) -> ScriptedChatModel:
    return ScriptedChatModel(
        responses=[r if isinstance(r, AIMessage) else AIMessage(content=r) for r in responses],
        calls=[],
    )


def test_agent_creation():
    agent = HospitalReActAgent(scripted("oi"), [situacao_atual], InMemorySaver())
    assert {"model", "tools"} <= set(agent.graph.nodes)


async def test_react_loop():
    llm = scripted(tool_call("situacao_atual"), "Na semana 202643 houve 1250 casos.")
    agent = HospitalReActAgent(llm, [situacao_atual], InMemorySaver())

    answer = await agent.invoke("Como está a dengue?", thread_id="t1")

    assert answer == "Na semana 202643 houve 1250 casos."
    # Na 2ª chamada o modelo já vê o resultado da tool.
    tool_messages = [m for m in llm.calls[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "1250" in tool_messages[0].text


async def test_system_prompt_injection():
    llm = scripted("ok")
    await HospitalReActAgent(llm, [situacao_atual]).invoke("oi", thread_id="t1")

    first = llm.calls[0][0]
    assert isinstance(first, SystemMessage)
    assert first.text == HOSPITAL_SYSTEM_PROMPT


async def test_thread_persistence():
    llm = scripted("primeira", "segunda", "outra thread")
    agent = HospitalReActAgent(llm, [situacao_atual], InMemorySaver())

    await agent.invoke("pergunta 1", thread_id="a")
    await agent.invoke("pergunta 2", thread_id="a")
    await agent.invoke("pergunta 3", thread_id="b")

    texts = [[m.text for m in call] for call in llm.calls]
    assert texts[1][1:] == ["pergunta 1", "primeira", "pergunta 2"]
    assert texts[2][1:] == ["pergunta 3"]


async def test_streaming_output():
    llm = scripted(tool_call("situacao_atual"), "resposta")
    agent = HospitalReActAgent(llm, [situacao_atual], InMemorySaver())

    events = [event async for event in agent.stream("Como está a dengue?", thread_id="t1")]

    kinds = [event["event"] for event in events]
    assert "on_chat_model_end" in kinds
    tool_ends = [e for e in events if e["event"] == "on_tool_end"]
    assert [e["name"] for e in tool_ends] == ["situacao_atual"]


async def test_create_hospital_agent_discovers_mcp_tools():
    client = DengueMCPClient(sys.executable, shlex.quote(str(FAKE_SERVER)))
    async with client:
        llm = scripted(tool_call("tendencia"), "Tendência de alta.")
        agent = await create_hospital_agent(llm, client, InMemorySaver())
        assert await agent.invoke("A dengue está em alta?", thread_id="t1") == "Tendência de alta."

    tool_messages = [m for m in llm.calls[1] if isinstance(m, ToolMessage)]
    assert "alta" in tool_messages[0].text


# --- Checkpointer no PostgreSQL ---


async def test_checkpointer_unreachable_raises_clear_error():
    # Porta 1: nada escuta lá, a conexão é recusada na hora.
    with pytest.raises(CheckpointerError, match="DATABASE_URL"):
        async with open_checkpointer("postgresql://u:p@127.0.0.1:1/x", connect_timeout=1):
            pass


@pytest.mark.integration
async def test_postgres_checkpointer_survives_restart(database_url):
    thread_id = f"test-{uuid.uuid4()}"

    async with open_checkpointer(database_url) as checkpointer:
        await HospitalReActAgent(scripted("primeira"), [situacao_atual], checkpointer).invoke(
            "pergunta 1", thread_id
        )

    # "Reinício": nova conexão e novo agente, mesma thread.
    llm = scripted("segunda")
    async with open_checkpointer(database_url) as checkpointer:
        try:
            await HospitalReActAgent(llm, [situacao_atual], checkpointer).invoke(
                "pergunta 2", thread_id
            )
        finally:
            await checkpointer.adelete_thread(thread_id)

    assert [m.text for m in llm.calls[0][1:]] == ["pergunta 1", "primeira", "pergunta 2"]


# --- Middleware: retry do modelo e falhas de tool ---


class FlakyChatModel(ScriptedChatModel):
    """Levanta `error` nas primeiras `failures` chamadas, depois segue o roteiro."""

    failures: int = 1
    error: Any = None
    attempts: int = 0

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise self.error
        return super()._generate(messages, *args, **kwargs)


def flaky(failures: int, error: Exception, *responses: str) -> FlakyChatModel:
    return FlakyChatModel(
        responses=[AIMessage(content=r) for r in responses],
        calls=[],
        failures=failures,
        error=error,
    )


@pytest.fixture
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(model_retry, "calculate_delay", lambda *args, **kwargs: 0)


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("Failed to connect to Ollama"),
        httpx.ReadTimeout("timeout"),
        ollama.ResponseError("model is loading", status_code=503),
    ],
)
async def test_transient_model_error_is_retried(no_retry_delay, error):
    llm = flaky(1, error, "Resposta depois da falha.")
    agent = HospitalReActAgent(llm, [situacao_atual])

    assert await agent.invoke("oi", thread_id="t1") == "Resposta depois da falha."
    assert llm.attempts == 2


async def test_model_error_propagates_after_retries(no_retry_delay):
    llm = flaky(10, ConnectionError("Failed to connect to Ollama"), "nunca")
    agent = HospitalReActAgent(llm, [situacao_atual])

    with pytest.raises(OllamaConnectionError, match="não respondeu") as info:
        await agent.invoke("oi", thread_id="t1")
    assert llm.attempts == 3  # 1 + 2 retries
    assert isinstance(info.value.__cause__, ConnectionError)


@pytest.mark.parametrize("status", [404, 500])
async def test_non_transient_model_error_is_not_retried(no_retry_delay, status):
    llm = flaky(1, ollama.ResponseError("falha permanente", status_code=status), "nunca")
    agent = HospitalReActAgent(llm, [situacao_atual])

    with pytest.raises(ollama.ResponseError):
        await agent.invoke("oi", thread_id="t1")
    assert llm.attempts == 1


@tool
def tool_quebrada() -> str:
    """Sempre falha fora do protocolo."""
    raise RuntimeError("servidor MCP caiu")


async def test_tool_exception_becomes_tool_execution_error():
    agent = HospitalReActAgent(scripted(tool_call("tool_quebrada")), [tool_quebrada])

    with pytest.raises(ToolExecutionError, match="servidor MCP caiu") as info:
        await agent.invoke("oi", thread_id="t1")
    assert info.value.tool_name == "tool_quebrada"
    assert isinstance(info.value.__cause__, RuntimeError)


async def test_mcp_tool_error_still_goes_back_to_model():
    """`isError` do servidor não é falha do agente: o modelo vê o erro e responde."""
    invalid_call = AIMessage(
        content="", tool_calls=[{"name": "tendencia", "args": {"semanas": 99}, "id": "call_1"}]
    )
    llm = scripted(invalid_call, "Não consegui consultar.")
    async with DengueMCPClient(sys.executable, shlex.quote(str(FAKE_SERVER))) as client:
        agent = await create_hospital_agent(llm, client)
        answer = await agent.invoke("Como está a dengue?", thread_id="t1")

    assert answer == "Não consegui consultar."
    tool_message = next(m for m in llm.calls[1] if isinstance(m, ToolMessage))
    assert tool_message.status == "error"
