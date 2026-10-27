"""Agente ReAct (raciocínio + ações) que consulta as tools de dengue do servidor MCP."""

from collections.abc import AsyncIterator, Sequence

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.schema import StreamEvent
from langchain_core.tools import BaseTool
from langgraph.types import Checkpointer

from ai_agent_hospital.agent.prompts import HOSPITAL_SYSTEM_PROMPT
from ai_agent_hospital.mcp_client import DengueMCPClient, load_langchain_tools


class HospitalReActAgent:
    """Grafo ReAct do LangGraph com o prompt do hospital; cada conversa é um `thread_id`.

    Com checkpointer, o histórico de cada thread é salvo e retomado nas próximas mensagens; sem
    ele, cada chamada começa do zero.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
        checkpointer: Checkpointer = None,
        system_prompt: str = HOSPITAL_SYSTEM_PROMPT,
    ) -> None:
        # create_agent substitui o langgraph.prebuilt.create_react_agent, deprecated desde o
        # LangGraph 1.0; o antigo `state_modifier`/`prompt` aqui é `system_prompt`.
        self.graph = create_agent(
            model=llm,
            tools=list(tools),
            system_prompt=system_prompt,
            checkpointer=checkpointer,
        )

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    async def invoke(self, message: str, thread_id: str) -> str:
        """Envia a mensagem na thread e devolve a resposta final do agente."""
        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]}, config=self._config(thread_id)
        )
        return result["messages"][-1].text

    def stream(self, message: str, thread_id: str) -> AsyncIterator[StreamEvent]:
        """Eventos da execução (tokens do modelo, início/fim de tools) à medida que acontecem.

        Devolve o gerador do LangGraph direto: quem para de consumir pode fechá-lo (`aclose()`),
        encerrando a execução do grafo na hora.
        """
        return self.graph.astream_events(
            {"messages": [HumanMessage(content=message)]},
            config=self._config(thread_id),
            version="v2",
        )


async def create_hospital_agent(
    llm: BaseChatModel,
    mcp_client: DengueMCPClient,
    checkpointer: Checkpointer = None,
) -> HospitalReActAgent:
    """Agente com as tools descobertas no servidor MCP (o cliente precisa estar conectado)."""
    tools = await load_langchain_tools(mcp_client)
    return HospitalReActAgent(llm, tools, checkpointer)
