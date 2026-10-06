from pathlib import Path
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image
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
styles['Heading2'].fontSize=15
styles['Heading2'].leading=19
for profile in ('operador','administrador'):
    source=root/'docs'/f'manual-{profile}.md'
    pdf=out/f'manual-{profile}.pdf'
    story=[]
    for block in source.read_text(encoding='utf-8').strip().split('\n\n'):
        if block.startswith('# '):
            story.append(Paragraph(block[2:],styles['Title']))
        elif block.startswith('## '):
            story.append(Paragraph(block[3:],styles['Heading2']))
        else:
            block=re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',block)
            block=re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',block)
            story.append(Paragraph(block.replace('\n','<br/>'),styles['BodyText']))
        story.append(Spacer(1,12))
    screens=[('01-acesso','Acesso e convite','1. Abra a URL do SGC. 2. Entre com identificador e senha. 3. Para o primeiro acesso, expanda a opção de ativação e use o convite nominal. 4. Para perda de acesso, use a solicitação ao dono. Nunca compartilhe o token.'),('02-autenticador','Código do autenticador','1. Abra o Google ou Microsoft Authenticator. 2. Localize sua conta SGC. 3. Digite o código de seis dígitos vigente. Esta imagem mostra uma reentrada; o QR é apresentado na configuração inicial. O QR pessoal deve permanecer privado.'),('03-visao-geral','Área de trabalho','1. Confira seu nome e perfil no rodapé do menu. 2. Use Visão geral para pendências. 3. Abra Registros para consultar itens e Informes para trabalhar na edição. 4. Use Sair ao terminar.'),('04-novo-registro','Preenchimento do registro','1. Escolha o tipo de registro. 2. Preencha os campos apresentados para esse tipo. 3. Descreva o fato e a providência com clareza. 4. Revise fotos e dados antes de salvar. Campos variam conforme a categoria; role a tela para ver as ações no final.'),('05-informes','Lista de informes','1. Localize a edição pelo título e período. 2. Confira seu estado. 3. Abra a edição para continuar o trabalho ou consultar a publicação. Alterações dependem do perfil e do estado exibido.'),('06-editor','Prévia do informe','1. Confira título, período e sumário. 2. Revise a relação entre texto e imagens. 3. Use Ver como celular para conferir a leitura móvel. 4. Baixar rascunho marcado gera uma cópia para revisão; a publicação oficial segue o fluxo de aprovação.')]
    for name,title,steps in screens:
        image_path=out/'telas'/f'{name}.png'
        if not image_path.exists(): continue
        story.extend([PageBreak(),Paragraph(title,styles['Heading2']),Paragraph('Captura real do ambiente de testes com dados fictícios. Versão 0.2.7-beta.3.',styles['BodyText']),Spacer(1,12)])
        im=Image(str(image_path)); ratio=min(500/im.imageWidth,490/im.imageHeight);im.drawWidth=im.imageWidth*ratio;im.drawHeight=im.imageHeight*ratio
        story.extend([im,Spacer(1,14),Paragraph(steps,styles['BodyText'])])
    def footer(canvas,doc):
        canvas.setFont('Helvetica',9);canvas.drawString(45,25,'SGC | Manual '+profile+' | Beta 0.2.7-beta.3');canvas.drawRightString(550,25,str(doc.page))
    SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=45,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)
    doc=pdfium.PdfDocument(str(pdf))
    assert len(doc)>=2, f'{profile}: manual unexpectedly short'
    doc[0].render(scale=1.2).to_pil().save(out/f'manual-{profile}-preview.png')
    renders=root/'qa/results/manuais-ilustrados'/profile;renders.mkdir(parents=True,exist_ok=True)
    for i,page in enumerate(doc): page.render(scale=1).to_pil().save(renders/f'page-{i+1}.png')
    assert 'SGC' in PdfReader(pdf).pages[0].extract_text()
    print(f'{profile}: {len(doc)} pages generated and text verified')
