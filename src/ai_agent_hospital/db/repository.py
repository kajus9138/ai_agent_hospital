"""Acesso às tabelas threads e messages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class Thread:
    id: UUID
    created_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Message:
    id: UUID
    thread_id: UUID
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    created_at: datetime


class ThreadRepository:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> UUID:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO threads (metadata) VALUES (%s) RETURNING id",
                (Jsonb(metadata or {}),),
            )
            (thread_id,) = await cur.fetchone()
        return thread_id

    async def add_message(
        self,
        thread_id: UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Message:
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

    async def get_thread_messages(self, thread_id: UUID) -> list[Message]:
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
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=class_row(Thread))
            await cur.execute(
                "SELECT id, created_at, metadata FROM threads ORDER BY created_at DESC, id"
            )
            return await cur.fetchall()
