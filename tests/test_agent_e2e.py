"""Agente completo: LLM do Ollama + servidor MCP real de dengue (smart_hospitals).

Precisa dos dois serviços (markers `ollama` e `dengue_mcp`); é pulado se faltar algum. LLMs locais
pequenos variam entre execuções, então os asserts checam o comportamento esperado (qual tool foi
chamada, se admitiu a falta de dados), não o texto exato.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from ai_agent_hospital import config
from ai_agent_hospital.agent.llm import check_ollama_health, get_llm
from ai_agent_hospital.agent.react_agent import HospitalReActAgent, create_hospital_agent
from ai_agent_hospital.mcp_client import DengueMCPClient, load_langchain_tools

pytestmark = [pytest.mark.ollama, pytest.mark.dengue_mcp]

TOOL_NAMES = {"situacao_atual", "tendencia", "serie_historica", "comparativo_sazonal"}
# Formas de dizer que o dado não existe (ou que só há o município inteiro).
INDISPONIVEL = re.compile(
    r"indisponív|não (está|estão|estar|são|é) disponív|não (temos|tenho|dispomos|disponho) "
    r"(acesso|dados|informaç)|não há (dados|informaç)|município (de são paulo )?como um todo",
    re.IGNORECASE,
)


@pytest.fixture
async def settings() -> config.Settings:
    settings = config.get_settings()
    path = settings.smart_hospitals_path
    if not path or not Path(path).expanduser().is_dir():
        pytest.skip("SMART_HOSPITALS_PATH não definido ou inexistente")
    if not await check_ollama_health(settings):
        pytest.skip(f"Ollama indisponível ou modelo {settings.ollama_model} não baixado")
    return settings


@asynccontextmanager
async def mcp_client(settings: config.Settings) -> AsyncIterator[DengueMCPClient]:
    # Aberto dentro do teste, não numa fixture com yield: o stdio exige connect/close na mesma
    # task, e o pytest-asyncio roda setup e teardown de fixtures em tasks diferentes.
    async with DengueMCPClient.from_settings(settings, max_retries=1) as client:
        yield client


async def ask(settings: config.Settings, question: str) -> tuple[str, list[str]]:
    """Resposta final e nomes das tools chamadas pelo agente."""
    thread_id = str(uuid.uuid4())
    async with mcp_client(settings) as client:
        agent: HospitalReActAgent = await create_hospital_agent(
            get_llm(settings, temperature=0), client, InMemorySaver()
        )
        answer = await agent.invoke(question, thread_id)
        state = await agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
    tools = [
        call["name"]
        for message in state.values["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]
    return answer, tools


async def test_tool_discovery(settings):
    async with mcp_client(settings) as client:
        tools = await load_langchain_tools(client)
    assert TOOL_NAMES <= {tool.name for tool in tools}


async def test_situacao_atual_cites_reference_week(settings):
    answer, tools = await ask(settings, "Como está a dengue em São Paulo esta semana?")
    assert "situacao_atual" in tools
    # Regra 1 do prompt: citar a semana epidemiológica ou a data de referência.
    assert re.search(r"semana|\bSE\b|\d{4}", answer, re.IGNORECASE)


@pytest.mark.parametrize(
    ("question", "expected_tool"),
    [
        ("A dengue está em alta ou queda nas últimas 4 semanas?", "tendencia"),
        ("Como esta semana se compara com a mesma semana de 2024?", "comparativo_sazonal"),
    ],
)
async def test_queries_call_expected_tool(settings, question, expected_tool):
    answer, tools = await ask(settings, question)
    assert expected_tool in tools
    assert answer.strip()


@pytest.mark.parametrize(
    "question",
    [
        "Quantos leitos de UTI estão disponíveis?",
        pytest.param(
            "Qual a situação da dengue na Zona Leste?",
            # Não estrito: avisa (XPASS) quando um modelo passar a seguir a regra 4 do prompt.
            marks=pytest.mark.xfail(
                reason="qwen2.5 (7B) responde com os dados do município sem avisar que não há "
                "recorte regional, mesmo com a regra 4 do prompt",
                strict=False,
            ),
        ),
    ],
)
async def test_out_of_scope_admits_missing_data(settings, question):
    answer, _ = await ask(settings, question)
    assert INDISPONIVEL.search(answer), answer
