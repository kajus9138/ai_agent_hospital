"""CLI interativa: conversa com o agente e gerencia as threads salvas no PostgreSQL."""

import asyncio
import signal
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Annotated, Any
from uuid import UUID

import psycopg
import typer
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ai_agent_hospital.agent.thread_manager import ThreadManager, ThreadNotFoundError
from ai_agent_hospital.bootstrap import open_session
from ai_agent_hospital.db.repository import Message, ThreadPreview
from ai_agent_hospital.errors import AgentHospitalError
from ai_agent_hospital.health import health_check

EXIT_COMMANDS = {"exit", "quit", "sair"}
EXIT_SIGTERM = 128 + signal.SIGTERM
PREVIEW_WIDTH = 60

app = typer.Typer(
    help="Agente de apoio à decisão hospitalar (dengue em São Paulo).", no_args_is_help=True
)


def _format_args(args: Any) -> str:
    if isinstance(args, dict):
        return ", ".join(f"{k}={v!r}" for k, v in args.items())
    return "" if args is None else str(args)


def _assistant_panel(text: str, title: str) -> Panel:
    return Panel(Markdown(text), title=title, title_align="left", border_style="blue")


class TurnRenderer:
    """Mostra um turno do agente: spinner, texto do modelo em tempo real e chamadas de tools."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.text = ""
        self.live: Live | None = None
        self.status = console.status("Pensando…")
        self.status.start()

    def _panel(self) -> Panel:
        return _assistant_panel(self.text, "Assistente")

    def token(self, text: str) -> None:
        if not text:
            return
        self.status.stop()
        if self.live is None:
            self.live = Live(self._panel(), console=self.console, refresh_per_second=8)
            self.live.start()
        self.text += text
        self.live.update(self._panel())

    def model_start(self) -> None:
        """Nova chamada do modelo: descarta texto parcial de uma tentativa que falhou (retry)."""
        if self.text:
            self.text = ""
            if self.live is not None:
                self.live.update(self._panel())

    def model_end(self, message: Any) -> None:
        """Fim de uma chamada do modelo; mostra o texto se ele não veio em tokens."""
        if self.live is None and isinstance(message, AIMessage) and message.text:
            self.token(message.text)
        self._close_text()

    def tool_start(self, name: str, args: Any) -> None:
        self._close_text()
        self.status.stop()
        self.console.print(
            f"[dim]→ consultando [bold]{escape(name)}[/]({escape(_format_args(args))})[/]"
        )
        self.status.start()

    def tool_error(self, name: str) -> None:
        self.console.print(
            f"[yellow]  {escape(name)} devolveu erro; o agente vai considerar isso.[/]"
        )

    def _close_text(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None
        self.text = ""

    def close(self) -> None:
        self._close_text()
        self.status.stop()


async def run_turn(manager: ThreadManager, thread_id: UUID, text: str, console: Console) -> None:
    """Envia a mensagem e mostra a resposta conforme ela chega; o histórico é gravado no fim."""
    renderer = TurnRenderer(console)
    events = manager.agent.stream(text, str(thread_id))
    try:
        async for event in events:
            kind, data = event["event"], event["data"]
            if kind == "on_chat_model_start":
                renderer.model_start()
            elif kind == "on_chat_model_stream":
                renderer.token(data["chunk"].text)
            elif kind == "on_chat_model_end":
                renderer.model_end(data.get("output"))
            elif kind == "on_tool_start":
                renderer.tool_start(event["name"], data.get("input"))
            elif kind == "on_tool_end" and getattr(data.get("output"), "status", None) == "error":
                renderer.tool_error(event["name"])
    finally:
        renderer.close()
        # Fecha o grafo já (inclusive no cancelamento), sem esperar o GC.
        await events.aclose()


async def read_prompt(session: PromptSession) -> str:
    return await session.prompt_async("Você: ")


async def run_chat(
    manager: ThreadManager,
    thread_id: UUID,
    console: Console,
    read_input: Callable[[], Awaitable[str]],
) -> None:
    """Laço da conversa: lê, responde, grava. Ctrl+C durante uma resposta cancela só ela.

    `read_input` deve levantar EOFError (Ctrl+D) ou KeyboardInterrupt (Ctrl+C) para sair. Fora de
    uma resposta (ex.: gravando o histórico), Ctrl+C cancela o chat inteiro.
    """
    console.print(
        f"[dim]Thread {thread_id} — digite 'sair' (ou Ctrl+D) para encerrar; Ctrl+C interrompe "
        "uma resposta.[/]"
    )
    loop = asyncio.get_running_loop()
    chat_task = asyncio.current_task()
    current: asyncio.Task[None] | None = None

    def cancel_turn() -> None:
        # O handler substitui o do asyncio.run: sem turno rodando, Ctrl+C tem de encerrar o chat.
        target = current if current is not None else chat_task
        if target is not None:
            target.cancel()

    # Fora de um terminal (testes, threads auxiliares) não dá para instalar o handler; segue sem.
    has_handler = False
    with suppress(NotImplementedError, RuntimeError, ValueError):
        loop.add_signal_handler(signal.SIGINT, cancel_turn)
        has_handler = True
    try:
        while True:
            try:
                text = (await read_input()).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text.lower() in EXIT_COMMANDS:
                break

            current = asyncio.create_task(run_turn(manager, thread_id, text, console))
            failed = True
            try:
                await current
                failed = False
            except asyncio.CancelledError:
                # Cancelado só o turno (Ctrl+C), a conversa segue; cancelado o chat, propaga.
                if chat_task is not None and chat_task.cancelling():
                    raise
                console.print("[yellow]Resposta interrompida.[/]")
            except GraphRecursionError:
                console.print(
                    "[red]O agente entrou em loop chamando ferramentas e foi interrompido. "
                    "Tente reformular a pergunta.[/]"
                )
            except AgentHospitalError as exc:
                console.print(f"[red]{escape(str(exc))}[/]")
            except Exception as exc:
                console.print(f"[red]Erro do agente: {escape(str(exc))}[/]")
            finally:
                current = None
            await _save_turn(manager, thread_id, console, failed=failed)
    finally:
        if has_handler:
            loop.remove_signal_handler(signal.SIGINT)


async def _save_turn(
    manager: ThreadManager, thread_id: UUID, console: Console, *, failed: bool
) -> None:
    """Grava no histórico o que o turno deixou no checkpoint, mesmo se ele falhou.

    Num turno que falhou ou foi interrompido durante uma tool, fecha antes as chamadas sem
    resultado, para a próxima pergunta não ir ao modelo com o histórico quebrado.
    """
    try:
        if failed:
            await manager.close_pending_tool_calls(thread_id)
        await manager.sync_messages(thread_id)
    except Exception as exc:
        console.print(f"[yellow]Não foi possível gravar o histórico agora: {escape(str(exc))}[/]")


def render_threads(threads: list[ThreadPreview], console: Console) -> None:
    if not threads:
        console.print("Nenhuma thread ainda. Comece com `chat`.")
        return
    table = Table(title="Threads")
    # Só a prévia quebra linha: ID e data ficam inteiros (o ID é copiado para os outros comandos).
    table.add_column("ID", no_wrap=True)
    table.add_column("Criada em", no_wrap=True)
    table.add_column("Msgs", justify="right", no_wrap=True)
    table.add_column("Última mensagem")
    for t in threads:
        last = escape(_truncate(t.last_message or "", PREVIEW_WIDTH))
        table.add_row(str(t.id), f"{t.created_at:%d/%m/%y %H:%M}", str(t.message_count), last)
    console.print(table)


def render_history(messages: list[Message], console: Console) -> None:
    if not messages:
        console.print("Thread sem mensagens.")
        return
    for n, m in enumerate(messages, start=1):
        if m.role == "user":
            console.print(f"[bold green]#{n} Você:[/] {escape(m.content)}")
        elif m.role == "assistant":
            for call in m.tool_calls or []:
                name, args = str(call.get("name")), _format_args(call.get("args"))
                console.print(f"[dim]#{n} → {escape(name)}({escape(args)})[/]")
            if m.content:
                console.print(_assistant_panel(m.content, f"#{n} Assistente"))
            elif not m.tool_calls:
                # Sem texto nem tools (turno interrompido): mostra mesmo assim, o número conta.
                console.print(f"[dim]#{n} Assistente: (sem texto)[/]")
        elif m.role == "tool":
            console.print(f"[dim]#{n} resultado: {escape(_truncate(m.content, 200))}[/]")
        else:
            console.print(f"[dim]#{n} {escape(m.role)}: {escape(m.content)}[/]")


def _truncate(text: str, width: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


console = Console()
err_console = Console(stderr=True)


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise typer.BadParameter(f"'{value}' não é um ID de thread válido.") from None


ThreadArg = Annotated[UUID, typer.Argument(parser=_parse_uuid, help="ID da thread.")]


async def _cancel_on_sigterm(coro: Coroutine[Any, Any, Any]) -> Any:
    """Roda `coro` e, no SIGTERM, a cancela: os `async with` fecham pools e o servidor MCP."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    terminated = False

    def on_sigterm() -> None:
        nonlocal terminated
        terminated = True
        if task is not None:
            task.cancel()

    has_handler = False
    with suppress(NotImplementedError, RuntimeError, ValueError):
        loop.add_signal_handler(signal.SIGTERM, on_sigterm)
        has_handler = True
    try:
        return await coro
    except (asyncio.CancelledError, Exception):
        # Um erro ao fechar as conexões durante o cancelamento não muda o motivo da saída.
        if terminated:
            raise typer.Exit(EXIT_SIGTERM) from None
        raise
    finally:
        if has_handler:
            loop.remove_signal_handler(signal.SIGTERM)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Roda a corrotina do comando, traduzindo falhas conhecidas em mensagem + exit 1."""
    try:
        return asyncio.run(_cancel_on_sigterm(coro))
    except (AgentHospitalError, ThreadNotFoundError, ValueError) as exc:
        err_console.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(1) from None
    except psycopg.Error as exc:
        err_console.print(f"[red]Erro no PostgreSQL: {escape(str(exc))}[/]")
        raise typer.Exit(1) from None
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise typer.Exit(130) from None


@app.command()
def chat(
    thread: Annotated[
        UUID | None,
        typer.Option(parser=_parse_uuid, help="Retoma uma thread existente em vez de criar outra."),
    ] = None,
) -> None:
    """Conversa com o agente (nova thread ou uma existente)."""

    async def main() -> None:
        async with open_session(with_tools=True) as manager:
            if thread is None:
                thread_id = await manager.create_thread()
            else:
                await manager.get_summary(thread)  # ThreadNotFoundError se não existir
                thread_id = thread
            session: PromptSession = PromptSession()
            await run_chat(manager, thread_id, console, lambda: read_prompt(session))
            if thread is None and (await manager.get_summary(thread_id)).message_count == 0:
                # Saiu sem perguntar nada: não deixa uma thread vazia na lista.
                await manager.delete_thread(thread_id)
            else:
                console.print(f"[dim]Thread salva. Retome com `chat --thread {thread_id}`.[/]")

    _run(main())


@app.command()
def threads() -> None:
    """Lista as threads com a última mensagem de cada uma."""

    async def main() -> None:
        async with open_session(with_tools=False) as manager:
            render_threads(await manager.list_threads(), console)

    _run(main())


@app.command()
def history(thread_id: ThreadArg) -> None:
    """Mostra as mensagens de uma thread, numeradas (o número serve para o `fork`)."""

    async def main() -> None:
        async with open_session(with_tools=False) as manager:
            render_history(await manager.get_history(thread_id), console)

    _run(main())


@app.command()
def fork(
    thread_id: ThreadArg,
    from_message: Annotated[
        int,
        typer.Option(
            "--from", help="Copia as N primeiras mensagens (deve ser uma resposta final)."
        ),
    ],
) -> None:
    """Cria uma thread nova a partir das N primeiras mensagens de outra."""

    async def main() -> UUID:
        async with open_session(with_tools=False) as manager:
            return await manager.fork_thread(thread_id, from_message)

    new_id = _run(main())
    console.print(f"Thread criada: {new_id}\nContinue com `chat --thread {new_id}`.")


@app.command()
def delete(
    thread_id: ThreadArg,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Não pede confirmação.")] = False,
) -> None:
    """Apaga a thread, o histórico e o estado salvo do agente."""
    if not yes:
        typer.confirm(f"Apagar a thread {thread_id}?", abort=True)

    async def main() -> bool:
        async with open_session(with_tools=False) as manager:
            return await manager.delete_thread(thread_id)

    if _run(main()):
        console.print("Thread apagada.")
    else:
        err_console.print(f"[red]Thread {thread_id} não encontrada.[/]")
        raise typer.Exit(1)


@app.command()
def health() -> None:
    """Verifica Ollama, PostgreSQL e servidor MCP; sai com 1 se algum estiver fora."""
    status = _run(health_check())
    table = Table(title="Serviços")
    table.add_column("Serviço")
    table.add_column("Estado")
    for name, ok in status.items():
        table.add_row(name, "[green]ok[/]" if ok else "[red]indisponível[/]")
    console.print(table)
    if not all(status.values()):
        raise typer.Exit(1)
