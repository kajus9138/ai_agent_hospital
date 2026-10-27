# Roteiro de demonstração

Roteiro para apresentar a POC a gestores: um agente que responde perguntas sobre a dengue em São
Paulo consultando dados reais (InfoDengue) por um servidor MCP local, com um LLM que roda na própria
máquina. Cada conversa abaixo mostra uma capacidade; as respostas são **transcrições reais**, gravadas
em 2026-10-27 com o modelo `qwen2.5` e o snapshot de referência **2026-10-04 (SE 40/2026)**.

O texto do LLM muda de uma execução para outra (e com outro snapshot, os números também). O que se
repete é o comportamento: qual tool o agente consulta e se ele se mantém nos dados.

## Antes de apresentar

```bash
docker compose up -d                      # PostgreSQL
ollama pull qwen2.5                       # e OLLAMA_MODEL=qwen2.5 no .env
uv run ai-agent-hospital health           # ollama, database e mcp: ok
uv run ai-agent-hospital chat             # conversa nova
```

- Rode uma pergunta de aquecimento antes do público entrar: a primeira resposta carrega o modelo na
  memória e pode levar bem mais tempo.
- Cada resposta leva de 30 s a 2 min numa máquina sem GPU dedicada. Use a espera para narrar as linhas
  `→ consultando ...`: é o agente decidindo que dado buscar.
- Confira a data do snapshot: a resposta de `situacao_atual` traz `data_referencia`. Para dados mais
  novos, veja [Atualizar os dados](docs/mcp-integration.md#atualizar-os-dados).

## 1. Situação atual

**Mostra:** o agente escolhe a tool sozinho e cita a semana de referência.

```text
Você: Qual a situação atual da dengue em São Paulo?
→ consultando situacao_atual()
```

> A situação atual da dengue em São Paulo na semana epidemiológica mais recente (referência:
> 2026-10-04) é como segue:
>
> - **Casos Notificados**: 352
> - **Casos Estimados (Nowcast)**: 1.161 (com intervalo de confiança mínimo de 582 e máximo de 3.114)
> - **Incidência por 100 mil habitantes**: 9,52
> - **Nível de Alerta**: Laranja
> - **Rt (Taxa de Reprodução)**: 0,98
> - **Probabilidade de Rt > 1 (p_rt1)**: 33,78%
> - **Variação Semanal dos Casos Estimados**: -13,6%
>
> O nível laranja indica que há uma situação de alerta, mas a taxa de reprodução está abaixo de 1,
> sugerindo uma tendência decrescente. [...]

**Para destacar:** os números vêm da tool, não do modelo. A leitura "tendência decrescente" se apoia
só na última semana; a conversa 2 mostra o quadro mais amplo.

## 2. Tendência

**Mostra:** a tool com parâmetro (`semanas`), preenchido a partir da pergunta.

```text
Você: Como está a tendência da dengue nas últimas 4 semanas?
→ consultando tendencia(semanas=4)
```

> Na última análise das últimas 4 semanas, observamos a seguinte tendência:
>
> - **Semana Epidemiológica (SE) 202637**: Casos estimados: 1047, Rt: 1.008, p_rt1: 57.37%
> - **Semana Epidemiológica (SE) 202638**: Casos estimados: 1207, Rt: 1.174, p_rt1: 99.99%
> - **Semana Epidemiológica (SE) 202639**: Casos estimados: 1344, Rt: 1.240, p_rt1: 99.99%
> - **Semana Epidemiológica (SE) 202640**: Casos estimados: 1161, Rt: 0.983, p_rt1: 33.78%
>
> A tendência resumida é **alta**, pois o Rt médio foi superior a 1,1 e a probabilidade de Rt > 1
> (p_rt1) também foi alta.
>
> Com base nesses dados, recomendo que sejam reforçadas as medidas preventivas e de controle da
> dengue, bem como preparados os sistemas de saúde para possíveis aumentos na demanda.

(Resposta resumida: o agente também listou o nível de alerta de cada semana.)

**Para destacar:** três semanas de alta seguidas de uma queda. Isso explica a aparente contradição com
a conversa 1 e é o tipo de nuance que um gestor precisa ver.

## 3. Série histórica (e autocorreção)

**Mostra:** o ciclo ReAct de verdade. O agente erra o formato do parâmetro, recebe o erro da tool,
corrige e tenta de novo, sem intervenção.

```text
Você: Mostre a série histórica de casos de dengue de julho a setembro de 2026.
→ consultando serie_historica(fim='20260930', inicio='20260701')
  serie_historica devolveu erro; o agente vai considerar isso.
→ consultando serie_historica(fim='20260930', inicio='20260701')
  serie_historica devolveu erro; o agente vai considerar isso.
→ consultando serie_historica(fim='202639', inicio='202628')
```

O erro da tool foi `Valor inválido '20260701': use SE (AAAASS) ou data (AAAA-MM-DD)`. Na terceira
tentativa o agente passou a usar semanas epidemiológicas:

> Aqui está a série histórica de casos de dengue no período de julho a setembro de 2026:
>
> | SEMANA EPI | CASOS NOTIFICADOS | CASOS ESTIMADOS (NOWCAST) | Rt | NÍVEL DE ALERTA |
> |---|---|---|---|---|
> | 28/2026 | 1,085 | 1,085 | 0.837 | 1 |
> | 29/2026 | 1,119 | 1,119 | 0.964 | 1 |
> | ... | | | | |
> | 38/2026 | 1,077 | 1,207 | 1.174 | 1 |
> | 39/2026 | 1,058 | 1,344 | 1.240 | 3 |

(Tabela resumida: a original tem as 12 semanas e o intervalo mínimo/máximo do nowcast.)

**Para destacar:** a autocorreção. Também vale notar que nas semanas recentes o nowcast (casos
estimados) fica acima dos notificados: são casos que ainda vão ser registrados.

## 4. Comparativo sazonal

**Mostra:** contexto histórico: o número atual é alto ou normal para a época?

```text
Você: A semana 40 de 2026 está acima ou abaixo do normal, comparada com a mesma semana dos anos anteriores?
→ consultando comparativo_sazonal(semana=40)
```

> A semana 40 de 2026 teve um número de casos estimados de 1.161, que está acima da média histórica
> para essa semana, que é de aproximadamente 549,9 casos.
>
> O intervalo mínimo e máximo dos anos anteriores foram de 57 a 3.238 casos, respectivamente. Embora
> o valor atual seja bem acima da média, ele está dentro do intervalo histórico observado nos anos
> anteriores. [...]

**Atenção ao formular:** cite a semana (ou pergunte isso depois da conversa 1, na mesma thread). Com
"esta semana" ou "a semana mais recente" sem contexto, o `qwen2.5` chamou
`comparativo_sazonal(semana=52)` nos testes e leu o mínimo histórico como se fosse o valor atual. Veja
[Limitações observadas](#limitações-observadas).

## 5. Fora do escopo

**Mostra:** o agente não inventa dados que não tem.

```text
Você: Quantos leitos estão ocupados no Hospital das Clínicas por causa da dengue?
```

> Desculpe, mas os dados disponíveis não incluem informações sobre a capacidade hospitalar ou a
> ocupação de leitos específicos para casos de dengue. [...]
>
> No entanto, posso fornecer informações epidemiológicas relevantes sobre a situação da dengue em São
> Paulo. Gostaria que eu verificasse isso para você?

**Para destacar:** nenhuma tool foi chamada e nenhum número inventado. O prompt do agente lista o que
não está disponível (leitos, bairros, outros municípios, insumos).

## 6. Decisão em várias etapas (multi-turno)

**Mostra:** o agente combina várias tools para apoiar uma decisão e usa o contexto da conversa na
pergunta seguinte.

```text
Você: Preciso decidir se reforço a triagem de dengue no pronto-socorro nas próximas semanas. Antes
      de recomendar, consulte a situação atual, a tendência das últimas 4 semanas e o comparativo
      com anos anteriores.
→ consultando situacao_atual()
→ consultando tendencia(semanas=4)
```

> A tendência das últimas 4 semanas é de **alta**:
>
> - **Rt médio**: 1.1
> - **Probabilidade de Rt > 1 (p_rt1) médio**: 73%
>
> [...] Por fim, vamos fazer o **comparativo sazonal** para entender como esta semana se compara com
> as mesmas semanas nos anos anteriores:

O primeiro turno parou ao anunciar o comparativo, sem chamá-lo. A pergunta seguinte, na mesma
thread, completa o raciocínio:

```text
Você: Na última semana o Rt ficou abaixo de 1. Isso muda a sua recomendação?
→ consultando comparativo_sazonal(semana=40)
```

> [...] **Conclusão e Recomendação**
>
> A situação atual indica que a dengue está em nível de alerta laranja, com uma tendência de alta na
> transmissão. Apesar do Rt atual estar abaixo de 1, a probabilidade de Rt > 1 é alta (73%), o que
> sugere um risco potencial de aumento da transmissão nas próximas semanas.
>
> **Recomendação:** Reforce a triagem de dengue no pronto-socorro nas próximas semanas. [...]

**Para destacar:** desta vez o agente acertou a semana (40), porque a situação atual já estava no
histórico da conversa, e a recomendação junta as três fontes. Um ponto para discutir com a plateia:
os 73% são a média das 4 semanas, não da última (33,8%); conferir o raciocínio do agente faz parte do
uso.

## 7. Threads: retomar e bifurcar

As conversas ficam no PostgreSQL e sobrevivem a reinícios. Depois de sair do chat (`sair`):

```bash
uv run ai-agent-hospital threads                 # lista, com a última mensagem
uv run ai-agent-hospital history <id>            # mensagens numeradas, com as tools chamadas
uv run ai-agent-hospital chat --thread <id>      # continua de onde parou
uv run ai-agent-hospital fork <id> --from 4      # nova thread a partir da mensagem 4
```

**Sugestão:** depois da conversa 6, faça um `fork` logo após a primeira resposta e, na thread nova,
pergunte por outro caminho (ex.: "E se a próxima semana repetir o Rt de 0,98?"). A conversa original
continua intacta.

## Limitações observadas

Registradas nas gravações deste roteiro, com `qwen2.5`:

- **Parâmetro opcional preenchido sem necessidade**: para "a semana mais recente", o modelo passou
  `semana=52` em vez de omitir o parâmetro (cujo padrão é a semana mais recente). Com a semana
  explícita ou o contexto da conversa, acerta.
- **Turno que para antes da última tool**: às vezes o modelo anuncia "vamos consultar..." e encerra
  o turno. Uma pergunta de seguimento retoma.
- **Leitura dos números**: o modelo pode misturar médias e valores pontuais (ex.: p_rt1 médio vs. da
  última semana). Os dados das tools estão sempre visíveis no `history`.
- **Recorte por bairro**: perguntado sobre a Zona Leste, o modelo responde com os dados do
  município sem avisar que não há recorte regional (falha conhecida, marcada como `xfail` em
  `tests/test_agent_e2e.py`). Evite essa pergunta ou use-a para discutir limites do modelo.
- **Modelos menores** (`llama3.2`, `llama3.2:1b`) erram com mais frequência ao chamar tools; para
  apresentar, prefira o `qwen2.5`.
