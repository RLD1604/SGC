# Painel exclusivo do dono

Acesse https://sq.srv1178310.hstgr.cloud/SGC/owner.html e entre com `rodrigo` e sua senha atual.

1. Sua conta, senha e autenticador atuais continuam válidos. Se o autenticador já estiver configurado, use-o e siga para a confirmação do passo 3. Só configure um QR quando o app solicitar a primeira configuração.
2. No Google Authenticator, toque em **+ → Ler código QR**. No Microsoft Authenticator, escolha **Adicionar conta → Outra conta → Escanear código QR**. Aponte a câmera para o QR mostrado no SGC. Se estiver usando apenas o telefone, abra **Não consigo escanear** para cadastrar a chave manualmente, com código baseado em tempo. Guarde a chave em local privado; não envie a chave nem o QR a operadores ou em mensagens.
3. Informe a senha e o código de seis números exibido pelo autenticador para abrir o painel.
4. Consulte os indicadores e filtre os eventos por usuário, condomínio, ação, resultado ou código de atendimento.
5. Use **Bloquear** ao terminar. A autorização adicional expira após 15 minutos. Sair encerra a sessão.

O painel é exclusivo do dono. Após confirmar senha e autenticador, use Todos os espaços → Abrir para acessar cada condomínio, inclusive textos, fotos e rascunhos privados. Sua identidade permanece rodrigo e suas ações ficam auditadas. Na área de trabalho, use Trocar espaço / painel do dono para escolher outro. O acesso global expira em 15 minutos e exige nova confirmação. Rascunhos locais do dono são separados por condomínio. Prefira trabalhar em um espaço por vez: trocar em outra aba bloqueia operações na aba anterior até reabri-la. As regras de revisão, publicação imutável e conferência por outra pessoa continuam vigentes. Os perfis de condomínio continuam sendo Operador e Administrador; nenhum deles permite promover uma pessoa a dono.

Os operadores não precisam ativar logs. Se uma ação falhar, devem informar ao dono o código de atendimento mostrado na tela e o que tentavam fazer, sem enviar senha ou token. Eventos relatados pelo navegador são identificados como relatos, não como confirmação de salvamento.

A senha tem no mínimo oito caracteres, incluindo número, letra maiúscula e caractere especial. O autenticador é uma proteção adicional ao acesso do dono.

Se perder o telefone e a chave, a recuperação exige manutenção autenticada no servidor, com backup prévio, invalidação das provas de acesso e novo provisionamento controlado. Não existe recuperação global pelo perfil Administrador de condomínio.

## Recuperar acesso de um convidado

Na seção Recuperação de acesso do painel aparecem as solicitações que as pessoas enviam pela tela de login. Não há envio de e-mail ou aviso externo automático: abra o painel para consultar a fila.

Confirme a identidade por um telefone ou contato que você já conhece; uma solicitação no app sozinha não comprova identidade. Registre como confirmou, marque a confirmação e clique em Emitir token. Entregue o token pessoalmente ao solicitante, que deverá definir a nova senha no formulário Token de recuperação. Vale 30 minutos, uma única vez.

Se a pessoa perdeu o telefone/autenticador, marque Também redefinir autenticador. A chave antiga será removida quando o token for usado; as sessões antigas serão revogadas e a pessoa precisará cadastrar o novo QR no próximo login. Para perda apenas da senha, o autenticador continua obrigatório e não é removido. Para um convite expirado, o painel emite um novo token de ativação, válido por 48 horas. Um pedido indevido pode ser recusado.

Administradores de condomínio não podem emitir esses tokens nem recuperar a conta do dono. Não envie senhas ou QR no campo de verificação de identidade.
