# QR Code do autenticador — 2026-10-05

Versão 0.2.6-beta.2, schema 9 preservado. QR gerado pelo servidor SGC em memória, sem arquivo persistente ou serviço externo. O endpoint de matrícula continua exigindo sessão do dono, CSRF e confirmação de senha. Uma matrícula já concluída não revela novamente a chave ou QR.

A URI é otpauth/TOTP, SHA1, seis dígitos e período de 30 segundos; compatível com cadastro de contas no Google Authenticator e de Outra conta no Microsoft Authenticator. Não se trata de notificações de aprovação da Microsoft.

O QR aparece no passo de configuração; chave manual disponível em Não consigo escanear. Ambos são removidos da tela após confirmação. CSP permite imagens data: apenas no painel para exibir a imagem PNG em memória. Resposta de matrícula e HTML continuam no-store. Manual atualizado com instruções dos dois aplicativos.

## Verificação

- 65 testes Python de unidade/regressão aprovados.
- QR de exemplo, sem segredo real, decodificado por biblioteca independente zxing-cpp: URI recuperada exatamente igual à de entrada.
- Chrome: imagem carregada, MFA confirmado com conta sintética, QR removido após confirmação, painel bloqueado, operador recusado e configuração sem transbordamento em celular; sem erros de JavaScript.
- Primeiro teste Chrome foi bloqueado pelo sandbox de rede; repetido com permissão de acesso ao localhost e aprovado, sem alterar o aplicativo.
- Desktop/VPS saudáveis, versão 0.2.6-beta.2. Imagem `sha256:77a6bc374108488e7540c43eabaaadfb68a5fda7d10fd45fdd97d2e70e59806d`.
- Contêiner anterior preservado no VPS; outros contêineres não alterados. Evidências: `/opt/sgc-codex-20260925/evidence/stage9-owner-qr-20261005`.
- Backup VPS anterior à atualização concluído. Dump local gerado antes da atualização e validado; primeiro destino de cópia apontava para a raiz errada, corrigido para backups/operacional dentro do repositório. SHA-256 `35AA95AA264713E331B86120584D64C8E37B7C80980552033744D8704D903CE4`.

Não foi alterada a senha ou a chave real de rodrigo; configuração pessoal do autenticador permanece necessária. Não simulamos instalação nos aplicativos reais do telefone: compatibilidade baseada no padrão e documentação oficial, com leitura independente do QR testada.

## Fontes

- https://support.google.com/accounts/answer/1066447
- https://support.microsoft.com/en-us/account-billing/add-personal-microsoft-accounts-to-the-microsoft-authenticator-app-92544b53-7706-4581-a142-30344a2a2a57
- https://pypi.org/project/qrcode/

## Cópia externa

Backup final da versão com QR em verificação/envio. Recibo será acrescentado após confirmação.
