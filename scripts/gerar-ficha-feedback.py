from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader
import pypdfium2 as pdfium

root = Path(__file__).resolve().parents[1]
out = root / 'docs/manuais/ficha-feedback-beta.pdf'
styles = getSampleStyleSheet()
styles['BodyText'].fontSize = 10
styles['BodyText'].leading = 14
story = [Paragraph('SGC - Como foi usar o sistema?', styles['Title']),
         Paragraph('Sua opinião nos ajuda a melhorar. Leva cerca de 3 minutos. Não precisa usar termos técnicos nem testar tudo: marque o que você realmente tentou.', styles['BodyText']), Spacer(1, 14),
         Paragraph('Nome: _______________________  Data: __________<br/>Perfil: Administrador / Operador<br/>Usou: Celular / Computador  |  Navegador, se souber: ______________', styles['BodyText']), Spacer(1, 14)]
rows = [[Paragraph(x, styles['BodyText']) for x in ['O que você tentou?', 'Fácil', 'Consegui, mas foi difícil', 'Não consegui', 'Não testei']]]
for task in ['Ativar a conta e configurar o autenticador', 'Entrar com senha e código do autenticador', 'Encontrar a função que precisava', 'Criar, salvar e editar um registro', 'Adicionar e conferir uma foto', 'Montar e visualizar um informe', 'Revisar ou aprovar, se for Administrador']:
    rows.append([Paragraph(task, styles['BodyText']), '[  ]', '[  ]', '[  ]', '[  ]'])
table = Table(rows, colWidths=[214, 44, 94, 71, 64])
table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), .4, colors.HexColor('#cccccc')), ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#eeeeee')), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,1), (-1,-1), 'CENTER'), ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8)]))
story.extend([table, Spacer(1, 16)])
for text in ['<b>1. Teve algum erro, lentidão ou algo que não salvou?</b> Não / Sim<br/>Se sim: o que tentou fazer, o que aconteceu e quando? Uma frase basta.<br/>_________________________________________________________________', '<b>2. O que ficou confuso ou você mudaria primeiro?</b><br/>_________________________________________________________________', '<b>3. Usaria o sistema no dia a dia?</b> Sim / Com ajustes / Não']:
    story.extend([Paragraph(text, styles['BodyText']), Spacer(1, 12)])
story.append(Paragraph('Obrigado! Devolva esta ficha a Rodrigo preenchida, ou envie as respostas por mensagem. Se algo impediu o trabalho, avise na hora. Não envie senha, token, QR Code ou código do autenticador. Em capturas de tela, esconda dados pessoais.', styles['BodyText']))
SimpleDocTemplate(str(out), pagesize=A4, leftMargin=45, rightMargin=45, topMargin=35, bottomMargin=35).build(story)
assert len(PdfReader(out).pages) == 1, 'A ficha deve ter uma página'
preview = root / 'qa/results/feedback-beta'
preview.mkdir(parents=True, exist_ok=True)
pdfium.PdfDocument(str(out))[0].render(scale=1.5).to_pil().save(preview / 'ficha.png')
print('Ficha gerada e verificada: 1 página')
