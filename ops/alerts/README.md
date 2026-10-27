# Alerta de falha de backup — healthchecks.io

Mecanismo "dead man switch": cada serviço de backup avisa o healthchecks.io quando termina bem; se o aviso não chegar no prazo, ou se chegar um aviso de falha, o healthchecks.io manda e-mail (e Telegram, se configurado). Funciona mesmo que o VPS inteiro desligue, porque quem vigia está fora dele.

## O que o proprietário cria (uma vez, ~10 minutos)

1. Conta gratuita em https://healthchecks.io (até 20 checks; basta e-mail). Em *Settings → Profile*, fuso `America/Sao_Paulo`.
2. Quatro checks, em *Add Check*, com estes nomes e prazos:

| Nome do check | Period | Grace | Por quê |
|---|---|---|---|
| `sgc-backup` | 1 day | 2 hours | roda 03:17 + atraso aleatório de 20 min |
| `sgc-backup-drive` | 1 day | 2 hours | roda 04:00 + 20 min |
| `vps-maintenance-backup` | 1 day | 8 hours | roda 04:00, pode levar horas e repete até 3× em 6 h |
| `vps-maintenance-weekly` | 1 week | 8 hours | domingo 05:00 |

   Em *Schedule* deixe "Simple". Tags opcionais: `vps`, `sgc`.
3. Em *Integrations*, confirme o e-mail (já vem) e, se quiser, adicione Telegram (o bot do healthchecks pede só um clique).
4. Copie a **URL de ping** de cada check (formato `https://hc-ping.com/xxxxxxxx-...`). Ela funciona como senha de escrita: quem a tiver consegue "fingir" que o backup rodou, mas não lê nada. Passe as quatro ao Claude pelo chat ou grave você mesmo no VPS (abaixo).

## O que entra no VPS

```
/usr/local/sbin/hc-ping                      script de ping (lê a URL de um arquivo)
/etc/systemd/system/hc-fail@.service         unidade genérica que manda /fail
/etc/hc-ping/<serviço>.url                   uma URL por serviço, root 0600
/etc/systemd/system/<serviço>.service.d/alert.conf   drop-in (não altera as unidades originais)
```

Gravar as URLs (uma linha por arquivo), por exemplo:

```sh
install -d -m 0700 /etc/hc-ping
printf '%s\n' 'https://hc-ping.com/...' > /etc/hc-ping/sgc-backup.url
# idem para sgc-backup-drive, vps-maintenance-backup, vps-maintenance-weekly
chmod 0600 /etc/hc-ping/*.url
```

Depois: `bash ops/alerts/instalar-alertas.sh` (copiar a pasta para o VPS antes). O script só recarrega o systemd; não reinicia aplicação nem mexe nos timers.

## Teste de aceite

1. Sucesso: `systemctl start sgc-backup.service` → o check `sgc-backup` fica verde com duração medida.
2. Falha simulada sem tocar em produção: `systemctl start hc-fail@sgc-backup-drive.service` → o check `sgc-backup-drive` fica vermelho e chega o e-mail; o próximo ciclo real às 04:00 o devolve ao verde.
3. Ausência: pausar nada; só conferir no painel que cada check mostra "next ping expected" coerente com os timers.

## Remoção

Apagar os quatro `alert.conf`, `hc-fail@.service`, `/usr/local/sbin/hc-ping`, `/etc/hc-ping/` e rodar `systemctl daemon-reload`. As unidades originais ficam exatamente como estavam.

## Limites

- Não detecta backup "bem-sucedido mas inútil" (o `sgc-backup` já testa a restauração; o `vps-maintenance-weekly` restaura do Drive toda semana — por isso o check semanal importa).
- Depende de saída HTTPS do VPS para hc-ping.com; falha de rede aparece como "ausência de ping", que também é alerta.
- Se os timers forem desativados de propósito, pausar os checks no painel para não receber alerta falso.
