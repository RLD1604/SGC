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
 {'id':'expired-session','evidence':'Sessão sintética expirou por inatividade; API recusou acesso com 401. Automação supôs cookies válidos e não refez login.','expected':'erro_do_teste'},
 {'id':'write-conflict','evidence':'Duas abas editaram a mesma revisão. A escrita obsoleta recebeu 409; dado vencedor ficou intacto e rascunho concorrente foi baixado.','expected':'protecao_esperada'},
 {'id':'log-document-state','evidence':'Administrador autorizado lia registro conferido, mas log de visualização recebeu 404: consulta de autorização omitia o estado e usava draft. Correção passou estado real; log aceito e rascunho privado de outro operador continuou negado.','expected':'erro_do_app'},
 {'id':'mfa-early-submit','evidence':'Formulário MFA exibia botão habilitado antes de instalar handler assíncrono. Clique antecipado não gerava verificação. Botão agora permanece desabilitado até terminar inicialização.','expected':'erro_do_app'},
 {'id':'wrong-admin-route','evidence':'Reenvio do registro chegou ao banco em review. O administrador tinha sido redirecionado ao acervo durante complemento. Teste recarregou acervo e esperou botão de conferência nessa rota, sem abrir o registro.','expected':'erro_do_teste'}]}
criteria={'erro_do_app':'Defeito na implementação do sistema','erro_do_teste':'Defeito ou expectativa incorreta da automação','protecao_esperada':'Bloqueio correto de segurança ou concorrência','informacao_insuficiente':'Evidência insuficiente para determinar a origem'}
questions={item['id']:{'type':'choice','instructions':f"Classifique somente a origem do incidente incidents[{i}] pelas evidências. Não use expected como prova. Não avalie textos editoriais nem autorize publicação.",'criteria':criteria} for i,item in enumerate(state['incidents'])}
transmitted={'incidents':[{k:v for k,v in x.items() if k!='expected'} for x in state['incidents']]}
try:response=call_jev(key,DEFAULT_MODEL,transmitted,questions,45)
except Exception:raise SystemExit('Falha na classificação TypeSafe; nenhuma credencial foi registrada')
report={'at':datetime.now(timezone.utc).isoformat(),'model':response['model'],'usage':response['usage'],'stateSha256':hashlib.sha256(json.dumps(transmitted,sort_keys=True).encode()).hexdigest(),'answers':response['answers'],'humanComparison':{item['id']:response['answers'][item['id']]['choice']==item['expected'] for item in state['incidents']},'scope':'Somente incidentes sintéticos, classificação consultiva; gates funcionais independentes'}
out=root/'qa/results/maverick/jev-incidents.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'model':report['model'],'usage':report['usage'],'agreements':sum(report['humanComparison'].values()),'incidents':len(state['incidents']),'report':str(out)},ensure_ascii=True))
