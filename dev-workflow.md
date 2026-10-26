# dev-workflow.md

O agente DEVE seguir estas etapas em toda tarefa.

## 1. Entender
- Ler a tarefa: `task-master show <id>`. Se os critérios de aceite estiverem vagos, perguntar antes de seguir.
- Buscar contexto:
  - Decisões e convenções do projeto no Basic Memory (`search_notes`, `build_context`)
  - Documentação atual de bibliotecas via Context7 (nunca confiar só na memória do modelo para APIs)
  - Uso real em outros projetos via Octocode, quando for útil comparar abordagens

## 2. Preparar
- Árvore limpa: `git status`
- Uma branch por tarefa: `git checkout -b feat/<id>-<descricao-curta>` (ou `fix/`, `chore/`)
- `task-master set-status --id=<id> --status=in-progress`
- Rodar os testes antes de mexer, para saber o ponto de partida: `uv run pytest`

## 3. Planejar
- Apresentar um plano (arquivos afetados, abordagem, testes) e esperar aprovação antes de escrever código.
  No Claude Code, use o plan mode (Shift+Tab).

## 4. Implementar
- Em passos pequenos, com testes junto do código.
- Registrar o progresso: `task-master update-subtask --id=<id> --prompt="o que funcionou / o que não"`

## 5. Validar
- Testes: `uv run pytest`
- Lint e tipos: `uv run ruff check . && uv run ruff format --check .`
- Revisar o diff com `/code-review` antes de commitar.

## 6. Entregar
- Commits em Conventional Commits, citando a tarefa: `feat: <resumo> (task <id>)`
- Abrir o PR com `gh pr create`.

## 7. Registrar
- Decisões relevantes no Basic Memory: decisão + contexto + alternativas descartadas.
- Atualizar o README se o uso mudou.
- `task-master set-status --id=<id> --status=done`

## Convenções do projeto
- Linguagem: Python 3.12
- Gestor de pacotes: uv (`uv.lock` versionado)
- Testes: pytest + pytest-asyncio (`tests/`)
- Lint/format: ruff (`ruff check` + `ruff format`)
- Commits: Conventional Commits

## Comandos essenciais
- Testes: `uv run pytest`
- Lint: `uv run ruff check .`
- Formatação: `uv run ruff format .`
- Build: `uv build`
