# Componentes de terceiros

## TinyMCE 8.9.1

- Repositório: https://github.com/tinymce/tinymce
- 16.290 estrelas consultadas pela API do GitHub em 10/09/2026; o número varia.
- Pacote oficial npm, versão fixada e SHA-512 verificado por `scripts/vendor-editor.py`.
- Licença do componente: GPL-2.0-or-later; texto distribuído em `public/vendor/tinymce/license.md`.
- Configuração local `license_key: 'gpl'`. Nenhum plugin premium, serviço Tiny Cloud ou recurso pago ativado.
- Tradução: `tinymce-i18n` 26.9.7, arquivo `langs8/pt-BR.js`, pacote npm com integridade verificada. O pacote distingue ferramentas/ajustes próprios sob MIT dos arquivos de idioma da distribuição TinyMCE, sujeitos aos termos da Tiny. O texto completo acompanha a entrega em `public/vendor/tinymce/LANGUAGE-LICENSE.txt`.

Esta instalação é para o uso interno do condomínio. Uma futura distribuição do software deve observar as obrigações da licença do editor, incluindo disponibilização de fontes quando aplicável, ou adotar uma licença comercial compatível. Esta nota não altera automaticamente a licença dos arquivos antigos do projeto.

O TinyMCE é um editor HTML com interface de processador de textos. Importação/exportação nativa DOCX, revisão colaborativa com controle de alterações e paginação idêntica ao Word não estão incluídas nesta entrega.

## Filerobot Image Editor 4.8.1

- Repositório: https://github.com/scaleflex/filerobot-image-editor
- Distribuição fixa: https://scaleflex.cloudimg.io/v7/plugins/filerobot-image-editor/4.8.1/filerobot-image-editor.min.js
- SHA-256: `6fcd7c93ecfca5e31f82c1b0f999ca55815af97763028d3fe822479d36bf2b2c`.
- Licença MIT incluída em `public/vendor/filerobot/LICENSE`; avisos das dependências estão preservados no bundle oficial.
- Biblioteca servida pelo próprio app e carregada somente ao abrir o editor. Traduções locais em português; nenhuma conta Filerobot/Cloudimage necessária. Teste no navegador verifica ausência de solicitações externas.
