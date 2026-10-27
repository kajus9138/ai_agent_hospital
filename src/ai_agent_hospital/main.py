"""Ponto de entrada da aplicação: a CLI."""

from ai_agent_hospital.cli import app


def main() -> None:
    """Roda a CLI (o mesmo que o comando `ai-agent-hospital`)."""
    app()


if __name__ == "__main__":
    main()
