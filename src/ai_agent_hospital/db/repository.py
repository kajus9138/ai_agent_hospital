"""Acesso às tabelas threads e messages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncCursor
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ai_agent_hospital.db.connection import transaction

# (role, content, tool_calls) de uma mensagem a gravar.
NewMessage = tuple[str, str, list[dict[str, Any]] | None]


class HistoryDivergedError(RuntimeError):
    """A tabela messages tem mais mensagens do que o histórico que deveria espelhar."""


async def _insert_messages(cur: AsyncCursor, thread_id: UUID, messages: list[NewMessage]) -> None:
    if not messages:
        return
    await cur.executemany(
        "INSERT INTO messages (thread_id, role, content, tool_calls) VALUES (%s, %s, %s, %s)",
        [
            (thread_id, role, content, Jsonb(tool_calls) if tool_calls is not None else None)
            for role, content, tool_calls in messages
        ],
    )


@dataclass(frozen=True)
class Thread:
    """Linha da tabela threads."""

    id: UUID
    created_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """Linha da tabela messages; `tool_calls` só em mensagens do assistente que chamam tools."""

    id: UUID
    thread_id: UUID
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    created_at: datetime


@dataclass(frozen=True)
class ThreadPreview:
    """Thread com a última mensagem, para listagens."""

    id: UUID
    created_at: datetime
    metadata: dict[str, Any]
    message_count: int
    last_message: str | None
    last_message_at: datetime | None


@dataclass(frozen=True)
class ThreadSummary:
    """Contagem e período (primeira e última mensagem) de uma thread."""

    id: UUID
    message_count: int
    first_message_at: datetime | None
    last_message_at: datetime | None


class ThreadRepository:
    """Acesso às tabelas threads e messages sobre um pool de conexões async."""

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> UUID:
        """Cria a thread com os metadados (ex.: título) e devolve o id gerado pelo banco."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO threads (metadata) VALUES (%s) RETURNING id",
                (Jsonb(metadata or {}),),
            )
            (thread_id,) = await cur.fetchone()
        return thread_id

    async def get_thread(self, thread_id: UUID) -> Thread | None:
        """A thread, ou None se ela não existe."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(Thread))
            await cur.execute(
                "SELECT id, created_at, metadata FROM threads WHERE id = %s", (thread_id,)
            )
            return await cur.fetchone()

    async def delete_thread(self, thread_id: UUID) -> bool:
        """Apaga a thread e, pelo ON DELETE CASCADE, suas mensagens. False se ela não existia."""
        async with self.pool.connection() as conn:
            cur = await conn.execute("DELETE FROM threads WHERE id = %s", (thread_id,))
            return cur.rowcount > 0

    async def add_message(
        self,
        thread_id: UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Grava uma mensagem no fim da thread e a devolve com id e data."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(Message))
            await cur.execute(
                """
                INSERT INTO messages (thread_id, role, content, tool_calls)
                VALUES (%s, %s, %s, %s)
                RETURNING id, thread_id, role, content, tool_calls, created_at
                """,
                (thread_id, role, content, Jsonb(tool_calls) if tool_calls is not None else None),
            )
            return await cur.fetchone()

    async def add_messages(self, thread_id: UUID, messages: list[NewMessage]) -> None:
        """Grava as mensagens na ordem dada, numa transação só (todas ou nenhuma)."""
        async with transaction(self.pool) as conn, conn.cursor() as cur:
            await _insert_messages(cur, thread_id, messages)

    async def append_missing_messages(
        self, thread_id: UUID, messages: list[NewMessage]
    ) -> int | None:
        """Recebe o histórico completo e grava só o que passa do que já está salvo.

        A linha da thread fica travada até o commit: dois syncs simultâneos da mesma thread não
        gravam a mesma cauda duas vezes. Devolve quantas mensagens gravou, ou None se a thread não
        existe.
        """
        async with transaction(self.pool) as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM threads WHERE id = %s FOR UPDATE", (thread_id,))
            if await cur.fetchone() is None:
                return None
            await cur.execute("SELECT count(*) FROM messages WHERE thread_id = %s", (thread_id,))
            (saved,) = await cur.fetchone()
            if saved > len(messages):
                raise HistoryDivergedError(
                    f"Thread {thread_id} tem {saved} mensagens salvas, mas o histórico recebido "
                    f"tem {len(messages)}."
                )
            await _insert_messages(cur, thread_id, messages[saved:])
        return len(messages) - saved

    async def count_messages(self, thread_id: UUID) -> int:
        """Quantas mensagens a thread tem."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) FROM messages WHERE thread_id = %s", (thread_id,)
            )
            (count,) = await cur.fetchone()
        return count

    async def get_thread_messages(self, thread_id: UUID) -> list[Message]:
        """Mensagens da thread em ordem de inserção (`seq`)."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(Message))
            await cur.execute(
                """
                SELECT id, thread_id, role, content, tool_calls, created_at
                FROM messages
                WHERE thread_id = %s
                ORDER BY seq
                """,
                (thread_id,),
            )
            return await cur.fetchall()

    async def list_threads(self) -> list[Thread]:
        """Todas as threads, da criada mais recentemente para a mais antiga."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(Thread))
            await cur.execute(
                "SELECT id, created_at, metadata FROM threads ORDER BY created_at DESC, id"
            )
            return await cur.fetchall()

    async def list_threads_with_preview(self) -> list[ThreadPreview]:
        """Threads com a última mensagem, da atividade mais recente para a mais antiga."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(ThreadPreview))
            await cur.execute(
                """
                SELECT t.id, t.created_at, t.metadata,
                       (SELECT count(*) FROM messages m WHERE m.thread_id = t.id) AS message_count,
                       last.content AS last_message, last.created_at AS last_message_at
                FROM threads t
                LEFT JOIN LATERAL (
                    SELECT content, created_at FROM messages m
                    WHERE m.thread_id = t.id ORDER BY seq DESC LIMIT 1
                ) last ON true
                ORDER BY COALESCE(last.created_at, t.created_at) DESC, t.id
                """
            )
            return await cur.fetchall()

    async def get_thread_summary(self, thread_id: UUID) -> ThreadSummary | None:
        """Contagem e período das mensagens; None se a thread não existe."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(ThreadSummary))
            await cur.execute(
                """
                SELECT t.id, count(m.id) AS message_count,
                       min(m.created_at) AS first_message_at, max(m.created_at) AS last_message_at
                FROM threads t LEFT JOIN messages m ON m.thread_id = t.id
                WHERE t.id = %s
                GROUP BY t.id
                """,
                (thread_id,),
            )
            return await cur.fetchone()
