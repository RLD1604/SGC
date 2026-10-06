"""Classify synthetic QA incidents; never sends credentials or editorial data."""
import json,hashlib,sys
from pathlib import Path
from datetime import datetime,timezone
from run_jev_qa import call_jev,DEFAULT_MODEL
root=Path(__file__).resolve().parents[2]
keyfile=next((p for p in (root/'chave.txt',root.parent/'chave.txt') if p.is_file()),None)
if not keyfile:raise SystemExit('Chave TypeSafe local indisponível')
key=keyfile.read_text(encoding='utf-8-sig').strip()
if key.startswith('TYPESAFE_API_KEY='):key=key.split('=',1)[1].strip().strip(chr(34)).strip(chr(39))
state={'incidents':[
 {'id':'no-login-quota','evidence':'Login público executava Argon2 sem limite persistente. Nova quota bloqueia excesso antes do hash e preserva contagem entre workers.','expected':'erro_do_app'},
 {'id':'shared-proxy-bucket','evidence':'Primeira candidata usava endereço do proxy para todos clientes. Revisão exigiu peer confiável explícito e prova de descarte de cabeçalho falsificado, agora aprovados.','expected':'erro_do_app'},
 {'id':'missing-qa-key','evidence':'Runner sintético omitiu chave requerida. Login recusou com 503 antes de criar sessão. Ao fornecer chave sintética a proteção passou.','expected':'erro_do_teste'},
 {'id':'invalid-edition-fixture','evidence':'Fixture SQL de publicação omitia campos obrigatórios da edição. PATCH legítimo encontrou edição inválida e retornou 400. Corrigir fixture fez controle positivo passar, sem alterar aplicativo.','expected':'erro_do_teste'}]}

criteria={'erro_do_app':'Defeito na implementação do sistema','erro_do_teste':'Defeito ou expectativa incorreta da automação','protecao_esperada':'Bloqueio correto de segurança ou concorrência','informacao_insuficiente':'Evidência insuficiente para determinar a origem'}
questions={item['id']:{'type':'choice','instructions':f"Classifique somente a origem do incidente incidents[{i}] pelas evidências. Não use expected como prova. Não avalie textos editoriais nem autorize publicação.",'criteria':criteria} for i,item in enumerate(state['incidents'])}
transmitted={'incidents':[{k:v for k,v in x.items() if k!='expected'} for x in state['incidents']]}
try:response=call_jev(key,DEFAULT_MODEL,transmitted,questions,45)
except Exception:raise SystemExit('Falha na classificação TypeSafe; nenhuma credencial foi registrada')
report={'at':datetime.now(timezone.utc).isoformat(),'model':response['model'],'usage':response['usage'],'stateSha256':hashlib.sha256(json.dumps(transmitted,sort_keys=True).encode()).hexdigest(),'answers':response['answers'],'humanComparison':{item['id']:response['answers'][item['id']]['choice']==item['expected'] for item in state['incidents']},'scope':'Somente incidentes sintéticos, classificação consultiva; gates funcionais independentes'}
out=root/'qa/results/pre-entrega-20261006/jev-incidents.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'model':report['model'],'usage':report['usage'],'agreements':sum(report['humanComparison'].values()),'incidents':len(state['incidents']),'report':str(out)},ensure_ascii=True))
