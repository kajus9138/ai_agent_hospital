"""Threads de conversa: catálogo e histórico no repository, estado do grafo no checkpointer."""

from contextlib import suppress
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from ai_agent_hospital.agent.react_agent import HospitalReActAgent
from ai_agent_hospital.db.repository import (
    Message,
    NewMessage,
    ThreadPreview,
    ThreadRepository,
    ThreadSummary,
)


class ThreadNotFoundError(LookupError):
    """A thread não existe no catálogo."""


def to_new_message(message: BaseMessage) -> NewMessage:
    """Converte uma mensagem do LangChain em (role, content, tool_calls) da tabela messages."""
    if isinstance(message, HumanMessage):
        return ("user", message.text, None)
    if isinstance(message, AIMessage):
        return ("assistant", message.text, [dict(c) for c in message.tool_calls] or None)
    if isinstance(message, ToolMessage):
        return ("tool", message.text, None)
    if isinstance(message, SystemMessage):
        return ("system", message.text, None)
    raise TypeError(f"Tipo de mensagem sem papel na tabela messages: {type(message).__name__}")


class ThreadManager:
    """Cria, lista, bifurca e apaga threads, mantendo repository e checkpointer em acordo.

    O `id` da thread no repository (UUID) é o `thread_id` do grafo. A tabela `messages` espelha as
    mensagens do estado do grafo, na mesma ordem: a posição N em uma é a posição N na outra.
    """

    def __init__(self, agent: HospitalReActAgent, repository: ThreadRepository) -> None:
        if agent.graph.checkpointer is None:
            raise ValueError("O agente precisa de um checkpointer para gerenciar threads.")
        self.agent = agent
        self.repository = repository

    @property
    def graph(self):
        return self.agent.graph

    @staticmethod
    def _config(thread_id: UUID) -> RunnableConfig:
        return {"configurable": {"thread_id": str(thread_id)}}

    async def _require(self, thread_id: UUID) -> None:
        if await self.repository.get_thread(thread_id) is None:
            raise ThreadNotFoundError(f"Thread {thread_id} não encontrada.")

    async def _state_messages(self, thread_id: UUID) -> list[BaseMessage]:
        state = await self.graph.aget_state(self._config(thread_id))
        return list(state.values.get("messages", []))

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> UUID:
        return await self.repository.create_thread(metadata)

    async def send_message(self, thread_id: UUID, text: str) -> str:
        """Envia a mensagem ao agente na thread, grava o histórico e devolve a resposta final."""
        await self._require(thread_id)
        try:
            answer = await self.agent.invoke(text, str(thread_id))
        except Exception:
            # O que chegou ao checkpoint antes da falha vai para o histórico, mas o erro que
            # importa é o do agente: uma falha aqui não o esconde (o próximo sync recupera).
            with suppress(Exception):
                await self.sync_messages(thread_id)
            raise
        await self.sync_messages(thread_id)
        return answer

    async def sync_messages(self, thread_id: UUID) -> int:
        """Grava no repository as mensagens do estado do grafo que ainda não estão lá.

        Para quem usa `agent.stream()` direto (a CLI): chamar ao fim de cada turno (e conferir antes
        do stream que a thread existe). Devolve quantas mensagens foram gravadas; se a tabela tiver
        mais mensagens que o estado, levanta `HistoryDivergedError` em vez de gravar desalinhado.
        """
        messages = [to_new_message(m) for m in await self._state_messages(thread_id)]
        written = await self.repository.append_missing_messages(thread_id, messages)
        if written is None:
            raise ThreadNotFoundError(f"Thread {thread_id} não encontrada.")
        return written

    async def get_history(self, thread_id: UUID) -> list[Message]:
        """Mensagens da thread em ordem de inserção."""
        await self._require(thread_id)
        return await self.repository.get_thread_messages(thread_id)

    async def list_threads(self) -> list[ThreadPreview]:
        return await self.repository.list_threads_with_preview()

    async def get_summary(self, thread_id: UUID) -> ThreadSummary:
        summary = await self.repository.get_thread_summary(thread_id)
        if summary is None:
            raise ThreadNotFoundError(f"Thread {thread_id} não encontrada.")
        return summary

    async def fork_thread(
        self, thread_id: UUID, from_message: int, metadata: dict[str, Any] | None = None
    ) -> UUID:
        """Nova thread com as `from_message` primeiras mensagens da original, que fica intacta.

        O corte precisa cair numa resposta final do assistente (sem tool_calls): no meio de um turno
        ficaria uma chamada de tool sem resultado ou duas perguntas seguidas.
        """
        await self._require(thread_id)
        messages = await self._state_messages(thread_id)
        if not 1 <= from_message <= len(messages):
            raise ValueError(f"from_message deve estar entre 1 e {len(messages)}: {from_message}.")
        last = messages[from_message - 1]
        if not isinstance(last, AIMessage) or last.tool_calls:
            raise ValueError(
                f"A mensagem {from_message} não é uma resposta final do assistente; "
                "escolha um ponto em que o turno terminou."
            )

        kept = messages[:from_message]
        new_id = await self.repository.create_thread(
            {**(metadata or {}), "forked_from": str(thread_id), "from_message": from_message}
        )
        try:
            # as_node="model": o estado fica como se o modelo tivesse acabado de responder, sem
            # próximo passo pendente; a próxima mensagem continua a conversa normalmente.
            await self.graph.aupdate_state(
                self._config(new_id), {"messages": kept}, as_node="model"
            )
            await self.repository.add_messages(new_id, [to_new_message(m) for m in kept])
        except Exception:
            # Limpeza best-effort: uma falha aqui não pode esconder o erro original.
            with suppress(Exception):
                await self.delete_thread(new_id)
            raise
        return new_id

    async def delete_thread(self, thread_id: UUID) -> bool:
        """Apaga a thread, suas mensagens e os checkpoints. False se ela não estava no catálogo.

        Catálogo primeiro: se a limpeza dos checkpoints falhar, sobra só estado órfão, invisível
        para listagens e syncs (nunca uma thread listada sem o estado do grafo).
        """
        deleted = await self.repository.delete_thread(thread_id)
        await self.graph.checkpointer.adelete_thread(str(thread_id))
        return deleted
