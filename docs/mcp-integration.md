# Integração com o servidor MCP de dengue (smart_hospitals)

Os dados de dengue que o agente consulta vêm de um servidor MCP **externo**, do projeto
[smart_hospitals](https://github.com/kajus9138/smart_hospitals). Ele não fica neste repositório: o
agente o inicia como subprocesso e conversa com ele pelo stdin/stdout (transporte stdio do MCP).
Este guia cobre como preparar o servidor, como o agente monta o comando, as tools disponíveis, como
atualizar os dados e o que fazer quando a conexão falha.

## Pré-requisitos

Uma vez por máquina:

```bash
git clone https://github.com/kajus9138/smart_hospitals.git ~/smart_hospitals
cd ~/smart_hospitals
uv sync                              # instala o servidor e suas dependências no .venv dele
ls data/dengue_sp_snapshot.csv       # snapshot do InfoDengue que as tools leem
uv run dengue-mcp                    # deve subir e ficar parado esperando no stdio (Ctrl+C sai)
```

O último comando é só um teste: no uso normal, quem inicia o servidor é o agente. Se ele não sobe à
mão, também não vai subir pelo agente.

Depois, no `.env` deste projeto:

```bash
SMART_HOSPITALS_PATH=/home/<você>/smart_hospitals
```

E confira: `uv run ai-agent-hospital health` deve mostrar `mcp  ok`.

## Variáveis de ambiente

| Variável | Padrão | Papel |
|---|---|---|
| `SMART_HOSPITALS_PATH` | (nenhum; obrigatória com o padrão de `MCP_SERVER_ARGS`) | Caminho do clone do smart_hospitals |
| `MCP_SERVER_COMMAND` | `uv` | Executável que sobe o servidor: um nome no `PATH` ou um caminho absoluto |
| `MCP_SERVER_ARGS` | `run --directory ${SMART_HOSPITALS_PATH} dengue-mcp` | Argumentos do comando, numa string |

Deixe `MCP_SERVER_ARGS` comentado no `.env` (como no `.env.example`): o python-dotenv expande
`${...}` ao ler o `.env` e troca variável ausente por string vazia, mesmo entre aspas, o que
esconderia um `SMART_HOSPITALS_PATH` faltando. O padrão já vive no `config.py`, e quem expande o
placeholder é o cliente, com as validações abaixo.

### Como o comando é montado

`DengueMCPClient` (`src/ai_agent_hospital/mcp_client/client.py`) transforma as variáveis no
subprocesso assim:

1. `SMART_HOSPITALS_PATH` vira caminho absoluto (`~` expandido). Ele é usado duas vezes, no
   `--directory` e como diretório de trabalho do subprocesso; relativo, seria resolvido duas vezes.
2. `MCP_SERVER_ARGS` é dividido com `shlex.split` (aspas funcionam como no shell) e **só depois** o
   `${SMART_HOSPITALS_PATH}` é substituído em cada argumento: um caminho com espaços continua sendo
   um argumento só.
3. Antes de iniciar qualquer coisa, o cliente valida a configuração: placeholder sem
   `SMART_HOSPITALS_PATH`, comando fora do `PATH` ou diretório inexistente dão erro na hora, com a
   correção na mensagem.
4. O subprocesso recebe um ambiente **filtrado** (o padrão do SDK do MCP: `PATH`, `HOME`, `USER`...)
   mais `SMART_HOSPITALS_PATH`. Segredos do `.env` deste projeto, como o `DATABASE_URL`, não vazam
   para ele.

Com os padrões e `SMART_HOSPITALS_PATH=~/smart_hospitals`, o resultado é
`uv run --directory /home/<você>/smart_hospitals dengue-mcp`.

Para usar outro executável (ex.: o Python do venv do smart_hospitals, sem passar pelo uv):

```bash
MCP_SERVER_COMMAND=/home/<você>/smart_hospitals/.venv/bin/python
MCP_SERVER_ARGS=-m smart_hospitals.mcp_server
```

## Ciclo de vida da conexão

- **Abertura com retry**: até 3 tentativas, com espera de 1 s e depois 2 s (backoff exponencial).
  Cada tentativa tem 30 s para o handshake (`initialize`). Esgotadas, sai um `MCPConnectionError`
  com o comando completo para você testar à mão.
- **Uma sessão por execução**: o `chat` abre o servidor uma vez e o mantém até sair. O `health` faz
  uma tentativa só (mostra o estado atual, não espera o servidor se recuperar).
- **Sem reconexão no meio da conversa**: se o servidor morre durante uma chamada, a tool falha com
  `ToolExecutionError`. O `chat` continua aberto, mas toda pergunta que precisar de dados vai falhar
  do mesmo jeito: saia (`sair`) e retome a thread com `chat --thread <id>`, que sobe um servidor novo.
  O histórico até ali fica salvo.
- **Mesma task asyncio**: o transporte stdio usa cancel scopes do anyio, então quem abre o cliente
  precisa fechá-lo na mesma task (`async with DengueMCPClient.from_settings() as client:`). O
  `bootstrap.open_session` já cuida disso, inclusive no Ctrl+C e no SIGTERM, que encerram o
  subprocesso antes de sair.

## Tools disponíveis

As tools **não** estão fixas no código: o agente as descobre na conexão (`list_tools`) e as converte
para tools do LangChain com `langchain_mcp_adapters` (`mcp_client/tools.py`). O modelo recebe nome,
descrição e schema de cada uma direto do servidor; o prompt do agente não as repete, para não ficar
desatualizado. A fonte da verdade é a
[seção MCP server do README do smart_hospitals](https://github.com/kajus9138/smart_hospitals#mcp-server);
o resumo abaixo é da versão usada no desenvolvimento.

| Tool | Parâmetros | Retorno |
|---|---|---|
| `situacao_atual` | nenhum | Última semana epidemiológica (SE): casos notificados, `casos_est` (nowcast, com mín./máx.), incidência por 100 mil, nível de alerta, Rt, p_rt1, variação semanal |
| `tendencia` | `semanas` (1-52, padrão 4) | Indicadores das últimas N semanas e um resumo `alta` / `estavel` / `queda` |
| `serie_historica` | `inicio`, `fim` (SE como `202401` ou data `2024-01-01`) | Série semanal no intervalo |
| `comparativo_sazonal` | `semana` (1-53, padrão: a mais recente) | A mesma SE nos anos anteriores (média, mín., máx.) |

Toda resposta traz `data_referencia`, a semana mais recente do snapshot; o prompt pede ao agente que
a cite. Os dados são do município de São Paulo como um todo: não há recorte por bairro nem dados de
leitos, e o agente é instruído a dizer isso em vez de inventar.

Quando uma tool devolve erro pelo protocolo (`isError`, ex.: `semanas=99` na `tendencia`), o erro volta
ao modelo como resposta da tool, e ele pode corrigir os argumentos e tentar de novo. A CLI mostra um
aviso amarelo nesse caso.

## Atualizar os dados

O servidor lê só o arquivo `data/dengue_sp_snapshot.csv` do smart_hospitals, gerado a partir da API
pública do InfoDengue. Para atualizá-lo:

```bash
cd ~/smart_hospitals
uv run python scripts/extract_infodengue.py   # sobrescreve o CSV; opções: --output, --ey-end
git diff --stat data/                         # confira o que mudou
```

O snapshot é carregado quando o servidor sobe. Como o agente inicia um servidor novo a cada `chat`,
basta **sair e abrir o chat de novo** depois de atualizar. O procedimento completo (e o que revisar
no CSV) está no
[README do smart_hospitals](https://github.com/kajus9138/smart_hospitals#atualizar-o-snapshot-de-dados).

## Solução de problemas

Comece por `uv run ai-agent-hospital health`. Se o `mcp` estiver `indisponível`, a linha acima da
tabela traz o motivo. As mensagens e o que fazer (o `health` faz uma tentativa só, então mostra
`após 1 tentativa(s)`; o `chat` faz 3):

| Mensagem | Causa | O que fazer |
|---|---|---|
| `MCP_SERVER_ARGS usa ${SMART_HOSPITALS_PATH}, mas SMART_HOSPITALS_PATH não foi definido` | Variável ausente ou vazia no `.env` | Defina `SMART_HOSPITALS_PATH` com o caminho do clone |
| `Diretório não encontrado: ...` | Caminho errado (ou o `.env.example` copiado sem ajuste, `/path/to/smart_hospitals`) | Corrija o caminho; `ls $SMART_HOSPITALS_PATH/pyproject.toml` deve existir |
| `Comando 'uv' não encontrado no PATH` | uv não instalado, ou fora do `PATH` do processo | Instale o uv ou use o caminho absoluto em `MCP_SERVER_COMMAND` (`which uv`) |
| `MCP_SERVER_ARGS inválido: No closing quotation` (no `health`, só `No closing quotation`) | Aspas sem fechar em `MCP_SERVER_ARGS` | Corrija as aspas, ou volte a deixar a variável comentada |
| `Não foi possível conectar ao servidor MCP após N tentativa(s): ...` | O processo sobe mas morre, ou não responde ao handshake em 30 s | Rode à mão o comando citado na mensagem; erros comuns: `uv sync` não rodado no smart_hospitals, CSV ausente, `dengue-mcp` inexistente (clone desatualizado: `git pull`) |
| `A tool '...' falhou fora do protocolo MCP` | O servidor caiu durante a conversa | Saia (`sair`) e retome a conversa com `chat --thread <id>` |

Outras verificações:

- **Rodar o servidor como o agente roda**: copie o comando da mensagem de erro e rode-o num terminal.
  Ele deve ficar parado (está esperando JSON-RPC no stdin); qualquer traceback é o problema.
- **Inspecionar as tools no navegador**: no smart_hospitals,
  `uv run mcp dev src/smart_hospitals/mcp_server/server.py`.
- **Logs do servidor**: cada chamada é registrada no stderr do servidor (tool, parâmetros, duração e
  status). O stdout é do protocolo; um `print` nele quebra a comunicação.
- **Teste de integração**: `uv run pytest -m dengue_mcp` sobe o servidor real, lista as tools,
  chama `situacao_atual` e `tendencia` e confere o erro de argumento inválido. É pulado se `SMART_HOSPITALS_PATH` não estiver definido.
