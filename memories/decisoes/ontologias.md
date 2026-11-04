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

Decisões tomadas nas tarefas 11 (base) e 15 (carregamento e prompt), em 2026-11-04. PRD em
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
- [decisao] `agent/ontology.py`: `load_ontologies(dir, names)`; `ontologies/` padrão é relativo ao cwd (como o `.env`); `names` na ordem dada, sem ela `.yaml`/`.yml` em ordem alfabética #ontologia
- [decisao] YAML vazio, que não é mapeamento ou não está em UTF-8 também é `OntologyParseError` #ontologia
- [decisao] `prompts.build_system_prompt`: sem ontologias devolve o `HOSPITAL_SYSTEM_PROMPT` exato; com elas, `## Ontologias` (os valores atuais vêm das tools, nunca da ontologia) + `### nome` + YAML verbatim #prompt
- [licao] O Ollama sem GPU roda com contexto padrão de 4096 tokens (`ollama ps`, coluna CONTEXT) e corta o prompt sem erro; a ontologia de dengue sozinha tem 4545 tokens no qwen2.5 (~2,98 caracteres/token) #ollama
- [decisao] `OLLAMA_NUM_CTX` (padrão 16384) repassado como `num_ctx` ao `ChatOllama`; no qwen2.5 7B o cache de 16k custa ~1 GB de RAM #ollama
- [alternativa-descartada] Documentar só `OLLAMA_CONTEXT_LENGTH` no `ollama serve`: depende de quem sobe o servidor #ollama
- [decisao] `log_prompt_size`: estimativa `len // 3`; WARNING acima de metade do `num_ctx` (o resto é para tools, histórico e resposta), em vez de um limite fixo de 8000 tokens #prompt
- [licao] Não editar arquivos com a suíte rodando: o `tests/test_docs.py` lê o fonte do `config.py` com `inspect.getsource`, que pega as linhas erradas se o arquivo mudou depois do import #testes

## Relations
- part_of [[ai_agent_hospital]]
- extends [[Agente ReAct com LangGraph]]
