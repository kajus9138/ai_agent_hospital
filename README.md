# ai_agent_hospital

POC de um agente ReAct de apoio à decisão para um hospital inteligente. Um gestor pergunta, em
português, como está a dengue em São Paulo; o agente decide quais dados consultar, chama as tools de
um servidor MCP local, raciocina sobre os indicadores (casos estimados, nível de alerta, Rt,
comparação com anos anteriores) e responde citando a semana de referência. Tudo roda na máquina: o
LLM no Ollama, as conversas no PostgreSQL e os dados num servidor MCP iniciado via stdio.

```mermaid
flowchart LR
    gestor([Gestor]) --> cli["CLI<br/>ai-agent-hospital"]
    cli --> agente["Agente ReAct<br/>(LangGraph)"]
    agente -->|raciocínio| ollama[("Ollama<br/>LLM local")]
    agente -->|threads| pg[("PostgreSQL")]
    agente -->|"tools via stdio"| mcp["Servidor MCP de dengue<br/>(smart_hospitals, repo externo)"]
    mcp --> dados[("Snapshot InfoDengue<br/>dengue em SP")]
```

**Stack:** Python 3.12 · LangGraph · langchain-ollama · langchain-mcp-adapters · PostgreSQL
(`langgraph-checkpoint-postgres` + psycopg 3) · uv · pytest · ruff

**Documentação:**

- [docs/architecture.md](docs/architecture.md): componentes, loop ReAct, persistência e erros
- [docs/mcp-integration.md](docs/mcp-integration.md): servidor MCP externo, tools, atualização de
  dados e solução de problemas
- [DEMO.md](DEMO.md): roteiro de demonstração com conversas reais
- [docs/acceptance-criteria.md](docs/acceptance-criteria.md): critérios de aceite do PRD e evidências

## Pré-requisitos

- [uv](https://docs.astral.sh/uv/) (instala o Python 3.12 se faltar)
- [Docker](https://docs.docker.com/get-docker/) com o Compose, para o PostgreSQL (ou um PostgreSQL
  13+ acessível)
- [Ollama](https://ollama.com/) rodando, com um modelo que suporte tool calling
- Git, para clonar o servidor MCP [smart_hospitals](https://github.com/kajus9138/smart_hospitals)

## Quick start

```bash
# 1. Servidor MCP de dengue (repositório separado), uma vez
git clone https://github.com/kajus9138/smart_hospitals.git ~/smart_hospitals
(cd ~/smart_hospitals && uv sync)

# 2. Serviços locais
docker compose up -d        # PostgreSQL 16 em localhost:5432
ollama pull llama3.2        # modelo padrão (para a demo: qwen2.5, veja abaixo)

# 3. Este projeto
uv sync                     # cria o .venv e instala as dependências
cp .env.example .env        # e ajuste SMART_HOSPITALS_PATH=/home/<você>/smart_hospitals

# 4. Conferir e conversar
uv run ai-agent-hospital health   # ollama, database e mcp devem estar "ok"
uv run ai-agent-hospital chat
```

Se o `health` mostrar algum serviço `indisponível`, a linha acima da tabela diz o motivo; para o MCP,
veja a [solução de problemas](docs/mcp-integration.md#solução-de-problemas).

Para apresentações, use `OLLAMA_MODEL=qwen2.5` (`ollama pull qwen2.5`, 4,7 GB): é o modelo com que as
conversas do [DEMO.md](DEMO.md) foram gravadas e o que erra menos ao chamar tools.

## Configuração

Lida de variáveis de ambiente e do `.env` (variáveis já definidas no ambiente têm prioridade):

| Variável | Padrão | Para quê |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2` | Modelo do Ollama; precisa suportar tool calling (veja [LLM](#llm-ollama)) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endereço do Ollama |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/ai_agent_hospital` | PostgreSQL das threads; o padrão é o do `docker-compose.yml` |
| `SMART_HOSPITALS_PATH` | (nenhum) | Clone do smart_hospitals; obrigatória para o `chat` e o `health` |
| `MCP_SERVER_COMMAND` | `uv` | Executável que sobe o servidor MCP |
| `MCP_SERVER_ARGS` | `run --directory ${SMART_HOSPITALS_PATH} dengue-mcp` | Argumentos do servidor MCP; o cliente expande o placeholder |
| `TEST_DATABASE_URL` | `DATABASE_URL` | Só para os testes de integração |

Deixe `MCP_SERVER_ARGS` comentado no `.env`, como no `.env.example`; o porquê e como o comando do
servidor é montado estão em [docs/mcp-integration.md](docs/mcp-integration.md#variáveis-de-ambiente).

## Exemplos de perguntas

Cada pergunta leva o agente a uma das tools do servidor MCP (conversas completas no
[DEMO.md](DEMO.md)):

| Pergunta | Tool |
|---|---|
| "Qual a situação atual da dengue em São Paulo?" | `situacao_atual` |
| "Como está a tendência da dengue nas últimas 4 semanas?" | `tendencia` |
| "Mostre a série histórica de julho a setembro de 2026." | `serie_historica` |
| "Como esta semana se compara com a mesma semana dos anos anteriores?" | `comparativo_sazonal` |

Perguntas de decisão ("Devo reforçar a triagem no pronto-socorro?") costumam combinar várias tools.
Fora do escopo dos dados (leitos, bairros, outras cidades), o agente diz que a informação não está
disponível.

## Uso como biblioteca

### Banco de dados

O `docker-compose.yml` sobe um PostgreSQL 16 em `localhost:5432` (banco `ai_agent_hospital`,
usuário/senha `postgres`), que é o `DATABASE_URL` padrão. O schema (`threads` e `messages`) está em
`src/ai_agent_hospital/db/schema.sql` e é idempotente: `init_schema(pool)` cria o que faltar.

```python
from ai_agent_hospital.db.connection import create_pool, init_schema
from ai_agent_hospital.db.repository import ThreadRepository

async with create_pool() as pool:  # usa DATABASE_URL
    await init_schema(pool)
    repo = ThreadRepository(pool)
    thread_id = await repo.create_thread({"title": "Ocupação de leitos"})
    await repo.add_message(thread_id, "user", "Como está a dengue em SP?")
    messages = await repo.get_thread_messages(thread_id)
```

### LLM (Ollama)

O modelo vem de `OLLAMA_MODEL` (padrão `llama3.2`) servido em `OLLAMA_BASE_URL`. `get_llm()` devolve
um `ChatOllama` (chat model do LangChain, usável no LangGraph) com temperatura 0.1, para um
raciocínio mais consistente. `check_ollama_health()` confirma que o Ollama responde **e** que o
modelo configurado já foi baixado.

Modelos recomendados para ReAct (precisam de suporte a tool calling): `llama3.2` (3B, leve),
`qwen2.5` (7B, o mais confiável em tool calling) e `mistral` (7B). O `llama3.2:1b` serve para testes
rápidos, mas erra com frequência ao chamar tools.

```bash
ollama pull llama3.2
```

```python
import asyncio

from ai_agent_hospital.agent.llm import check_ollama_health, get_llm


async def main():
    if await check_ollama_health():
        llm = get_llm()  # ou get_llm(temperature=0) para sobrescrever padrões
        resposta = await llm.ainvoke("Quais os sintomas de alerta da dengue?")
        print(resposta.content)


asyncio.run(main())
```

### Servidor MCP de dengue (smart_hospitals)

O cliente sobe o servidor do [smart_hospitals](https://github.com/kajus9138/smart_hospitals) via stdio
com `MCP_SERVER_COMMAND` + `MCP_SERVER_ARGS` e descobre as tools (`situacao_atual`, `tendencia`,
`serie_historica`, `comparativo_sazonal`) na conexão, convertendo-as para tools do LangChain.
Preparação, montagem do comando e solução de problemas: [docs/mcp-integration.md](docs/mcp-integration.md).

```python
from ai_agent_hospital.mcp_client import DengueMCPClient, load_langchain_tools

async with DengueMCPClient.from_settings() as client:  # 3 tentativas, com backoff
    tools = await load_langchain_tools(client)  # válidas enquanto o cliente estiver conectado
    resultado = await client.call_tool("tendencia", {"semanas": 8})
```

### Agente ReAct

`HospitalReActAgent` monta o grafo ReAct com `langchain.agents.create_agent` (sucessor do
`create_react_agent` do LangGraph), o prompt de sistema em `agent/prompts.py` e as tools descobertas
no servidor MCP. Cada conversa é um `thread_id`; com o checkpointer do PostgreSQL
(`open_checkpointer()`, que cria suas tabelas na primeira vez), o histórico sobrevive a reinícios.

```python
from ai_agent_hospital.agent.checkpointer import open_checkpointer
from ai_agent_hospital.agent.llm import get_llm
from ai_agent_hospital.agent.react_agent import create_hospital_agent
from ai_agent_hospital.mcp_client import DengueMCPClient

async with DengueMCPClient.from_settings() as client, open_checkpointer() as checkpointer:
    agent = await create_hospital_agent(get_llm(), client, checkpointer)
    print(await agent.invoke("A dengue está em alta ou queda?", thread_id="gestor-1"))
    async for event in agent.stream("E comparado a 2024?", thread_id="gestor-1"):
        ...  # eventos do astream_events (v2): tokens do modelo, início/fim de tools
```

### Threads

`ThreadManager` junta o catálogo (`threads`/`messages`) e o checkpointer: o UUID da thread no
catálogo é o `thread_id` do grafo, e a tabela `messages` espelha o estado do grafo na mesma ordem.

```python
from ai_agent_hospital.agent.thread_manager import ThreadManager
from ai_agent_hospital.db.connection import create_pool, init_schema
from ai_agent_hospital.db.repository import ThreadRepository

async with create_pool() as pool, open_checkpointer() as checkpointer:
    await init_schema(pool)
    agent = await create_hospital_agent(get_llm(), client, checkpointer)
    threads = ThreadManager(agent, ThreadRepository(pool))

    thread_id = await threads.create_thread({"title": "Dengue SP"})
    print(await threads.send_message(thread_id, "A dengue está em alta?"))  # grava o histórico
    history = await threads.get_history(thread_id)  # mensagens em ordem
    await threads.list_threads()  # com última mensagem e contagem
    await threads.get_summary(thread_id)  # contagem e período
    fork = await threads.fork_thread(thread_id, 2)  # nova thread com as 2 primeiras
    await threads.delete_thread(thread_id)  # catálogo, mensagens e checkpoints
```

Quem usa `agent.stream()` direto chama `threads.sync_messages(thread_id)` ao fim de cada turno.
O fork só corta numa resposta final do assistente (sem chamada de tool pendente).

## CLI

```bash
uv run ai-agent-hospital chat                    # conversa numa thread nova
uv run ai-agent-hospital chat --thread <id>      # retoma uma thread
uv run ai-agent-hospital threads                 # lista as threads e a última mensagem
uv run ai-agent-hospital history <id>            # mensagens numeradas da thread
uv run ai-agent-hospital fork <id> --from 4      # thread nova com as 4 primeiras mensagens
uv run ai-agent-hospital delete <id> [--yes]     # apaga thread, histórico e checkpoints
uv run ai-agent-hospital health                  # estado do Ollama, PostgreSQL e servidor MCP
```

O `chat` precisa do PostgreSQL, do Ollama com o modelo baixado e do smart_hospitals; os demais
comandos só do PostgreSQL. A resposta aparece conforme o modelo gera, com uma linha para cada tool
consultada. No chat, `sair` (ou `exit`/`quit`, Ctrl+D) encerra; Ctrl+C interrompe só a resposta em
andamento. O histórico é gravado ao fim de cada turno, inclusive quando ele falha; uma tool
interrompida fica registrada com erro (`ThreadManager.close_pending_tool_calls`), e a conversa segue.
Para voltar a um ponto anterior, use o `fork` (o número vem do `history`).

### Erros e health check

Se algo não sobe, o comando sai com código 1 e uma mensagem do que conferir. Os erros têm a base
`AgentHospitalError` (`errors.py`): `DatabaseConnectionError`, `OllamaConnectionError`,
`MCPConnectionError` e `ToolExecutionError` (tool que falha fora do protocolo, ex.: o servidor MCP
caiu). Falhas transitórias têm novas tentativas com backoff exponencial: cada chamada do modelo
(conexão, timeout, 502/503/504; esgotadas, viram `OllamaConnectionError`), a conexão com o banco
(o próprio pool) e a do servidor MCP. O `health` verifica os três serviços em paralelo e sai com 1 se algum estiver fora.
SIGTERM (ex.: `kill`) fecha pools e o servidor MCP antes de sair (código 143).

## Estrutura

```
src/ai_agent_hospital/
  agent/        # lógica do agente ReAct
  db/           # persistência das threads no PostgreSQL
  mcp_client/   # comunicação com o MCP local (stdio)
  config.py     # configurações via variáveis de ambiente / .env
  bootstrap.py  # monta banco, checkpointer, Ollama e MCP num ThreadManager (open_session)
  errors.py     # erros da aplicação (base AgentHospitalError)
  health.py     # health check dos serviços
  cli.py        # CLI (comando ai-agent-hospital)
  main.py       # ponto de entrada que chama a CLI
tests/
docs/           # arquitetura, integração MCP e critérios de aceite
DEMO.md         # roteiro de demonstração
```

## Desenvolvimento

```bash
uv run pytest                                      # testes
uv run ruff check . && uv run ruff format --check . # lint e formatação
```

Os testes marcados com `integration` (`tests/test_db.py`) usam `TEST_DATABASE_URL` (ou `DATABASE_URL`)
e são pulados se o PostgreSQL não estiver acessível. Cada teste roda num schema temporário que é
apagado no fim, então é seguro apontá-los para o banco de desenvolvimento.

O teste de integração do LLM (`tests/test_llm.py`) é pulado se o Ollama não responder ou se o
`OLLAMA_MODEL` não estiver baixado; os demais simulam o Ollama e rodam offline. Para usar outro
modelo já baixado: `OLLAMA_MODEL=llama3.2:1b uv run pytest -m ollama`.

Os testes marcados com `dengue_mcp` (`tests/test_dengue_integration.py`) sobem o servidor MCP real do
smart_hospitals e são pulados se `SMART_HOSPITALS_PATH` não estiver definido; os de
`tests/test_mcp_client.py` usam um servidor falso e rodam sem ele. Só a integração:
`uv run pytest -m dengue_mcp`.

O agente (`tests/test_react_agent.py`) é testado com um LLM roteirizado e roda offline; só a
persistência entre reinícios é `integration`. `tests/test_agent_e2e.py` usa Ollama **e** o MCP real
(`-m "ollama and dengue_mcp"`) e checa comportamento (tool chamada, admitir falta de dado), não texto.

## Workflow de desenvolvimento (template)

O projeto foi criado a partir de um template de workflow com Claude Code.

Ponto de partida para novos projetos: PRD → backlog no Task Master → uma branch por tarefa →
plano aprovado → implementação → revisão → PR → decisões registradas no Basic Memory.

O guia completo, com o porquê de cada peça, está em `docs/guia-dev-workflow-claude-code.pdf`.

### Criar um projeto novo

```bash
scripts/new-project.sh ~/projetos/meu-app            # nome do projeto = nome da pasta
scripts/new-project.sh ~/projetos/meu-app meu_app    # ou um nome explícito
```

O script copia o template (sem histórico, segredos, memórias nem tarefas), registra o projeto
no Basic Memory, cria o `.env`, roda `git init -b main`, instala o pre-commit e faz o commit
inicial. Se você clonou o template por outro caminho (ex.: `gh repo create --template`),
rode só `scripts/setup.sh` na raiz do projeto novo.

### O que vem no template

| Arquivo | Papel |
|---|---|
| `CLAUDE.md` | Regras que o Claude Code carrega em toda sessão; importa o `dev-workflow.md` |
| `dev-workflow.md` | O passo a passo por tarefa. Preencha as convenções e os comandos do projeto |
| `.mcp.json` | MCPs do projeto: Task Master e Basic Memory |
| `.claude/settings.json` | Permissões: bloqueia `--no-verify`, push forçado e leitura do `.env` |
| `.pre-commit-config.yaml` | Bloqueia commit na `main` + checagens básicas; ative o hook de testes |
| `.taskmaster/` | Config do Task Master (claude-code + Perplexity) e template de PRD |
| `memories/` | Base do Basic Memory, versionada no Git |
| `scripts/` | `new-project.sh` e `setup.sh` |

### Pré-requisitos (uma vez por máquina)

Node 18+, `uv`, `git`, `gh` autenticado, Claude Code, e:

```bash
npm install -g task-master-ai
uv tool install basic-memory
uv tool install pre-commit
claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp
```
