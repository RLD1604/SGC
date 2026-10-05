# Plano revisado — Beta limpa, MFA e recuperação assistida

2026-10-05. Escopo autorizado: implementar, revisar, testar, corrigir e publicar. Nenhum outro projeto será alterado.

1. Preservar bancos atuais e fonte; testar backups. Implementar e testar somente em PostgreSQL sintético.
2. Cada convidado define senha pelo token individual e configura seu próprio autenticador por QR. MFA obrigatório para os cinco convidados, inclusive André; isso não altera os dois perfis existentes. Uma sessão que só confirmou senha não pode ler ou editar dados.
3. Segredos MFA individuais cifrados no banco com chave de servidor separada da imagem/Git. Códigos com limite de tentativas e prevenção de reutilização. Tokens de convite de uso único, com expiração explicitada no manual.
4. Recuperação sem SMTP: formulário público cria solicitação privada na fila do dono, resposta genérica e limitação de abuso. Apenas rodrigo, após MFA de dono, confirma identidade por contato conhecido e emite token curto e de uso único; entrega pessoal/manual. Não devolver token pela solicitação pública. Perda do telefone exige marcar redefinição de MFA e revogar sessões ao confirmar recuperação. Não permitir que administradores recuperem/promovam o dono.
5. Logs identificam usuário, condomínio, ação, recurso consultado/alterado/excluído e resultado, sem conteúdo, credenciais ou texto editorial. Leituras entregues pela API são evidências de acesso; navegador não comprova leitura humana. Manter histórico imutável após iniciar o piloto.
6. Publicação: preparar banco novo vazio, preservar conta/senha/autenticador real de rodrigo e criar cinco convites no SQA. Os bancos anteriores são arquivados, sem apagar seu conteúdo, além dos backups. Desktop recebe uma cópia da mesma base inicial do VPS, sem espelhamento contínuo. Não copiar sessões para Desktop.
7. Produzir cinco manuais privados com token, login, perfil, link, expiração, MFA, recuperação e aviso sobre logs. Tokens não entram no Git/saída dos comandos. Manual geral e auditoria podem ser publicados sem tokens.
8. Verificar saúde, isolamento, fluxos positivos/negativos, banco sem registros/informes/mídias/publicações, um dono ativo e cinco convidados; publicar código e confirmar backup cifrado VPS/Drive final.

## Revisão do plano

- “Sem dados” significa sem conteúdo editorial anterior; contas, convites, condomínio e novos registros operacionais são necessários. Não prometer banco literalmente vazio.
- Mensagem pública de recuperação nunca revela se login existe; solicitação não concede acesso nem altera senha.
- Token de recuperação não basta para remover MFA por padrão; redefinição somente após decisão explícita do dono e confirmação de identidade.
- Preservar a conta real e segredo do dono; não reconfigurar seu telefone automaticamente.
- Na falta de SMTP, o app guarda a solicitação e o dono vê ao abrir o painel; não prometer notificação externa.
- Backups antigos contêm dados anteriores e serão preservados, não tratados como base inicial limpa.
- A autoridade global continua separada do perfil administrador. Conteúdo global do dono permanece fora desta entrega conforme decisão anterior.

Estado: planejamento/revisão concluídos; implementação em andamento.
