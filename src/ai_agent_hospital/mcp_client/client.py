"""Cliente do servidor MCP externo de dengue (projeto smart_hospitals), via stdio."""

import asyncio
import logging
import shlex
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.stdio import get_default_environment
from mcp.types import CallToolResult, Tool

from ai_agent_hospital.config import Settings, get_settings
from ai_agent_hospital.errors import MCPConnectionError

logger = logging.getLogger(__name__)

PATH_PLACEHOLDER = "${SMART_HOSPITALS_PATH}"


class DengueMCPClient:
    """Sobe o servidor MCP como subprocesso e mantém uma sessão aberta com ele.

    Use `async with DengueMCPClient(...) as client:` ou `connect()`/`close()`, sempre na mesma
    task: o transporte stdio usa cancel scopes do anyio, que não podem ser fechados em outra task.
    """

    def __init__(
        self,
        server_command: str,
        server_args: str,
        smart_hospitals_path: str | None = None,
        *,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        connect_timeout: float = 30.0,
    ) -> None:
        """
        Args:
            server_command: executável que sobe o servidor (ex.: `uv`).
            server_args: argumentos numa string, ex.: `run --directory ${SMART_HOSPITALS_PATH} x`.
            smart_hospitals_path: repo do smart_hospitals; substitui o placeholder e vira o cwd.
            max_retries: tentativas de conexão em `connect()`.
            retry_delay: espera antes da 2ª tentativa; dobra a cada nova tentativa.
            connect_timeout: limite, em segundos, do handshake (`initialize`) em cada tentativa.
        """
        # Absoluto: o path vira cwd do subprocesso e também vai no `--directory`; relativo, seria
        # resolvido duas vezes.
        path = (
            str(Path(smart_hospitals_path).expanduser().resolve()) if smart_hospitals_path else None
        )
        # Divide antes de substituir: um path com espaços continua sendo um argumento só.
        args = shlex.split(server_args)
        if any(PATH_PLACEHOLDER in arg for arg in args):
            if path is None:
                raise MCPConnectionError(
                    f"MCP_SERVER_ARGS usa {PATH_PLACEHOLDER}, mas SMART_HOSPITALS_PATH não foi "
                    "definido. Aponte-o para o clone do repo smart_hospitals."
                )
            args = [arg.replace(PATH_PLACEHOLDER, path) for arg in args]
        self._validate_config(server_command, path)

        # Ambiente filtrado do SDK (PATH, HOME, USER...): segredos do .env, como o DATABASE_URL,
        # não vazam para o subprocesso.
        env = get_default_environment()
        if path:
            env["SMART_HOSPITALS_PATH"] = path
        self.server_params = StdioServerParameters(
            command=server_command, args=args, cwd=path, env=env
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connect_timeout = connect_timeout
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._connect_lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kwargs) -> Self:
        """Cria o cliente com SMART_HOSPITALS_PATH, MCP_SERVER_COMMAND e MCP_SERVER_ARGS."""
        if settings is None:
            settings = get_settings()
        return cls(
            settings.mcp_server_command,
            settings.mcp_server_args,
            settings.smart_hospitals_path,
            **kwargs,
        )

    @staticmethod
    def _validate_config(command: str, path: str | None) -> None:
        if not shutil.which(command):
            raise MCPConnectionError(
                f"Comando '{command}' não encontrado no PATH. Se for o uv, instale com: "
                "curl -LsSf https://astral.sh/uv/install.sh | sh"
            )
        if path and not Path(path).is_dir():
            raise MCPConnectionError(
                f"Diretório não encontrado: {path}. Aponte SMART_HOSPITALS_PATH para o clone do "
                "repo smart_hospitals."
            )

    @property
    def session(self) -> ClientSession:
        """Sessão MCP ativa; levanta MCPConnectionError se `connect()` ainda não rodou."""
        if self._session is None:
            raise MCPConnectionError("Cliente MCP não conectado; chame connect() antes.")
        return self._session

    async def connect(self) -> ClientSession:
        """Sobe o servidor e faz o handshake, com backoff exponencial entre as tentativas."""
        # Lock: chamadas concorrentes não sobem dois subprocessos.
        async with self._connect_lock:
            if self._session is None:
                self._stack, self._session = await self._connect_with_retries()
            return self._session

    async def _connect_with_retries(self) -> tuple[AsyncExitStack, ClientSession]:
        last_error: BaseException | None = None
        for attempt in range(self.max_retries):
            if attempt:
                await asyncio.sleep(self.retry_delay * 2 ** (attempt - 1))
            stack = AsyncExitStack()
            try:
                read, write = await stack.enter_async_context(stdio_client(self.server_params))
                session = await stack.enter_async_context(ClientSession(read, write))
                # Timeout só no handshake: envolver a entrada dos contextos deixaria o escopo do
                # timeout atravessando a vida do task group do stdio_client.
                async with asyncio.timeout(self.connect_timeout):
                    await session.initialize()
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Tentativa %d/%d de conectar ao MCP falhou: %r",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                await self._close_quietly(stack)
                continue
            except BaseException:
                # Cancelamento/KeyboardInterrupt: encerra o subprocesso e propaga.
                await self._close_quietly(stack)
                raise
            return stack, session

        command = shlex.join([self.server_params.command, *self.server_params.args])
        raise MCPConnectionError(
            f"Não foi possível conectar ao servidor MCP após {self.max_retries} tentativa(s): "
            f"{last_error!r}. Confira se `{command}` sobe o servidor quando rodado à mão."
        ) from last_error

    async def list_tools(self) -> list[Tool]:
        """Tools que o servidor expõe (nome, descrição e inputSchema)."""
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
        """Executa uma tool; erros da própria tool vêm em `result.isError`, não como exceção."""
        return await self.session.call_tool(name, arguments or {})

    async def close(self) -> None:
        """Encerra a sessão e o subprocesso; pode ser chamado mais de uma vez."""
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            await stack.aclose()

    @staticmethod
    async def _close_quietly(stack: AsyncExitStack) -> None:
        # Ao falhar no meio da abertura, o fechamento também pode falhar (processo já morto).
        try:
            await stack.aclose()
        except Exception as exc:
            logger.debug("Erro ao limpar tentativa de conexão MCP: %r", exc)

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
