"""LLM local servido pelo Ollama, exposto como chat model do LangChain."""

import logging

import httpx
import ollama
from langchain_ollama import ChatOllama

from ai_agent_hospital.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Temperatura baixa: o raciocínio ReAct precisa de respostas consistentes, não criativas.
DEFAULT_TEMPERATURE = 0.1


def get_llm(settings: Settings | None = None, **kwargs) -> ChatOllama:
    """Cria o ChatOllama com OLLAMA_MODEL e OLLAMA_BASE_URL das configurações.

    `kwargs` vão para o ChatOllama e sobrescrevem os padrões (ex.: `temperature=0`).
    """
    if settings is None:
        settings = get_settings()
    params = {
        "model": settings.ollama_model,
        "base_url": settings.ollama_base_url,
        "temperature": DEFAULT_TEMPERATURE,
    }
    return ChatOllama(**(params | kwargs))


def _with_tag(model: str) -> str:
    """Nome do modelo com tag explícita: o Ollama trata `llama3.2` como `llama3.2:latest`."""
    # Só a parte após a última "/" pode ter tag: em `registro:5000/modelo`, o ":" é da porta.
    return model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"


async def check_ollama_health(settings: Settings | None = None, timeout: float = 5.0) -> bool:
    """True se o Ollama responde e o modelo configurado já foi baixado (`ollama pull`)."""
    if settings is None:
        settings = get_settings()
    try:
        async with ollama.AsyncClient(host=settings.ollama_base_url, timeout=timeout) as client:
            response = await client.list()
    # ValueError: resposta 200 que não é do Ollama (JSON inválido, ValidationError do pydantic).
    except (ConnectionError, ollama.ResponseError, httpx.HTTPError, ValueError) as exc:
        logger.warning("Ollama indisponível em %s: %s", settings.ollama_base_url, exc)
        return False

    wanted = _with_tag(settings.ollama_model)
    if any(_with_tag(m.model or "") == wanted for m in response.models):
        return True
    logger.warning(
        "Modelo %s não encontrado no Ollama; rode `ollama pull %s`",
        settings.ollama_model,
        settings.ollama_model,
    )
    return False
