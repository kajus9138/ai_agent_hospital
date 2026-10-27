"""Erros da aplicação: um tipo por serviço externo, todos com uma base comum.

A CLI captura `AgentHospitalError` e mostra a mensagem; por isso cada erro já diz o que conferir.
"""


class AgentHospitalError(Exception):
    """Base dos erros conhecidos da aplicação."""


class OllamaConnectionError(AgentHospitalError):
    """Ollama fora do ar ou modelo configurado não baixado."""


class DatabaseConnectionError(AgentHospitalError):
    """PostgreSQL inacessível ou falha ao preparar as tabelas."""


class MCPConnectionError(AgentHospitalError):
    """Falha ao configurar, iniciar ou usar a conexão com o servidor MCP."""


class ToolExecutionError(AgentHospitalError):
    """Uma tool MCP falhou fora do protocolo (ex.: servidor morreu no meio da chamada).

    Erros que a própria tool devolve (`isError`) não viram esta exceção: vão ao modelo como
    ToolMessage de erro, para ele se corrigir.
    """

    def __init__(self, tool_name: str, cause: BaseException) -> None:
        super().__init__(
            f"A tool '{tool_name}' falhou fora do protocolo MCP: {cause!r}. Se o servidor MCP "
            "caiu, reinicie o chat."
        )
        self.tool_name = tool_name
