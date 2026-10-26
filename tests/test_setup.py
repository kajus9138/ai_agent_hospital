"""Verifica o setup do projeto: versão do Python, dependências e estrutura do pacote."""

import importlib
import sys

import pytest

from ai_agent_hospital import config


def test_python_312():
    assert sys.version_info[:2] == (3, 12)


@pytest.mark.parametrize(
    "module",
    [
        "langgraph.graph",
        "langchain_ollama",
        "langgraph.checkpoint.postgres",
        "langchain_mcp_adapters.client",
        "mcp",
        "psycopg",
        "dotenv",
    ],
)
def test_core_dependencies_import(module):
    importlib.import_module(module)


def test_stategraph_import():
    from langgraph.graph import StateGraph

    assert StateGraph is not None


@pytest.mark.parametrize(
    "package",
    [
        "ai_agent_hospital.agent",
        "ai_agent_hospital.db",
        "ai_agent_hospital.mcp_client",
        "ai_agent_hospital.main",
    ],
)
def test_package_structure(package):
    importlib.import_module(package)


@pytest.fixture
def no_dotenv(monkeypatch):
    """Isola os testes do .env local e das variáveis do ambiente."""
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for var in ("OLLAMA_MODEL", "OLLAMA_BASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_settings_defaults(no_dotenv):
    settings = config.get_settings()
    assert settings.ollama_model == config.DEFAULT_OLLAMA_MODEL
    assert settings.ollama_base_url == config.DEFAULT_OLLAMA_BASE_URL
    assert settings.database_url == config.DEFAULT_DATABASE_URL


def test_settings_env_override(no_dotenv, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/x")
    settings = config.get_settings()
    assert settings == config.Settings(
        "qwen2.5", "http://ollama:11434", "postgresql://u:p@db:5432/x"
    )
