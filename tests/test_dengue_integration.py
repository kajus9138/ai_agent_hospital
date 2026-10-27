"""Integração com o servidor MCP real de dengue (repo smart_hospitals), via stdio.

Os testes `dengue_mcp` usam SMART_HOSPITALS_PATH (do ambiente ou do .env) e são pulados se ele não
estiver definido ou não existir. Os asserts checam só a forma das respostas: os valores dependem do
snapshot do InfoDengue no outro repo.
"""

import json
import shutil
from pathlib import Path

import pytest

from ai_agent_hospital import config
from ai_agent_hospital.mcp_client import DengueMCPClient, MCPConnectionError, load_langchain_tools

TOOL_NAMES = {"situacao_atual", "tendencia", "serie_historica", "comparativo_sazonal"}
TENDENCIAS = {"alta", "estavel", "queda"}


@pytest.fixture
def settings() -> config.Settings:
    settings = config.get_settings()
    path = settings.smart_hospitals_path
    if not path or not Path(path).expanduser().is_dir():
        pytest.skip("SMART_HOSPITALS_PATH não definido ou inexistente")
    return settings


def real_client(settings: config.Settings) -> DengueMCPClient:
    # Uma tentativa só: se o servidor real não sobe, o teste falha logo, com o erro do cliente.
    return DengueMCPClient.from_settings(settings, max_retries=1)


@pytest.mark.dengue_mcp
async def test_connection_and_list_tools(settings):
    async with real_client(settings) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES


@pytest.mark.dengue_mcp
async def test_situacao_atual(settings):
    async with real_client(settings) as client:
        result = await client.call_tool("situacao_atual")
    assert not result.isError
    assert isinstance(result.structuredContent, dict)
    assert result.structuredContent["data_referencia"]


@pytest.mark.dengue_mcp
async def test_tendencia(settings):
    async with real_client(settings) as client:
        result = await client.call_tool("tendencia", {"semanas": 4})
    assert not result.isError
    content = result.structuredContent
    assert len(content["semanas"]) == 4
    assert content["tendencia_resumo"] in TENDENCIAS


@pytest.mark.dengue_mcp
async def test_invalid_argument_is_reported(settings):
    async with real_client(settings) as client:
        result = await client.call_tool("tendencia", {"semanas": 99})
    assert result.isError
    assert "semanas" in result.content[0].text


@pytest.mark.dengue_mcp
async def test_langchain_tools_end_to_end(settings):
    async with real_client(settings) as client:
        tools = {tool.name: tool for tool in await load_langchain_tools(client)}
        assert set(tools) == TOOL_NAMES
        content = await tools["tendencia"].ainvoke({"semanas": 2})
    assert json.loads(content[0]["text"])["tendencia_resumo"] in TENDENCIAS


@pytest.mark.dengue_mcp
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv não instalado")
async def test_wrong_directory_fails_with_clear_error(settings, tmp_path):
    # Diretório existe, mas não é o smart_hospitals: o `uv run` não acha o comando dengue-mcp.
    # Usa `settings` só para ser pulado junto com os demais quando o smart_hospitals não existe.
    client = DengueMCPClient(
        "uv", config.DEFAULT_MCP_SERVER_ARGS, str(tmp_path), max_retries=1, connect_timeout=10
    )
    with pytest.raises(MCPConnectionError, match="uv run --directory"):
        await client.connect()
