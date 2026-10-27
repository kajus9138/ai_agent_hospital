"""CLI interativa: conversa com o agente e gerencia as threads salvas no PostgreSQL."""

import asyncio
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager, suppress
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

from ai_agent_hospital.agent.checkpointer import CheckpointerError, open_checkpointer
from ai_agent_hospital.agent.llm import check_ollama_health, get_llm
from ai_agent_hospital.agent.react_agent import HospitalReActAgent, create_hospital_agent
from ai_agent_hospital.agent.thread_manager import ThreadManager, ThreadNotFoundError
from ai_agent_hospital.config import Settings, get_settings
from ai_agent_hospital.db.connection import create_pool, init_schema
from ai_agent_hospital.db.repository import Message, ThreadPreview, ThreadRepository
from ai_agent_hospital.mcp_client import DengueMCPClient
from ai_agent_hospital.mcp_client.client import MCPConnectionError

EXIT_COMMANDS = {"exit", "quit", "sair"}
PREVIEW_WIDTH = 60

app = typer.Typer(
    help="Agente de apoio à decisão hospitalar (dengue em São Paulo).", no_args_is_help=True
)


class StartupError(Exception):
    """Algo de que a CLI depende (banco, Ollama, servidor MCP) não está disponível."""


@asynccontextmanager
async def open_session(
    settings: Settings | None = None, *, with_tools: bool
) -> AsyncIterator[ThreadManager]:
    """ThreadManager pronto para uso, com banco, checkpointer e (se `with_tools`) o servidor MCP.

    Sem tools o agente não chama o modelo nem sobe o servidor MCP: basta para listar, ler,
    bifurcar e apagar threads. Tudo é aberto e fechado nesta task (exigência do stdio do MCP).
    """
    settings = settings or get_settings()
    async with AsyncExitStack() as stack:
        # Pools pequenos: a CLI é um usuário só, e são dois (repository e checkpointer).
        pool = create_pool(settings.database_url, min_size=1, max_size=4)
        stack.push_async_callback(pool.close)
        try:
            await pool.open(wait=True, timeout=10.0)
            await init_schema(pool)
            checkpointer = await stack.enter_async_context(
                open_checkpointer(settings.database_url, min_size=1, max_size=4)
            )
        except CheckpointerError as exc:
            raise StartupError(str(exc)) from exc
        except psycopg.Error as exc:
            raise StartupError(
                f"Não foi possível conectar ao PostgreSQL: {exc}. Confira o DATABASE_URL e se o "
                "banco está no ar (`docker compose up -d`)."
            ) from exc

        llm = get_llm(settings)
        if with_tools:
            if not await check_ollama_health(settings):
                raise StartupError(
                    f"Ollama indisponível em {settings.ollama_base_url} ou modelo "
                    f"{settings.ollama_model} não baixado (`ollama pull {settings.ollama_model}`)."
                )
            try:
                client = await stack.enter_async_context(DengueMCPClient.from_settings(settings))
            except (MCPConnectionError, ValueError) as exc:
                raise StartupError(str(exc)) from exc
            agent = await create_hospital_agent(llm, client, checkpointer)
        else:
            agent = HospitalReActAgent(llm, [], checkpointer)
        yield ThreadManager(agent, ThreadRepository(pool))


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
            if kind == "on_chat_model_stream":
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


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Roda a corrotina do comando, traduzindo falhas conhecidas em mensagem + exit 1."""
    try:
        return asyncio.run(coro)
    except (StartupError, ThreadNotFoundError, ValueError) as exc:
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
