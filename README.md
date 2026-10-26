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
cp .env.example .env    # ajuste OLLAMA_MODEL, OLLAMA_BASE_URL e DATABASE_URL
uv run ai-agent-hospital
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
