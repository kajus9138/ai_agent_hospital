# Claude Code Instructions

## Workflow do projeto
Este projeto segue o fluxo definido em `dev-workflow.md`. Siga-o em toda tarefa.
@./dev-workflow.md

## Regras inegociáveis
- Nunca commitar direto na `main` e nunca usar `--no-verify`.
- Decisões de arquitetura, convenções e lições aprendidas vão no **Basic Memory** (pasta `memories/`,
  versionada no Git), nunca na memória local do Claude Code.
- Nunca editar à mão `.taskmaster/tasks/tasks.json` nem `.taskmaster/config.json`; use o `task-master`.

## Task Master (resumo)
- `task-master next` / `task-master show <id>`: próxima tarefa e seus detalhes
- `task-master set-status --id=<id> --status=in-progress|done`
- `task-master update-subtask --id=<id> --prompt="notas de implementação"`
- PRD → backlog: `parse-prd .taskmaster/docs/prd.txt` → `analyze-complexity --research` → `expand --all`
- Referência completa (ler só quando precisar): `.taskmaster/CLAUDE.md`
