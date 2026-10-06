# Validação adicional para entrega da Beta

Data: 6 de outubro de 2026. Candidata: 0.2.7-beta.3, esquema 11. Testes com escrita limitados ao aplicativo QA em 127.0.0.1:19103/SGC e bancos exclusivos com prefixo sgc_owner_qa_. Nenhum convite nominal foi utilizado.

## Etapa 1 Acesso e recuperação

Aprovada no primeiro ciclo efetivo. Sete gates HTTP passaram em banco novo: expiração por inatividade e absoluta, replay do cookie após logout, senha antiga recusada após recuperação, todas as sessões anteriores revogadas, MFA preservado e solicitação rejeitada sem gerar token. Integração complementar em outro banco novo passou ativação de cinco contas sintéticas, política de senha, cifra do segredo MFA, CSRF, replay, quota, recuperação genérica, emissão exclusiva pelo dono, reset explícito do autenticador e recusa de reutilização do token.

## Etapa 2 Concorrência e carga controlada

Ciclo 1 interrompido antes de qualquer requisição de carga: runner procurava cookie sqa_csrf, mas o caminho /SGC usa cookie próprio. Corrigido para usar o CSRF emitido à sessão pelo aplicativo, sem alterar validação do servidor.

Ciclo 2 aprovado: três contas sintéticas, 12 criações concorrentes, 12 edições independentes, cinco edições sobre a mesma revisão com exatamente um sucesso e quatro conflitos 409, seis salvamentos simultâneos com foto e download validado, três criações e edições de informe e 60 consultas com seis requisições simultâneas. Conferência final confirmou revisões e valores persistidos.

Foram medidas 101 requisições HTTP controladas: p95 379 ms e máximo 470 ms, sem erro inesperado. Os quatro conflitos 409 são esperados e confirmam a proteção contra sobrescrita. Medição feita no Docker Desktop/QA local; não representa capacidade do VPS, internet ou grande escala. Não houve teste de estresse destrutivo ou chamada adicional à IA.

## Etapa 3 Compatibilidade

Ciclo 1: Chrome passou; Android emulado foi bloqueado no runner porque esperava Sair visível enquanto o menu móvel estava recolhido. Corrigida a condição para aguardar existência do controle e estado autenticado. O aplicativo não foi alterado.

Ciclo 2 aprovado: Chrome desktop, Android Pixel 5 emulado, iPhone 13 emulado e Edge desktop. Chrome e os dois perfis móveis navegaram por início, registros, informes e novo registro; verificaram ausência de overflow horizontal, TinyMCE inicializado, preenchimento e salvamento, recarga e persistência. Edge passou navegação autenticada. Zero exceções JavaScript.

Limite: os dispositivos móveis foram emulados em Chromium. Safari/WebKit, Android/iPhone físicos, câmera nativa e experiência humana dos convidados permanecem validações de campo, sem alegação de aprovação nesses ambientes.

## Etapa 4 Operação e acompanhamento

Health público confirmou status ok, versão beta.3 e esquema 11. Timers de backup interno e envio ao Drive ativos, últimos serviços success. Nova execução de backup foi detectada após o recibo anterior; envio do pacote mais recente acionado para conferir a mesma identificação em VPS e Drive.

Monitor diário SGC existente está ativo, com notificações apenas para falha, atraso maior que 30 horas ou ação necessária. A observação de vários dias continua pela automação; não equivale a vários dias de estabilidade já comprovada nesta execução.

Conferência final aprovada: backup 20261006T062542Z-16b1aca2 presente no VPS e Google Drive, recibo success para a mesma identificação, exatamente quatro arquivos e hashes idênticos verificados com rclone check. Pacote age também passou SHA-256 local. Painel de status do dono atualizado. Conteúdo editorial real permanece vazio no Desktop e VPS; cinco convites originais têm tokens, permissões e validade preservados.

## Evidências

Resultados sanitizados e screenshots sintéticos ficam em qa/results/beta-adicional-20261006, excluídos do Git. Runner reproduzível: qa/beta_additional_gates.cjs load ou compatibility. Credenciais e sessões QA permanecem em .secrets, sem impressão ou versionamento. Manuais ilustrados foram preparados com screenshots sintéticos, sem tokens reais.
