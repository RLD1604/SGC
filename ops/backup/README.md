# Backup diário do SGC no VPS

Esta rotina cria diariamente um pacote cifrado com dump consistente do PostgreSQL,
imagem Docker do aplicativo, manifesto, hashes e metadados mínimos de reconstrução.
Antes de aceitar o backup, restaura o dump em um PostgreSQL efêmero com rede `none`.
O pacote não inclui variáveis de ambiente do contêiner, chaves ou senhas.

## Pré-requisitos

- Docker, `age`, `jq`, `tar` e `sha256sum` no VPS.
- Destinatário público `age`; mantenha a identidade privada fora do VPS.
- Espaço temporário suficiente em `/run/sgc-backup` e definitivo em
  `/var/backups/sgc`. Se `/run` não comportar a imagem, configure um volume
  temporário protegido e cifrado em repouso.

## Instalação manual auditável

Não execute estas instruções sem conferir os nomes de contêiner e banco.

```sh
install -d -m 0700 /etc/sgc-backup /var/backups/sgc /run/sgc-backup
install -m 0750 sgc-backup.sh /usr/local/sbin/sgc-backup
install -m 0750 sgc-backup-retention-report.sh /usr/local/sbin/sgc-backup-retention-report
install -m 0600 sgc-backup.conf.example /etc/sgc-backup/sgc-backup.conf
install -m 0644 sgc-backup.service /etc/systemd/system/sgc-backup.service
install -m 0644 sgc-backup.timer /etc/systemd/system/sgc-backup.timer
```

Edite `/etc/sgc-backup/sgc-backup.conf`, informe `AGE_RECIPIENT` e confirme os
demais valores. Então teste de forma manual:

```sh
systemd-analyze verify /etc/systemd/system/sgc-backup.service /etc/systemd/system/sgc-backup.timer
systemctl daemon-reload
systemctl start sgc-backup.service
systemctl status sgc-backup.service
journalctl -u sgc-backup.service --since today
```

Somente depois de conferir um diretório com `SUCCESS`, manifesto e hash válido:

```sh
systemctl enable --now sgc-backup.timer
systemctl list-timers sgc-backup.timer
```

O timer roda diariamente às 03:17 no fuso de São Paulo, com atraso aleatório de
até 20 minutos, e recupera uma execução perdida após reinício. A retenção está em
modo somente relatório: o script lista candidatos antigos, mas não apaga nada.

## Cópias externas

O diretório de cada execução contém somente o pacote `.age`, seu SHA-256, o
manifesto sem segredos e o marcador `SUCCESS`. Um processo externo deve copiar
apenas execuções com `SUCCESS` para o Google Drive. O GitHub deve receber estes
scripts e o código do app, nunca dumps, pacotes de recuperação ou credenciais.
Ative exclusão automática somente depois de validar a cópia externa, a custódia
da identidade `age`, alertas de falha e pelo menos um ensaio completo de recuperação.

