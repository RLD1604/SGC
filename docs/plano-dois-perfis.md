# Dois perfis — plano e auditoria

Data: 2026-10-05. Estado: execução em andamento.

## Contrato aprovado

Operador cria/edita/envia registros próprios ou atribuídos, consulta fontes conferidas, monta/envia informes e usa IA. Não revisa registros, aprova, exporta publicações ou administra contas.

Administrador executa o fluxo editorial e administra contas exclusivamente no condomínio vinculado. Estados de documentos, expiração/revogação de permissões, revisões imutáveis e isolamento permanecem obrigatórios.

## Etapas e critérios

0. Inventário e backup: preservar fonte e dump PostgreSQL, validar SHA-256.
1. Autorização: implementar os dois perfis; testar permissões positivas, negativas, estados e isolamento.
2. Migração e convites: manter histórico de grants/decisões; novos convites aceitam exatamente um dos dois perfis. Migração transacional e idempotente com auditoria. Testadores 01/02 Operador, 03 Administrador somente SQA.
3. Interface e manuais: nomes e ações coerentes; manual separado por perfil, sem credenciais.
4. Local: testes de regressão, migração e saúde Docker. Até três tentativas por falha; não avançar com erro.
5. VPS: backup validado antes da implantação; preservar rollback e outros containers; validar saúde e permissões.
6. GitHub e Drive: publicar somente fontes sem segredos; cópia cifrada de recuperação; comparar versões e hashes.
7. Auditoria: comparar cada critério com evidência e registrar pendências.

## Revisão do plano

Não trocar nomes de grants históricos: aprovações referenciam seus IDs. Perfis antigos permanecem legíveis no backend para auditoria, mas não são oferecidos em convites novos. Migração deve preservar períodos de validade e registrar as alterações.

Superusuário global não foi encontrado no código: não declarar essa função entregue. Ela exige projeto próprio de autorização global e auditoria.

## Evidências

Backup local validado: condominio-20261005T165602Z-16e3fd47b9e448da99d758e184d9abf2.dump; SHA-256 F41C9B280D5BE5DEBE76B6509DC1D898946E1084B693C9662169355685807D82. Cópia externa deste backup ainda não configurada.
