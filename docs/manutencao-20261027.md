# Manutenção 0.2.7-beta.4 — 27/10/2026

Atualização de dependências sem mudança de código do aplicativo nem do esquema (continua 11).

| Componente | Antes | Depois |
|---|---|---|
| Python (imagem base) | 3.12.15 | 3.12.16 (`python:3.12.16-slim`, Debian 13 atualizado) |
| Pillow | 12.3.0 | 13.0.0 |
| psycopg2-binary | 2.9.12 | 2.9.13 |
| TinyMCE | 8.9.1 | 8.10.0 (via `scripts/vendor-editor.py`, SHA-512 conferido) |

O arquivo `public/vendor/tinymce/langs/pt_BR.js` saiu: o editor carrega `pt-BR.js`, que vem do pacote de idiomas.

## Antes de publicar

- Produção conferida idêntica ao commit 6239806 (diferença apenas de final de linha CRLF).
- Backup VPS `20261027T031822Z-06c76116`: restauração testada e cópia no Google Drive.

## Testes da candidata (ambiente isolado no Desktop, banco descartável, contas sintéticas)

- 80/80 testes Python com os opt-ins de PostgreSQL, iguais na beta.3 e na beta.4, sem skips.
- Processamento de fotos (`store_image`): JPEG com EXIF de rotação, vertical, PNG com transparência, WebP, PNG pequena, GIF e arquivo inválido — resultado idêntico entre Pillow 12.3.0 e 13.0.0.
- Jornada Maverick em Chrome real, quatro fases: 35/35, QA_SKIP=0, zero exceções JavaScript, incluindo a revisão com IA (texto sintético, autorizada pelo proprietário).
- `beta_additional_gates.cjs`: compatibilidade 4/4 (Chrome, Android e iPhone emulados, Edge) e carga 7/7 (101 requisições, p95 354 ms, máximo 477 ms).
- Logs da candidata: zero respostas 5xx; os eventos de erro foram os provocados pela bateria (queda de conexão simulada e conflitos 409).

## Publicação

`ops/deploy/manut-20261027.sh` com `ENABLE_HSTS=1`, mesmo desenho do deploy de 06/10 (rollback automático). Imagem `sgc-codex:manut-20261027`, id `sha256:33c9e9e8bbb367e3a96e455836087a55d4115bf5d864669870945d48513a928e`, igual à testada.

Mudanças de configuração:

- `AUTH_TRUSTED_PROXY_IPS` passou a ser lido do Traefik no momento do deploy. O Traefik estava em 172.18.0.2 desde a manutenção do VPS de 22/10, enquanto o SGC ainda confiava em 172.18.0.5; com isso todos os usuários apareciam com o IP do proxy e compartilhavam as quotas de login. Se o Traefik mudar de IP após um reinício, repetir o deploy ou ajustar a variável.
- Cabeçalho `Strict-Transport-Security: max-age=31536000` no roteador `/SGC` (sem `includeSubDomains`).

Conferido após publicar: health público ok, versão 0.2.7-beta.4, esquema 11, trigger de auditoria ativo, conta do dono preservada, TinyMCE 8.10.0 servido, HSTS presente, contagens de usuários, registros, fotos, convites e auditoria iguais às de antes, n8n inalterado.

Rollback: o contêiner anterior ficou parado como `sgc-codex-app-pre-manut-20261027` (imagem `sgc-codex:pre-entrega-20261006`). Para voltar: parar e renomear `sgc-codex-app`, renomear o de reserva para `sgc-codex-app` e iniciá-lo. Evidências em `/opt/sgc-codex-20260925/evidence/manut-20261027`.
