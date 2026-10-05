# Auditoria da mudança — 2026-10-05

## Planejamento versus execução

| Critério | Evidência e resultado |
|---|---|
| Backup antes de alterar | Dump local validado e fonte HEAD arquivada; backup cifrado VPS antes de cada implantação, SHA-256 OK. |
| Dois perfis | Operador e Administrador implementados no backend e nos convites; exatamente um perfil por convite. |
| Histórico preservado | Grants antigos são revogados, não apagados; novos grants mantêm validade e revogação futura. Eventos registram IDs de origem e destino. |
| Migração segura | Ensaio transacional revertido antes de aplicar; segunda execução sem criar novamente grants. Schema 7 local e VPS. |
| Permissões e isolamento | 40 testes Python passaram, incluindo regressão, estados, expiração, revogação e desativação restrita ao condomínio; teste JavaScript passou. Prova transacional no PostgreSQL local e VPS validou convite e desativação sem alterar outro vínculo; todos os dados sintéticos revertidos. |
| Testadores SQA | 01 e 02 Operador; 03 Administrador, confirmado no PostgreSQL do VPS. |
| Manuais | Dois PDFs de uma página, renderizados e revisados visualmente; fontes Markdown e gerador incluídos. Substituem instruções antigas de Editor. |
| Implantação | Docker local e VPS saudáveis na versão 0.2.5-beta.1/schema 7. Mesma imagem sha256:02dd2ed8ec441966367c03f66cc37f82ef98f9e7ee617ca4621f88d3a1d0d5bf. Hashes de auth.py, authorization.py, schema.sql e auth-ui.js iguais. Containers anteriores preservados; outros 11 containers mantiveram nomes e imagens. |
| GitHub e Drive | Código publicado na main (7d63d0f). Backup final 20261005T171633Z-de24f335: SHA-256 validado, Drive com exatamente quatro arquivos e last-success.json com mesmo runId/status success/files 4. Relatório final segue em commit documental separado. |

## Erros encontrados e tratamento

1. Python local sem Flask: suíte executada em container com dependências do app.
2. Container de produção somente leitura: testes movidos para container descartável com volume somente leitura e sem rede.
3. Tentativa de marcar imagem antiga por ID indisponível: imagem anterior 5afc88c preservada por tag e fonte completa arquivada.
4. Interface somava permissões de condomínios diferentes: cálculo limitado ao condomínio corrente; teste específico incluído.
5. Convite malformado podia causar erro de tipo: validação exige uma string válida e um único perfil.
6. Desativação global de usuário: corrigida para desativar somente membership e grants no condomínio autorizado. Sessões e vínculos de outros condomínios preservados.
7. Convite podia alterar identidade global de usuário convidado em outro condomínio: conflito agora recusado se existir outro vínculo.
8. Harness de teste podia importar fonte antiga da imagem: diretório de trabalho explicitamente /tests; suíte repetida com a fonte corrigida (40 testes OK).
9. HTTP 404 transitório durante troca do container: repetição da saúde pública terminou com sucesso no primeiro deploy.
10. Comando de conferência SQL tinha aspas incompatíveis com PowerShell: repetido via stdin, sem alterações ao banco.
11. Integração SQL precisava registrar o adaptador UUID, como o servidor faz: corrigido; teste passou local e VPS, com rollback confirmado.
12. Renovação da autorização do Drive não podia salvar rclone.conf sob ProtectSystem=strict: configuração renovável movida para /var/lib/sgc-backup-drive (pasta já autorizada para escrita). Original preservada, arquivos com permissão 0600; leitura autenticada e listagem dos quatro arquivos passaram. Backup final terminou com sucesso.
13. Git interpretava PDFs como texto: adicionada regra binária para preservar documentos; diff --check passou.

## Limites e pendências de produto

A administração de convites continua usando o suporte/CLI e a API já existente. A API de emissão depende de entrega de tokens configurada; não foi criada uma tela de gestão de usuários nesta mudança.

Superusuário global não existe nesta implementação. Ele não deve ser anunciado como entregue. A revisão não equivale a provar ausência de qualquer falha possível no aplicativo: cobre as regras e os fluxos afetados por esta mudança.

Rollback de código e rollback da migração do banco são operações distintas. A imagem anterior ao schema 7 requer reverter a migração ou restaurar o backup para compreender os perfis novos; não executar restauração sobre produção sem analisar escritas posteriores.
