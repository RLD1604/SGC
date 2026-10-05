# Auditoria — Beta limpa, MFA individual e recuperação

2026-10-05, versão 0.2.7-beta.1, schema 10. Plano: plano-beta-mfa-recuperacao.md.

| Planejado | Executado / evidência |
|---|---|
| MFA nominal após ativação | Cinco convites individuais, senha escolhida pelo usuário e QR distinto; obrigatórios inclusive para Operador |
| Sessão com senha não abre dados | Integração rejeitou workspace e painel antes do segundo fator; re-login volta a exigir MFA |
| Segredos protegidos | Chaves pessoais cifradas com Fernet no banco; chave de cifra em montagem privada, fora de Git/imagem; QR apenas em resposta no-store após senha e CSRF |
| Recuperação sem SMTP | Fila privada, resposta pública genérica e quota; dono exige MFA e verificação humana para emitir token de 30 minutos; convite renovado vale 48 horas |
| Perda do telefone | Decisão explícita do dono, token de uso único; ao usar, revoga sessões e remove somente MFA do solicitante |
| Logs individuais | Identidade do servidor, ação, recursos/IDs, resultado, campos alterados sem valores; lixeira/restauração específicas; relatos do navegador distinguidos de acessos entregues pela API |
| Base inicial limpa | Desktop/VPS: records=0, editions=0, publications=0, media=0; dono ativo=1, convidados=5, owner grant=1; autenticação do dono preservada |
| Revisão e testes | 65 testes Python, privacidade Node, integração PostgreSQL e Chrome desktop/celular aprovados |
| Publicação segura | Mesma imagem saudável nos dois ambientes; outros contêineres iguais; banco e contêiner anteriores preservados; GitHub/Drive em confirmação final |
| Manuais | Cinco PDFs de uma página, login/perfil/token/expiração/MFA/recuperação; extração de texto e renderização revisadas, sem publicar tokens no Git |

## Testes e correções

- Integração em bancos exclusivos sgc_owner_qa_*: cinco ativações, complexidade de senha, token usado/expirado, cifra por usuário, CSRF, código inválido/reutilizado, limite de tentativas, isolamento antes/depois de MFA, acesso global negado aos clientes, recuperação genérica, dono sem step-up negado, cliente impedido de emitir token, emissão única, troca de senha, MFA reset e sessões revogadas.
- Leituras, edição, conflito de revisão, lixeira negada ao operador, lixeira/restauração de administrador em documento autorizado, IDs e ausência de conteúdo editorial nos logs.
- Primeiro teste ampliado revelou exigência antiga de um informe em edição: removida para permitir base realmente vazia e criação do primeiro registro. Diagnóstico repetido sem mudança e reteste após correção registrados separadamente.
- Teste de lixeira inicialmente supunha que Administrador editava rascunho privado de outro autor. A política vigente nega esse acesso; teste corrigido para preservar a política e usar documento próprio autorizado.
- Navegador encontrou cookie CSRF com nome diferente em /SGC: corrigido para usar a configuração do app. Integração ampliada para executar nesse caminho.
- Primeira navegação ocorreu antes de iniciar o servidor QA: aguardada saúde. Botão Sair fica oculto no menu mobile; teste passou a usar viewport desktop para essa ação, mantendo a conferência mobile do QR. Fluxo final completo passou sem erros de JavaScript.
- Preparador de banco novo não tinha adaptador UUID registrado. A tentativa ficou em banco novo isolado e foi revertida pela transação; banco ativo permaneceu intacto. Corrigido, testado em clone QA e repetido com destino novo r2, com sucesso.
- Um destino inicial de cópia de backup apontava para a raiz do workspace. Dump havia sido gerado antes da troca; cópia refeita dentro do repositório e verificada.
- Verificador somente de leitura no VPS ficou sem permissão ao executar como root sem capabilities sobre o segredo do banco, que pertence ao usuário do app. Repetido em contêiner temporário somente de leitura com DAC_OVERRIDE para as três montagens necessárias; cinco convites aprovados, sem exibir tokens/hashes. Não alterou o app ou banco.
- Cinco PDFs finais conferidos: uma página cada, token correspondente e nenhum token de outro participante, instruções de ambos os autenticadores e expiração. Previews de revisão usam token substituído, fora da pasta de entrega. Pasta privada com ACL restrita; manuais fora do Git.

- Revisão final da lixeira revelou bloqueio ao arquivar registro conferido. API passou a exigir leitura autorizada e perfil Administrador, preservar conteúdo e estado, rejeitar alteração de texto junto da operação e registrar revisão. Interface esconde lixeira do Operador. Integração QA _i aprovou arquivamento/restauração de registro ready e rejeitou adulteração; 65 regressões e privacidade Node repetidas com sucesso. Primeira chamada QA tinha PYTHONPATH ausente: corrigida somente a configuração do comando, sem alteração de banco ativo.

## Preservação e verificação

Dump inicial transferido do VPS para Desktop: SHA-256 `b4d035c9a059436e0f0bfe7aaeba1d88c148277f1c404acf31173dda48f673ee`.

Imagem final Desktop/VPS: `sha256:03130952c0fe95152b73358aeb5c3fd348ea306693c3881f32a4aa96f1af005d`. Saúde pública status=ok, schema 10. Evidências VPS: `/opt/sgc-codex-20260925/evidence/stage9-beta-mfa-trash-final-20261005`.

O banco anterior de cada ambiente permanece como condominio_pre_beta_20261005, com leitura somente por padrão. O alvo preparatório que falhou não substituiu banco ativo. Nenhum banco de outro projeto foi alterado. Não há espelhamento contínuo: os dois ambientes receberam a mesma base inicial, depois podem divergir.

Chaves MFA agora fazem parte somente do interior do pacote age cifrado, sob credentials/. Senha de banco e chave IA continuam sob custódia separada. Nenhuma chave/tokens/manuais privados foi incluída no Git ou imagem Docker.

## Limites transparentes

Não existe notificação externa automática da fila: o dono deve consultar o painel. A resposta pública não confirma se o usuário existe. O app não faz verificação de identidade humana; essa confirmação é responsabilidade do dono por contato conhecido.

Logs comprovam recursos entregues pela API e operações confirmadas; não comprovam que a pessoa leu cada campo nem guardam teclas, fotos ou conteúdo editorial. Browser reports são relatos não confiáveis. Diagnóstico tem retenção de 90 dias; auditoria de negócio continua imutável. Metadados de conteúdo entregue por workspace são limitados a 100 IDs por resposta.

Base “zerada” significa sem conteúdo editorial anterior; contas, convites, condomínio, estrutura e logs novos são necessários. Backups/bancos anteriores e rascunhos locais no navegador são preservados. Convites nominais expiram em 07/10/2026 às 17h25 (Brasília), uso único.

## Recibo final

Código e backup externo em finalização. Não considerar Drive aprovado antes de confirmar status success, mesmo runId e exatamente quatro arquivos.
