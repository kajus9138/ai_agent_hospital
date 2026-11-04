"""Ontologias em YAML que entram no system prompt do agente."""

from pathlib import Path

import pytest
import yaml

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
