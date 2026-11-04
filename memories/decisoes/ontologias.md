---
title: Ontologias no prompt do agente
type: note
permalink: decisoes/ontologias
tags:
- decisao
- ontologia
- prompt
---

# Ontologias no prompt do agente

Decisões tomadas na tarefa 11 (base das ontologias), em 2026-11-04. PRD em
`.taskmaster/docs/prd-ontologias.txt`; backlog nas tarefas 11, 15, 18 e 20.

## Contexto
Somar ao system prompt ontologias em YAML (a primeira é `dengue_sp.yaml`, ~14 KB, ~4 mil tokens, que
diz como interpretar os valores das tools do MCP de dengue). Outras ontologias devem entrar sem mudar
código.

## Observations
- [decisao] Ontologias ficam em `ontologies/` na raiz, versionadas; o YAML entra no prompt como está, sem resumo #ontologia
- [decisao] `Settings.ontologies_dir: str | None`: None = padrão `ontologies/`, que pode não existir (sem ontologias, prompt igual ao de antes); diretório definido em `ONTOLOGIES_DIR` precisa existir #config
- [decisao] `Settings.ontologies: tuple[str, ...] | None` (tupla porque `Settings` é frozen); `ONTOLOGIES` vazia ou só com vírgulas vira None = todos os `.yaml` #config
- [decisao] `errors.py`: base `OntologyError(AgentHospitalError)` para a CLI tratar as falhas de carregamento juntas; derivados de diretório, arquivo e YAML inválido #erros
- [decisao] `pyyaml` declarado como dependência direta (antes só transitiva); usar `yaml.safe_load` #ontologia
- [convencao] Variável nova no `config.py` exige linha na tabela do README no mesmo PR: `tests/test_docs.py` falha sem ela #docs
- [alternativa-descartada] Backlog com 10 tarefas geradas pelo parse: agrupado em 4 com `task-master move` (tarefas viraram subtarefas) e testes junto de cada tarefa, não numa tarefa de testes no fim #taskmaster
- [licao] Depois de `task-master move`, as dependências continuam apontando para os IDs antigos; corrigir com `remove-dependency`/`add-dependency` e conferir com `validate-dependencies` #taskmaster
- [licao] O hook de testes do pre-commit roda com o que não está no stage guardado, mas arquivos não versionados ficam: commit só do backlog quebrou porque `tests/test_ontology.py` (não versionado) importava erros ainda fora do stage. Commitar o código antes #git
- [pendencia] Limite de tamanho do prompt com modelos locais pequenos: nesta versão só log (tarefa 15) #ollama

## Relations
- part_of [[ai_agent_hospital]]
- extends [[Agente ReAct com LangGraph]]
