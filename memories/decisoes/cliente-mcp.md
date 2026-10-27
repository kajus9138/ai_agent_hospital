---
title: Cliente MCP do servidor de dengue
type: note
permalink: decisoes/cliente-mcp
tags:
- decisao
- mcp
- stdio
---

# Cliente MCP do servidor de dengue

Decisões tomadas na tarefa 4 (MCP Client for Stdio Communication), em 2026-10-27.

## Contexto
O servidor MCP de dengue é externo (repo smart_hospitals, FastMCP, stdio, `uv run --directory
<repo> dengue-mcp`). O agente precisa subir esse processo, manter uma sessão e usar as tools no
LangGraph. O texto da task sugeria um conversor JSON Schema → Pydantic feito à mão.

## Observations
- [decisao] `mcp_client/client.py`: `DengueMCPClient` mantém `stdio_client` + `ClientSession` num `AsyncExitStack`; `connect()`/`close()` ou `async with`, e `from_settings()` no mesmo padrão `settings | None` de `get_llm` #mcp
- [decisao] Conversão para LangChain com `langchain_mcp_adapters.tools.load_mcp_tools(client.session)` (decisão da task 1): trata schema, paginação, conteúdo/artefato e devolve `isError` ao modelo como ToolMessage de erro #mcp
- [alternativa-descartada] Conversor manual `_schema_to_pydantic` + `StructuredTool`: reimplementaria JSON Schema e o tratamento de resultado que o adapters já faz #mcp
- [decisao] Retry com backoff exponencial (`retry_delay * 2**n`) e timeout por tentativa só na abertura (`connect`); esgotado → `MCPConnectionError` com o comando para testar à mão #mcp
- [alternativa-descartada] Reconexão transparente no meio de uma chamada: as tools do adapters ficam presas à sessão, e servidor stdio que morre é falha de ambiente; quem usa recria o cliente #mcp
- [decisao] `${SMART_HOSPITALS_PATH}` é expandido pelo cliente por argumento, depois do `shlex.split` (path com espaços continua um argumento só), com o path já absoluto (ele também vira o `cwd`; relativo seria resolvido duas vezes); placeholder sem path → erro claro #config
- [decisao] Subprocesso recebe o ambiente filtrado do SDK (`get_default_environment()`: PATH, HOME, USER...) + SMART_HOSPITALS_PATH, não o `os.environ` inteiro: segredos do .env (DATABASE_URL) não vazam #seguranca
- [decisao] `connect()` sob `asyncio.Lock` (chamadas concorrentes não sobem dois servidores); timeout só em volta do `initialize()`; cancelamento no meio da abertura fecha o subprocesso antes de propagar #mcp
- [licao] O python-dotenv (1.2.4) expande `${VAR}` nos valores do `.env` mesmo entre aspas simples e troca variável ausente por "": por isso `MCP_SERVER_ARGS` fica comentado no `.env.example` e o padrão vive no `config.py` #config
- [licao] O transporte stdio usa cancel scopes do anyio: `connect()` e `close()` precisam rodar na mesma task #mcp
- [convencao] Testes sobem `tests/fake_dengue_server.py` (FastMCP com as 4 tools e dados fixos) com `sys.executable`: stdio real, sem smart_hospitals; o teste com o servidor real é da task 5 #testes
- [decisao] Task 5 (2026-10-27): integração com o servidor real em `tests/test_dengue_integration.py`, marker `dengue_mcp`; a fixture `settings` pula tudo se SMART_HOSPITALS_PATH não existir (marker sozinho não tira teste da suíte padrão) #testes
- [alternativa-descartada] Marker `integration` (pedido na task): no repo ele significa "precisa de PostgreSQL"; misturar faria `-m integration` exigir os dois serviços #testes
- [convencao] Asserts da integração checam só a forma (chaves, tamanho, `tendencia_resumo` ∈ alta/estavel/queda), não valores: eles mudam com o snapshot do InfoDengue no outro repo #testes
- [licao] O fake da task 4 tinha um contrato de `tendencia` diferente do real (`semanas` int + `tendencia`); alinhado ao real (`semanas` lista + `tendencia_resumo`). Ao mudar o servidor real, confira o fake #testes

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Setup do projeto Python]]
