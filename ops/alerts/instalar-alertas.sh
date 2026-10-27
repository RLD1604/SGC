#!/usr/bin/env bash
# Instala o alerta de falha de backup (healthchecks.io) nos quatro serviços.
# Pré-requisito: /etc/hc-ping/<serviço>.url já criados (ver README.md).
# Idempotente; não reinicia nenhum serviço de aplicação, só recarrega o systemd.
set -Eeuo pipefail
here=$(cd "$(dirname "$0")" && pwd)
services=(sgc-backup sgc-backup-drive vps-maintenance-backup vps-maintenance-weekly)

install -m 0755 "$here/hc-ping" /usr/local/sbin/hc-ping
install -m 0644 "$here/hc-fail@.service" /etc/systemd/system/hc-fail@.service
install -d -m 0700 /etc/hc-ping
for s in "${services[@]}"; do
  [ -s "/etc/hc-ping/$s.url" ] || { echo "falta /etc/hc-ping/$s.url" >&2; exit 2; }
  chmod 0600 "/etc/hc-ping/$s.url"
  install -d -m 0755 "/etc/systemd/system/$s.service.d"
  install -m 0644 "$here/drop-in-alert.conf" "/etc/systemd/system/$s.service.d/alert.conf"
done
systemd-analyze verify /etc/systemd/system/hc-fail@.service "/etc/systemd/system/${services[0]}.service"
systemctl daemon-reload
for s in "${services[@]}"; do
  printf '%s: ' "$s"
  systemctl show "$s.service" -p OnFailure -p ExecStartPre -p ExecStartPost --value | grep -c hc-ping
done
echo "instalado; os timers continuam os mesmos:"
systemctl list-timers 'sgc-*' 'vps-maintenance-*' --no-pager
