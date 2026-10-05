# Acesso global exclusivo de rodrigo — 2026-10-05

## Plano e revisão

Usar a conta existente, sem mudar senha, QR ou convites. Proprietário comprovado por grant exclusivo no banco e confirmação de senha/TOTP com validade de 15 minutos. O painel lista todos os condomínios; entrar seleciona um único espaço e cria a associação administrativa do dono quando necessária. Dono pode consultar rascunhos privados e editar conteúdo ainda editável; estados, revisão concorrente, conferência por outra pessoa e publicação imutável permanecem obrigatórios. Clientes não recebem essa exceção.

Revisão: nunca confiar em platformOwner/ownerVerified enviados pelo navegador; autoridade recarregada no PostgreSQL por requisição, com prova válida da sessão. Associação automática do dono tem basis exclusivo e deixa de autorizar quando a autoridade de dono for revogada. Cookie HttpOnly seleciona espaço mas não concede autoridade. API também confere espaço esperado da aba. Rascunhos locais do dono separados por condomínio. Sem alterar conteúdo, contas convidadas ou autenticação existente.

## Execução e testes

Implementado no backend, painel, área de trabalho e armazenamento local. Novo registro/informe recebe condomínio selecionado, substituindo o valor fixo sqa. Sessão do dono sem confirmação é redirecionada ao painel e workspace retorna 403. Após expiração/bloqueio, a API recusa acesso editorial. Filtro da API limita os documentos ao espaço escolhido; mídias continuam vinculadas à autorização do documento. Aprovações usam grant administrativo real para manter trilha verificável.

Integrações em bancos QA exclusivos spaces_a e spaces_b aprovadas: acesso de dono a documento privado de terceiro, edição autorizada, seleção de segundo condomínio sem associação prévia, workspace filtrado, CSRF, identificador inexistente, administrador comum negado, cookie de espaço forjado sem ampliação de permissão, conflito entre abas, prova expirada e autoridade revogada. Fluxos anteriores de cinco convites, MFA, recuperação e auditoria repetidos com sucesso. 65 testes unitários aprovados.

Chrome desktop/celular: ativação, QR, MFA, recuperação, fila exclusiva, botão Abrir SQA, identificação do dono/espaço, retorno ao painel, Bloquear e redirecionamento obrigatório para confirmação. Sem erros JavaScript. Revisão encontrou banner sobrescrito pelo aviso Beta: classe separada corrigida antes do teste final. Revisão também identificou colisão de rascunho novo entre espaços e acrescentou chave por condomínio apenas para dono, preservando rascunhos dos demais usuários.

## Publicação

Em confirmação. Backup anterior cifrado e verificado: 20261005T205140Z-fba9311e no VPS e Drive. Nenhum dado editorial será criado em produção pelos testes.
