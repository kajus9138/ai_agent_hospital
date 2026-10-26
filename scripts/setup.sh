#!/usr/bin/env bash
# Prepara um projeto criado a partir do template. Pode ser rodado mais de uma vez.
# Uso (na raiz do projeto): scripts/setup.sh [nome-do-projeto]
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${1:-$(basename "$PWD")}"
NAME="$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9_-' '_')"

echo "▸ Projeto: $NAME ($PWD)"

# 1. Pré-requisitos
missing=0
for cmd in git gh node npx uv uvx task-master basic-memory pre-commit claude; do
  command -v "$cmd" >/dev/null || { echo "  ✗ falta: $cmd"; missing=1; }
done
if [ "$missing" -ne 0 ]; then
  echo "Instale os pré-requisitos (seção 2 do guia) e rode de novo." >&2
  exit 1
fi

# 2. Basic Memory: registra o projeto e aponta o .mcp.json para ele
mkdir -p memories .taskmaster/tasks .taskmaster/reports
touch memories/.gitkeep
if basic-memory project add "$NAME" "$PWD/memories" >/dev/null 2>&1; then
  echo "  ✓ Basic Memory: projeto '$NAME' registrado"
else
  echo "  • Basic Memory: '$NAME' já estava registrado (confira com: basic-memory project list)"
fi
python3 - "$NAME" <<'PY'
import json, sys
path = ".mcp.json"
with open(path) as f:
    cfg = json.load(f)
args = cfg["mcpServers"]["basic-memory"]["args"]
args[args.index("--project") + 1] = sys.argv[1]
with open(path, "w") as f:
    json.dump(cfg, f, indent="\t", ensure_ascii=False)
    f.write("\n")
PY
echo "  ✓ .mcp.json aponta para '$NAME'"

# 3. Segredos locais
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ✓ .env criado a partir do .env.example (preencha as chaves que for usar)"
fi

# 4. Git + pre-commit
if [ ! -d .git ]; then
  git init -b main >/dev/null
  echo "  ✓ git init (branch main)"
fi
pre-commit install >/dev/null
echo "  ✓ pre-commit instalado"
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add -A
  # Único commit permitido na main: o inicial. Daí em diante, só via feature branch + PR.
  git commit --no-verify -q -m "chore: projeto criado a partir do template de workflow"
  echo "  ✓ commit inicial criado"
fi

# 5. MCPs globais (escopo de usuário)
if ! claude mcp get context7 >/dev/null 2>&1; then
  echo "  ⚠ Context7 não configurado. Rode uma vez na máquina:"
  echo "      claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp"
fi

cat <<EOF

Pronto. Próximos passos:
  1. Preencha .taskmaster/docs/prd.txt e as convenções em dev-workflow.md
  2. Abra o Claude Code aqui e confira os MCPs com /mcp
  3. task-master parse-prd .taskmaster/docs/prd.txt
EOF
