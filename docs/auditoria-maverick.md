# Teste real Maverick — QA aprovada; publicação em preparação

## Ambiente e limite

Chrome real, interfaces/API sem simulação de respostas, PostgreSQL exclusivo sgc_owner_qa_maverick20261005_a e porta local 19102/SGC. Contas sintéticas Maverick (Operador), Iceman (Operador) e Viper (Administrador), convite, senha e MFA individuais. Nenhuma dessas contas foi criada no Desktop/VPS de produção; os cinco participantes mantêm seus convites. A versão publicada e seu backup final 20261005T220209Z-a0c3a4d8 permanecem preservados. Credenciais/QR/cookies de QA somente em .secrets, fora de Git e relatórios.

## Etapa 1 — aprovada após correções

Ativação/MFA, limite do assunto, validação de envio vazio, todos os campos, acentos/emoji/escape HTML, persistência PostgreSQL após recarregar, foto horizontal/vertical, etapas e legendas, cancelamento/giro/aplicação/restauração no editor de fotos, oito categorias e três situações de serviço, revisão real Groq com consentimento sem alterar o original, recuperação de rascunho local, privacidade frente a outro Operador, envio para revisão, pedido de complemento por Viper, correção e reenvio por Maverick, conferência por Viper, busca/filtros e registro no celular. Sem exceções JavaScript nessa etapa.

Defeitos reproduzidos e correções candidatas:
- Menu de revisão oculto por atributo hidden era exibido devido ao CSS. Regra explícita [hidden] com display:none corrige.
- Editar registro era oferecido em review/ready embora API negasse alteração. Interface agora permite edição somente em draft/fix e bloqueia formulário via rota direta nos demais estados.
- Botões de pedir complemento/conferir permaneciam em ready. Agora somente em review; lixeira continua exclusiva de Administrador.

## Etapa 2 — três ciclos de correção, não aprovada

Primeira execução encontrou perda de blocos em sequência rápida: cinco persistidos onde dez eram esperados. Ciclo 1 bloqueou campos e ações durante gravação: todos os modelos passaram, mas ocultar foto após escolher capa não persistia. A capa salvava sem recriar os handlers, que mantinham referência ao bloco substituído pela resposta do servidor.

Ciclo 2 atualizou a tela após salvar capa; erro seguinte foi perda de legenda/formato na sequência rápida. Ciclo 3 estendeu bloqueio até terminar também a confirmação do rascunho local e evitou restauração tardia se o usuário já editou a tela. Nesse ciclo passaram: criação/recarga de todos os modelos e bloco personalizado; duplicar/subir/descer/remover/desfazer; legenda, portrait, destaque, capa e ocultar/mostrar após recarga; prévia desktop/mobile e download de rascunho marcado.

Bloqueador atual: ao clicar Enviar revisão para aprovação na jornada completa, o botão não foi substituído pelo estado Aguardando aprovação; timeout de 12 segundos. Relatório do ciclo não registrou erro HTTP do endpoint de submissão, nem exceção JavaScript; registrou 429 somente em diagnostics/client devido ao volume automatizado, que é limitação prevista de telemetria e não comprova a causa do bloqueio. Não presumir causa sem instrumentar o clique, salvamento anterior, handler e requisição de submissão. Tela de falha preservada em qa/results/maverick/phase-2-failure.png.

Também foi preparada proteção de tela de leitura para revisão de informe já enviada; ainda precisa de validação integral após destravar a submissão. Não classificar essa mudança como aprovada.

## Falhas de execução do harness, separadas de defeitos do app

Uma navegação começou antes de o QA estar pronto (ERR_EMPTY_RESPONSE), sem mudança de dados; repetida após inicialização. Leitura do editor de registro presumiu handle global editor, que nessa tela é nulo: teste corrigido para tinymce.get('record-text').getContent(). Um script de edição local usou leitura CP1252 implícita e não aplicou alteração: repetido com UTF-8 explícito. Essas falhas não foram correções do aplicativo e não foram contadas como ciclos de saneamento do app.

## Próximas etapas planejadas, ainda não executadas

Diagnosticar submissão com IDs/requisições e mensagem imediata; corrigir e repetir Etapa 2 mediante nova decisão com o usuário. Etapa 3 preparada no harness: devolução de informe, ajuste/reenvio, aprovação por Viper, publicação, leitura/download por Maverick, igualdade dos bytes oficiais, lixeira/restauração da fonte sem alterar publicação, e bloqueios de acesso do Operador ao dono/convites. Após isso: indisponibilidade e recuperação do salvamento, conflito de duas sessões, nota solta, re-login MFA e recuperação de senha, logs e banco, regressões e publicação Desktop→VPS→GitHub→Drive.

## Conclusão histórica antes da retomada autorizada

Parada deliberada após três ciclos da Etapa 2. Não avançar à Etapa 3, não publicar a candidata e não recomendar entrega ainda. As correções estão somente nos arquivos de trabalho e no servidor QA. Preservar banco, relatórios e conta sintética para retomar. Não há promessa de teste exaustivo de todas as combinações possíveis.

## Diagnóstico adicional somente de leitura após a parada

A auditoria SQL encontrou edition.submit=success e o último informe em pending_approval, com revisão imutável criada. Portanto, o envio chegou ao banco; o bloqueador reproduzido é a atualização da tela, que continua oferecendo Enviar revisão para aprovação. O harness registrava apenas respostas HTTP >=400, não todas as respostas; ausência no relatório de erros não significa ausência de requisição. Não afirmar falha de gravação do envio.

Hipótese forte por inspeção: o handler captura e antes de await save(); persist() substitui state pela cópia confirmada, e passa a apontar para objeto anterior; ao atualizar e._workflowState depois da submissão, o novo objeto em state permanece draft e render mantém o botão. Há padrão semelhante em outros handlers que usam referências após await save(), e precisa ser revisado sistematicamente. Solução proposta: após cada confirmação, usar o documento retornado/atual em state ou recarregar workspace antes de renderizar/navegar; repetir submissão, devolução, aprovação e publicação, com confirmação simultânea de UI/API/BD. Não implementada após atingir o limite de ciclos.

## Retomada autorizada — até cinco tentativas por bloqueador

Após a terceira falha, foi feita pausa, revisão das evidências SQL/UI e planejamento. A revisão confirmou que a submissão estava no banco, e que referências capturadas antes de save tornavam-se antigas porque a gravação substitui state por uma cópia. Plano revisto: usar a revisão do objeto atual depois de save e consultar workspace confirmado após submissão, devolução, aprovação e publicação. Bloquear o botão de submissão durante toda a ação. Manter estados/revisões e regras do backend. Comparação planejado/executado: refreshWorkspace central implementado, quatro transições consultam estado canônico, submissão usa revisão atual, botão protegido. Aprendizado: todo handler que cruza await save deve reencontrar objetos por ID ou renderizar após o retorno; a resposta HTTP de sucesso sozinha não comprova atualização da tela. Próximo teste é a tentativa 4 da etapa de informes; se falhar, revisar antes da 5, e parar caso persista após a quinta.

## Regra definitiva de tentativas — autorização do usuário

Máximo de cinco tentativas por etapa/bloqueador. Havendo erro na terceira, interromper a execução antes da quarta: revisar evidências e causa, planejar a solução, revisar o planejamento, corrigir, comparar implementação com o planejado e registrar o aprendizado. Só então executar a quarta e, se necessário, a quinta tentativa. Não avançar enquanto houver erro ou pendência da etapa atual; se a quinta falhar, parar e apresentar evidências e opções ao usuário. Cada tentativa registra teste, resultado, erro, causa confirmada ou hipótese, correção e evidência da repetição. Falhas do harness devem ser identificadas separadamente de defeitos do aplicativo.

Atualização factual: Etapa 2 passou na quarta tentativa após a revisão registrada acima. Na Etapa 3, a segunda execução confirmou devolução, ajuste/reenvio, aprovação, publicação, download oficial e preservação da publicação ao arquivar/restaurar a fonte. O último teste permanece pendente: a emissão de convite por Operador retornou 503, embora se esperasse 403. Inspeção confirmou que issue_invitation verifica a configuração de entrega antes da autorização; no ambiente QA não há entrega configurada. Nenhum convite foi emitido. Revisar a ordem de autorização/configuração e seu teste antes de concluir a etapa; não interpretar esse resultado como acesso concedido.

## Etapa 3 — repetição do bloqueador, tentativa 3

Causa confirmada: a ausência de AUTH_DELIVER_TOKEN produzia 503 antes da checagem de permissão. Isso não permitia emitir convites, mas mascarava a negação de acesso esperada. Plano: manter validações, verificar escopo e autorização antes de consultar a configuração de entrega. Executado em auth.py; somente o contêiner QA recebeu a alteração. Teste de regressão verifica Operador negado com 403 mesmo sem entrega e usuário autorizado recebendo 503 sem entrega, sem acessar banco. Doze testes unitários de autenticação passaram.

Repetição real no Chrome (QA_PHASE=3, QA_SKIP=5): sessão/MFA existente confirmada, painel do dono negado, emissão de convite negada com 403, nenhuma exceção JavaScript. Exit code 0. Os quatro fluxos positivos anteriores não foram repetidos nesta execução: já passaram na tentativa 2, conforme relatório preservado. Comparação: o ajuste corresponde à ordem de verificação planejada, preserva a falha segura quando entrega indisponível e não emite convite. Aprendizado: testar autorização também com dependências ausentes para não mascarar a recusa por erro de configuração.

Pendências gerais continuam: auditoria das respostas 404 de diagnostics/client observadas na execução anterior, testes de indisponibilidade/conflito e demais jornadas, regressão final e publicação. Desktop/VPS de produção e GitHub não receberam esta candidata. O bloqueador específico da etapa 3 está saneado; não declarar a bateria inteira concluída.

## Etapa 4 — revisão após a terceira execução com erro

Execução 1: automação tentou segundo diálogo após uma navegação ainda em curso; execução 2: networkidle não convergiu, por isso foi descartado como critério de prontidão; execução 3: marcador da rota anterior foi aceito durante ida/volta à mesma edição de nota. Consulta SQL somente de leitura confirmou local vazio no servidor, portanto a alteração a descartar não foi gravada. Plano revisto: invalidar marcador da tela antes de navegar, esperar data-route da renderização atual e aguardar o editor correspondente; recarregar explicitamente quando destino já é a rota atual. A marca de renderização não muda permissões ou dados. Implementado conforme plano. Aprendizado: URL e presença de um editor antigo não provam que a nova tela abriu. A tentativa 4 verificará os fluxos reais com essa sincronização; máximo continua cinco.


## Etapa 4 — quinta tentativa e parada obrigatória

Tentativa 4: nota e rejeição de HTML como foto passaram; continuar/descartar/salvar antes de sair passaram; interrupção real de rede, download JSON e reconexão passaram. O harness consultou tinymce durante a troca de documento e gerou ReferenceError na sua própria função de espera. Corrigida a espera para primeiro verificar a existência de tinymce. Isso não foi exceção lançada pelo app.

Tentativa 5: passaram nota, campos opcionais, rejeição de arquivo, proteção de navegação, queda/reconexão e conflito real entre duas abas. PATCH obsoleto retornou 409 como esperado; não houve sobrescrita do dado vencedor, o JSON preservou a alteração concorrente e a cópia local sobreviveu à recarga. Depois, o teste de telemetria confirmou o recebimento do log do Administrador para a fonte conferida, com a correção do estado do documento em server.py. A execução parou ao abrir Iceman para a prova negativa: auth/session=401 e timeout esperando logout, pois account() pressupõe que cookies guardados continuam válidos e não refaz login.

Diagnóstico somente de leitura: sessão de Iceman expirou por inatividade, sem revogação; usuário permanece active. Viper permanece com sessão válida. Browser descartou cookies expirados de Iceman. Isso é comportamento esperado de segurança; a falha está no harness, que não trata reentrada após expiração. A consulta inicial usou nome incorreto de coluna expires_at e não fez alteração; corrigida para idle_expires_at/absolute_expires_at.

Plano proposto para retomada, sem executar sexta tentativa: ensinar account() a detectar o formulário de login quando houver estado privado salvo, reentrar com a senha sintética e MFA já cadastrados, aguardar código novo se houver bloqueio contra replay; nunca reativar convites usados nem prolongar sessões artificialmente. Revisar essa alteração e repetir as verificações ainda pendentes de privacidade da telemetria, logout/reentrada e recuperação. Depois rodar regressões e comparar planejamento/execução antes de publicar.

Regra respeitada: interrompido após cinco execuções da Etapa 4; não avançado à etapa seguinte e não publicada a candidata. Os relatórios preservam resultado/skipped por execução. Confirmação somente de leitura no banco real local: records=0, editions=0, official_publications=0, activeusers=1, invitedusers=5. Não transferidos registros ou usuários sintéticos a produção. Correções permanecem no diretório de trabalho e no contêiner QA. Não executada nova classificação Jev nesta etapa; resultados descritos são do navegador/API/PostgreSQL reais.


## Retomada autorizada e revisão final

Usuário autorizou o plano de reentrada. account() agora espera o estado de autenticação efetivo, distingue primeira ativação de reentrada com chave já cadastrada, usa senha+MFA quando sessão expira, preserva cadastro e aguarda novo contador de TOTP quando necessário. Não altera validade de sessões nem reaproveita convites consumidos. Retomada 1: teste esperava 403 para workspace sem MFA; implementação corretamente usa 401, expectativa corrigida após revisar require_session. Retomada 2: revelou clique antes do handler de MFA estar pronto. Corrigido app: botão Confirmar permanece desabilitado até setup e handlers terminarem; erro de setup mantém confirmação desabilitada. Retomada 3 passou nos testes pendentes. Repetição integral da Etapa 4 passou em uma execução, sem exceções JavaScript.

Repetição das jornadas anteriores: registros/fotos/IA/privacidade/revisão passou na segunda execução. Primeira falhou porque harness recarregou acervo do Administrador em vez de reabrir registro depois de reenvio; banco confirmou review, abertura explícita corrigiu o teste. Informes/blocos e publicação completa passaram cada um em uma execução. Códigos 409 do conflito e 401/403/404 de acesso recusado são verificações esperadas. 429 da telemetria decorre da quota compartilhada sob volume automatizado; é bloqueio de volume, não perda dos logs de transações de negócio. 404 ao tentar registrar leitura de fonte retornada/privada pode ser recusa de escopo esperada, distinta do defeito corrigido para fontes conferidas.

Regressões finais na imagem sgc-codex:maverick-20261006: 66 testes Python aprovados, privacidade/volume de diagnostics.js e dois perfis na interface aprovados. A primeira execução após atualizar cache CSS tinha duas expectativas literais antigas de URL sem query; o teste passou a validar o mesmo caminho com versão opcional, mantendo restrição ao prefixo, e a repetição passou. Integração PostgreSQL nova e exclusiva passou: cinco ativações, política de senha, MFA cifrado, isolamento de sessão pendente/CSRF, replay e quota, recuperação genérica, emissão exclusiva pelo dono, reset de MFA, token único, revogação, acesso global do dono e logs identificados. Auditoria Maverick passou na segunda execução após corrigir nome de coluna no script, sem alterar dados: dois artefatos oficiais com hash válido, 12 tipos de ações, 176 visualizações identificadas, recuperação de Maverick na fila e nenhuma senha/token sintético no JSON de logs.

Jev executado como classificador consultivo: modelo jev-1.13.0, uma chamada, 1393 tokens de entrada e 320 de saída. Concordância em cinco de cinco incidentes sintéticos com análise humana. Nenhum conteúdo de cliente, senha, chave, cookie ou dump foi transmitido. Não substitui os resultados funcionais.

Comparação plano/execução: reentrada por senha+MFA implementada e validada; isolamento da telemetria validado; logout/recuperação/reentrada validado; jornadas anteriores repetidas; regressões e auditoria de BD concluídas. Versão candidata 0.2.7-beta.2. Os manuais e convites reais não foram regenerados nem consumidos; verificação somente de leitura confirmou conteúdo=0, dono ativo=1, convites válidos=5.

Backup pré-publicação: dump local sgc-pre-maverick-20261006.dump, SHA-256 488db978ebe5c893d22e7ebf1a94af4c114e5fc73cd7e0073597ec6869ae5046. Primeira execução VPS falhou silenciosamente com exit 1; causa não confirmada. Acrescentado trap que registra apenas linha/código, preservando script anterior; segunda execução passou com restauração de 37 tabelas. Não afirmar que instrumentação corrige causa desconhecida. RunId pré-publicação 20261006T004039Z-e50634c5: SUCCESS, manifesto, pacote cifrado e SHA válido; cópia VPS→Drive terminou success para o mesmo runId. Publicação ainda depende da verificação pós-troca e backup final.
