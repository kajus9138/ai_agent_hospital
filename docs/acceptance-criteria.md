# Critérios de aceite do PRD

Situação dos critérios da seção 6 do PRD (`.taskmaster/docs/prd.txt`) ao fim da task 10, em
2026-10-27. O escopo da seção 4 (interação com o usuário, threads no PostgreSQL, MCP local de dengue)
está coberto pelas tasks 1 a 9; abaixo, a evidência de cada critério.

| Critério | Situação |
|---|---|
| O sistema DEVE comunicar-se com o MCP local | Atendido |
| A documentação DEVE estar informativa e organizada | Atendido |

## O sistema DEVE comunicar-se com o MCP local

O agente sobe o servidor MCP de dengue do
[smart_hospitals](https://github.com/kajus9138/smart_hospitals) como subprocesso e conversa com ele
via stdio (`mcp_client/client.py`). As tools são descobertas na conexão e usadas pelo agente ReAct.

Evidências:

- **Testes com o servidor real** (`uv run pytest -m dengue_mcp`, com `SMART_HOSPITALS_PATH`
  definido): conexão e listagem das tools, chamadas a `situacao_atual` e `tendencia`, erro de
  argumento inválido devolvido pelo protocolo, tools convertidas para o LangChain e diagnóstico de
  diretório errado. Resultado em 2026-10-27: 6 passed.
- **Ponta a ponta com o LLM** (`uv run pytest -m "ollama and dengue_mcp"`): o agente com Ollama
  chama a tool certa e admite quando o dado não existe. Resultado em 2026-10-27, com `qwen2.5`:
  5 passed, 1 xfailed. O xfail é conhecido e marcado no teste: perguntado sobre um recorte por bairro (Zona Leste), o modelo responde com os
  dados do município sem avisar que o recorte não existe.
- **Testes offline** (`tests/test_mcp_client.py`, `tests/test_bootstrap.py`): cliente, retry e
  montagem da sessão com um servidor MCP falso via stdio, rodando em qualquer máquina.
- **Health check**: `uv run ai-agent-hospital health` mostra `mcp  ok`.
- **Conversas reais**: as do [DEMO.md](../DEMO.md) foram gravadas com o stack local, usando as quatro
  tools (`situacao_atual`, `tendencia`, `serie_historica`, `comparativo_sazonal`).

## A documentação DEVE estar informativa e organizada

| Documento | Para quem | Conteúdo |
|---|---|---|
| [README.md](../README.md) | Quem vai rodar o projeto | Visão geral com diagrama, pré-requisitos, quick start, configuração, exemplos, CLI, uso como biblioteca, testes |
| [docs/architecture.md](architecture.md) | Quem vai manter ou estender | Componentes, montagem, loop ReAct, persistência das threads, erros e retries |
| [docs/mcp-integration.md](mcp-integration.md) | Quem vai configurar o servidor MCP | Pré-requisitos, variáveis, montagem do comando, tools, atualização dos dados, solução de problemas |
| [DEMO.md](../DEMO.md) | Quem vai apresentar a POC | Roteiro com conversas reais e o que destacar em cada uma |
| Docstrings em `src/ai_agent_hospital/` | Quem lê o código | Todas as funções, classes e métodos públicos documentados |

Evidências:

- O quick start do README foi seguido no ambiente de desenvolvimento até o `health` com os três
  serviços `ok` e um `chat` respondendo.
- `tests/test_docs.py` impede que a documentação se desatualize: toda variável lida em `config.py`
  precisa estar na tabela de configuração do README (e as do MCP no guia do MCP), e os links
  internos, inclusive âncoras, precisam resolver.
