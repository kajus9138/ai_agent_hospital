"""Ponto de entrada da aplicação."""

from ai_agent_hospital.config import get_settings


def main() -> None:
    settings = get_settings()
    print(f"ai_agent_hospital — modelo {settings.ollama_model} em {settings.ollama_base_url}")


if __name__ == "__main__":
    main()
