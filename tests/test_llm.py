"""Testes da integração com o Ollama (get_llm e health check).

Os testes unitários simulam o servidor com httpx.MockTransport: rodam sem Ollama. O teste de
integração usa o Ollama de OLLAMA_BASE_URL e é pulado se ele não responder ou se o modelo
OLLAMA_MODEL não estiver baixado.
"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from ai_agent_hospital import config
from ai_agent_hospital.agent import llm
from ai_agent_hospital.agent.llm import DEFAULT_TEMPERATURE, check_ollama_health, get_llm

SETTINGS = config.Settings("llama3.2", "http://ollama:11434", "postgresql://u:p@db:5432/x")


def test_get_llm_uses_settings():
    model = get_llm(SETTINGS)
    assert model.model == "llama3.2"
    assert model.base_url == "http://ollama:11434"
    assert model.temperature == DEFAULT_TEMPERATURE


def test_get_llm_kwargs_override():
    model = get_llm(SETTINGS, model="qwen2.5", temperature=0)
    assert model.model == "qwen2.5"
    assert model.temperature == 0


def test_get_llm_defaults_to_env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://outro:11434")
    model = get_llm()
    assert (model.model, model.base_url) == ("mistral", "http://outro:11434")


def _chat_handler(request: httpx.Request) -> httpx.Response:
    """Responde /api/chat em NDJSON (streaming), como o Ollama."""
    assert request.url.path == "/api/chat"
    chunks = [
        {"model": "llama3.2", "message": {"role": "assistant", "content": "Olá"}, "done": False},
        {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": ", mundo"},
            "done": True,
            "done_reason": "stop",
        },
    ]
    body = "\n".join(json.dumps(c) for c in chunks) + "\n"
    return httpx.Response(200, text=body, headers={"content-type": "application/x-ndjson"})


async def test_llm_response_format_offline():
    model = get_llm(SETTINGS, async_client_kwargs={"transport": httpx.MockTransport(_chat_handler)})
    response = await model.ainvoke("diga olá")
    assert isinstance(response, AIMessage)
    assert response.content == "Olá, mundo"


def _tags_transport(*names: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"model": n, "name": n} for n in names]})

    return httpx.MockTransport(handler)


def _error_transport(exc: Exception | None = None, status: int = 500) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        return httpx.Response(status, json={"error": "falhou"})

    return httpx.MockTransport(handler)


@pytest.fixture
def ollama_transport(monkeypatch):
    """Injeta um transport do httpx no AsyncClient criado pelo health check."""
    real_client = llm.ollama.AsyncClient

    def use(transport: httpx.MockTransport) -> None:
        monkeypatch.setattr(
            llm.ollama,
            "AsyncClient",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )

    return use


@pytest.mark.parametrize(
    ("configured", "available", "expected"),
    [
        ("llama3.2", ["llama3.2:latest"], True),  # tag implícita
        ("llama3.2:1b", ["qwen2.5:latest", "llama3.2:1b"], True),
        ("llama3.2", ["llama3.2:1b"], False),  # outra tag não serve
        ("llama3.2", [], False),
        ("registro:5000/llama3", ["registro:5000/llama3:latest"], True),  # ":" da porta
    ],
)
async def test_health_checks_model(ollama_transport, configured, available, expected):
    ollama_transport(_tags_transport(*available))
    settings = config.Settings(configured, "http://ollama:11434", "")
    assert await check_ollama_health(settings) is expected


@pytest.mark.parametrize(
    "transport",
    [
        _error_transport(httpx.ConnectError("connection refused")),
        _error_transport(httpx.ReadTimeout("timeout")),
        _error_transport(httpx.RemoteProtocolError("conexão caiu")),
        _error_transport(status=500),
        httpx.MockTransport(lambda request: httpx.Response(200, text="<html>outro serviço</html>")),
    ],
    ids=["server-down", "timeout", "protocol-error", "http-error", "not-ollama"],
)
async def test_health_false_when_ollama_fails(ollama_transport, transport):
    ollama_transport(transport)
    assert await check_ollama_health(SETTINGS) is False


@pytest.mark.ollama
async def test_llm_real_ollama():
    settings = config.get_settings()
    if not await check_ollama_health(settings):
        pytest.skip(f"Ollama ou modelo {settings.ollama_model} indisponível")
    response = await get_llm(settings, num_predict=20).ainvoke("Responda só: ok")
    assert isinstance(response, AIMessage)
    assert isinstance(response.content, str) and response.content.strip()
