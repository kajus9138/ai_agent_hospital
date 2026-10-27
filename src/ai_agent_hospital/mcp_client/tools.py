"""Tools do servidor MCP convertidas em tools do LangChain, para o agente ReAct."""

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools

from ai_agent_hospital.mcp_client.client import DengueMCPClient


async def load_langchain_tools(client: DengueMCPClient) -> list[BaseTool]:
    """Descobre as tools do servidor (sem nomes fixos) e as converte para o LangChain.

    As tools usam a sessão do cliente: só funcionam enquanto ele estiver conectado. Erros da
    própria tool (`isError`) voltam ao modelo como ToolMessage de erro, para ele se corrigir.
    """
    return await load_mcp_tools(client.session)
