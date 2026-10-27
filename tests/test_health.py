"""Health check dos serviços e o comando `health` da CLI."""

import asyncio
from typing import Any

import pytest
from test_bootstrap import UNREACHABLE_DB, make_settings
from typer.testing import CliRunner

from ai_agent_hospital import cli, health


@pytest.mark.integration
async def test_db_health_ok(database_url):
    assert await health.check_db_health(make_settings(database_url))


async def test_db_health_down():
    assert not await health.check_db_health(make_settings(UNREACHABLE_DB), timeout=1)


async def test_mcp_health_ok():
    assert await health.check_mcp_health(make_settings(UNREACHABLE_DB))


async def test_mcp_health_down():
    settings = make_settings(UNREACHABLE_DB, mcp_server_command="comando-que-nao-existe")
    assert not await health.check_mcp_health(settings)


async def test_mcp_health_times_out_when_server_hangs(monkeypatch):
    async def hang(self) -> list:
        await asyncio.sleep(3600)
        return []

    monkeypatch.setattr(health.DengueMCPClient, "list_tools", hang)
    assert not await health.check_mcp_health(make_settings(UNREACHABLE_DB), timeout=2)


async def test_unexpected_check_error_marks_service_down(monkeypatch):
    async def broken(settings: Any) -> bool:
        raise RuntimeError("URL malformada")

    monkeypatch.setattr(health, "check_ollama_health", broken)
    status = await health.health_check(make_settings(UNREACHABLE_DB))

    assert status["ollama"] is False
    assert status["mcp"] is True


async def test_health_check_reports_each_service(monkeypatch):
    async def ollama_down(settings: Any) -> bool:
        return False

    monkeypatch.setattr(health, "check_ollama_health", ollama_down)
    status = await health.health_check(make_settings(UNREACHABLE_DB))

    assert status == {"ollama": False, "database": False, "mcp": True}


@pytest.mark.parametrize(("status", "exit_code"), [(True, 0), (False, 1)])
def test_health_command(monkeypatch, status, exit_code):
    async def fake_health_check() -> dict[str, bool]:
        return {"ollama": True, "database": status, "mcp": True}

    monkeypatch.setattr(cli, "health_check", fake_health_check)
    result = CliRunner().invoke(cli.app, ["health"])

    assert result.exit_code == exit_code
    assert "database" in result.output
    assert ("indisponível" in result.output) is not status
