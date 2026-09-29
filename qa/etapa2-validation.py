"""Focused Etapa 2 validation checks; run in the application image or QA venv."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, '/site')
import server


def valid_state():
    return {
        'records': [{'id': 'r-1', 'title': 'Registro válido', 'text': 'Texto válido',
                     'category': 'Serviço', 'date': '2026-09-24', 'who': 'Equipe',
                     'progress': 'Concluído', 'status': 'ready', 'revision': 1,
                     'history': [{'at': '2026-09-24T12:00:00.000Z', 'text': 'Conferido'}],
                     'photos': []}],
        'editions': [{'id': 'e-1', 'title': 'Informe válido', 'period': 'Setembro de 2026',
                      'version': 1, 'cover': '/images/jardim.jpg', 'blocks': []}],
        'publications': []
    }


def rejected(name, change, fragment):
    state = valid_state()
    change(state)
    try:
        server.validate(state)
    except ValueError as error:
        assert fragment in str(error), (name, str(error))
        return
    raise AssertionError(name + ' foi aceito')


server.validate(valid_state())
rejected('data impossível', lambda s: s['records'][0].update(date='2026-02-30'), 'data informada não existe')
rejected('categoria inválida', lambda s: s['records'][0].update(category='Inexistente'), 'categoria')
rejected('andamento inválido', lambda s: s['records'][0].update(progress='Inexistente'), 'andamento')
rejected('histórico ambíguo', lambda s: s['records'][0].update(history={}), 'histórico')
rejected('revisão inválida', lambda s: s['records'][0].update(revision='1'), 'revisão')
rejected('informe sem período', lambda s: s['editions'][0].update(period='  '), 'período')
rejected('bloco sem tipo', lambda s: s['editions'][0].update(blocks=[{'id':'b-1','type':[],'title':'Título','body':'Texto'}]), 'tipo')
rejected('pronto sem texto', lambda s: s['records'][0].update(text='   '), 'obrigatório')

# Rascunho ainda pode permanecer incompleto, mas não com tipos corrompidos.
draft = valid_state()
draft['records'][0].update(title='', text='', status='draft', history=[])
server.validate(draft)

print('PASS: validação reutilizável da Etapa 2')
