"""Ontologias em YAML que entram no system prompt do agente."""

from pathlib import Path

import pytest
import yaml

from ai_agent_hospital.agent.ontology import Ontology, load_ontologies, load_ontology
from ai_agent_hospital.errors import (
    AgentHospitalError,
    OntologyDirectoryNotFoundError,
    OntologyError,
    OntologyFileNotFoundError,
    OntologyParseError,
)

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGIES = ROOT / "ontologies"


def test_initial_ontology_is_valid_yaml():
    data = yaml.safe_load((ONTOLOGIES / "dengue_sp.yaml").read_text(encoding="utf-8"))
    assert data["metadados"]["nome"] == "ontologia-dengue-sp"
    assert not (ROOT / "dengue_sp.yaml").exists()


@pytest.mark.parametrize(
    ("error", "attrs"),
    [
        (OntologyDirectoryNotFoundError("/srv/ontologias"), {"path": "/srv/ontologias"}),
        (
            OntologyFileNotFoundError("leitos.yaml", "ontologies"),
            {"filename": "leitos.yaml", "directory": "ontologies"},
        ),
        (OntologyParseError("ruim.yaml", yaml.YAMLError("linha 3")), {"filename": "ruim.yaml"}),
    ],
)
def test_ontology_errors(error, attrs):
    # A CLI captura AgentHospitalError; OntologyError agrupa as falhas de carregamento.
    assert isinstance(error, OntologyError)
    assert isinstance(error, AgentHospitalError)
    for name, value in attrs.items():
        assert getattr(error, name) == value
        assert value in str(error)


def test_parse_error_keeps_the_cause():
    assert "linha 3" in str(OntologyParseError("ruim.yaml", yaml.YAMLError("linha 3")))


ONTOLOGY_YAML = """\
# Comentário que também vai ao prompt.
metadados:
  nome: ontologia-teste
conceitos:
  - id: leito
"""


def write(directory: Path, name: str, content: str = ONTOLOGY_YAML) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_ontology_name_from_metadata(tmp_path):
    ontology = load_ontology(write(tmp_path, "a.yaml"))
    assert ontology == Ontology("ontologia-teste", ONTOLOGY_YAML)


@pytest.mark.parametrize("content", ["conceitos: []\n", "metadados: sem-nome\n"])
def test_load_ontology_name_falls_back_to_filename(tmp_path, content):
    assert load_ontology(write(tmp_path, "leitos.yaml", content)).name == "leitos"


@pytest.mark.parametrize("content", ["chave: [aberta\n", "- só uma lista\n", "", "\xff"])
def test_load_ontology_invalid(tmp_path, content):
    path = tmp_path / "ruim.yaml"
    path.write_bytes(content.encode("latin-1"))
    with pytest.raises(OntologyParseError) as exc_info:
        load_ontology(path)
    assert exc_info.value.filename == "ruim.yaml"


def test_load_ontologies_default_dir_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_ontologies() == []


def test_load_ontologies_default_dir(tmp_path, monkeypatch):
    (tmp_path / "ontologies").mkdir()
    write(tmp_path / "ontologies", "a.yaml")
    monkeypatch.chdir(tmp_path)
    assert [o.name for o in load_ontologies()] == ["ontologia-teste"]


@pytest.mark.parametrize("names", [None, ("a.yaml",)])
def test_load_ontologies_explicit_dir_missing(tmp_path, names):
    with pytest.raises(OntologyDirectoryNotFoundError):
        load_ontologies(str(tmp_path / "nao-existe"), names)


def test_load_ontologies_default_dir_missing_with_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OntologyDirectoryNotFoundError):
        load_ontologies(None, ("a.yaml",))


def test_load_ontologies_listed_file_missing(tmp_path):
    write(tmp_path, "a.yaml")
    with pytest.raises(OntologyFileNotFoundError) as exc_info:
        load_ontologies(str(tmp_path), ("a.yaml", "b.yaml"))
    assert exc_info.value.filename == "b.yaml"


def test_load_ontologies_all_yaml_sorted(tmp_path):
    write(tmp_path, "b.yml", "metadados: {nome: b}\n")
    write(tmp_path, "a.yaml", "metadados: {nome: a}\n")
    write(tmp_path, "notas.txt", "não é ontologia")
    (tmp_path / "pasta.yaml").mkdir()
    assert [o.name for o in load_ontologies(str(tmp_path))] == ["a", "b"]


def test_load_ontologies_only_listed_in_order(tmp_path):
    for name in ("a", "b", "c"):
        write(tmp_path, f"{name}.yaml", f"metadados: {{nome: {name}}}\n")
    assert [o.name for o in load_ontologies(str(tmp_path), ("c.yaml", "a.yaml"))] == ["c", "a"]


def test_load_real_ontologies():
    ontologies = load_ontologies(str(ONTOLOGIES))
    assert [o.name for o in ontologies] == ["ontologia-dengue-sp"]
