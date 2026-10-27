"""Agente ReAct (raciocínio + ações) que consulta as tools de dengue do servidor MCP."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import ollama
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.schema import StreamEvent
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Checkpointer, Command

from ai_agent_hospital.agent.prompts import HOSPITAL_SYSTEM_PROMPT
from ai_agent_hospital.errors import OllamaConnectionError, ToolExecutionError
from ai_agent_hospital.mcp_client import DengueMCPClient, load_langchain_tools

# Gateway/indisponível/timeout. O 500 fica de fora: no Ollama costuma ser permanente (ex.: falta
# de memória para o modelo).
TRANSIENT_STATUS = {502, 503, 504}


def is_transient_model_error(exc: BaseException) -> bool:
    """Falhas do Ollama que valem nova tentativa: conexão, timeout ou 502/503/504."""
    if isinstance(exc, ollama.ResponseError):
        return exc.status_code in TRANSIENT_STATUS
    # O cliente do Ollama troca o httpx.ConnectError pelo ConnectionError embutido.
    return isinstance(exc, ConnectionError | httpx.TransportError)


class OllamaFailureMiddleware(AgentMiddleware):
    """Esgotados os retries, troca a falha transitória do modelo por OllamaConnectionError."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        try:
            return await handler(request)
        except Exception as exc:
            if not is_transient_model_error(exc):
                raise
            raise OllamaConnectionError(
                f"O Ollama não respondeu mesmo após novas tentativas ({exc!r}). Confira se ele "
                "está no ar e tente de novo."
            ) from exc


class ToolFailureMiddleware(AgentMiddleware):
    """Troca exceções inesperadas de uma tool por ToolExecutionError, com o nome da tool.

    Só chegam aqui falhas fora do protocolo (ex.: sessão MCP morta): `isError` e argumentos
    inválidos já viram ToolMessage de erro antes, no ToolNode.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await handler(request)
        # GraphBubbleUp: sinais de controle do LangGraph (interrupts), não são falhas.
        except (GraphBubbleUp, ToolExecutionError):
            raise
        except Exception as exc:
            raise ToolExecutionError(request.tool_call["name"], exc) from exc


def default_middleware() -> list[AgentMiddleware]:
    # O primeiro da lista é o mais externo: OllamaFailureMiddleware só vê a falha final do retry.
    return [
        OllamaFailureMiddleware(),
        # on_failure="error": esgotadas as tentativas, a falha propaga em vez de virar uma
        # resposta do "assistente" com o texto do erro.
        ModelRetryMiddleware(max_retries=2, retry_on=is_transient_model_error, on_failure="error"),
        ToolFailureMiddleware(),
    ]


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
        middleware: Sequence[AgentMiddleware] | None = None,
    ) -> None:
        """`middleware=None` usa `default_middleware()`: retry do modelo e erro tipado de tool."""
        # create_agent substitui o langgraph.prebuilt.create_react_agent, deprecated desde o
        # LangGraph 1.0; o antigo `state_modifier`/`prompt` aqui é `system_prompt`.
        self.graph = create_agent(
            model=llm,
            tools=list(tools),
            system_prompt=system_prompt,
            checkpointer=checkpointer,
            middleware=default_middleware() if middleware is None else list(middleware),
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
