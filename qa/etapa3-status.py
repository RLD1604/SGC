"""Focused server-side P2-06 checks; execute inside the application image/venv."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, '/site')
import server


def state(status='draft', title='Assunto válido', text='Texto válido'):
    return {'records': [{'id':'r-1','title':title,'text':text,'status':status,
                         'revision':1,'history':[],'photos':[]}],
            'editions':[{'id':'e-1','title':'Informe','period':'Setembro',
                         'version':1,'blocks':[],'cover':'/images/jardim.jpg'}],
            'publications':[]}


before=state()
for target in ('review','ready'):
    candidate=copy.deepcopy(before)
    candidate['records'][0]['status']=target
    server.validate(candidate)
    server.validate_status_transitions(before,candidate)

for field, value in [('title','  '),('text','<p>&nbsp;</p>')]:
    candidate=state()
    candidate['records'][0].update(status='ready', **{field:value})
    try:
        server.validate_status_transitions(before,candidate)
    except ValueError as error:
        assert 'obrigatório' in str(error)
    else:
        raise AssertionError('Aprovação vazia foi aceita: '+field)

# An unchanged draft remains a permitted incomplete draft.
draft=state(title='',text='')
server.validate(draft)
server.validate_status_transitions(draft,copy.deepcopy(draft))
print('PASS: transições P2-06 são bloqueadas no servidor sem mutar a entrada anterior')
