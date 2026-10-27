"""Servidor MCP falso (stdio) com as mesmas 4 tools do servidor de dengue do smart_hospitals.

Devolve dados fixos: serve para testar o cliente com o transporte stdio de verdade, sem depender do
repo smart_hospitals. Rodar com: `python tests/fake_dengue_server.py`.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dengue-fake")


@mcp.tool()
def situacao_atual() -> dict:
    """Situação atual da dengue em São Paulo (última semana epidemiológica)."""
    return {"semana": "202643", "casos": 1250, "incidencia_100k": 10.7, "nivel": "alerta"}


@mcp.tool()
def tendencia(semanas: int = 4) -> dict:
    """Tendência de casos nas últimas N semanas (1 a 52)."""
    if not 1 <= semanas <= 52:
        raise ValueError("semanas deve estar entre 1 e 52")
    return {"semanas": semanas, "variacao_pct": 12.5, "tendencia": "alta"}


@mcp.tool()
def serie_historica(inicio: str, fim: str) -> list[dict]:
    """Série semanal de casos entre `inicio` e `fim` (YYYYWW ou YYYY-MM-DD)."""
    return [{"semana": inicio, "casos": 900}, {"semana": fim, "casos": 1250}]


@mcp.tool()
def comparativo_sazonal(semana: int | None = None) -> dict:
    """Compara a semana (1 a 53; padrão: a atual) com os mesmos períodos dos anos anteriores."""
    return {"semana": semana or 43, "atual": 1250, "media_anos_anteriores": 800}


if __name__ == "__main__":
    mcp.run()
