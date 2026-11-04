"""Prompts do agente.

As tools não são descritas aqui: o modelo recebe os schemas descobertos no servidor MCP, e
duplicá-los no prompt faria o texto ficar desatualizado quando o servidor mudar.
"""

import logging
from collections.abc import Sequence

from ai_agent_hospital.agent.ontology import Ontology

logger = logging.getLogger(__name__)

# Medido com o qwen2.5 na ontologia de dengue (YAML em português): ~2,98 caracteres por token.
CHARS_PER_TOKEN = 3

HOSPITAL_SYSTEM_PROMPT = """\
Você é um assistente de apoio à decisão para hospitais inteligentes em São Paulo.
Você ajuda gestores e tomadores de decisão a monitorar a situação epidemiológica da dengue
e antecipar demandas no sistema de saúde.

## Escopo dos Dados
Os dados disponíveis são indicadores epidemiológicos de dengue do município de São Paulo
como um todo, provenientes do InfoDengue. Os dados incluem casos notificados, casos estimados,
incidência, tendências e comparativos sazonais.

**Indisponível:**
- Dados de capacidade hospitalar, leitos ou ocupação
- Recorte por bairro, distrito, zona ou região
- Dados de outros municípios além de São Paulo capital
- Recursos humanos ou insumos hospitalares

## Orientações de Uso
1. Sempre cite a data ou semana epidemiológica de referência retornada pelas ferramentas ao
apresentar dados.
2. Ao fazer recomendações (ex: reforçar triagem, antecipar estoques), baseie-se nos indicadores
retornados e explicite o raciocínio.
3. Quando o usuário perguntar sobre algo FORA do escopo dos dados disponíveis, informe claramente
que essa informação não está disponível. NUNCA invente dados.
4. Se a pergunta pedir um recorte indisponível (ex.: um bairro ou zona da cidade), comece dizendo
que esse recorte não está disponível; só então, se útil, apresente os dados do município como um
todo, deixando claro que não são específicos daquele recorte.
5. Responda sempre em português.
6. Raciocine passo a passo antes de executar ações.
"""

ONTOLOGIES_INTRO = """\
## Ontologias
As ontologias abaixo (YAML) descrevem os conceitos do domínio e como interpretar os valores
retornados pelas ferramentas. Use-as para entender e explicar os dados; os valores atuais vêm sempre
das ferramentas, nunca das ontologias."""


def build_system_prompt(ontologies: Sequence[Ontology] = ()) -> str:
    """Prompt do hospital seguido das ontologias; sem ontologias, é o HOSPITAL_SYSTEM_PROMPT."""
    if not ontologies:
        return HOSPITAL_SYSTEM_PROMPT
    sections = [f"### {o.name}\n```yaml\n{o.content.rstrip()}\n```" for o in ontologies]
    return HOSPITAL_SYSTEM_PROMPT + "\n" + "\n\n".join([ONTOLOGIES_INTRO, *sections]) + "\n"


def estimate_tokens(text: str) -> int:
    """Estimativa de tokens pelo tamanho do texto; boa o bastante para avisar de contexto."""
    return len(text) // CHARS_PER_TOKEN


def log_prompt_size(prompt: str, num_ctx: int) -> int:
    """Registra o tamanho do prompt e avisa se ele passa de metade do contexto do modelo.

    A outra metade fica para os schemas das tools, o histórico da thread e a resposta; além do
    contexto, o Ollama corta o prompt sem erro.
    """
    tokens = estimate_tokens(prompt)
    logger.info(
        "System prompt: %d caracteres, ~%d tokens (contexto do modelo: %d)",
        len(prompt),
        tokens,
        num_ctx,
    )
    if tokens > num_ctx // 2:
        logger.warning(
            "O system prompt (~%d tokens) passa de metade do contexto do modelo (%d tokens): "
            "sobra pouco para tools e histórico. Aumente OLLAMA_NUM_CTX ou carregue menos "
            "ontologias.",
            tokens,
            num_ctx,
        )
    return tokens
