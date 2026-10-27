"""Mantém a documentação em dia com o código: variáveis de ambiente e links internos."""

import inspect
import re
from pathlib import Path

import pytest

from ai_agent_hospital import config

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "DEMO.md", *sorted((ROOT / "docs").glob("*.md"))]
MCP_VARS = {"SMART_HOSPITALS_PATH", "MCP_SERVER_COMMAND", "MCP_SERVER_ARGS"}

# [texto](alvo) fora de blocos de código; o alvo não tem espaços.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def settings_vars() -> set[str]:
    return set(re.findall(r'os\.getenv\("(\w+)"', inspect.getsource(config.get_settings)))


def table_vars(path: Path) -> set[str]:
    """Variáveis citadas na primeira coluna de tabelas markdown: | `VAR` | ..."""
    return set(re.findall(r"^\| `([A-Z_]+)` \|", path.read_text(encoding="utf-8"), re.M))


def without_code(text: str) -> str:
    """Texto sem blocos de código nem trechos em crase, onde `[x](y)` não é link."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def anchors(path: Path) -> set[str]:
    """Âncoras que o GitHub gera para os títulos: minúsculas, sem pontuação, espaço vira hífen.

    Títulos repetidos ganham sufixo: `foo`, `foo-1`, `foo-2`.
    """
    text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.M | re.S)
    seen: dict[str, int] = {}
    result = set()
    for title in re.findall(r"^#+ (.+)$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", title.strip().lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        result.add(f"{slug}-{n}" if n else slug)
    return result


def test_settings_reads_the_documented_vars():
    # Guarda do próprio teste: se o config deixar de usar os.getenv, a regex não acha nada.
    assert MCP_VARS <= settings_vars()


def test_readme_documents_every_setting():
    assert settings_vars() <= table_vars(ROOT / "README.md")


def test_mcp_guide_documents_mcp_settings():
    assert MCP_VARS <= table_vars(ROOT / "docs" / "mcp-integration.md")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_internal_links_resolve(doc):
    broken = []
    for target in LINK.findall(without_code(doc.read_text(encoding="utf-8"))):
        if re.match(r"[a-z]+:", target):  # http(s), mailto
            continue
        file_part, _, anchor = target.partition("#")
        dest = (doc.parent / file_part).resolve() if file_part else doc
        if not dest.exists():
            broken.append(target)
        elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
            broken.append(target)
    assert not broken, f"Links quebrados em {doc.name}: {broken}"
