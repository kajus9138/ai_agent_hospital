---
title: CLI interativa
type: note
permalink: decisoes/cli
tags:
- decisao
- cli
- typer
---

# CLI interativa

Decisões tomadas na tarefa 8 (CLI User Interface), em 2026-10-27.

## Contexto
A task pedia uma CLI com Typer + Rich (`chat`, `threads`, `history`) com comandos `async def` e o
entry point `hospital-agent`. As notas das tasks 6 e 7 deixaram para a CLI: `sync_messages` ao fim de
cada turno com `agent.stream()`, `GraphRecursionError` e falha no meio de uma tool.

## Observations
- [decisao] `cli.py`: comandos Typer síncronos chamando `asyncio.run`; o Typer 0.27.3 não executa `async def` (sem `iscoroutinefunction` no `typer/main.py`, nada no Context7) #typer
- [decisao] Entry point continua `ai-agent-hospital`, agora `ai_agent_hospital.cli:app`; `main.py` só chama `app()` #cli
- [alternativa-descartada] `hospital-agent` (nome da task): o README e o `uv run ai-agent-hospital` já usavam o outro #cli
- [decisao] `open_session(settings, with_tools=...)`: pool + `init_schema` + `open_checkpointer` + (chat) health do Ollama e `DengueMCPClient`, tudo num `AsyncExitStack` na mesma task (stdio do MCP). Sem tools usa `HospitalReActAgent(llm, [], cp)`: threads/history/fork/delete não sobem o MCP nem exigem Ollama #cli
- [decisao] Falhas de inicialização viram `StartupError` → mensagem + exit 1; UUID inválido é erro de uso do Typer (exit 2) #cli
- [decisao] Entrada com `prompt_toolkit.PromptSession.prompt_async` (dependência nova): roda no event loop e traduz Ctrl+C/Ctrl+D em `KeyboardInterrupt`/`EOFError`; de quebra, histórico de linhas #cli
- [alternativa-descartada] `asyncio.to_thread(console.input)` (do plano): no Ctrl+C a thread fica presa no `input()` e o `asyncio.run` espera por ela no shutdown do executor #cli
- [decisao] Ctrl+C durante uma resposta: `loop.add_signal_handler(SIGINT)` cancela só a task do turno (o stream é fechado com `aclose()`), a conversa segue; removido ao sair do chat. Fora de um turno (ex.: gravando o histórico) o mesmo handler cancela o chat inteiro, senão o Ctrl+C seria ignorado (achado do /code-review) #cli
- [decisao] Turno renderizado por eventos do `astream_events`: tokens (`on_chat_model_stream`) num `Live` com Markdown; `on_chat_model_end` mostra o texto se nenhum token veio (modelo sem streaming); `on_tool_start` vira linha "→ consultando tool(args)" #langgraph
- [decisao] `sync_messages` depois de todo turno, inclusive com erro ou cancelamento (best-effort, aviso em amarelo); `GraphRecursionError` e outras exceções não matam o loop #threads
- [decisao] `ThreadManager.close_pending_tool_calls(thread_id)`: turno que falha ou é cancelado durante uma tool deixa a AIMessage com `tool_calls` sem ToolMessage; o método responde cada chamada pendente com `ToolMessage(status="error")` via `aupdate_state(..., as_node="tools")`. Chamado pela CLI após turno com falha e pelo `send_message` no erro (achado do /code-review) #langgraph
- [alternativa-descartada] Só orientar o usuário a fazer `fork` de um ponto estável (primeira versão): a próxima pergunta iria ao modelo com o histórico quebrado até ele perceber #langgraph
- [decisao] Texto dinâmico (usuário, modelo, tools, exceções) passa por `rich.markup.escape`: um `[/b]` digitado derrubava `history`/`threads` com MarkupError #cli
- [decisao] `chat` sem `--thread` apaga a thread nova se o usuário sair sem mandar nada; pools da CLI com `min_size=1, max_size=4` (são dois: repository e checkpointer); `psycopg.Error` depois da abertura vira mensagem + exit 1 #cli
- [licao] Coluna do Rich com `no_wrap=True` usa o texto inteiro como largura mínima e espreme as outras; a prévia em `threads` quebra linha e já vem truncada em 60 caracteres #cli
- [pendencia] Logs do servidor MCP (stderr herdado) aparecem no meio do chat; o `stdio_client` aceita `errlog`, dá para mandar para um arquivo no `DengueMCPClient` #mcp
- [convencao] Testes do chat (`tests/test_cli.py`): `run_chat` com `ThreadManager` real (Postgres, `integration`), `read_input` injetado e `Console(file=StringIO())`; o teste de Ctrl+C manda SIGINT de verdade (`os.kill`) com um modelo que trava; comandos Typer com `CliRunner` e `open_session` falso #testes
- [licao] Com stdin fora de um terminal (pipe) o prompt_toolkit funciona, mas avisa "Input is not a terminal" e ecoa o prompt; só cosmético #cli

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Agente ReAct com LangGraph]]
- depends_on [[Gerenciamento de threads]]
