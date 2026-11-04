"""Ontologias em YAML que entram no system prompt do agente.

O YAML vai ao prompt como está no arquivo, com os comentários, que também explicam o domínio; o
parse só valida o arquivo e acha o nome da ontologia.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ai_agent_hospital.errors import (
    OntologyDirectoryNotFoundError,
    OntologyFileNotFoundError,
    OntologyParseError,
)

# Relativo ao diretório de onde a aplicação roda, como o .env.
DEFAULT_ONTOLOGIES_DIR = "ontologies"
YAML_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True)
class Ontology:
    """Uma ontologia: `name` vem de `metadados.nome` (ou do arquivo); `content` é o YAML cru."""

    name: str
    content: str


def load_ontology(path: Path) -> Ontology:
    """Lê e valida um arquivo de ontologia; YAML inválido ou que não é mapeamento é erro."""
    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise OntologyParseError(path.name, exc) from exc
    if not isinstance(data, dict):
        raise OntologyParseError(
            path.name, ValueError("o conteúdo precisa ser um mapeamento (chave: valor)")
        )
    metadata = data.get("metadados")
    name = metadata.get("nome") if isinstance(metadata, dict) else None
    return Ontology(str(name or path.stem), content)


def load_ontologies(
    directory: str | None = None, names: Sequence[str] | None = None
) -> list[Ontology]:
    """Carrega as ontologias de `directory` (padrão `ontologies/`).

    `names` escolhe os arquivos, na ordem dada; sem ela, todos os .yaml/.yml em ordem alfabética.
    O diretório padrão pode não existir (sem ontologias); um diretório ou arquivo pedido de
    propósito precisa existir.
    """
    path = Path(directory or DEFAULT_ONTOLOGIES_DIR).expanduser()
    if not path.is_dir():
        if directory is None and not names:
            return []
        raise OntologyDirectoryNotFoundError(str(path))

    if names:
        files = [path / name for name in names]
        for file in files:
            if not file.is_file():
                raise OntologyFileNotFoundError(file.name, str(path))
    else:
        files = sorted(p for p in path.iterdir() if p.suffix in YAML_SUFFIXES and p.is_file())
    return [load_ontology(file) for file in files]
