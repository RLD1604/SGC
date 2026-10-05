# Rastreamento e painel do dono — execução auditável

2026-10-05. Autorização: executar as etapas 0 a 5, revisar, comparar e auditar.

0. Backup PostgreSQL e fonte; verificar identidade rodrigo. Aprovado: dump condominio-20261005T180947Z-ae4a8a01e750415e985bf53a6f2d54fe.dump, SHA-256 CD07BA4A7F89080B459B469DFB8E2AEE4C33D65199B7E519F5CE28CA26BB6721; fonte pre-owner-audit-20261005.zip. Rodrigo ativo local.
1. Diagnóstico servidor: IDs emitidos pelo servidor, resultado após confirmação HTTP, JSON técnico sanitizado fora do banco e tabela própria com retenção de 90 dias. Auditoria de negócio permanece imutável. Testar falha do banco sem recursão.
2. Navegador: relatos limitados, sem texto/URL arbitrária/campos; CSRF, sessão, limitação de volume e indicação explícita de que o relato não comprova sucesso. Mostrar código de atendimento.
3. Dono: tabela de autorização global separada dos perfis de condomínio; provisionamento local para rodrigo, sem promoção pela API dos clientes. Reconfirmar senha e código TOTP, prova temporária por sessão e bloqueio de reuso/tentativas.
4. Painel: somente metadados de eventos, filtros e indicadores de app/backups. Nenhuma abertura global de conteúdo editorial será adicionada nesta entrega. Acesso ao painel auditado.
5. Revisão: testes positivos/negativos, PostgreSQL com fixtures revertidas, UI, backup antes de deploy, local→VPS→GitHub→Drive, igualdade de imagens/arquivos e inventário dos demais serviços.

## Revisão anterior à implementação

- Não tratar cliques ou relatos do browser como sucesso confirmado.
- Não armazenar mensagens de exceção, stack traces ou payloads potencialmente editoriais no diagnóstico.
- Não confiar em IDs, identidade, condomínio ou permissões enviados pelo navegador.
- Segredo TOTP fora do Git/imagem; montagem somente leitura. Ativação exige ação do dono no autenticador e não será declarada concluída sem essa ação.
- Consultas globais limitadas/paginadas e parâmetros SQL; sem acesso editorial implícito.
- Retenção somente na tabela de diagnóstico, nunca nas decisões/aprovações imutáveis.
- Limite de três ciclos por erro; parar se o terceiro não aprovar. Registrar erros do harness separadamente dos erros do app.

Estado: etapas 0 a 4 implementadas e verificadas; etapa 5 com Desktop/VPS verificados, publicação e cópia externa em finalização. Evidências em auditoria-rastreamento-dono.md. A configuração pessoal do autenticador pelo dono permanece necessária.
