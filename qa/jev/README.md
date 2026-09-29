# QA editorial do SGC com Jev

Esta bateria complementa os testes funcionais existentes. Playwright e os testes de API continuam responsáveis por campos, persistência, banco, fotos, permissões e navegação. Jev avalia a qualidade do texto sintético campo a campo e bloco a bloco, sem publicar nem alterar dados do SGC.

## Execução segura

Validação local, sem rede e sem chave:

```powershell
wsl -d Ubuntu -- python3 /mnt/d/01_Claude-Desktop/02_Projeto-Relatorio-SQA/prototipo-condominio/qa/jev/run_jev_qa.py --dry-run
```

Execução real: abra o Ubuntu/WSL, defina `TYPESAFE_API_KEY` somente naquela
sessão e execute:

```bash
cd /mnt/d/01_Claude-Desktop/02_Projeto-Relatorio-SQA
python3 prototipo-condominio/qa/jev/run_jev_qa.py
```

Calibração repetida com três casos sintéticos rotulados:

```bash
python3 prototipo-condominio/qa/jev/calibrate_jev.py --runs 3
```

O relatório de calibração é salvo em `qa/results/jev/calibration.json`.

O relatório auditável é salvo em `qa/results/jev/report.json`. Ele registra o modelo efetivamente usado, uso informado pela API, respostas tipadas, probabilidades, confiança e o SHA-256 do estado avaliado. A chave não é salva.

O padrão fixa `jev-1.13.0`, evitando que uma mudança silenciosa no alias altere os limites calibrados. Cada grupo é enviado em uma chamada: 18 perguntas para campos e 14 para os três blocos da fixture. Perguntas do mesmo grupo são avaliadas em paralelo contra o mesmo estado.

## Critérios iniciais

- `aprovado`: decisões aprovadas com confiança mínima de 0,65 e qualidade 2/3;
- `revisao_humana`: decisão incerta, pedido de revisão ou qualidade abaixo de 2;
- `reprovado`: risco editorial/privacidade de pelo menos 0,65 ou reprovação com confiança mínima de 0,65.

Esses limites são conservadores e precisam ser calibrados com exemplos rotulados em português antes de impedir uma publicação real. Jev nunca publica nem corrige conteúdo automaticamente nesta bateria.

## Dados reais

`fixtures.json` contém apenas conteúdo sintético. Antes de usar `--input` com dados de clientes, é necessário aprovar expressamente o envio desses textos ao TypeSafe e definir uma política de anonimização e retenção.
