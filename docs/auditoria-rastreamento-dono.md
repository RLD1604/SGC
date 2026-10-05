# Auditoria da execução — 2026-10-05

Versão 0.2.6-beta.1, schema 9. Plano: plano-rastreamento-dono.md.

| Etapa | Planejado | Executado e verificado |
|---|---|---|
| 0 | Preservar banco e fonte | Dump local validado por pg_restore; ZIP da fonte; backup cifrado VPS anterior à implantação, com SUCCESS e SHA-256 válido |
| 1 | Diagnóstico seguro no servidor | ID próprio por requisição, resultado HTTP, identidade e condomínio obtidos no servidor; persistência separada e saída JSON sanitizada de contingência |
| 2 | Relatos do navegador | Navegação, tentativas e falhas sem valores dos campos; sessão, CSRF, limite de tamanho e volume, código de atendimento |
| 3 | Dono separado dos clientes | Grant exclusivo de rodrigo; senha e TOTP, bloqueio de reutilização, limite de tentativas e autorização por sessão de 15 minutos |
| 4 | Painel somente de leitura | Indicadores e filtros paginados; nomes de usuários/condomínios; bloqueio, expiração e proteção contra cache/embutimento |
| 5 | Testar, comparar e distribuir | Testes concluídos; Desktop e VPS saudáveis com imagem e hashes de arquivos idênticos; GitHub e Drive confirmados abaixo |

## Evidências

- 64 testes Python de unidade/regressão aprovados na revisão final; testes Node de privacidade, limites e interface de perfis aprovados.
- Integração HTTP completa com PostgreSQL em bancos exclusivos `sgc_owner_qa_*`: sessão, CSRF, MFA, reutilização, acesso negado para operador/administrador, salvamento confirmado, logs sanitizados, limites, filtros e paginação.
- Retenção de diagnóstico de 90 dias testada sem remover a auditoria imutável de negócio.
- Chrome via Playwright: login, configuração MFA sintética, abertura e bloqueio do painel, operador recusado; desktop e celular sem erro de JavaScript ou transbordamento horizontal. Nenhuma credencial de cliente usada nos testes.
- Imagem Desktop/VPS: `sha256:5f791df54dd059dc1ef0ad587f95fae83a3df09351395aaff9b1923becc734f2`.
- VPS: saúde pública `status=ok`, schema 9; API do dono sem sessão retorna 401; quatro timers ativos. Serviços de status e retenção terminaram com Result=success e ExecMainStatus=0.
- Inventários anteriores/posteriores: os 11 contêineres fora da família do app permaneceram iguais. Contêiner anterior preservado para reversão.
- Evidência VPS: `/opt/sgc-codex-20260925/evidence/stage9-owner-audit-20261005`, incluindo SUCCESS, inventários e verificações.

## Erros e ajustes encontrados

1. Harness HTTP inicialmente importava módulos sem PYTHONPATH adequado; depois não enviava o cookie no caminho montado /SGC. Corrigidos; terceiro ciclo completo aprovado. Não eram falhas de produção.
2. Relatos do navegador poderiam amplificar eventos de negação: o endpoint de telemetria passou a registrar sua própria resposta somente na saída técnica, mantendo quota no banco para relatos aceitos.
3. Identidade após login e condomínio de ações de negócio precisavam de origem confiável: vinculados aos dados confirmados no servidor, sem aceitar identidade do navegador.
4. Paginação com horários iguais: cursor composto por horário e ID evita perder eventos.
5. Painel precisava expirar visualmente e impedir cache: bloqueio no horário autorizado e cabeçalhos no-store/CSP adicionados.
6. Retenção inicialmente dependia somente do tráfego: acrescentados timer diário no VPS e verificação diária oportunista; testes preservam auditoria de negócio.
7. Layout dos filtros e mensagens de indisponibilidade ajustados e revisados.
8. Uma chamada de administração terminou com CR de PowerShell no nome do serviço. Não alterou serviços; chamada repetida com texto normalizado e backup aprovado. Regras LF adicionadas para scripts e unidades.
9. Descoberta ampla de testes incluiu um script de integração que exige credenciais de banco em execução sem rede. Separada a execução de unidade desse script; os 64 testes de unidade passaram. A integração de banco já foi executada separadamente em banco sintético.

## Limites e ação pessoal necessária

Rodrigo está provisionado, mas a ativação pessoal do autenticador ainda precisa ser realizada pelo dono. Não foi redefinida sua senha nem fabricada uma confirmação de MFA real. Consulte manual-dono.md.

O diagnóstico não grava teclas, textos, fotos, senhas, tokens, cookies, mensagens brutas de exceção ou dumps. Registra ações e resultados operacionais. Relatos do navegador não são prova de sucesso; o resultado confirmado vem do servidor.

A fila offline é temporária, em memória, limitada a 20 eventos e ao mesmo usuário; perde-se ao fechar/recarregar a página. Durante indisponibilidade do banco, há saída técnica sanitizada, sem garantia de gravação no PostgreSQL.

O segredo do autenticador fica separado do Git e da imagem, em montagem somente leitura no Desktop/VPS. O pacote cifrado existente preserva banco e imagem, mas não é uma cópia de todos os segredos. Recuperar o acesso de dono também exige sua chave guardada com segurança ou reprovisionamento administrativo controlado; nenhuma rota de cliente permite isso.

Este painel não inclui edição global de conteúdo nem administração global de contas de clientes. Os bancos e contêineres sintéticos de QA são separados da produção; os contêineres de QA são parados ao concluir, preservando evidências.

## Publicação e cópia externa

- Código publicado na branch main de RLD1604/SGC: commit `1fe9cfc53f0c7ee5b32fd99164a2aa708d5592cb`; ls-remote confirmou a publicação. Atualização posterior deste recibo altera somente documentação.
- Backup final: `20261005T184950Z-b2d996f2`, imagem igual à implantada; SUCCESS e SHA-256 válidos. O serviço de backup restaurou o dump em PostgreSQL isolado antes de aceitar o pacote.
- Serviço de envio direto VPS→Drive terminou com Result=success, ExecMainStatus=0. Recibo last-success.json: status success, mesmo runId, files=4, verifiedAtUtc=2026-10-05T18:56:54Z. O serviço verifica os quatro arquivos e o pacote remoto antes de gravar esse recibo.
- Listagem remota final confirmou exatamente SUCCESS, manifest.json, sgc-recovery.tar.age e sgc-recovery.tar.age.sha256. SHA-256 do pacote: `f4761ecdf4d8c921eb2a9fb6c044f131004d40a3971d848252f1088866fd7e9d`.
- Indicador sanitizado do painel atualizado após essa confirmação; serviço terminou com sucesso.
- Contêiner de navegador QA desta entrega parado, sem remover os demais serviços ou as evidências.
