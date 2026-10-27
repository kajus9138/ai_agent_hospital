# ai_agent_hospital

POC de um agente ReAct para um tomador de decisão em um hospital inteligente. O agente usa um LLM
local servido pelo Ollama, guarda as threads de conversa no PostgreSQL e consulta um servidor MCP
local (via stdio) com dados de dengue em São Paulo.

**Stack:** Python 3.12 · LangGraph · langchain-ollama · langchain-mcp-adapters · PostgreSQL
(`langgraph-checkpoint-postgres` + psycopg 3) · uv · pytest · ruff

## Setup

Pré-requisitos: [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com/) rodando com o
modelo baixado (`ollama pull llama3.2`) e um PostgreSQL acessível.

```bash
uv sync                 # cria o .venv com Python 3.12 e instala as dependências
cp .env.example .env    # ajuste OLLAMA_*, DATABASE_URL e SMART_HOSPITALS_PATH
docker compose up -d    # PostgreSQL 16 local, com as mesmas credenciais do .env.example
uv run ai-agent-hospital
```

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

Os dados de dengue vêm do servidor MCP do projeto
[smart_hospitals](https://github.com/kajus9138/smart_hospitals), que **não** fica neste repo: clone-o
e aponte `SMART_HOSPITALS_PATH` para o clone no `.env`. O cliente sobe o servidor via stdio com
`MCP_SERVER_COMMAND` + `MCP_SERVER_ARGS` (padrão: `uv run --directory ${SMART_HOSPITALS_PATH}
dengue-mcp`). As tools (`situacao_atual`, `tendencia`, `serie_historica`, `comparativo_sazonal`)
são descobertas na conexão e convertidas para tools do LangChain.

Preparar o smart_hospitals (uma vez):

```bash
git clone https://github.com/kajus9138/smart_hospitals.git ~/smart_hospitals
cd ~/smart_hospitals && uv sync
ls data/dengue_sp_snapshot.csv     # snapshot do InfoDengue usado pelas tools
uv run dengue-mcp                  # deve subir e ficar esperando no stdio (Ctrl+C para sair)
```

Depois, no `.env` deste projeto: `SMART_HOSPITALS_PATH=/home/<você>/smart_hospitals`.

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

## Estrutura

```
src/ai_agent_hospital/
  agent/        # lógica do agente ReAct
  db/           # persistência das threads no PostgreSQL
  mcp_client/   # comunicação com o MCP local (stdio)
  config.py     # configurações via variáveis de ambiente / .env
  main.py       # ponto de entrada (comando ai-agent-hospital)
tests/
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
