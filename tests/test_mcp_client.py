"""Testes do cliente MCP (stdio) e da conversão das tools para o LangChain.

Os testes que conectam sobem `fake_dengue_server.py` com o Python atual: exercitam o transporte
stdio real sem depender do repo smart_hospitals (o teste com o servidor real é da task 5).
"""

import asyncio
import json
import shlex
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from ai_agent_hospital import config
from ai_agent_hospital.mcp_client import DengueMCPClient, MCPConnectionError, load_langchain_tools
from ai_agent_hospital.mcp_client import client as client_module

FAKE_SERVER = Path(__file__).parent / "fake_dengue_server.py"
TOOL_NAMES = {"situacao_atual", "tendencia", "serie_historica", "comparativo_sazonal"}


def fake_client(**kwargs) -> DengueMCPClient:
    return DengueMCPClient(sys.executable, shlex.quote(str(FAKE_SERVER)), **kwargs)


# --- Configuração (sem subprocesso) ---


def test_args_parsing():
    client = DengueMCPClient(sys.executable, "run --directory /path dengue-mcp")
    assert client.server_params.command == sys.executable
    assert client.server_params.args == ["run", "--directory", "/path", "dengue-mcp"]


def test_placeholder_path_with_spaces_stays_one_arg(tmp_path):
    folder = tmp_path / "Meus Projetos"
    folder.mkdir()
    client = DengueMCPClient(
        sys.executable, "run --directory ${SMART_HOSPITALS_PATH} dengue-mcp", str(folder)
    )
    assert client.server_params.args == ["run", "--directory", str(folder), "dengue-mcp"]


def test_relative_path_is_made_absolute(tmp_path, monkeypatch):
    (tmp_path / "smart_hospitals").mkdir()
    monkeypatch.chdir(tmp_path)
    client = DengueMCPClient(
        sys.executable, "run --directory ${SMART_HOSPITALS_PATH} x", "smart_hospitals"
    )
    expected = str(tmp_path.resolve() / "smart_hospitals")
    assert client.server_params.args[2] == expected
    assert client.server_params.cwd == expected


def test_args_parsing_respects_quotes(tmp_path):
    folder = tmp_path / "com espaço"
    folder.mkdir()
    client = DengueMCPClient(sys.executable, f"run --directory '{folder}' dengue-mcp")
    assert client.server_params.args == ["run", "--directory", str(folder), "dengue-mcp"]


def test_env_variable_expansion_sets_cwd_and_env(tmp_path):
    client = DengueMCPClient(
        sys.executable, "run --directory ${SMART_HOSPITALS_PATH} dengue-mcp", str(tmp_path)
    )
    params = client.server_params
    assert params.args == ["run", "--directory", str(tmp_path), "dengue-mcp"]
    assert Path(params.cwd) == tmp_path
    assert params.env["SMART_HOSPITALS_PATH"] == str(tmp_path)
    assert params.env["PATH"]  # o uv precisa de PATH/HOME


def test_secrets_not_passed_to_server(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:segredo@db/x")
    client = DengueMCPClient(sys.executable, "server.py")
    assert "DATABASE_URL" not in client.server_params.env


def test_placeholder_without_path_error():
    with pytest.raises(MCPConnectionError, match="SMART_HOSPITALS_PATH"):
        DengueMCPClient(sys.executable, "run --directory ${SMART_HOSPITALS_PATH} dengue-mcp")


def test_invalid_command_error(monkeypatch):
    monkeypatch.setattr(client_module.shutil, "which", lambda _cmd: None)
    with pytest.raises(MCPConnectionError, match="'uv' não encontrado"):
        DengueMCPClient("uv", "run dengue-mcp")


def test_invalid_directory_error(tmp_path):
    missing = tmp_path / "nao-existe"
    with pytest.raises(MCPConnectionError, match="Diretório não encontrado"):
        DengueMCPClient(sys.executable, "run dengue-mcp", str(missing))


def test_from_settings(tmp_path):
    settings = config.Settings(
        "llama3.2",
        "http://ollama:11434",
        "postgresql://u:p@db:5432/x",
        smart_hospitals_path=str(tmp_path),
        mcp_server_command=sys.executable,
        mcp_server_args="run --directory ${SMART_HOSPITALS_PATH} dengue-mcp",
    )
    client = DengueMCPClient.from_settings(settings, max_retries=1)
    assert client.server_params.args == ["run", "--directory", str(tmp_path), "dengue-mcp"]
    assert client.max_retries == 1


def test_settings_read_mcp_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("SMART_HOSPITALS_PATH", str(tmp_path))
    monkeypatch.setenv("MCP_SERVER_COMMAND", "python")
    monkeypatch.setenv("MCP_SERVER_ARGS", "server.py")
    settings = config.get_settings()
    assert settings.smart_hospitals_path == str(tmp_path)
    assert (settings.mcp_server_command, settings.mcp_server_args) == ("python", "server.py")


def test_settings_mcp_defaults(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for var in ("SMART_HOSPITALS_PATH", "MCP_SERVER_COMMAND", "MCP_SERVER_ARGS"):
        monkeypatch.delenv(var, raising=False)
    settings = config.get_settings()
    assert settings.smart_hospitals_path is None
    assert settings.mcp_server_command == "uv"
    assert settings.mcp_server_args == "run --directory ${SMART_HOSPITALS_PATH} dengue-mcp"


def test_session_before_connect_error():
    with pytest.raises(MCPConnectionError, match="não conectado"):
        _ = fake_client().session


# --- Conexão com o servidor falso (stdio real) ---


async def test_connection_and_tool_listing():
    async with fake_client() as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES
    tendencia = next(tool for tool in tools if tool.name == "tendencia")
    assert tendencia.inputSchema["properties"]["semanas"]["type"] == "integer"


async def test_tool_invocation():
    async with fake_client() as client:
        result = await client.call_tool("serie_historica", {"inicio": "202601", "fim": "202610"})
    assert not result.isError
    assert result.structuredContent["result"] == [
        {"semana": "202601", "casos": 900},
        {"semana": "202610", "casos": 1250},
    ]


async def test_tool_error_is_reported_not_raised():
    async with fake_client() as client:
        result = await client.call_tool("tendencia", {"semanas": 99})
    assert result.isError
    assert "entre 1 e 52" in result.content[0].text


async def test_close_is_idempotent_and_disconnects():
    client = fake_client()
    session = await client.connect()
    assert await client.connect() is session  # já conectado: reaproveita a sessão
    await client.close()
    await client.close()
    with pytest.raises(MCPConnectionError):
        _ = client.session


async def test_connect_retries_with_exponential_backoff(monkeypatch):
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    # Processo que sai na hora: o handshake nunca completa.
    client = DengueMCPClient(
        sys.executable, "-c pass", max_retries=3, retry_delay=0.5, connect_timeout=1
    )
    with pytest.raises(MCPConnectionError, match="após 3 tentativa"):
        await client.connect()
    assert delays == [0.5, 1.0]
    with pytest.raises(MCPConnectionError):
        _ = client.session


async def test_connect_times_out_on_silent_server():
    # Processo que fica vivo mas nunca responde ao initialize.
    client = DengueMCPClient(
        sys.executable, "-c 'import time; time.sleep(30)'", max_retries=1, connect_timeout=0.3
    )
    with pytest.raises(MCPConnectionError, match="TimeoutError"):
        await client.connect()


async def test_concurrent_connect_spawns_one_server(monkeypatch):
    calls = []
    session = object()

    async def fake_connect_with_retries():
        calls.append(1)
        await asyncio.sleep(0.05)  # cede o controle: a outra chamada chega com a 1ª em andamento
        return AsyncExitStack(), session

    client = fake_client()
    monkeypatch.setattr(client, "_connect_with_retries", fake_connect_with_retries)
    first, second = await asyncio.gather(client.connect(), client.connect())
    assert first is second is session
    assert len(calls) == 1


# --- Conversão para tools do LangChain ---


async def test_mcp_to_langchain_conversion():
    async with fake_client() as client:
        tools = {tool.name: tool for tool in await load_langchain_tools(client)}
        assert set(tools) == TOOL_NAMES

        serie = tools["serie_historica"].args_schema
        assert set(serie["required"]) == {"inicio", "fim"}
        assert "semanas" not in tools["tendencia"].args_schema.get("required", [])
        assert tools["situacao_atual"].description.startswith("Situação atual")

        content = await tools["tendencia"].ainvoke({"semanas": 8})
    assert json.loads(content[0]["text"]) == {
        "semanas": 8,
        "variacao_pct": 12.5,
        "tendencia": "alta",
    }


async def test_load_langchain_tools_requires_connection():
    with pytest.raises(MCPConnectionError):
        await load_langchain_tools(fake_client())
