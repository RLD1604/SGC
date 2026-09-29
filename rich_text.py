"""Server-side allowlist for editorial HTML, matching the browser's content model."""
import re
import bleach
from bleach.css_sanitizer import CSSSanitizer

TAGS='p br strong b i em u s strike sub sup ul ol li h1 h2 h3 h4 h5 h6 blockquote table caption colgroup col thead tbody tfoot tr th td a span div hr pre'.split()
STYLES='color background-color font-family font-size font-weight font-style text-decoration text-align line-height margin-left margin-right margin-top margin-bottom text-indent padding padding-left padding-right padding-top padding-bottom border border-width border-style border-color border-collapse width height vertical-align list-style-type'.split()

def clean_html(value):
    if not isinstance(value,str) or len(value)>1000000:
        raise ValueError('Texto formatado inválido ou muito extenso.')
    value=re.sub(r'<(script|style|iframe|object|svg|math)\b[^>]*>.*?</\1\s*>','',value,flags=re.I|re.S)
    return bleach.clean(value,tags=TAGS,attributes={'*':['style'],'a':['href'],'td':['colspan','rowspan'],'th':['colspan','rowspan'],'ol':['start']},protocols=['http','https','mailto','tel'],css_sanitizer=CSSSanitizer(allowed_css_properties=STYLES),strip=True,strip_comments=True)

def sanitize_documents(data,cur):
    for record in data['records']:
        for key in ('textHtml','feedbackHtml'):
            if key in record:
                record[key]=clean_html(record[key])
    for table in ('editions','publications'):
        for edition in data[table]:
            if table=='publications':
                cur.execute('SELECT document FROM publications WHERE id=%s',(edition['id'],))
                previous=cur.fetchone()
                if previous:
                    # Preserve historical documents byte-for-byte under the existing contract.
                    continue
            for block in edition['blocks']:
                block['body']=clean_html(block['body'])
