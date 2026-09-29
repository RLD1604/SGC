"""Fetch pinned official npm packages; verify SHA-512 before installing local assets."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile
import urllib.request

DEST=Path(__file__).resolve().parents[1] / 'public/vendor/tinymce'
PACKAGES=[
 ('https://registry.npmjs.org/tinymce/-/tinymce-8.9.1.tgz','5KrFiuKri2sPQW3ERWodsx3R0RZiw0cJJDr61qaMQiXO1ir3ZYaf6gVVaao+T29spZ9L9waaeE/co8Ov2Rn3vQ==','core'),
 ('https://registry.npmjs.org/tinymce-i18n/-/tinymce-i18n-26.9.7.tgz','ZLmWShvol2xL9UfpI+rLuimU6CiDg7XryJU3m/PS6hc/Y7KJNghtrMnhX3b1F9dVD8ybD3iyIIFLvCJRmlE4fA==','language')
]
for url,integrity,kind in PACKAGES:
    data=urllib.request.urlopen(url,timeout=60).read()
    assert base64.b64encode(hashlib.sha512(data).digest()).decode()==integrity,'Package integrity mismatch'
    count=0
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        for item in archive:
            if not item.isfile() or not item.name.startswith('package/'):
                continue
            relative=item.name.removeprefix('package/')
            if kind=='language':
                if relative not in ('langs8/pt-BR.js','LICENSE','LICENSE.txt','license.txt','LICENSE.md','package.json'):
                    continue
                print('Language package asset:',relative)
                relative='langs/'+relative.split('/')[-1] if relative.endswith('.js') else 'LANGUAGE-PACKAGE.json' if relative=='package.json' else 'LANGUAGE-LICENSE.txt'
            elif not (relative.endswith(('.min.js','.css','.woff','.woff2','.svg')) or relative.startswith('plugins/help/js/') or relative.lower() in ('license','license.txt','license.md','package.json')):
                continue
            target=(DEST / relative).resolve()
            assert target.is_relative_to(DEST.resolve()),'Invalid package path'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.extractfile(item).read())
            count+=1
    print(kind, count,'verified assets installed')
