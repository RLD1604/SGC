from pathlib import Path
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import pypdfium2 as pdfium
from pypdf import PdfReader

root=Path(__file__).resolve().parents[1]
out=root/'docs'/'manuais'
out.mkdir(exist_ok=True)
styles=getSampleStyleSheet()
styles['BodyText'].fontSize=11
styles['BodyText'].leading=16
for profile in ('operador','administrador'):
    source=root/'docs'/f'manual-{profile}.md'
    pdf=out/f'manual-{profile}.pdf'
    story=[]
    for block in source.read_text(encoding='utf-8').strip().split('\n\n'):
        if block.startswith('# '):
            story.append(Paragraph(block[2:],styles['Title']))
        else:
            block=re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',block)
            block=re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',block)
            story.append(Paragraph(block.replace('\n','<br/>'),styles['BodyText']))
        story.append(Spacer(1,12))
    SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=45,bottomMargin=45).build(story)
    doc=pdfium.PdfDocument(str(pdf))
    assert len(doc)==1, f'{profile}: unexpected page count'
    doc[0].render(scale=1.2).to_pil().save(out/f'manual-{profile}-preview.png')
    assert 'SGC' in PdfReader(pdf).pages[0].extract_text()
    print(f'{profile}: PDF generated and text verified')
