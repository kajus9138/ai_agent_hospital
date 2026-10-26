#!/usr/bin/env bash
# Cria um novo projeto a partir deste template e roda o setup.
# Uso: scripts/new-project.sh <diretorio-destino> [nome-do-projeto]
set -euo pipefail

TEMPLATE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?Uso: $0 <diretorio-destino> [nome-do-projeto]}"

if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST")" ]; then
  echo "✗ $DEST já existe e não está vazio." >&2
  exit 1
fi
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"

# Copia só o que é do template: nada de histórico, segredos, memórias ou tarefas deste repo.
rsync -a \
  --exclude '/.git' \
  --exclude '/.env' \
  --exclude '/memories' \
  --exclude '/*.pdf' \
  --exclude '/docs/*.pdf' \
  --exclude 'node_modules' \
  --exclude '/.claude/settings.local.json' \
  --exclude '/.taskmaster/tasks/*' \
  --exclude '/.taskmaster/reports/*' \
  --exclude '/.taskmaster/state.json' \
  "$TEMPLATE_DIR"/ "$DEST"/

cd "$DEST"
exec scripts/setup.sh "${2:-$(basename "$DEST")}"
