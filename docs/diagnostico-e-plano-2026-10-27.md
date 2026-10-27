# Diagnóstico e plano de manutenção — 27/10/2026

Auditoria de 30 minutos (00:32–01:02, horário de Brasília) feita por quatro agentes somente leitura, em paralelo, sobre: (A) infraestrutura e segurança do VPS; (B) código do SGC; (C) backups, recuperação e governança; (D) n8n, Hermes e serviços auxiliares. Nada foi alterado durante a auditoria.

Estado de partida: SGC 0.2.7-beta.4 publicado hoje com HSTS; backups do SGC e do VPS funcionando e testados; n8n 2.44.7; credenciais Google/Microsoft do n8n válidas; projeto Google Cloud publicado (não vence mais em 7 dias).

## 1. Resumo executivo

**O que está bem:** o SGC em produção é a peça mais bem construída do servidor (contêiner só leitura, sem privilégios, autenticação e autorização sólidas, SQL parametrizado, auditoria imutável, zero erros em 30 dias); n8n e Traefik estão na versão mais recente; firewall, SSH por chave, AppArmor e atualizações automáticas ativos; a cobertura dos backups é boa e a restauração é testada toda semana.

**Os cinco problemas que importam, em ordem:**

1. **Irrecuperabilidade em desastre duplo (C1).** As duas chaves que abrem todos os backups existem só no PC do Rodrigo. PC + VPS perdidos = SGC e VPS perdidos. Correção: 30 minutos, só o Rodrigo pode fazer.
2. **Ninguém é avisado quando o backup falha (C2/C3).** O backup geral ficou 3 dias parado e o do SGC pulou 4 dias em outubro; só foi descoberto por acaso ontem. Correção: 1 hora (healthchecks.io).
3. **O Hermes é a maior exposição do host (A2/D1/D2).** Roda como root com acesso ao Docker do servidor (equivale a root na máquina), sem limite de memória (usa 4,3 GB), sem healthcheck, exposto na internet, com imagem que **não pode ser reconstruída** se o contêiner morrer, e se auto-modifica. Correção: 1,5 h, exige reinício combinado.
4. **Bloqueio coletivo de login no SGC após reinício (S3, e S2 já hoje).** As cotas dependem do IP exato do proxy, que muda; entre 22 e 27/10 todos os usuários dividiram o mesmo balde. A recuperação de senha já tem esse defeito agora. Correção: 50 min + deploy.
5. **Falta CSP no app principal do SGC (S1)** — a defesa contra XSS num sistema que edita HTML rico só está no painel do dono. Correção: 2–3 h com testes.

Resto: Redis sem senha na rede interna, `.env` legíveis, volumes órfãos, código morto, runbook de reconstrução inexistente, docs desatualizados — tudo planejado abaixo, nenhum urgente isoladamente.

**Esforço total estimado:** Onda 0 ≈ 2,5 h; Onda 1 ≈ 3 h; Onda 2 ≈ 12 h; Onda 3 ≈ 3 h + runbook 4–6 h. Cerca de 25 horas de trabalho ao longo de 3–4 semanas, em janelas curtas e reversíveis.

## 2. Achados por área

### A. VPS — infraestrutura e segurança

Pontos fortes: ufw default deny (só 22/80/443); SSH sem senha, root só por chave; AppArmor enforce; unattended-upgrades ativo; rotação de logs Docker; Traefik sem dashboard inseguro, redirect 80→443, acme.json 600; n8n e SGC publicados só em 127.0.0.1; nenhum banco/Redis expõe porta no host; `systemctl --failed` vazio; TLS de todos os hosts válido (vencimentos: hermes 28/11/2026, n8n 01/01/2027, sq 04/01/2027, searxng 20/01/2027).

| ID | Sev. | Achado | Evidência | Correção | Esforço |
|---|---|---|---|---|---|
| A1 | Médio (era Alto) | 13 falhas do `vps-maintenance-backup` e 1 do weekly nos últimos 7 dias | journalctl -p err | Causa raiz já identificada e corrigida em 26/10 (OAuth do Drive expirado por projeto Google em "Testing"). Fechar só quando o ciclo agendado das 04:00 de 27/10 passar sem intervenção. Houve também 1 falha isolada do `sgc-backup` (linha 66, exit 1) a investigar no journal. | 15 |
| A2 | **Alto** | Hermes roda como root, sem limite de memória, sem healthcheck e com `/var/run/docker.sock` montado em leitura/escrita; exposto na web via Traefik | docker inspect | Quem controla o Hermes controla o host. Remover o socket (ou usar docker-socket-proxy só leitura), definir `mem_limit`, `pids_limit`, usuário não-root e healthcheck; avaliar se precisa ser público | 45 |
| A3 | Médio | Redis sem senha, `protected-mode no`, acessível por qualquer contêiner da rede `root_default` (n8n, Hermes, SGC, Traefik) | `PING`→`PONG` sem auth | `requirepass`/ACL no compose do Redis e `QUEUE_BULL_REDIS_PASSWORD` no n8n; ou rede dedicada Redis↔n8n | 20 |
| A4 | Médio | Traefik com docker.sock montado e como root | docker inspect | docker-socket-proxy em modo leitura; confirmar `exposedByDefault=false` | 30 |
| A5 | Médio | SSH 22 aberto ao mundo, sem fail2ban/crowdsec; `MaxAuthTries 6`, `X11Forwarding yes` | ufw, sshd -T, lastb 85 falhas históricas (5 em 10 dias) | Mitigado por chave-apenas. Opcional: fail2ban, `MaxAuthTries 3`, `X11Forwarding no`, restringir 22 a IPs conhecidos | 15 |
| A6 | Médio | 80 volumes Docker órfãos (4 GB) + 1 imagem dangling | `docker system df`: 87 volumes, 7 ativos | Listar e conferir antes de `docker volume prune` (precisa de autorização) | 15 |
| A7 | Baixo | Contêiner de rollback `sgc-codex-app-pre-manut-20261027` parado | esperado | Remover após alguns dias de beta.4 estável | 5 |
| A8 | Médio | 1 atualização de segurança padrão (libbrotli1) + cloud-init/tmux + 6 ESM-apps sem Ubuntu Pro | apt, `pro security-status` | Deixar unattended-upgrades aplicar; avaliar Ubuntu Pro gratuito (até 5 máquinas) para ESM | 10 |
| A9 | Médio | Três arquivos `.env` legíveis por todos (0644): `/root/.hermes/.env`, `/root/.env` (dono uid 1001), `/docker/searxng-ydje/.env` | ls -l | `chmod 600`; conferir dono de `/root/.env` | 5 |
| A10 | Médio | Disco: Hermes 34 GB em `/docker/hermes-agent-jdmg`; restic local 23 GB; `/root/vps-backups` 7 GB | du | Entender o que são os 34 GB; retenção do restic local (ver C); sem urgência (92 GB livres) | 20 |
| A11 | Baixo | Swap 760 MB em uso, swappiness 60, load 3,3 pontual | free, uptime | Opcional `vm.swappiness=10`; monitorar | 5 |
| A13 | Baixo | n8n sem `EXECUTIONS_DATA_PRUNE`/`MAX_AGE` explícitos | env | Padrão já poda em 336 h; banco n8n tem 37 MB | 5 |
| A14 | Baixo | `fwupd-refresh.service` falha 8× em 7 dias | journal | Inofensivo em VM; `systemctl mask fwupd-refresh.timer` | 2 |
| A15 | Baixo | 7 chaves em `/root/.ssh/authorized_keys` | contagem | Revisar quais ainda são necessárias (Codex, Claude, Hostinger, antigas) | 10 |

Não verificado por A: causa raiz das falhas (segredos proibidos — mas já conhecida pelo orquestrador); conteúdo dos volumes órfãos; o que ocupa os 34 GB do Hermes; se os 7 `.env` e 7 chaves SSH estão em uso; `exposedByDefault` do Traefik; snapshots do painel Hostinger.

### B. SGC — código

Pontos fortes (verificados no código): tokens aleatórios guardados como SHA-256 com `compare_digest`; argon2 com re-hash; hash fictício contra enumeração de contas; sessão rotacionada no login, idle 30 min / absoluta 12 h, revogação por geração; CSRF em três camadas (cookie + header + hash na sessão) mais `Origin`/`Sec-Fetch-Site`; TOTP com janela ±1 e anti-replay; segredo MFA cifrado com Fernet; step-up do dono; todas as rotas de escrita passam por sessão + CSRF + `authorize()`; mídia só por rota contextual com 404 em negação; SQL 100% parametrizado; auditoria imutável; IA só recebe trechos de texto com consentimento, timeout 45 s e sem log de conteúdo; nenhum uso de API deprecada de Pillow/Werkzeug.

| ID | Sev. | Achado | Onde | Correção | Esforço |
|---|---|---|---|---|---|
| S1 | **Alto** | CSP só em `owner.html`; `index.html` (app principal com editor HTML e fotos), `beta.html` e `ia.html` (script inline) não recebem CSP. `X-Frame-Options` inconsistente (DENY vs SAMEORIGIN). Sem `Permissions-Policy`. | server.py:471-473, 639-640; public/ia.html:5 | CSP em todas as páginas; mover script inline; unificar DENY; `Referrer-Policy` e `Permissions-Policy`. Testar se TinyMCE exige `style-src 'unsafe-inline'`. | M |
| S2 | Médio | Cota de "esqueci a senha" usa `request.remote_addr` direto, ignorando o proxy confiável → atrás do Traefik todos os anônimos compartilham 20 pedidos/10 min (um curioso bloqueia a recuperação para todos) | user_security.py:95-100 vs auth.py:305-335 | Reusar `auth._quota_client_address()` | P |
| S3 | Médio | Cotas de login dependem do IP exato do Traefik (`AUTH_TRUSTED_PROXY_IPS`); se mudar num reinício, todos caem num balde só (foi exatamente o que aconteceu entre 22 e 27/10) | auth.py:317-335; ops/deploy/manut-20261027.sh | Aceitar CIDR da rede `root_default` ou fixar IP do Traefik no compose; alertar em 429 de `/api/auth/login` | P |
| S4 | Médio | Sem pool de conexões: conexão nova a cada chamada, 3–5 por request; depende do GC para fechar | server.py:56-58; auth.py:235-262; observability.py:19-26 | `ThreadedConnectionPool` + `close()` em `finally`; `statement_timeout` global | M |
| S5 | Médio | Export HTML embute todas as fotos (masters 2048 px) como data: URI sem teto, gravado duas vezes no banco | editorial_api.py:74-104, 334, 392 | Limitar fotos/bytes por edição; usar versão reduzida no artefato | M |
| S6 | Médio | Limite de 12 MB por foto é checado depois do base64-decode de um JSON de até 64 MB; cada foto é codificada 2× (WEBP e PNG) | server.py:48-49, 374-401 | `MAX_CONTENT_LENGTH` ~24 MB nas rotas editoriais; checar tamanho antes de decodificar; PNG só quando origem for PNG/alfa | P |
| S7 | Médio | Código morto em produção: imagens de exemplo aceitas em `store_image`, estado de demonstração em `app.js`, `vendor/jodit*` (722 KB) e `filerobot/` servidos sem uso, ~80 linhas inalcançáveis em `/api/state`, `/api/import`, `/api/media` | server.py:382-383, 531-614; public/app.js:7-11,45; public/vendor/ | Remover (está no git) | P |
| S8 | Médio (a confirmar) | `render_edition` injeta `block["body"]` sem re-sanitizar; se algum PATCH gravar sem `normalize_state`, vira XSS armazenado no HTML aprovado | editorial_api.py:95-97 | `clean_html` também em `render_edition` (defesa em profundidade) | P |
| S9 | Baixo | `/api/health` e `version.json` públicos expõem versão, schema e editor | server.py:524-528 | Health público só com `status` | P |
| S10 | Baixo | Relatos do navegador: 120/min/usuário × 2 KB até 90 dias; limpeza roda dentro do request com timeout 2 s | observability.py:21-24, 83 | 20–30/min; retenção no timer já existente | P |
| S11 | Baixo | IDs de publicação/revisão não validados como UUID → erro vira 503 "banco indisponível" (ruído, não injeção) | editorial_api.py:340-404; server.py:518-521 | `uuid.UUID()` → 404 | P |
| S12 | Baixo | `/api/ai/status` revela se há chave Groq; cota de IA global (2/min, 100/dia) | ai_review.py:77, 107-110 | Expor só `enabled`; cota por usuário | P |
| S13 | Baixo | Dono sem cookie `sgc_owner_space` cai em `'sqa'` por padrão | owner_console.py:90-96 | Sem cookie, sem espaço | P |
| S14 | Baixo | `issue_invitation` grava `email` sem validar | auth.py:~495 | Validar tipo/tamanho/formato | P |
| S15 | Info | `.secrets/` mistura segredos de produção com credenciais/sessões de QA | .secrets/ | Separar em `qa/.secrets/` | P |
| Q1 | Info | 70+ linhas com mais de 300 colunas; imports repetidos dentro de funções; type hints só em auth/authorization | vários | Formatador + lint; não bloqueante | M |
| Q2 | Info | `bleach` está em modo manutenção upstream | requirements.txt | Avaliar `nh3` a médio prazo | — |

Não verificado por B: `authorization.py` em detalhe; `validate()` (limites de fotos/blocos); PATCH de edições/registros (S8); fluxos de recuperação/ativação além de grep; JS do cliente além de grep; CVEs das dependências (sem rede).

### C. Backups, recuperação e governança

Cobertura verificada como boa: o backup geral inclui n8n_data, acme.json do Traefik (único lugar dos certificados), Hermes, SearXNG, `/opt/sgc-codex-20260925` com os segredos; as fotos do SGC ficam dentro do PostgreSQL e entram no `pg_dump`. A retenção do restic é real (14/8/6 com prune). `main` está em sincronia com o GitHub (67f30b3). `.gitignore` cobre segredos, backups, resultados de QA e entregas privadas.

| ID | Sev. | Achado | Evidência | Correção | Esforço |
|---|---|---|---|---|---|
| C1 | **Alto** | **Ponto único de falha nas chaves:** a chave SSH `id_ed25519_vps_2026` (que abre o pacote de recuperação do vps-maintenance, com a senha do restic e o rclone.conf) existe só em `C:\Users\roddr\.ssh`. A identidade age do SGC tem 2 cópias (D: e E:), ambas no mesmo gabinete. Nenhuma cópia fora de casa, em papel ou cofre. | `~/.ssh`, `backups\saas-etapa1\keys`, `E:\SGC-Backup-Keys`, busca no Drive sem chaves | Cópia offline das duas chaves em local físico distinto (papel/pendrive) ou cofre de senhas com 2FA; registrar no runbook onde está. Nunca no Drive em claro. | 30 min |
| C2 | **Alto** | **Nenhum alerta de falha** em nenhuma cadeia (sem `OnFailure=`, e-mail, Telegram, healthchecks). A falha de 24–26/10 só deixou um `last-failure.json` no disco. | grep nos units e scripts: zero | **healthchecks.io** (grátis, "dead man switch"): `ExecStartPost=curl -fsS -m 10 https://hc-ping.com/<uuid>` nos dois serviços de backup + `OnFailure=` com ping em `/fail`; alerta por e-mail/Telegram. Alternativa: webhook no n8n (mas morre junto com o VPS). | 1 h |
| C3 | **Alto** | A cadeia do SGC também **pulou dias** sem ninguém notar: não há pacote em 12, 14, 20 e 24/10 | `ls /var/backups/sgc` por dia | Investigar o journal nesses dias; conferir `Persistent=true` no timer; C2 cobre o futuro | 30 min |
| C4 | Médio | Retenção do SGC em `report-only`: 58 pacotes, 3,6 GB, ~74 MB/dia, nunca apaga (17 só em 05/10, de testes) | manifest, script de retenção | Ativar poda real (14 diários + 8 semanais) depois de C2; não é urgente (levaria anos para encher) | 1 h |
| C5 | Médio | Projeção de disco: 92 GB livres; pior caso ~58 dias (fim de dez/2026), caso médio ~115 dias (fev/2027); com a poda do restic funcionando tende a platô de 30–40 GB | df, maintenance.py:286 | Acompanhar `disk_used_percent` no relatório semanal; alerta em 80% via C2 | 15 min |
| C6 | Médio | O pacote SGC de hoje (00:18) ainda empacota a imagem **beta.3** enquanto roda a beta.4 — até 03:17 o pacote de recuperação combina imagem antiga com banco atual | manifest `image_ref` vs `docker ps` | Rodar `systemctl start sgc-backup.service` ao fim de cada deploy (incluir no script) | 10 min |
| C7 | Médio | Imagem do banco do SGC em produção é um ID sem tag (`b0f9560a2de0`) | docker ps | `docker tag b0f9560a2de0 postgres-sgc:17-prod` e registrar no deploy | 5 min |
| C8 | Médio | **Não existe runbook de reconstrução do SGC do zero** num VPS novo; o ensaio mensal "do zero" previsto em 25/09 nunca foi executado | grep nos docs | Escrever `docs/runbook-recuperacao-vps-novo.md` (age -d, docker load, redes/volumes, dump, segredos, Traefik/acme.json, proxy dinâmico, HSTS) e **ensaiar uma vez** em VM descartável | 4–6 h |
| C9 | Baixo | Tarefa Windows `SGC-Backup-Diario-Drive-GitHub`: copia o pacote do VPS para `backups\saas-etapa1\vps-daily`, `E:\SGC-Daily` e `G:\Meu Drive`; só 7 execuções; falhou 26/10 (PC desligado). Redundante com o envio feito pelo próprio VPS; única utilidade é a cópia em E: (mesmo PC) | Get-ScheduledTask, script | Desativar; se quiser 2ª nuvem, rclone no VPS para um 2º destino (Backblaze B2) | 15 min |
| C10 | Baixo | Cópia local do SGC no Docker Desktop está vazia (6 usuários, 0 registros, 0 fotos), ainda na beta.3 | psql local | Desligar ou atualizar como ambiente de QA | 10 min |
| C11 | Baixo | `D:\02-Codex-Desktop\04-VPS\02-Backups` tem 5 tar.age quase iguais de 756 MB (22/10) + 4 pacotes de recuperação | Get-ChildItem | Manter só o `recovery-final-20261022T201201Z` e um `cutover-*-final`; resto para quarentena (skill exclusao-segura) | 10 min |
| C12 | Baixo | Docs desatualizados: `prototipo-condominio/README.md:57` ("sem login e controle de permissões"); `validacao-pre-entrega-20261006.md:25` (proxy 172.18.0.5); `02_Projeto-Relatorio-SQA/README.md:38` (volume `uploads_data`); `runbook-operacao-beta.md` (backup local pré-VPS); docs de 06/10 citam beta.3 | grep | Atualizar README e runbook; marcar os de 06/10 como históricos | 1 h |
| C13 | Info | 7 arquivos não rastreados (feedback, kits, previews, este diagnóstico). Conferir se `preparar-kits-testadores.py` embute nomes/e-mails antes de commitar | git status | Commitar o que for público; o resto em `entregas-privadas/` | 10 min |
| C14 | Info | Não há compose de produção: o VPS usa `docker create` manual no script de deploy; o `compose.yaml` do repo é só local | arquivos | Gerar `compose.prod.yaml` equivalente ao script (ajuda C8) | 2 h |

**Resposta à pergunta "se o PC queimar hoje":** se só o PC queimar, SGC e VPS continuam no ar e os backups continuam sendo gerados — mas as duas chaves se perdem e os 58 pacotes do SGC no Drive e o pacote de recuperação do VPS ficam ilegíveis. Se PC **e** VPS falharem (ou o VPS for comprometido), **hoje não há recuperação possível** de nenhum dos dois. C1 resolve 90% desse risco em 30 minutos; C8 resolve o resto.

Não verificado por C: branch protection/2FA no GitHub; motivo exato dos dias sem pacote; decifragem efetiva dos pacotes com as chaves atuais (não se abriu chave); se a "revisão semanal por IA na nuvem do ChatGPT" do Codex ainda existe (nenhum doc a menciona; o que existe é o `last-weekly-report.md` gerado na VPS, que depende de alguém abrir por ssh).

### D. n8n, Hermes, SearXNG, Traefik, Redis

Versões: n8n 2.44.7 = mais recente; Traefik 3.7.16 = mais recente; Redis 7.2.16 (ramo antigo; há 7.4.12 e 8.x); SearXNG de 19/10 (rolling, normal); PostgreSQL 17.11. Recursos agora: Hermes 4,3 GiB de RAM sem limite; SearXNG 638 MiB sem limite; os demais com limite e folga. Zero erros nos logs de n8n, worker, Hermes e SearXNG em 72 h; nenhuma execução presa.

| ID | Sev. | Achado | Evidência | Correção | Esforço |
|---|---|---|---|---|---|
| D1 | **Alto** | Hermes como root com docker.sock (= root no host), sem limite de memória, sem healthcheck — confirma A2 | docker inspect; `id` = uid 0 | docker-socket-proxy com só os endpoints necessários, `mem_limit`, healthcheck HTTP em :4860, usuário não-root | 60 |
| D2 | **Alto** | Hermes **não é reconstruível**: imagem local `hermes-https-restore:20261017-v0222` (4,6 GB) sem Dockerfile/repositório no host; o compose aponta para outra tag (`20260830`) que não é a que roda; origem foi `ghcr.io/hostinger/hvps-hermes-agent:latest` (jun/2026). O agente se auto-modifica ("Self-improvement review" editando skills). | `.build.log`, `ls /docker/hermes-agent-jdmg` | `docker save` da imagem para backup externo (o vps-maintenance já guarda uma cópia plana do filesystem, não a imagem); extrair `/opt/hermes/Dockerfile` e README do contêiner para o host; alinhar a tag no compose | 30 |
| D3 | Médio | Workflow n8n **"Portal Google — Tasks v2" falha em 73% das execuções** (24 erros/33 em 7 dias, 2× por disparo às 09:01 e 17:01); 45 erros desde 16/10 | execution_entity | Os 401 de 22–26/10 eram token vencido; as credenciais estão OK desde 26/10 23:51, mas ainda não houve disparo depois disso. Conferir a execução das 09:01 de 27/10; se falhar, abrir na UI (provável escopo Tasks) | 20 |
| D4 | Médio | Hermes: 33 GB em `data/` — 14 GB em `data/backups`, 4,8 GB whisper-venv, 2,6 GB `state.db`, 1,9 GB snapshots | du | Rotacionar `data/backups` (reter N últimos) ou movê-los para fora do volume vivo; VACUUM do `state.db` | 20 |
| D5 | Médio | Redis sem senha, `protected-mode no`, `maxmemory 0`, `noeviction` — confirma A3 | CONFIG GET | `requirepass` + `QUEUE_BULL_REDIS_PASSWORD`; `maxmemory` ~128 MB mantendo `noeviction` (fila Bull) | 20 |
| D6 | Médio | Redis 7.2.16 em ramo antigo | releases | `redis:7.4-alpine` numa janela, com backup antes | 10 |
| D7 | Médio | Sem rate limiting no Traefik para n8n/Hermes/SearXNG; `EXECUTIONS_DATA_PRUNE/MAX_AGE` implícitos (padrão 336 h funciona) | labels, compose | Middleware `ratelimit`; declarar prune explicitamente | 15 |
| D8 | Baixo | Hermes e n8n também em `entrypoints=web` (redundante; redirect já é global); Hermes e SearXNG sem middleware de cabeçalhos de segurança (n8n e SGC têm) | labels | Só `websecure`; reaproveitar middleware `n8n@docker` | 10 |
| D9 | Baixo | SearXNG sem `limiter` e porta 8080 em 172.19.0.1 (bridge interna) | settings.yml | OK se uso próprio; senão `limiter: true` | 10 |
| D10 | Info | n8n: 1 usuário, login exigido; 13 ativos / 26 workflows (9 marcados [REVISAR]/[ARQUIVADO]); credenciais 12; runner JS interno, aviso de Python sumiu; tabelas pequenas, sem bloat; Postgres 128 MB shared_buffers adequado ao limite de 512 MiB | SQL, settings | Definir `N8N_RUNNERS_TASK_TIMEOUT` explícito; exportar e excluir os [ARQUIVADO] | 15 |

Incidente de higiene durante a auditoria: um filtro do agente não casou a linha `N8N_ENCRYPTION_KEY=` do compose e o valor ficou gravado num arquivo temporário da sessão no Windows. O agente não reproduziu o valor; o orquestrador apagou o arquivo em seguida e confirmou que não há outra cópia na pasta de tarefas. A chave não saiu do computador do Rodrigo nem foi exibida no chat. Recomendação: considerar a rotação desnecessária (exposição local, apagada), mas registrar.

Não verificado por D: texto das mensagens de erro do Tasks v2 (JSON com ponteiros); conteúdo do Dockerfile dentro da imagem do Hermes; logs do Hermes em arquivo (s6); tag latest do SearXNG no ghcr.

## 3. Plano de soluções priorizado

Critério: primeiro o que pode derrubar ou comprometer o servidor inteiro; depois o que degrada o SGC para os usuários; depois higiene e dívida. Cada ação é uma janela separada, com backup antes e rollback definido. Nada aqui foi executado.

### Onda 1 — esta semana (risco ao host e ao acervo)

| # | Ação | Área | Esforço | Risco de executar | Pré-requisito |
|---|---|---|---|---|---|
| 1 | Confirmar que o backup geral das 04:00 de 27/10 e o SGC passaram sozinhos; investigar a falha isolada do `sgc-backup` (linha 66) | A1 | 15 min | nenhum (leitura) | — |
| 2 | **Hermes:** `docker save` da imagem em uso para `/root/vps-backups` e para o Drive; extrair Dockerfile/README do contêiner; alinhar a tag no compose. Sem isso, se o contêiner morrer o Hermes não volta. | D2 | 30 min | baixo | espaço em disco (4,6 GB) |
| 3 | **Hermes:** tirar o `docker.sock` (ou pôr `docker-socket-proxy` só leitura), `mem_limit` 6 GB, `pids_limit`, healthcheck em :4860. Reinício do Hermes necessário — **combinar horário**. | A2/D1 | 60 min | médio: pode quebrar funções do agente que usem Docker; rollback = compose anterior | ação 2 feita; saber se o Hermes usa Docker de verdade |
| 4 | `chmod 600` nos três `.env` legíveis por todos; conferir dono de `/root/.env` | A9 | 5 min | nenhum | — |
| 5 | Redis com senha (`requirepass` + `QUEUE_BULL_REDIS_PASSWORD` no n8n e worker), `protected-mode yes`, `maxmemory 128mb`. Reinício de Redis + n8n + worker (fila para por ~1 min). | A3/D5 | 20 min | médio: fila Bull; rollback = compose anterior | backup do compose; janela sem execuções em andamento |
| 6 | SGC: aceitar a rede do proxy (CIDR `172.18.0.0/16`) em `AUTH_TRUSTED_PROXY_IPS`, ou fixar IP do Traefik no compose — elimina a recorrência do bloqueio coletivo após reinício | S3 | 20 min + deploy | baixo (há script de deploy com rollback) | testes em QA isolado |

### Onda 2 — próximas duas semanas (SGC mais robusto)

| # | Ação | Área | Esforço | Risco | Pré-requisito |
|---|---|---|---|---|---|
| 7 | CSP em todas as páginas do SGC + `Permissions-Policy` + `X-Frame-Options: DENY` unificado; mover script inline de `ia.html` | S1 | 2–3 h | médio: TinyMCE pode exigir `style-src 'unsafe-inline'`; testar a jornada Maverick completa | ambiente QA isolado (já montado uma vez) |
| 8 | Cota de recuperação de senha usando o IP real do cliente | S2 | 30 min | baixo | — |
| 9 | Pool de conexões + `statement_timeout` | S4 | 2 h | médio; testar carga (gate `load`) | — |
| 10 | Limites: `MAX_CONTENT_LENGTH` menor nas rotas editoriais; checar tamanho antes do decode; PNG só quando fizer sentido; teto de fotos/bytes por informe e artefato com versão reduzida | S5/S6 | 3 h | médio | — |
| 11 | `clean_html` em `render_edition`; validar UUID → 404; validar e-mail do convite; health público só com `status`; dono sem cookie sem espaço; cota de relatos 30/min e retenção no timer | S8–S14 | 2 h | baixo | — |
| 12 | Remover código morto (imagens de exemplo, demo em app.js, jodit/filerobot, rotas inalcançáveis) e separar segredos de QA | S7/S15 | 1 h | baixo | — |
| 13 | n8n: investigar o "Tasks v2" se ainda falhar em 27/10; declarar prune explícito e `N8N_RUNNERS_TASK_TIMEOUT`; middleware `ratelimit` e cabeçalhos de segurança no Traefik para Hermes/SearXNG; só `websecure` | D3/D7/D8 | 1 h | baixo | — |

### Onda 3 — quando houver janela (higiene e capacidade)

| # | Ação | Área | Esforço | Risco | Pré-requisito |
|---|---|---|---|---|---|
| 14 | Hermes: rotacionar `data/backups` (14 GB) e VACUUM do `state.db`; entender os 34 GB | D4/A10 | 30 min | baixo | saber o que o próprio Hermes espera encontrar |
| 15 | Volumes Docker órfãos (80, 4 GB): listar, conferir, podar | A6 | 15 min | baixo com conferência | autorização explícita |
| 16 | Redis 7.2 → 7.4 | D6 | 10 min | baixo | backup; janela |
| 17 | SSH: `MaxAuthTries 3`, `X11Forwarding no`, revisar as 7 chaves autorizadas; fail2ban opcional | A5/A15 | 20 min | baixo (não se trancar fora: testar nova sessão antes de fechar a atual) | — |
| 18 | Ubuntu Pro gratuito para as 6 correções ESM; deixar unattended-upgrades aplicar libbrotli1; mascarar `fwupd-refresh` | A8/A14 | 15 min | baixo | conta Ubuntu One (Rodrigo) |
| 19 | Remover contêiner de rollback da beta.3 após uma semana estável; lint/formatador no SGC; avaliar `nh3` no lugar de `bleach` | A7/Q1/Q2 | 1 h | nenhum | — |

### Onda 0 — antes de tudo (continuidade; não dependem de janela nem de código)

Estas ações entram **antes** da Onda 1, porque sem elas qualquer incidente grave é irrecuperável.

| # | Ação | Área | Esforço | Risco | Quem |
|---|---|---|---|---|---|
| 0.1 | Cópia offline da chave SSH `id_ed25519_vps_2026` e da identidade age do SGC em local físico distinto (papel/pendrive) ou cofre com 2FA; anotar no runbook onde está | C1 | 30 min | nenhum | Rodrigo (só ele deve manusear as chaves) |
| 0.2 | Alerta de falha de backup via healthchecks.io nos dois serviços (`ExecStartPost` + `OnFailure`), com aviso por e-mail/Telegram | C2 | 1 h | baixo | Claude prepara; Rodrigo cria a conta e autoriza |
| 0.3 | Investigar os 4 dias sem pacote do SGC (12, 14, 20, 24/10) e a falha isolada da linha 66; confirmar `Persistent=true` | C3/A1 | 30 min | nenhum | Claude |
| 0.4 | Rodar `sgc-backup` agora (pacote ainda traz a imagem beta.3) e incluir essa chamada no final do script de deploy; dar tag à imagem do banco | C6/C7 | 15 min | nenhum | Claude |
| 0.5 | Desativar a tarefa Windows legada e desligar (ou atualizar) a cópia local vazia do SGC | C9/C10 | 15 min | nenhum | Claude, com autorização |

Para a Onda 2/3 somam-se: runbook de reconstrução do zero com ensaio em VM descartável (C8, 4–6 h, o item de maior valor da lista), `compose.prod.yaml` (C14), poda real do SGC (C4), limpeza da pasta `04-VPS\02-Backups` (C11), atualização de README/runbook (C12) e commit dos arquivos públicos pendentes (C13).

## 3b. Investigação C3 — dias sem pacote do SGC (27/10, 00:50)

**24/10 — causa confirmada.** O journal mostra o `sgc-backup` falhando às 03:36:09 na linha 66 (o `pg_restore` de verificação) com `FATAL: terminating connection due to administrator command`. É uma condição de corrida conhecida da imagem oficial do PostgreSQL: durante a inicialização o entrypoint sobe um servidor **temporário** (que escuta só no socket Unix), depois o derruba e sobe o definitivo. O script espera com `pg_isready` via `docker exec` — que usa o socket Unix e, portanto, responde "pronto" já na fase temporária. O `pg_restore` conecta nesse servidor temporário e é morto quando o entrypoint o encerra. É intermitente por natureza (depende de quantos milissegundos o `initdb` leva).

**12, 14 e 20/10 — não há como confirmar.** O journal retém só 7 dias (`MaxRetentionSec=7day`), não existe outro log do serviço e o recibo do Drive guarda só o último sucesso. A hipótese mais provável é a mesma corrida: três falhas em ~16 execuções é compatível com uma corrida de ~15–20 %, e o serviço **não tem `Restart=on-failure`** — uma falha transitória significa um dia sem pacote. Os reinícios do VPS (16, 17 e 22/10) não coincidem com os dias faltantes e o timer tem `Persistent=true`, então não foram eles.

**Correção proposta (não aplicada; o script do repositório `ops/backup/sgc-backup.sh` é idêntico ao do VPS, então a mudança vale para os dois):**

1. Esperar pelo servidor definitivo, não pelo temporário: usar `pg_isready -h 127.0.0.1` no laço e no `pg_restore` (o servidor temporário não escuta em TCP, então o TCP só responde quando a inicialização terminou). Duas linhas (62, 65 e 66 do script).
2. Dar segunda chance ao serviço sem mexer na unidade original: drop-in com `Restart=on-failure`, `RestartSec=10min`, `StartLimitIntervalSec=2h`, `StartLimitBurst=3` — mesma política já usada pelo `vps-maintenance-backup`.
3. Com o alerta do healthchecks.io instalado, qualquer recorrência passa a ser avisada no mesmo dia.
4. Opcional: subir `MaxRetentionSec` do journal para 30 dias (hoje ocupa 963 MB do limite de 1 GB; o custo é só disco).

## 4. O que não foi verificado

Cada seção lista o que o respectivo agente não alcançou. Transversalmente: configurações do GitHub (2FA, proteção de branch — `gh` não está autenticado); painel e snapshots da Hostinger; CVEs das versões instaladas; decifragem real dos pacotes de backup; conteúdo das mensagens de erro do workflow "Tasks v2"; o que ocupa os 34 GB do Hermes; se o Hermes realmente usa o socket do Docker (define se a ação 3 quebra algo). Nada foi executado para testar hipóteses — foi uma leitura de 30 minutos, não um pentest.

## 5. Como foi feito

Cada agente recebeu um escopo fechado, prazo de 12 minutos, proibição de alterar qualquer coisa e de imprimir segredos. Os relatórios foram consolidados pelo orquestrador; achados sem evidência foram marcados como "a confirmar".
