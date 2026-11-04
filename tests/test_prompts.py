"""Montagem do system prompt com as ontologias e aviso de tamanho."""

import logging

import pytest

from ai_agent_hospital.agent.ontology import Ontology
from ai_agent_hospital.agent.prompts import (
    HOSPITAL_SYSTEM_PROMPT,
    build_system_prompt,
    estimate_tokens,
    log_prompt_size,
)

DENGUE = Ontology("ontologia-dengue-sp", "# comentário\nmetadados:\n  nome: ontologia-dengue-sp\n")
LEITOS = Ontology("leitos", "conceitos: []\n")


@pytest.mark.parametrize("ontologies", [(), []])
def test_without_ontologies_prompt_is_unchanged(ontologies):
    assert build_system_prompt(ontologies) == HOSPITAL_SYSTEM_PROMPT
    assert build_system_prompt() == HOSPITAL_SYSTEM_PROMPT


def test_ontologies_follow_the_base_prompt_in_order():
    prompt = build_system_prompt([DENGUE, LEITOS])
    assert prompt.startswith(HOSPITAL_SYSTEM_PROMPT)
    rest = prompt[len(HOSPITAL_SYSTEM_PROMPT) :]
    assert (
        rest.index("## Ontologias")
        < rest.index("### ontologia-dengue-sp")
        < rest.index("### leitos")
    )


def test_ontology_yaml_is_kept_verbatim():
    prompt = build_system_prompt([DENGUE])
    assert f"### ontologia-dengue-sp\n```yaml\n{DENGUE.content}```\n" in prompt


def test_estimate_tokens():
    assert estimate_tokens("x" * 3000) == 1000


def test_log_prompt_size_info(caplog):
    caplog.set_level(logging.INFO, logger="ai_agent_hospital.agent.prompts")
    assert log_prompt_size("x" * 3000, num_ctx=4096) == 1000
    assert [r.levelname for r in caplog.records] == ["INFO"]
    assert "3000 caracteres" in caplog.text and "~1000 tokens" in caplog.text


def test_log_prompt_size_warns_above_half_the_context(caplog):
    caplog.set_level(logging.INFO, logger="ai_agent_hospital.agent.prompts")
    log_prompt_size("x" * 3 * 2049, num_ctx=4096)
    assert [r.levelname for r in caplog.records] == ["INFO", "WARNING"]
    assert "OLLAMA_NUM_CTX" in caplog.records[-1].getMessage()


def test_real_ontology_fits_the_default_context(caplog):
    from ai_agent_hospital.agent.ontology import load_ontologies
    from ai_agent_hospital.config import DEFAULT_OLLAMA_NUM_CTX

    caplog.set_level(logging.WARNING, logger="ai_agent_hospital.agent.prompts")
    log_prompt_size(build_system_prompt(load_ontologies()), DEFAULT_OLLAMA_NUM_CTX)
    assert not caplog.records
