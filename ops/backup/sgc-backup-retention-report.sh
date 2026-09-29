#!/usr/bin/env bash
set -Eeuo pipefail
CONFIG=${SGC_BACKUP_CONFIG:-/etc/sgc-backup/sgc-backup.conf}
[[ -r "$CONFIG" ]] || { echo "Configuração ausente: $CONFIG" >&2; exit 2; }
# shellcheck source=/dev/null
source "$CONFIG"
: "${BACKUP_ROOT:?}"
: "${RETENTION_DAILY:=14}"

echo "Modo somente relatório: nenhum arquivo será removido."
mapfile -t successful < <(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -type f -name SUCCESS -printf '%h\n' | sort -r)
echo "Backups válidos encontrados: ${#successful[@]}"
if ((${#successful[@]} > RETENTION_DAILY)); then
  echo "Mais antigos que a janela diária inicial ($RETENTION_DAILY), apenas candidatos a revisão:"
  printf '%s\n' "${successful[@]:RETENTION_DAILY}"
else
  echo "Nenhum candidato fora da janela diária inicial."
fi

